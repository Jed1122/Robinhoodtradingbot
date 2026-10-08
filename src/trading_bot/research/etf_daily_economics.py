"""Frozen descriptive DEVELOPMENT scorecards, not accepted economic evidence.

Current monthly prices are counterfactual constant budgets, not historical bills.
Research sunk costs are excluded and unknown. Spread/slippage is embedded once
in assumed prices; paid/estimated fees are not deducted again from marked NAV.
The retrospective exposure-matched reference is mathematical, not an executable
allocation. Completed episodes are not claimed independent opportunities.
"""

from dataclasses import dataclass, replace
from decimal import Decimal, localcontext
from typing import Literal

from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_benchmark import (
    _money_context,
)
from trading_bot.research.etf_daily_protocol import (
    EtfDailyError,
    EtfDailyProtocol,
    EtfDailyRequest,
    _check,
    _DailyRecord,
)
from trading_bot.research.etf_exploratory_economics import (
    EtfExploratoryScore as EtfDailyScore,
)
from trading_bot.research.etf_exploratory_economics import (
    EtfExploratorySizing as EtfDailySizing,
)
from trading_bot.research.etf_exploratory_economics import (
    EtfExploratoryTrace,
    EtfExploratoryUncertainty,
    score_etf_exploratory_trace,
)
from trading_bot.research.etf_exploratory_economics import (
    _performance as _shared_performance,
)
from trading_bot.research.etf_exploratory_economics import (
    _period_returns as _period_returns,
)
from trading_bot.research.etf_exploratory_economics import (
    _renewals as _renewals,
)
from trading_bot.research.etf_exploratory_economics import (
    _returns as _returns,
)
from trading_bot.research.etf_exploratory_economics import (
    _sizing as _shared_sizing,
)
from trading_bot.research.metrics import (
    PerformanceMetrics,
)
from trading_bot.simulation.etf_daily_screen import EtfDailyResult, run_etf_daily_screen
from trading_bot.simulation.etf_history import _policy

ZERO = Decimal("0")
EtfDailyUncertainty = EtfExploratoryUncertainty
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
            "schema": "etf-daily-economic-development-protocol-v2",
            "daily_protocol": protocol.protocol_hash,
            "cost_plan": etf_daily_cost_plan_hash(),
            "costs": _COSTS,
            "budgets": _BUDGETS,
            "cash_yield": "zero_assumption_not_measured",
            "operating_cost": "whole_month_renewals_anchored_first_decision_no_proration",
            "references": "mean_dollar_exposure_matched_buy_hold_capped_at_canonical_order_limit",
            "uncertainty": "paired_fixed_capital_pnl_20_100_blocks_1000_draws_95pct",
            "performance": "prior_nav_period_returns_nonpositive_prior_nav_undefined",
            "criteria": (
                "canonical_drawdown_and_completed_episode_proxy_then_positive_paired_bounds"
            ),
            "admission": "always_false_no_source_cost_independence_qualification",
            "limitations": _LIMITATIONS,
        }
    )


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


def _trace(out: EtfDailyResult) -> EtfExploratoryTrace:
    protocol = out.request.protocol
    return EtfExploratoryTrace(
        _policy(protocol.study),
        out.request.initial_cash,
        protocol.study.risk_equity_reference,
        protocol.study.seed,
        protocol.per_side_cost_bps,
        protocol.side_fee,
        out.request.bars,
        out.request.distributions,
        out.points,
        out.account,
        out.events,
        out.attempts,
        sum(d.scheduled == "entry" for d in out.decisions),
        out.incomplete_reasons,
        out.result_hash,
    )


def _sizing(out: EtfDailyResult) -> EtfDailySizing:
    return _shared_sizing(_trace(out))


def _performance(out: EtfDailyResult) -> PerformanceMetrics:
    return _shared_performance(_trace(out))


def _score(
    out: EtfDailyResult, cost_name: str, budget: tuple[str, Decimal, Decimal]
) -> EtfDailyScore:
    return score_etf_exploratory_trace(
        _trace(out),
        cost_name=cost_name,
        budget_name=budget[0],
        data_monthly=budget[1],
        compute_monthly=budget[2],
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
