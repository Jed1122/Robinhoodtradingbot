"""Strict, immutable configuration models for every operating mode."""

import re
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
)

from trading_bot.domain import BarInterval, ExecutionMode


def _validate_config_decimal(value: object) -> Decimal:
    if type(value) is Decimal:
        return value
    if type(value) is int:
        return Decimal(value)
    raise ValueError("decimal input must be Decimal or an exact integer")


def _validate_strict_literal_bool(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("literal boolean input must be a boolean")
    return value


def _validate_strict_literal_int(value: object) -> int:
    if type(value) is not int:
        raise ValueError("literal integer input must be an integer")
    return value


def _validate_strict_tuple_container(value: object) -> object:
    if type(value) not in (list, tuple):
        raise ValueError("tuple input must be a YAML list or native tuple")
    return value


def _validate_strict_bar_interval(value: object) -> object:
    if type(value) not in (str, BarInterval):
        raise ValueError("bar interval input must be a string or BarInterval")
    return value


def _validate_strict_execution_mode(value: object) -> object:
    if type(value) not in (str, ExecutionMode):
        raise ValueError("execution mode input must be a string or ExecutionMode")
    return value


ConfigDecimal = Annotated[Decimal, BeforeValidator(_validate_config_decimal)]
StrictFalse = Annotated[Literal[False], BeforeValidator(_validate_strict_literal_bool)]
StrictTrue = Annotated[Literal[True], BeforeValidator(_validate_strict_literal_bool)]
StrictOne = Annotated[Literal[1], BeforeValidator(_validate_strict_literal_int)]
StrictBarInterval = Annotated[BarInterval, BeforeValidator(_validate_strict_bar_interval)]
StrictExecutionMode = Annotated[ExecutionMode, BeforeValidator(_validate_strict_execution_mode)]
StrictStringTuple = Annotated[
    tuple[StrictStr, ...], BeforeValidator(_validate_strict_tuple_container)
]
StrictIntegerTuple = Annotated[
    tuple[StrictInt, ...], BeforeValidator(_validate_strict_tuple_container)
]
StrictDecimalTuple = Annotated[
    tuple[ConfigDecimal, ...], BeforeValidator(_validate_strict_tuple_container)
]
StrictBarIntervalTuple = Annotated[
    tuple[StrictBarInterval, ...], BeforeValidator(_validate_strict_tuple_container)
]
StrictExecutionModeTuple = Annotated[
    tuple[StrictExecutionMode, ...], BeforeValidator(_validate_strict_tuple_container)
]
Pct = ConfigDecimal
Seconds = ConfigDecimal

_RESEARCH_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,14}\Z")
_EQUITY_RESEARCH_CANDIDATES = frozenset({"equity_momentum", "equity_relative_strength"})


class StrictModel(BaseModel):
    """Base for the only canonical configuration graph."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )


class PortfolioSettings(StrictModel):
    expected_starting_equity_usd: ConfigDecimal = Field(gt=0)
    live_account_equity_ceiling_usd: ConfigDecimal = Field(gt=0)
    max_total_gross_exposure_pct: Pct = Field(ge=0, le=100)
    min_cash_reserve_pct: Pct = Field(ge=0, le=100)
    max_open_positions: StrictInt = Field(ge=0)
    max_gross_exposure_usd: ConfigDecimal = Field(ge=0)

    @model_validator(mode="after")
    def validate_portfolio_bounds(self) -> Self:
        if self.live_account_equity_ceiling_usd < self.expected_starting_equity_usd:
            raise ValueError("live account equity ceiling must not be below expected equity")
        if self.max_total_gross_exposure_pct + self.min_cash_reserve_pct > Decimal("100"):
            raise ValueError(
                "gross exposure plus cash reserve cannot exceed 100 whole-percent units"
            )
        return self


class PositionRiskSettings(StrictModel):
    max_risk_per_trade_pct: Pct = Field(ge=0, le=100)
    max_position_notional_pct: Pct = Field(ge=0, le=100)
    max_correlated_group_exposure_pct: Pct = Field(ge=0, le=100)
    minimum_reward_to_initial_risk: ConfigDecimal = Field(gt=0)
    averaging_down_allowed: StrictFalse
    pyramiding_allowed: StrictFalse


class LossLimitSettings(StrictModel):
    max_daily_loss_pct: Pct = Field(ge=0, le=100)
    max_weekly_loss_pct: Pct = Field(ge=0, le=100)
    max_peak_to_trough_drawdown_pct: Pct = Field(ge=0, le=100)
    consecutive_loss_pause_count: StrictInt = Field(ge=1)
    consecutive_loss_pause_minutes: StrictInt = Field(ge=1)

    @model_validator(mode="after")
    def validate_ordered_loss_limits(self) -> Self:
        if not (
            self.max_daily_loss_pct
            <= self.max_weekly_loss_pct
            <= self.max_peak_to_trough_drawdown_pct
        ):
            raise ValueError("daily, weekly, and drawdown limits must be ordered")
        return self


class ActivitySettings(StrictModel):
    max_new_orders_per_day: StrictInt = Field(ge=0)
    max_orders_per_symbol_per_day: StrictInt = Field(ge=0)
    minimum_minutes_between_new_orders: StrictInt = Field(ge=0)
    max_order_notional_usd: ConfigDecimal = Field(ge=0)


class EquitySettings(StrictModel):
    enabled: StrictBool
    long_only: StrictTrue
    margin_allowed: StrictFalse
    short_sales_allowed: StrictFalse
    options_allowed: StrictFalse
    leveraged_etfs_allowed: StrictFalse
    inverse_etfs_allowed: StrictFalse
    otc_allowed: StrictFalse
    microcaps_allowed: StrictFalse
    max_spread_pct: Pct = Field(ge=0, le=100)
    minimum_price_usd: ConfigDecimal = Field(gt=0)
    minimum_average_daily_dollar_volume_usd: ConfigDecimal = Field(gt=0)
    avoid_new_entry_before_earnings_trading_days: StrictInt = Field(ge=0)
    avoid_new_entry_after_earnings_trading_days: StrictInt = Field(ge=0)
    reconciliation_quantity_tolerance: ConfigDecimal = Field(ge=0)


class CryptoSettings(StrictModel):
    enabled: StrictBool
    max_total_crypto_exposure_pct: Pct = Field(ge=0, le=100)
    max_single_crypto_exposure_pct: Pct = Field(ge=0, le=100)
    initial_symbol_allowlist: StrictStringTuple = Field(min_length=1)
    max_spread_pct: Pct = Field(ge=0, le=100)
    leverage_allowed: StrictFalse
    reconciliation_quantity_tolerance: ConfigDecimal = Field(ge=0)

    @model_validator(mode="after")
    def validate_crypto_limits(self) -> Self:
        if self.max_single_crypto_exposure_pct > self.max_total_crypto_exposure_pct:
            raise ValueError("single-crypto exposure cannot exceed total crypto exposure")
        if len(set(self.initial_symbol_allowlist)) != len(self.initial_symbol_allowlist):
            raise ValueError("crypto symbol allowlist cannot contain duplicates")
        return self


class PredictionSettings(StrictModel):
    simulation_enabled: StrictBool
    live_enabled: StrictFalse
    future_max_single_contract_risk_pct: Pct = Field(ge=0, le=100)
    future_max_total_exposure_pct: Pct = Field(ge=0, le=100)


class FreshnessSettings(StrictModel):
    max_executable_quote_age_seconds: Seconds = Field(gt=0)
    max_account_snapshot_age_seconds: Seconds = Field(gt=0)
    max_broker_health_age_seconds: Seconds = Field(gt=0)
    max_broker_review_age_seconds: Seconds = Field(gt=0)
    max_preflight_age_seconds: Seconds = Field(gt=0)
    max_clock_drift_seconds: Seconds = Field(gt=0)


class AuthorizationSettings(StrictModel):
    activation_lifetime_seconds: StrictInt = Field(ge=1)
    live_lease_lifetime_seconds: StrictInt = Field(ge=1)


class RuntimeSettings(StrictModel):
    start_paused: StrictBool
    broker_timeout_seconds: Seconds = Field(gt=0)
    shutdown_deadline_seconds: StrictInt = Field(ge=1)
    remainder_order_max_age_seconds: StrictInt = Field(ge=1)
    automatic_live_activation_enabled: StrictFalse
    automatic_liquidation_enabled: StrictFalse
    normal_entry_market_orders_allowed: StrictFalse
    emergency_market_orders_allowed: StrictFalse


class MarketDataSettings(StrictModel):
    canonical_bar_intervals: StrictBarIntervalTuple = Field(min_length=1)
    max_data_age_bars: StrictInt = Field(ge=0)
    max_anomaly_change_pct: Pct = Field(ge=0, le=100)
    max_cross_response_timestamp_skew_seconds: Seconds = Field(ge=0)
    interpolated_bars_allowed: StrictFalse

    @model_validator(mode="after")
    def validate_unique_intervals(self) -> Self:
        if len(set(self.canonical_bar_intervals)) != len(self.canonical_bar_intervals):
            raise ValueError("canonical bar intervals cannot contain duplicates")
        return self


class ResearchSettings(StrictModel):
    seed: StrictInt = Field(ge=0)
    walk_forward_folds: StrictInt = Field(ge=2)
    embargo_bars: StrictInt = Field(ge=0)
    monte_carlo_iterations: StrictInt = Field(ge=1)
    history_calendar_days: StrictInt = Field(ge=1)
    minimum_history_bars: StrictInt = Field(ge=2)
    minimum_test_bars_per_fold: StrictInt = Field(ge=1)
    minimum_independent_opportunities: StrictInt = Field(ge=1)
    maximum_stressed_drawdown_pct: Pct = Field(ge=0, le=100)
    minimum_positive_walk_forward_folds: StrictInt = Field(ge=1)
    maximum_single_opportunity_profit_contribution_pct: Pct = Field(ge=0, le=100)
    maximum_monte_carlo_loss_probability_pct: Pct = Field(ge=0, le=100)
    minimum_benchmark_excess_return_pct: Pct = Field(ge=0, le=100)
    assumptions_validated: StrictBool
    evidence_promotable: StrictBool

    @model_validator(mode="after")
    def unvalidated_research_is_not_promotable(self) -> Self:
        if self.evidence_promotable and not self.assumptions_validated:
            raise ValueError("research evidence cannot be promotable before assumptions validate")
        if self.minimum_positive_walk_forward_folds > self.walk_forward_folds:
            raise ValueError("positive research folds cannot exceed walk-forward folds")
        if self.minimum_history_bars < self.minimum_test_bars_per_fold * self.walk_forward_folds:
            raise ValueError("research history cannot be smaller than the test-fold requirement")
        return self


class SimulationSettings(StrictModel):
    rejection_probability_pct: Pct = Field(ge=0, le=100)
    no_fill_probability_pct: Pct = Field(ge=0, le=100)
    full_fill_probability_pct: Pct = Field(ge=0, le=100)
    partial_fill_probability_pct: Pct = Field(ge=0, le=100)
    partial_fill_min_pct: Pct = Field(gt=0, le=100)
    partial_fill_max_pct: Pct = Field(gt=0, le=100)
    latency_milliseconds: StrictInt = Field(ge=0)
    cancel_race_probability_pct: Pct = Field(ge=0, le=100)
    same_bar_fills_allowed: StrictFalse
    market_session_rules_enforced: StrictTrue
    assumptions_validated: StrictBool
    evidence_promotable: StrictBool

    @model_validator(mode="after")
    def validate_simulation_assumptions(self) -> Self:
        total = (
            self.rejection_probability_pct
            + self.no_fill_probability_pct
            + self.full_fill_probability_pct
            + self.partial_fill_probability_pct
        )
        if total != Decimal("100"):
            raise ValueError("simulation outcome probabilities must total 100 whole-percent units")
        if self.partial_fill_min_pct > self.partial_fill_max_pct:
            raise ValueError("partial fill minimum cannot exceed maximum")
        if self.evidence_promotable and not self.assumptions_validated:
            raise ValueError("simulation evidence cannot be promotable before assumptions validate")
        return self


class CostSettings(StrictModel):
    assumed_equity_spread_pct: Pct = Field(ge=0, le=100)
    assumed_crypto_spread_pct: Pct = Field(ge=0, le=100)
    assumed_prediction_spread_pct: Pct = Field(ge=0, le=100)
    assumed_slippage_pct: Pct = Field(ge=0, le=100)
    max_slippage_pct: Pct = Field(ge=0, le=100)
    equity_commission_usd: ConfigDecimal = Field(ge=0)
    crypto_fee_pct: Pct = Field(ge=0, le=100)
    prediction_fee_pct: Pct = Field(ge=0, le=100)
    stressed_cost_multiplier: ConfigDecimal = Field(ge=1)
    stressed_fill_probability_pct: Pct = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_cost_bounds(self) -> Self:
        if self.assumed_slippage_pct > self.max_slippage_pct:
            raise ValueError("assumed slippage cannot exceed the configured maximum")
        return self


class RetrySettings(StrictModel):
    read_attempts: StrictInt = Field(ge=1)
    initial_backoff_seconds: Seconds = Field(ge=0)
    max_backoff_seconds: Seconds = Field(ge=0)
    write_attempts: StrictOne

    @model_validator(mode="after")
    def validate_backoff(self) -> Self:
        if self.initial_backoff_seconds > self.max_backoff_seconds:
            raise ValueError("initial backoff cannot exceed maximum backoff")
        return self


class SchedulerSettings(StrictModel):
    equity_reconciliation_cadence_seconds: StrictInt = Field(ge=1)
    crypto_reconciliation_cadence_seconds: StrictInt = Field(ge=1)
    broker_health_cadence_seconds: StrictInt = Field(ge=1)
    heartbeat_cadence_seconds: StrictInt = Field(ge=1)
    performance_report_cadence_seconds: StrictInt = Field(ge=1)
    security_report_cadence_seconds: StrictInt = Field(ge=1)


class MonitoringSettings(StrictModel):
    host: StrictStr = Field(min_length=1)
    port: StrictInt = Field(ge=1, le=65535)
    container_loopback_publish: StrictBool
    webhook_attempts: StrictInt = Field(ge=1)
    webhook_timeout_seconds: Seconds = Field(gt=0)
    alert_deduplication_window_seconds: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def validate_bind_policy(self) -> Self:
        if self.host == "127.0.0.1":
            return self
        # This validates a configured address string; no socket bind occurs in this model.
        if self.host == "0.0.0.0" and self.container_loopback_publish:  # nosec B104
            return self
        raise ValueError("monitoring must bind loopback or verified container loopback publish")


class LoggingSettings(StrictModel):
    max_event_bytes: StrictInt = Field(ge=2)


class PromotionSettings(StrictModel):
    paper_min_eligible_unique_cycles: StrictInt = Field(ge=1)
    shadow_min_calendar_days: StrictInt = Field(ge=1)
    micro_order_review_interval: StrictInt = Field(ge=1)
    normal_min_combined_calendar_days: StrictInt = Field(ge=1)
    normal_min_valid_observations: StrictInt = Field(ge=1)
    clean_reconciliation_required: StrictTrue
    no_critical_security_findings_required: StrictTrue
    current_manual_acknowledgement_required: StrictTrue
    pause_on_unknown_order_state: StrictTrue


class LlmReportingSettings(StrictModel):
    enabled: StrictBool
    daily_token_budget: StrictInt = Field(ge=0)
    monthly_token_budget: StrictInt = Field(ge=0)
    timeout_seconds: Seconds = Field(gt=0)

    @model_validator(mode="after")
    def validate_token_budgets(self) -> Self:
        if self.monthly_token_budget < self.daily_token_budget:
            raise ValueError("monthly LLM budget cannot be below daily budget")
        return self


class BackupSettings(StrictModel):
    destination: StrictStr = Field(min_length=1)
    cadence_seconds: StrictInt = Field(ge=1)
    retention_daily_archives: StrictInt = Field(ge=1)
    restore_test_cadence_seconds: StrictInt = Field(ge=1)
    encryption_required: StrictTrue


class EquityStrategySettings(StrictModel):
    short_windows: StrictIntegerTuple = Field(min_length=1)
    long_windows: StrictIntegerTuple = Field(min_length=1)
    regime_multipliers: StrictDecimalTuple = Field(min_length=1)
    research_universe_symbols: StrictStringTuple = Field(min_length=1)
    research_candidate_strategy_ids: StrictStringTuple = Field(min_length=1)
    research_relative_strength_top_n: StrictIntegerTuple = Field(min_length=1)
    research_rebalance_bars: StrictInt = Field(ge=1)
    research_unselected_symbols_exit_to_cash: StrictTrue
    research_benchmark_symbol: StrictStr = Field(min_length=1)
    bar_interval: StrictBarInterval
    maximum_holding_bars: StrictInt = Field(ge=1)
    stop_loss_atr_multiplier: ConfigDecimal = Field(gt=0)
    exit_reward_to_initial_risk: ConfigDecimal = Field(gt=0)
    exit_on_regime_change: StrictBool
    mean_reversion_enabled: StrictFalse

    @model_validator(mode="after")
    def validate_equity_grid(self) -> Self:
        if tuple(sorted(set(self.short_windows))) != self.short_windows:
            raise ValueError("equity short windows must be unique and increasing")
        if tuple(sorted(set(self.long_windows))) != self.long_windows:
            raise ValueError("equity long windows must be unique and increasing")
        if max(self.short_windows) >= min(self.long_windows):
            raise ValueError("equity short windows must remain below long windows")
        if len(set(self.research_universe_symbols)) != len(self.research_universe_symbols) or any(
            _RESEARCH_SYMBOL.fullmatch(symbol) is None for symbol in self.research_universe_symbols
        ):
            raise ValueError(
                "equity research universe must contain unique uppercase ticker symbols"
            )
        if len(set(self.research_candidate_strategy_ids)) != len(
            self.research_candidate_strategy_ids
        ) or not set(self.research_candidate_strategy_ids).issubset(_EQUITY_RESEARCH_CANDIDATES):
            raise ValueError("equity research candidates are unsupported or duplicated")
        if tuple(
            sorted(set(self.research_relative_strength_top_n))
        ) != self.research_relative_strength_top_n or max(
            self.research_relative_strength_top_n
        ) > len(self.research_universe_symbols):
            raise ValueError(
                "relative-strength top-N values must be unique, increasing, and in universe"
            )
        if self.research_benchmark_symbol not in self.research_universe_symbols:
            raise ValueError("equity research benchmark must be in the research universe")
        return self


class CryptoStrategySettings(StrictModel):
    bar_intervals: StrictBarIntervalTuple = Field(min_length=1)
    fast_windows: StrictIntegerTuple = Field(min_length=1)
    slow_windows: StrictIntegerTuple = Field(min_length=1)
    breakout_windows: StrictIntegerTuple = Field(min_length=1)
    maximum_holding_bars: StrictInt = Field(ge=1)
    stop_loss_atr_multiplier: ConfigDecimal = Field(gt=0)
    exit_reward_to_initial_risk: ConfigDecimal = Field(gt=0)
    cash_regime_for_negative_trend: StrictTrue


class PredictionResearchSettings(StrictModel):
    seed: StrictInt = Field(ge=0)
    minimum_margin_of_safety_pct: Pct = Field(gt=0, le=100)
    calibration_bins: StrictInt = Field(ge=2)
    minimum_samples_per_bin: StrictInt = Field(ge=1)
    maximum_holding_bars: StrictInt = Field(ge=1)
    live_eligible: StrictFalse


class OptionsShortlistSettings(StrictModel):
    """Fixed acquisition-universe policy; no trading or source-verification authority."""

    enabled: StrictBool
    underlying: Literal["SPY"]
    version: Literal["spy-prior-close-atm-30d-v1"]
    reference: Literal["previous_regular_session_close"]
    strike_tie: Literal["lower_strike"]
    expiry_tie: Literal["earlier_expiry"]
    min_dte: StrictInt = Field(ge=21, le=21)
    target_dte: StrictInt = Field(ge=30, le=30)
    max_dte: StrictInt = Field(ge=45, le=45)
    max_input_records: StrictInt = Field(ge=1, le=25000)
    max_input_bytes: StrictInt = Field(ge=1, le=16777216)
    max_json_depth: StrictInt = Field(ge=1, le=16)
    max_decision_sessions: StrictInt = Field(ge=1, le=1)


class OptionsSettings(StrictModel):
    """Options-only research extension; all percentages use whole-percent units."""

    enabled: StrictBool
    live_supported: StrictFalse
    max_per_trade_loss_usd: ConfigDecimal = Field(ge=0)
    cumulative_trial_loss_limit_usd: ConfigDecimal = Field(ge=0)
    max_total_payoff_risk_pct: Pct = Field(ge=0, le=100)
    max_underlying_group_payoff_risk_pct: Pct = Field(ge=0, le=100)
    min_unencumbered_cash_pct: Pct = Field(ge=0, le=100)
    max_open_strategy_positions: StrictInt = Field(ge=0)
    max_new_positions_per_session: StrictInt = Field(ge=0)
    max_structure_units_per_entry: StrictInt = Field(ge=0)
    replay_max_bytes: StrictInt = Field(ge=1)
    replay_max_records: StrictInt = Field(ge=1)
    replay_max_json_depth: StrictInt = Field(ge=1)
    allow_locked_quotes: StrictBool
    margin_borrowing_enabled: StrictFalse
    uncovered_options_enabled: StrictFalse
    zero_dte_live_enabled: StrictFalse
    overnight_session_entries_enabled: StrictFalse
    research_shortlist: OptionsShortlistSettings

    @model_validator(mode="after")
    def validate_risk_hierarchy(self) -> Self:
        if self.max_underlying_group_payoff_risk_pct > self.max_total_payoff_risk_pct:
            raise ValueError("options group risk exceeds portfolio risk")
        if self.max_total_payoff_risk_pct + self.min_unencumbered_cash_pct > 100:
            raise ValueError("options payoff risk and cash reserve exceed 100 percent")
        return self


class AppConfig(StrictModel):
    mode: StrictExecutionMode
    live_trading_enabled: StrictBool
    portfolio: PortfolioSettings
    position_risk: PositionRiskSettings
    loss_limits: LossLimitSettings
    activity: ActivitySettings
    equities: EquitySettings
    crypto: CryptoSettings
    prediction_markets: PredictionSettings
    freshness: FreshnessSettings
    authorization: AuthorizationSettings
    runtime: RuntimeSettings
    market_data: MarketDataSettings
    research: ResearchSettings
    simulation: SimulationSettings
    costs: CostSettings
    retry: RetrySettings
    scheduler: SchedulerSettings
    monitoring: MonitoringSettings
    logging: LoggingSettings
    promotion: PromotionSettings
    llm_reporting: LlmReportingSettings
    backup: BackupSettings
    equity_strategies: EquityStrategySettings
    crypto_strategies: CryptoStrategySettings
    prediction_research: PredictionResearchSettings
    options: OptionsSettings

    @model_validator(mode="after")
    def live_flag_never_unpauses_startup(self) -> Self:
        if self.options.research_shortlist.enabled and (
            not self.options.enabled
            or self.mode not in {ExecutionMode.BACKTEST, ExecutionMode.SIMULATION}
        ):
            raise ValueError("shortlist requires an explicit offline options research mode")
        if self.live_trading_enabled and not self.runtime.start_paused:
            raise ValueError("live trading flag cannot unpause startup")
        if self.options.enabled:
            if (
                self.equities.enabled
                or self.crypto.enabled
                or (self.prediction_markets.simulation_enabled)
            ):
                raise ValueError("options runtime excludes standalone non-options strategies")
            if self.live_trading_enabled or self.mode not in (
                ExecutionMode.BACKTEST,
                ExecutionMode.SIMULATION,
                ExecutionMode.PAPER,
            ):
                raise ValueError(
                    "options runtime currently permits credential-free offline modes only"
                )
            if not self.runtime.start_paused:
                raise ValueError("options runtime must start paused")
        return self


class SafetyEnvelope(StrictModel):
    """Release-level bounds that mode and environment values can only tighten."""

    allowed_modes: StrictExecutionModeTuple = Field(min_length=1)
    live_trading_permitted: StrictBool
    prediction_live_permitted: StrictFalse
    options: OptionsSettings
    portfolio: PortfolioSettings
    position_risk: PositionRiskSettings
    loss_limits: LossLimitSettings
    activity: ActivitySettings
    equities: EquitySettings
    crypto: CryptoSettings
    prediction_markets: PredictionSettings
    freshness: FreshnessSettings
    authorization: AuthorizationSettings
    runtime: RuntimeSettings
    market_data: MarketDataSettings
    research: ResearchSettings
    simulation: SimulationSettings
    costs: CostSettings
    retry: RetrySettings
    logging: LoggingSettings
    promotion: PromotionSettings
    llm_reporting: LlmReportingSettings
    micro_max_order_notional_usd: ConfigDecimal = Field(ge=0)
    micro_max_gross_exposure_usd: ConfigDecimal = Field(ge=0)
    micro_max_new_orders_per_day: StrictInt = Field(ge=0)
