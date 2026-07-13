"""Immutable broker-neutral market-data records."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import (
    DomainValidationError,
    _require_decimal,
    _require_exact_bool,
    _require_exact_enum,
    _require_nonempty,
    _require_sha256_hex,
)
from trading_bot.domain.enums import AssetClass, BarInterval, TimestampSource
from trading_bot.domain.identifiers import DataHash, InstrumentId


@dataclass(frozen=True, slots=True)
class Quote:
    instrument_id: InstrumentId
    observed_at: datetime
    bid: Decimal
    ask: Decimal
    last: Decimal | None
    source: str
    data_hash: DataHash
    freshness_verified: bool
    timestamp_source: TimestampSource

    def __post_init__(self) -> None:
        _require_nonempty(self.instrument_id, "instrument_id")
        require_utc(self.observed_at)
        _require_decimal(self.bid, "bid", positive=True)
        _require_decimal(self.ask, "ask", positive=True)
        if self.last is not None:
            _require_decimal(self.last, "last", positive=True)
        if self.bid > self.ask:
            raise DomainValidationError("bid cannot exceed ask")
        _require_nonempty(self.source, "source")
        _require_sha256_hex(self.data_hash, "data_hash")
        _require_exact_bool(self.freshness_verified, "freshness_verified")
        _require_exact_enum(self.timestamp_source, TimestampSource, "timestamp_source")


@dataclass(frozen=True, slots=True)
class SpreadEstimate:
    instrument_id: InstrumentId
    observed_at: datetime
    absolute: Decimal
    percentage: Decimal
    data_hash: DataHash

    def __post_init__(self) -> None:
        _require_nonempty(self.instrument_id, "instrument_id")
        require_utc(self.observed_at)
        _require_decimal(self.absolute, "absolute", nonnegative=True)
        _require_decimal(self.percentage, "percentage", nonnegative=True)
        _require_sha256_hex(self.data_hash, "data_hash")


@dataclass(frozen=True, slots=True)
class Bar:
    instrument_id: InstrumentId
    interval: BarInterval
    starts_at: datetime
    ends_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    source: str
    data_hash: DataHash
    interpolated: bool = False

    def __post_init__(self) -> None:
        _require_nonempty(self.instrument_id, "instrument_id")
        _require_exact_enum(self.interval, BarInterval, "interval")
        require_utc(self.starts_at)
        require_utc(self.ends_at)
        if self.starts_at >= self.ends_at:
            raise DomainValidationError("bar starts_at must precede ends_at")
        _require_decimal(self.open, "open", positive=True)
        _require_decimal(self.high, "high", positive=True)
        _require_decimal(self.low, "low", positive=True)
        _require_decimal(self.close, "close", positive=True)
        _require_decimal(self.volume, "volume", nonnegative=True)
        prices = (self.open, self.high, self.low, self.close)
        if self.low != min(prices) or self.high != max(prices):
            raise DomainValidationError("bar low and high must bound all OHLC prices")
        _require_nonempty(self.source, "source")
        _require_sha256_hex(self.data_hash, "data_hash")
        _require_exact_bool(self.interpolated, "interpolated")


@dataclass(frozen=True, slots=True)
class Instrument:
    id: InstrumentId
    symbol: str
    asset_class: AssetClass
    provider_status: str
    tradable: bool
    fractional_eligible: bool
    price_increment: Decimal
    quantity_increment: Decimal
    minimum_quantity: Decimal
    minimum_notional: Decimal
    maximum_quantity: Decimal | None
    correlation_group: str
    observed_at: datetime
    data_hash: DataHash

    def __post_init__(self) -> None:
        _require_nonempty(self.id, "id")
        _require_nonempty(self.symbol, "symbol")
        _require_exact_enum(self.asset_class, AssetClass, "asset_class")
        _require_nonempty(self.provider_status, "provider_status")
        _require_exact_bool(self.tradable, "tradable")
        _require_exact_bool(self.fractional_eligible, "fractional_eligible")
        _require_decimal(self.price_increment, "price_increment", positive=True)
        _require_decimal(self.quantity_increment, "quantity_increment", positive=True)
        _require_decimal(self.minimum_quantity, "minimum_quantity", positive=True)
        _require_decimal(self.minimum_notional, "minimum_notional", positive=True)
        if self.maximum_quantity is not None:
            _require_decimal(self.maximum_quantity, "maximum_quantity", positive=True)
            if self.maximum_quantity < self.minimum_quantity:
                raise DomainValidationError("maximum_quantity cannot be less than minimum_quantity")
        _require_nonempty(self.correlation_group, "correlation_group")
        require_utc(self.observed_at)
        _require_sha256_hex(self.data_hash, "data_hash")


@dataclass(frozen=True, slots=True)
class MarketClock:
    asset_class: AssetClass
    venue: str
    observed_at: datetime
    is_open: bool
    halted: bool
    trading_disabled: bool
    cancel_only: bool
    next_open_at: datetime | None
    next_close_at: datetime | None

    def __post_init__(self) -> None:
        _require_exact_enum(self.asset_class, AssetClass, "asset_class")
        _require_nonempty(self.venue, "venue")
        require_utc(self.observed_at)
        _require_exact_bool(self.is_open, "is_open")
        _require_exact_bool(self.halted, "halted")
        _require_exact_bool(self.trading_disabled, "trading_disabled")
        _require_exact_bool(self.cancel_only, "cancel_only")
        if self.next_open_at is not None:
            require_utc(self.next_open_at)
        if self.next_close_at is not None:
            require_utc(self.next_close_at)
