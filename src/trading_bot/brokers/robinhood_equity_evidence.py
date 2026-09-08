"""Sanitized capability evidence and runtime declaration checks for equity MCP reads."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from trading_bot.brokers.robinhood_equity_mapping import (
    AUTHENTICATED_SHAPE_PATH,
    AUTHENTICATED_SHAPE_SHA256,
)
from trading_bot.brokers.robinhood_mcp_schema_gate import DeclaredMcpTool
from trading_bot.capabilities.models import (
    CapabilityEvidence,
    CapabilityManifest,
    CapabilityRecord,
    EvidenceLevel,
    OperationKind,
)
from trading_bot.domain import AssetClass, DataHash
from trading_bot.market_data import content_hash

EXPECTED_TOOL_ARGUMENTS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "get_accounts": (frozenset(), frozenset()),
    "get_portfolio": (frozenset({"account_number"}), frozenset({"account_number"})),
    "get_equity_positions": (
        frozenset({"account_number", "cursor"}),
        frozenset({"account_number"}),
    ),
    "get_equity_orders": (
        frozenset(
            {
                "account_number",
                "created_at_gte",
                "cursor",
                "order_id",
                "placed_agent",
                "state",
                "symbol",
            }
        ),
        frozenset({"account_number"}),
    ),
    "get_equity_quotes": (frozenset({"symbols"}), frozenset({"symbols"})),
    "get_equity_tradability": (
        frozenset({"account_number", "symbols"}),
        frozenset({"account_number", "symbols"}),
    ),
    "get_equity_historicals": (
        frozenset(
            {
                "adjustment_type",
                "bounds",
                "end_time",
                "interval",
                "start_time",
                "symbols",
            }
        ),
        frozenset({"start_time", "symbols"}),
    ),
}

EXPECTED_EQUITY_WRITE_ARGUMENTS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "cancel_equity_order": (
        frozenset({"account_number", "order_id"}),
        frozenset({"account_number", "order_id"}),
    ),
    "place_equity_order": (
        frozenset(
            {
                "account_number",
                "dollar_amount",
                "limit_price",
                "market_hours",
                "quantity",
                "ref_id",
                "side",
                "stop_price",
                "symbol",
                "tax_lots",
                "time_in_force",
                "type",
            }
        ),
        frozenset({"account_number", "symbol", "side", "type"}),
    ),
    "review_equity_order": (
        frozenset(
            {
                "account_number",
                "dollar_amount",
                "limit_price",
                "market_hours",
                "quantity",
                "side",
                "stop_price",
                "symbol",
                "tax_lots",
                "time_in_force",
                "type",
            }
        ),
        frozenset({"account_number", "symbol", "side", "type"}),
    ),
}

# These hashes bind both input and output JSON Schemas from the sanitized,
# authenticated tools/list capture. They are declaration evidence only: no
# review, placement, or cancellation operation was invoked to obtain them.
EXPECTED_EQUITY_WRITE_SCHEMA_SHA256: dict[str, str] = {
    "cancel_equity_order": "e54d03ec9e50c3abc6305d93ad5a1b2a975acaa0309c7013791243f9ba115bed",
    "place_equity_order": "9ae58a3814e8b3754242e5c587d357e313ba5d8fb6df38e4278ed7825c920e80",
    "review_equity_order": "5f158880003bb14a17cfe9e51ca562a8ff8f72e44e6b994d78c2eedbe27ebe74",
}


class EquityEvidenceError(RuntimeError):
    pass


def _artifact() -> dict[str, object]:
    try:
        value: object = json.loads(AUTHENTICATED_SHAPE_PATH.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise EquityEvidenceError("authenticated shape artifact is unavailable") from exc
    if type(value) is not dict or value.get("shape_sha256") != AUTHENTICATED_SHAPE_SHA256:
        raise EquityEvidenceError("authenticated shape artifact identity changed")
    payload = dict(value)
    payload.pop("shape_sha256", None)
    observed = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if observed != AUTHENTICATED_SHAPE_SHA256 or value.get("contains_account_data") is not False:
        raise EquityEvidenceError("authenticated shape artifact validation failed")
    return value


def _tool_shape_hash(name: str) -> str:
    tools = _artifact().get("tools")
    if type(tools) is not dict or name not in tools:
        raise EquityEvidenceError("authenticated tool shape is unavailable")
    return hashlib.sha256(
        json.dumps(tools[name], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _declared_contract_hash(name: str) -> str:
    properties, required = EXPECTED_TOOL_ARGUMENTS[name]
    return str(
        content_hash(
            {
                "operation": name,
                "properties": tuple(sorted(properties)),
                "required": tuple(sorted(required)),
            }
        )
    )


def authenticated_equity_manifest() -> CapabilityManifest:
    """Build a value-free manifest from the reviewed declaration and read-shape artifacts."""

    observed_at = datetime(2026, 7, 21, tzinfo=UTC)
    records = []
    for operation in sorted(EXPECTED_TOOL_ARGUMENTS):
        records.append(
            CapabilityRecord(
                provider="robinhood-trading",
                operation=operation,
                asset_class=AssetClass.EQUITY,
                operation_kind=OperationKind.READ,
                evidence=(
                    CapabilityEvidence(
                        level=EvidenceLevel.SCHEMA_DECLARED,
                        source_uri=f"mcp://robinhood-trading/tools/{operation}",
                        observed_at=observed_at,
                        schema_sha256=_declared_contract_hash(operation),
                        authenticated=False,
                        contains_account_data=False,
                        notes=("Reviewed read-only argument contract",),
                    ),
                    CapabilityEvidence(
                        level=EvidenceLevel.AUTHENTICATED_READ_VERIFIED,
                        source_uri=f"mcp://robinhood-trading/tools/{operation}",
                        observed_at=observed_at,
                        schema_sha256=_tool_shape_hash(operation),
                        authenticated=True,
                        contains_account_data=False,
                        notes=("Authenticated value-free response shape",),
                    ),
                ),
                limitations=(
                    "Equity positions and orders accept only authenticated empty collections "
                    "until nonempty row shapes are reviewed",
                ),
                locked_reason=None,
            )
        )
    return CapabilityManifest(records=tuple(records))


def validate_read_tool_declarations(observed: tuple[DeclaredMcpTool, ...]) -> DataHash:
    """Require exact reviewed input keys and bind current raw declaration hashes."""

    by_name = {tool.name: tool for tool in observed}
    if len(by_name) != len(observed):
        raise EquityEvidenceError("MCP tools/list contains duplicate names")
    bound_hashes: list[tuple[str, str]] = []
    for name, (expected_properties, expected_required) in EXPECTED_TOOL_ARGUMENTS.items():
        tool = by_name.get(name)
        if tool is None or type(tool.input_schema) is not dict or tool.output_schema is None:
            raise EquityEvidenceError("required MCP read declaration is missing")
        if "properties" not in tool.input_schema:
            if (
                expected_properties
                or tool.input_schema.get("type") != "object"
                or tool.input_schema.get("additionalProperties") is not False
            ):
                raise EquityEvidenceError("required MCP input declaration is incompatible")
            properties: object = {}
        else:
            properties = tool.input_schema["properties"]
        required = tool.input_schema.get("required", [])
        if type(properties) is not dict or type(required) is not list:
            raise EquityEvidenceError("required MCP input declaration is incompatible")
        if frozenset(properties) != expected_properties or frozenset(required) != expected_required:
            raise EquityEvidenceError("required MCP input declaration changed")
        bound_hashes.append((name, tool.schema_sha256))
    return content_hash(
        {
            "authenticated_shape_sha256": AUTHENTICATED_SHAPE_SHA256,
            "tool_schema_hashes": tuple(sorted(bound_hashes)),
        }
    )


def validate_equity_write_tool_declarations(
    observed: tuple[DeclaredMcpTool, ...],
) -> DataHash:
    """Bind exact write declarations without treating them as reviewed writes."""

    by_name = {tool.name: tool for tool in observed}
    if len(by_name) != len(observed):
        raise EquityEvidenceError("MCP tools/list contains duplicate names")
    bound_hashes: list[tuple[str, str]] = []
    for name, (expected_properties, expected_required) in (
        EXPECTED_EQUITY_WRITE_ARGUMENTS.items()
    ):
        tool = by_name.get(name)
        if tool is None:
            raise EquityEvidenceError("required MCP equity write declaration is missing")
        input_schema = tool.input_schema
        if (
            type(input_schema) is not dict
            or input_schema.get("type") != "object"
            or input_schema.get("additionalProperties") is not False
            or tool.output_schema is None
        ):
            raise EquityEvidenceError("required MCP equity write input declaration is incompatible")
        properties = input_schema.get("properties")
        required = input_schema.get("required", [])
        if (
            type(properties) is not dict
            or type(required) is not list
            or frozenset(properties) != expected_properties
            or frozenset(required) != expected_required
        ):
            raise EquityEvidenceError("required MCP equity write input declaration changed")
        if tool.schema_sha256 != EXPECTED_EQUITY_WRITE_SCHEMA_SHA256[name]:
            raise EquityEvidenceError("required MCP equity write schema changed")
        bound_hashes.append((name, tool.schema_sha256))
    return content_hash({"tool_schema_hashes": tuple(sorted(bound_hashes))})


__all__ = [
    "EXPECTED_EQUITY_WRITE_ARGUMENTS",
    "EXPECTED_EQUITY_WRITE_SCHEMA_SHA256",
    "EXPECTED_TOOL_ARGUMENTS",
    "EquityEvidenceError",
    "authenticated_equity_manifest",
    "validate_equity_write_tool_declarations",
    "validate_read_tool_declarations",
]
