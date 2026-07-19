"""Strict DTO subset for documented official Robinhood Crypto v2 operations."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from trading_bot.clock import require_utc


class StrictProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("*", mode="before")
    @classmethod
    def reject_binary_floats(cls, value: object) -> object:
        if type(value) is float:
            raise ValueError("provider numerics cannot use binary floating point")
        return value


class CryptoAccountDto(StrictProviderModel):
    account_number: str
    status: str
    buying_power: Decimal
    buying_power_currency: str


class CryptoHoldingDto(StrictProviderModel):
    account_number: str
    asset_code: str
    total_quantity: Decimal
    quantity_available_for_trading: Decimal
    average_buy_price: Decimal | None


class TradingPairDto(StrictProviderModel):
    symbol: str
    asset_code: str
    quote_code: str
    asset_increment: Decimal
    quote_increment: Decimal
    max_order_size: Decimal
    min_order_amount: Decimal
    status: str
    is_api_tradable: bool


class BestBidAskDto(StrictProviderModel):
    symbol: str
    bid_inclusive_of_sell_spread: Decimal
    ask_inclusive_of_buy_spread: Decimal


class EstimatedPriceDto(StrictProviderModel):
    symbol: str
    side: str
    quantity: Decimal
    estimated_price: Decimal
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_utc(cls, value: datetime) -> datetime:
        return require_utc(value)


class CryptoExecutionDto(StrictProviderModel):
    effective_price: Decimal
    quantity: Decimal
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_utc(cls, value: datetime) -> datetime:
        return require_utc(value)


class CryptoOrderDto(StrictProviderModel):
    id: str
    account_number: str
    client_order_id: str | None
    symbol: str
    side: str
    type: str
    state: str
    time_in_force: str
    quantity: Decimal
    filled_asset_quantity: Decimal
    average_price: Decimal | None
    limit_price: Decimal | None
    stop_price: Decimal | None
    created_at: datetime
    updated_at: datetime
    executions: tuple[CryptoExecutionDto, ...]

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        return require_utc(value)


class ResultsResponse[T](StrictProviderModel):
    next: str | None
    previous: str | None
    results: tuple[T, ...]


CryptoAccountsResponse = ResultsResponse[CryptoAccountDto]
CryptoHoldingsResponse = ResultsResponse[CryptoHoldingDto]
TradingPairsResponse = ResultsResponse[TradingPairDto]
BestBidAskResponse = ResultsResponse[BestBidAskDto]
EstimatedPriceResponse = ResultsResponse[EstimatedPriceDto]
CryptoOrdersResponse = ResultsResponse[CryptoOrderDto]


__all__ = [
    "BestBidAskDto",
    "BestBidAskResponse",
    "CryptoAccountDto",
    "CryptoAccountsResponse",
    "CryptoExecutionDto",
    "CryptoHoldingDto",
    "CryptoHoldingsResponse",
    "CryptoOrderDto",
    "CryptoOrdersResponse",
    "EstimatedPriceDto",
    "EstimatedPriceResponse",
    "StrictProviderModel",
    "TradingPairDto",
    "TradingPairsResponse",
]
