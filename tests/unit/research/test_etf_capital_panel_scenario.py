"""Scenario wiring doubles execution, while passive math uses fabricated originals."""

from decimal import Decimal as D

from tests.unit.research.test_etf_capital_panel_evaluator import (
    declared_scenario,
)
from tests.unit.research.test_etf_capital_panel_evaluator import original as original
from tests.unit.research.test_etf_capital_panel_evaluator import short_window as short_window
from tests.unit.simulation.test_etf_capital_walk_forward import (
    request,
    typed_orchestration_prepared,
)
from trading_bot.market_data.etf_capital_owned import _own_capital_source
from trading_bot.research.etf_capital_panel import (
    _CapitalCompactWalkForward,
    _evaluate_scenario,
)
from trading_bot.research.etf_capital_passive import (
    CapitalPassiveRequest,
    run_capital_passive_reference,
)


def test_scenario_uses_one_walker_and_same_managed_terms_and_actual_passive_prices(
    monkeypatch,
    original,
    short_window,
):
    import trading_bot.research.etf_capital_panel as panel
    import trading_bot.simulation.etf_capital_walk_forward as walker

    owned = _own_capital_source(original)
    prepared = typed_orchestration_prepared(owned)
    walk = request(owned.dataset)
    declared = declared_scenario(
        walk,
        owned=owned,
        prepared=prepared,
        recurring_usd_per_day=None,
        sunk_research_usd=D(50),
        template=short_window,
    )
    walks, managed, windows = [], [], []

    def compact(value, **kwargs):
        walks.append((value, kwargs))
        return _CapitalCompactWalkForward(declared.folds, declared.paths, declared.walker_hash)

    def constrained(value, **kwargs):
        managed.append((value, kwargs))
        return object()

    def window(value, **kwargs):
        windows.append((value, kwargs))
        return declared.managed_spy

    monkeypatch.setattr(walker, "_replay_owned_capital_walk_forward", compact)
    monkeypatch.setattr(panel, "_replay_owned_capital_constrained", constrained)
    monkeypatch.setattr(panel, "_capital_economic_window", window)
    monkeypatch.setattr(panel, "_retain_final", lambda *a, **k: declared.managed_spy_final)
    value = _evaluate_scenario(
        walk, owned=owned, prepared=prepared, recurring_usd_per_day=None, sunk_research_usd=D(50)
    )
    assert len(walks) == len(managed) == len(windows) == 1
    assert walks[0][1]["owned"] is managed[0][1]["owned"] is owned
    assert walks[0][1]["prepared"] is managed[0][1]["prepared"] is prepared
    assert walks[0][1]["retention"].sunk_research_usd == 50
    comparison = managed[0][0]
    assert len(comparison.days) == 654
    assert all(d.entry_decision_allowed for d in comparison.days[:630])
    assert not any(d.entry_decision_allowed for d in comparison.days[630:])
    assert all(d.entry_submission_allowed for d in comparison.days[:631])
    assert not any(d.entry_submission_allowed for d in comparison.days[631:])
    assert (
        comparison.initial_cash,
        comparison.roundtrip_friction_pct,
        comparison.entry_fee,
        comparison.exit_fee,
        comparison.episode_fee_bound,
    ) == (
        walk.initial_cash,
        walk.roundtrip_friction_pct,
        walk.entry_fee,
        walk.exit_fee,
        walk.episode_fee_bound,
    )
    dates = tuple(s.session_date for s in original.calendar.sessions)
    passive = run_capital_passive_reference(
        CapitalPassiveRequest(
            original,
            D(100),
            dates[770:1400],
            D(".10"),
            D(".01"),
            D(".02"),
        )
    )
    assert value.full_spy.reference_hash == passive.input_hash
    assert value.full_spy.kernel_hash == passive.kernel_result.input_hash
    assert value.full_spy.marked_nav == (
        D(100),
        *tuple(p.close_midpoint_nav for p in passive.kernel_result.points),
    )
    assert value.full_spy.raw_quantities == passive.raw_quantities
    assert value.full_spy.marked_nav[-1] != passive.kernel_result.points[-1].liquidation_proxy
    assert value.full_spy.mean_exposure is value.full_spy.exposures is None
    assert value.paths == declared.paths and value.folds == declared.folds
    assert value.cash_nav == (D(100),) * 631
