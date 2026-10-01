"""Operator-visible fabricated ETF lifecycle examples, never market evidence."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_bot.domain import (
    AccountId,
    AssetClass,
    BrokerOrderId,
    ConfigHash,
    Fill,
    FillId,
    Instrument,
    InstrumentId,
    OrderIntent,
    OrderIntentId,
    OrderPurpose,
    OrderType,
    Side,
    TimeInForce,
)
from trading_bot.market_data.etf_source import _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_study import EtfStudy
from trading_bot.simulation.etf_account import EtfAccountEvent, EtfAccountRequest

_NOW = datetime(2019, 1, 2, 15, tzinfo=UTC)
_ACCOUNT = AccountId("etf-offline")
_SPY = InstrumentId("SPY")


def synthetic_etf_account_request(
    study: EtfStudy, cash: Decimal, scenario: str = "completed"
) -> EtfAccountRequest:
    if scenario not in ("completed", "open", "pending_settlement"):
        raise ValueError("etf_fixture_invalid")
    instrument = Instrument(
        _SPY,
        "SPY",
        AssetClass.EQUITY,
        "synthetic",
        True,
        True,
        Decimal(".01"),
        Decimal(".001"),
        Decimal(".001"),
        Decimal("1"),
        None,
        "US-equity",
        _NOW,
        content_hash("etf-synthetic-instrument-v1"),
    )

    def order(name: str, side: Side, price: Decimal, seconds: int) -> OrderIntent:
        at = _NOW + timedelta(seconds=seconds)
        return OrderIntent(
            OrderIntentId(name),
            _ACCOUNT,
            _SPY,
            AssetClass.EQUITY,
            side,
            OrderPurpose.ENTRY if side is Side.BUY else OrderPurpose.PROTECTIVE_EXIT,
            OrderType.LIMIT,
            TimeInForce.GOOD_FOR_DAY,
            Decimal(".1"),
            price,
            None,
            at,
            at + timedelta(hours=1),
            study.policy_id,
            ConfigHash(study.config_hash),
            content_hash(("etf-fixture-intent", name)),
            "etf-fixture-exit-v1",
        )

    buy, sell = (
        order("etf-entry", Side.BUY, Decimal("100"), 0),
        order("etf-exit", Side.SELL, Decimal("101"), 5),
    )
    events = []
    for ordinal, seconds, kind, fields in (
        (
            0,
            0,
            "intent",
            {
                "intent": buy,
                "instrument": instrument,
                "stop_distance": Decimal("1"),
                "fee_bound": Decimal(".02"),
            },
        ),
        (
            1,
            1,
            "fill",
            {
                "fill": Fill(
                    FillId("buy"),
                    BrokerOrderId(buy.id),
                    _ACCOUNT,
                    _SPY,
                    Side.BUY,
                    Decimal(".1"),
                    Decimal("100"),
                    Decimal(".01"),
                    _NOW + timedelta(seconds=1),
                    content_hash("buy"),
                )
            },
        ),
        (2, 2, "settlement", {"fill_ids": ("buy",)}),
        (
            3,
            3,
            "dividend_ex",
            {"action_id": content_hash("fixture-distribution"), "cash_per_share": Decimal(".2")},
        ),
        (4, 4, "dividend_pay", {"action_id": content_hash("fixture-distribution")}),
        (
            5,
            5,
            "intent",
            {
                "intent": sell,
                "instrument": instrument,
                "stop_distance": Decimal("1"),
                "fee_bound": Decimal(".02"),
            },
        ),
        (
            6,
            6,
            "fill",
            {
                "fill": Fill(
                    FillId("sell"),
                    BrokerOrderId(sell.id),
                    _ACCOUNT,
                    _SPY,
                    Side.SELL,
                    Decimal(".1"),
                    Decimal("101"),
                    Decimal(".01"),
                    _NOW + timedelta(seconds=6),
                    content_hash("sell"),
                )
            },
        ),
        (7, 7, "settlement", {"fill_ids": ("sell",)}),
    ):
        events.append(
            EtfAccountEvent(
                content_hash(("etf-fixture-event", ordinal)),
                ordinal,
                _ns(_NOW + timedelta(seconds=seconds)),
                kind,
                **fields,
            )
        )
    count = 2 if scenario == "open" else 7 if scenario == "pending_settlement" else 8
    return EtfAccountRequest(study, cash, tuple(events[:count]))
