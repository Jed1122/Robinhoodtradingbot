"""Explicit zero-tolerance reconciliation differences and results."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_bot.clock import require_utc
from trading_bot.domain import AccountId, OrderEvent


@dataclass(frozen=True, slots=True)
class ReconciliationDifference:
    code: str
    identity: str
    local_value: str | None
    broker_value: str | None
    material: bool = True


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    reconciliation_id: str
    account_id: AccountId
    clean: bool
    differences: tuple[ReconciliationDifference, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        require_utc(self.observed_at)
        if self.clean != (not self.differences):
            raise ValueError("clean reconciliation cannot contain differences")


class IncompatibleReconciliationOutcome(RuntimeError):
    pass


def validate_order_outcome(event: OrderEvent, cumulative_fill_quantity: Decimal) -> None:
    if (
        event in {OrderEvent.RECONCILE_SUBMITTED, OrderEvent.RECONCILE_REJECTED}
        and cumulative_fill_quantity > 0
    ):
        raise IncompatibleReconciliationOutcome("positive fill provenance blocks zero-fill outcome")


__all__ = [
    "IncompatibleReconciliationOutcome",
    "ReconciliationDifference",
    "ReconciliationResult",
    "validate_order_outcome",
]
