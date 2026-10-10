"""Literal original-account path reports; fabricated inputs, never accepted edge."""

from dataclasses import replace
from decimal import Decimal as D
from decimal import localcontext

import pytest

from tests.unit.research.test_etf_capital_prepared import long_source
from tests.unit.simulation.test_etf_capital_trajectory import request as trajectory


@pytest.fixture(scope="module")
def source():
    return long_source(206)


def request(source, **changes):
    from trading_bot.research.etf_capital_path_economics import CapitalPathEconomicRequest

    return replace(CapitalPathEconomicRequest(trajectory(source), D(".01"), D(99)), **changes)


def run(value):
    from trading_bot.research.etf_capital_path_economics import evaluate_capital_path_economics

    return evaluate_capital_path_economics(value)


def test_final_cash_fees_turnover_and_episode_are_not_double_deducted(source):
    value = run(request(source))
    assert value.cash_change == value.trading_pnl == value.marked_pnl == D(".05495")
    assert value.fees_paid == D(".03")
    assert value.turnover_notional == D("30.09995")
    assert value.completed_episode_pnl == (D(".05495"),)
    assert value.metrics.expectancy.value == D(".05495")
    assert value.metrics.turnover.value == D(".3009995")
    assert value.independent_opportunities is None
    assert value.metrics.independent_opportunities.value is None
    assert value.actual_tax_usd is None
    assert value.metrics.spread_cost.value is value.metrics.slippage_cost.value is None


def test_inclusive_calendar_accrual_includes_weekend_but_not_sunk_cost(source):
    value = run(request(source))
    assert tuple(str(d) for d in value.session_dates) == (
        "2020-10-07",
        "2020-10-08",
        "2020-10-09",
        "2020-10-12",
        "2020-10-13",
        "2020-10-14",
    )
    assert value.recurring_cost == D(".08")
    assert value.sunk_research_cost == D(99)
    assert value.operating_profit == D("-.02505")
    assert value.net_nav[0] == D("99.99")
    assert value.net_nav[3] == D("99.99495")
    assert value.net_nav[-1] == D("99.97495")


@pytest.mark.parametrize("count,quantity,unsettled", ((2, ".05", "0"), (4, "0", "15.07245")))
def test_incomplete_held_and_flat_unsettled_have_no_final_trading_profit(
    source, count, quantity, unsettled
):
    value = request(source, trajectory=trajectory(source, count=count))
    result = run(value)
    assert result.trading_pnl is result.operating_profit is None
    assert result.residual_quantity == D(quantity)
    assert result.unsettled_proceeds == D(unsettled)
    assert result.completed_episode_pnl == ()
    assert "account_outcome_incomplete" in result.reasons


def test_prior_nav_returns_are_not_fixed_initial_capital_increments(source):
    value = run(request(source, recurring_usd_per_day=D(0)))
    assert value.prior_nav_returns[0] == 0
    assert value.prior_nav_returns[1] == D("-.000175")
    with localcontext() as context:
        context.prec = 64
        expected = D(".05") / D("99.9825")
    assert value.prior_nav_returns[2] == expected
    assert value.prior_nav_returns[2] != D(".0005")


def test_cash_only_expense_path_cannot_publish_legacy_ratio_as_standard_sortino(source):
    original = trajectory(source, count=3)
    cash_only = replace(
        original,
        days=tuple(replace(day, candidate=None) for day in original.days),
    )
    value = run(request(source, trajectory=cash_only))
    assert value.net_nav == (D("99.99"), D("99.98"), D("99.97"))
    assert value.trading_pnl == 0 and value.operating_profit == D("-.03")
    assert value.metrics.sortino.value is None
    assert value.metrics.sortino.status == (
        "unavailable_legacy_negative_return_sample_sd_not_target_downside_deviation"
    )
    assert value.metrics.sharpe.value is not None


def test_nonpositive_prior_nav_makes_entire_return_ratios_unknown(source):
    value = run(request(source, recurring_usd_per_day=D(101)))
    assert value.prior_nav_returns is None
    for metric in (
        value.metrics.sharpe,
        value.metrics.sortino,
        value.metrics.annualized_volatility_pct,
    ):
        assert metric.value is None
        assert metric.status == "undefined_nonpositive_prior_nav"
    assert value.trading_pnl == D(".05495")
    assert value.operating_profit == D("-807.94505")


def test_no_trade_does_not_invent_expectancy_or_independent_support(source):
    value = run(request(source, trajectory=trajectory(source, count=1)))
    assert value.trading_pnl == 0
    assert value.completed_episode_pnl == ()
    assert value.metrics.expectancy.value is None
    assert value.metrics.independent_opportunities.value is None
    assert not value.source_qualified and not value.cost_qualified
    assert not value.execution_enabled and not value.economic_admitted
    assert not value.evidence_promotable


@pytest.mark.parametrize("amount", (None, 0, D(-1), D("NaN"), D("Infinity"), D("1e600")))
def test_invalid_expense_assumptions_deny_without_data_leak(source, amount):
    with pytest.raises(ValueError, match="capital_path_economics_invalid"):
        run(request(source, recurring_usd_per_day=amount))


def test_bounded_expense_factors_cannot_publish_oversized_derived_output(source):
    with pytest.raises(ValueError, match="capital_path_economics_invalid"):
        run(request(source, recurring_usd_per_day=D("1e511")))


def test_ambient_precision_and_sunk_cost_identity_remain_distinct(source):
    original = request(source)
    expected = run(original)
    with localcontext() as context:
        context.prec = 3
        assert run(original) == expected
    other = run(replace(original, sunk_research_usd=D(100)))
    assert other.input_hash != expected.input_hash
    assert other.operating_profit == expected.operating_profit


def test_unsafe_mutated_admission_flag_denies(source):
    value = request(source)
    object.__setattr__(value, "economic_admitted", True)
    with pytest.raises(ValueError, match="capital_path_economics_invalid"):
        run(value)


def test_duplicate_original_delivery_does_not_recount_fees_notional_or_episode(source):
    from trading_bot.research.etf_capital_path_economics import _capital_path_economics
    from trading_bot.simulation.etf_capital_trajectory import replay_capital_trajectory

    value = trajectory(source)
    original = replay_capital_trajectory(value)
    duplicate = replace(original, events=(*original.events, original.events[-1]))
    result = _capital_path_economics(
        duplicate,
        initial_cash=D(100),
        initial_at=source.calendar.sessions[199].opens_at,
        recurring_usd_per_day=D(0),
        sunk_research_usd=D(0),
    )
    assert result.fees_paid == D(".03")
    assert result.turnover_notional == D("30.09995")
    assert result.completed_episode_pnl == (D(".05495"),)


def test_original_entitlement_and_payment_have_separate_cash_and_nav_effects(source):
    from tests.unit.config.test_capital_research import capital_loaded
    from trading_bot.market_data.etf_capital_actions import CapitalDistribution
    from trading_bot.market_data.etf_capital_dataset import build_capital_dataset

    ex_date = source.calendar.sessions[201].session_date
    pay_date = source.calendar.sessions[203].session_date
    actions = (
        *source.actions[:4],
        replace(
            source.actions[4],
            distributions=(CapitalDistribution(ex_date, ex_date, pay_date, D(2), "a" * 64),),
        ),
    )
    altered = build_capital_dataset(
        loaded=capital_loaded(),
        archives=source.archives,
        actions=actions,
        calendar=source.calendar,
        start=source.start,
        end=source.end,
    )
    before = run(request(altered, trajectory=trajectory(altered, count=3)))
    assert before.cash_change == D("-15.0175")
    assert before.distribution_receivable == D(".1") and before.distributions_paid == 0
    assert before.marked_pnl == D(".1325") and before.trading_pnl is None
    after = run(request(altered))
    assert after.distributions_paid == D(".1") and after.distribution_receivable == 0
    assert after.trading_pnl == D(".15495")
    assert after.completed_episode_pnl == (D(".15495"),)


def test_public_adapter_never_adopts_result_or_dictionary_as_original_request(source):
    value = request(source)
    with pytest.raises(ValueError, match="capital_path_economics_invalid"):
        run(replace(value, trajectory={}))
    with pytest.raises(ValueError, match="capital_path_economics_invalid"):
        run({})
