"""Deterministic cancel/replacement policy that cannot replace before terminal cancel."""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from trading_bot.domain import BrokerOrder, CancelReceipt, OrderIntent


class RemainingOrderDecision(StrEnum):
    LEAVE = "leave"
    CANCEL = "cancel"
    REVIEW_REPLACEMENT = "review_replacement"


def evaluate_remainder(
    *, age: timedelta, quote_move: Decimal, remaining_risk_allowed: bool, strategy_valid: bool
) -> RemainingOrderDecision:
    if not remaining_risk_allowed or not strategy_valid:
        return RemainingOrderDecision.CANCEL
    if age >= timedelta(minutes=5) or abs(quote_move) >= Decimal("0.01"):
        return RemainingOrderDecision.REVIEW_REPLACEMENT
    return RemainingOrderDecision.LEAVE


class CancelCapability(Protocol):
    async def cancel_known_order(self, account_id: str, order_id: str) -> CancelReceipt: ...


class ReplacementReviewer(Protocol):
    async def review_replacement(self, intent: OrderIntent) -> object: ...


@dataclass(frozen=True, slots=True)
class CancelReplaceResult:
    cancel: CancelReceipt
    replacement_review: object | None


class CancelReplaceService:
    def __init__(self, cancel: CancelCapability, reviewer: ReplacementReviewer) -> None:
        self._cancel = cancel
        self._reviewer = reviewer

    async def replace(self, order: BrokerOrder, new_intent: OrderIntent) -> CancelReplaceResult:
        receipt = await self._cancel.cancel_known_order(order.account_id, order.broker_order_id)
        if not receipt.accepted or receipt.ambiguous:
            return CancelReplaceResult(receipt, None)
        review = await self._reviewer.review_replacement(new_intent)
        return CancelReplaceResult(receipt, review)


__all__ = [
    "CancelReplaceResult",
    "CancelReplaceService",
    "RemainingOrderDecision",
    "evaluate_remainder",
]
