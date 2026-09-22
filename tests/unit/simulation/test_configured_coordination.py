"""Causal per-action scheduling for the offline multi-order coordinator."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from tests.unit.simulation._configured_fixtures import at, market, request, settings
from tests.unit.simulation._equity_portfolio_fixtures import configured, intent, scenario
from tests.unit.simulation._equity_replay_fixtures import LATER, NOW
from trading_bot.domain import OrderState
from trading_bot.simulation.configured import ConfiguredOrderSession, simulate_configured_order
from trading_bot.simulation.configured_models import (
    ConfiguredValidationError,
    SyntheticCancelRequest,
)
from trading_bot.simulation.equity_replay_portfolio import ReplayPortfolio
from trading_bot.simulation.events import EventCursor


def coordinated(run):
    assert hasattr(run, "advance_next"), "single-action advance is missing"
    assert hasattr(run, "next_event_key"), "cross-order priority key is missing"
    assert hasattr(run, "cancel_after_observation"), "post-observation cancel phase is missing"
    return run


def equity_run(*, quantity="4", latency=0, race="0", deliveries=True):
    req = scenario()
    book = ReplayPortfolio(req)
    outcome = book.reserve(intent(req, quantity=quantity), 4)
    order = configured(book, req, outcome.order_id, events=None if deliveries else ())
    order = replace(
        order,
        simulation=settings(latency_milliseconds=latency, cancel_race_probability_pct=D(race)),
    )
    return coordinated(ConfiguredOrderSession(order)), req


def cancel_at(at_time, *, identifier="decision-cancel", sequence=100):
    return SyntheticCancelRequest(identifier, EventCursor(sequence, at_time))


def test_single_steps_match_legacy_run_without_dropping_equal_time_actions():
    req = request(events=(market(),), simulation=settings(latency_milliseconds=1000))
    run = coordinated(ConfiguredOrderSession(req))
    assert run.next_event_key == (at(1000), 1)
    first = run.advance_next()
    assert first.lifecycle.snapshot.order.state is OrderState.SUBMITTED
    assert first.lifecycle.snapshot.position.quantity == 0
    assert run.next_event_key == (at(1000), 4)
    result = run.advance_next()
    assert result.lifecycle.snapshot.position.quantity == 1
    assert run.next_event_key is None
    assert result == simulate_configured_order(req)


def test_global_merge_processes_both_acknowledgements_before_either_fill():
    req = scenario()
    book = ReplayPortfolio(req)
    runs = {}
    for instrument in req.instruments:
        accepted = book.reserve(
            intent(req, identifier=instrument.id, instrument=instrument.id, quantity="1"), 4
        )
        single = replace(
            configured(book, req, accepted.order_id), simulation=settings(latency_milliseconds=1000)
        )
        runs[instrument.id] = coordinated(ConfiguredOrderSession(single))
    observed = []
    for _ in range(4):
        symbol = min(runs, key=lambda s: (*runs[s].next_event_key, s))
        result = runs[symbol].advance_next()
        observed.append((symbol, result.decisions[-1].reason.value))
    assert observed == [
        ("SECOND", "submission_accepted"),
        ("SYNTH", "submission_accepted"),
        ("SECOND", "full_fill"),
        ("SYNTH", "full_fill"),
    ]


def test_failed_single_fill_preserves_published_ack_and_queue():
    req = request(initial=replace(request().initial, cash=D(1)), events=(market(),))
    run = coordinated(ConfiguredOrderSession(req))
    published = run.advance_next()
    with pytest.raises(ConfiguredValidationError):
        run.advance_next()
    assert run.result == published
    assert run.next_event_key == (at(1000), 4)


def test_post_observation_zero_latency_cancel_preserves_fill_prefix():
    run, _ = equity_run()
    prefix = run.advance_to(LATER)
    assert prefix.lifecycle.snapshot.position.quantity == 2
    run.cancel_after_observation(cancel_at(LATER))
    assert run.result.events == prefix.events and run.result.decisions == prefix.decisions
    assert run.next_event_key == (LATER, 5)
    pending = run.advance_next()
    assert pending.lifecycle.snapshot.order.state is OrderState.CANCEL_PENDING
    assert run.next_event_key == (LATER, 6)
    done = run.advance_next()
    assert done.lifecycle.snapshot.order.state is OrderState.CANCELED
    assert done.lifecycle.snapshot.position.quantity == 2
    assert done.events[: len(prefix.events)] == prefix.events
    assert [d.reason.value for d in done.decisions] == [
        "submission_accepted",
        "partial_fill",
        "cancel_requested",
        "cancel_confirmed",
    ]


def test_post_observation_cancel_permits_only_configured_race_before_ack():
    run, _ = equity_run(quantity="6", latency=1500, race="100")
    now = LATER + timedelta(seconds=1)
    prefix = run.advance_to(now)
    assert prefix.lifecycle.snapshot.position.quantity == 2
    run.cancel_after_observation(cancel_at(now))
    run.advance_next()
    race = run.advance_next()
    assert race.lifecycle.snapshot.position.quantity == 4
    assert race.lifecycle.snapshot.order.state is OrderState.CANCEL_PENDING
    done = run.advance_next()
    assert done.lifecycle.snapshot.order.state is OrderState.CANCELED
    assert done.lifecycle.snapshot.position.quantity == 4
    assert done.lifecycle.snapshot.cash == D(20)
    assert done.lifecycle.snapshot.cursor.occurred_at == NOW + timedelta(milliseconds=3500)


@pytest.mark.parametrize(
    "kind",
    ["past", "future", "pending_ack", "open_phase", "legacy", "duplicate", "collision", "terminal"],
)
def test_invalid_causal_cancel_cannot_change_published_state(kind):
    run, req = equity_run(
        quantity="2" if kind == "terminal" else "4",
        latency=1000 if kind in {"pending_ack", "open_phase"} else 0,
    )
    if kind == "legacy":
        run = coordinated(ConfiguredOrderSession(request(events=(market(),))))
        run.advance_to(at(1000))
        event = cancel_at(at(1000))
    else:
        if kind == "open_phase":
            run.advance_next()  # Ack only; the same-time quote has not been processed.
        else:
            run.advance_to(NOW if kind == "pending_ack" else LATER)
        event = cancel_at(NOW if kind == "pending_ack" else LATER)
        if kind in {"past", "future"}:
            event = cancel_at(LATER + timedelta(microseconds=-1 if kind == "past" else 1))
        if kind == "collision":
            event = cancel_at(LATER, identifier=req.markets[0].event_id)
        if kind == "duplicate":
            run.cancel_after_observation(event)
    published, key = run.result, run.next_event_key
    with pytest.raises(ConfiguredValidationError):
        run.cancel_after_observation(event)
    assert run.result == published and run.next_event_key == key


def test_future_delivery_does_not_drain_a_pending_same_time_causal_cancel():
    run, req = equity_run(deliveries=False)
    run.deliver(req.markets[0])
    prefix = run.advance_to(LATER)
    run.cancel_after_observation(cancel_at(LATER))
    run.deliver(req.markets[2])
    assert run.result.events == prefix.events and run.result.decisions == prefix.decisions
    assert run.next_event_key == (LATER, 5)
    done = run.advance_to(LATER)
    assert done.lifecycle.snapshot.order.state is OrderState.CANCELED


def test_future_delivery_preserves_single_step_prefix_at_an_open_timestamp():
    first = market()
    req = request(events=(first,), simulation=settings(latency_milliseconds=1000))
    run = coordinated(ConfiguredOrderSession(req))
    acknowledged = run.advance_next()
    run.deliver(market("future", 2, 2000))
    assert run.result.events == acknowledged.events
    assert run.result.decisions == acknowledged.decisions
    assert run.next_event_key == (at(1000), 4)


def test_causal_cancel_rebuild_and_preloaded_future_have_equal_results():
    preloaded, req = equity_run()
    streaming, _ = equity_run(deliveries=False)
    streaming.deliver(req.markets[0])
    for run in (preloaded, streaming):
        run.advance_to(LATER)
        run.cancel_after_observation(cancel_at(LATER))
        run.advance_to(LATER)
    for event in req.markets[2::2]:
        streaming.deliver(event)
    assert streaming.advance_to(req.end_at) == preloaded.advance_to(req.end_at)


def test_global_causal_phase_requests_all_cancels_before_zero_latency_acks():
    runs = {symbol: equity_run()[0] for symbol in ("A", "B")}
    for symbol, run in runs.items():
        run.advance_to(LATER)
        run.cancel_after_observation(cancel_at(LATER, identifier=f"cancel-{symbol}"))
    observed = []
    for _ in range(4):
        symbol = min(runs, key=lambda s: (*runs[s].next_event_key, s))
        observed.append((symbol, runs[symbol].advance_next().decisions[-1].reason.value))
    assert observed == [
        ("A", "cancel_requested"),
        ("B", "cancel_requested"),
        ("A", "cancel_confirmed"),
        ("B", "cancel_confirmed"),
    ]
