"""Pure long-only research scores; these are never executable order instructions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from itertools import pairwise

from trading_bot.research.hybrid_sources import SourceFact, identifier, utc, visible_facts

FAMILIES = (
    "momentum",
    "trend",
    "breakout",
    "quality_momentum",
    "mean_reversion",
    "pead",
    "revision_momentum",
)


@dataclass(frozen=True)
class PriceBar:
    completed_at: datetime
    open: Decimal
    close: Decimal

    def __post_init__(self) -> None:
        utc(self.completed_at)
        if any(
            not isinstance(v, Decimal)
            or not v.is_finite()
            or not Decimal("1e-30") <= v <= Decimal("1e30")
            for v in (self.open, self.close)
        ):
            raise ValueError("positive finite prices required")


@dataclass(frozen=True)
class ResearchSignal:
    status: str
    score: float | None
    reason: str


def validate_bars(bars: tuple[PriceBar, ...]) -> None:
    if any(a.completed_at >= b.completed_at for a, b in pairwise(bars)):
        raise ValueError("bars must have unique increasing completion timestamps")


def latest_metrics(
    facts: tuple[SourceFact, ...], symbol: str, as_of: datetime
) -> dict[str, Decimal]:
    selected: dict[str, SourceFact] = {}
    for fact in visible_facts(facts, as_of):
        if fact.symbol != symbol:
            continue
        old = selected.get(fact.metric)
        if old is None or (fact.period_end, fact.available_at, fact.event_id) > (
            old.period_end,
            old.available_at,
            old.event_id,
        ):
            selected[fact.metric] = fact
    return {key: value.value for key, value in selected.items()}


def evaluate_strategies(
    symbol: str, bars: tuple[PriceBar, ...], facts: tuple[SourceFact, ...], as_of: datetime
) -> dict[str, ResearchSignal]:
    identifier(symbol)
    utc(as_of)
    validate_bars(bars)
    if any(b.completed_at > as_of for b in bars):
        raise ValueError("future or incomplete bar")
    result = {
        name: ResearchSignal("unavailable", None, "required point-in-time inputs missing")
        for name in FAMILIES
    }
    if len(bars) < 21:
        return result
    closes = [b.close for b in bars]
    mean20 = sum(closes[-20:]) / Decimal(20)
    momentum = closes[-1] / closes[-21] - 1
    metrics = latest_metrics(facts, symbol, as_of)
    scores = {
        "momentum": momentum,
        "trend": closes[-1] / mean20 - 1,
        "breakout": closes[-1] / max(closes[-21:-1]) - 1,
        "mean_reversion": mean20 / closes[-1] - 1,
    }
    if "roe" in metrics:
        scores["quality_momentum"] = momentum * max(Decimal(0), metrics["roe"])
    if "earnings_surprise" in metrics:
        scores["pead"] = metrics["earnings_surprise"]
    if "estimate_revision" in metrics:
        scores["revision_momentum"] = metrics["estimate_revision"]
    for name, score in scores.items():
        result[name] = ResearchSignal(
            "research_only", float(score), "descriptive feature; unvalidated hypothesis"
        )
    return result


def rank_fundamentals(facts: tuple[SourceFact, ...], as_of: datetime) -> list[dict[str, object]]:
    visible = visible_facts(facts, as_of)
    result: list[dict[str, object]] = []
    for symbol in sorted({f.symbol for f in visible}):
        metrics = latest_metrics(visible, symbol, as_of)
        if not {"roe", "revenue_growth", "debt_to_equity"} <= metrics.keys():
            continue
        required = {"roe", "revenue_growth", "debt_to_equity"}
        latest = {
            metric: max(
                (f for f in visible if f.symbol == symbol and f.metric == metric),
                key=lambda f: (f.period_end, f.available_at, f.event_id),
            )
            for metric in required
        }
        if len({f.period_end for f in latest.values()}) != 1:
            continue
        score = metrics["roe"] + metrics["revenue_growth"] - metrics["debt_to_equity"]
        result.append({"symbol": symbol, "score": float(score), "status": "research_only"})
    return sorted(result, key=lambda r: (-float(str(r["score"])), str(r["symbol"])))


@dataclass(frozen=True)
class ScreenInput:
    symbol: str
    price: Decimal
    dollar_volume: Decimal | None
    available_at: datetime

    def __post_init__(self) -> None:
        identifier(self.symbol)
        utc(self.available_at)
        for value in (self.price, self.dollar_volume):
            if value is not None and (not value.is_finite() or value < 0):
                raise ValueError("finite nonnegative screen values required")


def screen_universe(
    inputs: tuple[ScreenInput, ...],
    *,
    as_of: datetime,
    minimum_price: Decimal,
    minimum_dollar_volume: Decimal,
) -> dict[str, list[str]]:
    """Explicit caller thresholds are research filters, never execution eligibility."""
    utc(as_of)
    for value in (minimum_price, minimum_dollar_volume):
        if not value.is_finite() or value <= 0:
            raise ValueError("positive finite screening thresholds required")
    if len({row.symbol for row in inputs}) != len(inputs):
        raise ValueError("duplicate screening symbol")
    result: dict[str, list[str]] = {"eligible": [], "unavailable": [], "excluded": []}
    for row in sorted(inputs, key=lambda r: r.symbol):
        if row.available_at > as_of or row.dollar_volume is None:
            result["unavailable"].append(row.symbol)
        elif row.price < minimum_price or row.dollar_volume < minimum_dollar_volume:
            result["excluded"].append(row.symbol)
        else:
            result["eligible"].append(row.symbol)
    return result
