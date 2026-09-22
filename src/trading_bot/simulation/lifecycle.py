"""Pure single-order synthetic replay; no broker, ledger, or runtime integration."""

from dataclasses import replace
from decimal import Decimal

from trading_bot.domain import DataHash, OrderEvent
from trading_bot.domain.order_state_machine import InvalidOrderTransition, transition
from trading_bot.simulation.lifecycle_accounting import apply_lifecycle_fill
from trading_bot.simulation.lifecycle_codec import lifecycle_hash
from trading_bot.simulation.lifecycle_models import (
    LifecycleControlEvent,
    LifecycleErrorReason,
    LifecycleEvent,
    LifecycleFillEvent,
    LifecycleReceipt,
    LifecycleRequest,
    LifecycleResult,
    LifecycleSnapshot,
    deny,
)


def _state_payload(snapshot: LifecycleSnapshot) -> dict[str, object]:
    return {
        "order": snapshot.order,
        "position": snapshot.position,
        "cash": snapshot.cash,
        "fees": snapshot.fees,
        "remaining_quantity": snapshot.remaining_quantity,
        "cursor": snapshot.cursor,
    }


def _check_identity(snapshot: LifecycleSnapshot, event: LifecycleEvent) -> None:
    identity = event.fill if isinstance(event, LifecycleFillEvent) else event
    order = snapshot.order
    if (
        identity.account_id != order.account_id
        or identity.instrument_id != order.instrument_id
        or identity.broker_order_id != order.broker_order_id
        or (isinstance(event, LifecycleFillEvent) and event.fill.side is not order.side)
    ):
        deny(LifecycleErrorReason.IDENTITY)


def _advance(
    snapshot: LifecycleSnapshot,
    event: LifecycleEvent,
    event_digest: DataHash,
) -> LifecycleSnapshot:
    try:
        if isinstance(event, LifecycleControlEvent):
            state = transition(snapshot.order.state, event.event)
            order = replace(
                snapshot.order,
                state=state,
                updated_at=event.cursor.occurred_at,
                data_hash=event_digest,
            )
            return replace(snapshot, order=order, cursor=event.cursor)
        accounting = apply_lifecycle_fill(snapshot, event.fill)
        order_event = (
            OrderEvent.FILL if accounting.remaining_quantity == 0 else OrderEvent.PARTIAL_FILL
        )
        state = transition(snapshot.order.state, order_event)
        order = replace(
            snapshot.order,
            state=state,
            filled_quantity=accounting.filled_quantity,
            updated_at=event.cursor.occurred_at,
            data_hash=event_digest,
        )
        position = replace(accounting.position, data_hash=event_digest)
        return replace(
            snapshot,
            order=order,
            position=position,
            cash=accounting.cash,
            fees=accounting.fees,
            remaining_quantity=accounting.remaining_quantity,
            cursor=event.cursor,
        )
    except InvalidOrderTransition:
        deny(LifecycleErrorReason.TRANSITION)


def replay_order_lifecycle(request: LifecycleRequest) -> LifecycleResult:
    """Replay from fresh state; reject a malformed script without returning partial effects."""
    if type(request) is not LifecycleRequest:
        deny()
    request.__post_init__()
    initial_payload: dict[str, object] = {
        "order": request.order,
        "position": request.position,
        "cash": request.cash,
        "fees": Decimal("0"),
        "remaining_quantity": request.order.requested_quantity,
        "cursor": request.submitted,
    }
    initial_hash = lifecycle_hash("initial_snapshot", initial_payload)
    snapshot = LifecycleSnapshot(
        request.order,
        request.position,
        request.cash,
        Decimal("0"),
        request.order.requested_quantity,
        request.submitted,
        initial_hash,
    )
    seen_events: dict[str, DataHash] = {}
    seen_fills: set[str] = set()
    applied_digests: tuple[DataHash, ...] = ()
    receipts: list[LifecycleReceipt] = []
    for event in request.events:
        _check_identity(snapshot, event)
        digest = lifecycle_hash("event", {"initial": initial_hash, "event": event})
        prior = seen_events.get(event.event_id)
        if prior is not None:
            if prior != digest:
                deny(LifecycleErrorReason.DUPLICATE)
            receipts.append(
                LifecycleReceipt(
                    event.event_id,
                    digest,
                    False,
                    "duplicate_event",
                    snapshot.snapshot_hash,
                )
            )
            continue
        if isinstance(event, LifecycleFillEvent) and event.fill.id in seen_fills:
            deny(LifecycleErrorReason.DUPLICATE)
        if (
            event.cursor.sequence <= snapshot.cursor.sequence
            or event.cursor.occurred_at < snapshot.cursor.occurred_at
            or (
                isinstance(event, LifecycleFillEvent)
                and event.cursor.occurred_at <= request.submitted.occurred_at
            )
        ):
            deny(LifecycleErrorReason.ORDERING)
        candidate = _advance(snapshot, event, digest)
        candidate_digests = (*applied_digests, digest)
        snapshot_hash = lifecycle_hash(
            "snapshot",
            {
                "initial": initial_hash,
                "state": _state_payload(candidate),
                "applied_events": candidate_digests,
            },
        )
        candidate = replace(candidate, snapshot_hash=snapshot_hash)
        receipt = LifecycleReceipt(event.event_id, digest, True, "event_applied", snapshot_hash)
        # Publish only locally after every record and hash was successfully validated.
        snapshot = candidate
        applied_digests = candidate_digests
        seen_events[event.event_id] = digest
        if isinstance(event, LifecycleFillEvent):
            seen_fills.add(event.fill.id)
        receipts.append(receipt)
    result_hash = lifecycle_hash(
        "result",
        {
            "initial": initial_hash,
            "final": snapshot.snapshot_hash,
            "receipts": tuple(receipts),
        },
    )
    return LifecycleResult(snapshot, tuple(receipts), result_hash)
