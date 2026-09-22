"""Exact broker-neutral review wrapper with no placement capability."""

from datetime import datetime, timedelta

from trading_bot.brokers import BrokerReview
from trading_bot.domain import BrokerOrderReview, DomainValidationError, OrderIntent
from trading_bot.domain.order_matching import review_matches_intent


def review_is_fresh(
    review: BrokerOrderReview,
    now: datetime,
    maximum_lifetime: timedelta = timedelta(seconds=30),
) -> bool:
    """Require an unexpired canonical review within the hard 30-second domain bound."""
    if type(review) is not BrokerOrderReview or type(now) is not datetime:
        raise DomainValidationError("review freshness requires canonical values")
    if maximum_lifetime <= timedelta(0) or maximum_lifetime > timedelta(seconds=30):
        raise DomainValidationError("review lifetime must be within thirty seconds")
    return (
        review.reviewed_at <= now < review.expires_at
        and now - review.reviewed_at <= maximum_lifetime
    )


class OrderReviewMismatch(RuntimeError):
    """Indicate that review output cannot be bound to the requested intent."""

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__("broker review did not match intent")


class OrderReviewService:
    """Use an independently injected review-only capability exactly once."""

    __slots__ = ("_review",)

    def __init__(self, review: BrokerReview) -> None:
        self._review = review

    async def review(self, intent: OrderIntent) -> BrokerOrderReview:
        if type(intent) is not OrderIntent:
            raise DomainValidationError("intent must be an OrderIntent")
        reviewed = await self._review.review_order(intent)
        if type(reviewed) is not BrokerOrderReview or not review_matches_intent(
            reviewed,
            intent,
        ):
            raise OrderReviewMismatch() from None
        return reviewed


__all__ = [
    "OrderReviewMismatch",
    "OrderReviewService",
    "review_is_fresh",
    "review_matches_intent",
]
