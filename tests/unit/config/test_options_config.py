"""Options profile extends the one canonical loader without unlocking live modes."""

from decimal import Decimal
from pathlib import Path

import pytest

from trading_bot.config import ConfigLoadError, LoadedConfig, load_config

CONFIGS = Path(__file__).parents[3] / "configs"


def load_options(environ: dict[str, str] | None = None) -> LoadedConfig:
    return load_config(
        base_path=CONFIGS / "base.yaml",
        mode_path=CONFIGS / "options/simulation.yaml",
        safety_path=CONFIGS / "safety-envelope.yaml",
        environ=environ or {},
    )


def test_options_only_profile_preserves_percentage_and_nonreplenishing_trial_caps() -> None:
    loaded = load_options()
    config = loaded.config
    assert config.options.enabled
    assert not config.options.live_supported
    assert not config.equities.enabled
    assert not config.crypto.enabled
    assert not config.prediction_markets.simulation_enabled
    assert not config.live_trading_enabled
    assert config.runtime.start_paused
    assert config.position_risk.max_risk_per_trade_pct == Decimal("0.50")
    assert config.options.max_per_trade_loss_usd == Decimal("50")
    assert config.options.cumulative_trial_loss_limit_usd == Decimal("50")
    assert config.options.max_total_payoff_risk_pct == Decimal("5")
    assert config.options.max_underlying_group_payoff_risk_pct == Decimal("2")
    assert config.options.min_unencumbered_cash_pct == Decimal("80")
    assert config.options.max_open_strategy_positions == 1
    assert config.options.max_new_positions_per_session == 1
    assert config.options.max_structure_units_per_entry == 1


@pytest.mark.parametrize(
    ("leaf", "value"),
    [
        ("OPTIONS__LIVE_SUPPORTED", "true"),
        ("OPTIONS__MAX_TOTAL_PAYOFF_RISK_PCT", "6"),
        ("OPTIONS__MAX_UNDERLYING_GROUP_PAYOFF_RISK_PCT", "3"),
        ("OPTIONS__MIN_UNENCUMBERED_CASH_PCT", "79"),
        ("OPTIONS__CUMULATIVE_TRIAL_LOSS_LIMIT_USD", "51"),
        ("OPTIONS__MAX_PER_TRADE_LOSS_USD", "51"),
        ("OPTIONS__MAX_STRUCTURE_UNITS_PER_ENTRY", "2"),
        ("OPTIONS__MAX_OPEN_STRATEGY_POSITIONS", "2"),
        ("OPTIONS__MAX_NEW_POSITIONS_PER_SESSION", "2"),
        ("OPTIONS__ALLOW_LOCKED_QUOTES", "true"),
        ("OPTIONS__UNCOVERED_OPTIONS_ENABLED", "true"),
        ("OPTIONS__ZERO_DTE_LIVE_ENABLED", "true"),
        ("EQUITIES__ENABLED", "true"),
        ("CRYPTO__ENABLED", "true"),
        ("PREDICTION_MARKETS__SIMULATION_ENABLED", "true"),
        ("LIVE_TRADING_ENABLED", "true"),
        ("MODE", "micro_live"),
    ],
)
def test_options_profile_rejects_relaxed_or_live_overrides(leaf: str, value: str) -> None:
    with pytest.raises(ConfigLoadError):
        load_options({"TRADING_BOT__" + leaf: value})


def test_options_settings_are_hashed_and_can_only_tighten() -> None:
    baseline = load_options()
    tightened = load_options({"TRADING_BOT__OPTIONS__MAX_PER_TRADE_LOSS_USD": "25"})
    assert tightened.config_hash != baseline.config_hash
    assert tightened.config.options.max_per_trade_loss_usd == 25


@pytest.mark.parametrize(
    ("name", "lower", "upper"),
    [
        ("REPLAY_MAX_BYTES", "1024", "4194305"),
        ("REPLAY_MAX_RECORDS", "10", "5001"),
        ("REPLAY_MAX_JSON_DEPTH", "4", "17"),
    ],
)
def test_replay_resource_bounds_use_canonical_config_and_cannot_relax(
    name: str,
    lower: str,
    upper: str,
) -> None:
    baseline = load_options()
    tightened = load_options({"TRADING_BOT__OPTIONS__" + name: lower})
    assert tightened.config_hash != baseline.config_hash
    with pytest.raises(ConfigLoadError):
        load_options({"TRADING_BOT__OPTIONS__" + name: upper})
