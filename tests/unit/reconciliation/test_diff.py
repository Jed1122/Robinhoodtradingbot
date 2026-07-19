from decimal import Decimal

import pytest

from trading_bot.domain import OrderEvent
from trading_bot.reconciliation import IncompatibleReconciliationOutcome, validate_order_outcome


@pytest.mark.parametrize("outcome", [OrderEvent.RECONCILE_SUBMITTED, OrderEvent.RECONCILE_REJECTED])
def test_fill_provenance_blocks_incompatible_reconciliation_outcome(outcome: OrderEvent) -> None:
    with pytest.raises(IncompatibleReconciliationOutcome):
        validate_order_outcome(outcome, Decimal("0.01"))


def test_zero_fill_permits_zero_fill_outcome() -> None:
    validate_order_outcome(OrderEvent.RECONCILE_SUBMITTED, Decimal("0"))
