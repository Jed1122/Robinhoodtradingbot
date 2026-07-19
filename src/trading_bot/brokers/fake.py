"""Deterministic in-memory broker for simulation and paper modes only."""

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

from trading_bot.clock import Clock
from trading_bot.domain import (
    AccountId,
    AccountSnapshot,
    AssetClass,
    BrokerHealth,
    BrokerOrder,
    BrokerOrderId,
    BrokerOrderReview,
    CancelReceipt,
    ClientOrderId,
    DataHash,
    Fill,
    OrderId,
    OrderIntent,
    OrderState,
    PersistedReviewedOrder,
    Position,
)
from trading_bot.risk import canonical_review_payload_sha256


class FakeBroker:
    def __init__(
        self, account: AccountSnapshot, clock: Clock, *, positions: tuple[Position, ...] = ()
    ) -> None:
        self._account = account
        self._clock = clock
        self._positions = positions
        self._orders: dict[str, BrokerOrder] = {}
        self._by_key: dict[str, BrokerOrder] = {}
        self._fills: tuple[Fill, ...] = ()

    async def review_order(self, intent: OrderIntent) -> BrokerOrderReview:
        now = self._clock.now()
        price = intent.limit_price or intent.stop_price or Decimal("1")
        client_order_id = ClientOrderId(str(intent.id))
        return BrokerOrderReview(
            intent,
            "fake",
            now,
            min(intent.expires_at, now + timedelta(seconds=30)),
            intent.quantity * price,
            Decimal("0"),
            client_order_id,
            canonical_review_payload_sha256(intent, client_order_id=client_order_id),
            f"fake-review-{intent.id}",
        )

    async def place_order(self, submission: PersistedReviewedOrder) -> BrokerOrder:
        existing = self._by_key.get(submission.deduplication_key)
        if existing is not None:
            return existing
        intent = submission.review.normalized_order
        now = self._clock.now()
        broker_id = BrokerOrderId(f"fake-{len(self._orders) + 1}")
        order = BrokerOrder(
            OrderId(f"fake-local-{len(self._orders) + 1}"),
            broker_id,
            intent.account_id,
            intent.id,
            submission.review.client_order_id,
            intent.instrument_id,
            intent.side,
            intent.purpose,
            intent.order_type,
            intent.time_in_force,
            intent.quantity,
            Decimal("0"),
            intent.limit_price,
            intent.stop_price,
            OrderState.SUBMITTED,
            now,
            now,
            DataHash("f" * 64),
        )
        self._orders[broker_id] = order
        self._by_key[submission.deduplication_key] = order
        return order

    async def cancel_known_order(
        self, account_id: AccountId, order_id: BrokerOrderId
    ) -> CancelReceipt:
        order = self._orders.get(order_id)
        now = self._clock.now()
        if order is None or order.account_id != account_id:
            return CancelReceipt(order_id, False, False, now, "unknown_order")
        if order.state in {OrderState.FILLED, OrderState.CANCELED, OrderState.REJECTED}:
            return CancelReceipt(order_id, False, False, now, "terminal_order")
        canceled = replace(order, state=OrderState.CANCELED, updated_at=now)
        self._orders[order_id] = canceled
        for key, value in tuple(self._by_key.items()):
            if value.broker_order_id == order_id:
                self._by_key[key] = canceled
        return CancelReceipt(order_id, True, False, now, "canceled")

    async def get_accounts(self) -> tuple[AccountSnapshot, ...]:
        return (self._account,)

    async def get_account_state(self, account_id: AccountId) -> AccountSnapshot:
        if account_id != self._account.account_id:
            raise KeyError("unknown account")
        return self._account

    async def get_positions(self, account_id: AccountId) -> tuple[Position, ...]:
        await self.get_account_state(account_id)
        return self._positions

    async def get_open_orders(self, account_id: AccountId) -> tuple[BrokerOrder, ...]:
        await self.get_account_state(account_id)
        terminal = {OrderState.FILLED, OrderState.CANCELED, OrderState.REJECTED, OrderState.EXPIRED}
        return tuple(order for order in self._orders.values() if order.state not in terminal)

    async def get_recent_orders(
        self, account_id: AccountId, since: datetime
    ) -> tuple[BrokerOrder, ...]:
        await self.get_account_state(account_id)
        return tuple(order for order in self._orders.values() if order.updated_at >= since)

    async def get_fills(self, account_id: AccountId, since: datetime) -> tuple[Fill, ...]:
        await self.get_account_state(account_id)
        return tuple(fill for fill in self._fills if fill.occurred_at >= since)

    async def get_buying_power(self, account_id: AccountId, asset_class: AssetClass) -> Decimal:
        return (await self.get_account_state(account_id)).buying_power_for(asset_class)

    async def health_check(self) -> BrokerHealth:
        return BrokerHealth(True, self._clock.now(), Decimal("0"), ())


__all__ = ["FakeBroker"]
