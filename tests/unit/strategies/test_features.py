from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading_bot.domain import Bar, BarInterval, DataHash, InstrumentId
from trading_bot.strategies import FeaturePipeline, HistoricalSlice, LookaheadViolation

NOW = datetime(2026, 7, 17, tzinfo=UTC)
ID = InstrumentId("AAPL")


def bars(count: int) -> tuple[Bar, ...]:
    values = []
    for index in range(count):
        end = NOW - timedelta(days=count - index)
        close = Decimal(100 + index)
        values.append(
            Bar(
                ID,
                BarInterval.ONE_DAY,
                end - timedelta(days=1),
                end,
                close,
                close + 1,
                close - 1,
                close,
                Decimal("1000"),
                "fixture",
                DataHash(f"{index + 1:064x}"),
            )
        )
    return tuple(values)


def history(count: int = 5) -> HistoricalSlice:
    records = bars(count)
    return HistoricalSlice(ID, records, Decimal("0.1"), DataHash("a" * 64))


def test_incomplete_bar_cannot_change_features() -> None:
    incomplete = replace(bars(1)[0], starts_at=NOW, ends_at=NOW + timedelta(days=1))
    with pytest.raises(LookaheadViolation):
        FeaturePipeline(short_window=2, long_window=3).compute(
            replace(history(), bars=(*history().bars, incomplete)), as_of=NOW
        )


def test_features_are_canonical_and_unavailable_is_not_zero() -> None:
    result = FeaturePipeline(short_window=3, long_window=10).compute(history(), as_of=NOW)
    values = dict(result.values)
    assert values["latest_close"] == Decimal("104")
    assert values["moving_average_short"] == Decimal("103")
    assert values["moving_average_long"] is None
    assert tuple(values) == tuple(sorted(values, key=lambda name: list(values).index(name)))


def test_identical_inputs_produce_identical_feature_hash() -> None:
    pipeline = FeaturePipeline(short_window=2, long_window=3)
    assert pipeline.compute(history(), as_of=NOW) == pipeline.compute(history(), as_of=NOW)
