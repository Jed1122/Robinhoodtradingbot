from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest

from trading_bot.domain import BrokerOrder, BrokerOrderId, CancelReceipt, OrderIntent
from trading_bot.execution.cancel_policy import (
    CancelReplaceService,
    RemainingOrderDecision,
    evaluate_remainder,
)


def test_replacement_policy_requires_review_for_stale_remainder() -> None:
    assert (
        evaluate_remainder(
            age=timedelta(minutes=6),
            quote_move=Decimal("0"),
            remaining_risk_allowed=True,
            strategy_valid=True,
        )
        is RemainingOrderDecision.REVIEW_REPLACEMENT
    )


def test_invalid_strategy_cancels_instead_of_replacing() -> None:
    assert (
        evaluate_remainder(
            age=timedelta(),
            quote_move=Decimal("0"),
            remaining_risk_allowed=True,
            strategy_valid=False,
        )
        is RemainingOrderDecision.CANCEL
    )


def test_fresh_valid_remainder_is_left_alone() -> None:
    assert (
        evaluate_remainder(
            age=timedelta(),
            quote_move=Decimal("0"),
            remaining_risk_allowed=True,
            strategy_valid=True,
        )
        is RemainingOrderDecision.LEAVE
    )


def test_large_quote_move_requires_replacement_review() -> None:
    assert (
        evaluate_remainder(
            age=timedelta(),
            quote_move=Decimal("-0.02"),
            remaining_risk_allowed=True,
            strategy_valid=True,
        )
        is RemainingOrderDecision.REVIEW_REPLACEMENT
    )


@pytest.mark.asyncio
async def test_replacement_waits_for_confirmed_cancel() -> None:
    class Cancel:
        accepted = False

        async def cancel_known_order(self, account_id, order_id):  # type: ignore[no-untyped-def]
            del account_id
            return CancelReceipt(
                order_id, self.accepted, False, datetime(2026, 7, 17, tzinfo=UTC), "result"
            )

    class Reviewer:
        calls = 0

        async def review_replacement(self, intent):  # type: ignore[no-untyped-def]
            del intent
            self.calls += 1
            return "review"

    cancel, reviewer = Cancel(), Reviewer()
    service = CancelReplaceService(cancel, reviewer)  # type: ignore[arg-type]
    order = cast(
        BrokerOrder,
        SimpleNamespace(account_id="account", broker_order_id=BrokerOrderId("order")),
    )
    intent = cast(OrderIntent, object())
    assert (await service.replace(order, intent)).replacement_review is None
    cancel.accepted = True
    assert (await service.replace(order, intent)).replacement_review == "review"
    assert reviewer.calls == 1
