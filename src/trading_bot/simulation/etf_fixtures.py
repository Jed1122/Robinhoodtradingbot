"""Operator-visible fabricated ETF lifecycle examples, never market evidence."""

from dataclasses import replace
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
    MarketClock,
    OrderEvent,
    OrderIntent,
    OrderIntentId,
    OrderPurpose,
    OrderType,
    Quote,
    Side,
    TimeInForce,
    TimestampSource,
)
from trading_bot.market_data.etf_source import EtfObservedQuote, EtfSessionEvent, _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_costs import EtfCostEvidence, EtfCostInterval
from trading_bot.research.etf_study import EtfStudy
from trading_bot.simulation.etf_account import EtfAccountEvent, EtfAccountRequest
from trading_bot.simulation.etf_fixture_execution import (
    EtfFixtureAccountObservation,
    EtfFixtureExecutionObservation,
    EtfFixtureExecutionRequest,
)

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


def synthetic_etf_quote_request(
    study: EtfStudy, cash: Decimal, scenario: str = "full"
) -> EtfFixtureExecutionRequest:
    """One fabricated reserved order; not a strategy opportunity or real quote."""
    if scenario not in ("full", "partial", "pending_ack"):
        raise ValueError("etf_fixture_invalid")
    original = synthetic_etf_account_request(study, cash, "open").events[0]
    if original.intent is None:
        raise ValueError("etf_fixture_invalid")
    order = replace(
        original.intent,
        limit_price=Decimal("100.1"),
        data_hash=content_hash("etf-quote-fixture-intent-v1"),
    )
    pending = replace(
        original,
        event_id=content_hash(("etf-quote-fixture-pending-v1", order)),
        kind="pending_intent",
        intent=order,
        fee_bound=Decimal(".1"),
    )
    account = EtfAccountRequest(study, cash, (pending,))
    ordinal = 0 if scenario == "pending_ack" else 1
    clock_at = _NOW + timedelta(milliseconds=2)
    clock = EtfSessionEvent(
        content_hash("etf-quote-fixture-clock-v1"),
        ordinal,
        _ns(clock_at),
        _ns(clock_at),
        _SPY,
        None,
        MarketClock(
            AssetClass.EQUITY,
            "XNYS",
            clock_at,
            True,
            False,
            False,
            False,
            _NOW + timedelta(days=1),
            _NOW + timedelta(hours=1),
        ),
    )
    at = _NOW + timedelta(milliseconds=10)
    digest = content_hash(("etf-quote-fixture-quote-v1", scenario))
    size = Decimal(".04") if scenario == "partial" else Decimal(".1")
    quote = EtfObservedQuote(
        digest,
        ordinal + 1,
        _ns(at),
        _ns(at),
        _SPY,
        None,
        Quote(
            _SPY,
            at,
            Decimal("99.99"),
            Decimal("100"),
            None,
            "synthetic",
            digest,
            False,
            TimestampSource.SIMULATED,
        ),
        size,
        size,
    )
    observations: tuple[EtfFixtureExecutionObservation, ...] = (clock, quote)
    if scenario != "pending_ack":
        accepted = EtfFixtureAccountObservation(
            0,
            EtfAccountEvent(
                content_hash("etf-quote-fixture-acceptance-v1"),
                1,
                _ns(_NOW + timedelta(milliseconds=1)),
                "order_status",
                order_id=str(order.id),
                order_event=OrderEvent.BROKER_ACCEPTED,
            ),
        )
        observations = (accepted, *observations)
    roles = (
        ("commission_per_share", "USD/share", ".02"),
        ("minimum_commission", "USD/order", ".03"),
        ("regulatory_per_notional", "USD/USD", ".0001"),
        ("extra_slippage", "bps", "0"),
        ("latency", "seconds", ".01"),
        ("cash_rate", "whole_percent/year", "0"),
        ("operating_cost", "USD/day", "0"),
    )
    costs = EtfCostEvidence(
        tuple(
            EtfCostInterval(
                role,
                unit,
                Decimal(value),
                "USD",
                _NOW - timedelta(days=1),
                _NOW + timedelta(days=2),
                _NOW - timedelta(days=2),
                content_hash(("etf-quote-fixture-cost-v1", role, value)),
            )
            for role, unit, value in roles
        ),
        "synthetic",
        (),
    )
    return EtfFixtureExecutionRequest(account, observations, costs, str(order.id))
