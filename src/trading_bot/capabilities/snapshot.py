"""Schema-only MCP capture and canonical sanitized JSON artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import parse_qsl, unquote, urlsplit

from mcp import types

from trading_bot.capabilities.models import (
    CapabilityEvidence,
    CapabilityManifest,
    CapabilityRecord,
    EvidenceLevel,
    OperationKind,
)
from trading_bot.clock import require_utc
from trading_bot.domain import AssetClass

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

_PROVIDER = "robinhood-trading"
_TOOL_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._~-]{0,127})?\Z")
_JWT_LIKE = re.compile(r"[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
_API_TOKEN_LIKE = re.compile(
    r"(?:sk|pk|ghp|gho|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{8,}",
    re.IGNORECASE,
)
_ACCOUNT_ID_LIKE = re.compile(r"RHC[A-Z0-9]{8,}", re.IGNORECASE)
_UUID_LIKE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_HIGH_ENTROPY_TOKEN = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{32,}(?![A-Za-z0-9_-])")
_PERCENT_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
_PEM_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE)
_BEARER_OR_HEADER_ASSIGNMENT = re.compile(
    r"(?:authorization|proxy-authorization|[a-z0-9-]*header|cookie|set-cookie)\s*[:=]"
    r"\s*(?:bearer\s+)?\S+",
    re.IGNORECASE,
)
_BEARER_MATERIAL = re.compile(r"\bbearer\s+[A-Za-z0-9._~-]+", re.IGNORECASE)
_SECRET_ASSIGNMENT = re.compile(
    r"(?:x-api-key|api[_-]?key|access[_-]?token|refresh[_-]?token|signature|signatures|sig|"
    r"account[_-]?(?:id|number|uuid))\s*[:=]\s*\S+",
    re.IGNORECASE,
)
_NAMED_ASSIGNMENT = re.compile(
    r"(?P<name>[A-Za-z][A-Za-z0-9_.%~-]{0,127})\s*[:=]\s*(?P<value>[^\s&#]+)",
    re.IGNORECASE,
)
_SENSITIVE_COMPONENTS = (
    "token",
    "account",
    "privatekey",
    "signingkey",
    "signature",
    "sig",
    "cookie",
    "header",
    "auth",
    "apikey",
    "session",
    "credential",
    "bearer",
    "secret",
    "password",
    "passphrase",
)
_SENSITIVE_SCHEMA_STRUCTURAL_KEYS = frozenset(
    {
        "$defs",
        "$ref",
        "additionalProperties",
        "allOf",
        "anyOf",
        "contains",
        "definitions",
        "dependentRequired",
        "dependentSchemas",
        "deprecated",
        "else",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "format",
        "if",
        "items",
        "maxContains",
        "maxItems",
        "maxLength",
        "maxProperties",
        "maximum",
        "minContains",
        "minItems",
        "minLength",
        "minProperties",
        "minimum",
        "multipleOf",
        "not",
        "nullable",
        "oneOf",
        "prefixItems",
        "properties",
        "propertyNames",
        "readOnly",
        "required",
        "then",
        "type",
        "unevaluatedProperties",
        "uniqueItems",
        "writeOnly",
    }
)
_MAX_INSPECTION_TEXT_LENGTH = 65_536
_MAX_PERCENT_DECODE_ROUNDS = 3

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
        return _decode_schema_object(self._input_schema_json)

    @property
    def output_schema(self) -> dict[str, JsonValue] | None:
        """Return a detached output-schema view, preserving explicit null."""
        if self._output_schema_json is None:
            return None
        return _decode_schema_object(self._output_schema_json)

    def as_json(self) -> dict[str, JsonValue]:
        """Return a detached exact-schema representation suitable for JSON."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": _copy_json(self.input_schema),
            "outputSchema": _copy_json(self.output_schema),
            "schemaSha256": self.schema_sha256,
        }


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
        try:
            require_utc(self.observed_at)
        except Exception:
            raise CapabilitySnapshotError("snapshot timestamp must be aware UTC") from None
        if type(self.tools) is not tuple or any(
            type(item) is not SanitizedToolSchema for item in self.tools
        ):
            raise CapabilitySnapshotError("snapshot tools must be immutable sanitized values")
        names = tuple(item.name for item in self.tools)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise CapabilitySnapshotError("snapshot tools must be unique and deterministic")
        if type(self.manifest) is not CapabilityManifest:
            raise CapabilitySnapshotError("snapshot manifest is invalid")
        expected = CapabilityManifest(
            records=tuple(_record_from_schema(item, self.observed_at) for item in self.tools)
        )
        if self.manifest != expected:
            raise CapabilitySnapshotError("snapshot manifest does not match captured schemas")

    def as_json(self) -> dict[str, JsonValue]:
        """Render the deterministic committed artifact without SDK extras."""
        return {
            "provider": self.provider,
            "observedAt": self.observed_at.isoformat().replace("+00:00", "Z"),
            "method": "tools/list",
            "tools": [item.as_json() for item in self.tools],
        }


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
    timestamp = observed_at if observed_at is not None else datetime.now(UTC)
    try:
        require_utc(timestamp)
    except Exception:
        raise CapabilitySnapshotError("observed_at must be aware UTC") from None

    captured: list[SanitizedToolSchema] = []
    names: set[str] = set()
    seen_cursors: set[str] = set()
    params: types.PaginatedRequestParams | None = None

    while True:
        result = await _request_tools_page(session, params)
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


def _copy_json(value: object) -> JsonValue:
    if value is None or type(value) in {bool, int, str}:
        return cast(JsonScalar, value)
    if type(value) is float:
        assert isinstance(value, float)
        if not math.isfinite(value):
            raise CapabilitySnapshotError("schema contains a nonfinite number")
        return value
    if type(value) is list:
        assert isinstance(value, list)
        return [_copy_json(item) for item in value]
    if type(value) is dict:
        assert isinstance(value, dict)
        copied: dict[str, JsonValue] = {}
        for key, item in value.items():
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
        assert isinstance(value, str)
        if text_contains_sensitive_material(value):
            raise UnsafeCapabilitySnapshot("capability snapshot contains sensitive material")
        return
    if type(value) is list:
        assert isinstance(value, list)
        for item in value:
            _scan_sensitive(item, sensitive_property=sensitive_property)
        return
    if type(value) is not dict:
        return
    assert isinstance(value, dict)
    if sensitive_property and any(
        key not in _SENSITIVE_SCHEMA_STRUCTURAL_KEYS and _contains_value(item)
        for key, item in value.items()
    ):
        raise UnsafeCapabilitySnapshot("sensitive schema properties cannot embed metadata")
    for key, item in value.items():
        if text_contains_sensitive_material(key):
            raise UnsafeCapabilitySnapshot("capability snapshot contains sensitive material")
        if key == "properties" and type(item) is dict:
            assert isinstance(item, dict)
            for property_name, property_schema in item.items():
                if text_contains_sensitive_material(property_name):
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


def text_contains_sensitive_material(value: str) -> bool:
    if len(value) > _MAX_INSPECTION_TEXT_LENGTH:
        return True
    try:
        candidates = _decoded_candidates(value)
    except (UnicodeError, ValueError):
        return True
    for candidate in candidates:
        if (
            _PEM_PRIVATE_KEY.search(candidate)
            or _BEARER_MATERIAL.search(candidate)
            or _JWT_LIKE.search(candidate)
            or _API_TOKEN_LIKE.search(candidate)
            or _ACCOUNT_ID_LIKE.search(candidate)
            or _UUID_LIKE.search(candidate)
            or _HIGH_ENTROPY_TOKEN.search(candidate)
            or _BEARER_OR_HEADER_ASSIGNMENT.search(candidate)
            or _SECRET_ASSIGNMENT.search(candidate)
        ):
            return True
        if any(
            _name_is_sensitive(match.group("name")) and bool(match.group("value"))
            for match in _NAMED_ASSIGNMENT.finditer(candidate)
        ):
            return True
        try:
            parsed = urlsplit(candidate)
        except ValueError:
            return True
        if parsed.username is not None or parsed.password is not None:
            return True
        for component in (parsed.query, parsed.fragment):
            if not component:
                continue
            try:
                pairs = parse_qsl(
                    component,
                    keep_blank_values=True,
                    max_num_fields=128,
                )
            except ValueError:
                return True
            if any(_name_is_sensitive(name) and bool(item) for name, item in pairs):
                return True
        segments = tuple(segment for segment in parsed.path.split("/") if segment)
        if any(
            _name_is_sensitive(segment) and bool(segments[index + 1])
            for index, segment in enumerate(segments[:-1])
        ):
            return True
    return False


def _decoded_candidates(value: str) -> tuple[str, ...]:
    candidates = [value]
    decoded = value
    for _ in range(_MAX_PERCENT_DECODE_ROUNDS):
        next_value = unquote(decoded, errors="strict")
        if next_value == decoded:
            break
        candidates.append(next_value)
        decoded = next_value
    if _PERCENT_ESCAPE.search(decoded):
        raise ValueError
    return tuple(candidates)


def _normalize_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _name_is_sensitive(value: str) -> bool:
    normalized = _normalize_name(value)
    return any(component in normalized for component in _SENSITIVE_COMPONENTS)


def _contains_value(value: JsonValue) -> bool:
    if value is None:
        return False
    if type(value) is str:
        return bool(value)
    if type(value) in {bool, int, float}:
        return True
    if type(value) is list:
        assert isinstance(value, list)
        return bool(value)
    if type(value) is dict:
        assert isinstance(value, dict)
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
