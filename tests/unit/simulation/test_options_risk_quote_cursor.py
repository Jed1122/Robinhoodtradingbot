"""Synthetic internal-clock regressions, never policy admission or broker evidence.

Multi-order/multi-unit fixtures intentionally exercise the accounting engine beyond
the public study's one-position/one-unit policy. Halts request cancellation; they
must not invent instantaneous cancellation or erase an already possible fill race.
"""

from dataclasses import replace
from decimal import Decimal

import pytest

from tests.unit.market_data.test_databento_batch import no_network  # noqa: F401
from tests.unit.simulation.test_options_account_risk_clock import observe
from tests.unit.simulation.test_options_historical_clock import closing, setup, submit
from tests.unit.simulation.test_options_historical_execution import scenario
from tests.unit.simulation.test_options_historical_restart import resume
from trading_bot.domain.enums import OrderState
from trading_bot.market_data.options_source_verify import ceil_available_at
from trading_bot.research.options_account_journal import initial_account_path
from trading_bot.simulation import options_historical_clock as clock_module

D = Decimal


def two_risk_orders(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch, units=2)
    observe(clock, order)
    submit(clock, order)
    observe(clock, order)
    second = replace(order, intent_id="second-order")
    clock.submit("episode-2", "same-session", second, available_ns=clock.now_ns)
    clock.advance(events[0])
    return clock, order, events


def observe_first_fill(clock, order):
    clock.mark("episode-1", D("0.20"), available_ns=clock.now_ns)
    observe(clock, order)


def held_with_pending_buy(tmp_path, monkeypatch, *, accepted=True, race="fill_before_ack"):
    clock, order, events = setup(tmp_path, monkeypatch, assumptions=scenario(cancel_race=race))
    # Deliberately non-admissible accounting fixture; no strategy risk gate is bypassed.
    initial = initial_account_path(
        study_hash=clock.initial.study_hash,
        capital=D("100"),
        start_ns=clock.initial.start_ns,
        loaded=clock.loaded,
        scenario=clock.scenario,
    )
    clock = type(clock)(initial, (), loaded=clock.loaded, scenario=clock.scenario, seed=7)
    order = replace(order, account_scope=initial.path_id)
    observe(clock, order)
    submit(clock, order)
    clock.advance(events[0])
    clock.advance(events[1])
    clock.mark("episode-1", D("0.25"), available_ns=clock.now_ns)
    observe(clock, order)
    second = replace(order, intent_id="pending-buy", created_at=ceil_available_at(clock.now_ns))
    clock.submit("episode-2", "same-session", second, available_ns=clock.now_ns)
    if accepted:
        clock.advance(events[2])
    clock.mark("episode-1", D("0"), available_ns=clock.now_ns)
    return clock, order, events


def test_two_fills_share_quote_liquidity_across_risk_observation_boundary(tmp_path, monkeypatch):
    clock, order, events = two_risk_orders(tmp_path, monkeypatch)
    clock.advance(events[1])
    first = clock.result()
    assert "market_event_pending" in first.reasons
    assert [o.filled_units for o in first.orders] == [2, 0]
    assert first.net_cash_flow == D("-51.00") and first.fees == D("1.00")
    observe_first_fill(clock, order)
    clock.advance(events[1])
    second = clock.result()
    assert "market_event_pending" not in second.reasons
    assert [o.filled_units for o in second.orders] == [2, 1]
    assert second.net_cash_flow == D("-76.50") and second.fees == D("1.50")
    clock.mark("episode-2", D("0.20"), available_ns=clock.now_ns)
    observe(clock, order)
    before = clock.result()
    clock.advance(events[1])
    assert clock.result() == before
    clock.advance(events[2])
    observe(clock, order)
    assert [o.filled_units for o in clock.result().orders] == [2, 2]
    assert clock.result().net_cash_flow == D("-102.00")
    assert clock.result().reconciliation_reasons == ()


def test_loss_halt_requests_cancellation_of_already_submitted_buy(tmp_path, monkeypatch):
    clock, order, _ = held_with_pending_buy(tmp_path, monkeypatch)
    assert clock.result().orders[1].state is OrderState.SUBMITTED
    observe(clock, order)
    pending = clock.result().orders[1]
    assert pending.state is OrderState.CANCEL_PENDING
    assert pending.cancel_requested_ns == clock.now_ns
    assert pending.filled_units == 0
    assert clock.state.trial.reserved_risk == D("52")
    assert clock.state.latched_halts == ("drawdown_latched", "weekly_loss_latched")
    assert resume(clock).result() == clock.result()


def test_legacy_no_risk_multiorder_quote_remains_atomic(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch, units=2)
    submit(clock, order)
    clock.submit(
        "episode-2",
        "same-session",
        replace(order, intent_id="second-order"),
        available_ns=clock.now_ns,
    )
    clock.advance(events[0])
    clock.advance(events[1])
    assert [o.filled_units for o in clock.result().orders] == [2, 1]
    assert clock.result().net_cash_flow == D("-76.50")
    assert "market_event_pending" not in clock.result().reasons


@pytest.mark.parametrize("marked", [False, True])
def test_pending_quote_cannot_resume_before_new_risk_observation(tmp_path, monkeypatch, marked):
    clock, _, events = two_risk_orders(tmp_path, monkeypatch)
    clock.advance(events[1])
    if marked:
        clock.mark("episode-1", D("0.20"), available_ns=clock.now_ns)
    before = clock.result()
    with pytest.raises(ValueError):
        clock.advance(events[1])
    assert clock.result() == before == resume(clock).result()


@pytest.mark.parametrize("action", ["later_event", "changed_event", "time", "submit", "flow"])
def test_observed_pending_quote_cannot_be_skipped_or_interleaved(tmp_path, monkeypatch, action):
    clock, order, events = two_risk_orders(tmp_path, monkeypatch)
    clock.advance(events[1])
    observe_first_fill(clock, order)
    before = clock.result()
    with pytest.raises(ValueError):
        if action == "later_event":
            clock.advance(events[2])
        elif action == "changed_event":
            clock.advance(replace(events[1], record_ordinal=100))
        elif action == "time":
            clock.advance_time(clock.now_ns + 1)
        elif action == "submit":
            clock.submit(
                "episode-3",
                "same-session",
                replace(order, intent_id="third-order", created_at=ceil_available_at(clock.now_ns)),
                available_ns=clock.now_ns,
            )
        else:
            clock.external_flow(D("1"), available_ns=clock.now_ns)
    assert clock.result() == before == resume(clock).result()
    clock.advance(events[1])
    assert [o.filled_units for o in clock.result().orders] == [2, 1]


@pytest.mark.parametrize(
    "cut", ["first_fill", "first_observation", "second_fill", "second_observation"]
)
def test_restart_at_each_fill_boundary_preserves_cursor_and_liquidity(tmp_path, monkeypatch, cut):
    clock, order, events = two_risk_orders(tmp_path, monkeypatch)
    clock.advance(events[1])
    if cut == "first_fill":
        restored = resume(clock)
        assert restored.result() == clock.result()
        clock = restored
    observe_first_fill(clock, order)
    if cut == "first_observation":
        restored = resume(clock)
        assert restored.result() == clock.result()
        clock = restored
    clock.advance(events[1])
    if cut == "second_fill":
        restored = resume(clock)
        assert restored.result() == clock.result()
        clock = restored
    clock.mark("episode-2", D("0.20"), available_ns=clock.now_ns)
    observe(clock, order)
    if cut == "second_observation":
        restored = resume(clock)
        assert restored.result() == clock.result()
        clock = restored
    before = clock.result()
    clock.advance(events[1])
    assert clock.result() == before
    assert [o.filled_units for o in before.orders] == [2, 1]
    assert before.state.cash == D("9923.50") and before.fees == D("1.50")
    assert "market_event_pending" not in before.reasons
    assert resume(clock).result() == before


@pytest.mark.parametrize("half", ["first", "second"])
def test_failed_fill_rolls_back_only_its_cursor_step_and_restart_remains_exact(
    tmp_path, monkeypatch, half
):
    clock, order, events = two_risk_orders(tmp_path, monkeypatch)
    if half == "second":
        clock.advance(events[1])
        observe_first_fill(clock, order)
    before = clock.result()
    real = clock_module.advance_order
    target = order.intent_id if half == "first" else "second-order"

    def invalid_fee(current, event, **kwargs):
        step = real(current, event, **kwargs)
        return (
            replace(step, fee=D("99"))
            if current.intent.intent_id == target and step.fill_units
            else step
        )

    with monkeypatch.context() as fault:
        fault.setattr(clock_module, "advance_order", invalid_fee)
        with pytest.raises(ValueError):
            clock.advance(events[1])
    assert clock.result() == before == resume(clock).result()
    assert [o.filled_units for o in before.orders] == ([0, 0] if half == "first" else [2, 0])
    clock.advance(events[1])
    if half == "first":
        observe_first_fill(clock, order)
        clock.advance(events[1])
    assert [o.filled_units for o in clock.result().orders] == [2, 1]
    assert clock.result().net_cash_flow == D("-76.50")


@pytest.mark.parametrize(
    "race,event_index,filled",
    [
        ("ack_before_fill", 3, 1),
        ("ack_before_fill", 4, 0),
        ("fill_before_ack", 4, 1),
        ("fill_before_ack", 5, 0),
    ],
)
def test_halt_cancel_preserves_pre_ack_and_tied_races_without_post_ack_fills(
    tmp_path, monkeypatch, race, event_index, filled
):
    clock, order, events = held_with_pending_buy(tmp_path, monkeypatch, race=race)
    observe(clock, order)
    assert clock.result().orders[1].state is OrderState.CANCEL_PENDING
    assert clock.state.trial.reserved_risk == D("52")
    clock = resume(clock)
    clock.advance(events[event_index])
    second = clock.result().orders[1]
    assert second.filled_units == filled
    assert second.state is (OrderState.FILLED if filled else OrderState.CANCELED)
    assert clock.result().net_cash_flow == (D("-51.00") if filled else D("-25.50"))
    assert clock.state.trial.reserved_risk == (D("52") if filled else D("26"))
    assert resume(clock).result() == clock.result()


def test_repeated_halt_observation_does_not_restart_cancel_ack_clock(tmp_path, monkeypatch):
    clock, order, events = held_with_pending_buy(tmp_path, monkeypatch, race="ack_before_fill")
    observe(clock, order)
    requested_at = clock.now_ns
    clock.advance_time(clock.now_ns + 1)
    observe(clock, order)
    assert clock.result().orders[1].cancel_requested_ns == requested_at
    clock.advance(events[4])
    assert clock.result().orders[1].state is OrderState.CANCELED
    assert clock.result().orders[1].filled_units == 0


def test_submission_pending_buy_is_canceled_on_ack_not_fabricated_terminal(tmp_path, monkeypatch):
    clock, order, events = held_with_pending_buy(tmp_path, monkeypatch, accepted=False)
    observe(clock, order)
    pending = clock.result().orders[1]
    assert pending.state is OrderState.SUBMISSION_PENDING
    assert pending.filled_units == 0 and clock.state.trial.reserved_risk == D("52")
    clock = resume(clock)
    clock.advance(events[2])
    pending = clock.result().orders[1]
    assert pending.state is OrderState.CANCEL_PENDING
    assert pending.accepted_ns == pending.cancel_requested_ns == events[2].available_ns
    assert pending.filled_units == 0 and clock.state.trial.reserved_risk == D("52")
    clock.advance_time(events[2].available_ns + clock.scenario.cancel_acknowledgement_ns)
    assert clock.result().orders[1].state is OrderState.CANCELED
    assert clock.state.trial.reserved_risk == D("26")
    assert resume(clock).result() == clock.result()


@pytest.mark.parametrize("halt_before_ack", [False, True])
def test_unknown_buy_outcome_stays_reserved_not_auto_canceled(
    tmp_path, monkeypatch, halt_before_ack
):
    clock, order, events = setup(tmp_path, monkeypatch, assumptions=scenario(ambiguous_ppm=1000000))
    observe(clock, order)
    submit(clock, order)
    if halt_before_ack:
        observe(clock, order, complete=False)
    clock.advance(events[0])
    if not halt_before_ack:
        observe(clock, order, complete=False)
    pending = clock.result().orders[0]
    assert pending.state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION
    assert pending.cancel_requested_ns is None and pending.filled_units == 0
    assert clock.state.trial.reserved_risk == D("26")
    assert clock.state.latched_halts == ("risk_history_incomplete",)
    clock.advance_time(clock.initial.start_ns + 10001)
    assert clock.result().orders[0].state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION
    assert clock.state.trial.reserved_risk == D("26")
    assert resume(clock).result() == clock.result()


def test_partial_buy_halt_cancels_only_unfilled_remainder(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch, units=5)
    initial = initial_account_path(
        study_hash=clock.initial.study_hash,
        capital=D("1000"),
        start_ns=clock.initial.start_ns,
        loaded=clock.loaded,
        scenario=clock.scenario,
    )
    clock = type(clock)(initial, (), loaded=clock.loaded, scenario=clock.scenario, seed=7)
    order = replace(order, account_scope=initial.path_id)
    observe(clock, order)
    submit(clock, order)
    clock.advance(events[0])
    clock.advance(events[1])
    clock.mark("episode-1", D("0"), available_ns=clock.now_ns)
    observe(clock, order)
    pending = clock.result().orders[0]
    assert pending.state is OrderState.CANCEL_PENDING and pending.filled_units == 3
    assert "weekly_loss_latched" in clock.state.latched_halts
    assert clock.state.trial.reserved_risk == D("130")
    clock.advance_time(clock.now_ns + clock.scenario.cancel_acknowledgement_ns)
    assert clock.result().orders[0].state is OrderState.CANCELED
    assert clock.state.positions[0].units == 3
    assert clock.state.trial.reserved_risk == D("130")
    assert clock.result().net_cash_flow == D("-76.50")
    assert resume(clock).result() == clock.result()


def test_halt_never_auto_cancels_protective_sell(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    observe(clock, order)
    submit(clock, order)
    clock.advance(events[0])
    clock.advance(events[1])
    clock.mark("episode-1", None, available_ns=clock.now_ns)
    observe(clock, order, complete=False)
    submit(clock, closing(order, events[1].available_ns))
    clock.advance(events[2])
    observe(clock, order, complete=False)
    closing_order = clock.result().orders[1]
    assert closing_order.state is OrderState.SUBMITTED
    assert closing_order.cancel_requested_ns is None
    clock.advance(events[3])
    observe(clock, order)
    clock.advance_time(events[3].available_ns + 10)
    observe(clock, order)
    assert clock.state.episodes[0].finalized
    assert clock.state.positions == clock.state.unsettled == ()
    assert clock.state.trial.consumed_loss == D("6")
    assert clock.state.incidents == ()
    assert clock.state.latched_halts == ("risk_history_incomplete",)
    assert resume(clock).result() == clock.result()


def test_failed_automatic_cancel_does_not_partially_append_loss_observation(tmp_path, monkeypatch):
    clock, order, _ = held_with_pending_buy(tmp_path, monkeypatch)
    before = clock.result()

    def denied(*args, **kwargs):
        raise ValueError("fabricated cancel failure")

    with monkeypatch.context() as fault:
        fault.setattr(clock_module, "request_cancel", denied)
        with pytest.raises(ValueError):
            observe(clock, order)
    assert clock.result() == before == resume(clock).result()
    observe(clock, order)
    assert clock.result().orders[1].state is OrderState.CANCEL_PENDING
