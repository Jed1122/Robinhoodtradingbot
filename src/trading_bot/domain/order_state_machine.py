"""Pure, deterministic order lifecycle transitions at the domain boundary."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from trading_bot.domain.enums import OrderEvent, OrderState

_ERROR_MESSAGE: Final = "order transition is not allowed"


class InvalidOrderTransition(RuntimeError):
    """Indicate that an order event is invalid for its current state."""

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__(_ERROR_MESSAGE)


_TRANSITIONS: Final[Mapping[tuple[OrderState, OrderEvent], OrderState]] = MappingProxyType(
    {
        (OrderState.PROPOSED, OrderEvent.RISK_DENY): OrderState.RISK_REJECTED,
        (OrderState.PROPOSED, OrderEvent.RISK_ALLOW): OrderState.RISK_APPROVED,
        (OrderState.PROPOSED, OrderEvent.EXPIRE): OrderState.EXPIRED,
        (OrderState.RISK_APPROVED, OrderEvent.REQUEST_REVIEW): OrderState.REVIEW_REQUESTED,
        (OrderState.RISK_APPROVED, OrderEvent.EXPIRE): OrderState.EXPIRED,
        (OrderState.REVIEW_REQUESTED, OrderEvent.REVIEW_ACCEPTED): OrderState.REVIEWED,
        (OrderState.REVIEW_REQUESTED, OrderEvent.REVIEW_REJECTED): OrderState.REJECTED,
        (OrderState.REVIEW_REQUESTED, OrderEvent.EXPIRE): OrderState.EXPIRED,
        (OrderState.REVIEWED, OrderEvent.FINAL_RISK_DENY): OrderState.RISK_REJECTED,
        (OrderState.REVIEWED, OrderEvent.PREPARE_SUBMISSION): OrderState.SUBMISSION_PENDING,
        (OrderState.REVIEWED, OrderEvent.EXPIRE): OrderState.EXPIRED,
        (OrderState.SUBMISSION_PENDING, OrderEvent.BROKER_ACCEPTED): OrderState.SUBMITTED,
        (OrderState.SUBMISSION_PENDING, OrderEvent.BROKER_REJECTED): OrderState.REJECTED,
        (
            OrderState.SUBMISSION_PENDING,
            OrderEvent.BROKER_AMBIGUOUS,
        ): OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
        (OrderState.SUBMITTED, OrderEvent.PARTIAL_FILL): OrderState.PARTIALLY_FILLED,
        (OrderState.SUBMITTED, OrderEvent.FILL): OrderState.FILLED,
        (OrderState.SUBMITTED, OrderEvent.REQUEST_CANCEL): OrderState.CANCEL_PENDING,
        (OrderState.SUBMITTED, OrderEvent.BROKER_EXPIRED): OrderState.EXPIRED,
        (
            OrderState.SUBMITTED,
            OrderEvent.RECONCILIATION_DRIFT,
        ): OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
        (OrderState.PARTIALLY_FILLED, OrderEvent.PARTIAL_FILL): OrderState.PARTIALLY_FILLED,
        (OrderState.PARTIALLY_FILLED, OrderEvent.FILL): OrderState.FILLED,
        (OrderState.PARTIALLY_FILLED, OrderEvent.REQUEST_CANCEL): OrderState.CANCEL_PENDING,
        (OrderState.PARTIALLY_FILLED, OrderEvent.BROKER_EXPIRED): OrderState.EXPIRED,
        (
            OrderState.PARTIALLY_FILLED,
            OrderEvent.RECONCILIATION_DRIFT,
        ): OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
        (OrderState.CANCEL_PENDING, OrderEvent.CANCEL_CONFIRMED): OrderState.CANCELED,
        (
            OrderState.CANCEL_PENDING,
            OrderEvent.CANCEL_REJECTED,
        ): OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
        (OrderState.CANCEL_PENDING, OrderEvent.PARTIAL_FILL): OrderState.CANCEL_PENDING,
        (OrderState.CANCEL_PENDING, OrderEvent.FILL): OrderState.FILLED,
        (OrderState.CANCEL_PENDING, OrderEvent.BROKER_EXPIRED): OrderState.EXPIRED,
        (
            OrderState.CANCEL_PENDING,
            OrderEvent.RECONCILIATION_DRIFT,
        ): OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
        (
            OrderState.CANCEL_PENDING,
            OrderEvent.BROKER_AMBIGUOUS,
        ): OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
        (
            OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
            OrderEvent.RECONCILE_SUBMITTED,
        ): OrderState.SUBMITTED,
        (
            OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
            OrderEvent.RECONCILE_PARTIAL,
        ): OrderState.PARTIALLY_FILLED,
        (
            OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
            OrderEvent.RECONCILE_FILLED,
        ): OrderState.FILLED,
        (
            OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
            OrderEvent.RECONCILE_CANCELED,
        ): OrderState.CANCELED,
        (
            OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
            OrderEvent.RECONCILE_REJECTED,
        ): OrderState.REJECTED,
        (
            OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
            OrderEvent.RECONCILE_EXPIRED,
        ): OrderState.EXPIRED,
    }
)


def transition(current: OrderState, event: OrderEvent) -> OrderState:
    """Return the sole valid next state or fail without rendering unsafe inputs."""

    if type(current) is not OrderState or type(event) is not OrderEvent:
        raise InvalidOrderTransition() from None
    next_state = _TRANSITIONS.get((current, event))
    if next_state is None:
        raise InvalidOrderTransition() from None
    return next_state


__all__ = ["InvalidOrderTransition", "transition"]
