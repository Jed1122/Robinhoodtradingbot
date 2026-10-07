"""Frozen descriptive DEVELOPMENT scorecards, not accepted economic evidence.

Current monthly prices are counterfactual constant budgets, not historical bills.
Research sunk costs are excluded and unknown. Spread/slippage is embedded once
in assumed prices; paid/estimated fees are not deducted again from marked NAV.
The retrospective exposure-matched reference is mathematical, not an executable
allocation. Completed episodes are not claimed independent opportunities.
"""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, localcontext
from typing import Literal

from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_benchmark import (
    EtfBenchmarkBar,
    EtfBenchmarkRequest,
    _money_context,
    _ratio,
    run_etf_benchmark,
)
from trading_bot.research.etf_daily_protocol import (
    EtfDailyError,
    EtfDailyProtocol,
    EtfDailyRequest,
    _check,
    _DailyRecord,
)
from trading_bot.research.etf_paired_economics import EtfMatchedReturns, analyze_etf_matched_returns
from trading_bot.research.etf_resampling import EtfBlockRisk
from trading_bot.research.metrics import (
    MetricValue,
    PerformanceInput,
    PerformanceMetrics,
    calculate_performance,
)
from trading_bot.simulation.etf_daily_screen import EtfDailyResult, run_etf_daily_screen
from trading_bot.simulation.etf_history import _policy
from trading_bot.simulation.lifecycle_accounting import _context

ZERO = Decimal("0")
_COSTS = (
    ("zero_cost_mathematical_reference", ZERO, ZERO, ZERO),
    ("five_bps_uncalibrated", Decimal("5"), Decimal(".01"), Decimal(".10")),
    ("twenty_five_bps_uncalibrated", Decimal("25"), Decimal(".01"), Decimal(".10")),
)
_BUDGETS = (
    ("zero_data_zero_compute_unverified", ZERO, ZERO),
    ("zero_data_twelve_compute_unverified", ZERO, Decimal("12")),
    ("current_paid_zero_compute", Decimal("99"), ZERO),
    ("current_paid_twelve_compute", Decimal("99"), Decimal("12")),
)
_LIMITATIONS = (
    "development_only_not_legacy_study_or_admission",
    "all_execution_fractional_terms_and_costs_assumed",
    "current_budget_is_not_historical_customer_billing",
    "monthly_renewal_anchor_is_a_counterfactual_not_observed_charges",
    "zero_cash_yield_lower_bound_not_measured_interest",
    "sunk_research_expense_unknown_and_excluded",
    "paired_returns_use_daily_pnl_over_fixed_initial_capital",
    "retrospective_mean_exposure_matched_reference_not_tradable_allocation",
    "daily_close_drawdown_and_occupancy_not_intraday_recovery_proof",
    "completed_episodes_and_daily_blocks_do_not_establish_independence",
    "original_price_action_and_publication_basis_unqualified",
    "final_holdout_not_evaluated",
)


def etf_daily_cost_plan_hash() -> str:
    return content_hash(("etf-daily-cost-assumptions-v1", _COSTS, _BUDGETS, _LIMITATIONS))


def etf_daily_economic_plan_hash(protocol: EtfDailyProtocol) -> str:
    _check(type(protocol) is EtfDailyProtocol)
    protocol.__post_init__()
    return content_hash(
        {
            "schema": "etf-daily-economic-development-protocol-v1",
            "daily_protocol": protocol.protocol_hash,
            "cost_plan": etf_daily_cost_plan_hash(),
            "costs": _COSTS,
            "budgets": _BUDGETS,
            "cash_yield": "zero_assumption_not_measured",
            "operating_cost": "whole_month_renewals_anchored_first_decision_no_proration",
            "references": "mean_dollar_exposure_matched_buy_hold_capped_at_canonical_order_limit",
            "uncertainty": "paired_fixed_capital_pnl_20_100_blocks_1000_draws_95pct",
            "criteria": (
                "canonical_drawdown_and_completed_episode_proxy_then_positive_paired_bounds"
            ),
            "admission": "always_false_no_source_cost_independence_qualification",
            "limitations": _LIMITATIONS,
        }
    )


@dataclass(frozen=True, slots=True)
class EtfDailyUncertainty:
    seed: int
    paired_input_hash: str
    paired_report_hash: str
    vs_constrained: tuple[EtfBlockRisk, ...]
    vs_cash: tuple[EtfBlockRisk, ...]
    constrained_lower_bound: Decimal
    cash_lower_bound: Decimal


@dataclass(frozen=True, slots=True)
class EtfDailyScore(_DailyRecord):
    initial_cash: Decimal
    cost_scenario: str
    operating_scenario: str
    monthly_data_assumption: Decimal
    monthly_compute_assumption: Decimal
    run_hash: str
    account_hash: str
    evaluation_start: date | None
    evaluation_end: date | None
    evaluation_sessions: int
    completed_episodes: int
    independent_opportunities: None
    fees: Decimal
    realized_trading_pnl: Decimal | None
    marked_trading_pnl: Decimal | None
    operating_cost: Decimal | None
    operating_profit_proxy: Decimal | None
    reference_notional: Decimal | None
    candidate_mean_exposure: Decimal | None
    reference_mean_exposure: Decimal | None
    constrained_benchmark_pnl: Decimal | None
    cash_benchmark_pnl: Decimal | None
    risk_reference_drawdown_pct: Decimal | None
    performance: PerformanceMetrics | None
    uncertainty: EtfDailyUncertainty | None
    screening_verdict: Literal["REJECT", "PROCEED_TO_FURTHER_RESEARCH", "INSUFFICIENT_EVIDENCE"]
    incomplete_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EtfDailyEconomicReport(_DailyRecord):
    protocol_hash: str
    input_hash: str
    code_hash: str
    config_hash: str
    source_hash: str
    calendar_hash: str
    distribution_hash: str
    scores: tuple[EtfDailyScore, ...]
    limitations: tuple[str, ...] = _LIMITATIONS
    assumed_cash_yield: Decimal = ZERO
    measured_cash_yield: None = None
    sunk_research_cost: None = None
    sunk_cost_included: Literal[False] = False

    @property
    def result_hash(self) -> str:
        return content_hash({"schema": "etf-daily-economic-development-report-v1", "report": self})


def _renewals(first: date, last: date) -> int:
    # The fixed anchor is the 26th, so every hypothetical monthly anniversary
    # exists; this does not silently substitute calendar-month or daily billing.
    return max(
        1,
        (last.year - first.year) * 12
        + last.month
        - first.month
        + (1 if last.day >= first.day else 0),
    )


def _returns(nav: tuple[Decimal, ...], origin: Decimal) -> tuple[Decimal, ...]:
    previous = origin
    changes = []
    for value in nav:
        changes.append(_ratio(value - previous, origin))
        previous = value
    return tuple(changes)


def _performance(out: EtfDailyResult) -> PerformanceMetrics:
    origin = out.request.initial_cash
    points = out.points
    bars = {row.session_date: row for row in out.request.bars}
    nav = tuple(point.liquidation_proxy for point in points)
    elapsed = _ratio(
        Decimal((points[-1].session_date - points[0].session_date).days + 1), Decimal("365.25")
    )
    trades = tuple(
        episode.net_cash_flow
        for episode in out.account.trial.episodes
        if episode.complete and episode.net_cash_flow is not None
    )
    turnover = sum(
        (event.fill.quantity * event.fill.price for event in out.events if event.fill is not None),
        ZERO,
    )
    exposures = tuple(point.marked_nav - point.cash - point.receivable for point in points)
    with localcontext(_context(exact=False)) as context:
        context.prec = 64
        metrics = calculate_performance(
            PerformanceInput(
                (
                    (bars[points[0].session_date].raw.starts_at, origin),
                    *((bars[p.session_date].raw.ends_at, p.liquidation_proxy) for p in points),
                ),
                _returns(nav, origin),
                trades,
                252,
                elapsed,
                _ratio(turnover, origin),
                exposures,
                exposures,
                _ratio(Decimal(sum(point.shares > 0 for point in points)), Decimal(len(points))),
                ZERO,
                ZERO,
                out.account.fees,
                0,
            )
        )
    return replace(
        metrics,
        spread_cost=MetricValue(None, "unmeasured_component_embedded_in_assumed_prices"),
        slippage_cost=MetricValue(None, "unmeasured_component_embedded_in_assumed_prices"),
        independent_opportunities=MetricValue(None, "not_established"),
        time_in_market_pct=replace(
            metrics.time_in_market_pct, status="daily_close_occupancy_proxy"
        ),
    )


def _score(
    out: EtfDailyResult, cost_name: str, budget: tuple[str, Decimal, Decimal]
) -> EtfDailyScore:
    budget_name, data_monthly, compute_monthly = budget
    episodes = sum(episode.complete for episode in out.account.trial.episodes)
    if not out.points:
        return EtfDailyScore(
            out.request.initial_cash,
            cost_name,
            budget_name,
            data_monthly,
            compute_monthly,
            out.result_hash,
            out.account.state_hash,
            None,
            None,
            0,
            episodes,
            None,
            out.account.fees,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "INSUFFICIENT_EVIDENCE",
            out.incomplete_reasons,
        )
    protocol = out.request.protocol
    cfg = _policy(protocol.study).config
    bars = {row.session_date: row for row in out.request.bars}
    points = out.points
    origin = out.request.initial_cash
    mean_exposure = _ratio(
        sum((p.marked_nav - p.cash - p.receivable for p in points), ZERO), Decimal(len(points))
    )
    first_open = bars[points[0].session_date].raw.open * (1 + protocol.per_side_cost_bps / 10000)
    unit_exposure = _ratio(
        sum((bars[p.session_date].raw.close for p in points), ZERO),
        Decimal(len(points)) * first_open,
    )
    reference_notional = min(
        cfg.activity.max_order_notional_usd,
        protocol.study.risk_equity_reference * cfg.position_risk.max_position_notional_pct / 100,
        _ratio(mean_exposure, unit_exposure),
    )
    reference = run_etf_benchmark(
        EtfBenchmarkRequest(
            tuple(
                EtfBenchmarkBar(
                    p.session_date,
                    bars[p.session_date].raw.open,
                    bars[p.session_date].raw.close,
                    p.source_hash,
                )
                for p in points
            ),
            out.request.distributions,
            origin,
            reference_notional,
            protocol.per_side_cost_bps,
            protocol.side_fee,
            protocol.side_fee,
        )
    )
    reference_mean = _ratio(
        sum(
            (p.close_midpoint_nav - p.cash - p.dividend_receivable for p in reference.points), ZERO
        ),
        Decimal(len(points)),
    )
    monthly = data_monthly + compute_monthly
    costs = tuple(
        Decimal(_renewals(points[0].session_date, p.session_date)) * monthly for p in points
    )
    candidate_nav = tuple(p.liquidation_proxy for p in points)
    trading_pnl = candidate_nav[-1] - origin
    operating_profit = trading_pnl - costs[-1]
    risk_peak = origin
    risk_drawdown = ZERO
    for value in candidate_nav:
        risk_peak = max(risk_peak, value)
        risk_drawdown = max(
            risk_drawdown, (risk_peak - value) / protocol.study.risk_equity_reference * 100
        )
    uncertainty = None
    if len(points) >= 100:
        candidate_returns = _returns(
            tuple(value - cost for value, cost in zip(candidate_nav, costs, strict=True)), origin
        )
        reference_returns = _returns(tuple(p.liquidation_proxy for p in reference.points), origin)
        matched = EtfMatchedReturns(
            tuple(p.session_date for p in points),
            candidate_returns,
            reference_returns,
            (ZERO,) * len(points),
            content_hash((out.result_hash, reference.result_hash, budget)),
        )
        paired = analyze_etf_matched_returns(matched, seed=protocol.study.seed)
        uncertainty = EtfDailyUncertainty(
            paired.seed,
            matched.input_hash,
            paired.report_hash,
            paired.candidate_vs_constrained,
            paired.candidate_vs_cash,
            paired.constrained_lower_bound,
            paired.cash_lower_bound,
        )
    verdict: Literal["REJECT", "PROCEED_TO_FURTHER_RESEARCH", "INSUFFICIENT_EVIDENCE"]
    if out.incomplete_reasons:
        verdict = "INSUFFICIENT_EVIDENCE"
    elif operating_profit <= 0 or risk_drawdown > cfg.research.maximum_stressed_drawdown_pct:
        verdict = "REJECT"
    elif (
        episodes < cfg.research.minimum_independent_opportunities
        or uncertainty is None
        or uncertainty.constrained_lower_bound <= 0
        or uncertainty.cash_lower_bound <= 0
    ):
        verdict = "INSUFFICIENT_EVIDENCE"
    else:
        # This is only a reason to research independent opportunities, costs,
        # and eligible sources further. It is never economic acceptance.
        verdict = "PROCEED_TO_FURTHER_RESEARCH"
    realized = out.account.cash - origin if out.account.complete else None
    return EtfDailyScore(
        origin,
        cost_name,
        budget_name,
        data_monthly,
        compute_monthly,
        out.result_hash,
        out.account.state_hash,
        points[0].session_date,
        points[-1].session_date,
        len(points),
        episodes,
        None,
        out.account.fees,
        realized,
        trading_pnl,
        costs[-1],
        operating_profit,
        reference_notional,
        mean_exposure,
        reference_mean,
        reference.points[-1].liquidation_proxy - origin,
        ZERO,
        risk_drawdown,
        _performance(out),
        uncertainty,
        verdict,
        out.incomplete_reasons,
    )


def run_etf_daily_economics(request: EtfDailyRequest) -> EtfDailyEconomicReport:
    """All preregistered scenarios; never choose a winner or evaluate holdout rows."""
    try:
        _check(type(request) is EtfDailyRequest)
        request.__post_init__()
        protocol_hash = etf_daily_economic_plan_hash(request.protocol)
        scores: list[EtfDailyScore] = []
        with localcontext(_money_context()):
            for capital in request.protocol.study.capital_tiers:
                for name, bps, fee, fee_bound in _COSTS:
                    protocol = replace(
                        request.protocol,
                        per_side_cost_bps=bps,
                        side_fee=fee,
                        episode_fee_bound=fee_bound,
                    )
                    out = run_etf_daily_screen(
                        replace(request, protocol=protocol, initial_cash=capital)
                    )
                    scores.extend(_score(out, name, budget) for budget in _BUDGETS)
        return EtfDailyEconomicReport(
            protocol_hash,
            request.request_hash,
            request.protocol.study.code_hash,
            request.protocol.study.config_hash,
            request.protocol.source_hash,
            request.protocol.calendar_hash,
            request.protocol.distribution_hash,
            tuple(scores),
        )
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise EtfDailyError() from None
