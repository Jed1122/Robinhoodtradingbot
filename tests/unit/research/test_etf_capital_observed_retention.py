"""One real fabricated observed path, not a real-data economic evaluation."""

from decimal import Decimal as D

import pytest

from tests.unit.research.test_etf_capital_observed_prepared import observed_long_source
from tests.unit.simulation.test_etf_capital_observed_walk_forward import request
from trading_bot.market_data.etf_capital_owned import _own_capital_observed_source
from trading_bot.research.etf_capital_economic_window import _capital_economic_window
from trading_bot.research.etf_capital_matched import _capital_matched_values, _CapitalMatchedTerms
from trading_bot.research.etf_capital_panel import _CapitalPanelRetention, _retain_path
from trading_bot.research.etf_capital_panel_models import CapitalObservedPanelPath
from trading_bot.research.etf_capital_prepared import _prepare_owned_capital_days
from trading_bot.research.etf_capital_protocol import CapitalStudyProtocol
from trading_bot.research.etf_capital_signals import capital_candidates
from trading_bot.simulation.etf_capital_trajectory import (
    CapitalTrajectoryDay,
    _replay_prepared_capital_trajectory,
)
from trading_bot.simulation.etf_capital_walk_forward import _walk_forward_inputs

PROTOCOL = CapitalStudyProtocol("observed-252x84-v2")


@pytest.fixture(scope="module")
def original_path():
    source = observed_long_source(715)
    owned = _own_capital_observed_source(source)
    walk = request(source)
    terms, instruments, dates, _, _ = _walk_forward_inputs(walk, owned)
    prepared = _prepare_owned_capital_days(owned, sessions=dates)
    candidate = capital_candidates()[0]
    schedule = tuple(
        CapitalTrajectoryDay(day, candidate, index < 691, index < 692, True)
        for index, day in enumerate(dates[271:715], start=271)
    )
    trajectory = _replay_prepared_capital_trajectory(
        source=owned.dataset,
        source_hash=owned.source_hash,
        prepared=prepared,
        terms=terms,
        instruments=instruments,
        schedule=schedule,
    )
    matched_terms = _CapitalMatchedTerms(
        walk.initial_cash,
        walk.roundtrip_friction_pct,
        walk.entry_fee,
        walk.exit_fee,
    )
    return owned, prepared, dates, candidate, trajectory, matched_terms


def test_observed_path_projection_denies_legacy_protocol(original_path):
    owned, _, dates, candidate, trajectory, terms = original_path
    with pytest.raises(ValueError):
        _retain_path(
            trajectory,
            path_index=1,
            candidate=candidate,
            owned=owned,
            terms=terms,
            test_sessions=dates[272:692],
            recurring_usd_per_day=None,
            sunk_research_usd=None,
        )


@pytest.mark.parametrize("recurring", [None, D(".01")])
def test_real_observed_compact_projection_matches_full_path(original_path, recurring):
    owned, prepared, dates, candidate, trajectory, terms = original_path
    tests = dates[272:692]
    assert len(trajectory.points) == 444
    assert any(point.account.quantity > 0 for point in trajectory.points)
    retention = _CapitalPanelRetention(owned, prepared, terms, tests, recurring, D(99), PROTOCOL)
    value = retention.path(trajectory, 1, candidate)
    expected = _capital_economic_window(
        trajectory,
        initial_cash=terms.initial_cash,
        test_sessions=tests,
        recurring_usd_per_day=recurring,
        sunk_research_usd=D(99),
    )
    matched = _capital_matched_values(owned, terms, trajectory, tests)
    assert type(value) is CapitalObservedPanelPath
    assert value.window == expected
    assert value.window.baseline_session == dates[271]
    assert value.window.session_dates == tests and len(value.window.marked_nav) == 421
    assert value.window.tail_sessions == dates[692:715]
    assert value.matched_spy.reference_hash == matched.input_hash
    assert value.matched_spy.kernel_hash == matched.kernel_result.input_hash
    assert value.matched_spy.marked_nav == (
        terms.initial_cash,
        *tuple(p.close_midpoint_nav for p in matched.kernel_result.points),
    )
    assert value.matched_spy.raw_quantities == matched.raw_quantities
    assert value.matched_spy.exposures == matched.close_exposures
    assert value.matched_spy.mean_exposure == matched.mean_exposure
    assert matched.mean_exposure > 0
    assert value.final.account_hash == trajectory.account.economic_hash
    assert value.final.risk_hash == trajectory.risk.result_hash
    assert value.final.trajectory_hash == trajectory.input_hash
    assert value.final.marked_equity == trajectory.account.marked_equity
    assert value.window.sunk_research_cost == D(99)
    if recurring is None:
        assert value.window.net_nav is value.window.operating_profit is None
    else:
        assert value.window.recurring_cost == D((tests[-1] - dates[271]).days) * recurring
    assert value.execution_enabled is value.evidence_promotable is False
    assert not hasattr(value, "events") and not hasattr(value, "observations")
