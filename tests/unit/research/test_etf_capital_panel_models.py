"""Strict compact identities; these records never authenticate caller outcomes."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_selection import CapitalTrainingOutcome
from trading_bot.research.etf_capital_signals import capital_candidates


def training(**changes):
    from trading_bot.research.etf_capital_panel_models import CapitalPanelTraining

    candidate = capital_candidates()[0]
    outcome = CapitalTrainingOutcome(
        candidate, D(".11"), True, datetime(2020, 1, 1, tzinfo=UTC), "a" * 64
    )
    values = (candidate, outcome, "a" * 64, "b" * 64, "c" * 64, 750, 10)
    identity = content_hash(("capital-panel-training-v1", *values, (False,) * 5))
    return replace(CapitalPanelTraining(*values, identity), **changes)


def test_original_training_identity_retains_full_result_and_is_immutable():
    # Dropping original trajectory/account/risk lineage or changing PNL must fail.
    value = training()
    assert value.trajectory_hash == value.outcome.input_hash == "a" * 64
    assert value.final_account_hash == "b" * 64
    assert value.final_risk_hash == "c" * 64
    assert value.point_count == 750 and value.event_count == 10
    assert value.outcome.net_pnl == D(".11")
    assert all(
        getattr(value, key) is False
        for key in (
            "source_qualified",
            "cost_qualified",
            "execution_enabled",
            "economic_admitted",
            "evidence_promotable",
        )
    )
    with pytest.raises(FrozenInstanceError):
        value.point_count = 1
    with pytest.raises(ValueError, match="capital_economic_panel_invalid"):
        training(final_account_hash="d" * 64)


@pytest.mark.parametrize(
    "key,value",
    (
        ("point_count", True),
        ("event_count", -1),
        ("trajectory_hash", "A" * 64),
        ("input_hash", "0" * 64),
    ),
)
def test_tampered_training_record_denies_before_adoption(key, value):
    with pytest.raises(ValueError, match="capital_economic_panel_invalid"):
        training(**{key: value})


def test_rehashed_wrong_candidate_and_complete_pnl_cannot_be_retained():
    from trading_bot.research.etf_capital_panel_models import CapitalPanelTraining

    original = training()
    for candidate, outcome in (
        (capital_candidates()[1], original.outcome),
        (original.candidate, replace(original.outcome, complete=False)),
        (original.candidate, replace(original.outcome, input_hash="d" * 64)),
    ):
        values = (
            candidate,
            outcome,
            original.trajectory_hash,
            original.final_account_hash,
            original.final_risk_hash,
            750,
            10,
        )
        identity = content_hash(("capital-panel-training-v1", *values, (False,) * 5))
        with pytest.raises(ValueError, match="capital_economic_panel_invalid"):
            CapitalPanelTraining(*values, identity)


def test_output_subclasses_and_mutated_inherited_flags_are_not_authority():
    from trading_bot.research.etf_capital_panel_models import CapitalPanelTraining

    class Counterfeit(CapitalPanelTraining):
        pass

    value = training()
    with pytest.raises(ValueError, match="capital_economic_panel_invalid"):
        Counterfeit(
            value.candidate,
            value.outcome,
            value.trajectory_hash,
            value.final_account_hash,
            value.final_risk_hash,
            750,
            10,
            value.input_hash,
        )
    object.__setattr__(value, "execution_enabled", True)
    with pytest.raises(ValueError, match="capital_economic_panel_invalid"):
        value.__post_init__()


def test_conditional_rejection_does_not_remove_unknown_independence():
    from trading_bot.research.etf_capital_panel_models import (
        CapitalPanelCriterion,
        CapitalPanelDecision,
    )

    criteria = []
    for key, status, value, threshold in (
        ("observed_operating_positive", "fails_declared_screen", D(-1), D(0)),
        ("positive_folds", "unknown", None, D(3)),
        ("stress_drawdown", "unknown", None, D(10)),
        ("observed_benchmark_excess", "unknown", None, D(0)),
        ("conditional_lower_bounds", "unknown", None, D(0)),
        ("conditional_loss_probability", "unknown", None, D(50)),
        ("independent_opportunities", "unknown", None, D(30)),
        ("independent_profit_concentration", "unknown", None, D(50)),
        ("net_expectancy_support", "unknown", None, D(0)),
        ("adaptive_selection_coverage", "unknown", None, D(95)),
    ):
        values = (key, status, value, threshold, "declared screen only", ("a" * 64,))
        criteria.append(
            CapitalPanelCriterion(
                *values, content_hash(("capital-panel-criterion-v1", *values, (False,) * 5))
            )
        )
    values = (D(100), 0, tuple(criteria), "REJECT")
    result = CapitalPanelDecision(
        *values, content_hash(("capital-panel-decision-v1", *values, (False,) * 5))
    )
    assert result.verdict == "REJECT"
    assert result.criteria[6].value is None and result.criteria[6].threshold == 30
    with pytest.raises(ValueError, match="capital_economic_panel_invalid"):
        replace(result, verdict="GO")


def test_label_constructor_rejects_bool_as_path_index():
    from trading_bot.research.etf_capital_panel_models import CapitalPanelLabel

    with pytest.raises(ValueError, match="capital_economic_panel_invalid"):
        CapitalPanelLabel(D(100), D(".05"), False, "cash")


def test_rehashed_family_cannot_hide_malformed_column_identity():
    from tests.unit.research.test_etf_capital_panel import family_inputs
    from trading_bot.research.etf_capital_panel import _build_family
    from trading_bot.research.etf_capital_panel_models import CapitalPanelFamily

    dates, capitals, costs, labels, columns = family_inputs()
    value = _build_family(
        "trading",
        dates,
        labels,
        columns,
        capitals=capitals,
        frictions=costs,
        seed=20260710,
        draws=1,
    )
    hashes = ("not-a-sha256", *value.column_hashes[1:])
    fields = (value.kind, dates, labels, columns, hashes, value.bands)
    with pytest.raises(ValueError, match="capital_economic_panel_invalid"):
        CapitalPanelFamily(
            *fields, content_hash(("capital-panel-family-v1", *fields, (False,) * 5))
        )
