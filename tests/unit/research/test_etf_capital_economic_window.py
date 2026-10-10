"""Literal cutoff economics from real fabricated original-event owner output."""

from dataclasses import replace
from datetime import timedelta, timezone
from decimal import Decimal as D
from decimal import localcontext

import pytest

from tests.unit.research.test_etf_capital_prepared import long_source
from tests.unit.simulation.test_etf_capital_trajectory import request
from trading_bot.simulation.etf_capital_trajectory import replay_capital_trajectory


@pytest.fixture(scope="module")
def original():
    return replay_capital_trajectory(request(long_source(206)))


def run(original, *, count=5, recurring=D(".01"), sunk=D(99)):
    from trading_bot.research.etf_capital_economic_window import _capital_economic_window

    return _capital_economic_window(
        original,
        initial_cash=D(100),
        test_sessions=tuple(p.at.date() for p in original.points[1 : 1 + count]),
        recurring_usd_per_day=recurring,
        sunk_research_usd=sunk,
    )


def test_window_cost_starts_after_baseline_and_counts_weekend_once(original):
    value = run(original, count=3)
    assert str(value.baseline_session) == "2020-10-07"
    assert tuple(map(str, value.session_dates)) == ("2020-10-08", "2020-10-09", "2020-10-12")
    assert value.marked_nav == (D(100), D("99.9825"), D("100.0325"), D("100.05495"))
    assert value.net_nav == (D(100), D("99.9725"), D("100.0125"), D("100.00495"))
    assert value.recurring_cost == D(".05")
    assert value.sunk_research_cost == 99
    assert value.marked_pnl == D(".05495")
    assert value.marked_operating_profit == D(".00495")


def test_tail_settlement_does_not_finalize_cutoff_cash_or_episode(original):
    cutoff = run(original, count=3)
    assert cutoff.cash_change == D(".05495")
    assert cutoff.trading_pnl is cutoff.operating_profit is None
    assert cutoff.unsettled_proceeds == D("15.07245")
    assert cutoff.residual_quantity == 0
    assert cutoff.completed_episode_pnl == ()
    assert cutoff.tail_sessions == tuple(p.at.date() for p in original.points[4:])
    final = run(original)
    assert final.trading_pnl == D(".05495")
    assert final.operating_profit == D("-.01505")
    assert final.recurring_cost == D(".07")
    assert final.completed_episode_pnl == (D(".05495"),)
    assert final.fees_paid == D(".03")
    assert final.turnover_notional == D("30.09995")
    assert final.trading_metrics.expectancy.value == D(".05495")


def test_returns_use_baseline_marked_nav_not_initial_cash(original):
    held_baseline = replace(original, points=original.points[1:])
    value = run(held_baseline, recurring=D(0))
    assert value.baseline_nav == D("99.9825")
    assert value.cash_change == D("15.07245")
    assert value.marked_pnl == D(".07245")
    assert value.trading_pnl is None
    assert value.fees_paid == D(".02")
    assert value.turnover_notional == D("15.09245")
    with localcontext() as context:
        context.prec = 64
        want = D(".05") / D("99.9825")
    assert value.trading_prior_nav_returns[0] == want
    assert value.trading_prior_nav_returns[0] != D(".0005")


def test_unknown_expense_stays_unknown_without_erasing_trading_results(original):
    value = run(original, recurring=None, sunk=None)
    assert value.recurring_cost is value.sunk_research_cost is None
    assert value.net_nav is value.operating_prior_nav_returns is value.operating_metrics is None
    assert value.operating_profit is value.marked_operating_profit is None
    assert value.trading_pnl == D(".05495")
    assert value.trading_metrics.fees.value == D(".03")
    assert "operating_cost_unknown" in value.reasons


def test_nonpositive_prior_net_nav_never_becomes_truncated_or_zero_return(original):
    value = run(original, recurring=D(101))
    assert value.operating_prior_nav_returns is None
    assert value.operating_metrics.sharpe.value is None
    assert value.operating_metrics.sharpe.status == "undefined_nonpositive_prior_nav"
    assert value.trading_prior_nav_returns is not None
    assert value.operating_profit == D("-706.94505")


def test_unknown_cost_not_explicit_zero_and_sunk_only_changes_identity(original):
    unknown = run(original, recurring=None)
    zero = run(original, recurring=D(0))
    other = run(original, recurring=D(0), sunk=D(100))
    assert unknown.input_hash != zero.input_hash != other.input_hash
    assert zero.net_nav == other.net_nav == zero.marked_nav
    assert zero.operating_profit == other.operating_profit == D(".05495")
    assert zero.actual_tax_usd is zero.independent_opportunities is None
    assert zero.trading_metrics.independent_opportunities.value is None
    assert zero.trading_metrics.spread_cost.value is None
    assert zero.trading_metrics.slippage_cost.value is None
    assert zero.trading_metrics.sortino.value is None
    assert not zero.source_qualified and not zero.cost_qualified
    assert (
        not zero.execution_enabled and not zero.economic_admitted and not zero.evidence_promotable
    )


def test_duplicate_original_delivery_does_not_double_count_costs(original):
    from trading_bot.simulation.etf_capital_risk import CapitalRiskObservation

    duplicate = replace(
        original,
        events=(*original.events, original.events[-1]),
        observations=tuple(replace(o) for o in original.observations),
    )
    # The additional raw delivery occurs after all close frontiers; no original
    # economic mutation or observation is invented to count it.
    assert all(type(o) is CapitalRiskObservation for o in duplicate.observations)
    value = run(duplicate)
    assert value.trading_pnl == D(".05495")
    assert value.fees_paid == D(".03")
    assert value.turnover_notional == D("30.09995")
    assert value.completed_episode_pnl == (D(".05495"),)


@pytest.mark.parametrize("amount", (0, False, D(-1), D("NaN"), D("Infinity"), D("1e600")))
def test_invalid_expense_denies_without_private_details(original, amount):
    with pytest.raises(ValueError, match=r"^capital_economic_window_invalid$"):
        run(original, recurring=amount)


def test_oversized_derived_expense_denies(original):
    with pytest.raises(ValueError, match=r"^capital_economic_window_invalid$"):
        run(original, recurring=D("1e511"))


def test_hostile_ambient_decimal_context_does_not_change_report(original):
    expected = run(original)
    with localcontext() as context:
        context.prec = 3
        assert run(original) == expected


@pytest.mark.parametrize("field", ("account", "equity", "source_count"))
def test_altered_original_cutoff_fields_are_not_adopted(original, field):
    if field == "account":
        points = (
            *original.points[:-1],
            replace(original.points[-1], account=original.points[0].account),
        )
        altered = replace(original, points=points)
    elif field == "equity":
        points = (*original.points[:-1], replace(original.points[-1], equity=D(101)))
        altered = replace(original, points=points)
    else:
        observed = original.observations[-1]
        observations = (*original.observations[:-1], replace(observed, source_count=4096))
        altered = replace(original, observations=observations)
    # Invalid tail cannot hide behind the earlier cutoff.
    with pytest.raises(ValueError, match=r"^capital_economic_window_invalid$"):
        run(altered, count=3)


def test_unsafe_mutated_flag_denies(original):
    altered = replace(original)
    object.__setattr__(altered, "economic_admitted", True)
    with pytest.raises(ValueError, match=r"^capital_economic_window_invalid$"):
        run(altered)


def test_terminal_zero_nav_has_valid_returns_until_it_becomes_a_prior_nav():
    value = request(long_source(206))
    value = replace(value, days=tuple(replace(d, candidate=None) for d in value.days))
    original = replay_capital_trajectory(value)
    terminal = run(original, count=2, recurring=D(50))
    assert terminal.net_nav == (D(100), D(50), D(0))
    assert terminal.operating_prior_nav_returns == (D("-.5"), D(-1))
    late = run(original, count=3, recurring=D(50))
    assert late.net_nav == (D(100), D(50), D(0), D(-150))
    assert late.operating_prior_nav_returns is None
    assert late.operating_metrics.sharpe.status == "undefined_nonpositive_prior_nav"


def test_original_distribution_receivable_not_tail_payment_enters_cutoff_nav():
    from tests.unit.config.test_capital_research import capital_loaded
    from trading_bot.market_data.etf_capital_actions import CapitalDistribution
    from trading_bot.market_data.etf_capital_dataset import build_capital_dataset

    source = long_source(206)
    ex_date = source.calendar.sessions[201].session_date
    pay_date = source.calendar.sessions[203].session_date
    actions = (
        *source.actions[:4],
        replace(
            source.actions[4],
            distributions=(CapitalDistribution(ex_date, ex_date, pay_date, D(2), "a" * 64),),
        ),
    )
    source = build_capital_dataset(
        loaded=capital_loaded(),
        archives=source.archives,
        actions=actions,
        calendar=source.calendar,
        start=source.start,
        end=source.end,
    )
    original = replay_capital_trajectory(request(source))
    cutoff = run(original, count=2, recurring=D(0))
    assert cutoff.distributions_paid == 0
    assert cutoff.distribution_receivable == D(".1")
    assert cutoff.marked_pnl == D(".1325")
    assert cutoff.trading_pnl is None
    assert cutoff.completed_episode_pnl == ()
    final = run(original, recurring=D(0))
    assert final.distributions_paid == D(".1")
    assert final.distribution_receivable == 0
    assert final.completed_episode_pnl == (D(".15495"),)


@pytest.mark.parametrize("kind", ("unfilled", "partial"))
def test_unfilled_or_partial_entry_remains_incomplete(kind):
    value = request(
        long_source(206),
        entry_outcome=kind,
        entry_fill_fraction=D(0) if kind == "unfilled" else D(".5"),
        entry_fee=D(0),
    )
    original = replay_capital_trajectory(value)
    result = run(original)
    assert result.trading_pnl is result.operating_profit is None
    assert result.available_cash < result.cash_change + D(100)
    assert result.completed_episode_pnl == ()


@pytest.mark.parametrize("sessions", ((), [], ("2020-10-08",), (True,)))
def test_nonoriginal_or_empty_session_window_denies(original, sessions):
    from trading_bot.research.etf_capital_economic_window import _capital_economic_window

    with pytest.raises(ValueError, match=r"^capital_economic_window_invalid$"):
        _capital_economic_window(
            original,
            initial_cash=D(100),
            test_sessions=sessions,
            recurring_usd_per_day=D(0),
            sunk_research_usd=D(0),
        )


def test_shifted_window_cannot_silently_move_baseline(original):
    from trading_bot.research.etf_capital_economic_window import _capital_economic_window

    with pytest.raises(ValueError, match=r"^capital_economic_window_invalid$"):
        _capital_economic_window(
            original,
            initial_cash=D(100),
            test_sessions=tuple(p.at.date() for p in original.points[2:]),
            recurring_usd_per_day=D(0),
            sunk_research_usd=D(0),
        )


def test_coordinated_future_finality_cannot_finalize_an_earlier_cutoff(original):
    at = original.points[3].at
    assert original.points[3].account.unsettled_proceeds == D("15.07245")
    assert len(original.events) == 8
    observations = tuple(
        replace(row, source_count=8) if row.cursor.occurred_at == at else row
        for row in original.observations
    )
    points = tuple(
        replace(point, account=original.account) if point.at == at else point
        for point in original.points
    )
    with pytest.raises(ValueError, match=r"^capital_economic_window_invalid$"):
        run(replace(original, observations=observations, points=points), count=3)


def test_equal_instant_non_utc_points_cannot_shift_calendar_expense(original):
    zone = timezone(timedelta(hours=14))
    points = tuple(
        replace(point, at=point.at.astimezone(zone)) if index >= 3 else point
        for index, point in enumerate(original.points)
    )
    # Python datetime equality does not distinguish this calendar-date alias.
    assert points[3].at == original.points[3].at
    assert str(points[3].at.date()) == "2020-10-13"
    with pytest.raises(ValueError, match=r"^capital_economic_window_invalid$"):
        run(replace(original, points=points), count=3)


def test_integer_equity_cannot_alias_a_decimal_baseline(original):
    points = (replace(original.points[0], equity=100), *original.points[1:])
    with pytest.raises(ValueError, match=r"^capital_economic_window_invalid$"):
        run(replace(original, points=points))


@pytest.mark.parametrize(
    "changes",
    (
        {"complete": D(1)},
        {"quantity": False},
        {"cash": 100},
        {"available_cash": 100},
        {"fees": 0},
        {"unsettled_proceeds": False},
        {"distribution_receivable": 0},
        {"execution_enabled": 0},
        {"evidence_promotable": 0},
        {"source_qualified": 0},
    ),
)
def test_equality_equivalent_account_types_are_not_canonical(original, changes):
    account = replace(original.points[0].account)
    for name, value in changes.items():
        object.__setattr__(account, name, value)
    assert account == original.points[0].account
    points = (replace(original.points[0], account=account), *original.points[1:])
    with pytest.raises(ValueError, match=r"^capital_economic_window_invalid$"):
        run(replace(original, points=points))


def test_invalid_final_account_type_cannot_hide_beyond_cutoff(original):
    account = replace(original.account, complete=D(1))
    with pytest.raises(ValueError, match=r"^capital_economic_window_invalid$"):
        run(replace(original, account=account), count=3)


def test_invalid_tail_account_type_cannot_hide_beyond_cutoff(original):
    tail = original.points[-1]
    points = (*original.points[:-1], replace(tail, account=replace(tail.account, quantity=False)))
    with pytest.raises(ValueError, match=r"^capital_economic_window_invalid$"):
        run(replace(original, points=points), count=3)


def test_point_subclass_cannot_supply_an_unvalidated_record(original):
    from trading_bot.simulation.etf_capital_trajectory import CapitalTrajectoryPoint

    class DerivedPoint(CapitalTrajectoryPoint):
        pass

    point = original.points[0]
    alias = DerivedPoint(point.at, point.equity, point.account, point.policy, point.opening)
    with pytest.raises(ValueError, match=r"^capital_economic_window_invalid$"):
        run(replace(original, points=(alias, *original.points[1:])))


def test_observation_reordering_cannot_hide_in_timestamp_lookup(original):
    observations = (*original.observations[:-2], *reversed(original.observations[-2:]))
    with pytest.raises(ValueError, match=r"^capital_economic_window_invalid$"):
        run(replace(original, observations=observations), count=3)
