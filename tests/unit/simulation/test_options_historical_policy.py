"""Pure policy composition tests; source verification is tested separately."""

import importlib
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.unit.market_data.test_databento_batch import no_network  # noqa: F401
from tests.unit.simulation.test_options_historical_clock import attach_calendar, setup
from trading_bot.domain import Bar, InstrumentId
from trading_bot.domain.enums import BarInterval
from trading_bot.domain.options import OptionKind
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation.options_historical_models import AccountSettlement
from trading_bot.strategies.protocol import HistoricalSlice, StrategyAction


def api():
    try:
        return importlib.import_module("trading_bot.simulation.options_historical_policy")
    except ModuleNotFoundError:
        pytest.fail("historical research policy owner is not implemented")


def history(at, *, rising=True, count=750):
    bars = []
    for n in range(count):
        close = Decimal(1000 + n if rising else 2000 - n)
        end = at - timedelta(days=count - n, hours=1)
        bars.append(
            Bar(
                InstrumentId("SPY"),
                BarInterval.ONE_DAY,
                end - timedelta(hours=6),
                end,
                close,
                close,
                close,
                close,
                Decimal("10000"),
                "synthetic.daily",
                content_hash(("bar", n, close)),
            )
        )
    return HistoricalSlice(InstrumentId("SPY"), tuple(bars), None, content_hash(tuple(bars)))


@pytest.mark.parametrize("rising,kind", [(True, OptionKind.CALL), (False, OptionKind.PUT)])
def test_shared_features_and_directional_strategy_are_used(tmp_path, monkeypatch, rising, kind):
    clock, order, _ = setup(tmp_path, monkeypatch)
    decisions = api().historical_signal(
        history(order.created_at, rising=rising), at=order.created_at, loaded=clock.loaded
    )
    assert len(decisions) == 2
    assert next(d for k, d in decisions if k is kind).action is StrategyAction.ENTER_LONG
    assert next(d for k, d in decisions if k is not kind).action is StrategyAction.HOLD


def test_short_history_does_not_relax_canonical_research_minimum(tmp_path, monkeypatch):
    clock, order, _ = setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        api().historical_signal(
            history(order.created_at, count=100), at=order.created_at, loaded=clock.loaded
        )


@pytest.mark.parametrize("capital,allowed", [("100", False), ("10000", True)])
def test_research_policy_honors_capital_and_all_outer_limits(
    tmp_path, monkeypatch, capital, allowed
):
    clock, order, events = setup(tmp_path, monkeypatch)
    c = order.structure.legs[0].contract
    cal = attach_calendar(clock, order)
    state = replace(clock.initial, authorized_capital=Decimal(capital), cash=Decimal(capital))
    quote = replace(events[0].record.value, bid=Decimal("0.09"), ask=Decimal("0.10"))
    report = api().evaluate_historical_entry(
        state=state,
        contract=c,
        quote=quote,
        calendar=cal,
        session=c.eligible_sessions[0],
        at=quote.received_at,
        scenario=clock.scenario,
        loaded=clock.loaded,
        loss_reasons=(),
    )
    assert (not report) is allowed
    if not allowed:
        assert "per_trade_risk" in report


def test_legacy_order_cap_is_not_overridden_by_hypothetical_capital(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    cal = attach_calendar(clock, order)
    assert "legacy_order_notional" in api().evaluate_historical_entry(
        state=clock.initial,
        contract=order.structure.legs[0].contract,
        quote=events[0].record.value,
        calendar=cal,
        session=order.structure.legs[0].contract.eligible_sessions[0],
        at=events[0].record.available_at,
        scenario=clock.scenario,
        loaded=clock.loaded,
        loss_reasons=(),
    )


def test_loss_halts_and_incidents_cannot_be_ignored(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    cal = attach_calendar(clock, order)
    state = replace(clock.initial, incidents=("unexpected_shares",), latched_halts=("drawdown",))
    reasons = api().evaluate_historical_entry(
        state=state,
        contract=order.structure.legs[0].contract,
        quote=events[0].record.value,
        calendar=cal,
        session=order.structure.legs[0].contract.eligible_sessions[0],
        at=events[0].record.available_at,
        scenario=clock.scenario,
        loaded=clock.loaded,
        loss_reasons=("weekly_loss_latched",),
    )
    assert {"unexpected_shares", "drawdown", "weekly_loss_latched"} <= set(reasons)


@pytest.mark.parametrize("boundary", ["before_open", "at_close", "ineligible_session"])
def test_entries_outside_the_supplied_eligible_session_are_denied(tmp_path, monkeypatch, boundary):
    clock, order, events = setup(tmp_path, monkeypatch)
    contract = order.structure.legs[0].contract
    calendar = attach_calendar(clock, order)
    session = contract.eligible_sessions[0]
    at = session.opens_at
    if boundary == "before_open":
        at -= timedelta(microseconds=1)
    elif boundary == "at_close":
        at = session.closes_at
    else:
        session = replace(session, session_id="unapproved-session")
    quote = replace(
        events[0].record.value,
        bid=Decimal("0.09"),
        ask=Decimal("0.10"),
        event_at=at,
        received_at=at,
        underlying_event_at=at,
    )

    reasons = api().evaluate_historical_entry(
        state=clock.initial,
        contract=contract,
        quote=quote,
        calendar=calendar,
        session=session,
        at=at,
        scenario=clock.scenario,
        loaded=clock.loaded,
        loss_reasons=(),
    )

    assert "outside_session" in reasons


@pytest.mark.parametrize(
    "cash,external_flows", [("0", "0"), ("10000", "10000"), ("10000", "10001")]
)
def test_zero_adjusted_risk_capital_returns_a_denial_without_invalid_capital_construction(
    tmp_path, monkeypatch, cash, external_flows
):
    clock, order, events = setup(tmp_path, monkeypatch)
    calendar = attach_calendar(clock, order)
    state = replace(
        clock.initial, cash=Decimal(cash), cumulative_external_flows=Decimal(external_flows)
    )
    quote = replace(events[0].record.value, bid=Decimal("0.09"), ask=Decimal("0.10"))
    assert state.risk_capital == 0

    reasons = api().evaluate_historical_entry(
        state=state,
        contract=order.structure.legs[0].contract,
        quote=quote,
        calendar=calendar,
        session=order.structure.legs[0].contract.eligible_sessions[0],
        at=quote.received_at,
        scenario=clock.scenario,
        loaded=clock.loaded,
        loss_reasons=(),
    )

    assert reasons == ("capital_unavailable",)


def test_positive_book_capital_does_not_allow_negative_available_cash(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    calendar = attach_calendar(clock, order)
    state = replace(
        clock.initial,
        unsettled=(
            AccountSettlement(
                "unsettled-proceeds", "prior-episode", Decimal("10001"), clock.now_ns + 1
            ),
        ),
    )
    quote = replace(events[0].record.value, bid=Decimal("0.09"), ask=Decimal("0.10"))
    assert state.risk_capital == Decimal("10000")
    assert state.available_cash == Decimal("-1")

    reasons = api().evaluate_historical_entry(
        state=state,
        contract=order.structure.legs[0].contract,
        quote=quote,
        calendar=calendar,
        session=order.structure.legs[0].contract.eligible_sessions[0],
        at=quote.received_at,
        scenario=clock.scenario,
        loaded=clock.loaded,
        loss_reasons=(),
    )

    assert reasons == ("capital_unavailable",)


@pytest.mark.parametrize("bid,ask", [("0.091", "0.10"), ("0.09", "0.101")])
def test_either_off_tick_quote_side_denies_entry(tmp_path, monkeypatch, bid, ask):
    clock, order, events = setup(tmp_path, monkeypatch)
    calendar = attach_calendar(clock, order)
    quote = replace(events[0].record.value, bid=Decimal(bid), ask=Decimal(ask))

    reasons = api().evaluate_historical_entry(
        state=clock.initial,
        contract=order.structure.legs[0].contract,
        quote=quote,
        calendar=calendar,
        session=order.structure.legs[0].contract.eligible_sessions[0],
        at=quote.received_at,
        scenario=clock.scenario,
        loaded=clock.loaded,
        loss_reasons=(),
    )

    assert reasons == ("invalid_option_tick", "off_tick")


def test_zero_bid_quote_denies_entry_even_with_affordable_ask(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    calendar = attach_calendar(clock, order)
    quote = replace(events[0].record.value, bid=Decimal("0"), ask=Decimal("0.10"))

    reasons = api().evaluate_historical_entry(
        state=clock.initial,
        contract=order.structure.legs[0].contract,
        quote=quote,
        calendar=calendar,
        session=order.structure.legs[0].contract.eligible_sessions[0],
        at=quote.received_at,
        scenario=clock.scenario,
        loaded=clock.loaded,
        loss_reasons=(),
    )

    assert reasons == ("zero_bid",)
