"""Observed panel shapes and screens; fabricated orchestration, not a study."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from tests.unit.research.test_etf_capital_observed_prepared import observed_long_source
from tests.unit.research.test_etf_capital_panel_evaluator import (
    short_window as _legacy_short_window,
)
from tests.unit.simulation.test_etf_capital_observed_walk_forward import request as walk_request
from tests.unit.simulation.test_etf_capital_observed_walk_forward import typed_prepared
from trading_bot.code_identity import CodeIdentity
from trading_bot.config.loader import restore_loaded_config
from trading_bot.domain import CodeHash
from trading_bot.market_data.recording import content_hash
from trading_bot.research import etf_capital_panel as panel
from trading_bot.research import etf_capital_panel_models as models
from trading_bot.research.etf_capital_economic_window import _window_metrics
from trading_bot.research.etf_capital_feasibility import _config
from trading_bot.research.etf_capital_protocol import CapitalStudyProtocol
from trading_bot.research.etf_capital_selection import (
    CapitalTrainingOutcome,
    select_capital_training,
)
from trading_bot.research.etf_capital_signals import capital_candidates
from trading_bot.research.etf_resampling import dependent_mean_risks
from trading_bot.simulation.etf_capital_walk_forward import _walk_forward_inputs

PROTOCOL = CapitalStudyProtocol("observed-252x84-v2")
short_window = _legacy_short_window


def request(source, **changes):
    cls = getattr(panel, "CapitalObservedEconomicPanelRequest", None)
    assert cls is not None, "observed panel admission is missing"
    walk = walk_request(source)
    return replace(
        cls(
            source,
            walk.instruments,
            walk.episode_fee_bound,
            walk.entry_fee,
            walk.exit_fee,
            None,
            None,
        ),
        **changes,
    )


def test_observed_pairing_uses_421_nav_points_and_rejects_legacy_dimensions():
    candidate = (D(100), D(101), *((D(101),) * 419))
    reference = (D(100),) * 421
    result = panel._paired_column(candidate, reference, D(100), protocol=PROTOCOL)
    assert result == (D(".01"), *((D(0),) * 419))
    with pytest.raises(ValueError):
        panel._paired_column((D(100),) * 631, (D(100),) * 631, D(100), protocol=PROTOCOL)
    with pytest.raises(ValueError):
        panel._paired_column(candidate, reference, D(100))


@pytest.fixture(scope="module")
def source():
    return observed_long_source(752)


def declared_scenario(walk, *, owned, prepared, recurring_usd_per_day, sunk_research_usd, template):
    terms, _, dates, folds, _ = _walk_forward_inputs(walk, owned)
    sessions = {s.session_date: s for s in owned.dataset.calendar.sessions}
    retained = []
    for fold in folds:
        cutoff = sessions[fold.train_sessions[-1]].closes_at + timedelta(seconds=3)
        at = sessions[dates[dates.index(fold.test_sessions[0]) - 1]].closes_at
        outcomes = tuple(
            CapitalTrainingOutcome(c, D(0), True, cutoff, "a" * 64) for c in capital_candidates()
        )
        training = tuple(
            panel._record(
                models.CapitalObservedPanelTraining,
                o.candidate,
                o,
                o.input_hash,
                "b" * 64,
                "c" * 64,
                252,
                0,
            )
            for o in outcomes
        )
        selected = select_capital_training(
            outcomes,
            loaded=terms.loaded,
            capital=walk.initial_cash,
            training_cutoff=cutoff,
            selection_at=at,
        )
        retained.append(
            panel._record(models.CapitalObservedPanelFold, fold, cutoff, at, training, selected)
        )
    cash = (walk.initial_cash,) * 421
    times = tuple(sessions[day].closes_at for day in dates[271:692])
    returns, metrics = _window_metrics(times, cash, (), D(0), (D(0),) * 420, D(0), D(0))
    window = replace(
        template,
        input_hash="d" * 64,
        trajectory_hash="e" * 64,
        initial_cash=walk.initial_cash,
        baseline_session=dates[271],
        session_dates=dates[272:692],
        tail_sessions=dates[692:715],
        baseline_nav=walk.initial_cash,
        marked_nav=cash,
        cash_change=D(0),
        marked_pnl=D(0),
        trading_pnl=D(0),
        fees_paid=D(0),
        recurring_cost=None,
        sunk_research_cost=sunk_research_usd,
        operating_profit=None,
        marked_operating_profit=None,
        trading_prior_nav_returns=returns,
        trading_metrics=metrics,
        residual_quantity=D(0),
        available_cash=walk.initial_cash,
        unsettled_proceeds=D(0),
        distribution_receivable=D(0),
        distributions_paid=D(0),
        completed_episode_pnl=(),
        turnover_notional=D(0),
    )
    if recurring_usd_per_day is not None:
        costs = tuple(D((day - dates[271]).days) * recurring_usd_per_day for day in dates[271:692])
        net = tuple(a - b for a, b in zip(cash, costs, strict=True))
        nr, nm = _window_metrics(times, net, (), D(0), (D(0),) * 420, D(0), D(0))
        window = replace(
            window,
            net_nav=net,
            recurring_cost=costs[-1],
            operating_profit=-costs[-1],
            marked_operating_profit=-costs[-1],
            operating_prior_nav_returns=nr,
            operating_metrics=nm,
        )
    final = panel._record(
        models.CapitalPanelFinal,
        "e" * 64,
        "f" * 64,
        "a" * 64,
        True,
        walk.initial_cash,
        walk.initial_cash,
        D(0),
        D(0),
        D(0),
        D(0),
        walk.initial_cash,
        D(0),
        D(0),
        D(0),
        (),
    )
    mathematical = panel._record(
        models.CapitalPanelMathematical,
        "b" * 64,
        "c" * 64,
        walk.initial_cash,
        cash,
        (D(0),) * 420,
        D(0),
        (D(0),) * 420,
        ("fabricated_orchestration_only",),
    )
    paths = tuple(
        panel._record(models.CapitalObservedPanelPath, i, c, "e" * 64, window, final, mathematical)
        for i, c in enumerate((None, *capital_candidates()))
    )
    full = panel._record(
        models.CapitalPanelMathematical,
        mathematical.reference_hash,
        mathematical.kernel_hash,
        mathematical.baseline_nav,
        mathematical.marked_nav,
        mathematical.raw_quantities,
        None,
        None,
        mathematical.limitations,
    )
    return panel._record(
        models.CapitalObservedPanelScenario,
        walk.initial_cash,
        walk.roundtrip_friction_pct,
        "f" * 64,
        tuple(retained),
        paths,
        full,
        window,
        final,
        cash,
    )


def evaluation_double(monkeypatch, template):
    identity = CodeIdentity(CodeHash("a" * 64), "b" * 40, False, None, True)
    monkeypatch.setattr(panel, "resolve_code_identity", lambda *a, **k: identity)
    monkeypatch.setattr(
        panel, "_prepare_owned_capital_days", lambda owned, **kw: typed_prepared(owned)
    )
    monkeypatch.setattr(
        panel,
        "_evaluate_scenario",
        lambda walk, **kw: declared_scenario(walk, **kw, template=template),
    )
    actual_family = panel._build_family
    calls = []

    def family(*args, **kwargs):
        calls.append((args[0], kwargs["draws"], len(args[1]), len(args[3])))
        return actual_family(*args, **dict(kwargs, draws=1))

    monkeypatch.setattr(panel, "_build_family", family)
    monkeypatch.setattr(
        panel,
        "dependent_mean_risks",
        lambda values, **kw: dependent_mean_risks(values, **dict(kw, draws=1)),
    )
    return calls


@pytest.mark.parametrize("recurring", [None, D(".01")])
def test_complete_observed_panel_shape_unknown_costs_and_no_go(
    source, short_window, monkeypatch, recurring
):
    value = request(source, recurring_usd_per_day=recurring)
    calls = evaluation_double(monkeypatch, short_window)
    result = panel.evaluate_capital_observed_economic_panel(value)
    dates = tuple(s.session_date for s in source.calendar.sessions)
    assert type(result) is models.CapitalObservedEconomicPanelReport
    assert result.used_sessions == dates[:715] and result.unused_sessions == dates[715:]
    assert result.baseline_session == dates[271] and result.test_sessions == dates[272:692]
    assert result.tail_sessions == dates[692:715]
    assert len(result.scenarios) == 24 and len(result.decisions) == 174
    assert all(len(s.folds) == 5 and len(s.paths) == 29 for s in result.scenarios)
    assert all(
        len(f.training) == 28 and all(t.point_count == 252 for t in f.training)
        for s in result.scenarios
        for f in s.folds
    )
    assert len(result.trading.columns) == 2784 and all(
        len(c) == 420 for c in result.trading.columns
    )
    assert tuple(b.observations for b in result.trading.bands) == (420, 420)
    assert tuple(b.block_length for b in result.trading.bands) == (20, 100)
    assert calls == [("trading", 1000, 420, 2784)] + (
        [] if recurring is None else [("operating", 1000, 420, 2784)]
    )
    if recurring is None:
        assert result.operating is result.cash_risks is None
        assert all(d.verdict == "INSUFFICIENT_EVIDENCE" for d in result.decisions)
    else:
        assert result.operating is not None and len(result.cash_risks) == 696
        assert all(d.verdict == "REJECT" for d in result.decisions)
    assert all(all(c.status == "unknown" for c in d.criteria[6:]) for d in result.decisions)
    assert "conditional_on_no_unobserved_actions" in result.limitations
    assert result.execution_enabled is result.evidence_promotable is False
    assert result.protocol_hash != models._panel_hash("protocol", panel._PROTOCOL)
    cfg = _config(restore_loaded_config(source.canonical_config, source.config_hash))
    assert result.statistics_hash == content_hash(
        (
            "capital-panel-observed-statistics-v1",
            PROTOCOL.protocol_hash,
            result.trading.labels,
            cfg.research.seed,
            (20, 100),
            cfg.research.monte_carlo_iterations,
            "existing-dependent-mean_and-complete-family-max-error-v1",
            result.test_sessions,
            (False,) * 5,
        )
    )


def test_observed_panel_public_types_flags_and_unknown_cost_do_not_open_legacy(source, monkeypatch):
    value = request(source)
    identity = CodeIdentity(CodeHash("a" * 64), "b" * 40, False, None, True)
    monkeypatch.setattr(panel, "_implementation", lambda: identity)
    monkeypatch.setattr(
        panel,
        "_prepare_owned_capital_days",
        lambda *a, **k: pytest.fail("invalid request reached preparation"),
    )
    with pytest.raises(ValueError):
        panel.evaluate_capital_economic_panel(value)
    legacy = panel.CapitalEconomicPanelRequest(
        source,
        value.instruments,
        value.episode_fee_bound,
        value.entry_fee,
        value.exit_fee,
        None,
        None,
    )
    with pytest.raises(ValueError):
        panel.evaluate_capital_observed_economic_panel(legacy)
    for flag in (
        "source_qualified",
        "cost_qualified",
        "execution_enabled",
        "economic_admitted",
        "evidence_promotable",
    ):
        forged = replace(value)
        object.__setattr__(forged, flag, True)
        with pytest.raises(ValueError):
            panel.evaluate_capital_observed_economic_panel(forged)
    for bad in (replace(value, dataset=None), replace(value, recurring_usd_per_day=D(-1))):
        with pytest.raises(ValueError):
            panel.evaluate_capital_observed_economic_panel(bad)


@pytest.mark.parametrize(
    "defect", ["legacy_path", "missing_training", "wrong_dates", "reordered_paths"]
)
def test_observed_mixed_or_incomplete_graph_denies_before_statistics(
    source, short_window, monkeypatch, defect
):
    value = request(source)
    evaluation_double(monkeypatch, short_window)
    actual = panel._evaluate_scenario

    def bad(walk, **kwargs):
        result = actual(walk, **kwargs)
        path = result.paths[0]
        paths, folds = result.paths, result.folds
        if defect == "legacy_path":
            paths = (panel._record(models.CapitalPanelPath, *models._values(path)), *paths[1:])
        elif defect == "missing_training":
            f = folds[0]
            folds = (
                panel._record(
                    type(f), f.fold, f.training_cutoff, f.selection_at, f.training[:-1], f.selection
                ),
                *folds[1:],
            )
        elif defect == "wrong_dates":
            w = replace(path.window, baseline_session=path.window.session_dates[0])
            paths = (
                panel._record(
                    type(path),
                    path.path_index,
                    path.candidate,
                    path.trajectory_hash,
                    w,
                    path.final,
                    path.matched_spy,
                ),
                *paths[1:],
            )
        else:
            paths = (paths[1], paths[0], *paths[2:])
        return panel._record(
            type(result),
            result.capital,
            result.friction_pct,
            result.walker_hash,
            folds,
            paths,
            result.full_spy,
            result.managed_spy,
            result.managed_spy_final,
            result.cash_nav,
        )

    monkeypatch.setattr(panel, "_evaluate_scenario", bad)
    monkeypatch.setattr(
        panel, "_build_family", lambda *a, **k: pytest.fail("bad graph reached statistics")
    )
    with pytest.raises(ValueError):
        panel.evaluate_capital_observed_economic_panel(value)


def test_observed_fold_screen_uses_84_session_boundaries(source, short_window, monkeypatch):
    from tests.unit.research.test_etf_capital_panel import family_inputs
    from trading_bot.market_data.etf_capital_owned import _own_capital_observed_source

    owned = _own_capital_observed_source(source)
    cfg = _config(restore_loaded_config(source.canonical_config, source.config_hash))
    rows = []
    nav = [D(100)] * 421
    for index, amount in ((84, 110), (168, 90), (252, 95), (336, 94), (420, 99)):
        nav[index] = D(amount)
    for cost in cfg.capital_research.round_trip_friction_pct:
        scenario = declared_scenario(
            replace(walk_request(source), roundtrip_friction_pct=cost),
            owned=owned,
            prepared=typed_prepared(owned),
            recurring_usd_per_day=D(0),
            sunk_research_usd=None,
            template=short_window,
        )
        path = scenario.paths[0]
        window = replace(path.window, net_nav=tuple(nav), marked_operating_profit=D(-1))
        changed = panel._record(
            type(path), 0, None, path.trajectory_hash, window, path.final, path.matched_spy
        )
        rows.append(
            panel._record(
                type(scenario),
                scenario.capital,
                cost,
                scenario.walker_hash,
                scenario.folds,
                (changed,),
                scenario.full_spy,
                scenario.managed_spy,
                scenario.managed_spy_final,
                scenario.cash_nav,
            )
        )
    _, capitals, costs, labels, _ = family_inputs()
    dates = rows[0].paths[0].window.session_dates
    family = panel._build_family(
        "operating",
        dates,
        labels,
        ((D(0),) * 420,) * 2784,
        capitals=capitals,
        frictions=costs,
        seed=20260710,
        draws=1,
        protocol=PROTOCOL,
    )
    risks = (dependent_mean_risks((D(0),) * 420, seed=20260710, draws=1),) * 696
    decision = panel._decide_path(
        D(100), 0, tuple(rows), operating=family, cash_risks=risks, cfg=cfg, protocol=PROTOCOL
    )
    assert decision.criteria[1].value == D(3)
    assert (
        decision.criteria[1].reason
        == "minimum_positive_consecutive_84_date_folds_across_four_costs"
    )
    assert decision.verdict == "REJECT"
