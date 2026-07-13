"""Schema-only MCP capture and canonical sanitized JSON artifacts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from mcp import types

from trading_bot.capabilities.models import (
    CapabilityEvidence,
    CapabilityManifest,
    CapabilityRecord,
    EvidenceLevel,
    OperationKind,
    validated_manifest_copy,
)
from trading_bot.capabilities.sanitization import (
    candidate_name_has_unsafe_characters as _candidate_name_has_unsafe_characters,
)
from trading_bot.capabilities.sanitization import (
    decoded_candidates as _decoded_candidates,
)
from trading_bot.capabilities.sanitization import (
    name_is_sensitive as _name_is_sensitive,
)
from trading_bot.capabilities.sanitization import (
    segments_have_sensitive_value_pair as _segments_have_sensitive_value_pair,
)
from trading_bot.capabilities.sanitization import (
    text_contains_sensitive_material,
)
from trading_bot.clock import require_utc
from trading_bot.domain import AssetClass

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

_PROVIDER = "robinhood-trading"
_TOOL_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._~-]{0,127})?\Z")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
_JSON_SCHEMA_TYPES = frozenset(
    {"array", "boolean", "integer", "null", "number", "object", "string"}
)
_JSON_SCHEMA_FORMATS = frozenset(
    {
        "date",
        "date-time",
        "duration",
        "email",
        "hostname",
        "idn-email",
        "idn-hostname",
        "ipv4",
        "ipv6",
        "iri",
        "iri-reference",
        "json-pointer",
        "password",
        "regex",
        "relative-json-pointer",
        "time",
        "uri",
        "uri-reference",
        "uri-template",
        "uuid",
    }
)
_LOCAL_JSON_POINTER = re.compile(r"#(?:/(?:[^~/%]|~[01]|%[0-9A-Fa-f]{2})*)*\Z")
_SCHEMA_MAPPING_KEYS = frozenset({"$defs", "definitions", "dependentSchemas", "properties"})
_SCHEMA_LIST_KEYS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
_SCHEMA_CHILD_KEYS = frozenset(
    {
        "additionalProperties",
        "contains",
        "else",
        "if",
        "items",
        "not",
        "propertyNames",
        "then",
        "unevaluatedProperties",
    }
)
_SCHEMA_BOOLEAN_KEYS = frozenset({"deprecated", "nullable", "readOnly", "uniqueItems", "writeOnly"})
_MAX_TOOLS_LIST_PAGES = 32
_TOOLS_LIST_PAGE_TIMEOUT_SECONDS = 10.0
_MAX_LOCAL_JSON_POINTER_LENGTH = 65_536

_REVIEWED_TOOLS: dict[str, tuple[AssetClass, OperationKind]] = {
    "cancel_equity_order": (AssetClass.EQUITY, OperationKind.CANCEL),
    "get_equity_fundamentals": (AssetClass.EQUITY, OperationKind.READ),
    "get_equity_historicals": (AssetClass.EQUITY, OperationKind.READ),
    "get_equity_orders": (AssetClass.EQUITY, OperationKind.READ),
    "get_equity_positions": (AssetClass.EQUITY, OperationKind.READ),
    "get_equity_quotes": (AssetClass.EQUITY, OperationKind.READ),
    "get_equity_technical_indicators": (AssetClass.EQUITY, OperationKind.READ),
    "get_equity_tradability": (AssetClass.EQUITY, OperationKind.READ),
    "place_equity_order": (AssetClass.EQUITY, OperationKind.PLACE),
    "review_equity_order": (AssetClass.EQUITY, OperationKind.REVIEW),
}


class CapabilitySnapshotError(ValueError):
    """Base error for a rejected schema-only MCP snapshot."""


class UnsafeCapabilitySnapshot(CapabilitySnapshotError):
    """Raised when selected schema fields contain sensitive material."""


class DuplicateToolNameError(CapabilitySnapshotError):
    """Raised when tools/list declares the same tool name more than once."""


class PaginationCycleError(CapabilitySnapshotError):
    """Raised when tools/list repeats a pagination cursor."""


class ToolsListSession(Protocol):
    """The only MCP session capability accepted by schema discovery."""

    async def list_tools(
        self,
        cursor: str | None = None,
        *,
        params: types.PaginatedRequestParams | None = None,
    ) -> types.ListToolsResult: ...


@dataclass(frozen=True, slots=True)
class SanitizedToolSchema:
    """Only the four allowed MCP tool fields plus their canonical digest."""

    name: str
    description: str | None
    _input_schema_json: str
    _output_schema_json: str | None
    schema_sha256: str

    def __post_init__(self) -> None:
        if type(self.name) is not str or _TOOL_NAME.fullmatch(self.name) is None:
            raise CapabilitySnapshotError("sanitized tool name is invalid")
        if self.description is not None and type(self.description) is not str:
            raise CapabilitySnapshotError("sanitized tool description is invalid")
        input_schema = _decode_schema_object(self._input_schema_json)
        output_schema = (
            None
            if self._output_schema_json is None
            else _decode_schema_object(self._output_schema_json)
        )
        selected: dict[str, JsonValue] = {
            "name": self.name,
            "description": self.description,
            "inputSchema": input_schema,
            "outputSchema": output_schema,
        }
        _scan_sensitive(selected)
        expected_digest = canonical_sha256(
            {
                "inputSchema": input_schema,
                "outputSchema": output_schema,
            }
        )
        if (
            type(self.schema_sha256) is not str
            or _SHA256_HEX.fullmatch(self.schema_sha256) is None
            or self.schema_sha256 != expected_digest
        ):
            raise CapabilitySnapshotError("sanitized tool digest is invalid")

    @property
    def input_schema(self) -> dict[str, JsonValue]:
        """Return a detached input-schema view."""
        validated = _validated_tool_copy(self)
        return _decode_schema_object(validated._input_schema_json)

    @property
    def output_schema(self) -> dict[str, JsonValue] | None:
        """Return a detached output-schema view, preserving explicit null."""
        validated = _validated_tool_copy(self)
        if validated._output_schema_json is None:
            return None
        return _decode_schema_object(validated._output_schema_json)

    def as_json(self) -> dict[str, JsonValue]:
        """Return a detached exact-schema representation suitable for JSON."""
        return _validated_tool_as_json(_validated_tool_copy(self))


@dataclass(frozen=True, slots=True)
class ToolsListSnapshot:
    """A sanitized raw-schema artifact and its derived capability manifest."""

    provider: str
    observed_at: datetime
    tools: tuple[SanitizedToolSchema, ...]
    manifest: CapabilityManifest

    def __post_init__(self) -> None:
        if type(self.provider) is not str or self.provider != _PROVIDER:
            raise CapabilitySnapshotError("snapshot provider is invalid")
        canonical_timestamp: datetime | None = None
        if type(self.observed_at) is datetime:
            with suppress(Exception):
                canonical_timestamp = require_utc(self.observed_at)
        if canonical_timestamp is None:
            raise CapabilitySnapshotError(
                "snapshot timestamp must be an exact aware UTC datetime"
            ) from None
        object.__setattr__(self, "observed_at", canonical_timestamp)
        if type(self.tools) is not tuple or any(
            type(item) is not SanitizedToolSchema for item in self.tools
        ):
            raise CapabilitySnapshotError("snapshot tools must be immutable sanitized values")
        validated_tools = tuple(_validated_tool_copy(item) for item in self.tools)
        names = tuple(item.name for item in validated_tools)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise CapabilitySnapshotError("snapshot tools must be unique and deterministic")
        if type(self.manifest) is not CapabilityManifest:
            raise CapabilitySnapshotError("snapshot manifest is invalid")
        validated_manifest: CapabilityManifest | None = None
        try:
            validated_manifest = validated_manifest_copy(self.manifest)
        except MemoryError:
            raise
        except Exception:
            validated_manifest = None
        if validated_manifest is None:
            raise CapabilitySnapshotError("snapshot manifest is invalid") from None
        expected = CapabilityManifest(
            records=tuple(_record_from_schema(item, self.observed_at) for item in validated_tools)
        )
        if validated_manifest != expected:
            raise CapabilitySnapshotError("snapshot manifest does not match captured schemas")
        object.__setattr__(self, "tools", validated_tools)
        object.__setattr__(self, "manifest", validated_manifest)

    def as_json(self) -> dict[str, JsonValue]:
        """Render the deterministic committed artifact without SDK extras."""
        return _validated_snapshot_as_json(_validated_snapshot_copy(self))


def canonical_sha256(value: JsonValue) -> str:
    """Hash canonical JSON, sorting object keys while retaining array order."""
    _require_json_value(value)
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


async def capture_tools_list(
    session: ToolsListSession,
    *,
    observed_at: datetime | None = None,
) -> CapabilityManifest:
    """Capture declared schemas using tools/list and return evidence records only."""
    return (await capture_tools_snapshot(session, observed_at=observed_at)).manifest


async def capture_tools_snapshot(
    session: ToolsListSession,
    *,
    observed_at: datetime | None = None,
) -> ToolsListSnapshot:
    """Capture all tools/list pages without invoking any declared tool."""
    supplied_timestamp = observed_at if observed_at is not None else datetime.now(UTC)
    timestamp: datetime | None = None
    if type(supplied_timestamp) is datetime:
        with suppress(Exception):
            timestamp = require_utc(supplied_timestamp)
    if timestamp is None:
        raise CapabilitySnapshotError("observed_at must be an exact aware UTC datetime") from None

    captured: list[SanitizedToolSchema] = []
    names: set[str] = set()
    seen_cursors: set[str] = set()
    params: types.PaginatedRequestParams | None = None
    page_count = 0

    while True:
        result = await _request_tools_page(session, params)
        page_count += 1
        page_tools, cursor = _sanitize_tools_page(result)
        for declared in page_tools:
            if declared.name in names:
                raise DuplicateToolNameError("tools/list contains a duplicate tool name")
            names.add(declared.name)
            captured.append(declared)
        if cursor is None:
            break
        if not cursor or cursor in seen_cursors:
            raise PaginationCycleError("tools/list returned an invalid or repeated cursor")
        if page_count >= _MAX_TOOLS_LIST_PAGES:
            raise CapabilitySnapshotError("MCP tools/list pagination limit exceeded") from None
        seen_cursors.add(cursor)
        params = types.PaginatedRequestParams(cursor=cursor)

    tools = tuple(sorted(captured, key=lambda item: item.name))
    records = tuple(_record_from_schema(item, timestamp) for item in tools)
    return ToolsListSnapshot(
        provider=_PROVIDER,
        observed_at=timestamp,
        tools=tools,
        manifest=CapabilityManifest(records=records),
    )


async def _request_tools_page(
    session: ToolsListSession,
    params: types.PaginatedRequestParams | None,
) -> types.ListToolsResult:
    result: types.ListToolsResult | None = None
    failed = False
    try:
        async with asyncio.timeout(_TOOLS_LIST_PAGE_TIMEOUT_SECONDS):
            result = (
                await session.list_tools(params=params)
                if params is not None
                else await session.list_tools()
            )
    except Exception:
        failed = True
    if failed or type(result) is not types.ListToolsResult:
        raise CapabilitySnapshotError("MCP tools/list failed safely") from None
    return result


def _sanitize_tools_page(
    result: types.ListToolsResult,
) -> tuple[tuple[SanitizedToolSchema, ...], str | None]:
    sanitized: tuple[SanitizedToolSchema, ...] | None = None
    cursor: str | None = None
    failed = False
    try:
        raw_tools = result.tools
        raw_cursor = result.nextCursor
        if type(raw_tools) is not list or (raw_cursor is not None and type(raw_cursor) is not str):
            raise TypeError
        converted: list[SanitizedToolSchema] = []
        for declared in raw_tools:
            if type(declared) is not types.Tool:
                raise TypeError
            converted.append(_sanitize_tool(declared))
        sanitized = tuple(converted)
        cursor = raw_cursor
    except CapabilitySnapshotError:
        raise
    except Exception:
        failed = True
    if failed or sanitized is None:
        raise CapabilitySnapshotError("MCP tools/list failed safely") from None
    return sanitized, cursor


async def write_tools_snapshot(
    session: ToolsListSession,
    output: Path,
    *,
    observed_at: datetime | None = None,
) -> ToolsListSnapshot:
    """Validate a complete snapshot in memory, then write exactly one artifact."""
    if output.is_symlink():
        raise CapabilitySnapshotError("snapshot destination cannot be a symlink")
    snapshot = await capture_tools_snapshot(session, observed_at=observed_at)
    artifact = snapshot.as_json()
    payload = json.dumps(artifact, allow_nan=False, indent=2, sort_keys=True) + "\n"
    if output.is_symlink():
        raise CapabilitySnapshotError("snapshot destination cannot be a symlink")
    _atomic_private_write(output, payload)
    return snapshot


def _sanitize_tool(tool: types.Tool) -> SanitizedToolSchema:
    if _TOOL_NAME.fullmatch(tool.name) is None:
        raise CapabilitySnapshotError("tool name is not a sanitized MCP path segment")
    if tool.description is not None and type(tool.description) is not str:
        raise CapabilitySnapshotError("tool description must be a string or null")
    input_value = _copy_json(tool.inputSchema)
    output_value = _copy_json(tool.outputSchema)
    if type(input_value) is not dict or (
        output_value is not None and type(output_value) is not dict
    ):
        raise CapabilitySnapshotError("tool schemas must be JSON objects or null output")
    selected: dict[str, JsonValue] = {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": input_value,
        "outputSchema": output_value,
    }
    _scan_sensitive(selected)
    digest = canonical_sha256(
        {
            "inputSchema": input_value,
            "outputSchema": output_value,
        }
    )
    return SanitizedToolSchema(
        name=tool.name,
        description=tool.description,
        _input_schema_json=_encode_json(input_value),
        _output_schema_json=None if output_value is None else _encode_json(output_value),
        schema_sha256=digest,
    )


def _record_from_schema(tool: SanitizedToolSchema, observed_at: datetime) -> CapabilityRecord:
    reviewed = _REVIEWED_TOOLS.get(tool.name)
    asset_class, operation_kind = reviewed or (AssetClass.EQUITY, OperationKind.DISCOVER)
    locked_reason = (
        None if reviewed is not None else "tool name is not in the reviewed operation allowlist"
    )
    limitations: tuple[str, ...] = (
        "tools/list is unauthenticated schema evidence only; no tool was invoked",
    )
    if reviewed is None:
        limitations += ("asset class and operation safety remain unclassified",)
    return CapabilityRecord(
        provider=_PROVIDER,
        operation=tool.name,
        asset_class=asset_class,
        operation_kind=operation_kind,
        evidence=(
            CapabilityEvidence(
                level=EvidenceLevel.SCHEMA_DECLARED,
                source_uri=f"mcp://{_PROVIDER}/tools/{tool.name}",
                observed_at=observed_at,
                schema_sha256=tool.schema_sha256,
                authenticated=False,
                contains_account_data=False,
                notes=("sanitized MCP 1.28.1 tools/list declaration",),
            ),
        ),
        limitations=limitations,
        locked_reason=locked_reason,
    )


def _validated_tool_copy(value: object) -> SanitizedToolSchema:
    """Rebuild one exact stored tool before using any of its declared values."""
    validated: SanitizedToolSchema | None = None
    try:
        if type(value) is not SanitizedToolSchema:
            raise TypeError
        validated = SanitizedToolSchema(
            name=value.name,
            description=value.description,
            _input_schema_json=value._input_schema_json,
            _output_schema_json=value._output_schema_json,
            schema_sha256=value.schema_sha256,
        )
    except MemoryError:
        raise
    except Exception:
        validated = None
    if validated is None:
        raise CapabilitySnapshotError("snapshot tool is invalid") from None
    return validated


def _validated_snapshot_copy(value: object) -> ToolsListSnapshot:
    """Rebuild a complete exact snapshot before any public serialization."""
    validated: ToolsListSnapshot | None = None
    try:
        if type(value) is not ToolsListSnapshot:
            raise TypeError
        validated = ToolsListSnapshot(
            provider=value.provider,
            observed_at=value.observed_at,
            tools=value.tools,
            manifest=value.manifest,
        )
    except MemoryError:
        raise
    except Exception:
        validated = None
    if validated is None:
        raise CapabilitySnapshotError("snapshot is invalid") from None
    return validated


def _validated_tool_as_json(value: SanitizedToolSchema) -> dict[str, JsonValue]:
    input_schema = _decode_schema_object(value._input_schema_json)
    output_schema = (
        None
        if value._output_schema_json is None
        else _decode_schema_object(value._output_schema_json)
    )
    return {
        "name": value.name,
        "description": value.description,
        "inputSchema": _copy_json(input_schema),
        "outputSchema": _copy_json(output_schema),
        "schemaSha256": value.schema_sha256,
    }


def _validated_snapshot_as_json(value: ToolsListSnapshot) -> dict[str, JsonValue]:
    return {
        "provider": value.provider,
        "observedAt": value.observed_at.isoformat().replace("+00:00", "Z"),
        "method": "tools/list",
        "tools": [_validated_tool_as_json(item) for item in value.tools],
    }


def _copy_json(value: object) -> JsonValue:
    if value is None or type(value) in {bool, int, str}:
        return cast(JsonScalar, value)
    if type(value) is float:
        if not math.isfinite(value):
            raise CapabilitySnapshotError("schema contains a nonfinite number")
        return value
    if type(value) is list:
        list_value = cast(list[object], value)
        return [_copy_json(item) for item in list_value]
    if type(value) is dict:
        mapping = cast(dict[object, object], value)
        copied: dict[str, JsonValue] = {}
        for key, item in mapping.items():
            if type(key) is not str:
                raise CapabilitySnapshotError("schema object keys must be strings")
            copied[key] = _copy_json(item)
        return copied
    raise CapabilitySnapshotError("schema contains a non-JSON value")


def _encode_json(value: JsonValue) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
    )


def _decode_schema_object(value: str) -> dict[str, JsonValue]:
    decoded: object | None = None
    invalid = False
    try:
        if type(value) is not str:
            raise TypeError
        decoded = json.loads(
            value,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        if type(decoded) is not dict or _encode_json(decoded) != value:
            raise ValueError
    except Exception:
        invalid = True
    if invalid or type(decoded) is not dict:
        raise CapabilitySnapshotError("stored schema JSON is invalid") from None
    return decoded


def _unique_json_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, item in pairs:
        if key in result:
            raise ValueError
        result[key] = item
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError


def _atomic_private_write(output: Path, payload: str) -> None:
    descriptor = -1
    temporary: Path | None = None
    try:
        descriptor, raw_temporary = tempfile.mkstemp(
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
        )
        temporary = Path(raw_temporary)
        os.fchmod(descriptor, 0o600)
        stream = os.fdopen(descriptor, "w", encoding="utf-8", newline="")
        descriptor = -1
        with stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if output.is_symlink():
            raise CapabilitySnapshotError("snapshot destination cannot be a symlink")
        os.replace(temporary, output)
        temporary = None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _scan_sensitive(
    value: JsonValue,
    *,
    sensitive_property: bool = False,
) -> None:
    if type(value) is str:
        if text_contains_sensitive_material(value):
            raise UnsafeCapabilitySnapshot("capability snapshot contains sensitive material")
        return
    if type(value) is list:
        for item in value:
            _scan_sensitive(item, sensitive_property=sensitive_property)
        return
    if type(value) is not dict:
        return
    if sensitive_property:
        _validate_sensitive_schema(value)
    for key, item in value.items():
        if _candidate_name_has_unsafe_characters(key) or text_contains_sensitive_material(key):
            raise UnsafeCapabilitySnapshot("capability snapshot contains sensitive material")
        if sensitive_property and key in _SCHEMA_MAPPING_KEYS:
            schema_mapping = cast(dict[str, JsonValue], item)
            for schema_name, schema in schema_mapping.items():
                if _candidate_name_has_unsafe_characters(
                    schema_name
                ) or text_contains_sensitive_material(schema_name):
                    raise UnsafeCapabilitySnapshot(
                        "capability snapshot contains sensitive material"
                    )
                _scan_sensitive(schema, sensitive_property=True)
            continue
        if key == "properties" and type(item) is dict:
            for property_name, property_schema in item.items():
                if _candidate_name_has_unsafe_characters(
                    property_name
                ) or text_contains_sensitive_material(property_name):
                    raise UnsafeCapabilitySnapshot(
                        "capability snapshot contains sensitive material"
                    )
                sensitive_label = _name_is_sensitive(property_name)
                if (
                    sensitive_label
                    and type(property_schema) is not dict
                    and _contains_value(property_schema)
                ):
                    raise UnsafeCapabilitySnapshot(
                        "capability snapshot contains sensitive material"
                    )
                _scan_sensitive(
                    property_schema,
                    sensitive_property=sensitive_property or sensitive_label,
                )
            continue
        sensitive_schema_alias = _name_is_sensitive(key) and _looks_like_schema(item)
        if _name_is_sensitive(key) and not sensitive_schema_alias and _contains_value(item):
            raise UnsafeCapabilitySnapshot("capability snapshot contains sensitive material")
        _scan_sensitive(
            item,
            sensitive_property=sensitive_property or sensitive_schema_alias,
        )


def _validate_sensitive_schema(value: dict[str, JsonValue]) -> None:
    """Accept only recursively validated, declaration-only JSON Schema shapes."""
    for key, item in value.items():
        if key == "type":
            if not _schema_type_is_valid(item):
                raise UnsafeCapabilitySnapshot("sensitive schema declaration is invalid")
            continue
        if key == "format":
            if type(item) is not str or item not in _JSON_SCHEMA_FORMATS:
                raise UnsafeCapabilitySnapshot("sensitive schema declaration is invalid")
            continue
        if key == "$ref":
            if type(item) is not str or not _local_json_pointer_is_safe(item):
                raise UnsafeCapabilitySnapshot("sensitive schema declaration is invalid")
            continue
        if key in _SCHEMA_MAPPING_KEYS:
            if type(item) is not dict:
                raise UnsafeCapabilitySnapshot("sensitive schema declaration is invalid")
            for schema in item.values():
                _validate_schema_node(schema)
            continue
        if key in _SCHEMA_LIST_KEYS:
            if type(item) is not list or not item:
                raise UnsafeCapabilitySnapshot("sensitive schema declaration is invalid")
            for schema in item:
                _validate_schema_node(schema)
            continue
        if key in _SCHEMA_CHILD_KEYS:
            _validate_schema_node(item)
            continue
        if key in _SCHEMA_BOOLEAN_KEYS:
            if type(item) is not bool:
                raise UnsafeCapabilitySnapshot("sensitive schema declaration is invalid")
            continue
        if key == "required":
            if not _schema_required_is_valid(item, value.get("properties")):
                raise UnsafeCapabilitySnapshot("sensitive schema declaration is invalid")
            continue
        if _contains_value(item):
            raise UnsafeCapabilitySnapshot("sensitive schema properties cannot embed metadata")


def _schema_type_is_valid(value: JsonValue) -> bool:
    if type(value) is str:
        return value in _JSON_SCHEMA_TYPES
    if type(value) is not list or not value:
        return False
    return all(type(item) is str and item in _JSON_SCHEMA_TYPES for item in value) and len(
        value
    ) == len(set(value))


def _schema_required_is_valid(
    value: JsonValue,
    properties: JsonValue | None,
) -> bool:
    if type(value) is not list or type(properties) is not dict:
        return False
    return all(type(item) is str and item in properties for item in value) and len(value) == len(
        set(value)
    )


def _validate_schema_node(value: JsonValue) -> None:
    if type(value) is bool:
        return
    if type(value) is not dict:
        raise UnsafeCapabilitySnapshot("sensitive schema declaration is invalid")
    _validate_sensitive_schema(value)


def _local_json_pointer_is_safe(value: str) -> bool:
    segments = _decoded_local_pointer_segments(value)
    return segments is not None and not _segments_have_sensitive_value_pair(segments)


def _decoded_local_pointer_segments(value: str) -> tuple[str, ...] | None:
    if (
        type(value) is not str
        or len(value) > _MAX_LOCAL_JSON_POINTER_LENGTH
        or _LOCAL_JSON_POINTER.fullmatch(value) is None
    ):
        return None
    try:
        decoded = _decoded_candidates(value)[-1]
    except (UnicodeError, ValueError):
        return None
    if _LOCAL_JSON_POINTER.fullmatch(decoded) is None:
        return None
    if decoded == "#":
        return ()
    raw_segments = decoded[2:].split("/")
    segments: list[str] = []
    for raw_segment in raw_segments:
        # RFC 6901 requires ~1 to be expanded before ~0 so ~01 remains literal ~1.
        segment = raw_segment.replace("~1", "/").replace("~0", "~")
        if not segment.isascii() or any(
            ord(character) < 32 or ord(character) == 127 for character in segment
        ):
            return None
        segments.append(segment)
    return tuple(segments)


def _contains_value(value: JsonValue) -> bool:
    if value is None:
        return False
    if type(value) is str:
        return bool(value)
    if type(value) in {bool, int, float}:
        return True
    if type(value) is list:
        return bool(value)
    if type(value) is dict:
        return bool(value)
    return False


def _looks_like_schema(value: JsonValue) -> bool:
    return type(value) is dict and any(
        key in value for key in ("type", "properties", "oneOf", "anyOf", "allOf", "$ref")
    )


def _require_json_value(value: object) -> None:
    if value is None or type(value) in {bool, int, str}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("canonical JSON numbers must be finite")
        return
    if type(value) is list:
        for item in value:
            _require_json_value(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("canonical JSON object keys must be strings")
            _require_json_value(item)
        return
    raise TypeError("canonical hashing accepts JSON values only")


__all__ = [
    "CapabilitySnapshotError",
    "DuplicateToolNameError",
    "JsonValue",
    "PaginationCycleError",
    "SanitizedToolSchema",
    "ToolsListSession",
    "ToolsListSnapshot",
    "UnsafeCapabilitySnapshot",
    "canonical_sha256",
    "capture_tools_list",
    "capture_tools_snapshot",
    "text_contains_sensitive_material",
    "write_tools_snapshot",
]
