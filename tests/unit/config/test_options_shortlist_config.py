"""Offline shortlist activation cannot escape the canonical release policy."""

from pathlib import Path

import pytest

from trading_bot.config import LoadedConfig, load_config

ROOT = Path("configs")


def load(
    environ: dict[str, str] | None = None, profile: str = "options/shortlist/simulation.yaml"
) -> LoadedConfig:
    return load_config(
        ROOT / "base.yaml", ROOT / profile, ROOT / "safety-envelope.yaml", environ or {}
    )


def test_explicit_profile_enables_only_research_and_preserves_risk() -> None:
    loaded = load()
    settings = loaded.config.options.research_shortlist
    assert settings.enabled is True
    assert (settings.min_dte, settings.target_dte, settings.max_dte) == (21, 30, 45)
    assert (settings.max_input_records, settings.max_input_bytes) == (25000, 16777216)
    assert (settings.max_json_depth, settings.max_decision_sessions) == (16, 1)
    assert loaded.config.options.live_supported is False
    assert loaded.config.options.max_per_trade_loss_usd == 50
    assert loaded.config.options.cumulative_trial_loss_limit_usd == 50
    assert loaded.config.position_risk.max_risk_per_trade_pct == pytest.approx(0.5)
    assert loaded.config.runtime.start_paused is True


def test_ordinary_simulation_remains_shortlist_disabled() -> None:
    assert (
        load(profile="options/simulation.yaml").config.options.research_shortlist.enabled is False
    )


@pytest.mark.parametrize("mode", ["paper", "shadow", "micro_live", "live"])
def test_operating_modes_cannot_enable_shortlist(mode: str) -> None:
    with pytest.raises(ValueError):
        load({"TRADING_BOT__MODE": mode})


@pytest.mark.parametrize(
    "field,value",
    [
        ("MIN_DTE", "20"),
        ("TARGET_DTE", "31"),
        ("MAX_DTE", "46"),
        ("MAX_INPUT_RECORDS", "25001"),
        ("MAX_INPUT_BYTES", "16777217"),
        ("MAX_JSON_DEPTH", "17"),
        ("MAX_DECISION_SESSIONS", "2"),
        ("MAX_INPUT_RECORDS", "true"),
        ("MAX_INPUT_BYTES", "16.0"),
        ("MAX_INPUT_RECORDS", "0"),
        ("MAX_INPUT_BYTES", "-1"),
        ("UNDERLYING", "QQQ"),
        ("VERSION", "custom-v2"),
        ("REFERENCE", "current_price"),
        ("STRIKE_TIE", "higher_strike"),
        ("EXPIRY_TIE", "later_expiry"),
    ],
)
def test_policy_and_ceiling_overrides_denied(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        load({f"TRADING_BOT__OPTIONS__RESEARCH_SHORTLIST__{field}": value})


def test_tighter_resources_change_config_identity() -> None:
    before = load()
    after = load({"TRADING_BOT__OPTIONS__RESEARCH_SHORTLIST__MAX_INPUT_RECORDS": "100"})
    assert after.config.options.research_shortlist.max_input_records == 100
    assert before.config_hash != after.config_hash


def test_disabled_options_cannot_enable_shortlist() -> None:
    with pytest.raises(ValueError):
        load({"TRADING_BOT__OPTIONS__ENABLED": "false"})
