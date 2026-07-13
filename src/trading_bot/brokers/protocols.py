"""Broker-neutral least-privilege capability protocols."""

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from trading_bot.domain import (
    AccountId,
    AccountSnapshot,
    AssetClass,
    BrokerHealth,
    BrokerOrder,
    BrokerOrderId,
    BrokerOrderReview,
    CancelReceipt,
    Fill,
    OrderIntent,
    PersistedReviewedOrder,
    Position,
)

__all__ = ["BrokerCancelOnly", "BrokerPlace", "BrokerRead", "BrokerReview"]


class BrokerRead(Protocol):
    """Read-only broker account and order-state capability."""

    async def get_accounts(self) -> tuple[AccountSnapshot, ...]: ...

    async def get_account_state(self, account_id: AccountId) -> AccountSnapshot: ...

    async def get_positions(self, account_id: AccountId) -> tuple[Position, ...]: ...

    async def get_open_orders(self, account_id: AccountId) -> tuple[BrokerOrder, ...]: ...

    async def get_recent_orders(
        self,
        account_id: AccountId,
        since: datetime,
    ) -> tuple[BrokerOrder, ...]: ...

    async def get_fills(self, account_id: AccountId, since: datetime) -> tuple[Fill, ...]: ...

    async def get_buying_power(
        self,
        account_id: AccountId,
        asset_class: AssetClass,
    ) -> Decimal: ...

    async def health_check(self) -> BrokerHealth: ...


class BrokerReview(Protocol):
    """Broker order-review capability without placement authority."""

    async def review_order(self, intent: OrderIntent) -> BrokerOrderReview: ...


class BrokerPlace(Protocol):
    """Placement capability accepting only a persisted reviewed order."""

    async def place_order(self, submission: PersistedReviewedOrder) -> BrokerOrder: ...


class BrokerCancelOnly(Protocol):
    """Cancel-only capability limited to a positively identified order."""

    async def cancel_known_order(
        self,
        account_id: AccountId,
        order_id: BrokerOrderId,
    ) -> CancelReceipt: ...
