"""Compact projections reuse real original kernels; no caller balance authority."""

from dataclasses import replace
from decimal import Decimal as D

import pytest

from tests.unit.research.test_etf_capital_prepared import long_source
from tests.unit.simulation.test_etf_capital_trajectory import request
from trading_bot.market_data.etf_capital_owned import _own_capital_source
from trading_bot.research.etf_capital_selection import CapitalTrainingOutcome
from trading_bot.research.etf_capital_signals import capital_candidates
from trading_bot.simulation.etf_capital_trajectory import replay_capital_trajectory


@pytest.fixture(scope="module")
def originals():
    source = long_source(206)
    trajectory = replay_capital_trajectory(request(source))
    return source, trajectory


def test_training_projection_retains_original_hashes_before_graph_release(originals):
    from trading_bot.research.etf_capital_panel import _retain_training

    _, trajectory = originals
    # Projection-only fixture; repeating points is NOT 750-session execution.
    expanded = replace(trajectory, points=trajectory.points * 125)
    candidate = capital_candidates()[0]
    outcome = CapitalTrainingOutcome(
        candidate, D(".05495"), True, trajectory.points[-1].at, trajectory.input_hash
    )
    value = _retain_training(expanded, candidate, outcome)
    assert value.trajectory_hash == trajectory.input_hash
    assert value.final_account_hash == trajectory.account.economic_hash
    assert value.final_risk_hash == trajectory.risk.result_hash
    assert value.point_count == 750 and value.event_count == len(trajectory.events)
    assert value.outcome.net_pnl == D(".05495")
    assert not hasattr(value, "trajectory")


def test_path_projection_matches_real_window_and_matched_kernel(originals):
    from trading_bot.research.etf_capital_economic_window import _capital_economic_window
    from trading_bot.research.etf_capital_matched import (
        _capital_matched_values,
        _CapitalMatchedTerms,
    )
    from trading_bot.research.etf_capital_panel import _retain_path

    source, trajectory = originals
    owned = _own_capital_source(source)
    sessions = tuple(p.at.date() for p in trajectory.points[1:4])
    terms = _CapitalMatchedTerms(D(100), D(".10"), D(".01"), D(".02"))
    value = _retain_path(
        trajectory,
        path_index=0,
        candidate=None,
        owned=owned,
        terms=terms,
        test_sessions=sessions,
        recurring_usd_per_day=None,
        sunk_research_usd=D(99),
    )
    expected = _capital_economic_window(
        trajectory,
        initial_cash=D(100),
        test_sessions=sessions,
        recurring_usd_per_day=None,
        sunk_research_usd=D(99),
    )
    matched = _capital_matched_values(owned, terms, trajectory, sessions)
    assert value.window == expected
    assert value.matched_spy.reference_hash == matched.input_hash
    assert value.matched_spy.kernel_hash == matched.kernel_result.input_hash
    assert value.matched_spy.marked_nav == (
        D(100),
        *tuple(p.close_midpoint_nav for p in matched.kernel_result.points),
    )
    assert value.matched_spy.raw_quantities == matched.raw_quantities
    assert value.matched_spy.exposures == matched.close_exposures
    assert value.matched_spy.mean_exposure == matched.mean_exposure
    assert value.final.trading_pnl == D(".05495")
    assert value.window.trading_pnl is None
    assert value.window.net_nav is None and value.window.sunk_research_cost == 99
    assert not hasattr(value, "events") and not hasattr(value, "observations")


def test_private_retention_does_not_accept_an_external_callback():
    from trading_bot.simulation.etf_capital_walk_forward import _replay_owned_capital_walk_forward

    with pytest.raises(ValueError, match="capital_walk_forward_invalid"):
        _replay_owned_capital_walk_forward(
            None, owned=None, prepared=None, retention=lambda value: value
        )


def test_compact_walker_keeps_every_training_outcome_and_same_public_hash(monkeypatch, originals):
    import trading_bot.simulation.etf_capital_walk_forward as walker
    from tests.unit.simulation.test_etf_capital_walk_forward import (
        orchestration_probe,
        typed_orchestration_prepared,
    )
    from tests.unit.simulation.test_etf_capital_walk_forward import (
        request as walk_request,
    )
    from trading_bot.research.etf_capital_matched import _CapitalMatchedTerms
    from trading_bot.research.etf_capital_panel import _CapitalPanelRetention, _record, _retain_path
    from trading_bot.research.etf_capital_panel_models import CapitalPanelFinal, CapitalPanelPath

    source = long_source(1423, start_day=__import__("datetime").date(2016, 1, 4))
    owned = _own_capital_source(source)
    prepared = typed_orchestration_prepared(owned)
    probe = orchestration_probe.__wrapped__(monkeypatch, owned)
    fake_replay = walker._replay_prepared_capital_trajectory
    short_source, real = originals

    def typed_double(**kwargs):
        # Only traversal is doubled. Full typed structure is retained; this is
        # not account/source/economic/workload validation.
        fake = fake_replay(**kwargs)
        points = tuple(
            replace(
                real.points[0],
                at=next(
                    s.closes_at for s in source.calendar.sessions if s.session_date == day.session
                ),
            )
            for day in kwargs["schedule"]
        )
        return replace(
            real,
            points=points,
            input_hash=fake.input_hash,
            account=replace(
                real.account, cash=fake.account.cash, complete=fake.account.complete, quantity=D(0)
            ),
        )

    monkeypatch.setattr(walker, "_replay_prepared_capital_trajectory", typed_double)
    terms = _CapitalMatchedTerms(D(100), D(".10"), D(".01"), D(".02"))
    short_path = _retain_path(
        real,
        path_index=0,
        candidate=None,
        owned=_own_capital_source(short_source),
        terms=terms,
        test_sessions=tuple(p.at.date() for p in real.points[1:4]),
        recurring_usd_per_day=None,
        sunk_research_usd=None,
    )

    def project(self, result, index, candidate):
        window = replace(short_path.window, trajectory_hash=result.input_hash)
        final = _record(
            CapitalPanelFinal,
            result.input_hash,
            result.account.economic_hash,
            result.risk.result_hash,
            True,
            D(100),
            D(100),
            D(0),
            D(0),
            D(0),
            D(0),
            D(100),
            D(0),
            D(0),
            D(0),
            (),
        )
        return _record(
            CapitalPanelPath,
            index,
            candidate,
            result.input_hash,
            window,
            final,
            short_path.matched_spy,
        )

    monkeypatch.setattr(_CapitalPanelRetention, "path", project)
    value = walk_request(source)
    full = walker._replay_owned_capital_walk_forward(value, owned=owned, prepared=prepared)
    probe.paths.clear()
    retention = _CapitalPanelRetention(
        owned,
        prepared,
        terms,
        tuple(s.session_date for s in source.calendar.sessions[770:1400]),
        None,
        None,
    )
    compact = walker._replay_owned_capital_walk_forward(
        value, owned=owned, prepared=prepared, retention=retention
    )
    assert compact.walker_hash == full.input_hash
    assert len(compact.folds) == 5 and all(len(f.training) == 28 for f in compact.folds)
    assert tuple(f.selection for f in compact.folds) == tuple(f.selection for f in full.folds)
    assert tuple(p.trajectory_hash for p in compact.paths) == (
        full.selected.input_hash,
        *tuple(p.trajectory.input_hash for p in full.fixed),
    )
    assert all(
        a.outcome == b.outcome
        for f, g in zip(compact.folds, full.folds, strict=True)
        for a, b in zip(f.training, g.training, strict=True)
    )
    assert len(compact.paths) == 29 and not hasattr(compact.folds[0].training[0], "trajectory")
