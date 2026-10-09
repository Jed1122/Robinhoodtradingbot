"""Opt-in capital research cannot change legacy evidence or trading authority."""

from decimal import Decimal
from pathlib import Path

import pytest

from trading_bot.config import ConfigLoadError, load_config
from trading_bot.config.loader import restore_loaded_config
from trading_bot.domain import ExecutionMode

CONFIGS = Path(__file__).resolve().parents[3] / "configs"


def capital_loaded(*, mode_path=None, policy_path=None, environ=None):
    return load_config(
        CONFIGS / "base.yaml",
        mode_path or CONFIGS / "etf/capital/simulation.yaml",
        CONFIGS / "safety-envelope.yaml",
        environ or {},
        research_policy_path=policy_path or CONFIGS / "etf/capital/policy.yaml",
    )


def test_capital_policy_is_opt_in_and_offline():
    loaded = capital_loaded()
    policy = loaded.config.capital_research
    assert policy.capital_tiers == tuple(map(Decimal, (100, 250, 500, 1000, 5000, 10000)))
    assert policy.universe == ("SPY", "QQQ", "IWM", "SHY", "IEF")
    assert policy.position_risk.max_position_notional_pct == Decimal("20")
    assert policy.position_risk.max_risk_per_trade_pct == Decimal("0.5")
    assert policy.loss_limits.max_daily_loss_pct == Decimal("1")
    assert policy.min_cash_reserve_pct == Decimal("40")
    assert policy.max_open_positions == 1
    assert loaded.config.mode is ExecutionMode.SIMULATION
    assert loaded.config.live_trading_enabled is False
    assert loaded.config.runtime.start_paused is True
    assert loaded.config.crypto.enabled is False
    assert loaded.config.prediction_markets.simulation_enabled is False
    assert loaded.config.activity.max_order_notional_usd == Decimal("15")
    assert loaded.config.portfolio.live_account_equity_ceiling_usd == Decimal("1000")
    assert policy.execution_enabled is False and policy.evidence_promotable is False


def test_capital_graph_restores_through_existing_decoder():
    loaded = capital_loaded()
    restored = restore_loaded_config(loaded.canonical_json, loaded.config_hash)
    assert restored == loaded
    assert type(restored.config) is type(loaded.config)


@pytest.mark.parametrize("mode", ["paper", "shadow", "micro_live", "normal_live"])
def test_capital_profile_cannot_be_used_for_execution(mode):
    with pytest.raises(ConfigLoadError):
        capital_loaded(mode_path=CONFIGS / f"{mode}.yaml")


@pytest.mark.parametrize(
    "environ",
    [
        {"LIVE_TRADING_ENABLED": "true"},
        {"TRADING_BOT__RUNTIME__START_PAUSED": "false"},
        {"TRADING_BOT__CAPITAL_RESEARCH__MIN_CASH_RESERVE_PCT": "0"},
    ],
)
def test_research_profile_rejects_environment_overrides(environ):
    with pytest.raises(ConfigLoadError):
        capital_loaded(environ=environ)


def test_policy_cannot_expand_risk_or_enable_execution(tmp_path):
    original = (CONFIGS / "etf/capital/policy.yaml").read_text()
    for before, after in [
        ("max_risk_per_trade_pct: 0.50", "max_risk_per_trade_pct: 0.51"),
        ("max_position_notional_pct: 20", "max_position_notional_pct: 21"),
        ("min_cash_reserve_pct: 40", "min_cash_reserve_pct: 39"),
        ("execution_enabled: false", "execution_enabled: true"),
    ]:
        assert before in original
        path = tmp_path / "policy.yaml"
        path.write_text(original.replace(before, after))
        with pytest.raises(ConfigLoadError):
            capital_loaded(policy_path=path)


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("simulation", "3b578b00e91aa17ce92bd5b69d653b6ffa4fef00fdc54e49a4e16e2e6c632c0a"),
        ("backtest", "f1da8bc13c0d46d6dd7838f0dcaaa717e54b4e4cbb533dfb64947489d94f04db"),
        ("paper", "4daf2a6d9f6deafa1e0a75cbef8ba30e83f7dad995e3683e41e0273dc8d1ad16"),
        ("shadow", "26edaea0ed64ccf190d39ae2c4b9843de7cfc2bacc0b36d562a39b92874f3de4"),
    ],
)
def test_legacy_canonical_preimages_remain_literal(mode, expected):
    loaded = load_config(
        CONFIGS / "base.yaml", CONFIGS / f"{mode}.yaml", CONFIGS / "safety-envelope.yaml", {}
    )
    assert loaded.config_hash == expected
    assert "capital_research" not in type(loaded.config).model_fields
