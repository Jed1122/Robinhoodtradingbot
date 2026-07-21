from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from trading_bot.brokers.robinhood_equity_mapping import (
    UnverifiedNonemptyShape,
    account_fingerprint,
)
from trading_bot.brokers.robinhood_equity_mcp import (
    EquityReadError,
    RobinhoodEquityReadAdapter,
)
from trading_bot.brokers.robinhood_mcp_schema_gate import DeclaredMcpTool, JsonValue
from trading_bot.brokers.robinhood_mcp_transport import (
    OFFICIAL_MCP_ENDPOINT,
    McpToolResult,
    RobinhoodMcpTransport,
)
from trading_bot.domain import AccountId, BarInterval, InstrumentId
from trading_bot.market_data import MarketDataCapabilityError
from trading_bot.market_data.robinhood_equity_mcp import RobinhoodEquityMarketData

NOW = datetime(2026, 7, 21, 18, tzinfo=UTC)
INSTRUMENT = InstrumentId("SYNTH")


class FixedClock:
    def now(self) -> datetime:
        return NOW


class LocalSession:
    def __init__(self, responses: Mapping[str, JsonValue]) -> None:
        self.responses = dict(responses)
        self.calls: list[tuple[str, dict[str, JsonValue]]] = []

    async def list_tools(self) -> tuple[DeclaredMcpTool, ...]:
        return ()

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, JsonValue],
    ) -> McpToolResult:
        self.calls.append((name, dict(arguments)))
        return McpToolResult((), False, self.responses[name])


def transport_for(
    tmp_path: Path,
    responses: Mapping[str, JsonValue],
) -> tuple[RobinhoodMcpTransport, LocalSession]:
    store = tmp_path / "oauth"
    store.mkdir(mode=0o700)
    store.chmod(0o700)
    session = LocalSession(responses)
    return (
        RobinhoodMcpTransport(
            session,
            endpoint=OFFICIAL_MCP_ENDPOINT,
            oauth_store_dir=store,
            allowed_tools=frozenset(responses),
        ),
        session,
    )


def account_payload(account_number: str, **overrides: object) -> dict[str, JsonValue]:
    value: dict[str, JsonValue] = {
        "account_number": account_number,
        "affiliate": "synthetic-affiliate",
        "agentic_allowed": True,
        "brokerage_account_type": "individual",
        "deactivated": False,
        "is_default": True,
        "management_type": "self_directed",
        "nickname": None,
        "option_level": "none",
        "permanently_deactivated": False,
        "rhc_account_number": None,
        "rhs_account_number": "synthetic-brokerage-account",
        "state": "active",
        "type": "cash",
    }
    value.update(overrides)  # type: ignore[arg-type]
    return value


def accounts_response(*account_numbers: str) -> dict[str, JsonValue]:
    return {
        "data": {"accounts": [account_payload(value) for value in account_numbers]},
        "guide": "synthetic-read-shape",
    }


def portfolio_response() -> dict[str, JsonValue]:
    return {
        "data": {
            "buying_power": {
                "buying_power": "125.50",
                "display_currency": "USD",
                "unleveraged_buying_power": "125.50",
            },
            "cash": "125.50",
            "crypto_value": "0",
            "currency": "USD",
            "equity_value": "125.50",
            "event_contracts_value": "0",
            "fixed_income_value": "0",
            "futures_value": "0",
            "mutual_funds_value": "0",
            "options_value": "0",
            "pending_deposits": "0",
            "total_value": "125.50",
        },
        "guide": "synthetic-read-shape",
    }


def quote_response(**overrides: JsonValue) -> dict[str, JsonValue]:
    quote: dict[str, JsonValue] = {
        "adjusted_previous_close": "99.50",
        "ask_price": "101.00",
        "bid_price": "100.00",
        "has_traded": True,
        "last_non_reg_trade_price": "100.75",
        "last_trade_price": "100.50",
        "previous_close": "99.50",
        "previous_close_date": "2026-07-20",
        "state": "active",
        "symbol": str(INSTRUMENT),
        "venue_ask_time": "2026-07-21T17:59:59Z",
        "venue_bid_time": "2026-07-21T17:59:58Z",
        "venue_last_non_reg_trade_time": "2026-07-21T17:59:59Z",
        "venue_last_trade_time": "2026-07-21T17:59:58Z",
    }
    quote.update(overrides)
    return {
        "data": {
            "results": [
                {
                    "close": {
                        "date": "2026-07-20",
                        "interpolated": False,
                        "price": "99.50",
                        "source": "synthetic",
                        "symbol": str(INSTRUMENT),
                    },
                    "quote": quote,
                }
            ],
            "closes_error": None,
        },
        "guide": "synthetic-read-shape",
    }


def historical_response(
    *,
    bars: list[dict[str, JsonValue]] | None = None,
) -> dict[str, JsonValue]:
    if bars is None:
        bars = [
            {
                "begins_at": "2026-07-19T00:00:00Z",
                "close_price": "101.00",
                "high_price": "102.00",
                "interpolated": False,
                "low_price": "99.00",
                "open_price": "100.00",
                "session": "reg",
                "volume": 1200,
            },
            {
                "begins_at": "2026-07-20T00:00:00Z",
                "close_price": "102.00",
                "high_price": "103.00",
                "interpolated": False,
                "low_price": "100.00",
                "open_price": "101.00",
                "session": "reg",
                "volume": 1300,
            },
        ]
    return {
        "data": {
            "results": [
                {
                    "bars": bars,
                    "bounds": "regular",
                    "interval": "day",
                    "symbol": str(INSTRUMENT),
                }
            ],
            "not_found": None,
        },
        "guide": "synthetic-read-shape",
    }


def read_adapter(
    transport: RobinhoodMcpTransport,
    account_id: AccountId,
) -> RobinhoodEquityReadAdapter:
    return RobinhoodEquityReadAdapter(
        transport,
        FixedClock(),
        expected_account_fingerprint=account_fingerprint(account_id),
    )


@pytest.mark.asyncio
async def test_account_fingerprint_selects_exactly_one_account_for_portfolio(
    tmp_path: Path,
) -> None:
    selected = AccountId("synthetic-selected-account")
    transport, session = transport_for(
        tmp_path,
        {
            "get_accounts": accounts_response("synthetic-other-account", str(selected)),
            "get_portfolio": portfolio_response(),
        },
    )

    accounts = await read_adapter(transport, selected).get_accounts()

    assert len(accounts) == 1
    assert accounts[0].account_id == selected
    assert accounts[0].equity == Decimal("125.50")
    assert session.calls == [
        ("get_accounts", {}),
        ("get_portfolio", {"account_number": str(selected)}),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("selected_count", (0, 2))
async def test_account_fingerprint_selection_fails_if_not_unique(
    tmp_path: Path,
    selected_count: int,
) -> None:
    selected = AccountId("synthetic-selected-account")
    numbers = ("synthetic-other-account",) + (str(selected),) * selected_count
    transport, _ = transport_for(tmp_path, {"get_accounts": accounts_response(*numbers)})

    with pytest.raises(EquityReadError, match="not unique"):
        await read_adapter(transport, selected).get_accounts()


@pytest.mark.asyncio
async def test_authenticated_empty_positions_and_orders_are_supported(tmp_path: Path) -> None:
    account_id = AccountId("synthetic-selected-account")
    transport, session = transport_for(
        tmp_path,
        {
            "get_equity_positions": {
                "data": {"positions": [], "next": None},
                "guide": "synthetic-read-shape",
            },
            "get_equity_orders": {
                "data": {"orders": [], "next": None},
                "guide": "synthetic-read-shape",
            },
        },
    )
    adapter = read_adapter(transport, account_id)

    assert await adapter.get_positions(account_id) == ()
    assert await adapter.get_open_orders(account_id) == ()
    assert session.calls == [
        ("get_equity_positions", {"account_number": str(account_id)}),
        ("get_equity_orders", {"account_number": str(account_id)}),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "collection_name"),
    (
        ("get_equity_positions", "positions"),
        ("get_equity_orders", "orders"),
    ),
)
async def test_nonempty_authenticated_collection_fails_closed(
    tmp_path: Path,
    tool_name: str,
    collection_name: str,
) -> None:
    account_id = AccountId("synthetic-selected-account")
    transport, _ = transport_for(
        tmp_path,
        {
            tool_name: {
                "data": {collection_name: [{"unreviewed": "row"}], "next": None},
                "guide": "synthetic-read-shape",
            }
        },
    )
    adapter = read_adapter(transport, account_id)

    with pytest.raises(UnverifiedNonemptyShape, match="authenticated review"):
        if tool_name == "get_equity_positions":
            await adapter.get_positions(account_id)
        else:
            await adapter.get_open_orders(account_id)


@pytest.mark.asyncio
async def test_quote_and_historical_reads_validate_reviewed_shapes(tmp_path: Path) -> None:
    transport, session = transport_for(
        tmp_path,
        {
            "get_equity_quotes": quote_response(),
            "get_equity_historicals": historical_response(),
        },
    )
    market_data = RobinhoodEquityMarketData(
        transport,
        FixedClock(),
        maximum_quote_age=timedelta(seconds=5),
    )

    quote = await market_data.get_quote(INSTRUMENT)
    bars = await market_data.get_bars(
        INSTRUMENT,
        BarInterval.ONE_DAY,
        datetime(2026, 7, 19, tzinfo=UTC),
        datetime(2026, 7, 21, tzinfo=UTC),
    )

    assert (quote.bid, quote.ask, quote.last) == (
        Decimal("100.00"),
        Decimal("101.00"),
        Decimal("100.75"),
    )
    assert tuple(item.close for item in bars) == (Decimal("101.00"), Decimal("102.00"))
    assert all(item.interval is BarInterval.ONE_DAY for item in bars)
    assert session.calls[0] == ("get_equity_quotes", {"symbols": [str(INSTRUMENT)]})
    assert session.calls[1][0] == "get_equity_historicals"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    (
        {"unreviewed_provider_field": "value"},
        {"bid_price": 100},
        {"symbol": "WRONG"},
        {"venue_bid_time": "2026-07-21T17:59:00Z"},
    ),
)
async def test_quote_shape_or_semantic_drift_fails_closed(
    tmp_path: Path,
    overrides: dict[str, JsonValue],
) -> None:
    transport, _ = transport_for(tmp_path, {"get_equity_quotes": quote_response(**overrides)})
    market_data = RobinhoodEquityMarketData(
        transport,
        FixedClock(),
        maximum_quote_age=timedelta(seconds=5),
    )

    with pytest.raises(MarketDataCapabilityError):
        await market_data.get_quote(INSTRUMENT)


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ("coerced_volume", "reordered", "extra_field"))
async def test_historical_shape_or_ordering_drift_fails_closed(
    tmp_path: Path,
    drift: str,
) -> None:
    bars = historical_response()["data"]["results"][0]["bars"]  # type: ignore[index]
    assert isinstance(bars, list)
    copied = [dict(item) for item in bars]
    if drift == "coerced_volume":
        copied[0]["volume"] = "1200"
    elif drift == "reordered":
        copied.reverse()
    else:
        copied[0]["unreviewed_provider_field"] = "value"
    transport, _ = transport_for(
        tmp_path,
        {"get_equity_historicals": historical_response(bars=copied)},
    )
    market_data = RobinhoodEquityMarketData(
        transport,
        FixedClock(),
        maximum_quote_age=timedelta(seconds=5),
    )

    with pytest.raises(MarketDataCapabilityError):
        await market_data.get_bars(
            INSTRUMENT,
            BarInterval.ONE_DAY,
            datetime(2026, 7, 19, tzinfo=UTC),
            datetime(2026, 7, 21, tzinfo=UTC),
        )
