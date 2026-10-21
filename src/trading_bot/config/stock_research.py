"""Opt-in stock research policy inside the canonical configuration graph."""

from decimal import Decimal
from itertools import pairwise
from typing import Literal, Self

from pydantic import Field, StrictInt, model_validator

from trading_bot.config.hybrid import HybridAppConfig, HybridSafetyEnvelope
from trading_bot.config.models import ConfigDecimal, StrictFalse, StrictModel


class StockResearchSettings(StrictModel):
    policy_id: Literal["stock-research-v1"] = "stock-research-v1"
    provider: Literal["robinhood_official_mcp"] = "robinhood_official_mcp"
    live_enabled: StrictFalse = False
    llm_enabled: StrictFalse = False
    scan_minutes: StrictInt = Field(default=60, ge=15, le=60)
    minimum_price_usd: ConfigDecimal = Field(default=Decimal(10), ge=10)
    minimum_market_cap_usd: ConfigDecimal = Field(default=Decimal("2000000000"), ge=2000000000)
    minimum_scanner_turnover_usd: ConfigDecimal = Field(default=Decimal("20000000"), ge=20000000)
    turnover_sessions: StrictInt = Field(default=30, ge=20, le=60)
    max_calls_per_cycle: StrictInt = Field(default=32, ge=1, le=32)
    max_daily_calls: StrictInt = Field(default=512, ge=1, le=1024)
    shortlist_count: StrictInt = Field(default=10, ge=1, le=20)
    minimum_sector_peers: StrictInt = Field(default=5, ge=3, le=50)
    maximum_source_age_minutes: StrictInt = Field(default=120, ge=1, le=1440)
    quality_weight_pct: ConfigDecimal = Field(default=Decimal(40), ge=0, le=100)
    growth_weight_pct: ConfigDecimal = Field(default=Decimal(35), ge=0, le=100)
    valuation_weight_pct: ConfigDecimal = Field(default=Decimal(25), ge=0, le=100)
    market_cap_boundaries_usd: tuple[ConfigDecimal, ...] = (
        Decimal("2000000000"),
        Decimal("3000000000"),
        Decimal("4000000000"),
        Decimal("5000000000"),
        Decimal("6250000000"),
        Decimal("7500000000"),
        Decimal("10000000000"),
        Decimal("15000000000"),
        Decimal("20000000000"),
        Decimal("30000000000"),
        Decimal("50000000000"),
        Decimal("75000000000"),
        Decimal("100000000000"),
        Decimal("200000000000"),
        Decimal("500000000000"),
        Decimal("1000000000000"),
    )

    @model_validator(mode="after")
    def bounded_hypothesis(self) -> Self:
        if self.quality_weight_pct + self.growth_weight_pct + self.valuation_weight_pct != 100:
            raise ValueError("stock research weights must sum to 100")
        bounds = self.market_cap_boundaries_usd
        if (
            not 1 <= len(bounds) <= 24
            or bounds[0] != self.minimum_market_cap_usd
            or any(left >= right for left, right in pairwise(bounds))
            or len(bounds) + 1 > self.max_calls_per_cycle
            or self.max_daily_calls < self.max_calls_per_cycle
        ):
            raise ValueError("stock research partition or call budget invalid")
        return self


class StockResearchAppConfig(HybridAppConfig):
    stock_research: StockResearchSettings


class StockResearchSafetyEnvelope(HybridSafetyEnvelope):
    stock_research: StockResearchSettings
