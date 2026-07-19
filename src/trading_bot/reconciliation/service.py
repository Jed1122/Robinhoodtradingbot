"""Broker/local comparison with no generic drift tolerance."""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Protocol

from trading_bot.brokers import BrokerRead
from trading_bot.clock import Clock
from trading_bot.domain import AccountId, AccountSnapshot, AssetClass, BrokerOrder, Fill, Position
from trading_bot.domain.decimal_utils import canonical_decimal_text
from trading_bot.reconciliation.models import ReconciliationDifference, ReconciliationResult


class LocalReconciliationState(Protocol):
    async def account(self, account_id: AccountId) -> AccountSnapshot: ...
    async def positions(self, account_id: AccountId) -> tuple[Position, ...]: ...
    async def orders(self, account_id: AccountId) -> tuple[BrokerOrder, ...]: ...
    async def fills(self, account_id: AccountId) -> tuple[Fill, ...]: ...


class ReconciliationStore(Protocol):
    async def persist(self, result: ReconciliationResult) -> None: ...


def _decimal(value: Decimal) -> str:
    return canonical_decimal_text(value)


def _compare_by_key(
    local: tuple[object, ...],
    broker: tuple[object, ...],
    *,
    key: str,
    code: str,
    values: tuple[str, ...],
    differences: list[ReconciliationDifference],
) -> None:
    local_map = {str(getattr(item, key)): item for item in local}
    broker_map = {str(getattr(item, key)): item for item in broker}
    for identity in sorted(local_map.keys() | broker_map.keys()):
        left = local_map.get(identity)
        right = broker_map.get(identity)
        if left is None or right is None:
            differences.append(
                ReconciliationDifference(
                    f"unexpected_broker_{code}" if left is None else f"missing_broker_{code}",
                    identity,
                    None if left is None else "present",
                    None if right is None else "present",
                )
            )
        elif any(getattr(left, value) != getattr(right, value) for value in values):
            left_value = "|".join(str(getattr(left, value)) for value in values)
            right_value = "|".join(str(getattr(right, value)) for value in values)
            differences.append(
                ReconciliationDifference(
                    f"{code}_state_mismatch",
                    identity,
                    left_value,
                    right_value,
                )
            )


class ReconciliationService:
    def __init__(
        self,
        broker: BrokerRead,
        local: LocalReconciliationState,
        store: ReconciliationStore,
        clock: Clock,
    ) -> None:
        self._broker = broker
        self._local = local
        self._store = store
        self._clock = clock

    async def reconcile(self, account_id: AccountId) -> ReconciliationResult:
        now = self._clock.now()
        differences: list[ReconciliationDifference] = []
        accounts = await self._broker.get_accounts()
        if tuple(account.account_id for account in accounts) != (account_id,):
            differences.append(
                ReconciliationDifference(
                    "account_identity_mismatch",
                    str(account_id),
                    str(account_id),
                    ",".join(account.account_id for account in accounts),
                )
            )
        local_account = await self._local.account(account_id)
        broker_account = await self._broker.get_account_state(account_id)
        for field in ("provider_state", "restricted", "equity", "cash"):
            if getattr(local_account, field) != getattr(broker_account, field):
                differences.append(
                    ReconciliationDifference(
                        f"account_{field}_mismatch",
                        str(account_id),
                        str(getattr(local_account, field)),
                        str(getattr(broker_account, field)),
                    )
                )
        local_positions = await self._local.positions(account_id)
        broker_positions = await self._broker.get_positions(account_id)
        _compare_by_key(
            local_positions,
            broker_positions,
            key="instrument_id",
            code="position",
            values=("quantity",),
            differences=differences,
        )
        local_orders = await self._local.orders(account_id)
        broker_orders = (
            *await self._broker.get_open_orders(account_id),
            *await self._broker.get_recent_orders(account_id, now - timedelta(days=1)),
        )
        _compare_by_key(
            local_orders,
            tuple(broker_orders),
            key="broker_order_id",
            code="order",
            values=(
                "instrument_id",
                "side",
                "purpose",
                "requested_quantity",
                "filled_quantity",
                "state",
            ),
            differences=differences,
        )
        local_fills = await self._local.fills(account_id)
        broker_fills = await self._broker.get_fills(account_id, now - timedelta(days=1))
        _compare_by_key(
            local_fills,
            broker_fills,
            key="id",
            code="fill",
            values=("broker_order_id", "instrument_id", "side", "quantity", "price", "fee"),
            differences=differences,
        )
        for asset_class in AssetClass:
            try:
                local_power = local_account.buying_power_for(asset_class)
            except ValueError:
                differences.append(
                    ReconciliationDifference(
                        "missing_local_buying_power", asset_class.value, None, "present"
                    )
                )
                local_power = None
            broker_power = await self._broker.get_buying_power(account_id, asset_class)
            if local_power is not None and local_power != broker_power:
                differences.append(
                    ReconciliationDifference(
                        "buying_power_mismatch",
                        asset_class.value,
                        _decimal(local_power),
                        _decimal(broker_power),
                    )
                )
        result = ReconciliationResult(
            str(uuid.uuid4()), account_id, not differences, tuple(differences), now
        )
        await self._store.persist(result)
        return result


__all__ = ["LocalReconciliationState", "ReconciliationService", "ReconciliationStore"]
