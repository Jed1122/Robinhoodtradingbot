"""Validation tests for the single canonical configuration graph."""

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from trading_bot.config import (
    AppConfig,
    PredictionSettings,
    SafetyEnvelope,
    load_config,
)
from trading_bot.config.models import StrictModel

ROOT = Path(__file__).parents[3]
CONFIGS = ROOT / "configs"


def load_backtest():  # type: ignore[no-untyped-def]
    return load_config(
        base_path=CONFIGS / "base.yaml",
        mode_path=CONFIGS / "backtest.yaml",
        safety_path=CONFIGS / "safety-envelope.yaml",
        environ={},
    )


def test_all_models_are_frozen_and_forbid_unknown_keys() -> None:
    config = load_backtest().config

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        type(config).model_validate({**config.model_dump(), "mystery": True})

    with pytest.raises(ValidationError, match="frozen"):
        config.portfolio.max_open_positions = 10  # type: ignore[misc]

    for value in config.__dict__.values():
        if hasattr(value, "model_config"):
            assert value.model_config["extra"] == "forbid"
            assert value.model_config["frozen"] is True
            assert value.model_config["allow_inf_nan"] is False


def test_every_graph_field_is_required_in_yaml() -> None:
    pending: list[type[StrictModel]] = [AppConfig, SafetyEnvelope]
    seen: set[type[StrictModel]] = set()

    while pending:
        model = pending.pop()
        if model in seen:
            continue
        seen.add(model)
        assert all(field.is_required() for field in model.model_fields.values())
        for field in model.model_fields.values():
            annotation = field.annotation
            if isinstance(annotation, type) and issubclass(annotation, StrictModel):
                pending.append(annotation)


def test_approved_portfolio_risk_activity_and_asset_values_are_exact() -> None:
    config = load_backtest().config

    assert config.portfolio.expected_starting_equity_usd == Decimal("100")
    assert config.portfolio.live_account_equity_ceiling_usd == Decimal("150")
    assert config.portfolio.max_total_gross_exposure_pct == Decimal("60")
    assert config.portfolio.min_cash_reserve_pct == Decimal("40")
    assert config.portfolio.max_open_positions == 5
    assert config.position_risk.max_risk_per_trade_pct == Decimal("0.50")
    assert config.position_risk.max_position_notional_pct == Decimal("15")
    assert config.position_risk.max_correlated_group_exposure_pct == Decimal("25")
    assert config.position_risk.minimum_reward_to_initial_risk == Decimal("2.0")
    assert not config.position_risk.averaging_down_allowed
    assert not config.position_risk.pyramiding_allowed
    assert config.loss_limits.max_daily_loss_pct == Decimal("2")
    assert config.loss_limits.max_weekly_loss_pct == Decimal("5")
    assert config.loss_limits.max_peak_to_trough_drawdown_pct == Decimal("10")
    assert config.loss_limits.consecutive_loss_pause_count == 3
    assert config.loss_limits.consecutive_loss_pause_minutes == 240
    assert config.activity.max_new_orders_per_day == 3
    assert config.activity.max_orders_per_symbol_per_day == 1
    assert config.activity.minimum_minutes_between_new_orders == 30
    assert config.equities.enabled
    assert config.equities.long_only
    assert not any(
        (
            config.equities.margin_allowed,
            config.equities.short_sales_allowed,
            config.equities.options_allowed,
            config.equities.leveraged_etfs_allowed,
            config.equities.inverse_etfs_allowed,
            config.equities.otc_allowed,
            config.equities.microcaps_allowed,
        )
    )
    assert config.equities.max_spread_pct == Decimal("0.35")
    assert config.equities.minimum_price_usd == Decimal("5")
    assert config.equities.minimum_average_daily_dollar_volume_usd == Decimal("50000000")
    assert config.equities.avoid_new_entry_before_earnings_trading_days == 2
    assert config.equities.avoid_new_entry_after_earnings_trading_days == 1
    assert config.crypto.enabled
    assert config.crypto.max_total_crypto_exposure_pct == Decimal("20")
    assert config.crypto.max_single_crypto_exposure_pct == Decimal("10")
    assert config.crypto.initial_symbol_allowlist == ("BTC-USD", "ETH-USD")
    assert config.crypto.max_spread_pct == Decimal("0.60")
    assert not config.crypto.leverage_allowed
    assert config.prediction_markets.simulation_enabled
    assert not config.prediction_markets.live_enabled
    assert config.prediction_markets.future_max_single_contract_risk_pct == Decimal("2")
    assert config.prediction_markets.future_max_total_exposure_pct == Decimal("10")


def test_operational_and_research_values_are_explicit_and_exact() -> None:
    config = load_backtest().config

    assert config.freshness.max_executable_quote_age_seconds == Decimal("5")
    assert config.freshness.max_account_snapshot_age_seconds == Decimal("30")
    assert config.freshness.max_broker_health_age_seconds == Decimal("30")
    assert config.freshness.max_broker_review_age_seconds == Decimal("30")
    assert config.freshness.max_preflight_age_seconds == Decimal("300")
    assert config.freshness.max_clock_drift_seconds == Decimal("2")
    assert config.authorization.activation_lifetime_seconds == 900
    assert config.authorization.live_lease_lifetime_seconds == 28800
    assert config.retry.read_attempts == 3
    assert config.retry.initial_backoff_seconds == Decimal("0.25")
    assert config.retry.max_backoff_seconds == Decimal("2")
    assert config.retry.write_attempts == 1
    assert config.scheduler.equity_reconciliation_cadence_seconds == 60
    assert config.scheduler.crypto_reconciliation_cadence_seconds == 60
    assert config.promotion.paper_min_eligible_unique_cycles == 100
    assert config.promotion.shadow_min_calendar_days == 7
    assert config.promotion.micro_order_review_interval == 10
    assert config.promotion.normal_min_combined_calendar_days == 30
    assert config.promotion.normal_min_valid_observations == 100
    assert config.backup.cadence_seconds == 86400
    assert config.backup.retention_daily_archives == 30
    assert config.monitoring.host == "127.0.0.1"
    assert config.monitoring.port == 8080
    assert not config.monitoring.container_loopback_publish
    assert not config.llm_reporting.enabled
    assert config.llm_reporting.daily_token_budget > 0
    assert config.llm_reporting.monthly_token_budget >= config.llm_reporting.daily_token_budget
    assert config.llm_reporting.timeout_seconds > 0
    assert config.equity_strategies.short_windows == (20, 30, 50)
    assert config.equity_strategies.long_windows == (100, 150, 200)
    assert config.equity_strategies.regime_multipliers == (
        Decimal("1"),
        Decimal("0.5"),
        Decimal("0"),
    )
    assert [item.value for item in config.market_data.canonical_bar_intervals] == [
        "one_minute",
        "five_minute",
        "one_hour",
        "four_hour",
        "one_day",
    ]
    assert config.equity_strategies.bar_interval.value == "one_day"
    assert [item.value for item in config.crypto_strategies.bar_intervals] == [
        "four_hour",
        "one_day",
    ]
    assert config.research.seed == 20260710
    assert config.prediction_research.seed == 20260710
    assert config.equities.reconciliation_quantity_tolerance == 0
    assert config.crypto.reconciliation_quantity_tolerance == 0
    assert not config.research.assumptions_validated
    assert not config.research.evidence_promotable
    assert not config.simulation.assumptions_validated
    assert not config.simulation.evidence_promotable


def test_prediction_live_is_always_false() -> None:
    with pytest.raises(ValidationError):
        PredictionSettings(
            simulation_enabled=True,
            live_enabled=True,
            future_max_single_contract_risk_pct=Decimal("2"),
            future_max_total_exposure_pct=Decimal("10"),
        )


def test_null_and_invalid_scalar_types_fail() -> None:
    config = load_backtest().config
    raw = config.model_dump()
    raw["portfolio"]["max_open_positions"] = None
    with pytest.raises(ValidationError):
        type(config).model_validate(raw)


@pytest.mark.parametrize("nonfinite", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_nonfinite_decimal_is_rejected_everywhere(nonfinite: Decimal) -> None:
    config = load_backtest().config
    raw = config.model_dump()
    raw["costs"]["assumed_equity_spread_pct"] = nonfinite

    with pytest.raises(ValidationError):
        type(config).model_validate(raw)


def test_nonfinite_decimal_in_tuple_is_rejected() -> None:
    config = load_backtest().config
    raw = config.model_dump()
    raw["equity_strategies"]["regime_multipliers"] = [Decimal("1"), Decimal("NaN")]

    with pytest.raises(ValidationError):
        type(config).model_validate(raw)

    raw = config.model_dump()
    raw["runtime"]["start_paused"] = "sometimes"
    with pytest.raises(ValidationError):
        type(config).model_validate(raw)
