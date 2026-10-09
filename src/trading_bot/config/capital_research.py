"""Opt-in canonical research extension; never an execution configuration."""

from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, model_validator

from trading_bot.config.models import (
    AppConfig,
    ConfigDecimal,
    LossLimitSettings,
    PositionRiskSettings,
    SafetyEnvelope,
    StrictDecimalTuple,
    StrictFalse,
    StrictIntegerTuple,
    StrictModel,
    StrictOne,
    StrictStringTuple,
)
from trading_bot.domain import ExecutionMode


class CapitalResearchSettings(StrictModel):
    policy_id: Literal["capital-constrained-etf-research-v1"]
    capital_tiers: StrictDecimalTuple
    universe: StrictStringTuple
    maximum_holding_sessions: StrictIntegerTuple
    round_trip_friction_pct: StrictDecimalTuple
    position_risk: PositionRiskSettings
    loss_limits: LossLimitSettings
    min_cash_reserve_pct: ConfigDecimal = Field(ge=40, le=100)
    max_open_positions: StrictOne
    execution_enabled: StrictFalse
    evidence_promotable: StrictFalse

    @model_validator(mode="after")
    def fixed_scope_and_conservative_limits(self) -> Self:
        if (
            self.capital_tiers != tuple(map(Decimal, (100, 250, 500, 1000, 5000, 10000)))
            or self.universe != ("SPY", "QQQ", "IWM", "SHY", "IEF")
            or self.maximum_holding_sessions != (2, 5, 10, 20)
            or self.round_trip_friction_pct != tuple(map(Decimal, (".05", ".10", ".20", ".40")))
            or self.position_risk.max_risk_per_trade_pct > Decimal(".50")
            or self.position_risk.max_position_notional_pct > 20
            or self.position_risk.max_correlated_group_exposure_pct > 20
            or self.position_risk.minimum_reward_to_initial_risk < 2
            or self.loss_limits.max_daily_loss_pct > 1
            or self.loss_limits.max_weekly_loss_pct > 5
            or self.loss_limits.max_peak_to_trough_drawdown_pct > 10
            or self.loss_limits.consecutive_loss_pause_count > 3
            or self.loss_limits.consecutive_loss_pause_minutes < 240
        ):
            raise ValueError("capital research policy exceeds its frozen research scope")
        return self


class CapitalResearchAppConfig(AppConfig):
    capital_research: CapitalResearchSettings

    @model_validator(mode="after")
    def isolated_offline_research(self) -> Self:
        if (
            self.mode not in (ExecutionMode.BACKTEST, ExecutionMode.SIMULATION)
            or self.live_trading_enabled
            or not self.runtime.start_paused
            or self.runtime.automatic_live_activation_enabled
            or self.options.enabled
            or not self.equities.enabled
            or self.crypto.enabled
            or self.prediction_markets.simulation_enabled
            or self.equity_strategies.etf_pilot.enabled
        ):
            raise ValueError("capital research requires isolated paused offline configuration")
        return self


class CapitalResearchSafetyEnvelope(SafetyEnvelope):
    capital_research: CapitalResearchSettings


def enforce_capital_research_envelope(
    config: CapitalResearchAppConfig, envelope: CapitalResearchSafetyEnvelope
) -> None:
    """The release-bound subsection is exact; no caller-declared risk authority."""
    if config.capital_research != envelope.capital_research:
        raise ValueError("capital research release identity mismatch")
