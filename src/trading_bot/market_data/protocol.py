"""Broker-neutral market-data capability contracts."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from trading_bot.domain import (
    AssetClass,
    Bar,
    BarInterval,
    CorporateAction,
    EarningsEvent,
    Instrument,
    InstrumentId,
    MarketClock,
    Quote,
    SpreadEstimate,
)


class MarketDataCapability(StrEnum):
    INFORMATIONAL_QUOTE = "informational_quote"
    EXECUTABLE_QUOTE = "executable_quote"
    BARS = "bars"
    MARKET_CLOCK = "market_clock"
    CORPORATE_ACTIONS = "corporate_actions"
    EARNINGS_CALENDAR = "earnings_calendar"
    INSTRUMENT_METADATA = "instrument_metadata"
    SPREAD_ESTIMATE = "spread_estimate"


class MarketDataCapabilityError(RuntimeError):
    pass


class MarketDataProvider(Protocol):
    async def get_quote(self, instrument_id: InstrumentId) -> Quote: ...
    async def get_executable_quote(
        self, instrument_id: InstrumentId, quantity: Decimal
    ) -> Quote: ...
    async def get_bars(
        self,
        instrument_id: InstrumentId,
        interval: BarInterval,
        start: datetime,
        end: datetime,
    ) -> tuple[Bar, ...]: ...
    async def get_market_clock(self, asset_class: AssetClass) -> MarketClock: ...
    async def get_corporate_actions(
        self, instrument_id: InstrumentId, start: date, end: date
    ) -> tuple[CorporateAction, ...]: ...
    async def get_earnings_calendar(
        self, instrument_ids: tuple[InstrumentId, ...], start: date, end: date
    ) -> tuple[EarningsEvent, ...]: ...
    async def get_instrument_metadata(self, instrument_id: InstrumentId) -> Instrument: ...
    async def get_spread_estimate(self, instrument_id: InstrumentId) -> SpreadEstimate: ...


__all__ = ["MarketDataCapability", "MarketDataCapabilityError", "MarketDataProvider"]
