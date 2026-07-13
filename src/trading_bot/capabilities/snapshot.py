"""Schema-only MCP capture and canonical sanitized JSON artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import parse_qsl, urlsplit

from mcp import types

from trading_bot.capabilities.models import (
    CapabilityEvidence,
    CapabilityManifest,
    CapabilityRecord,
    EvidenceLevel,
    OperationKind,
)
from trading_bot.clock import InvalidTimestamp, require_utc
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
_PEM_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE)
_BEARER_OR_HEADER_ASSIGNMENT = re.compile(
    r"(?:authorization|proxy-authorization|[a-z0-9-]*header|cookie|set-cookie)\s*[:=]"
    r"\s*(?:bearer\s+)?\S+",
    re.IGNORECASE,
)
_BEARER_MATERIAL = re.compile(r"\bbearer\s+[A-Za-z0-9._~-]{16,}", re.IGNORECASE)
_SECRET_ASSIGNMENT = re.compile(
    r"(?:x-api-key|api[_-]?key|access[_-]?token|refresh[_-]?token|signature|signatures|sig|"
    r"account[_-]?(?:id|number|uuid))\s*[:=]\s*\S+",
    re.IGNORECASE,
)
_SENSITIVE_NAMES = frozenset(
    {
        "account",
        "accountid",
        "accountnumber",
        "accountuuid",
        "accesstoken",
        "apikey",
        "authorization",
        "cookie",
        "privatekey",
        "refreshtoken",
        "setcookie",
        "sig",
        "signature",
        "signatures",
        "token",
        "xapikey",
    }
)
_VALUE_KEYWORDS = frozenset({"const", "default", "enum", "example", "examples"})

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
    input_schema: dict[str, JsonValue]
    output_schema: dict[str, JsonValue] | None
    schema_sha256: str

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
    except InvalidTimestamp as exc:
        raise CapabilitySnapshotError("observed_at must be aware UTC") from exc

    captured: list[SanitizedToolSchema] = []
    names: set[str] = set()
    seen_cursors: set[str] = set()
    params: types.PaginatedRequestParams | None = None

    while True:
        result = (
            await session.list_tools(params=params)
            if params is not None
            else await session.list_tools()
        )
        for declared in result.tools:
            if declared.name in names:
                raise DuplicateToolNameError("tools/list contains a duplicate tool name")
            names.add(declared.name)
            captured.append(_sanitize_tool(declared))
        cursor = result.nextCursor
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


async def write_tools_snapshot(
    session: ToolsListSession,
    output: Path,
    *,
    observed_at: datetime | None = None,
) -> ToolsListSnapshot:
    """Validate a complete snapshot in memory, then write exactly one artifact."""
    snapshot = await capture_tools_snapshot(session, observed_at=observed_at)
    artifact = snapshot.as_json()
    payload = json.dumps(artifact, allow_nan=False, indent=2, sort_keys=True) + "\n"
    output.write_text(payload, encoding="utf-8")
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
        input_schema=input_value,
        output_schema=output_value,
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


def _scan_sensitive(
    value: JsonValue,
    *,
    sensitive_property: bool = False,
) -> None:
    if type(value) is str:
        assert isinstance(value, str)
        if _string_is_sensitive(value):
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
    for key, item in value.items():
        if _string_is_sensitive(key):
            raise UnsafeCapabilitySnapshot("capability snapshot contains sensitive material")
        normalized = _normalize_name(key)
        if sensitive_property and normalized in _VALUE_KEYWORDS and _contains_value(item):
            raise UnsafeCapabilitySnapshot("sensitive schema properties cannot embed values")
        if key == "properties" and type(item) is dict:
            assert isinstance(item, dict)
            for property_name, property_schema in item.items():
                _scan_sensitive(
                    property_schema,
                    sensitive_property=_normalize_name(property_name) in _SENSITIVE_NAMES,
                )
            continue
        if (
            normalized in _SENSITIVE_NAMES
            and not _looks_like_schema(item)
            and _contains_value(item)
        ):
            raise UnsafeCapabilitySnapshot("capability snapshot contains sensitive material")
        _scan_sensitive(item, sensitive_property=sensitive_property)


def _string_is_sensitive(value: str) -> bool:
    if (
        _PEM_PRIVATE_KEY.search(value)
        or _BEARER_MATERIAL.search(value)
        or _JWT_LIKE.search(value)
        or _API_TOKEN_LIKE.search(value)
        or _ACCOUNT_ID_LIKE.search(value)
        or _UUID_LIKE.search(value)
        or _HIGH_ENTROPY_TOKEN.search(value)
        or _BEARER_OR_HEADER_ASSIGNMENT.search(value)
        or _SECRET_ASSIGNMENT.search(value)
    ):
        return True
    try:
        parsed = urlsplit(value)
    except ValueError:
        return True
    if not parsed.query:
        return False
    return any(
        _normalize_name(name) in _SENSITIVE_NAMES and bool(item)
        for name, item in parse_qsl(parsed.query, keep_blank_values=True)
    )


def _normalize_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


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
    "write_tools_snapshot",
]
