"""Declared cross-cost screens are not independent edge or promotion evidence."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from tests.unit.research.test_etf_capital_prepared import long_source
from tests.unit.simulation.test_etf_capital_trajectory import request
from trading_bot.config.loader import restore_loaded_config
from trading_bot.research.etf_capital_economic_window import (
    _capital_economic_window,
    _window_metrics,
)
from trading_bot.research.etf_capital_feasibility import _config
from trading_bot.research.etf_capital_panel import _build_family, _record, _retain_final
from trading_bot.research.etf_capital_panel_models import (
    CapitalPanelMathematical,
    CapitalPanelPath,
    CapitalPanelScenario,
)
from trading_bot.research.etf_resampling import dependent_mean_risks
from trading_bot.simulation.etf_capital_trajectory import replay_capital_trajectory


@pytest.fixture(scope="module")
def declared():
    """Typed projection-only declarations; not actual 1423-session execution."""
    source = long_source(206)
    original = replay_capital_trajectory(request(source))
    window = _capital_economic_window(
        original,
        initial_cash=D(100),
        test_sessions=tuple(p.at.date() for p in original.points[1:4]),
        recurring_usd_per_day=None,
        sunk_research_usd=None,
    )
    cfg = _config(restore_loaded_config(source.canonical_config, source.config_hash))
    times = tuple(datetime(2019, 12, 31, tzinfo=UTC) + timedelta(days=i) for i in range(631))
    nav = tuple(D(100) + D(i) / 100 for i in range(631))
    returns, metrics = _window_metrics(times, nav, (), D(0), (D(0),) * 630, D(0), D(0))
    projected = replace(
        window,
        input_hash="b" * 64,
        baseline_session=times[0].date(),
        session_dates=tuple(t.date() for t in times[1:]),
        tail_sessions=(),
        baseline_nav=D(100),
        marked_nav=nav,
        marked_pnl=D("6.30"),
        trading_prior_nav_returns=returns,
        trading_metrics=metrics,
    )
    mathematical = _record(
        CapitalPanelMathematical,
        "a" * 64,
        "b" * 64,
        D(100),
        (D(100),) * 631,
        (D(0),) * 630,
        None,
        None,
        ("typed_declaration_not_source_execution",),
    )
    final = _retain_final(original, initial_cash=D(100), test_count=3)

    def scenarios(known):
        current = replace(
            projected,
            net_nav=nav if known else None,
            recurring_cost=D(0) if known else None,
            marked_operating_profit=D("6.30") if known else None,
            operating_prior_nav_returns=returns if known else None,
            operating_metrics=metrics if known else None,
        )
        path = _record(CapitalPanelPath, 0, None, original.input_hash, current, final, mathematical)
        return tuple(
            _record(
                CapitalPanelScenario,
                D(100),
                cost,
                "c" * 64,
                (),
                (path,),
                mathematical,
                current,
                final,
                (D(100),) * 631,
            )
            for cost in cfg.capital_research.round_trip_friction_pct
        )

    return cfg, scenarios(False), scenarios(True)


def test_unknown_cost_preserves_all_unknown_support_without_go(declared):
    from trading_bot.research.etf_capital_panel import _decide_path

    cfg, unknown, _ = declared
    result = _decide_path(D(100), 0, unknown, operating=None, cash_risks=None, cfg=cfg)
    assert result.verdict == "INSUFFICIENT_EVIDENCE"
    assert len(result.criteria) == 10 and all(c.status == "unknown" for c in result.criteria)
    assert result.criteria[6].threshold == 30
    assert result.criteria[7].threshold == 50
    assert result.criteria[9].threshold == 95
    assert all(c.value is None for c in result.criteria)
    assert result.execution_enabled is result.evidence_promotable is False


@pytest.fixture(scope="module")
def conditional_family():
    from tests.unit.research.test_etf_capital_panel import family_inputs

    dates, capitals, costs, labels, _ = family_inputs()
    columns = ((D(".0001"),) * 630,) * 2784
    family = _build_family(
        "operating",
        dates,
        labels,
        columns,
        capitals=capitals,
        frictions=costs,
        seed=20260710,
        draws=1,
    )
    loss = dependent_mean_risks((D("-.01"),) * 630, seed=20260710, draws=1)
    return family, (loss,) * 696


def test_probability_fraction_is_whole_percent_and_known_failure_rejects(
    declared, conditional_family
):
    from trading_bot.research.etf_capital_panel import _decide_path

    cfg, _, known = declared
    family, risks = conditional_family
    result = _decide_path(D(100), 0, known, operating=family, cash_risks=risks, cfg=cfg)
    assert result.criteria[0].value == D("6.30")
    assert result.criteria[1].value == 5
    assert result.criteria[2].value == 0
    assert result.criteria[5].value == 100
    assert result.criteria[5].threshold == 50
    assert result.criteria[5].status == "fails_declared_screen"
    assert result.verdict == "REJECT"
    assert all(c.status == "unknown" and c.value is None for c in result.criteria[6:])


def test_one_losing_cost_cannot_be_hidden_by_three_positive_costs(declared, conditional_family):
    from trading_bot.research.etf_capital_panel import _decide_path

    cfg, _, known = declared
    family, risks = conditional_family
    path = known[-1].paths[0]
    changed_window = replace(path.window, marked_operating_profit=D(-1))
    changed_path = _record(
        CapitalPanelPath,
        0,
        None,
        path.trajectory_hash,
        changed_window,
        path.final,
        path.matched_spy,
    )
    last = known[-1]
    changed = _record(
        CapitalPanelScenario,
        last.capital,
        last.friction_pct,
        last.walker_hash,
        last.folds,
        (changed_path,),
        last.full_spy,
        last.managed_spy,
        last.managed_spy_final,
        last.cash_nav,
    )
    result = _decide_path(
        D(100), 0, (*known[:3], changed), operating=family, cash_risks=risks, cfg=cfg
    )
    assert result.criteria[0].value == -1
    assert result.criteria[0].status == "fails_declared_screen"
    assert result.verdict == "REJECT"


def test_all_conditional_screens_pass_but_independence_does_not_appear(
    declared, conditional_family
):
    from trading_bot.research.etf_capital_panel import _decide_path

    cfg, _, known = declared
    family, risks = conditional_family
    zero_risks = tuple(tuple(replace(r, loss_probability=D(0)) for r in row) for row in risks)
    result = _decide_path(D(100), 0, known, operating=family, cash_risks=zero_risks, cfg=cfg)
    assert all(c.status == "passes_declared_screen" for c in result.criteria[:6])
    assert result.verdict == "INSUFFICIENT_EVIDENCE"
    assert all(c.value is None and c.status == "unknown" for c in result.criteria[6:])


def test_negative_original_drawdown_is_not_mistaken_for_a_pass(declared, conditional_family):
    from trading_bot.research.etf_capital_panel import _decide_path

    cfg, _, known = declared
    family, risks = conditional_family
    scenario = known[-1]
    path = scenario.paths[0]
    metric = path.window.operating_metrics
    worse = replace(metric, maximum_drawdown_pct=replace(metric.maximum_drawdown_pct, value=D(-11)))
    window = replace(path.window, operating_metrics=worse)
    changed = _record(
        CapitalPanelPath, 0, None, path.trajectory_hash, window, path.final, path.matched_spy
    )
    last = _record(
        CapitalPanelScenario,
        scenario.capital,
        scenario.friction_pct,
        scenario.walker_hash,
        (),
        (changed,),
        scenario.full_spy,
        scenario.managed_spy,
        scenario.managed_spy_final,
        scenario.cash_nav,
    )
    result = _decide_path(
        D(100), 0, (*known[:3], last), operating=family, cash_risks=risks, cfg=cfg
    )
    assert result.criteria[2].value == 11
    assert result.criteria[2].status == "fails_declared_screen"


def test_wrong_family_dates_cannot_be_paired_to_window(declared, conditional_family):
    from trading_bot.research.etf_capital_panel import _decide_path

    cfg, _, known = declared
    family, risks = conditional_family
    altered = _record(
        type(family),
        family.kind,
        tuple(day + timedelta(days=1) for day in family.session_dates),
        family.labels,
        family.columns,
        family.column_hashes,
        family.bands,
    )
    with pytest.raises(ValueError, match="capital_economic_panel_invalid"):
        _decide_path(D(100), 0, known, operating=altered, cash_risks=risks, cfg=cfg)
