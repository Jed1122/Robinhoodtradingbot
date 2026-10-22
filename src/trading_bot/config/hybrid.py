"""Opt-in extension of the canonical graph; legacy configurations are unchanged."""

from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, StrictInt, model_validator

from trading_bot.config.models import (
    AppConfig,
    ConfigDecimal,
    SafetyEnvelope,
    StrictFalse,
    StrictModel,
)
from trading_bot.domain import ExecutionMode


class HybridSettings(StrictModel):
    policy_id: Literal["hybrid-equity-v1"] = "hybrid-equity-v1"
    starting_capital_usd: ConfigDecimal = Field(default=Decimal(1000), gt=0)
    long_term_pct: ConfigDecimal = Field(default=Decimal(75), ge=0, le=100)
    tactical_pct: ConfigDecimal = Field(default=Decimal(15), ge=0, le=15)
    reserve_pct: ConfigDecimal = Field(default=Decimal(10), ge=10, le=100)
    tactical_position_pct: ConfigDecimal = Field(default=Decimal(4), gt=0, le=4)
    company_pct: ConfigDecimal = Field(default=Decimal(10), gt=0, le=10)
    sector_pct: ConfigDecimal = Field(default=Decimal(25), gt=0, le=25)
    monthly_operating_usd: ConfigDecimal = Field(default=Decimal(12), ge=0)
    additional_monthly_budget_usd: ConfigDecimal = Field(default=Decimal(0), ge=0, le=0)
    tax_rate: ConfigDecimal | None = Field(default=None, ge=0, le=1)
    paper_period_required: StrictFalse = False
    live_enabled: StrictFalse = False
    paid_llm_enabled: StrictFalse = False
    screening_minutes: StrictInt = Field(default=30, ge=15, le=60)
    principal_trigger_pct: ConfigDecimal = Field(default=Decimal(15), ge=10, le=20)
    trailing_pct: ConfigDecimal = Field(default=Decimal(5), gt=0, le=100)
    simulation_slippage_bps: ConfigDecimal = Field(default=Decimal(5), ge=0, le=100)
    simulation_fee_usd: ConfigDecimal = Field(default=Decimal("0.01"), ge=0)

    @model_validator(mode="after")
    def allocations(self) -> Self:
        if self.long_term_pct + self.tactical_pct + self.reserve_pct != 100:
            raise ValueError("hybrid allocations must sum to 100")
        return self


class HybridAppConfig(AppConfig):
    hybrid: HybridSettings

    @model_validator(mode="after")
    def isolated_nonlive_composition(self) -> Self:
        if (
            self.mode not in {ExecutionMode.PAPER, ExecutionMode.SIMULATION, ExecutionMode.BACKTEST}
            or self.live_trading_enabled
            or self.crypto.enabled
            or self.options.enabled
            or self.prediction_markets.simulation_enabled
            or not self.runtime.start_paused
        ):
            raise ValueError(
                "hybrid release is paused equities-only and cannot enable live trading"
            )
        if self.portfolio.expected_starting_equity_usd != self.hybrid.starting_capital_usd:
            raise ValueError("hybrid starting capital must match canonical portfolio settings")
        return self


class HybridSafetyEnvelope(SafetyEnvelope):
    hybrid: HybridSettings
