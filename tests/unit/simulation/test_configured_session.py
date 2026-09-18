"""Incremental advancement preserves cash, control precedence and immutable prefixes."""

from dataclasses import replace
from decimal import Decimal as D
from decimal import localcontext

import pytest

from trading_bot.domain import OrderState, TimeInForce
from trading_bot.simulation import configured
from trading_bot.simulation.configured_models import ConfiguredValidationError

from ._configured_fixtures import at, cancel, market, request, settings


def session(req):
    # Keep initial RED a behavioral assertion, not an import/collection error.
    constructor = getattr(configured, "ConfiguredOrderSession", None)
    assert constructor is not None, "incremental configured-order session is missing"
    return constructor(req)


@pytest.mark.parametrize(
    "kind,want",
    [
        ("full", "9658f7d0e4c8559b2e801f0f363c1e51126bad6cdd0b30c93956044903cc04c2"),
        ("partial", "59bb8566a10c8e3d630dd8841f569dacb7afec429d5d8677aab8b5755b6e9c25"),
        ("cancel_race", "676915aabd9622d2d1b2db9b86cd001d5874320d6de0ae86f65001405fa059f8"),
        ("expiry", "95f557bbb566450890a4ba11a6c6d1fa6f4f4c8ccba014425ee8986f7ec56fc9"),
    ],
)
def test_legacy_audit_identity_survives_scheduler_extraction(kind, want):
    req = request(events=(market(),))
    if kind == "partial":
        req = replace(req, events=(market(available_quantity=D("0.25")),))
    elif kind == "cancel_race":
        req = replace(
            req,
            events=(cancel(), market("race", 2, 1200)),
            simulation=settings(cancel_race_probability_pct=D(100)),
        )
    elif kind == "expiry":
        initial = replace(
            req.initial, order=replace(req.initial.order, time_in_force=TimeInForce.GOOD_FOR_DAY)
        )
        req = replace(
            req, initial=initial, expires_at=at(1500), events=(cancel(), market("equal", 2, 1500))
        )
    assert configured.simulate_configured_order(req).result_hash == want


def test_advance_does_not_drop_the_next_queued_ack_or_market():
    req = request(events=(market(),))
    run = session(req)
    pending = run.advance_to(at(499))
    assert pending.events == ()
    assert run.next_event_at == at(500)
    acknowledged = run.advance_to(at(500))
    assert acknowledged.lifecycle.snapshot.order.state is OrderState.SUBMITTED
    assert run.next_event_at == at(1000)
    final = run.advance_to(req.end_at)
    assert final.lifecycle.snapshot.cash == D("900.2562625")
    assert final.lifecycle.snapshot.position.quantity == D(1)
    assert pending.events == ()
    assert run.next_event_at is None
    assert final == configured.simulate_configured_order(req)


def test_forward_delivery_matches_preloaded_single_run():
    first = market("first", 1, 1000, available_quantity=D("0.25"))
    second = market("second", 2, 2000)
    req = request()
    run = session(req)
    run.advance_to(at(500))
    run.deliver(first)
    prefix = run.advance_to(at(1000))
    run.deliver(second)
    assert run.result.lifecycle == prefix.lifecycle
    final = run.advance_to(req.end_at)
    assert final.lifecycle.snapshot.position.quantity == D(1)
    assert final == configured.simulate_configured_order(replace(req, events=(first, second)))


def test_duplicate_pending_delivery_is_audit_only():
    event = market(available_quantity=D("0.25"))
    req = request()
    run = session(req)
    run.deliver(event)
    run.deliver(event)
    final = run.advance_to(req.end_at)
    assert final.lifecycle.snapshot.position.quantity == D("0.25")
    assert [d.reason.value for d in final.decisions] == [
        "submission_accepted",
        "partial_fill",
        "duplicate_event",
    ]
    assert final == configured.simulate_configured_order(replace(req, events=(event, event)))


@pytest.mark.parametrize("event", [market(), market("late", 2, 999), cancel()])
def test_late_or_published_timestamp_delivery_denies_without_mutation(event):
    run = session(request())
    published = run.advance_to(at(1000))
    with pytest.raises(ConfiguredValidationError):
        run.deliver(event)
    assert run.result == published
    assert run.next_event_at is None


@pytest.mark.parametrize("when", [at(499), at(10001), at(501).replace(tzinfo=None), None])
def test_invalid_advancement_is_atomic(when):
    run = session(request(events=(market(),)))
    published = run.advance_to(at(500))
    with pytest.raises(ConfiguredValidationError):
        run.advance_to(when)
    assert run.result == published
    assert run.next_event_at == at(1000)


def test_failed_fill_cannot_publish_an_ack_or_consume_the_queue():
    initial = replace(request().initial, cash=D(1))
    run = session(request(initial=initial, events=(market(),)))
    published = run.result
    with pytest.raises(ConfiguredValidationError):
        run.advance_to(at(1000))
    assert run.result == published
    assert run.next_event_at == at(500)
    acknowledged = run.advance_to(at(500))
    assert acknowledged.lifecycle.snapshot.order.state is OrderState.SUBMITTED
    assert acknowledged.lifecycle.snapshot.cash == D(1)


def test_cancel_race_and_expiry_priorities_survive_incremental_boundaries():
    initial = request().initial
    initial = replace(initial, order=replace(initial.order, time_in_force=TimeInForce.GOOD_FOR_DAY))
    req = request(
        initial=initial,
        expires_at=at(1500),
        events=(
            cancel(),
            market("race", 2, 1200, available_quantity=D("0.25")),
            market("equal", 3, 1500),
        ),
        simulation=settings(cancel_race_probability_pct=D(100)),
    )
    run = session(req)
    run.advance_to(at(1000))
    assert run.next_event_at == at(1200)
    assert run.advance_to(at(1200)).lifecycle.snapshot.position.quantity == D("0.25")
    final = run.advance_to(req.end_at)
    assert final.lifecycle.snapshot.order.state is OrderState.EXPIRED
    assert final.lifecycle.snapshot.position.quantity == D("0.25")
    assert final == configured.simulate_configured_order(req)


def test_conflicting_duplicate_or_invalid_object_cannot_modify_pending_input():
    event = market()
    run = session(request(events=(event,)))
    published = run.result
    for invalid in (replace(event, available_quantity=D("0.25")), object()):
        with pytest.raises(ConfiguredValidationError):
            run.deliver(invalid)
        assert run.result == published
    assert run.advance_to(at(1000)).lifecycle.snapshot.position.quantity == D(1)


def test_repeated_advance_does_not_apply_fills_twice():
    run = session(request(events=(market(),)))
    final = run.advance_to(at(1000))
    assert run.advance_to(at(1000)) == final
    assert run.advance_to(at(10000)) == final


def test_controls_outside_horizon_do_not_invent_completion():
    run = session(request(end_at=at(499)))
    assert run.next_event_at is None
    result = run.advance_to(at(499))
    assert result.lifecycle.snapshot.order.state is OrderState.SUBMISSION_PENDING
    assert not result.lifecycle.order_terminal


def test_new_future_delivery_does_not_rewrite_generated_events_or_decisions():
    first = market("first", 1, 1000, available_quantity=D("0.25"))
    run = session(request(events=(first,)))
    prior = run.advance_to(at(1000))
    run.deliver(market("later", 2, 2000))
    assert run.result.events == prior.events
    assert run.result.decisions == prior.decisions
    assert run.result.lifecycle == prior.lifecycle
    assert run.result.input_hash != prior.input_hash


def test_incremental_execution_does_not_use_ambient_decimal_precision():
    req = request(events=(market(),))
    normal = session(req).advance_to(req.end_at)
    with localcontext() as context:
        context.prec = 2
        low_precision = session(req)
        low_precision.advance_to(at(500))
        assert low_precision.advance_to(req.end_at) == normal


def test_order_simulation_succeeds_with_network_and_sqlite_disabled(monkeypatch):
    import socket
    import sqlite3

    req = request(events=(market(),))

    def forbidden(*args, **kwargs):
        raise AssertionError("offline order simulation attempted external I/O")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    result = session(req).advance_to(req.end_at)
    assert result.lifecycle.snapshot.cash == D("900.2562625")
    assert result.evidence_promotable is False
