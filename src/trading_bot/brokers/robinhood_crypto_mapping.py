"""Strict Crypto v2 DTO to broker-neutral domain mapping."""

import hashlib
from collections import Counter
from datetime import datetime
from decimal import Decimal

from trading_bot.brokers.robinhood_crypto_schemas import (
    BestBidAskDto,
    CryptoAccountDto,
    CryptoHoldingDto,
    CryptoOrderDto,
    EstimatedPriceDto,
    TradingPairDto,
)
from trading_bot.domain import (
    AccountId,
    AccountSnapshot,
    AssetBuyingPower,
    AssetClass,
    BrokerOrder,
    BrokerOrderId,
    ClientOrderId,
    DataHash,
    Fill,
    FillId,
    Instrument,
    InstrumentId,
    OrderId,
    OrderIntent,
    OrderPurpose,
    OrderState,
    OrderType,
    Position,
    Quote,
    Side,
    TimeInForce,
    TimestampSource,
)


class CryptoMappingError(RuntimeError):
    pass


class MaterialExecutionDrift(CryptoMappingError):
    pass


def _instrument(symbol: str) -> InstrumentId:
    if not symbol or "-" not in symbol:
        raise CryptoMappingError("unexpected Crypto symbol")
    return InstrumentId(symbol)


def map_account(
    dto: CryptoAccountDto, *, observed_at: datetime, data_hash: DataHash, reconciled_equity: Decimal
) -> AccountSnapshot:
    if dto.buying_power_currency != "USD":
        raise CryptoMappingError("unsupported Crypto buying-power currency")
    return AccountSnapshot(
        AccountId(dto.account_number),
        dto.status,
        reconciled_equity,
        dto.buying_power,
        (AssetBuyingPower(AssetClass.CRYPTO, dto.buying_power),),
        dto.status != "active",
        observed_at,
        data_hash,
    )


def map_holding(
    dto: CryptoHoldingDto, *, observed_at: datetime, data_hash: DataHash, mark_price: Decimal
) -> Position:
    if dto.total_quantity < dto.quantity_available_for_trading:
        raise CryptoMappingError("available quantity exceeds total holding")
    return Position(
        AccountId(dto.account_number),
        InstrumentId(f"{dto.asset_code}-USD"),
        AssetClass.CRYPTO,
        dto.total_quantity,
        dto.average_buy_price,
        dto.total_quantity * mark_price,
        observed_at,
        data_hash,
    )


def map_trading_pair(
    dto: TradingPairDto, *, observed_at: datetime, data_hash: DataHash
) -> Instrument:
    if dto.quote_code != "USD" or dto.symbol != f"{dto.asset_code}-{dto.quote_code}":
        raise CryptoMappingError("unsupported or inconsistent Crypto pair")
    return Instrument(
        _instrument(dto.symbol),
        dto.symbol,
        AssetClass.CRYPTO,
        dto.status,
        dto.is_api_tradable,
        True,
        dto.quote_increment,
        dto.asset_increment,
        dto.asset_increment,
        dto.min_order_amount,
        dto.max_order_size,
        f"crypto:{dto.asset_code}",
        observed_at,
        data_hash,
    )


def map_best_bid_ask(dto: BestBidAskDto, *, received_at: datetime, data_hash: DataHash) -> Quote:
    return Quote(
        _instrument(dto.symbol),
        received_at,
        dto.bid_inclusive_of_sell_spread,
        dto.ask_inclusive_of_buy_spread,
        None,
        "robinhood_crypto_v2",
        data_hash,
        False,
        TimestampSource.LOCAL_RECEIPT,
    )


def map_estimated_price(dto: EstimatedPriceDto, *, data_hash: DataHash) -> Quote:
    return Quote(
        _instrument(dto.symbol),
        dto.timestamp,
        dto.estimated_price,
        dto.estimated_price,
        dto.estimated_price,
        "robinhood_crypto_v2_estimated_price",
        data_hash,
        True,
        TimestampSource.PROVIDER,
    )


_ORDER_TYPES = {
    "market": OrderType.MARKET,
    "limit": OrderType.LIMIT,
    "stop_loss": OrderType.STOP_LOSS,
    "stop_limit": OrderType.STOP_LIMIT,
}
_ORDER_STATES = {
    "open": OrderState.SUBMITTED,
    "partially_filled": OrderState.PARTIALLY_FILLED,
    "filled": OrderState.FILLED,
    "canceled": OrderState.CANCELED,
    "cancelled": OrderState.CANCELED,
    "rejected": OrderState.REJECTED,
    "expired": OrderState.EXPIRED,
}
_TIF = {
    "gtc": TimeInForce.GOOD_TIL_CANCELED,
    "gfd": TimeInForce.GOOD_FOR_DAY,
    "ioc": TimeInForce.IMMEDIATE_OR_CANCEL,
}


def map_order(
    dto: CryptoOrderDto, *, data_hash: DataHash, known_intent: OrderIntent | None = None
) -> BrokerOrder:
    side = Side(dto.side)
    purpose = (
        known_intent.purpose
        if known_intent is not None
        else (OrderPurpose.ENTRY if side is Side.BUY else OrderPurpose.STRATEGY_EXIT)
    )
    intent_id = None if known_intent is None else known_intent.id
    return BrokerOrder(
        OrderId(f"broker:{dto.id}"),
        BrokerOrderId(dto.id),
        AccountId(dto.account_number),
        intent_id,
        None if dto.client_order_id is None else ClientOrderId(dto.client_order_id),
        _instrument(dto.symbol),
        side,
        purpose,
        _ORDER_TYPES[dto.type],
        _TIF[dto.time_in_force],
        dto.quantity,
        dto.filled_asset_quantity,
        dto.limit_price,
        dto.stop_price,
        _ORDER_STATES[dto.state],
        dto.created_at,
        dto.updated_at,
        data_hash,
    )


def execution_key(
    order: CryptoOrderDto, index: int
) -> tuple[str, datetime, str, Decimal, Decimal, int]:
    execution = order.executions[index]
    base = (
        order.id,
        execution.timestamp,
        order.side,
        execution.effective_price,
        execution.quantity,
    )
    ordinal = sum(
        1
        for prior in order.executions[:index]
        if (order.id, prior.timestamp, order.side, prior.effective_price, prior.quantity) == base
    )
    return (*base, ordinal)


def map_executions(
    order: CryptoOrderDto,
    *,
    data_hash: DataHash,
    persisted_multiplicity: Counter[tuple[str, datetime, str, Decimal, Decimal]] | None = None,
) -> tuple[Fill, ...]:
    base_keys = [
        (order.id, item.timestamp, order.side, item.effective_price, item.quantity)
        for item in order.executions
    ]
    observed = Counter(base_keys)
    persisted = persisted_multiplicity or Counter()
    if any(observed[key] < count for key, count in persisted.items()):
        raise MaterialExecutionDrift("execution multiplicity decreased")
    if (
        sum((item.quantity for item in order.executions), Decimal("0"))
        != order.filled_asset_quantity
    ):
        raise MaterialExecutionDrift("execution sum disagrees with cumulative filled quantity")
    fills = []
    for index, item in enumerate(order.executions):
        key = execution_key(order, index)
        base = key[:-1]
        if key[-1] < persisted[base]:
            continue
        digest = hashlib.sha256("|".join(map(str, key)).encode()).hexdigest()
        fills.append(
            Fill(
                FillId(digest),
                BrokerOrderId(order.id),
                AccountId(order.account_number),
                _instrument(order.symbol),
                Side(order.side),
                item.quantity,
                item.effective_price,
                Decimal("0"),
                item.timestamp,
                data_hash,
            )
        )
    return tuple(fills)


__all__ = [
    "CryptoMappingError",
    "MaterialExecutionDrift",
    "execution_key",
    "map_account",
    "map_best_bid_ask",
    "map_estimated_price",
    "map_executions",
    "map_holding",
    "map_order",
    "map_trading_pair",
]
