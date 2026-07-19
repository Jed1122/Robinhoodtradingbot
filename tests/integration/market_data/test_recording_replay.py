from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading_bot.domain import Bar, BarInterval, DataHash, InstrumentId
from trading_bot.market_data import RecordedMarketDataProvider

NOW = datetime(2026, 7, 17, tzinfo=UTC)
ID = InstrumentId("AAPL")


@dataclass
class Clock:
    current: datetime

    def now(self) -> datetime:
        return self.current


def make_bar(day_offset: int) -> Bar:
    end = NOW + timedelta(days=day_offset)
    return Bar(
        ID,
        BarInterval.ONE_DAY,
        end - timedelta(days=1),
        end,
        Decimal("10"),
        Decimal("11"),
        Decimal("9"),
        Decimal("10"),
        Decimal("100"),
        "recorded",
        DataHash(str(day_offset + 5) * 64),
    )


@pytest.mark.asyncio
async def test_recorded_provider_hides_future_bars() -> None:
    clock = Clock(NOW)
    provider = RecordedMarketDataProvider(clock, bars=(make_bar(-1), make_bar(1)))
    bars = await provider.get_bars(
        ID, BarInterval.ONE_DAY, NOW - timedelta(days=5), NOW + timedelta(days=5)
    )
    assert bars == (make_bar(-1),)
    clock.current = NOW + timedelta(days=2)
    assert (
        len(
            await provider.get_bars(
                ID, BarInterval.ONE_DAY, NOW - timedelta(days=5), NOW + timedelta(days=5)
            )
        )
        == 2
    )
