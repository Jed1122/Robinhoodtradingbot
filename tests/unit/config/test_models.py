"""Validation tests for the single canonical configuration graph."""

from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from trading_bot.config import (
    AppConfig,
    LoadedConfig,
    MonitoringSettings,
    PredictionSettings,
    RetrySettings,
    SafetyEnvelope,
    UnsafeConfiguration,
    enforce_safety_envelope,
    load_config,
)
from trading_bot.config.models import StrictModel

ROOT = Path(__file__).parents[3]
CONFIGS = ROOT / "configs"


def load_backtest() -> LoadedConfig:
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
        config.portfolio.max_open_positions = 10

    for value in config.__dict__.values():
        if hasattr(value, "model_config"):
            assert value.model_config["extra"] == "forbid"
            assert value.model_config["frozen"] is True
            assert value.model_config["allow_inf_nan"] is False
            assert value.model_config["hide_input_in_errors"] is True


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


def test_logging_event_bound_is_required_strict_and_owned_by_the_release_envelope() -> None:
    loaded = load_backtest()
    config = loaded.config
    envelope = loaded.safety_envelope

    assert config.logging.max_event_bytes == 65536
    assert envelope.logging.max_event_bytes == 65536

    raw = config.model_dump()
    del raw["logging"]
    with pytest.raises(ValidationError):
        AppConfig.model_validate(raw)

    for invalid in (True, "65536", 1):
        raw = config.model_dump()
        raw["logging"]["max_event_bytes"] = invalid
        with pytest.raises(ValidationError):
            AppConfig.model_validate(raw)

    tighter = config.model_copy(update={"logging": type(config.logging)(max_event_bytes=32768)})
    enforce_safety_envelope(tighter, envelope)

    weaker = config.model_copy(update={"logging": type(config.logging)(max_event_bytes=65537)})
    with pytest.raises(UnsafeConfiguration, match=r"logging\.max_event_bytes"):
        enforce_safety_envelope(weaker, envelope)


@pytest.mark.parametrize(
    ("host", "container_loopback_publish", "accepted"),
    (
        ("127.0.0.1", False, True),
        ("0.0.0.0", True, True),
        ("0.0.0.0", False, False),
        ("192.0.2.1", True, False),
    ),
)
def test_monitoring_bind_policy_requires_verified_loopback_publication(
    host: str,
    container_loopback_publish: bool,
    accepted: bool,
) -> None:
    values = {
        "host": host,
        "port": 8080,
        "container_loopback_publish": container_loopback_publish,
        "webhook_attempts": 1,
        "webhook_timeout_seconds": Decimal("1"),
        "alert_deduplication_window_seconds": 0,
    }

    if accepted:
        assert MonitoringSettings.model_validate(values).host == host
    else:
        with pytest.raises(ValidationError, match="monitoring must bind loopback"):
            MonitoringSettings.model_validate(values)


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
    assert config.equity_strategies.research_universe_symbols == (
        "SPY",
        "QQQ",
        "IWM",
        "DIA",
    )
    assert config.equity_strategies.research_candidate_strategy_ids == (
        "equity_momentum",
        "equity_relative_strength",
    )
    assert config.equity_strategies.research_relative_strength_top_n == (1, 2)
    assert config.equity_strategies.research_rebalance_bars == 5
    assert config.equity_strategies.research_unselected_symbols_exit_to_cash
    assert config.equity_strategies.research_benchmark_symbol == "SPY"
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
    assert config.research.history_calendar_days == 3650
    assert config.research.minimum_history_bars == 750
    assert config.research.minimum_test_bars_per_fold == 50
    assert config.research.minimum_independent_opportunities == 30
    assert config.research.maximum_stressed_drawdown_pct == Decimal("10")
    assert config.research.minimum_positive_walk_forward_folds == 3
    assert config.prediction_research.seed == 20260710
    assert config.equities.reconciliation_quantity_tolerance == 0
    assert config.crypto.reconciliation_quantity_tolerance == 0
    assert not config.research.assumptions_validated
    assert not config.research.evidence_promotable
    assert not config.simulation.assumptions_validated
    assert not config.simulation.evidence_promotable


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("equity_strategies", "research_universe_symbols"), []),
        (
            ("equity_strategies", "research_universe_symbols"),
            ["SPY", "SPY"],
        ),
        (
            ("equity_strategies", "research_universe_symbols"),
            ["spy", "QQQ"],
        ),
        (
            ("equity_strategies", "research_candidate_strategy_ids"),
            ["equity_mean_reversion"],
        ),
        (
            ("equity_strategies", "research_candidate_strategy_ids"),
            ["equity_momentum", "equity_momentum"],
        ),
        (
            ("equity_strategies", "research_relative_strength_top_n"),
            [1, 5],
        ),
    ),
)
def test_equity_research_scope_rejects_invalid_values(
    path: tuple[str, ...],
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate(_with_config_value(path, value))


def test_prediction_live_is_always_false() -> None:
    with pytest.raises(ValidationError):
        PredictionSettings(
            simulation_enabled=True,
            live_enabled=True,  # type: ignore[arg-type]
            future_max_single_contract_risk_pct=Decimal("2"),
            future_max_total_exposure_pct=Decimal("10"),
        )


def _with_config_value(path: tuple[str, ...], value: Any) -> dict[str, Any]:
    raw = load_backtest().config.model_dump()
    target = raw
    for part in path[:-1]:
        nested = target[part]
        assert isinstance(nested, dict)
        target = cast(dict[str, Any], nested)
    target[path[-1]] = value
    return raw


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("portfolio", "max_open_positions"), True),
        (("portfolio", "max_open_positions"), "5"),
        (("live_trading_enabled",), 0),
        (("live_trading_enabled",), 1),
        (("live_trading_enabled",), "false"),
        (("position_risk", "averaging_down_allowed"), 0),
        (("position_risk", "averaging_down_allowed"), "false"),
        (("equities", "long_only"), 1),
        (("retry", "write_attempts"), True),
        (("equity_strategies", "short_windows"), ("20", 30, 50)),
    ],
)
def test_integer_boolean_and_literal_boundaries_reject_coercion(
    path: tuple[str, ...], value: Any
) -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate(_with_config_value(path, value))


def test_native_integer_and_boolean_values_remain_accepted() -> None:
    raw = _with_config_value(("portfolio", "max_open_positions"), 4)
    raw["live_trading_enabled"] = False
    raw["position_risk"]["averaging_down_allowed"] = False
    raw["equities"]["long_only"] = True

    config = AppConfig.model_validate(raw)

    assert config.portfolio.max_open_positions == 4
    assert config.live_trading_enabled is False
    assert config.position_risk.averaging_down_allowed is False
    assert config.equities.long_only is True


def test_integer_literal_rejects_boolean_equivalent() -> None:
    with pytest.raises(ValidationError):
        RetrySettings(
            read_attempts=3,
            initial_backoff_seconds=Decimal("0.25"),
            max_backoff_seconds=Decimal("2"),
            write_attempts=True,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("invalid", [0.5, "0.5", True])
def test_decimal_boundary_rejects_float_string_and_bool(invalid: object) -> None:
    raw = _with_config_value(("position_risk", "max_risk_per_trade_pct"), invalid)

    with pytest.raises(ValidationError):
        AppConfig.model_validate(raw)


@pytest.mark.parametrize("valid", [Decimal("0.5"), 1])
def test_decimal_boundary_accepts_decimal_and_exact_non_bool_integer(valid: object) -> None:
    raw = _with_config_value(("position_risk", "max_risk_per_trade_pct"), valid)

    config = AppConfig.model_validate(raw)

    assert isinstance(valid, (Decimal, int))
    assert type(config.position_risk.max_risk_per_trade_pct) is Decimal
    assert config.position_risk.max_risk_per_trade_pct == Decimal(valid)


@pytest.mark.parametrize("invalid", [0.5, "0.5", True])
def test_decimal_tuple_members_reject_coercion(invalid: object) -> None:
    raw = _with_config_value(
        ("equity_strategies", "regime_multipliers"),
        (Decimal("1"), invalid, Decimal("0")),
    )

    with pytest.raises(ValidationError):
        AppConfig.model_validate(raw)


@pytest.mark.parametrize(
    "invalid",
    [
        {"BTC-USD", "ETH-USD"},
        frozenset({"BTC-USD", "ETH-USD"}),
        iter(("BTC-USD", "ETH-USD")),
    ],
)
def test_tuple_containers_reject_unordered_and_one_shot_iterables(invalid: object) -> None:
    raw = _with_config_value(("crypto", "initial_symbol_allowlist"), invalid)

    with pytest.raises(ValidationError):
        AppConfig.model_validate(raw)


def test_tuple_containers_accept_native_list_and_tuple() -> None:
    raw = _with_config_value(("crypto", "initial_symbol_allowlist"), ["BTC-USD", "ETH-USD"])
    raw["equity_strategies"]["short_windows"] = (20, 30, 50)

    config = AppConfig.model_validate(raw)

    assert config.crypto.initial_symbol_allowlist == ("BTC-USD", "ETH-USD")
    assert config.equity_strategies.short_windows == (20, 30, 50)


def test_enum_tuple_members_reject_bytes_coercion() -> None:
    config_raw = _with_config_value(("market_data", "canonical_bar_intervals"), [b"one_minute"])
    envelope_raw = load_backtest().safety_envelope.model_dump()
    envelope_raw["allowed_modes"] = [b"backtest"]

    with pytest.raises(ValidationError):
        AppConfig.model_validate(config_raw)
    with pytest.raises(ValidationError):
        SafetyEnvelope.model_validate(envelope_raw)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("mode",), b"backtest"),
        (("equity_strategies", "bar_interval"), b"one_day"),
    ],
)
def test_enum_scalar_members_reject_bytes_coercion(path: tuple[str, ...], value: object) -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate(_with_config_value(path, value))


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
