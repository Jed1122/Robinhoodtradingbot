from dataclasses import FrozenInstanceError, replace
from datetime import timedelta, timezone
from decimal import ROUND_DOWN, Decimal, Inexact, localcontext

import pytest

from trading_bot.domain import OrderEvent, OrderState, Side
from trading_bot.simulation.events import EventCursor
from trading_bot.simulation.lifecycle import replay_order_lifecycle
from trading_bot.simulation.lifecycle_models import (
    LifecycleControlEvent,
    LifecycleFillEvent,
    LifecycleValidationError,
)

from ._lifecycle_fixtures import ORIGIN, control, execution, make_request


def accepted():
    return control("accept", 1, OrderEvent.BROKER_ACCEPTED)


@pytest.mark.parametrize(
    "changes",
    [
        {"quantity": Decimal("0.5")},
        {"price": Decimal("99")},
        {"fee": Decimal("0.02")},
        {"id": "different-fill"},
        {"data_hash": "f" * 64},
        {"account_id": "different-account"},
        {"instrument_id": "different-instrument"},
        {"broker_order_id": "different-order"},
        {"side": Side.SELL},
    ],
)
def test_reused_event_id_cannot_change_fill_payload(changes):
    first = execution("partial", 2, "0.25")
    conflicting = replace(first, fill=replace(first.fill, **changes))
    with pytest.raises(LifecycleValidationError):
        replay_order_lifecycle(make_request((accepted(), first, conflicting)))


def test_reused_event_id_cannot_change_cursor():
    first = execution("partial", 2, "0.25")
    changed = replace(first, cursor=replace(first.cursor, sequence=3))
    with pytest.raises(LifecycleValidationError, match="duplicate_conflict"):
        replay_order_lifecycle(make_request((accepted(), first, changed)))


def test_fill_id_cannot_be_reused_under_new_envelope():
    first = execution("partial", 2, "0.25")
    changed = replace(first, event_id="different-envelope")
    with pytest.raises(LifecycleValidationError, match="duplicate_conflict"):
        replay_order_lifecycle(make_request((accepted(), first, changed)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_id", "wrong"),
        ("instrument_id", "wrong"),
        ("broker_order_id", "wrong"),
    ],
)
def test_control_identity_cannot_cross_orders(field, value):
    with pytest.raises(LifecycleValidationError, match="identity_mismatch"):
        replay_order_lifecycle(make_request((replace(accepted(), **{field: value}),)))


def test_control_id_conflict_is_not_treated_as_successful_retransmission():
    different = replace(accepted(), event=OrderEvent.BROKER_REJECTED)
    with pytest.raises(LifecycleValidationError, match="duplicate_conflict"):
        replay_order_lifecycle(make_request((accepted(), different)))


@pytest.mark.parametrize("sequence,seconds", [(0, 2), (1, 2), (2, 0), (2, -1)])
def test_new_fill_rejects_backward_cursor_or_time(sequence, seconds):
    original = execution("fill", 2, "0.25")
    timestamp = ORIGIN + timedelta(seconds=seconds)
    changed = replace(
        original,
        cursor=EventCursor(sequence, timestamp),
        fill=replace(original.fill, occurred_at=timestamp),
    )
    with pytest.raises(LifecycleValidationError, match="ordering_invalid"):
        replay_order_lifecycle(make_request((accepted(), changed)))


def test_new_fill_at_submission_time_is_rejected_even_after_same_time_acceptance():
    accept = replace(accepted(), cursor=EventCursor(1, ORIGIN))
    fill = execution("fill", 2, "1")
    fill = replace(fill, cursor=EventCursor(2, ORIGIN), fill=replace(fill.fill, occurred_at=ORIGIN))
    with pytest.raises(LifecycleValidationError, match="ordering_invalid"):
        replay_order_lifecycle(make_request((accept, fill)))


@pytest.mark.parametrize(
    "terminal",
    [
        control("reject", 1, OrderEvent.BROKER_REJECTED),
        control("expire", 2, OrderEvent.BROKER_EXPIRED),
        control("confirm", 3, OrderEvent.CANCEL_CONFIRMED),
    ],
)
def test_terminal_rejection_expiry_and_cancellation_cannot_reopen(terminal):
    events = () if terminal.event is OrderEvent.BROKER_REJECTED else (accepted(),)
    if terminal.event is OrderEvent.CANCEL_CONFIRMED:
        events += (control("cancel", 2, OrderEvent.REQUEST_CANCEL),)
    request = make_request((*events, terminal, control("again", 4, OrderEvent.BROKER_ACCEPTED)))
    with pytest.raises(LifecycleValidationError, match="transition_invalid"):
        replay_order_lifecycle(request)


def test_rejection_after_acceptance_is_invalid():
    with pytest.raises(LifecycleValidationError, match="transition_invalid"):
        replay_order_lifecycle(
            make_request(
                (
                    accepted(),
                    control("reject", 2, OrderEvent.BROKER_REJECTED),
                )
            )
        )


def test_failed_replay_does_not_modify_inputs_or_prior_results():
    valid = make_request((accepted(), execution("partial", 2, "0.25")))
    before = replay_order_lifecycle(valid)
    invalid = replace(valid, events=(*valid.events, execution("overfill", 3, "1")))
    with pytest.raises(LifecycleValidationError):
        replay_order_lifecycle(invalid)
    assert replay_order_lifecycle(valid) == before
    assert before.snapshot.cash == Decimal("974.99")
    assert valid.cash == Decimal("1000")
    assert valid.position.quantity == 0
    assert valid.order.state is OrderState.SUBMISSION_PENDING


@pytest.mark.parametrize("precision,rounding", [(1, ROUND_DOWN), (50, ROUND_DOWN)])
def test_full_replay_is_independent_of_decimal_context(precision, rounding):
    request = make_request(
        (accepted(), execution("first", 2, "0.25"), execution("second", 3, "0.75", price="99"))
    )
    expected = replay_order_lifecycle(request)
    with localcontext() as context:
        context.prec = precision
        context.rounding = rounding
        context.traps[Inexact] = True
        context.clear_flags()
        assert replay_order_lifecycle(request) == expected
        assert not any(context.flags.values())


@pytest.mark.parametrize(
    "field,value",
    [
        ("quantity", Decimal("NaN")),
        ("price", Decimal("Infinity")),
        ("fee", Decimal("-1")),
        ("fee", Decimal("1e600")),
        ("side", "buy"),
        ("account_id", object()),
        ("data_hash", "synthetic-secret-sentinel"),
        ("occurred_at", ORIGIN.replace(tzinfo=None)),
        ("occurred_at", ORIGIN.replace(tzinfo=timezone(timedelta(hours=1)))),
    ],
)
def test_replay_revalidates_corrupted_frozen_fill_without_leaking(field, value):
    event = execution("fill", 2, "1")
    request = make_request((accepted(), event))
    object.__setattr__(event.fill, field, value)
    with pytest.raises(LifecycleValidationError) as caught:
        replay_order_lifecycle(request)
    assert "synthetic-secret-sentinel" not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("value", [True, -1, 1.5])
def test_replay_revalidates_corrupted_event_sequence(value):
    event = execution("fill", 2, "1")
    request = make_request((accepted(), event))
    object.__setattr__(event.cursor, "sequence", value)
    with pytest.raises(LifecycleValidationError):
        replay_order_lifecycle(request)


def test_replay_rejects_nonrequest_without_inspection():
    with pytest.raises(LifecycleValidationError):
        replay_order_lifecycle(object())


@pytest.mark.parametrize(
    "changes",
    [
        {"receipts": []},
        {"receipts": (object(),)},
        {"snapshot": object()},
        {"result_hash": "wrong"},
    ],
)
def test_result_rejects_invalid_record_shapes(changes):
    result = replay_order_lifecycle(make_request())
    with pytest.raises(LifecycleValidationError):
        replace(result, **changes)


def test_result_flags_cannot_be_enabled_or_changed():
    result = replay_order_lifecycle(make_request())
    with pytest.raises(ValueError):
        replace(result, evidence_promotable=True)
    with pytest.raises(FrozenInstanceError):
        result.source_kind = "real"


def test_receipt_cannot_claim_duplicate_was_applied():
    result = replay_order_lifecycle(make_request((accepted(),)))
    with pytest.raises(LifecycleValidationError):
        replace(result.receipts[0], reason_code="duplicate_event")


@pytest.mark.parametrize("event_class", [LifecycleControlEvent, LifecycleFillEvent])
def test_subclass_events_are_not_accepted(event_class):
    class UntrustedEvent(event_class):
        pass

    original = accepted() if event_class is LifecycleControlEvent else execution("fill", 2, "1")
    # A subclass must not gain authority by overriding validation.
    values = {name: getattr(original, name) for name in original.__dataclass_fields__}
    subclass = UntrustedEvent(**values)
    with pytest.raises(LifecycleValidationError):
        make_request((subclass,))
