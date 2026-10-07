"""Synthetic score boundaries are not reconciled accounts or economic evidence."""

from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from tests.unit.research.test_etf_daily_protocol import daily_bar
from tests.unit.simulation.test_etf_daily_screen import request
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_benchmark import _money_context
from trading_bot.research.etf_daily_economics import _score
from trading_bot.risk.options_economics import TrialEpisode, TrialLossState
from trading_bot.simulation.etf_daily_screen import run_etf_daily_screen

D = Decimal
ZERO_EXPOSURE = D("0")
HALF_DOLLAR_STEP = D(".5")
ZERO_BUDGET = ("zero_data_zero_compute_unverified", D("0"), D("0"))
MARKERS = (
    "source_qualified",
    "cost_qualified",
    "execution_enabled",
    "economic_admitted",
    "evidence_promotable",
)


@pytest.fixture(scope="module")
def actual_daily_result():
    """One real offline runner invocation; no broker or provider transport."""
    return run_etf_daily_screen(request(count=200))


def scored(out, budget=ZERO_BUDGET):
    # Match the public economic runner's money context, but score only one case.
    with localcontext(_money_context()):
        return _score(out, "synthetic_single_case_unverified", budget)


def projected(out, nav, *, completed=30, exposure=ZERO_EXPOSURE, evaluation_bars=None):
    """Fabricate score-only projections, deliberately without an account replay.

    These NAVs and completed episodes exercise the frozen decision function;
    they never establish that these cash flows arose from execution/accounting.
    """
    protocol = replace(
        out.request.protocol,
        per_side_cost_bps=D("0"),
        side_fee=D("0"),
        episode_fee_bound=D("0"),
    )
    bars = out.request.bars
    if evaluation_bars is not None:
        bars = (*bars[:100], *evaluation_bars)
    req = replace(out.request, protocol=protocol, bars=bars)
    points = tuple(
        replace(
            point,
            cash=value - exposure,
            settled_cash=value - exposure,
            shares=D("0") if exposure == 0 else D(".1"),
            receivable=D("0"),
            marked_nav=value,
            liquidation_proxy=value,
            reserved_trial=D("0"),
            consumed_trial=D("0"),
            account_hash=content_hash(("fabricated-score-point", i, value, exposure)),
        )
        for i, (point, value) in enumerate(zip(out.points[: len(nav)], nav, strict=True))
    )
    episodes = tuple(
        TrialEpisode(f"fabricated-score-episode-{i}", D("0"), D("1"), True, True, True)
        for i in range(completed)
    )
    account = replace(
        out.account,
        cash=nav[-1],
        settled_cash=nav[-1],
        position=replace(
            out.account.position, quantity=D("0"), average_price=None, market_value=D("0")
        ),
        fees=D("0"),
        orders=(),
        trial=TrialLossState(episodes),
        unsettled=(),
        receivables=(),
    )
    return replace(
        out,
        request=req,
        points=points,
        decisions=(),
        attempts=(),
        exits=(),
        events=(),
        account=account,
        incomplete_reasons=(),
    )


def rising_nav(count=100, step=HALF_DOLLAR_STEP):
    return tuple(D("500") + step * (i + 1) for i in range(count))


def assert_unqualified(record):
    assert all(getattr(record, marker) is False for marker in MARKERS)


def test_actual_hundred_point_runner_score_uses_deterministic_paired_resampling(
    actual_daily_result,
):
    out = actual_daily_result
    assert len(out.points) == 100
    first = scored(out)
    second = scored(out)
    assert first == second
    uncertainty = first.uncertainty
    assert uncertainty is not None
    assert uncertainty.seed == out.request.protocol.study.seed
    assert len(uncertainty.paired_input_hash) == len(uncertainty.paired_report_hash) == 64
    for comparisons in (uncertainty.vs_constrained, uncertainty.vs_cash):
        assert tuple(r.interval.block_length for r in comparisons) == (20, 100)
        assert all(
            r.interval.observations == 100 and r.interval.samples == 1000 for r in comparisons
        )
        assert all(0 <= r.loss_probability <= r.nonpositive_probability <= 1 for r in comparisons)
    # For a 100-observation/100-block draw, there is exactly one possible block.
    # Final cash-comparison P&L is .12504 / 500; its mean over 100 points is below.
    cash_full_block = uncertainty.vs_cash[1]
    assert cash_full_block.interval.lower == cash_full_block.interval.upper == D(".0000025008")
    assert cash_full_block.loss_samples == cash_full_block.nonpositive_samples == 0
    assert (
        uncertainty.vs_constrained[0].interval.lower < uncertainty.vs_constrained[0].interval.upper
    )
    assert first.completed_episodes == 0
    assert first.screening_verdict == "INSUFFICIENT_EVIDENCE"
    assert first.incomplete_reasons == ("open_account_obligations",)
    assert first.independent_opportunities is None
    assert first.performance.independent_opportunities.value is None
    assert first.performance.independent_opportunities.status == "not_established"
    assert_unqualified(first)


@pytest.mark.parametrize("completed", [0, 29])
def test_positive_real_bounds_cannot_substitute_for_completed_episode_proxy(
    actual_daily_result, completed
):
    result = scored(projected(actual_daily_result, rising_nav(), completed=completed))
    assert result.operating_profit_proxy == D("50")
    assert result.uncertainty.constrained_lower_bound == D(".001")
    assert result.uncertainty.cash_lower_bound == D(".001")
    assert result.completed_episodes == completed
    assert result.screening_verdict == "INSUFFICIENT_EVIDENCE"
    assert result.independent_opportunities is None
    assert_unqualified(result)


def test_ninety_nine_points_have_no_uncertainty_even_with_thirty_episode_proxies(
    actual_daily_result,
):
    result = scored(projected(actual_daily_result, rising_nav(99)))
    assert result.evaluation_sessions == 99 and result.completed_episodes == 30
    assert result.operating_profit_proxy > 0
    assert result.uncertainty is None
    assert result.screening_verdict == "INSUFFICIENT_EVIDENCE"
    assert_unqualified(result)


@pytest.mark.parametrize("step", [D("0"), D("-.000001")])
def test_nonpositive_operating_profit_rejects_with_enough_episode_proxies(
    actual_daily_result, step
):
    result = scored(projected(actual_daily_result, rising_nav(step=step)))
    assert result.completed_episodes == 30 and result.uncertainty is not None
    assert result.operating_profit_proxy <= 0
    assert result.screening_verdict == "REJECT"
    assert_unqualified(result)


def test_zero_constrained_lower_endpoint_is_insufficient_despite_positive_cash_bound(
    actual_daily_result,
):
    # Cap the reference at $15; first open 100 gives .15 shares. Closes 101..200
    # give the same .15 daily P&L as the fabricated candidate, hence zero excess.
    bars = tuple(
        daily_bar(point.session_date, D("101") + i, opening=D("100"), low=D("99"))
        for i, point in enumerate(actual_daily_result.points)
    )
    out = projected(
        actual_daily_result, rising_nav(step=D(".15")), exposure=D("50"), evaluation_bars=bars
    )
    result = scored(out)
    assert result.reference_notional == D("15")
    assert result.operating_profit_proxy == D("15")
    assert result.uncertainty.constrained_lower_bound == 0
    assert result.uncertainty.cash_lower_bound == D(".0003")
    assert result.screening_verdict == "INSUFFICIENT_EVIDENCE"
    assert_unqualified(result)


def test_zero_cash_lower_endpoint_is_insufficient_despite_positive_constrained_bound(
    actual_daily_result,
):
    # One first-point gain then 99 flat points has a zero 20-block lower endpoint;
    # the falling-price reference makes constrained excess strictly positive.
    bars = tuple(
        daily_bar(point.session_date, D("100") - D(i) / 100)
        for i, point in enumerate(actual_daily_result.points)
    )
    out = projected(actual_daily_result, (D("501"),) * 100, exposure=D("50"), evaluation_bars=bars)
    result = scored(out)
    assert result.operating_profit_proxy == D("1")
    assert result.uncertainty.constrained_lower_bound > 0
    assert result.uncertainty.cash_lower_bound == 0
    assert result.screening_verdict == "INSUFFICIENT_EVIDENCE"
    assert_unqualified(result)


@pytest.mark.parametrize(
    ("first_nav", "expected_drawdown", "verdict"),
    [
        (D("490"), D("10"), "PROCEED_TO_FURTHER_RESEARCH"),
        (D("489.999999"), D("10.000001"), "REJECT"),
    ],
)
def test_drawdown_uses_risk_reference_and_rejects_only_above_frozen_limit(
    actual_daily_result, first_nav, expected_drawdown, verdict
):
    nav = (first_nav, *(D("490") + D("5") * i for i in range(1, 100)))
    result = scored(projected(actual_daily_result, nav))
    assert result.operating_profit_proxy == D("485")
    assert result.risk_reference_drawdown_pct == expected_drawdown
    assert result.uncertainty.constrained_lower_bound > 0
    assert result.uncertainty.cash_lower_bound > 0
    assert result.screening_verdict == verdict
    assert_unqualified(result)


def test_further_research_verdict_never_promotes_positive_score_only_projection(
    actual_daily_result,
):
    out = projected(actual_daily_result, rising_nav())
    result = scored(out)
    assert result.completed_episodes == 30 and result.evaluation_sessions == 100
    assert result.screening_verdict == "PROCEED_TO_FURTHER_RESEARCH"
    assert result.independent_opportunities is None
    assert result.performance.independent_opportunities.status == "not_established"
    for record in (result, out, out.request, out.request.protocol):
        assert_unqualified(record)
    assert out.account.execution_enabled is False and out.account.evidence_promotable is False


def test_performance_uses_prior_nav_not_fixed_capital_returns(actual_daily_result):
    # Initial500 ->1000 ->1100 ->880 ->792 means period returns1,.1,-.2,-.1.
    # Mean=.2, sample variance=.3, downside sample variance=.005.
    result = scored(projected(actual_daily_result, tuple(map(D, ("1000", "1100", "880", "792")))))
    metrics = result.performance
    assert metrics is not None
    with localcontext() as context:
        context.prec = 64
        annual_root = D("252").sqrt()
        deviation = D(".3").sqrt()
        downside = D(".005").sqrt()
        assert abs(metrics.annualized_volatility_pct.value - deviation * annual_root * 100) < D(
            "1e-55"
        )
        assert abs(metrics.sharpe.value - D(".2") / deviation * annual_root) < D("1e-55")
        assert abs(metrics.sortino.value - D(".2") / downside * annual_root) < D("1e-55")
    assert metrics.total_return_pct.value == D("58.4")
    assert_unqualified(result)


def test_paired_returns_remain_fixed_capital_after_performance_correction(actual_daily_result):
    nav = (*tuple(map(D, ("1000", "1100", "880", "792"))), *((D("792"),) * 96))
    result = scored(projected(actual_daily_result, nav))
    # Full100-block must telescope to292/500/100, not sum compounded returns.
    interval = result.uncertainty.vs_cash[1].interval
    assert interval.lower == interval.upper == D(".00584")
    assert result.operating_profit_proxy == D("292")
    assert_unqualified(result)


@pytest.mark.parametrize("prior", [D("0"), D("-1")])
def test_nonpositive_prior_nav_marks_return_metrics_unknown(actual_daily_result, prior):
    result = scored(projected(actual_daily_result, (prior, D("10"))))
    metrics = result.performance
    assert metrics is not None
    for metric in (metrics.annualized_volatility_pct, metrics.sharpe, metrics.sortino):
        assert metric.value is None
        assert metric.status == "undefined_nonpositive_prior_nav"
    # Preserve other observed values and rejection; do not invent zero returns.
    assert result.marked_trading_pnl == D("-490")
    assert result.screening_verdict == "REJECT"
    assert_unqualified(result)
