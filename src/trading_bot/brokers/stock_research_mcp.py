"""Schema-bound stock-market research; no account or execution operations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from mcp import ClientSession

from trading_bot.brokers.robinhood_mcp_schema_gate import JsonValue
from trading_bot.brokers.robinhood_mcp_sdk import SchemaOnlyMcpClientSession, _as_json
from trading_bot.brokers.robinhood_mcp_transport import McpToolResult, McpToolSession
from trading_bot.capabilities.snapshot import canonical_sha256, capture_tools_snapshot

STOCK_RESEARCH_TOOLS = frozenset(
    {
        "get_scanner_filter_specs",
        "get_scanner_datapoints",
        "preview_scan",
        "get_equity_quotes",
        "get_equity_historicals",
        "get_equity_fundamentals",
        "get_financials",
        "get_earnings_results",
        "get_earnings_calendar",
        "get_sec_filing_index",
        "get_sec_filing_facts",
        "get_sec_filing_facts_catalog",
        "get_sec_filing",
    }
)
PROFILE_PATH = Path(__file__).parent / "schema_snapshots/robinhood_stock_research.20261021.json"
PROFILE_SHA256 = "f95f313e2187326c610032029be438839536c6da69de30f17b1d1fe642d235f1"
MAX_RESPONSE_BYTES = 8_388_608


def _profile() -> dict[str, Any]:
    body = PROFILE_PATH.read_bytes()
    if hashlib.sha256(body).hexdigest() != PROFILE_SHA256:
        raise RuntimeError("stock research schema profile changed")
    value = json.loads(body)
    tools = {row["name"]: row for row in value["tools"]}
    if set(tools) != STOCK_RESEARCH_TOOLS:
        raise RuntimeError("stock research schema profile changed")
    for row in tools.values():
        if (
            canonical_sha256(
                {"inputSchema": row["inputSchema"], "outputSchema": row["outputSchema"]}
            )
            != row["schemaSha256"]
        ):
            raise RuntimeError("stock research schema profile changed")
    return tools


def _arguments(name: str, arguments: Mapping[str, JsonValue], expected: dict[str, Any]) -> None:
    encoded = json.dumps(dict(arguments), allow_nan=False, separators=(",", ":"))
    if len(encoded.encode()) > 131072:
        raise ValueError("stock research request too large")
    if not Draft202012Validator(expected["inputSchema"]).is_valid(dict(arguments)):
        raise ValueError("stock research request violates reviewed schema")
    limits = {
        "get_equity_quotes": 20,
        "get_equity_historicals": 10,
        "get_equity_fundamentals": 10,
        "get_financials": 20,
    }
    if name in limits:
        symbols = arguments.get("symbols")
        if not isinstance(symbols, list) or not 1 <= len(symbols) <= limits[name]:
            raise ValueError("stock research symbol batch invalid")
        if any(type(symbol) is not str or not symbol for symbol in symbols):
            raise ValueError("stock research symbol invalid")
        if len(set(symbols)) != len(symbols):
            raise ValueError("stock research duplicate symbol")
    if name == "preview_scan":
        filters = arguments.get("filters")
        if not isinstance(filters, list) or not 1 <= len(filters) <= 32:
            raise ValueError("stock research filters invalid")
        stock = [
            item
            for item in filters
            if isinstance(item, dict) and item.get("filter_type") == "FILTER_TYPE_INSTRUMENT_TYPE"
        ]
        if (
            len(stock) != 1
            or stock[0].get("predicate") != "="
            or stock[0].get("values") != ["STOCK"]
        ):
            raise ValueError("individual-stock filter required")
    if name == "get_financials" and arguments.get("limit", 4) not in range(1, 41):
        raise ValueError("stock financial period count invalid")

    if name == "get_earnings_calendar":
        days = arguments.get("days", 7)
        if type(days) is not int or not 1 <= abs(days) <= 31:
            raise ValueError("stock earnings calendar window invalid")
    if name == "get_sec_filing_facts":
        for field, maximum in (("filing_ids", 3), ("concepts", 10)):
            values = arguments.get(field)
            if not isinstance(values, list) or not 1 <= len(values) <= maximum:
                raise ValueError("stock filing facts batch invalid")
            if any(type(value) is not str or not value for value in values):
                raise ValueError("stock filing facts identifiers invalid")


def _stock_vocabulary(payload: dict[str, Any]) -> bool:
    specs = payload["data"]["filter_specs"] or []
    return any(
        item is not None
        and item["filter_type"] == "FILTER_TYPE_INSTRUMENT_TYPE"
        and "STOCK" in (item.get("options") or [])
        and "=" in (item.get("supported_predicates") or [])
        for item in specs
    )


def _verify_stock_preview(payload: dict[str, Any]) -> None:
    result = payload["data"]["result"]
    echoed = [
        item
        for item in (result.get("filters_applied") or [])
        if item.get("filter_type_enum", item.get("filter_type")) == "FILTER_TYPE_INSTRUMENT_TYPE"
    ]
    if (
        len(echoed) != 1
        or echoed[0]["values"] != ["STOCK"]
        or echoed[0]["predicate"] not in {"=", "ANY_OF"}
        or not isinstance(result["results"], list)
        or result["total_items"] < len(result["results"])
    ):
        raise RuntimeError("stock discovery scope not established")
    rows = result["results"]
    if (
        any(
            row["instrument_type"] != "EQUITY" or row["columns"].get("Asset type") != "STOCK"
            for row in rows
        )
        or len({row["instrument_id"] for row in rows}) != len(rows)
        or len({row["ticker"] for row in rows}) != len(rows)
    ):
        raise RuntimeError("stock discovery contains incompatible instruments")


class StockResearchMcpSession:
    """Fixed read-only facade, initially locked until current schemas match."""

    def __init__(self, session: ClientSession) -> None:
        self._sdk = session
        self._expected = _profile()
        self._validated = False
        self._stock_filter_verified = False

    async def validate_tools(self) -> str:
        self._validated = False
        self._stock_filter_verified = False
        snapshot = await capture_tools_snapshot(
            SchemaOnlyMcpClientSession(self._sdk), omit_descriptions=True
        )
        actual = {tool.name: tool.schema_sha256 for tool in snapshot.tools}
        if any(actual.get(name) != row["schemaSha256"] for name, row in self._expected.items()):
            raise RuntimeError("stock research schema drift")
        self._validated = True
        return PROFILE_SHA256

    async def list_tools(self) -> tuple[()]:
        # Do not hand an execution-capable catalog to the research consumer.
        raise PermissionError("use stock research schema validation")

    async def call_tool(self, name: str, arguments: Mapping[str, JsonValue]) -> McpToolResult:
        if name not in STOCK_RESEARCH_TOOLS:
            raise PermissionError("outside individual-stock research profile")
        if not self._validated:
            raise RuntimeError("stock research schema has not been validated")
        submitted = json.loads(json.dumps(dict(arguments), allow_nan=False))
        _arguments(name, submitted, self._expected[name])
        if name == "preview_scan" and not self._stock_filter_verified:
            raise RuntimeError("stock discovery filter vocabulary unavailable")
        try:
            result = await self._sdk.call_tool(name, submitted)
            if result.isError or result.structuredContent is None:
                raise RuntimeError("stock research unavailable")
            encoded = json.dumps(result.structuredContent, allow_nan=False, separators=(",", ":"))
            if len(encoded.encode()) > MAX_RESPONSE_BYTES or not Draft202012Validator(
                self._expected[name]["outputSchema"]
            ).is_valid(result.structuredContent):
                raise RuntimeError("stock research response violates reviewed schema")
            if name == "get_scanner_filter_specs":
                self._stock_filter_verified = _stock_vocabulary(result.structuredContent)
            elif name == "preview_scan":
                _verify_stock_preview(result.structuredContent)
            return McpToolResult((), False, _as_json(result.structuredContent))
        except Exception:
            raise RuntimeError("stock research response unavailable or incompatible") from None


class StockResearchTransport:
    """Independent second allowlist; contains no credentials or execution methods."""

    def __init__(self, session: McpToolSession) -> None:
        self._session = session

    async def call_tool(self, name: str, arguments: Mapping[str, JsonValue]) -> McpToolResult:
        if name not in STOCK_RESEARCH_TOOLS:
            raise PermissionError("outside individual-stock research transport")
        try:
            return await self._session.call_tool(name, arguments)
        except Exception:
            raise RuntimeError("stock research call failed safely") from None
