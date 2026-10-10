"""Literal declared training panels; no market evidence or risk authority."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from tests.unit.research.test_etf_capital_feasibility import CONFIGS, loaded
from trading_bot.research.etf_capital_signals import capital_candidates

CUTOFF = datetime(2019, 12, 31, 21, tzinfo=UTC)
SELECTION = CUTOFF + timedelta(days=30)


def panel():
    from trading_bot.research.etf_capital_selection import CapitalTrainingOutcome

    return tuple(
        CapitalTrainingOutcome(candidate, D(0), True, CUTOFF, "a" * 64)
        for candidate in capital_candidates()
    )


def select(records=None, **changes):
    from trading_bot.research.etf_capital_selection import select_capital_training

    args = dict(loaded=loaded(), capital=D(100), training_cutoff=CUTOFF, selection_at=SELECTION)
    return select_capital_training(records if records is not None else panel(), **(args | changes))


def test_cash_is_selected_when_complete_training_profits_are_nonpositive():
    value = select()
    assert value.selected is None
    assert value.selected_net_pnl == D(0)
    assert value.excluded == ()
    assert value.reason == "no_complete_positive_candidate"


def test_training_objective_selects_largest_positive_dollar_profit():
    records = list(panel())
    records[0] = replace(records[0], net_pnl=D(".10"))
    records[27] = replace(records[27], net_pnl=D(".20"))
    value = select(tuple(records))
    assert value.selected == capital_candidates()[27]
    assert value.selected_net_pnl == D(".20")


def test_ties_follow_frozen_grid_order_not_family_name_sort():
    records = tuple(replace(v, net_pnl=D(1)) for v in panel())
    assert select(records).selected == capital_candidates()[0]


def test_incomplete_outcomes_are_excluded_not_zero_or_profitable_marks():
    records = list(panel())
    records[0] = replace(records[0], net_pnl=None, complete=False)
    value = select(tuple(records))
    assert value.selected is None
    assert value.excluded == (capital_candidates()[0],)
    with pytest.raises(ValueError):
        select((replace(records[0], net_pnl=D(100)), *records[1:]))


def test_outcomes_later_than_training_cutoff_cannot_leak_into_selection():
    records = panel()
    with pytest.raises(ValueError):
        select((replace(records[0], last_outcome_at=CUTOFF + timedelta(seconds=1)), *records[1:]))
    with pytest.raises(ValueError):
        select(selection_at=CUTOFF)


def test_optimistic_cost_panel_cannot_claim_conservative_selection():
    records = panel()
    with pytest.raises(ValueError):
        select((replace(records[0], roundtrip_friction_pct=D(".05")), *records[1:]))


@pytest.mark.parametrize("shape", ("missing", "duplicate", "reversed", "list"))
def test_entire_frozen_panel_is_required_even_if_winner_appears_known(shape):
    records = panel()
    variants = {
        "missing": records[:-1],
        "duplicate": (records[1], *records[1:]),
        "reversed": records[::-1],
        "list": list(records),
    }
    with pytest.raises(ValueError):
        select(variants[shape])


@pytest.mark.parametrize("capital", (D(100), D(250), D(500), D(1000), D(5000), D(10000)))
def test_each_capital_is_an_independent_bound_identity(capital):
    value = select(capital=capital)
    assert value.capital == capital
    assert all(
        flag is False
        for flag in (
            value.source_qualified,
            value.cost_qualified,
            value.execution_enabled,
            value.economic_admitted,
            value.evidence_promotable,
        )
    )
    assert value.independent_opportunities is None


def test_panel_identity_binds_unknowns_capital_cutoff_and_every_losing_candidate():
    first = select()
    records = panel()
    changed = select((replace(records[0], net_pnl=D(-1)), *records[1:]))
    assert first.panel_hash != changed.panel_hash
    assert first.panel_hash != select(capital=D(250)).panel_hash
    assert first.panel_hash != select(training_cutoff=CUTOFF + timedelta(seconds=1)).panel_hash


@pytest.mark.parametrize("value", (D("NaN"), D("Infinity"), 1, True, D("1e600")))
def test_noncanonical_profit_cannot_rank_a_candidate(value):
    records = panel()
    with pytest.raises(ValueError):
        select((replace(records[0], net_pnl=value), *records[1:]))


@pytest.mark.parametrize(
    "field,value",
    (("complete", 1), ("input_hash", "bad"), ("last_outcome_at", CUTOFF.replace(tzinfo=None))),
)
def test_altered_training_declarations_fail_closed(field, value):
    records = panel()
    with pytest.raises(ValueError):
        select((replace(records[0], **{field: value}), *records[1:]))


def test_unsupported_capital_and_nonresearch_config_are_not_authority():
    from trading_bot.config import load_config

    with pytest.raises(ValueError):
        select(capital=D(101))
    with pytest.raises(ValueError):
        select(
            loaded=load_config(
                CONFIGS / "base.yaml",
                CONFIGS / "simulation.yaml",
                CONFIGS / "safety-envelope.yaml",
                {},
            )
        )


@pytest.mark.parametrize("copy_raises", (False, True))
def test_outcome_hash_uses_the_normalized_utc_instant_not_a_timezone_copy_hook(copy_raises):
    from datetime import timezone, tzinfo

    class DeclaredUtc(tzinfo):
        def utcoffset(self, dt):
            return timedelta(0)

        def dst(self, dt):
            return timedelta(0)

        def __deepcopy__(self, memo):
            if copy_raises:
                raise TypeError("timezone-copy-must-not-run")
            return timezone(timedelta(hours=1))

    records = panel()
    changed = tuple(
        replace(row, last_outcome_at=CUTOFF.replace(tzinfo=DeclaredUtc())) for row in records
    )
    assert select(changed) == select(records)
