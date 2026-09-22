"""Fail-closed market-data validation and durable quarantine gateway."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from trading_bot.clock import Clock, require_utc
from trading_bot.domain import (
    AssetClass,
    Bar,
    BarInterval,
    CorporateAction,
    DataHash,
    EarningsEvent,
    Instrument,
    InstrumentId,
    MarketClock,
    Quote,
    SpreadEstimate,
    TimestampSource,
    require_bounded_decimal,
)
from trading_bot.market_data.protocol import MarketDataProvider

_MICROSECONDS = Decimal("1000000")


@dataclass(frozen=True, slots=True)
class DataQualityEvent:
    id: str
    instrument_id: InstrumentId | None
    occurred_at: datetime
    code: str
    severity: str
    reason: str
    data_hash: DataHash | None
    details: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ValidationResult[T]:
    value: T | None
    events: tuple[DataQualityEvent, ...]


@dataclass(frozen=True, slots=True)
class MarketDataValidationPolicy:
    maximum_quote_age_seconds: Decimal
    maximum_anomaly_change_pct: Decimal
    interpolated_bars_allowed: bool = False

    def __post_init__(self) -> None:
        require_bounded_decimal(
            self.maximum_quote_age_seconds, "maximum_quote_age_seconds", positive=True
        )
        require_bounded_decimal(
            self.maximum_anomaly_change_pct,
            "maximum_anomaly_change_pct",
            nonnegative=True,
        )


class DataQualitySink(Protocol):
    async def append_all(self, events: tuple[DataQualityEvent, ...]) -> None: ...


class RejectedMarketData(RuntimeError):
    def __init__(self, events: tuple[DataQualityEvent, ...]) -> None:
        self.events = events
        super().__init__("market data rejected after durable quarantine")


def _elapsed_seconds(start: datetime, end: datetime) -> Decimal:
    delta = end - start
    microseconds = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
    return Decimal(microseconds) / _MICROSECONDS


class MarketDataValidator:
    def __init__(self, policy: MarketDataValidationPolicy) -> None:
        self._policy = policy

    @staticmethod
    def _event(
        code: str,
        now: datetime,
        instrument_id: InstrumentId | None,
        data_hash: DataHash | None,
    ) -> DataQualityEvent:
        return DataQualityEvent(
            str(uuid.uuid4()), instrument_id, now, code, "error", code, data_hash
        )

    def validate_quote(
        self,
        quote: Quote,
        *,
        expected_instrument: InstrumentId,
        now: datetime,
        previous: Quote | None,
        executable: bool = False,
    ) -> ValidationResult[Quote]:
        now = require_utc(now)
        events: list[DataQualityEvent] = []
        if quote.instrument_id != expected_instrument:
            events.append(
                self._event("instrument_mismatch", now, expected_instrument, quote.data_hash)
            )
        if quote.bid <= 0 or quote.ask <= 0 or (quote.last is not None and quote.last <= 0):
            events.append(
                self._event("nonpositive_price", now, quote.instrument_id, quote.data_hash)
            )
        if quote.bid > quote.ask:
            events.append(self._event("crossed_quote", now, quote.instrument_id, quote.data_hash))
        age = _elapsed_seconds(quote.observed_at, now)
        if age < 0 or age > self._policy.maximum_quote_age_seconds:
            events.append(self._event("stale_quote", now, quote.instrument_id, quote.data_hash))
        if quote.freshness_verified and quote.timestamp_source is not TimestampSource.PROVIDER:
            events.append(
                self._event("untrusted_timestamp", now, quote.instrument_id, quote.data_hash)
            )
        if executable and (
            not quote.freshness_verified or quote.timestamp_source is not TimestampSource.PROVIDER
        ):
            events.append(
                self._event("nonexecutable_quote", now, quote.instrument_id, quote.data_hash)
            )
        if previous is not None and previous.last is not None and quote.last is not None:
            change = abs(quote.last - previous.last) * Decimal("100") / previous.last
            if change > self._policy.maximum_anomaly_change_pct:
                events.append(
                    self._event(
                        "unconfirmed_price_anomaly", now, quote.instrument_id, quote.data_hash
                    )
                )
        return ValidationResult(None if events else quote, tuple(events))

    def validate_bar(
        self,
        bar: Bar,
        *,
        expected_instrument: InstrumentId,
        expected_interval: BarInterval,
        now: datetime,
    ) -> ValidationResult[Bar]:
        now = require_utc(now)
        events: list[DataQualityEvent] = []
        if bar.instrument_id != expected_instrument:
            events.append(
                self._event("instrument_mismatch", now, expected_instrument, bar.data_hash)
            )
        if bar.interval is not expected_interval:
            events.append(self._event("interval_mismatch", now, bar.instrument_id, bar.data_hash))
        if bar.ends_at > now:
            events.append(self._event("future_bar", now, bar.instrument_id, bar.data_hash))
        if bar.interpolated and not self._policy.interpolated_bars_allowed:
            events.append(self._event("interpolated_bar", now, bar.instrument_id, bar.data_hash))
        return ValidationResult(None if events else bar, tuple(events))

    def validate_clock(
        self, clock: MarketClock, *, expected_asset_class: AssetClass, now: datetime
    ) -> ValidationResult[MarketClock]:
        now = require_utc(now)
        invalid = clock.asset_class is not expected_asset_class or (
            clock.is_open and (clock.halted or clock.trading_disabled or clock.cancel_only)
        )
        events = (self._event("market_clock_conflict", now, None, None),) if invalid else ()
        return ValidationResult(None if events else clock, events)


class ValidatingMarketDataProvider:
    def __init__(
        self,
        inner: MarketDataProvider,
        validator: MarketDataValidator,
        quality_events: DataQualitySink,
        clock: Clock,
    ) -> None:
        self._inner = inner
        self._validator = validator
        self._quality_events = quality_events
        self._clock = clock
        self._last: dict[InstrumentId, Quote] = {}

    async def _validated_quote(
        self, instrument_id: InstrumentId, quote: Quote, *, executable: bool
    ) -> Quote:
        result = self._validator.validate_quote(
            quote,
            expected_instrument=instrument_id,
            now=self._clock.now(),
            previous=self._last.get(instrument_id),
            executable=executable,
        )
        await self._quality_events.append_all(result.events)
        if result.value is None:
            raise RejectedMarketData(result.events)
        self._last[instrument_id] = result.value
        return result.value

    async def get_quote(self, instrument_id: InstrumentId) -> Quote:
        return await self._validated_quote(
            instrument_id, await self._inner.get_quote(instrument_id), executable=False
        )

    async def get_executable_quote(self, instrument_id: InstrumentId, quantity: Decimal) -> Quote:
        require_bounded_decimal(quantity, "quantity", positive=True)
        return await self._validated_quote(
            instrument_id,
            await self._inner.get_executable_quote(instrument_id, quantity),
            executable=True,
        )

    async def get_bars(
        self,
        instrument_id: InstrumentId,
        interval: BarInterval,
        start: datetime,
        end: datetime,
    ) -> tuple[Bar, ...]:
        bars = await self._inner.get_bars(instrument_id, interval, start, end)
        values: list[Bar] = []
        events: list[DataQualityEvent] = []
        for bar in bars:
            result = self._validator.validate_bar(
                bar,
                expected_instrument=instrument_id,
                expected_interval=interval,
                now=self._clock.now(),
            )
            events.extend(result.events)
            if result.value is not None:
                values.append(result.value)
        await self._quality_events.append_all(tuple(events))
        if events:
            raise RejectedMarketData(tuple(events))
        return tuple(values)

    async def get_market_clock(self, asset_class: AssetClass) -> MarketClock:
        result = self._validator.validate_clock(
            await self._inner.get_market_clock(asset_class),
            expected_asset_class=asset_class,
            now=self._clock.now(),
        )
        await self._quality_events.append_all(result.events)
        if result.value is None:
            raise RejectedMarketData(result.events)
        return result.value

    async def get_corporate_actions(
        self, instrument_id: InstrumentId, start: date, end: date
    ) -> tuple[CorporateAction, ...]:
        return await self._inner.get_corporate_actions(instrument_id, start, end)

    async def get_earnings_calendar(
        self, instrument_ids: tuple[InstrumentId, ...], start: date, end: date
    ) -> tuple[EarningsEvent, ...]:
        return await self._inner.get_earnings_calendar(instrument_ids, start, end)

    async def get_instrument_metadata(self, instrument_id: InstrumentId) -> Instrument:
        return await self._inner.get_instrument_metadata(instrument_id)

    async def get_spread_estimate(self, instrument_id: InstrumentId) -> SpreadEstimate:
        return await self._inner.get_spread_estimate(instrument_id)


__all__ = [
    "DataQualityEvent",
    "MarketDataValidationPolicy",
    "MarketDataValidator",
    "RejectedMarketData",
    "ValidatingMarketDataProvider",
    "ValidationResult",
]
