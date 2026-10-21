"""Explicit bounded source imports; imports never attest data qualification."""

import re
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_bot.clock import require_utc
from trading_bot.research.hybrid_service import research_snapshot
from trading_bot.research.hybrid_sources import SourceFact
from trading_bot.research.hybrid_strategies import PriceBar, validate_bars


class ResearchInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    provider: Literal["declared_import", "sec_public", "fred_public"]
    source_reference: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    received_at: datetime
    facts: tuple[SourceFact, ...] = ()
    prices: dict[str, tuple[PriceBar, ...]] = Field(default_factory=dict)

    _utc = field_validator("received_at")(require_utc)

    @model_validator(mode="after")
    def bounded_point_in_time(self) -> Self:
        if len(self.facts) > 2000 or len(self.prices) > 20:
            raise ValueError("research input bounds exceeded")
        if any(fact.available_at > self.received_at for fact in self.facts):
            raise ValueError("future financial facts unavailable")
        for symbol, bars in self.prices.items():
            if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol) is None or len(bars) > 1000:
                raise ValueError("invalid symbol or excessive history")
            validate_bars(bars)
            if any(bar.completed_at > self.received_at for bar in bars):
                raise ValueError("future price bars unavailable")
        return self


def present_research(bundle: ResearchInputs, now: datetime) -> dict[str, object]:
    require_utc(now)
    if bundle.received_at > now:
        raise ValueError("future input receipt cannot enter research")
    report = research_snapshot(as_of=now, facts=bundle.facts, prices=bundle.prices)
    report["sources"] = [
        {
            "name": bundle.source_reference,
            "status": "declared_unqualified",
            "as_of": bundle.received_at.isoformat(),
            "detail": bundle.provider,
        }
    ]
    statuses = report.get("strategy_status", [])
    if isinstance(statuses, list):
        report["strategy_status"] = [
            dict(item, name=item.get("strategy", "unknown"))
            for item in statuses
            if isinstance(item, dict)
        ]
    report["qualified"] = False
    report["data_age_seconds"] = (now - bundle.received_at).total_seconds()
    return report
