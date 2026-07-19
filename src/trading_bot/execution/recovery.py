"""Paused startup recovery using read and cancel-only broker capabilities."""

from dataclasses import dataclass, replace
from typing import Protocol

from trading_bot.brokers import BrokerCancelOnly, BrokerRead
from trading_bot.domain import AccountId, BrokerOrder, OrderPurpose, RuntimeState
from trading_bot.reconciliation import ReconciliationResult, ReconciliationService
from trading_bot.risk import ActionContext, BrokerAction, is_action_allowed


class RecoveryState(Protocol):
    async def unfilled_entry_orders(self, account_id: AccountId) -> tuple[BrokerOrder, ...]: ...


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    state: RuntimeState
    reconciliation: ReconciliationResult
    canceled_order_ids: tuple[str, ...]
    critical_alert_required: bool


class RecoveryService:
    def __init__(
        self,
        broker_read: BrokerRead,
        broker_cancel: BrokerCancelOnly,
        reconciliation: ReconciliationService,
        local: RecoveryState,
        action_context: ActionContext,
    ) -> None:
        self._read = broker_read
        self._cancel = broker_cancel
        self._reconciliation = reconciliation
        self._local = local
        self._action_context = action_context

    async def recover(self, account_id: AccountId) -> RecoveryResult:
        accounts = await self._read.get_accounts()
        if tuple(account.account_id for account in accounts) != (account_id,):
            raise RuntimeError("recovery account identity is not exact")
        result = await self._reconciliation.reconcile(account_id)
        canceled: list[str] = []
        if result.clean:
            for order in await self._local.unfilled_entry_orders(account_id):
                if order.purpose is not OrderPurpose.ENTRY or order.filled_quantity != 0:
                    continue
                context = replace(self._action_context, lease_valid=False)
                if is_action_allowed(
                    RuntimeState.PAUSED, BrokerAction.CANCEL_KNOWN_ENTRY, context
                ).allowed:
                    receipt = await self._cancel.cancel_known_order(
                        account_id, order.broker_order_id
                    )
                    if receipt.accepted:
                        canceled.append(order.broker_order_id)
        return RecoveryResult(RuntimeState.PAUSED, result, tuple(canceled), not result.clean)


__all__ = ["RecoveryResult", "RecoveryService", "RecoveryState"]
