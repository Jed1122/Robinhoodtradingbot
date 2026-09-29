"""Modeled timeline composition; no source, strategy or risk-admission certification."""

import importlib
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.unit.market_data.test_databento_batch import no_network  # noqa: F401
from tests.unit.research.test_options_study_registration import config
from tests.unit.simulation.test_options_historical_execution import arrangement, scenario
from trading_bot.domain.enums import OrderState, Side
from trading_bot.domain.options import OptionLeg, OptionStructure, PositionEffect
from trading_bot.lifecycle.options_expiry import OptionExpiryCalendar
from trading_bot.market_data.options_session_inputs import _ns
from trading_bot.market_data.options_source_verify import ceil_available_at
from trading_bot.market_data.recording import content_hash
from trading_bot.research.options_account_journal import initial_account_path
from trading_bot.research.options_account_journal_models import JournalOrderUpdate

D = Decimal


def setup(tmp_path, monkeypatch, *, assumptions=None, units=1, duration=10000):
    try:
        module = importlib.import_module("trading_bot.simulation.options_historical_clock")
    except ModuleNotFoundError:
        pytest.fail("historical lifecycle clock is not implemented")
    _, proposed, events = arrangement(tmp_path, monkeypatch, units=units)
    loaded, assumptions = config(), assumptions or scenario()
    initial = initial_account_path(
        study_hash=content_hash("fabricated-clock-study"),
        capital=D("10000"),
        start_ns=proposed.order.decision_ns,
        loaded=loaded,
        scenario=assumptions,
    )
    at = initial.start_ns
    intent = replace(
        proposed.order.intent,
        account_scope=initial.path_id,
        config_hash=loaded.config_hash,
        expires_at=ceil_available_at(at + duration),
    )
    clock = module._EpisodeClock(initial, (), loaded=loaded, scenario=assumptions, seed=7)
    return clock, intent, events


def submit(clock, order, *, at=None):
    clock.submit(
        "episode-1",
        order.structure.legs[0].contract.eligible_sessions[0].session_id,
        order,
        available_ns=clock.now_ns if at is None else at,
    )


def closing(order, at, *, units=1):
    leg = order.structure.legs[0]
    return replace(
        order,
        intent_id="fixture-close",
        created_at=ceil_available_at(at),
        limit_price=D("0.20"),
        quantity=units,
        net_effect="credit",
        structure=OptionStructure(
            order.structure.kind, (OptionLeg(leg.contract, Side.SELL, PositionEffect.CLOSE, 1),)
        ),
    )


def test_exact_cash_and_settlement_are_separate_from_end_of_quotes(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    submit(clock, order)
    clock.advance(events[0])
    clock.advance(events[1])
    submit(clock, closing(order, events[1].available_ns), at=events[1].available_ns)
    clock.advance(events[2])
    clock.advance(events[3])
    pending = clock.result()
    assert pending.net_cash_flow == D("-6.00") and pending.fees == D("1.00")
    assert pending.state.cash == D("9994.00")
    assert pending.state.trial.reserved_risk == D("26.00")
    assert pending.status == "incomplete" and "settlement_pending" in pending.reasons
    assert pending.reconciliation_reasons == ()
    clock.advance_time(events[3].available_ns + 10)
    result = clock.result()
    assert result.status == "completed"
    assert result.state.trial.consumed_loss == D("6.00")
    assert result.state.trial.reserved_risk == 0
    assert result.net_cash_flow == D("-6.00") and result.fees == D("1.00")
    assert not result.production_eligible and not result.economic_eligible


def test_open_position_never_forces_an_end_fill(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    submit(clock, order)
    for event in events:
        clock.advance(event)
    clock.advance_time(events[-1].available_ns + 1000)
    result = clock.result()
    assert result.status == "incomplete" and "open_position" in result.reasons
    assert result.state.positions[0].units == 1
    assert result.net_cash_flow == D("-25.50")
    assert result.state.trial.reserved_risk == D("26")


@pytest.mark.parametrize(
    "field,status,reason",
    [
        ("reject_ppm", "completed", None),
        ("unfilled_ppm", "completed", None),
        ("ambiguous_ppm", "incomplete", "unknown_order"),
    ],
)
def test_order_outcomes_do_not_invent_acceptance_or_losses(
    tmp_path, monkeypatch, field, status, reason
):
    clock, order, events = setup(tmp_path, monkeypatch, assumptions=scenario(**{field: 1000000}))
    submit(clock, order)
    for event in events:
        clock.advance(event)
    clock.advance_time(_ns(order.expires_at))
    result = clock.result()
    assert result.status == status and result.net_cash_flow == 0 and result.fees == 0
    assert result.state.trial.consumed_loss == 0
    if reason:
        assert reason in result.reasons and result.state.trial.reserved_risk == D("26")
    else:
        assert result.state.trial.reserved_risk == 0


def test_unacknowledged_submission_stays_unknown_after_deadline(tmp_path, monkeypatch):
    clock, order, events = setup(
        tmp_path, monkeypatch, assumptions=scenario(acknowledgement_ns=10000)
    )
    submit(clock, order)
    clock.advance_time(_ns(order.expires_at))
    assert clock.result().status == "incomplete"
    assert clock.result().orders[0].state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION
    clock.advance(
        replace(
            events[-1],
            available_ns=_ns(order.expires_at) + 1,
            record=None,
            state="gap",
            record_ordinal=None,
        )
    )
    assert clock.result().orders[0].state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION


def test_cancel_race_fill_then_cancel_is_one_journaled_quantity(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch, units=5)
    submit(clock, order)
    clock.advance(events[0])
    clock.cancel(order.intent_id, available_ns=events[0].available_ns)
    clock.advance(events[2])
    result = clock.result()
    assert result.orders[0].state is OrderState.CANCELED
    assert result.state.positions[0].units == 3
    assert result.net_cash_flow == D("-76.50") and result.fees == D("1.50")
    assert result.reconciliation_reasons == ()
    clock.advance(events[3])
    assert clock.result().net_cash_flow == D("-76.50")


def test_expiry_precedes_quote_at_exact_day_deadline(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch, duration=1000)
    submit(clock, order)
    clock.advance(events[0])
    future = replace(
        events[1],
        event_ns=_ns(order.expires_at),
        available_ns=_ns(order.expires_at),
        record=None,
        state="session_boundary",
        record_ordinal=None,
    )
    clock.advance(future)
    result = clock.result()
    assert result.orders[0].state is OrderState.EXPIRED and result.net_cash_flow == 0
    assert result.status == "completed"


def test_duplicate_event_and_backward_clock_are_fail_safe(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    submit(clock, order)
    clock.advance(events[0])
    clock.advance(events[1])
    before = clock.result()
    clock.advance(events[1])
    assert clock.result() == before
    with pytest.raises(ValueError):
        clock.advance(events[0])
    with pytest.raises(ValueError):
        clock.advance_time(clock.now_ns - 1)


def test_reconstructed_prefix_not_supplied_cash_is_restart_authority(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    submit(clock, order)
    clock.advance(events[0])
    clock.advance(events[1])
    result = clock.result()
    module = importlib.import_module("trading_bot.simulation.options_historical_clock")
    restored = module._EpisodeClock(
        clock.initial, result.journal, loaded=clock.loaded, scenario=clock.scenario, seed=7
    )
    assert restored.result().state == result.state
    assert restored.result().net_cash_flow == 0  # this invocation's delta, not history reset
    assert restored.result().state.trial.reserved_risk == D("26")
    assert restored.result().orders[0].state is OrderState.FILLED
    with pytest.raises(ValueError):
        module._EpisodeClock(
            replace(clock.initial, cash=D("20000")),
            result.journal,
            loaded=clock.loaded,
            scenario=clock.scenario,
            seed=7,
        )


def test_pending_order_restart_requires_execution_cursor_not_invented_ack(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    submit(clock, order)
    clock.advance(events[0])
    module = importlib.import_module("trading_bot.simulation.options_historical_clock")
    with pytest.raises(ValueError):
        module._EpisodeClock(
            clock.initial,
            clock.result().journal,
            loaded=clock.loaded,
            scenario=clock.scenario,
            seed=7,
        )


def test_failed_close_leaves_existing_position_and_full_trial_reservation(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    submit(clock, order)
    clock.advance(events[0])
    clock.advance(events[1])
    with pytest.raises(ValueError):
        submit(clock, closing(order, events[1].available_ns, units=2), at=events[1].available_ns)
    assert clock.result().state.positions[0].units == 1
    assert len(clock.result().orders) == 1


def test_journal_fill_facts_contain_no_supplied_cash_delta(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    submit(clock, order)
    clock.advance(events[0])
    clock.advance(events[1])
    fact = next(
        e.fact
        for e in clock.result().journal
        if isinstance(e.fact, JournalOrderUpdate) and e.fact.fill_units
    )
    assert fact.price == D("0.25") and fact.fill_units == 1
    assert not hasattr(fact, "cash_flow")


def attach_calendar(clock, order):
    from trading_bot.domain.options import OptionSession

    contract = order.structure.legs[0].contract
    last_close = contract.last_trading_at
    last_open = last_close - timedelta(hours=6, minutes=30)
    last = OptionSession(
        "expiry-last", last_open, last_close, last_close.date(), "America/New_York"
    )
    prior = OptionSession(
        "expiry-prior",
        last_open - timedelta(days=1),
        last_close - timedelta(days=1),
        (last_close - timedelta(days=1)).date(),
        "America/New_York",
    )
    calendar = OptionExpiryCalendar(
        contract.contract_id,
        contract.eligible_sessions[0].trading_date,
        contract.expiration,
        (contract.eligible_sessions[0], prior, last),
        True,
        order.created_at,
        content_hash("fabricated-expiry-calendar"),
    )
    clock.watch_expiry(contract, calendar)
    return calendar


def test_expiry_exit_session_and_missed_deadline_never_invent_a_sale(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    calendar = attach_calendar(clock, order)
    submit(clock, order)
    clock.advance(events[0])
    clock.advance(events[1])
    clock.advance_time(_ns(calendar.sessions[-2].opens_at))
    assert clock.result().expiry[0].reasons == ("expiry_exit_session",)
    assert not clock.result().state.incidents
    clock.advance_time(_ns(calendar.sessions[-2].closes_at) + 1000)
    result = clock.result()
    assert "expiry_exit_deadline_reached" in result.state.incidents
    assert result.status == "incomplete" and result.state.positions[0].units == 1
    assert result.state.trial.reserved_risk == D("26")
    incident = next(
        e
        for e in result.journal
        if getattr(e.fact, "reason", None) == "expiry_exit_deadline_reached"
    )
    assert incident.available_ns == _ns(calendar.sessions[-2].closes_at)


def test_unknown_order_and_missing_calendar_cannot_clear_expiry(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch, assumptions=scenario(ambiguous_ppm=1000000))
    submit(clock, order)
    clock.advance(events[0])
    result = clock.result()
    assert result.expiry[0].reasons == ("expiry_calendar_unverified",)
    assert "expiry_calendar_unverified" in result.reasons
    assert result.status == "incomplete"


def test_same_calendar_is_idempotent_but_changed_contract_or_calendar_denies(tmp_path, monkeypatch):
    clock, order, _ = setup(tmp_path, monkeypatch)
    calendar = attach_calendar(clock, order)
    c = order.structure.legs[0].contract
    clock.watch_expiry(c, calendar)
    with pytest.raises(ValueError):
        clock.watch_expiry(c, replace(calendar, complete=False))
    with pytest.raises(ValueError):
        clock.watch_expiry(replace(c, tick_size=D("0.02")), calendar)


def test_cancel_timer_without_later_quotes_releases_only_unfilled_remainder(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    submit(clock, order)
    clock.advance(events[0])
    clock.cancel(order.intent_id, available_ns=events[0].available_ns)
    clock.advance_time(events[0].available_ns + 2)
    result = clock.result()
    assert result.orders[0].state is OrderState.CANCELED and result.status == "completed"
    assert result.net_cash_flow == 0
    clock.advance_time(_ns(order.expires_at))
    assert clock.result().orders[0].state is OrderState.CANCELED


def test_result_without_orders_is_empty_not_a_completed_trade(tmp_path, monkeypatch):
    clock, _, _ = setup(tmp_path, monkeypatch)
    assert clock.result().status == "empty" and clock.result().net_cash_flow == 0


def test_execution_cash_projection_is_independently_reconciled(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    submit(clock, order)
    clock.advance(events[0])
    clock.advance(events[1])
    clock._cash = D("100")  # fault injection into the execution aggregate, not accounting facts
    assert "cash_flow_mismatch" in clock.result().reconciliation_reasons
    assert clock.result().state.cash == D("9974.50")


def two_orders(clock, order):
    submit(clock, order)
    second = replace(order, intent_id="second-order")
    clock.submit("episode-2", "same-session", second, available_ns=clock.now_ns)


def test_shared_observation_liquidity_cannot_be_reused_between_orders(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch, units=3)
    two_orders(clock, order)
    clock.advance(events[0])
    clock.advance(events[1])
    result = clock.result()
    assert sum(o.filled_units for o in result.orders) == 3
    assert result.net_cash_flow == D("-76.50")
    assert result.orders[1].state is OrderState.SUBMITTED


def test_failed_event_rolls_back_partial_accounting_and_liquidity(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    two_orders(clock, order)
    clock.advance(events[0])
    before = clock.result()
    module = importlib.import_module("trading_bot.simulation.options_historical_clock")
    real = module.advance_order

    def fail_second(current, event, **kwargs):
        step = real(current, event, **kwargs)
        return replace(step, fee=D("99")) if current.intent.intent_id == "second-order" else step

    monkeypatch.setattr(module, "advance_order", fail_second)
    with pytest.raises(ValueError):
        clock.advance(events[1])
    assert clock.result() == before
    monkeypatch.setattr(module, "advance_order", real)
    clock.advance(events[1])
    assert clock.result().net_cash_flow == D("-51.00")
    assert sum(o.filled_units for o in clock.result().orders) == 2


def test_fee_aggregate_corruption_is_detected(tmp_path, monkeypatch):
    clock, _, _ = setup(tmp_path, monkeypatch)
    clock._fees = D("1")
    assert clock.result().reconciliation_reasons == ("fees_mismatch",)


def test_execution_order_projection_corruption_is_detected(tmp_path, monkeypatch):
    clock, order, _ = setup(tmp_path, monkeypatch)
    submit(clock, order)
    clock._orders[order.intent_id] = replace(
        clock._orders[order.intent_id], state=OrderState.FILLED
    )
    assert "order_projection_mismatch" in clock.result().reconciliation_reasons


def test_time_bound_remainder_and_cancel_timer_processed_once(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    submit(clock, order)
    clock.advance(events[0])
    clock.cancel(order.intent_id, available_ns=events[0].available_ns)
    clock.advance_time(_ns(order.expires_at) + 1000)
    assert clock.result().orders[0].state is OrderState.CANCELED
    assert clock.result().status == "completed"


def test_clock_result_is_ambient_decimal_context_independent(tmp_path, monkeypatch):
    from decimal import localcontext

    clock, order, events = setup(tmp_path, monkeypatch)
    with localcontext() as ctx:
        ctx.prec = 2
        submit(clock, order)
        clock.advance(events[0])
        clock.advance(events[1])
        assert clock.result().net_cash_flow == D("-25.50")
        assert clock.result().reconciliation_reasons == ()


def test_prefix_without_completion_fact_is_not_reported_completed(tmp_path, monkeypatch):
    from trading_bot.research.options_account_journal_models import JournalComplete

    clock, order, events = setup(tmp_path, monkeypatch, assumptions=scenario(reject_ppm=1000000))
    submit(clock, order)
    clock.advance(events[0])
    assert isinstance(clock.result().journal[-1].fact, JournalComplete)
    module = importlib.import_module("trading_bot.simulation.options_historical_clock")
    restored = module._EpisodeClock(
        clock.initial,
        clock.result().journal[:-1],
        loaded=clock.loaded,
        scenario=clock.scenario,
        seed=7,
    )
    result = restored.result()
    assert result.status == "incomplete" and "episode_unfinalized" in result.reasons
    assert result.state.trial.reserved_risk == D("26")
    restored.advance_time(restored.now_ns)
    assert restored.result().status == "completed"
