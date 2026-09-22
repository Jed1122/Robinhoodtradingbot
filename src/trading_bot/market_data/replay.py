"""Recorded provider that never exposes observations from the simulated future."""

from datetime import date, datetime
from decimal import Decimal

from trading_bot.clock import Clock
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
from trading_bot.market_data.protocol import MarketDataCapabilityError


def _latest[T](values: tuple[T, ...], *, observed: str, now: datetime) -> T:
    available = tuple(item for item in values if getattr(item, observed) <= now)
    if not available:
        raise MarketDataCapabilityError("recorded observation is unavailable at simulated time")
    return max(available, key=lambda item: getattr(item, observed))


class RecordedMarketDataProvider:
    def __init__(
        self,
        clock: Clock,
        *,
        quotes: tuple[Quote, ...] = (),
        bars: tuple[Bar, ...] = (),
        market_clocks: tuple[MarketClock, ...] = (),
        corporate_actions: tuple[CorporateAction, ...] = (),
        earnings: tuple[EarningsEvent, ...] = (),
        instruments: tuple[Instrument, ...] = (),
        spreads: tuple[SpreadEstimate, ...] = (),
    ) -> None:
        self.clock = clock
        self._quotes = quotes
        self._bars = bars
        self._market_clocks = market_clocks
        self._corporate_actions = corporate_actions
        self._earnings = earnings
        self._instruments = instruments
        self._spreads = spreads

    async def get_quote(self, instrument_id: InstrumentId) -> Quote:
        return _latest(
            tuple(item for item in self._quotes if item.instrument_id == instrument_id),
            observed="observed_at",
            now=self.clock.now(),
        )

    async def get_executable_quote(self, instrument_id: InstrumentId, quantity: Decimal) -> Quote:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        return await self.get_quote(instrument_id)

    async def get_bars(
        self,
        instrument_id: InstrumentId,
        interval: BarInterval,
        start: datetime,
        end: datetime,
    ) -> tuple[Bar, ...]:
        visible_end = min(end, self.clock.now())
        return tuple(
            sorted(
                (
                    item
                    for item in self._bars
                    if item.instrument_id == instrument_id
                    and item.interval is interval
                    and item.starts_at >= start
                    and item.ends_at <= visible_end
                ),
                key=lambda item: item.ends_at,
            )
        )

    async def get_market_clock(self, asset_class: AssetClass) -> MarketClock:
        return _latest(
            tuple(item for item in self._market_clocks if item.asset_class is asset_class),
            observed="observed_at",
            now=self.clock.now(),
        )

    async def get_corporate_actions(
        self, instrument_id: InstrumentId, start: date, end: date
    ) -> tuple[CorporateAction, ...]:
        now = self.clock.now()
        return tuple(
            item
            for item in self._corporate_actions
            if item.instrument_id == instrument_id
            and start <= item.effective_date <= end
            and item.announced_at <= now
        )

    async def get_earnings_calendar(
        self, instrument_ids: tuple[InstrumentId, ...], start: date, end: date
    ) -> tuple[EarningsEvent, ...]:
        now = self.clock.now()
        return tuple(
            item
            for item in self._earnings
            if item.instrument_id in instrument_ids
            and start <= item.earnings_date <= end
            and item.announced_at <= now
        )

    async def get_instrument_metadata(self, instrument_id: InstrumentId) -> Instrument:
        return _latest(
            tuple(item for item in self._instruments if item.id == instrument_id),
            observed="observed_at",
            now=self.clock.now(),
        )

    async def get_spread_estimate(self, instrument_id: InstrumentId) -> SpreadEstimate:
        return _latest(
            tuple(item for item in self._spreads if item.instrument_id == instrument_id),
            observed="observed_at",
            now=self.clock.now(),
        )


__all__ = ["RecordedMarketDataProvider"]
