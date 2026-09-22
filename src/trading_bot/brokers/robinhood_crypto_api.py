"""Read-only official Robinhood Crypto v2 broker adapter."""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Protocol, TypeVar
from uuid import UUID

import httpx
from pydantic import BaseModel

from trading_bot.brokers.errors import BrokerCancellationAmbiguous
from trading_bot.brokers.robinhood_crypto_mapping import (
    map_account,
    map_executions,
    map_holding,
    map_order,
)
from trading_bot.brokers.robinhood_crypto_schemas import (
    CryptoAccountsResponse,
    CryptoHoldingsResponse,
    CryptoOrderDto,
    CryptoOrdersResponse,
)
from trading_bot.brokers.robinhood_crypto_transport import RetryClass
from trading_bot.clock import Clock
from trading_bot.domain import (
    AccountId,
    AccountSnapshot,
    AssetClass,
    BrokerHealth,
    BrokerOrder,
    BrokerOrderId,
    CancelReceipt,
    ClientOrderId,
    Fill,
    OrderType,
    PersistedReviewedOrder,
    Position,
    TimeInForce,
)
from trading_bot.market_data import content_hash


class CryptoRequester(Protocol):
    async def request(
        self,
        method: str,
        path: str,
        *,
        query: tuple[tuple[str, str], ...] = (),
        json_body: dict[str, object] | None = None,
        retry_class: RetryClass,
    ) -> httpx.Response: ...


ResponseT = TypeVar("ResponseT", bound=BaseModel)


class RobinhoodCryptoReadAdapter:
    def __init__(
        self,
        transport: CryptoRequester,
        clock: Clock,
        *,
        reconciled_equity: Mapping[AccountId, Decimal],
        mark_prices: Mapping[str, Decimal],
        maximum_pages: int = 10,
    ) -> None:
        self._transport = transport
        self._clock = clock
        self._equity = reconciled_equity
        self._marks = mark_prices
        self._maximum_pages = maximum_pages

    async def _response(
        self, path: str, model: type[ResponseT], *, query: tuple[tuple[str, str], ...] = ()
    ) -> ResponseT:
        response = await self._transport.request(
            "GET", path, query=query, retry_class=RetryClass.READ_SAFE
        )
        response.raise_for_status()
        return model.model_validate_json(response.content)

    async def get_accounts(self) -> tuple[AccountSnapshot, ...]:
        response = await self._response("/api/v2/crypto/trading/accounts/", CryptoAccountsResponse)
        now = self._clock.now()
        digest = content_hash(response.model_dump(mode="json"))
        return tuple(
            map_account(
                item,
                observed_at=now,
                data_hash=digest,
                reconciled_equity=self._equity[AccountId(item.account_number)],
            )
            for item in response.results
        )

    async def get_account_state(self, account_id: AccountId) -> AccountSnapshot:
        matches = tuple(item for item in await self.get_accounts() if item.account_id == account_id)
        if len(matches) != 1:
            raise KeyError("Crypto account identity is not unique")
        return matches[0]

    async def get_positions(self, account_id: AccountId) -> tuple[Position, ...]:
        response = await self._response(
            "/api/v2/crypto/trading/holdings/",
            CryptoHoldingsResponse,
            query=(("account_number", account_id),),
        )
        now = self._clock.now()
        digest = content_hash(response.model_dump(mode="json"))
        return tuple(
            map_holding(
                item,
                observed_at=now,
                data_hash=digest,
                mark_price=self._marks[f"{item.asset_code}-USD"],
            )
            for item in response.results
            if item.account_number == account_id
        )

    async def _orders(self, account_id: AccountId) -> tuple[BrokerOrder, ...]:
        response = await self._response(
            "/api/v2/crypto/trading/orders/",
            CryptoOrdersResponse,
            query=(("account_number", account_id),),
        )
        digest = content_hash(response.model_dump(mode="json"))
        return tuple(
            map_order(item, data_hash=digest)
            for item in response.results
            if item.account_number == account_id
        )

    async def get_open_orders(self, account_id: AccountId) -> tuple[BrokerOrder, ...]:
        terminal = {"filled", "canceled", "rejected", "expired"}
        return tuple(
            item for item in await self._orders(account_id) if item.state.value not in terminal
        )

    async def get_recent_orders(
        self, account_id: AccountId, since: datetime
    ) -> tuple[BrokerOrder, ...]:
        return tuple(item for item in await self._orders(account_id) if item.updated_at >= since)

    async def get_fills(self, account_id: AccountId, since: datetime) -> tuple[Fill, ...]:
        response = await self._response(
            "/api/v2/crypto/trading/orders/",
            CryptoOrdersResponse,
            query=(("account_number", account_id),),
        )
        digest = content_hash(response.model_dump(mode="json"))
        return tuple(
            fill
            for order in response.results
            if order.account_number == account_id
            for fill in map_executions(order, data_hash=digest)
            if fill.occurred_at >= since
        )

    async def get_buying_power(self, account_id: AccountId, asset_class: AssetClass) -> Decimal:
        if asset_class is not AssetClass.CRYPTO:
            raise ValueError("Crypto adapter supplies only Crypto buying power")
        return (await self.get_account_state(account_id)).buying_power_for(asset_class)

    async def health_check(self) -> BrokerHealth:
        try:
            await self.get_accounts()
        except (httpx.HTTPError, ValueError, KeyError):
            return BrokerHealth(False, self._clock.now(), None, ("crypto_read_unhealthy",))
        return BrokerHealth(True, self._clock.now(), None, ())

    async def find_order(
        self, account_id: AccountId, client_order_id: ClientOrderId, created_after: datetime
    ) -> BrokerOrder | None:
        matches = tuple(
            order
            for order in await self._orders(account_id)
            if order.client_order_id == client_order_id and order.created_at >= created_after
        )
        if len(matches) > 1:
            raise RuntimeError("client order id is not unique")
        return matches[0] if matches else None


class RobinhoodCryptoPlaceAdapter:
    """One-attempt Crypto placement accepting only live persisted reviews."""

    def __init__(self, transport: CryptoRequester, clock: Clock) -> None:
        self._transport = transport
        self._clock = clock

    async def place_order(self, submission: PersistedReviewedOrder) -> BrokerOrder:
        intent = submission.review.normalized_order
        if submission.fencing_token <= 0 or submission.live_lease_id is None:
            raise PermissionError("Crypto placement requires a fenced live lease")
        if intent.order_type is OrderType.MARKET:
            raise ValueError("market-order placement is not implemented")
        client_order_id = submission.review.client_order_id
        if client_order_id is None or UUID(str(client_order_id)).version != 4:
            raise ValueError("Crypto placement requires the persisted UUID client order ID")
        tif = {
            TimeInForce.GOOD_FOR_DAY: "gfd",
            TimeInForce.GOOD_TIL_CANCELED: "gtc",
            TimeInForce.IMMEDIATE_OR_CANCEL: "ioc",
        }[intent.time_in_force]
        configuration: dict[str, object] = {
            "asset_quantity": intent.quantity,
            "time_in_force": tif,
        }
        if intent.limit_price is not None:
            configuration["limit_price"] = intent.limit_price
        if intent.stop_price is not None:
            configuration["stop_price"] = intent.stop_price
        response = await self._transport.request(
            "POST",
            "/api/v2/crypto/trading/orders/",
            json_body={
                "account_number": str(intent.account_id),
                "client_order_id": str(client_order_id),
                "symbol": str(intent.instrument_id).upper(),
                "side": intent.side.value,
                "type": intent.order_type.value,
                intent.order_type.value: configuration,
            },
            retry_class=RetryClass.WRITE_NEVER,
        )
        response.raise_for_status()
        dto = CryptoOrderDto.model_validate_json(response.content)
        return map_order(
            dto,
            data_hash=content_hash(dto.model_dump(mode="json")),
            known_intent=intent,
        )


class RobinhoodCryptoCancelAdapter:
    """One-attempt cancellation for a positively identified Crypto order."""

    def __init__(self, transport: CryptoRequester, clock: Clock) -> None:
        self._transport = transport
        self._clock = clock

    async def cancel_known_order(
        self, account_id: AccountId, order_id: BrokerOrderId
    ) -> CancelReceipt:
        try:
            response = await self._transport.request(
                "POST",
                f"/api/v2/crypto/trading/orders/{order_id}/cancel/",
                query=(("account_number", str(account_id)),),
                retry_class=RetryClass.WRITE_NEVER,
            )
        except Exception:
            raise BrokerCancellationAmbiguous() from None
        if response.status_code // 100 != 2:
            raise BrokerCancellationAmbiguous()
        return CancelReceipt(order_id, True, False, self._clock.now(), "cancel_accepted")


__all__ = [
    "CryptoRequester",
    "RobinhoodCryptoCancelAdapter",
    "RobinhoodCryptoPlaceAdapter",
    "RobinhoodCryptoReadAdapter",
]
