"""Immutable monthly research registration cannot launder legacy/live evidence."""

import importlib
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.unit.config.test_etf_monthly_config import ID, monthly_loaded
from trading_bot.simulation.etf_history import _policy


def api():
    return importlib.import_module("trading_bot.research.etf_monthly_study")


def study(**changes):
    args = dict(
        code_hash="a" * 64,
        source_plan_hash="b" * 64,
        cost_plan_hash="c" * 64,
        operating_basis_hash="d" * 64,
        holdout_exposure="unknown",
    )
    args.update(changes)
    return api().freeze_etf_monthly_study(monthly_loaded(), **args)


def test_fixed_monthly_registration_and_separate_identity():
    s = study()
    assert s.policy_id == ID and s.risk_equity_reference == Decimal("100")
    assert s.capital_tiers == (Decimal("500"), Decimal("1000"))
    assert s.development_previously_examined is True and s.holdout_exposure == "unknown"
    assert s.requested_start == datetime(2016, 1, 1, tzinfo=UTC)
    assert s.requested_end == datetime(2024, 1, 1, tzinfo=UTC)
    assert s.source_requested_end == s.holdout_end == datetime(2026, 1, 1, tzinfo=UTC)
    assert s.holdout_start == s.requested_end
    assert api().monthly_policy(s) == monthly_loaded()
    assert len(s.study_hash) == 64
    with pytest.raises(ValueError):
        _policy(s)
    with pytest.raises(FrozenInstanceError):
        s.seed = 1


@pytest.mark.parametrize(
    "name", ["code_hash", "source_plan_hash", "cost_plan_hash", "operating_basis_hash"]
)
def test_study_identity_binds_each_plan(name):
    assert study(**{name: "e" * 64}).study_hash != study().study_hash
    with pytest.raises(ValueError):
        study(**{name: "secret"})


@pytest.mark.parametrize(
    "name,value",
    [
        ("seed", 1),
        ("risk_equity_reference", Decimal("1000")),
        ("requested_end", datetime(2026, 1, 1, tzinfo=UTC)),
        ("canonical_config", "{}"),
        ("config_hash", "0" * 64),
        ("holdout_exposure", "untouched"),
    ],
)
def test_monthly_graph_seed_risk_and_windows_cannot_be_forged(name, value):
    with pytest.raises(ValueError):
        replace(study(), **{name: value})


@pytest.mark.parametrize(
    "name",
    [
        "source_qualified",
        "cost_qualified",
        "execution_enabled",
        "economic_admitted",
        "evidence_promotable",
        "live_authorized",
        "development_previously_examined",
        "policy_id",
        "capital_tiers",
    ],
)
def test_mutated_registration_denies_reconstruction(name):
    s = study()
    assert s.source_qualified is s.cost_qualified is s.execution_enabled is False
    assert s.economic_admitted is s.evidence_promotable is s.live_authorized is False
    value = name != "development_previously_examined"
    object.__setattr__(s, name, value)
    with pytest.raises(ValueError):
        api().monthly_policy(s)


def test_disabled_and_forged_loaded_graphs_cannot_freeze():
    from tests.unit.research.test_etf_study import loaded

    s = study()
    for policy in (loaded(), replace(monthly_loaded(), config_hash="0" * 64)):
        with pytest.raises(ValueError):
            api().freeze_etf_monthly_study(
                policy,
                code_hash=s.code_hash,
                source_plan_hash=s.source_plan_hash,
                cost_plan_hash=s.cost_plan_hash,
                operating_basis_hash=s.operating_basis_hash,
                holdout_exposure="unknown",
            )
