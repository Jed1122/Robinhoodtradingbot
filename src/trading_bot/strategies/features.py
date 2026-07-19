"""Deterministic Decimal features computed only from completed bars."""

from datetime import datetime
from decimal import Decimal, localcontext

from trading_bot.clock import require_utc
from trading_bot.market_data.recording import content_hash
from trading_bot.strategies.protocol import FeatureVector, HistoricalSlice


class LookaheadViolation(RuntimeError):
    pass


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    return None if not values else sum(values, Decimal("0")) / Decimal(len(values))


class FeaturePipeline:
    def __init__(self, *, short_window: int = 20, long_window: int = 100) -> None:
        if short_window < 2 or long_window <= short_window:
            raise ValueError("feature windows must satisfy 2 <= short < long")
        self._short = short_window
        self._long = long_window

    def compute(self, history: HistoricalSlice, *, as_of: datetime) -> FeatureVector:
        as_of = require_utc(as_of)
        bars = history.bars
        if any(bar.ends_at > as_of for bar in bars):
            raise LookaheadViolation("incomplete or future bar cannot enter features")
        if any(bar.instrument_id != history.instrument_id for bar in bars):
            raise ValueError("historical slice contains another instrument")
        if tuple(bar.ends_at for bar in bars) != tuple(sorted({bar.ends_at for bar in bars})):
            raise ValueError("bars must be strictly ordered without duplicate end times")
        closes = tuple(bar.close for bar in bars)
        values: list[tuple[str, Decimal | int | bool | str | None]] = []
        total_return = None
        if len(closes) >= 2:
            total_return = (closes[-1] / closes[0] - Decimal("1")) * Decimal("100")
        values.append(("total_return_pct", total_return))
        values.append(
            (
                "moving_average_short",
                _mean(closes[-self._short :] if len(closes) >= self._short else ()),
            )
        )
        values.append(
            (
                "moving_average_long",
                _mean(closes[-self._long :] if len(closes) >= self._long else ()),
            )
        )
        returns = tuple(
            closes[index] / closes[index - 1] - Decimal("1") for index in range(1, len(closes))
        )
        volatility = None
        if len(returns) >= 2:
            average = _mean(returns)
            if average is None:
                raise RuntimeError("return average is unexpectedly unavailable")
            variance = sum(((item - average) ** 2 for item in returns), Decimal("0")) / Decimal(
                len(returns) - 1
            )
            with localcontext() as context:
                context.prec = 64
                volatility = variance.sqrt() * Decimal("100")
        values.append(("realized_volatility_pct", volatility))
        true_ranges: list[Decimal] = []
        for index, bar in enumerate(bars):
            candidates = [bar.high - bar.low]
            if index:
                candidates.extend(
                    (abs(bar.high - bars[index - 1].close), abs(bar.low - bars[index - 1].close))
                )
            true_ranges.append(max(candidates))
        values.append(("average_true_range", _mean(tuple(true_ranges))))
        values.append(("breakout_high", max((bar.high for bar in bars), default=None)))
        values.append(("breakout_low", min((bar.low for bar in bars), default=None)))
        drawdown = None
        if closes:
            peak = max(closes)
            drawdown = (closes[-1] / peak - Decimal("1")) * Decimal("100")
        values.append(("drawdown_pct", drawdown))
        values.append(("average_volume", _mean(tuple(bar.volume for bar in bars))))
        values.append(
            ("average_dollar_volume", _mean(tuple(bar.close * bar.volume for bar in bars)))
        )
        values.append(("spread_pct", history.spread_percentage))
        canonical_values = tuple(values)
        data_hash = content_hash(
            {"as_of": as_of, "history_hash": history.data_hash, "values": canonical_values}
        )
        return FeatureVector(history.instrument_id, as_of, canonical_values, data_hash)


__all__ = ["FeaturePipeline", "LookaheadViolation"]
