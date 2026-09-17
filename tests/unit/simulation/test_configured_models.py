from dataclasses import FrozenInstanceError, replace
from datetime import datetime
from decimal import Decimal as D

import pytest

from trading_bot.domain import AssetClass, InstrumentId, OrderEvent, TimeInForce
from trading_bot.simulation.configured_models import ConfiguredValidationError
from trading_bot.simulation.configured_validation import validate_stream
from trading_bot.simulation.events import EventCursor

from ._configured_fixtures import at, cancel, market, request, settings, window
from ._lifecycle_fixtures import control, make_request


@pytest.mark.parametrize(
    "changes",
    [{"seed": True}, {"seed": -1}, {"events": []}, {"end_at": at(-1)}, {"expires_at": at(2000)}],
)
def test_invalid_request_shape_fails(changes):
    with pytest.raises(ConfiguredValidationError):
        request(**changes)


def test_settings_are_copied_and_records_frozen():
    supplied = settings()
    result = request(simulation=supplied)
    assert result.simulation == supplied
    assert result.simulation is not supplied
    with pytest.raises(FrozenInstanceError):
        result.seed = 8


def test_unsafe_flags_and_forged_settings_fail_closed():
    for value in (
        settings(assumptions_validated=True),
        settings(assumptions_validated=True, evidence_promotable=True),
        settings().model_copy(update={"same_bar_fills_allowed": True}),
        settings().model_copy(update={"no_fill_probability_pct": D(1)}),
    ):
        with pytest.raises(ConfiguredValidationError):
            request(simulation=value)


def test_scripted_initial_events_are_unsupported():
    with pytest.raises(ConfiguredValidationError):
        request(initial=make_request((control("ack", 1, OrderEvent.BROKER_ACCEPTED),)))


def test_duplicate_does_not_create_another_unique_opportunity():
    event = market()
    indexed = validate_stream(request(events=(event, event)))
    assert len(indexed) == 1
    assert indexed[0].duplicate_indices == (1,)


def test_conflicting_duplicate_and_multiple_cancel_requests_fail():
    event = market()
    with pytest.raises(ConfiguredValidationError, match="duplicate"):
        request(events=(event, replace(event, available_quantity=D(2))))
    with pytest.raises(ConfiguredValidationError):
        request(events=(cancel(), cancel("two", 2, 2000)))


@pytest.mark.parametrize(
    "events",
    [
        (market("one", 2, 1000), market("two", 1, 2000)),
        (market("one", 1, 2000), market("two", 2, 1000)),
        (cancel(milliseconds=499),),
        (market(milliseconds=11000),),
    ],
)
def test_invalid_input_order_or_horizon_fails(events):
    with pytest.raises(ConfiguredValidationError):
        request(events=events)


def test_window_overlap_and_outside_timestamp_fail():
    with pytest.raises(ConfiguredValidationError):
        request(events=(market(milliseconds=1000, window=window(500, 1500)),))
    with pytest.raises(ConfiguredValidationError):
        market(window=window(2000, 3000))
    with pytest.raises(ConfiguredValidationError):
        window(1000, 1000)


@pytest.mark.parametrize("field", ["quote", "clock"])
def test_stale_observation_is_invalid_not_nofill(field):
    event = market()
    with pytest.raises(ConfiguredValidationError):
        replace(event, **{field: replace(getattr(event, field), observed_at=at(999))})


def test_identity_mismatch_fails():
    event = market()
    for changed in (
        replace(event, quote=replace(event.quote, instrument_id=InstrumentId("wrong"))),
        replace(event, clock=replace(event.clock, asset_class=AssetClass.EQUITY)),
    ):
        with pytest.raises(ConfiguredValidationError, match="identity"):
            request(events=(changed,))


def test_gfd_requires_expiry_after_ack_and_gtc_prohibits_it():
    initial = make_request()
    gfd = replace(initial, order=replace(initial.order, time_in_force=TimeInForce.GOOD_FOR_DAY))
    for expiry in (None, at(500)):
        with pytest.raises(ConfiguredValidationError):
            request(initial=gfd, expires_at=expiry)
    assert request(initial=gfd, expires_at=at(501)).expires_at == at(501)


def test_source_namespace_bounded_values_and_exact_types():
    event = market()
    for changes in (
        {"event_id": "sim:injected"},
        {"available_quantity": True},
        {"available_quantity": D("1e600")},
        {"cursor": object()},
        {"quote": replace(event.quote, source="external")},
        {"window": object()},
    ):
        with pytest.raises(ConfiguredValidationError):
            replace(event, **changes)
    with pytest.raises(ConfiguredValidationError):
        replace(window(), starts_at=datetime(2026, 9, 17))


def test_forged_nested_record_revalidated():
    event = market()
    object.__setattr__(event, "cursor", EventCursor(0, at(1000)))
    with pytest.raises(ConfiguredValidationError):
        request(events=(event,))


def test_nonrepresentable_latency_fails_as_safe_validation_error():
    with pytest.raises(ConfiguredValidationError) as error:
        request(simulation=settings(latency_milliseconds=10**40))
    assert str(error.value) == "configured_input_invalid"
    assert error.value.__suppress_context__


def test_invalid_event_objects_and_hash_payloads_fail_safely():
    from trading_bot.simulation.configured_codec import configured_hash

    with pytest.raises(ConfiguredValidationError):
        request(events=(object(),))
    with pytest.raises(ConfiguredValidationError, match="hash"):
        configured_hash("bad", object())
