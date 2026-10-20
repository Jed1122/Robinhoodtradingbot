"""Observed records have distinct identities and reject mixed variant graphs."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest

from tests.unit.research.test_etf_capital_panel_models import training as legacy_training
from trading_bot.market_data.recording import content_hash
from trading_bot.research import etf_capital_panel_models as models
from trading_bot.research.etf_capital_selection import (
    CapitalTrainingOutcome,
    CapitalTrainingSelection,
)
from trading_bot.research.etf_capital_signals import CapitalWalkForwardFold, capital_candidates


def observed_training(*, count=252, tag="observed-training", candidate=None, outcome=None):
    cls = getattr(models, "CapitalObservedPanelTraining", None)
    assert cls is not None, "observed training record is missing"
    selected = capital_candidates()[0]
    fact = CapitalTrainingOutcome(
        selected, D(".11"), True, datetime(2023, 1, 3, tzinfo=UTC), "a" * 64
    )
    values = (
        selected if candidate is None else candidate,
        fact if outcome is None else outcome,
        "a" * 64,
        "b" * 64,
        "c" * 64,
        count,
        10,
    )
    return cls(*values, content_hash(("capital-panel-" + tag + "-v1", *values, (False,) * 5)))


def test_observed_training_requires_252_real_points_and_a_distinct_namespace():
    result = observed_training()
    assert result.point_count == 252 and result.event_count == 10
    assert result.trajectory_hash == result.outcome.input_hash == "a" * 64
    for count in (750, 251, True):
        with pytest.raises(ValueError):
            observed_training(count=count)
    with pytest.raises(ValueError):
        observed_training(tag="training")
    with pytest.raises(ValueError):
        models._typed(result, models.CapitalPanelTraining)
    assert (
        legacy_training().input_hash
        == "197adc3998c5e96c327b0686caaf6d7361148278481adfe06d557080937be9ab"
    )


def test_observed_training_rehashed_bad_outcome_and_mutated_flags_are_denied():
    value = observed_training()
    for change in (
        dict(complete=False),
        dict(input_hash="e" * 64),
        dict(roundtrip_friction_pct=D(".05")),
    ):
        with pytest.raises(ValueError):
            observed_training(outcome=replace(value.outcome, **change))
    with pytest.raises(ValueError):
        observed_training(candidate=capital_candidates()[1])
    object.__setattr__(value, "execution_enabled", True)
    with pytest.raises(ValueError):
        value.__post_init__()


def test_observed_fold_rejects_rehashed_legacy_training_and_unknown_subclasses():
    item = observed_training()
    cls = models.CapitalObservedPanelFold
    day = date(2023, 1, 3)
    fold = CapitalWalkForwardFold((day,), (day,), (), (), ())
    # Schema-only record test: whole schedule/selection admission is the assembler's job.
    selection = CapitalTrainingSelection(D(100), None, D(0), (), "schema_fixture", "d" * 64)
    values = (
        fold,
        datetime(2023, 1, 3, tzinfo=UTC),
        datetime(2023, 1, 4, tzinfo=UTC),
        (item,),
        selection,
    )
    record = cls(*values, content_hash(("capital-panel-observed-fold-v1", *values, (False,) * 5)))
    assert record.training == (item,)
    mixed = (*values[:3], (legacy_training(),), values[-1])
    with pytest.raises(ValueError):
        cls(*mixed, content_hash(("capital-panel-observed-fold-v1", *mixed, (False,) * 5)))
    with pytest.raises(ValueError):
        models._typed(record, models.CapitalPanelFold)

    class Forged(type(item)):
        pass

    with pytest.raises(ValueError):
        Forged(*models._values(item), item.input_hash)


def test_observed_graph_schemas_do_not_admit_legacy_scenarios_paths_or_families():
    observed_training()
    expected = {
        models.CapitalObservedPanelFold: {
            "training": tuple[models.CapitalObservedPanelTraining, ...]
        },
        models.CapitalObservedPanelScenario: {
            "folds": tuple[models.CapitalObservedPanelFold, ...],
            "paths": tuple[models.CapitalObservedPanelPath, ...],
        },
        models.CapitalObservedEconomicPanelReport: {
            "scenarios": tuple[models.CapitalObservedPanelScenario, ...],
            "trading": models.CapitalObservedPanelFamily,
        },
    }
    # Exercise the field type boundary, not source text. Legacy typed instances
    # fail immediately, before their uninitialized content can be read.
    pairs = {
        models.CapitalObservedPanelTraining: models.CapitalPanelTraining,
        models.CapitalObservedPanelFold: models.CapitalPanelFold,
        models.CapitalObservedPanelPath: models.CapitalPanelPath,
        models.CapitalObservedPanelScenario: models.CapitalPanelScenario,
        models.CapitalObservedPanelFamily: models.CapitalPanelFamily,
    }
    for schema, fields in expected.items():
        hints = models._hints(schema)
        for name, wanted in fields.items():
            assert hints[name] == wanted
    for new, old in pairs.items():
        with pytest.raises(ValueError):
            models._typed(object.__new__(old), new)
