"""Fixed research identity cannot become execution or rewrite prior policy."""

import hashlib
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from pathlib import Path

import pytest

from trading_bot.config import ConfigLoadError, load_config

CONFIGS = Path(__file__).parents[3] / "configs"
PREFIX = "TRADING_BOT__EQUITY_STRATEGIES__ETF_PILOT__"


def loaded(mode="backtest", **overrides):
    return load_config(
        CONFIGS / "base.yaml",
        CONFIGS / f"{mode}.yaml",
        CONFIGS / "safety-envelope.yaml",
        overrides,
    )


def freeze(**overrides):
    from trading_bot.research.etf_study import freeze_etf_study

    args = dict(
        code_hash="a" * 64,
        source_plan_hash="b" * 64,
        cost_plan_hash="c" * 64,
        holdout_previously_examined=False,
    )
    args.update(overrides)
    return freeze_etf_study(loaded(**{PREFIX + "ENABLED": "true"}), **args)


def test_fixed_study_is_separate_and_permanently_non_executable():
    baseline = loaded()
    assert baseline.config.equity_strategies.etf_pilot.enabled is False
    study = freeze()
    assert study.symbols == ("SPY",)
    assert study.windows == (20, 100)
    assert study.rebalance_sessions == 5
    assert study.risk_equity_reference == Decimal("100")
    assert study.capital_tiers == (Decimal("500"), Decimal("1000"))
    assert study.execution_enabled is False and study.evidence_promotable is False
    assert study.requested_start.isoformat() == "2016-01-01T00:00:00+00:00"
    assert study.requested_end.isoformat() == "2026-01-01T00:00:00+00:00"
    assert study.holdout_start.isoformat() == "2024-01-01T00:00:00+00:00"
    assert study.holdout_end == study.requested_end
    assert baseline.config.equity_strategies.research_universe_symbols == (
        "SPY",
        "QQQ",
        "IWM",
        "DIA",
    )
    for flag in ("execution_enabled", "evidence_promotable"):
        with pytest.raises((TypeError, ValueError), match="init=False"):
            replace(study, policy=loaded(**{PREFIX + "ENABLED": "true"}), **{flag: True})
    with pytest.raises(FrozenInstanceError):
        study.code_hash = "d" * 64


@pytest.mark.parametrize("mode", ["paper", "shadow", "micro_live", "live"])
def test_pilot_cannot_enable_inside_a_broker_runtime(mode):
    with pytest.raises(ConfigLoadError):
        loaded(mode, **{PREFIX + "ENABLED": "true"})


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("EXECUTION_ENABLED", "true"),
        ("EVIDENCE_PROMOTABLE", "true"),
        ("SHORT_WINDOW", "21"),
        ("SHORT_WINDOW", "true"),
        ("SYMBOL", "QQQ"),
        ("CAPITAL_TIERS", "[500, 1001]"),
        ("CAPITAL_TIERS", "[true, 1000]"),
        ("CAPITAL_TIERS", "[.nan, 1000]"),
        ("REQUESTED_START", "2018-01-01"),
        ("HOLDOUT_START", "2025-01-01"),
        ("UNKNOWN", "true"),
    ],
)
def test_fixed_policy_cannot_be_changed_to_make_a_study_pass(name, value):
    with pytest.raises(ConfigLoadError):
        loaded(**{PREFIX + name: value})


@pytest.mark.parametrize("name", ["code_hash", "source_plan_hash", "cost_plan_hash"])
def test_study_hash_binds_each_input_identity(name):
    assert freeze(**{name: "d" * 64}).study_hash != freeze().study_hash


@pytest.mark.parametrize("value", [True, "bad", "A" * 64, "a" * 40, None])
def test_invalid_evidence_identity_denies(value):
    with pytest.raises(ValueError):
        freeze(source_plan_hash=value)


def test_contamination_is_retained_and_changes_identity():
    study = freeze(holdout_previously_examined=True)
    assert "holdout_previously_examined" in study.non_promotability_reasons
    assert study.study_hash != freeze().study_hash
    assert not study.evidence_promotable
    with pytest.raises(ValueError):
        freeze(holdout_previously_examined=1)


def test_freeze_rejects_disabled_study_and_forged_config_identity():
    from trading_bot.research.etf_study import freeze_etf_study

    args = dict(
        code_hash="a" * 64,
        source_plan_hash="b" * 64,
        cost_plan_hash="c" * 64,
        holdout_previously_examined=False,
    )
    with pytest.raises(ValueError):
        freeze_etf_study(loaded(), **args)
    enabled = loaded(**{PREFIX + "ENABLED": "true"})
    with pytest.raises(ValueError):
        freeze_etf_study(replace(enabled, config_hash="d" * 64), **args)


def test_canonical_risk_changes_are_bound_not_replaced_by_starting_cash():
    from trading_bot.research.etf_study import freeze_etf_study

    safer = loaded(
        **{PREFIX + "ENABLED": "true", "TRADING_BOT__POSITION_RISK__MAX_RISK_PER_TRADE_PCT": "0.25"}
    )
    study = freeze_etf_study(
        safer,
        code_hash="a" * 64,
        source_plan_hash="b" * 64,
        cost_plan_hash="c" * 64,
        holdout_previously_examined=False,
    )
    assert study.study_hash != freeze().study_hash
    assert study.risk_equity_reference == Decimal("100")
    assert study.config_hash == safer.config_hash


def test_invalid_window_or_replaced_reference_denies():
    study = freeze()
    policy = loaded(**{PREFIX + "ENABLED": "true"})
    with pytest.raises(ValueError):
        replace(study, policy=policy, holdout_start=study.requested_start)
    with pytest.raises(ValueError):
        replace(study, policy=policy, risk_equity_reference=Decimal("1000"))


@pytest.mark.parametrize("supply_policy", [False, True])
@pytest.mark.parametrize("mutation", ["empty_preimage", "disabled_profile", "different_seed"])
def test_reconstructed_record_cannot_contradict_its_canonical_configuration(
    mutation,
    supply_policy,
):
    study = freeze()
    changes = {"seed": study.seed + 1}
    if mutation == "empty_preimage":
        changes = {"canonical_config": "{}", "config_hash": hashlib.sha256(b"{}").hexdigest()}
    elif mutation == "disabled_profile":
        disabled = loaded()
        changes = {
            "canonical_config": disabled.canonical_json.decode(),
            "config_hash": disabled.config_hash,
        }
    if supply_policy:
        changes["policy"] = loaded(**{PREFIX + "ENABLED": "true"})
    # 3.14 changed the standard-library missing-InitVar error to TypeError.
    errors = ValueError if supply_policy else (TypeError, ValueError)
    with pytest.raises(errors):
        replace(study, **changes)
    assert study.config_hash == loaded(**{PREFIX + "ENABLED": "true"}).config_hash


def test_reconstruction_rechecks_matching_but_disabled_loaded_policy():
    disabled = loaded()
    with pytest.raises(ValueError):
        replace(
            freeze(),
            policy=disabled,
            canonical_config=disabled.canonical_json.decode(),
            config_hash=disabled.config_hash,
        )
