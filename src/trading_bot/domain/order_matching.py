"""Exact identity and economic matching for reviewed and submitted orders."""

from trading_bot.domain.decimal_utils import DomainValidationError
from trading_bot.domain.orders import (
    BrokerOrder,
    BrokerOrderReview,
    OrderIntent,
    PersistedReviewedOrder,
)


def review_matches_intent(review: BrokerOrderReview, intent: OrderIntent) -> bool:
    """Return whether a canonical review preserves the complete requested intent."""

    if type(review) is not BrokerOrderReview:
        raise DomainValidationError("review must be a BrokerOrderReview")
    if type(intent) is not OrderIntent:
        raise DomainValidationError("intent must be an OrderIntent")
    return review.normalized_order == intent


def broker_order_matches_submission(
    order: BrokerOrder,
    submission: PersistedReviewedOrder,
) -> bool:
    """Bind a broker response to the exact reviewed local economic effect."""

    if type(order) is not BrokerOrder:
        raise DomainValidationError("order must be a BrokerOrder")
    if type(submission) is not PersistedReviewedOrder:
        raise DomainValidationError("submission must be a PersistedReviewedOrder")
    intent = submission.review.normalized_order
    return (
        order.intent_id == intent.id
        and order.account_id == submission.account_id == intent.account_id
        and order.client_order_id == submission.review.client_order_id
        and order.instrument_id == intent.instrument_id
        and order.side is intent.side
        and order.purpose is intent.purpose
        and order.order_type is intent.order_type
        and order.time_in_force is intent.time_in_force
        and order.requested_quantity == intent.quantity
        and order.limit_price == intent.limit_price
        and order.stop_price == intent.stop_price
    )


__all__ = ["broker_order_matches_submission", "review_matches_intent"]
