"""Exact constrained window fixtures, not execution or market evidence."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal as D
from decimal import localcontext

import pytest

from tests.unit.research.test_etf_capital_prepared import long_source
from tests.unit.simulation.test_etf_capital_constrained import (
    changed_spy,
    request,
    run,
)
from tests.unit.simulation.test_etf_capital_constrained import (
    original as _constrained_source,
)
from trading_bot.market_data.etf_capital_actions import CapitalDistribution
from trading_bot.research.etf_capital_economic_window import _capital_economic_window
from trading_bot.simulation.etf_capital_constrained import (
    CapitalConstrainedPoint,
    CapitalConstrainedResult,
)
from trading_bot.simulation.etf_capital_risk import CapitalRiskObservation
from trading_bot.simulation.etf_capital_trajectory import CapitalTrajectoryPoint
from trading_bot.simulation.events import EventCursor

# Re-export the shared fabricated source fixture without redefining its factory.
constrained_source = _constrained_source


@pytest.fixture(scope="module")
def original(constrained_source):
    return run(request(constrained_source, count=24))


def window(value, *, count=23, recurring=D(".01"), sunk=D(99)):
    return _capital_economic_window(
        value,
        initial_cash=D(100),
        test_sessions=tuple(p.at.date() for p in value.points[1 : count + 1]),
        recurring_usd_per_day=recurring,
        sunk_research_usd=sunk,
    )


def test_constrained_actual_cash_fees_turnover_and_completion_clock(original):
    cutoff = window(original, count=21, recurring=D(0))
    assert cutoff.cash_change == D("-.0498")
    assert cutoff.trading_pnl is cutoff.operating_profit is None
    assert cutoff.residual_quantity == 0
    assert cutoff.unsettled_proceeds == D("19.7701")
    assert cutoff.completed_episode_pnl == ()
    final = window(original, recurring=D(0))
    assert final.trading_pnl == final.operating_profit == D("-.0498")
    assert final.completed_episode_pnl == (D("-.0498"),)
    assert final.fees_paid == D(".03")
    assert final.turnover_notional == D("39.6")
    assert final.trajectory_hash == original.input_hash
    assert final.unsettled_proceeds == 0


def test_constrained_weekend_cost_baseline_and_unknown_are_distinct(original):
    value = window(original, count=3)
    assert str(value.baseline_session) == "2020-10-07"
    assert tuple(map(str, value.session_dates)) == ("2020-10-08", "2020-10-09", "2020-10-12")
    assert value.marked_nav == (D(100), D("99.9801"), D("99.9801"), D("99.9801"))
    assert value.net_nav == (D(100), D("99.9701"), D("99.9601"), D("99.9301"))
    assert value.recurring_cost == D(".05")
    assert value.sunk_research_cost == 99
    unknown = window(original, count=3, recurring=None, sunk=None)
    assert unknown.net_nav is unknown.operating_metrics is unknown.operating_profit is None
    assert unknown.recurring_cost is unknown.sunk_research_cost is None
    assert unknown.marked_nav == value.marked_nav
    assert unknown.input_hash != value.input_hash
    assert unknown.independent_opportunities is unknown.actual_tax_usd is None


def test_constrained_baseline_is_actual_mark_and_nonpositive_operating_prior_denies(original):
    held = replace(original, points=original.points[1:])
    value = window(held, count=2, recurring=D(0))
    assert value.baseline_nav == D("99.9801")
    assert value.marked_pnl == 0 and value.trading_prior_nav_returns == (D(0), D(0))
    negative = window(original, count=3, recurring=D(101))
    assert negative.operating_prior_nav_returns is None
    assert negative.operating_metrics.sharpe.status == "undefined_nonpositive_prior_nav"


def test_constrained_duplicate_delivery_and_hostile_context_preserve_report(original):
    expected = window(original)
    with localcontext() as context:
        context.prec = 3
        assert window(original) == expected
    repeated = replace(original, events=(*original.events, original.events[-1]))
    value = window(repeated)
    assert value.fees_paid == expected.fees_paid
    assert value.turnover_notional == expected.turnover_notional
    assert value.completed_episode_pnl == expected.completed_episode_pnl
    assert value.source_qualified is False and value.cost_qualified is False
    assert value.execution_enabled is False and value.economic_admitted is False
    assert value.evidence_promotable is False


@pytest.mark.parametrize(
    "kind",
    (
        "point_family",
        "equity",
        "timezone",
        "tail_account",
        "future_finality",
        "flag",
        "point_tuple",
        "point_subclass",
        "result_subclass",
        "account_bool",
    ),
)
def test_constrained_inconsistent_originals_deny_before_window_selection(original, kind):
    points = original.points
    if kind == "point_family":
        p = points[-1]
        bad = CapitalTrajectoryPoint(p.at, p.equity, p.account, None, None)
        changed = replace(original, points=(*points[:-1], bad))
    elif kind == "equity":
        changed = replace(original, points=(replace(points[0], equity=100), *points[1:]))
    elif kind == "timezone":
        alias = points[0].at.astimezone(timezone(timedelta(hours=-4)))
        changed = replace(original, points=(replace(points[0], at=alias), *points[1:]))
    elif kind == "tail_account":
        changed = replace(
            original, points=(*points[:-1], replace(points[-1], account=points[0].account))
        )
    elif kind == "future_finality":
        cutoff = points[21]
        observations = tuple(
            replace(o, source_count=len(original.events))
            if o.cursor.occurred_at == cutoff.at
            else o
            for o in original.observations
        )
        changed = replace(
            original,
            observations=observations,
            points=(*points[:21], replace(cutoff, account=original.account), *points[22:]),
        )
    elif kind == "point_tuple":
        changed = replace(original, points=list(points))
    elif kind == "point_subclass":

        class ExtendedPoint(CapitalConstrainedPoint):
            pass

        p = points[-1]
        extended = ExtendedPoint(p.at, p.equity, p.account, p.policy, p.opening)
        changed = replace(original, points=(*points[:-1], extended))
    elif kind == "result_subclass":

        class ExtendedResult(CapitalConstrainedResult):
            pass

        changed = ExtendedResult(
            original.events,
            original.observations,
            original.points,
            original.account,
            original.risk,
            original.input_hash,
        )
    elif kind == "account_bool":
        account = replace(points[0].account, quantity=False)
        changed = replace(original, points=(replace(points[0], account=account), *points[1:]))
    else:
        changed = replace(original)
        object.__setattr__(changed, "economic_admitted", 0)
    with pytest.raises(ValueError, match=r"^capital_economic_window_invalid$"):
        window(changed, count=21)


def test_constrained_result_metaclass_cannot_impersonate_exact_family(original):
    class EqualFamily(type):
        def __eq__(cls, other):
            return other is CapitalConstrainedResult

    class Spoof(CapitalConstrainedResult, metaclass=EqualFamily):
        pass

    changed = Spoof(
        original.events,
        original.observations,
        original.points,
        original.account,
        original.risk,
        original.input_hash,
    )
    assert type(changed) is not CapitalConstrainedResult
    with pytest.raises(ValueError, match=r"^capital_economic_window_invalid$"):
        window(changed)


def test_constrained_namespace_is_derived_from_exact_family(original, monkeypatch):
    from trading_bot.research import etf_capital_economic_window as module

    real = module.content_hash
    observed = []

    def record(value):
        observed.append(value)
        return real(value)

    monkeypatch.setattr(module, "content_hash", record)
    window(original)
    assert len(observed) == 1
    assert observed[0][0] == "capital-private-constrained-economic-window-v1"


def test_constrained_ex_entitlement_is_not_future_paid_cash(constrained_source):
    ex, pay = (constrained_source.calendar.sessions[i].session_date for i in (201, 202))
    source = changed_spy(
        constrained_source,
        {i: ("299", "300", "298", "299") for i in (201, 202)},
        distributions=(CapitalDistribution(ex, ex, pay, D(1), "b" * 64),),
    )
    result = run(request(source, count=4))
    cutoff = window(result, count=2, recurring=D(0))
    assert cutoff.distribution_receivable == D(".066")
    assert cutoff.distributions_paid == 0
    assert cutoff.marked_pnl == D("-.0199")
    assert cutoff.trading_pnl is None
    paid = window(result, count=3, recurring=D(0))
    assert paid.distributions_paid == D(".066")
    assert paid.distribution_receivable == 0
    assert paid.marked_pnl == D("-.0199")


def test_exact_630_test_and_23_tail_arithmetic_not_workload(original):
    # Fabricated empty-tape accounting dates, NOT a source calendar or owner run.
    baseline = original.points[0]
    times = tuple(datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(654))
    points = tuple(replace(baseline, at=at) for at in times)
    observations = tuple(
        CapitalRiskObservation(EventCursor(i + 1, at), 0, None, True, True)
        for i, at in enumerate(times)
    )
    empty = replace(
        original, events=(), points=points, observations=observations, account=baseline.account
    )
    value = window(empty, count=630)
    assert len(value.session_dates) == 630
    assert len(value.marked_nav) == len(value.net_nav) == 631
    assert len(value.tail_sessions) == 23
    assert value.recurring_cost == D("6.30")
    assert value.marked_pnl == 0
    assert value.marked_operating_profit == D("-6.30")


def test_original_strategy_window_literal_preimages_are_unchanged():
    from tests.unit.research.test_etf_capital_economic_window import run as strategy_window
    from tests.unit.simulation.test_etf_capital_trajectory import request as strategy_request
    from trading_bot.simulation.etf_capital_trajectory import replay_capital_trajectory

    strategy = replay_capital_trajectory(strategy_request(long_source(206)))
    assert (
        strategy_window(strategy).input_hash
        == "c0ce6c34f4c77300a49c928b2d31a84056f3694347cffe392e37d8e5c3628eff"
    )
    assert (
        strategy_window(strategy, recurring=None, sunk=None).input_hash
        == "800ca0f9abaa4dda78a4e8c9d795a7a31cf41d13bddccd50e793b38fefb7b644"
    )
