from datetime import UTC, datetime, timedelta
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from trading_bot.domain import Bar, BarInterval, DataHash, InstrumentId
from trading_bot.strategies import FeaturePipeline, HistoricalSlice


@given(st.lists(st.integers(min_value=1, max_value=10000), min_size=3, max_size=20))
def test_feature_hash_is_deterministic(prices: list[int]) -> None:
    now = datetime(2026, 7, 17, tzinfo=UTC)
    bars = tuple(
        Bar(
            InstrumentId("TEST"),
            BarInterval.ONE_DAY,
            now - timedelta(days=len(prices) - index + 1),
            now - timedelta(days=len(prices) - index),
            Decimal(price),
            Decimal(price + 1),
            Decimal(max(price - 1, 1)),
            Decimal(price),
            Decimal("1"),
            "fixture",
            DataHash(f"{index + 1:064x}"),
        )
        for index, price in enumerate(prices)
    )
    history = HistoricalSlice(InstrumentId("TEST"), bars, None, DataHash("a" * 64))
    pipeline = FeaturePipeline(short_window=2, long_window=3)
    assert (
        pipeline.compute(history, as_of=now).data_hash
        == pipeline.compute(history, as_of=now).data_hash
    )
