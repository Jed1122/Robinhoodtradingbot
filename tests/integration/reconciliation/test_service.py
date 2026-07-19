from datetime import UTC, datetime
from decimal import Decimal

import pytest

from trading_bot.domain import (
    AccountId,
    AccountSnapshot,
    AssetBuyingPower,
    AssetClass,
    BrokerOrder,
    BrokerOrderId,
    DataHash,
    InstrumentId,
    OrderId,
    OrderPurpose,
    OrderState,
    OrderType,
    Side,
    TimeInForce,
)
from trading_bot.reconciliation import ReconciliationService

NOW = datetime(2026, 7, 17, tzinfo=UTC)
ACCOUNT = AccountId("account-1")
HASH = DataHash("a" * 64)


def account() -> AccountSnapshot:
    return AccountSnapshot(
        ACCOUNT,
        "active",
        Decimal("100"),
        Decimal("100"),
        tuple(AssetBuyingPower(asset, Decimal("100")) for asset in AssetClass),
        False,
        NOW,
        HASH,
    )


def unexpected_order() -> BrokerOrder:
    return BrokerOrder(
        OrderId("local-external"),
        BrokerOrderId("broker-external"),
        ACCOUNT,
        None,
        None,
        InstrumentId("instrument-1"),
        Side.BUY,
        OrderPurpose.ENTRY,
        OrderType.LIMIT,
        TimeInForce.GOOD_FOR_DAY,
        Decimal("1"),
        Decimal("0"),
        Decimal("10"),
        None,
        OrderState.SUBMITTED,
        NOW,
        NOW,
        HASH,
    )


class Clock:
    def now(self) -> datetime:
        return NOW


class Local:
    async def account(self, account_id: AccountId) -> AccountSnapshot:
        return account()

    async def positions(self, account_id: AccountId) -> tuple:
        return ()

    async def orders(self, account_id: AccountId) -> tuple:
        return ()

    async def fills(self, account_id: AccountId) -> tuple:
        return ()


class Broker:
    open_orders = (unexpected_order(),)

    async def get_accounts(self) -> tuple:
        return (account(),)

    async def get_account_state(self, account_id: AccountId) -> AccountSnapshot:
        return account()

    async def get_positions(self, account_id: AccountId) -> tuple:
        return ()

    async def get_open_orders(self, account_id: AccountId) -> tuple:
        return self.open_orders

    async def get_recent_orders(self, account_id: AccountId, since: datetime) -> tuple:
        return ()

    async def get_fills(self, account_id: AccountId, since: datetime) -> tuple:
        return ()

    async def get_buying_power(self, account_id: AccountId, asset_class: AssetClass) -> Decimal:
        return Decimal("100")

    async def health_check(self) -> object:
        raise AssertionError


class Store:
    result = None

    async def persist(self, result: object) -> None:
        self.result = result


@pytest.mark.asyncio
async def test_unexpected_broker_order_is_material() -> None:
    store = Store()
    service = ReconciliationService(Broker(), Local(), store, Clock())  # type: ignore[arg-type]
    result = await service.reconcile(ACCOUNT)
    assert not result.clean
    assert result.differences[0].code == "unexpected_broker_order"
    assert result.differences[0].material
    assert store.result is result
