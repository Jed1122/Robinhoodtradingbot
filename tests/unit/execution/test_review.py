"""Unit tests for exact broker-neutral order review."""

from dataclasses import replace
from datetime import timedelta

import pytest

from tests.unit.execution._fixtures import make_intent, make_review
from trading_bot.domain import BrokerOrderReview, DomainValidationError, OrderIntentId
from trading_bot.execution.review import (
    OrderReviewMismatch,
    OrderReviewService,
    review_is_fresh,
    review_matches_intent,
)


class FakeReviewCapability:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls = 0

    async def review_order(self, intent: object) -> object:
        del intent
        self.calls += 1
        return self.response


@pytest.mark.asyncio
async def test_review_service_returns_one_exact_matching_review() -> None:
    intent = make_intent()
    expected = make_review(intent)
    capability = FakeReviewCapability(expected)
    service = OrderReviewService(capability)  # type: ignore[arg-type]

    actual = await service.review(intent)

    assert actual is expected
    assert capability.calls == 1


@pytest.mark.asyncio
async def test_review_service_rejects_normalized_intent_mismatch() -> None:
    intent = make_intent()
    other_intent = replace(
        intent,
        id=OrderIntentId("00000000-0000-4000-8000-000000000009"),
    )
    capability = FakeReviewCapability(make_review(other_intent))
    service = OrderReviewService(capability)  # type: ignore[arg-type]

    with pytest.raises(OrderReviewMismatch, match="broker review did not match intent"):
        await service.review(intent)

    assert capability.calls == 1


@pytest.mark.asyncio
async def test_review_service_rejects_noncanonical_response_without_rendering_it() -> None:
    response = object()
    service = OrderReviewService(FakeReviewCapability(response))  # type: ignore[arg-type]

    with pytest.raises(OrderReviewMismatch) as captured:
        await service.review(make_intent())

    assert type(captured.value) is OrderReviewMismatch
    assert repr(response) not in str(captured.value)


@pytest.mark.asyncio
async def test_review_service_rejects_noncanonical_intent_before_capability_call() -> None:
    intent = make_intent()
    capability = FakeReviewCapability(make_review(intent))
    service = OrderReviewService(capability)  # type: ignore[arg-type]

    with pytest.raises(DomainValidationError, match="intent must be an OrderIntent"):
        await service.review(object())  # type: ignore[arg-type]

    assert capability.calls == 0


def test_review_match_helper_requires_exact_canonical_records() -> None:
    intent = make_intent()
    review = make_review(intent)

    assert review_matches_intent(review, intent)
    assert not review_matches_intent(
        replace(
            review,
            normalized_order=replace(
                intent,
                id=OrderIntentId("00000000-0000-4000-8000-000000000009"),
            ),
        ),
        intent,
    )
    with pytest.raises(DomainValidationError):
        review_matches_intent(object(), intent)  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError):
        review_matches_intent(review, object())  # type: ignore[arg-type]


def test_review_mismatch_error_has_no_mutable_or_secret_bearing_state() -> None:
    error = OrderReviewMismatch()

    assert error.args == ("broker review did not match intent",)
    assert OrderReviewMismatch.__slots__ == ()
    assert vars(error) == {}
    assert BrokerOrderReview is not object


def test_review_freshness_has_hard_thirty_second_bound() -> None:
    review = make_review(make_intent())
    assert review_is_fresh(review, review.reviewed_at + timedelta(seconds=29))
    assert not review_is_fresh(review, review.reviewed_at + timedelta(seconds=31))
    with pytest.raises(DomainValidationError, match="within thirty seconds"):
        review_is_fresh(review, review.reviewed_at, timedelta(seconds=31))
