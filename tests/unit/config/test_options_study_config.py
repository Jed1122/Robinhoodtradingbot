"""Study settings extend the canonical graph without granting trading authority."""

from pathlib import Path

import pytest

from trading_bot.config import load_config
from trading_bot.config.loader import enforce_safety_envelope
from trading_bot.config.models import SafetyEnvelope

ROOT = Path("configs")


def load(environ=None, profile="options/study/simulation.yaml"):
    if not (ROOT / profile).exists():
        pytest.fail("options study profile is not implemented")
    return load_config(
        ROOT / "base.yaml", ROOT / profile, ROOT / "safety-envelope.yaml", environ or {}
    )


def test_study_profile_is_explicit_offline_only():
    loaded = load()
    study = loaded.config.options.research_study
    assert study.enabled
    assert study.confidence_level_pct == 95
    assert study.exit_policy == "signal_invalidation_or_prior_session_expiry"
    assert study.execution_enabled is False and study.evidence_promotable is False
    assert loaded.config.options.native_data.enabled
    assert loaded.config.options.research_shortlist.enabled
    assert loaded.config.runtime.start_paused
    assert not loaded.config.live_trading_enabled
    assert not loaded.config.equities.enabled and not loaded.config.crypto.enabled
    assert loaded.config.portfolio.expected_starting_equity_usd == 100
    assert loaded.config.position_risk.max_risk_per_trade_pct == pytest.approx(0.5)


@pytest.mark.parametrize(
    "profile",
    [
        "simulation.yaml",
        "paper.yaml",
        "options/simulation.yaml",
        "options/native-data/simulation.yaml",
    ],
)
def test_other_profiles_do_not_activate_study(profile):
    assert load(profile=profile).config.options.research_study.enabled is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("OPTIONS__RESEARCH_STUDY__CONFIDENCE_LEVEL_PCT", "0.95"),
        ("OPTIONS__RESEARCH_STUDY__CONFIDENCE_LEVEL_PCT", "94"),
        ("OPTIONS__RESEARCH_STUDY__CONFIDENCE_LEVEL_PCT", "100"),
        ("OPTIONS__RESEARCH_STUDY__CONFIDENCE_LEVEL_PCT", "true"),
        ("OPTIONS__RESEARCH_STUDY__EXECUTION_ENABLED", "true"),
        ("OPTIONS__RESEARCH_STUDY__EVIDENCE_PROMOTABLE", "true"),
        ("OPTIONS__RESEARCH_STUDY__EXIT_POLICY", "optimized_profit_target"),
        ("OPTIONS__NATIVE_DATA__ENABLED", "false"),
        ("OPTIONS__RESEARCH_SHORTLIST__ENABLED", "false"),
        ("MODE", "paper"),
        ("MODE", "shadow"),
        ("MODE", "live"),
        ("LIVE_TRADING_ENABLED", "true"),
        ("RUNTIME__START_PAUSED", "false"),
    ],
)
def test_study_cannot_weaken_boundaries(field, value):
    load()
    with pytest.raises(ValueError):
        load({"TRADING_BOT__" + field: value})


def test_confidence_may_tighten_and_release_envelope_can_disable():
    initial = load()
    stricter = load({"TRADING_BOT__OPTIONS__RESEARCH_STUDY__CONFIDENCE_LEVEL_PCT": "99"})
    assert stricter.config.options.research_study.confidence_level_pct == 99
    assert stricter.config_hash != initial.config_hash
    values = initial.safety_envelope.model_dump()
    values["options"]["research_study"]["confidence_level_pct"] = 99
    with pytest.raises(ValueError):
        enforce_safety_envelope(initial.config, SafetyEnvelope.model_validate(values))
    values["options"]["research_study"]["enabled"] = False
    with pytest.raises(ValueError):
        enforce_safety_envelope(stricter.config, SafetyEnvelope.model_validate(values))
