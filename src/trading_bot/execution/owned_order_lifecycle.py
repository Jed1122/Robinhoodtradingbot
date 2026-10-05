"""Versioned local post-submission facts; never an authenticated broker mapper."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Context, Decimal, DecimalException, Inexact, localcontext
from typing import NoReturn

from trading_bot.clock import require_utc
from trading_bot.domain import (
    AccountId,
    BrokerOrder,
    BrokerOrderId,
    DataHash,
    Fill,
    FillId,
    InstrumentId,
    OrderEvent,
    OrderId,
    OrderState,
    Side,
)
from trading_bot.domain.decimal_utils import canonical_decimal_text, require_bounded_decimal
from trading_bot.domain.order_state_machine import InvalidOrderTransition, transition

VERSION = "owned-equity-lifecycle-v1"
MAX_EVENTS = 10_000
MAX_PAYLOAD_BYTES = 16_384
_FILL_EVENTS = frozenset({OrderEvent.PARTIAL_FILL, OrderEvent.FILL})
_CONTROL_EVENTS = frozenset(
    {
        OrderEvent.REQUEST_CANCEL,
        OrderEvent.CANCEL_CONFIRMED,
        OrderEvent.CANCEL_REJECTED,
        OrderEvent.BROKER_EXPIRED,
        OrderEvent.RECONCILIATION_DRIFT,
        OrderEvent.BROKER_AMBIGUOUS,
        OrderEvent.RECONCILE_SUBMITTED,
        OrderEvent.RECONCILE_PARTIAL,
        OrderEvent.RECONCILE_FILLED,
        OrderEvent.RECONCILE_CANCELED,
        OrderEvent.RECONCILE_REJECTED,
        OrderEvent.RECONCILE_EXPIRED,
    }
)


class OwnedOrderError(ValueError):
    """Stable sanitized denial; input payloads and identifiers are never rendered."""

    def __init__(self) -> None:
        super().__init__("owned_order_event_invalid")


def _deny() -> NoReturn:
    raise OwnedOrderError() from None


def _identifier(value: str) -> None:
    if type(value) is not str or not value.strip() or len(value) > 255:
        _deny()


@dataclass(frozen=True, slots=True)
class OwnedOrderEvent:
    id: str
    order_id: OrderId
    event: OrderEvent
    occurred_at: datetime
    data_hash: DataHash
    fill: Fill | None = None
    external_execution_key: str | None = None
    occurrence_ordinal: int | None = None

    def __post_init__(self) -> None:
        try:
            _identifier(self.id)
            _identifier(self.order_id)
            require_utc(self.occurred_at)
            if (
                type(self.data_hash) is not str
                or len(self.data_hash) != 64
                or any(c not in "0123456789abcdef" for c in self.data_hash)
            ):
                _deny()
            if type(self.event) is not OrderEvent:
                _deny()
            if self.event in _FILL_EVENTS:
                if type(self.fill) is not Fill:
                    _deny()
                replace(self.fill)
                for value in (
                    self.fill.id,
                    self.fill.broker_order_id,
                    self.fill.account_id,
                    self.fill.instrument_id,
                ):
                    _identifier(value)
                require_bounded_decimal(self.fill.quantity, "quantity", positive=True)
                require_bounded_decimal(self.fill.price, "price", positive=True)
                require_bounded_decimal(self.fill.fee, "fee", nonnegative=True)
                if type(self.external_execution_key) is not str:
                    _deny()
                _identifier(self.external_execution_key)
                if (
                    type(self.occurrence_ordinal) is not int
                    or not 0 <= self.occurrence_ordinal < MAX_EVENTS
                ):
                    _deny()
            elif (
                self.event not in _CONTROL_EVENTS
                or self.fill is not None
                or self.external_execution_key is not None
                or self.occurrence_ordinal is not None
            ):
                _deny()
        except (ValueError, TypeError, AttributeError):
            _deny()


def _canonical(event: OwnedOrderEvent) -> dict[str, object]:
    if type(event) is not OwnedOrderEvent:
        _deny()
    event.__post_init__()
    fill = event.fill
    return {
        "version": VERSION,
        "id": event.id,
        "order_id": event.order_id,
        "event": event.event.value,
        "occurred_at": event.occurred_at.isoformat(),
        "data_hash": event.data_hash,
        "external_execution_key": event.external_execution_key,
        "occurrence_ordinal": event.occurrence_ordinal,
        "fill": None
        if fill is None
        else {
            "id": fill.id,
            "broker_order_id": fill.broker_order_id,
            "account_id": fill.account_id,
            "instrument_id": fill.instrument_id,
            "side": fill.side.value,
            "quantity": canonical_decimal_text(fill.quantity),
            "price": canonical_decimal_text(fill.price),
            "fee": canonical_decimal_text(fill.fee),
            "occurred_at": fill.occurred_at.isoformat(),
            "data_hash": fill.data_hash,
        },
    }


def encode_owned_event(event: OwnedOrderEvent) -> str:
    try:
        encoded = json.dumps(
            _canonical(event),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        if len(encoded.encode("ascii")) > MAX_PAYLOAD_BYTES:
            _deny()
        return encoded
    except (ValueError, TypeError, AttributeError):
        _deny()


def decode_owned_event(payload: str) -> OwnedOrderEvent:
    """Require the exact canonical encoding, not permissive provider JSON."""
    try:
        if type(payload) is not str or len(payload) > MAX_PAYLOAD_BYTES:
            _deny()
        data = json.loads(payload)
        if type(data) is not dict or data["version"] != VERSION:
            _deny()
        raw = data["fill"]
        fill = None
        if raw is not None:
            if type(raw) is not dict:
                _deny()
            fill = Fill(
                id=FillId(raw["id"]),
                broker_order_id=BrokerOrderId(raw["broker_order_id"]),
                account_id=AccountId(raw["account_id"]),
                instrument_id=InstrumentId(raw["instrument_id"]),
                side=Side(raw["side"]),
                quantity=Decimal(raw["quantity"]),
                price=Decimal(raw["price"]),
                fee=Decimal(raw["fee"]),
                occurred_at=datetime.fromisoformat(raw["occurred_at"]),
                data_hash=DataHash(raw["data_hash"]),
            )
        event = OwnedOrderEvent(
            id=data["id"],
            order_id=OrderId(data["order_id"]),
            event=OrderEvent(data["event"]),
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            data_hash=DataHash(data["data_hash"]),
            fill=fill,
            external_execution_key=data["external_execution_key"],
            occurrence_ordinal=data["occurrence_ordinal"],
        )
        if encode_owned_event(event) != payload:
            _deny()
        return event
    except (ValueError, TypeError, KeyError, AttributeError, DecimalException):
        _deny()


def advance_owned_order(order: BrokerOrder, event: OwnedOrderEvent) -> BrokerOrder:
    """Advance order quantity/state only; cash/reservations remain another owner's concern."""
    try:
        if type(order) is not BrokerOrder:
            _deny()
        order = replace(order)
        _canonical(event)
        if event.order_id != order.id or event.occurred_at < order.updated_at:
            _deny()
        next_state = transition(order.state, event.event)
        filled = order.filled_quantity
        fill = event.fill
        if fill is not None:
            if (
                fill.account_id != order.account_id
                or fill.instrument_id != order.instrument_id
                or fill.broker_order_id != order.broker_order_id
                or fill.side is not order.side
                or not order.created_at <= fill.occurred_at <= event.occurred_at
            ):
                _deny()
            if order.limit_price is not None and (
                (fill.side is Side.BUY and fill.price > order.limit_price)
                or (fill.side is Side.SELL and fill.price < order.limit_price)
            ):
                _deny()
            context = Context(prec=28)
            context.traps[Inexact] = True
            with localcontext(context):
                filled += fill.quantity
                remaining = order.requested_quantity - filled
                require_bounded_decimal(filled, "filled", nonnegative=True)
                require_bounded_decimal(remaining, "remaining", nonnegative=True)
            complete = filled == order.requested_quantity
            if (event.event is OrderEvent.FILL) != complete:
                _deny()
        if (
            (next_state is OrderState.SUBMITTED and filled != 0)
            or (
                next_state is OrderState.PARTIALLY_FILLED
                and not 0 < filled < order.requested_quantity
            )
            or (next_state is OrderState.FILLED and filled != order.requested_quantity)
        ):
            _deny()
        return replace(
            order,
            state=next_state,
            filled_quantity=filled,
            updated_at=event.occurred_at,
            data_hash=event.data_hash,
        )
    except (ValueError, TypeError, AttributeError, DecimalException, InvalidOrderTransition):
        _deny()


__all__ = [
    "OwnedOrderError",
    "OwnedOrderEvent",
    "advance_owned_order",
    "decode_owned_event",
    "encode_owned_event",
]
