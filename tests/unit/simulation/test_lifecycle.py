from dataclasses import replace
from decimal import Decimal

import pytest

from trading_bot.domain import OrderEvent, OrderState, Side
from trading_bot.simulation.lifecycle import replay_order_lifecycle
from trading_bot.simulation.lifecycle_models import LifecycleValidationError

from ._lifecycle_fixtures import control, execution, make_request


def accepted():
    return control("accept", 1, OrderEvent.BROKER_ACCEPTED)


def test_complete_buy_is_terminal_but_not_flat_or_promotable():
    result = replay_order_lifecycle(make_request((accepted(), execution("fill", 2, "1"))))
    assert result.snapshot.order.state is OrderState.FILLED
    assert result.snapshot.position.quantity == Decimal("1")
    assert result.snapshot.cash == Decimal("899.99")
    assert result.snapshot.fees == Decimal("0.01")
    assert result.snapshot.remaining_quantity == 0
    assert result.order_terminal
    assert not result.evidence_promotable
    assert result.source_kind == "synthetic-order-lifecycle-v1"
    assert result.snapshot.order.data_hash == result.receipts[-1].event_digest
    assert result.snapshot.position.data_hash == result.receipts[-1].event_digest


@pytest.mark.parametrize(
    "events,state,cash,position,remaining,fees",
    [
        ((), OrderState.SUBMISSION_PENDING, "1000", "0", "1", "0"),
        ((accepted(),), OrderState.SUBMITTED, "1000", "0", "1", "0"),
        (
            (control("reject", 1, OrderEvent.BROKER_REJECTED),),
            OrderState.REJECTED,
            "1000",
            "0",
            "1",
            "0",
        ),
        (
            (accepted(), execution("a", 2, "0.25")),
            OrderState.PARTIALLY_FILLED,
            "974.99",
            "0.25",
            "0.75",
            "0.01",
        ),
        (
            (accepted(), execution("a", 2, "0.25"), execution("b", 3, "0.75")),
            OrderState.FILLED,
            "899.98",
            "1",
            "0",
            "0.02",
        ),
        (
            (
                accepted(),
                control("cancel", 2, OrderEvent.REQUEST_CANCEL),
                control("confirm", 3, OrderEvent.CANCEL_CONFIRMED),
            ),
            OrderState.CANCELED,
            "1000",
            "0",
            "1",
            "0",
        ),
        (
            (
                accepted(),
                execution("a", 2, "0.25"),
                control("cancel", 3, OrderEvent.REQUEST_CANCEL),
                control("confirm", 4, OrderEvent.CANCEL_CONFIRMED),
            ),
            OrderState.CANCELED,
            "974.99",
            "0.25",
            "0.75",
            "0.01",
        ),
        (
            (
                accepted(),
                execution("a", 2, "0.25"),
                control("expire", 3, OrderEvent.BROKER_EXPIRED),
            ),
            OrderState.EXPIRED,
            "974.99",
            "0.25",
            "0.75",
            "0.01",
        ),
        (
            (
                accepted(),
                control("cancel", 2, OrderEvent.REQUEST_CANCEL),
                execution("a", 3, "0.25"),
            ),
            OrderState.CANCEL_PENDING,
            "974.99",
            "0.25",
            "0.75",
            "0.01",
        ),
        (
            (accepted(), control("cancel", 2, OrderEvent.REQUEST_CANCEL), execution("a", 3, "1")),
            OrderState.FILLED,
            "899.99",
            "1",
            "0",
            "0.01",
        ),
    ],
)
def test_scripted_lifecycle_outcomes(events, state, cash, position, remaining, fees):
    result = replay_order_lifecycle(make_request(events))
    assert result.snapshot.order.state is state
    assert result.snapshot.cash == Decimal(cash)
    assert result.snapshot.position.quantity == Decimal(position)
    assert result.snapshot.remaining_quantity == Decimal(remaining)
    assert result.snapshot.fees == Decimal(fees)
    assert result.order_terminal == (
        state
        in {
            OrderState.FILLED,
            OrderState.CANCELED,
            OrderState.REJECTED,
            OrderState.EXPIRED,
        }
    )


def test_duplicate_after_completion_changes_receipts_not_economics():
    fill = execution("fill", 2, "1")
    request = make_request((accepted(), fill))
    original = replay_order_lifecycle(request)
    duplicate = replay_order_lifecycle(replace(request, events=(*request.events, fill, accepted())))
    assert duplicate.snapshot == original.snapshot
    assert duplicate.result_hash != original.result_hash
    assert [receipt.applied for receipt in duplicate.receipts] == [True, True, False, False]
    assert duplicate.receipts[-1].reason_code == "duplicate_event"


def test_duplicate_does_not_reset_cursor_or_block_later_fill():
    first = execution("first", 2, "0.25")
    result = replay_order_lifecycle(
        make_request((accepted(), first, accepted(), first, execution("second", 3, "0.75")))
    )
    assert result.snapshot.cash == Decimal("899.98")
    assert result.snapshot.fees == Decimal("0.02")
    assert result.snapshot.cursor.sequence == 3


@pytest.mark.parametrize(
    "last",
    [
        control("again", 3, OrderEvent.BROKER_ACCEPTED),
        control("reject", 3, OrderEvent.BROKER_REJECTED),
        control("confirm", 3, OrderEvent.CANCEL_CONFIRMED),
        execution("extra", 3, "0.1"),
    ],
)
def test_terminal_order_does_not_reopen(last):
    with pytest.raises(LifecycleValidationError):
        replay_order_lifecycle(make_request((accepted(), execution("full", 2, "1"), last)))


def test_control_does_not_revalue_position_or_reobserve_it():
    first = execution("partial", 2, "0.25")
    partial = replay_order_lifecycle(make_request((accepted(), first)))
    canceled = replay_order_lifecycle(
        make_request(
            (
                accepted(),
                first,
                control("cancel", 3, OrderEvent.REQUEST_CANCEL),
                control("confirm", 4, OrderEvent.CANCEL_CONFIRMED),
            )
        )
    )
    assert canceled.snapshot.position == partial.snapshot.position
    assert canceled.snapshot.order.updated_at > partial.snapshot.order.updated_at


def test_sell_replay_closes_only_executed_quantity():
    result = replay_order_lifecycle(
        make_request(
            (accepted(), execution("fill", 2, "0.25", side=Side.SELL)),
            side=Side.SELL,
            quantity="0.25",
            position_quantity="0.25",
            average_price="90",
        )
    )
    assert result.snapshot.cash == Decimal("1024.99")
    assert result.snapshot.position.quantity == 0


def test_replay_is_fresh_and_binds_initial_provenance():
    request = make_request((accepted(), execution("fill", 2, "1")))
    first = replay_order_lifecycle(request)
    assert replay_order_lifecycle(request) == first
    changed = replace(request, position=replace(request.position, data_hash="e" * 64))
    assert replay_order_lifecycle(changed).result_hash != first.result_hash
    assert replay_order_lifecycle(changed).snapshot.snapshot_hash != first.snapshot.snapshot_hash
    assert request.order.state is OrderState.SUBMISSION_PENDING
    assert request.position.quantity == 0
