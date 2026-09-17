"""Immutable, synthetic-only order lifecycle contracts; no runtime capabilities."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal, DecimalException
from enum import StrEnum
from typing import Literal

from trading_bot.domain import (
    AccountId,
    AssetClass,
    BrokerOrder,
    BrokerOrderId,
    DataHash,
    Fill,
    InstrumentId,
    OrderEvent,
    OrderState,
    OrderType,
    Position,
    TimeInForce,
)
from trading_bot.domain.decimal_utils import (
    _require_exact_bool,
    _require_nonempty,
    _require_sha256_hex,
    _require_tuple,
    require_bounded_decimal,
)
from trading_bot.simulation.events import EventCursor


class LifecycleErrorReason(StrEnum):
    INPUT = "lifecycle_input_invalid"
    IDENTITY = "lifecycle_identity_mismatch"
    DUPLICATE = "lifecycle_duplicate_conflict"
    ORDERING = "lifecycle_ordering_invalid"
    TRANSITION = "lifecycle_transition_invalid"
    ACCOUNTING = "lifecycle_accounting_invalid"
    HASH = "lifecycle_hash_invalid"


class LifecycleValidationError(ValueError):
    def __init__(self, reason: LifecycleErrorReason) -> None:
        self.reason = reason if type(reason) is LifecycleErrorReason else LifecycleErrorReason.INPUT
        super().__init__(self.reason.value)


def deny(reason: LifecycleErrorReason = LifecycleErrorReason.INPUT) -> None:
    raise LifecycleValidationError(reason) from None


@contextmanager
def input_validation() -> Iterator[None]:
    try:
        yield
    except LifecycleValidationError:
        raise
    except (ValueError, DecimalException):
        deny()


def validate_cursor(cursor: EventCursor) -> None:
    if type(cursor) is not EventCursor:
        deny()
    cursor.__post_init__()


def validate_order(order: BrokerOrder) -> None:
    if type(order) is not BrokerOrder:
        deny()
    order.__post_init__()
    for value in (order.requested_quantity, order.filled_quantity):
        require_bounded_decimal(value, "quantity", nonnegative=True)
    for price in (order.limit_price, order.stop_price):
        if price is not None:
            require_bounded_decimal(price, "price", positive=True)


def validate_position(position: Position) -> None:
    if type(position) is not Position:
        deny()
    position.__post_init__()
    require_bounded_decimal(position.quantity, "quantity", nonnegative=True)
    require_bounded_decimal(position.market_value, "market_value", nonnegative=True)
    if position.average_price is not None:
        require_bounded_decimal(position.average_price, "average_price", positive=True)
    if position.quantity > 0 and position.average_price is None:
        deny()
    if position.quantity == 0 and (
        position.average_price is not None or position.market_value != 0
    ):
        deny()


@dataclass(frozen=True, slots=True)
class LifecycleControlEvent:
    event_id: str
    cursor: EventCursor
    account_id: AccountId
    instrument_id: InstrumentId
    broker_order_id: BrokerOrderId
    event: OrderEvent

    def __post_init__(self) -> None:
        with input_validation():
            for value in (self.event_id, self.account_id, self.instrument_id, self.broker_order_id):
                _require_nonempty(value, "identity")
            validate_cursor(self.cursor)
            if type(self.event) is not OrderEvent or self.event not in {
                OrderEvent.BROKER_ACCEPTED,
                OrderEvent.BROKER_REJECTED,
                OrderEvent.REQUEST_CANCEL,
                OrderEvent.CANCEL_CONFIRMED,
                OrderEvent.BROKER_EXPIRED,
            }:
                deny()


@dataclass(frozen=True, slots=True)
class LifecycleFillEvent:
    event_id: str
    cursor: EventCursor
    fill: Fill

    def __post_init__(self) -> None:
        with input_validation():
            _require_nonempty(self.event_id, "event_id")
            validate_cursor(self.cursor)
            if type(self.fill) is not Fill:
                deny()
            self.fill.__post_init__()
            for value in (self.fill.quantity, self.fill.price):
                require_bounded_decimal(value, "fill_value", positive=True)
            require_bounded_decimal(self.fill.fee, "fee", nonnegative=True)
            if self.fill.occurred_at != self.cursor.occurred_at:
                deny(LifecycleErrorReason.ORDERING)


type LifecycleEvent = LifecycleControlEvent | LifecycleFillEvent


@dataclass(frozen=True, slots=True)
class LifecycleRequest:
    order: BrokerOrder
    position: Position
    cash: Decimal
    submitted: EventCursor
    events: tuple[LifecycleEvent, ...]

    def __post_init__(self) -> None:
        with input_validation():
            validate_order(self.order)
            validate_position(self.position)
            validate_cursor(self.submitted)
            require_bounded_decimal(self.cash, "cash", nonnegative=True)
            _require_tuple(self.events, "events")
            for event in self.events:
                if type(event) not in (LifecycleControlEvent, LifecycleFillEvent):
                    deny()
                event.__post_init__()
            if (
                self.order.account_id != self.position.account_id
                or self.order.instrument_id != self.position.instrument_id
            ):
                deny(LifecycleErrorReason.IDENTITY)
            if (
                self.order.state is not OrderState.SUBMISSION_PENDING
                or self.order.filled_quantity != 0
                or self.order.order_type is not OrderType.LIMIT
                or self.order.time_in_force
                not in {
                    TimeInForce.GOOD_FOR_DAY,
                    TimeInForce.GOOD_TIL_CANCELED,
                }
                or self.position.asset_class not in {AssetClass.EQUITY, AssetClass.CRYPTO}
                or self.order.created_at != self.submitted.occurred_at
                or self.order.updated_at != self.submitted.occurred_at
                or self.position.observed_at > self.submitted.occurred_at
            ):
                deny()


@dataclass(frozen=True, slots=True)
class LifecycleSnapshot:
    order: BrokerOrder
    position: Position
    cash: Decimal
    fees: Decimal
    remaining_quantity: Decimal
    cursor: EventCursor
    snapshot_hash: DataHash

    def __post_init__(self) -> None:
        with input_validation():
            validate_order(self.order)
            validate_position(self.position)
            validate_cursor(self.cursor)
            for value in (self.cash, self.fees, self.remaining_quantity):
                require_bounded_decimal(value, "balance", nonnegative=True)
            _require_sha256_hex(self.snapshot_hash, "snapshot_hash")
            if (
                self.order.account_id != self.position.account_id
                or self.order.instrument_id != self.position.instrument_id
            ):
                deny(LifecycleErrorReason.IDENTITY)


@dataclass(frozen=True, slots=True)
class LifecycleReceipt:
    event_id: str
    event_digest: DataHash
    applied: bool
    reason_code: Literal["event_applied", "duplicate_event"]
    snapshot_hash: DataHash

    def __post_init__(self) -> None:
        with input_validation():
            _require_nonempty(self.event_id, "event_id")
            _require_sha256_hex(self.event_digest, "event_digest")
            _require_sha256_hex(self.snapshot_hash, "snapshot_hash")
            _require_exact_bool(self.applied, "applied")
            if type(self.reason_code) is not str or self.reason_code != (
                "event_applied" if self.applied else "duplicate_event"
            ):
                deny()


@dataclass(frozen=True, slots=True)
class LifecycleResult:
    snapshot: LifecycleSnapshot
    receipts: tuple[LifecycleReceipt, ...]
    result_hash: DataHash
    source_kind: Literal["synthetic-order-lifecycle-v1"] = field(
        default="synthetic-order-lifecycle-v1",
        init=False,
    )
    evidence_promotable: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        with input_validation():
            if type(self.snapshot) is not LifecycleSnapshot:
                deny()
            self.snapshot.__post_init__()
            _require_tuple(self.receipts, "receipts")
            for receipt in self.receipts:
                if type(receipt) is not LifecycleReceipt:
                    deny()
                receipt.__post_init__()
            _require_sha256_hex(self.result_hash, "result_hash")

    @property
    def order_terminal(self) -> bool:
        return self.snapshot.order.state in {
            OrderState.FILLED,
            OrderState.CANCELED,
            OrderState.REJECTED,
            OrderState.EXPIRED,
        }
