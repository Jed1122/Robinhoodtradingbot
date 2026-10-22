import json
from pathlib import Path

import pytest
from mcp import types

PROFILE = (
    Path(__file__).resolve().parents[3]
    / "src/trading_bot/brokers/schema_snapshots/robinhood_stock_research.20261021.json"
)


class Sdk:
    def __init__(self, *, drift=False, invalid=False):
        self.calls = []
        self.drift, self.invalid = drift, invalid

    async def list_tools(self, **kwargs):
        rows = json.loads(PROFILE.read_text())["tools"]
        if self.drift:
            rows[0]["inputSchema"]["properties"]["unexpected"] = {"type": "string"}
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=r["name"], inputSchema=r["inputSchema"], outputSchema=r["outputSchema"]
                )
                for r in rows
            ]
        )

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        payload = {
            "data": {
                "filter_specs": [
                    {
                        "filter_type": "FILTER_TYPE_INSTRUMENT_TYPE",
                        "display_name": "Asset type",
                        "filter_group": "FUNDAMENTAL",
                        "value_type": "STRING",
                        "unit_type": "PLAIN",
                        "supported_predicates": ["=", "ANY_OF"],
                        "options": ["STOCK", "ETF"],
                    }
                ]
            },
            "guide": "",
        }
        if self.invalid:
            payload = {"private-secret": "never expose this response"}
        return types.CallToolResult(content=[], structuredContent=payload)


async def test_explicit_stock_profile_requires_current_schema_then_permits_only_research():
    from trading_bot.brokers.stock_research_mcp import StockResearchMcpSession

    sdk = Sdk()
    session = StockResearchMcpSession(sdk)
    with pytest.raises(RuntimeError, match="schema"):
        await session.call_tool("get_scanner_filter_specs", {})
    digest = await session.validate_tools()
    assert len(digest) == 64
    result = await session.call_tool("get_scanner_filter_specs", {})
    assert result.is_error is False
    assert sdk.calls == [("get_scanner_filter_specs", {})]


@pytest.mark.parametrize(
    "name",
    [
        "place_equity_order",
        "review_equity_order",
        "cancel_equity_order",
        "get_accounts",
        "get_portfolio",
        "get_equity_orders",
        "get_equity_positions",
        "create_scan",
        "update_scan_filters",
        "get_option_quotes",
        "get_crypto_quotes",
        "update_alert",
    ],
)
async def test_stock_profile_denies_every_account_or_mutation_path_before_sdk(name):
    from trading_bot.brokers.stock_research_mcp import StockResearchMcpSession

    sdk = Sdk()
    session = StockResearchMcpSession(sdk)
    with pytest.raises(PermissionError):
        await session.call_tool(name, {})
    assert sdk.calls == []


async def test_stock_schema_drift_denies_all_reads():
    from trading_bot.brokers.stock_research_mcp import StockResearchMcpSession

    sdk = Sdk(drift=True)
    session = StockResearchMcpSession(sdk)
    with pytest.raises(RuntimeError, match="schema"):
        await session.validate_tools()
    with pytest.raises(RuntimeError, match="schema"):
        await session.call_tool("get_scanner_filter_specs", {})
    assert sdk.calls == []


async def test_stock_input_and_output_contracts_fail_without_payload_disclosure():
    from trading_bot.brokers.stock_research_mcp import StockResearchMcpSession

    sdk = Sdk(invalid=True)
    session = StockResearchMcpSession(sdk)
    await session.validate_tools()
    with pytest.raises(ValueError):
        await session.call_tool("get_financials", {"symbols": ["X"] * 21})
    with pytest.raises(ValueError):
        await session.call_tool("get_scanner_filter_specs", {"account_number": "fictional"})
    assert sdk.calls == []
    with pytest.raises(RuntimeError) as error:
        await session.call_tool("get_scanner_filter_specs", {})
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "name", ["place_equity_order", "get_accounts", "get_equity_orders", "create_scan"]
)
async def test_second_transport_gate_denies_even_a_permissive_inner_session(name):
    from trading_bot.brokers.stock_research_mcp import StockResearchTransport

    class Permissive:
        calls = 0

        async def call_tool(self, *args):
            self.calls += 1
            raise AssertionError("second gate must block")

    inner = Permissive()
    with pytest.raises(PermissionError):
        await StockResearchTransport(inner).call_tool(name, {})
    assert inner.calls == 0


@pytest.mark.parametrize(
    "filters",
    [
        None,
        [],
        [{"filter_type": "FILTER_TYPE_INSTRUMENT_TYPE", "predicate": "=", "values": ["ETF"]}],
        [{"filter_type": "FILTER_TYPE_MARKET_CAP", "predicate": ">", "values": ["2000000000"]}],
    ],
)
async def test_preview_cannot_silently_become_etf_or_unscoped_research(filters):
    from trading_bot.brokers.stock_research_mcp import StockResearchMcpSession

    sdk = Sdk()
    session = StockResearchMcpSession(sdk)
    await session.validate_tools()
    with pytest.raises(ValueError):
        await session.call_tool("preview_scan", {"filters": filters})
    assert sdk.calls == []


def test_stock_facade_is_explicit_and_unavailable_without_connection():
    from trading_bot.brokers.robinhood_mcp_sdk import RobinhoodMcpSdkConnection

    connection = RobinhoodMcpSdkConnection(oauth_store_dir="/not/opened")
    with pytest.raises(RuntimeError):
        _ = connection.stock_research_session


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("get_earnings_calendar", {"days": 100000}),
        ("get_earnings_calendar", {"days": 0}),
        ("get_sec_filing_facts", {"filing_ids": ["f1", "f2", "f3", "f4"], "concepts": ["Revenue"]}),
        ("get_sec_filing_facts", {"filing_ids": ["f1"], "concepts": ["x"] * 11}),
    ],
)
async def test_documented_calendar_and_filing_bounds_deny_before_provider(name, arguments):
    from trading_bot.brokers.stock_research_mcp import StockResearchMcpSession

    sdk = Sdk()
    session = StockResearchMcpSession(sdk)
    await session.validate_tools()
    with pytest.raises(ValueError):
        await session.call_tool(name, arguments)
    assert sdk.calls == []


async def test_scan_requires_server_filter_vocabulary_and_echoed_stock_scope():
    from trading_bot.brokers.stock_research_mcp import StockResearchMcpSession

    class MissingEcho(Sdk):
        async def call_tool(self, name, arguments):
            if name != "preview_scan":
                return await super().call_tool(name, arguments)
            self.calls.append((name, arguments))
            return types.CallToolResult(
                content=[],
                structuredContent={
                    "data": {
                        "result": {
                            "total_items": 1,
                            "results": [
                                {
                                    "ticker": "ETF",
                                    "instrument_id": "fictional",
                                    "instrument_type": "EQUITY",
                                    "columns": {"Asset type": "ETF"},
                                }
                            ],
                        }
                    },
                    "guide": "",
                },
            )

    sdk = MissingEcho()
    session = StockResearchMcpSession(sdk)
    await session.validate_tools()
    args = {
        "filters": [
            {"filter_type": "FILTER_TYPE_INSTRUMENT_TYPE", "predicate": "=", "values": ["STOCK"]}
        ]
    }
    with pytest.raises(RuntimeError):
        await session.call_tool("preview_scan", args)
    assert sdk.calls == []
    await session.call_tool("get_scanner_filter_specs", {})
    with pytest.raises(RuntimeError):
        await session.call_tool("preview_scan", args)
