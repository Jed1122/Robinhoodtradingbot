"""Research presentation seam. Calling without inputs is truthful and performs no I/O."""

from dataclasses import asdict
from datetime import datetime

from trading_bot.research.hybrid_sources import SourceFact, visible_facts
from trading_bot.research.hybrid_strategies import (
    FAMILIES,
    PriceBar,
    evaluate_strategies,
    rank_fundamentals,
)


def research_snapshot(
    *,
    as_of: datetime | None = None,
    facts: tuple[SourceFact, ...] = (),
    prices: dict[str, tuple[PriceBar, ...]] | None = None,
) -> dict[str, object]:
    if as_of is None:
        if facts or prices:
            raise ValueError("explicit as_of required for supplied inputs")
        return {
            "regime": "unknown",
            "opportunities": [],
            "sources": [],
            "strategy_status": [
                {
                    "strategy": name,
                    "status": "unavailable",
                    "reason": "required point-in-time inputs missing",
                }
                for name in FAMILIES
            ],
            "comparisons": [],
            "limitations": [
                "No supplied evidence; research unavailable",
                "No trading or promotion authorization",
            ],
        }
    visible = visible_facts(facts, as_of)
    statuses = []
    for symbol, bars in sorted((prices or {}).items()):
        for family, signal in evaluate_strategies(symbol, bars, visible, as_of).items():
            statuses.append({"symbol": symbol, "strategy": family, **asdict(signal)})
    return {
        "regime": "unknown",
        "opportunities": rank_fundamentals(visible, as_of),
        "sources": sorted({f.source_url for f in visible}),
        "strategy_status": statuses or research_snapshot()["strategy_status"],
        "comparisons": [],
        "limitations": [
            "Descriptive research only; no validated performance",
            "Source authenticity and coverage unverified",
            "No trading or promotion authorization",
        ],
    }
