from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest

from trading_bot.domain import (
    AccountId,
    AccountSnapshot,
    BrokerOrder,
    BrokerOrderId,
    DataHash,
    OrderPurpose,
    RuntimeState,
)
from trading_bot.execution.recovery import RecoveryService
from trading_bot.reconciliation import ReconciliationDifference, ReconciliationResult
from trading_bot.risk import ActionContext

NOW = datetime(2026, 7, 17, tzinfo=UTC)
ACCOUNT = AccountId("account-1")


def account() -> AccountSnapshot:
    return AccountSnapshot(
        ACCOUNT, "active", Decimal("100"), Decimal("100"), (), False, NOW, DataHash("a" * 64)
    )


class Read:
    async def get_accounts(self) -> tuple:
        return (account(),)


class CancelOnly:
    calls = 0

    async def cancel_known_order(self, account_id: AccountId, order_id: str) -> object:
        self.calls += 1
        raise AssertionError


class Reconcile:
    async def reconcile(self, account_id: AccountId) -> ReconciliationResult:
        return ReconciliationResult("reconciliation-1", account_id, True, (), NOW)


class Local:
    async def unfilled_entry_orders(self, account_id: AccountId) -> tuple:
        return ()


@pytest.mark.asyncio
async def test_recovery_uses_cancel_only_capability_and_remains_paused() -> None:
    cancel = CancelOnly()
    context = ActionContext(False, True, True, True, True, False, False, RuntimeState.PAUSED)
    recovery = RecoveryService(Read(), cancel, Reconcile(), Local(), context)  # type: ignore[arg-type]
    result = await recovery.recover(ACCOUNT)
    assert result.state is RuntimeState.PAUSED
    assert not hasattr(cancel, "place_order")


@pytest.mark.asyncio
async def test_clean_recovery_cancels_only_unfilled_entry() -> None:
    class Cancel:
        async def cancel_known_order(self, account_id, order_id):  # type: ignore[no-untyped-def]
            return SimpleNamespace(accepted=True)

    class LocalEntry:
        async def unfilled_entry_orders(self, account_id):  # type: ignore[no-untyped-def]
            return (
                cast(
                    BrokerOrder,
                    SimpleNamespace(
                        purpose=OrderPurpose.ENTRY,
                        filled_quantity=Decimal("0"),
                        broker_order_id=BrokerOrderId("entry"),
                    ),
                ),
            )

    context = ActionContext(False, True, True, True, True, False, False, RuntimeState.PAUSED)
    recovery = RecoveryService(Read(), Cancel(), Reconcile(), LocalEntry(), context)  # type: ignore[arg-type]
    result = await recovery.recover(ACCOUNT)
    assert result.canceled_order_ids == ("entry",)
    assert not result.critical_alert_required


@pytest.mark.asyncio
async def test_dirty_recovery_requires_critical_alert() -> None:
    class Dirty:
        async def reconcile(self, account_id):  # type: ignore[no-untyped-def]
            difference = ReconciliationDifference("position", "BTC", "0", "1")
            return ReconciliationResult("r", account_id, False, (difference,), NOW)

    context = ActionContext(False, True, True, True, True, False, False, RuntimeState.PAUSED)
    recovery = RecoveryService(Read(), CancelOnly(), Dirty(), Local(), context)  # type: ignore[arg-type]
    assert (await recovery.recover(ACCOUNT)).critical_alert_required
