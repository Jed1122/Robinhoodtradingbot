"""Public original-input admission; never saved outcomes or executable evidence."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from tests.unit.research.test_etf_capital_prepared import long_source
from tests.unit.simulation.test_etf_capital_walk_forward import request as walk_request
from trading_bot.code_identity import CodeIdentity
from trading_bot.domain import CodeHash
from trading_bot.research.etf_capital_panel import CapitalEconomicPanelRequest


def panel_request(source, **changes):
    walk = walk_request(source)
    return replace(
        CapitalEconomicPanelRequest(
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


@pytest.fixture(scope="module")
def original():
    return long_source(1424, start_day=__import__("datetime").date(2016, 1, 4))


def test_public_evaluator_accepts_no_saved_results_or_callback():
    from trading_bot.research.etf_capital_panel import evaluate_capital_economic_panel

    for value in (None, object(), lambda: None):
        with pytest.raises(ValueError, match="capital_economic_panel_invalid"):
            evaluate_capital_economic_panel(value)


def test_dirty_code_denies_before_originals_or_preparation(monkeypatch):
    import trading_bot.research.etf_capital_panel as panel
    from trading_bot.research.etf_capital_panel import evaluate_capital_economic_panel

    dirty = CodeIdentity(CodeHash("a" * 64), "b" * 40, True, None, True)
    monkeypatch.setattr(panel, "resolve_code_identity", lambda *a, **k: dirty)
    monkeypatch.setattr(panel, "_own_capital_source", lambda *_: pytest.fail("dirty ownership"))
    value = CapitalEconomicPanelRequest(None, (), None, D(0), D(0), None, None)
    with pytest.raises(ValueError, match="capital_economic_panel_invalid"):
        evaluate_capital_economic_panel(value)


def test_full_spy_fee_equal_smallest_capital_denies_before_prepare(monkeypatch, original):
    import trading_bot.research.etf_capital_panel as panel
    from trading_bot.research.etf_capital_panel import evaluate_capital_economic_panel

    clean = CodeIdentity(CodeHash("a" * 64), "b" * 40, False, None, True)
    monkeypatch.setattr(panel, "resolve_code_identity", lambda *a, **k: clean)
    monkeypatch.setattr(
        panel,
        "_prepare_owned_capital_days",
        lambda *a, **k: pytest.fail("invalid fee reached preparation"),
    )
    with pytest.raises(ValueError, match="capital_economic_panel_invalid"):
        evaluate_capital_economic_panel(panel_request(original, entry_fee=D(100)))


def test_forged_true_flag_denies_before_any_code_or_source_read(monkeypatch, original):
    import trading_bot.research.etf_capital_panel as panel
    from trading_bot.research.etf_capital_panel import evaluate_capital_economic_panel

    value = panel_request(original)
    object.__setattr__(value, "economic_admitted", True)
    monkeypatch.setattr(
        panel, "resolve_code_identity", lambda *a, **k: pytest.fail("forged flag read code")
    )
    with pytest.raises(ValueError, match="capital_economic_panel_invalid"):
        evaluate_capital_economic_panel(value)


@pytest.fixture(scope="module")
def short_window():
    from tests.unit.simulation.test_etf_capital_trajectory import request
    from trading_bot.research.etf_capital_economic_window import _capital_economic_window
    from trading_bot.simulation.etf_capital_trajectory import replay_capital_trajectory

    result = replay_capital_trajectory(request(long_source(206)))
    return _capital_economic_window(
        result,
        initial_cash=D(100),
        test_sessions=tuple(p.at.date() for p in result.points[1:4]),
        recurring_usd_per_day=None,
        sunk_research_usd=None,
    )


def declared_scenario(walk, *, owned, prepared, recurring_usd_per_day, sunk_research_usd, template):
    """Complete typed orchestration double, NOT actual path or economic evidence."""
    from trading_bot.research.etf_capital_economic_window import _window_metrics
    from trading_bot.research.etf_capital_panel import _record
    from trading_bot.research.etf_capital_panel_models import (
        CapitalPanelFinal,
        CapitalPanelFold,
        CapitalPanelMathematical,
        CapitalPanelPath,
        CapitalPanelScenario,
        CapitalPanelTraining,
    )
    from trading_bot.research.etf_capital_selection import (
        CapitalTrainingOutcome,
        select_capital_training,
    )
    from trading_bot.research.etf_capital_signals import capital_candidates
    from trading_bot.simulation.etf_capital_walk_forward import _walk_forward_inputs

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
            _record(CapitalPanelTraining, o.candidate, o, o.input_hash, "b" * 64, "c" * 64, 750, 0)
            for o in outcomes
        )
        selected = select_capital_training(
            outcomes,
            loaded=terms.loaded,
            capital=walk.initial_cash,
            training_cutoff=cutoff,
            selection_at=at,
        )
        retained.append(_record(CapitalPanelFold, fold, cutoff, at, training, selected))
    cash = (walk.initial_cash,) * 631
    times = tuple(sessions[day].closes_at for day in dates[769:1400])
    returns, metrics = _window_metrics(times, cash, (), D(0), (D(0),) * 630, D(0), D(0))
    window = replace(
        template,
        input_hash="d" * 64,
        trajectory_hash="e" * 64,
        initial_cash=walk.initial_cash,
        baseline_session=dates[769],
        session_dates=dates[770:1400],
        tail_sessions=dates[1400:1423],
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
        costs = tuple(D((day - dates[769]).days) * recurring_usd_per_day for day in dates[769:1400])
        net = tuple(nav - cost for nav, cost in zip(cash, costs, strict=True))
        net_returns, net_metrics = _window_metrics(times, net, (), D(0), (D(0),) * 630, D(0), D(0))
        window = replace(
            window,
            net_nav=net,
            recurring_cost=costs[-1],
            operating_profit=-costs[-1],
            marked_operating_profit=-costs[-1],
            operating_prior_nav_returns=net_returns,
            operating_metrics=net_metrics,
        )
    final = _record(
        CapitalPanelFinal,
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
    mathematical = _record(
        CapitalPanelMathematical,
        "b" * 64,
        "c" * 64,
        walk.initial_cash,
        cash,
        (D(0),) * 630,
        D(0),
        (D(0),) * 630,
        ("fabricated_orchestration_only",),
    )
    paths = tuple(
        _record(CapitalPanelPath, i, c, "e" * 64, window, final, mathematical)
        for i, c in enumerate((None, *capital_candidates()))
    )
    return _record(
        CapitalPanelScenario,
        walk.initial_cash,
        walk.roundtrip_friction_pct,
        "f" * 64,
        tuple(retained),
        paths,
        _record(
            type(mathematical),
            mathematical.reference_hash,
            mathematical.kernel_hash,
            mathematical.baseline_nav,
            mathematical.marked_nav,
            mathematical.raw_quantities,
            None,
            None,
            mathematical.limitations,
        ),
        window,
        final,
        cash,
    )


def evaluation_double(monkeypatch, template):
    import trading_bot.research.etf_capital_panel as panel
    from tests.unit.simulation.test_etf_capital_walk_forward import typed_orchestration_prepared

    identity = CodeIdentity(CodeHash("a" * 64), "b" * 40, False, None, True)
    identities = []
    monkeypatch.setattr(
        panel, "resolve_code_identity", lambda *a, **k: identities.append(identity) or identity
    )
    preparations, calls = [], []

    def prepare(owned, *, sessions):
        preparations.append(sessions)
        return typed_orchestration_prepared(owned)

    def scenario(walk, **kwargs):
        calls.append((walk.initial_cash, walk.roundtrip_friction_pct, kwargs["prepared"]))
        return declared_scenario(walk, **kwargs, template=template)

    monkeypatch.setattr(panel, "_prepare_owned_capital_days", prepare)
    monkeypatch.setattr(panel, "_evaluate_scenario", scenario)
    real_family = panel._build_family
    family_calls = []

    def family(*args, **kwargs):
        family_calls.append((args[0], kwargs["draws"], len(args[2]), len(args[3])))
        # Only orchestration is tested; existing actual resampling tests are separate.
        return real_family(*args, **dict(kwargs, draws=1))

    monkeypatch.setattr(panel, "_build_family", family)
    return preparations, calls, family_calls, identities


def test_public_panel_owns_once_and_retains_all_scenarios_before_whole_family(
    monkeypatch, original, short_window
):
    from trading_bot.research.etf_capital_panel import evaluate_capital_economic_panel

    preparations, calls, family_calls, identities = evaluation_double(monkeypatch, short_window)
    result = evaluate_capital_economic_panel(panel_request(original))
    capitals = tuple(map(D, ("100", "250", "500", "1000", "5000", "10000")))
    costs = tuple(map(D, (".05", ".10", ".20", ".40")))
    assert [(a, b) for a, b, _ in calls] == [(a, b) for a in capitals for b in costs]
    assert len(preparations) == 1 and len(preparations[0]) == 1423
    assert len({id(p) for _, _, p in calls}) == 1
    assert len(identities) == 2 and result.implementation == identities[0]
    assert len(result.scenarios) == 24
    assert all(
        len(s.folds) == 5 and all(len(f.training) == 28 for f in s.folds) and len(s.paths) == 29
        for s in result.scenarios
    )
    assert family_calls == [("trading", 1000, 2784, 2784)]
    assert len(result.trading.columns) == 2784 and len(result.trading.columns[0]) == 630
    assert result.operating is result.cash_risks is None
    assert len(result.decisions) == 174
    assert all(d.verdict == "INSUFFICIENT_EVIDENCE" for d in result.decisions)
    assert len(result.used_sessions) == 1423 and len(result.unused_sessions) == 1
    assert result.execution_enabled is result.evidence_promotable is False


@pytest.mark.parametrize("defect", ("path", "training", "order", "identity"))
def test_missing_or_reordered_or_misbound_fact_denies_before_statistics(
    monkeypatch, original, short_window, defect
):
    import trading_bot.research.etf_capital_panel as panel
    from trading_bot.research.etf_capital_panel import _record, evaluate_capital_economic_panel

    evaluation_double(monkeypatch, short_window)
    fake = panel._evaluate_scenario

    def bad(walk, **kwargs):
        result = fake(walk, **kwargs)
        folds, paths = result.folds, result.paths
        if defect == "path":
            paths = paths[:-1]
        elif defect == "training":
            fold = folds[0]
            folds = (
                _record(
                    type(fold),
                    fold.fold,
                    fold.training_cutoff,
                    fold.selection_at,
                    fold.training[:-1],
                    fold.selection,
                ),
                *folds[1:],
            )
        elif defect == "order":
            paths = (paths[1], paths[0], *paths[2:])
        else:
            path = paths[0]
            paths = (
                _record(type(path), 0, None, "0" * 64, path.window, path.final, path.matched_spy),
                *paths[1:],
            )
        return _record(
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
    monkeypatch.setattr(panel, "_build_family", lambda *a, **k: pytest.fail("invalid math"))
    with pytest.raises(ValueError, match="capital_economic_panel_invalid"):
        evaluate_capital_economic_panel(panel_request(original))


def test_code_changes_during_evaluation_deny_whole_report(monkeypatch, original, short_window):
    import trading_bot.research.etf_capital_panel as panel
    from trading_bot.research.etf_capital_panel import evaluate_capital_economic_panel

    evaluation_double(monkeypatch, short_window)
    first = CodeIdentity(CodeHash("a" * 64), "b" * 40, False, None, True)
    changed = CodeIdentity(CodeHash("c" * 64), "d" * 40, False, None, True)
    states = iter((first, changed))
    monkeypatch.setattr(panel, "resolve_code_identity", lambda *a, **k: next(states))
    with pytest.raises(ValueError, match="capital_economic_panel_invalid"):
        evaluate_capital_economic_panel(panel_request(original))


@pytest.mark.parametrize("recurring", (D(0), D(".01")))
def test_known_zero_or_positive_cost_keeps_whole_operating_family_and_same_managed_expense(
    monkeypatch, original, short_window, recurring
):
    import trading_bot.research.etf_capital_panel as panel
    from trading_bot.research.etf_capital_panel import evaluate_capital_economic_panel
    from trading_bot.research.etf_resampling import dependent_mean_risks

    _, _, family_calls, _ = evaluation_double(monkeypatch, short_window)
    risk_inputs = []

    def risk(values, **kwargs):
        risk_inputs.append((values, kwargs))
        return dependent_mean_risks(values, **dict(kwargs, draws=1))

    monkeypatch.setattr(panel, "dependent_mean_risks", risk)
    result = evaluate_capital_economic_panel(
        panel_request(
            original,
            recurring_usd_per_day=recurring,
            sunk_research_usd=D(50),
        )
    )
    assert family_calls == [("trading", 1000, 2784, 2784), ("operating", 1000, 2784, 2784)]
    assert result.operating is not None and len(result.operating.columns) == 2784
    assert result.cash_risks is not None and len(result.cash_risks) == len(risk_inputs) == 696
    assert all(
        values == result.operating.columns[index * 4 + 3]
        and kwargs == dict(seed=20260710, block_lengths=(20, 100), draws=1000)
        for index, (values, kwargs) in enumerate(risk_inputs)
    )
    first = result.scenarios[0]
    cost = D((result.test_sessions[-1] - result.baseline_session).days) * recurring
    assert first.paths[0].window.marked_operating_profit == -cost
    assert first.paths[0].window.recurring_cost == first.managed_spy.recurring_cost == cost
    assert first.paths[0].window.sunk_research_cost == first.managed_spy.sunk_research_cost == 50
    assert result.operating.columns[1] == (D(0),) * 630  # same managed expense cancels numerically
    assert sum(result.operating.columns[3]) == -cost / D(100)  # cash receives no expense
    assert all(d.verdict == "REJECT" for d in result.decisions)
    assert all(c.status == "unknown" for d in result.decisions for c in d.criteria[6:])
