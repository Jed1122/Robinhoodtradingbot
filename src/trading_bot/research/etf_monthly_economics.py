"""One frozen adaptive DEVELOPMENT grid. No executable or accepted edge claims."""

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal, localcontext
from typing import Literal

from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_benchmark import _money_context
from trading_bot.research.etf_exploratory_economics import (
    _BUDGETS,
    _COSTS,
    EtfExploratoryScore,
    EtfExploratoryTrace,
    score_etf_exploratory_trace,
)
from trading_bot.research.etf_monthly_protocol import (
    EtfMonthlyError,
    EtfMonthlyProtocol,
    EtfMonthlyRequest,
    _check,
    _markers,
    _MonthlyRecord,
)
from trading_bot.research.etf_monthly_study import monthly_policy
from trading_bot.simulation.etf_account import EtfAccountResult
from trading_bot.simulation.etf_exploratory_lifecycle import _Pending
from trading_bot.simulation.etf_monthly_screen import EtfMonthlyResult, run_etf_monthly_screen

_LIMITATIONS = (
    "adaptive_development_already_examined_not_fresh_oos",
    "all_execution_fractional_terms_and_costs_assumed",
    "current_budgets_not_customer_bills_or_verified_operating_routes",
    "whole_renewals_anchored_first_economic_point_not_warmup",
    "zero_cash_yield_assumption_not_measured_interest",
    "sunk_research_expense_unknown_and_excluded",
    "prior_nav_performance_separate_from_fixed_capital_paired_pnl",
    "retrospective_exposure_match_is_not_executable_allocation",
    "daily_close_drawdown_not_intraday_risk_or_recovery_proof",
    "completed_episodes_do_not_establish_independence",
    "raw_no_split_and_publication_correction_basis_unqualified",
    "final_holdout_not_evaluated_external_exposure_unknown",
)


def etf_monthly_cost_plan_hash() -> str:
    return content_hash(("etf-monthly-cost-assumptions-v1", _COSTS, _BUDGETS, _LIMITATIONS))


def etf_monthly_operating_basis_hash() -> str:
    return content_hash(
        (
            "etf-monthly-operating-basis-v1",
            tuple((name, "unknown", ()) for name, _, _ in _BUDGETS),
            "no_verified_fractional_order_or_recurring_cost_route",
        )
    )


def etf_monthly_economic_plan_hash(protocol: EtfMonthlyProtocol) -> str:
    try:
        _check(type(protocol) is EtfMonthlyProtocol)
        protocol.__post_init__()
        return content_hash(
            {
                "schema": "etf-monthly-economic-development-protocol-v1",
                "price_policy": protocol.protocol_hash,
                "cost_plan": etf_monthly_cost_plan_hash(),
                "operating_basis": etf_monthly_operating_basis_hash(),
                "costs": _COSTS,
                "budgets": _BUDGETS,
                "first_economic_point": protocol.first_evaluation_session,
                "renewal_anchor": "first_evaluated_point_whole_calendar_anniversaries",
                "references": "same_dates_capped_mean_exposure_buy_hold_and_zero_cash_yield",
                "performance": "prior_nav_nonpositive_prior_undefined",
                "uncertainty": (
                    "fixed_capital_paired_pnl_20_100_blocks_1000_draws_95pct_seed20260710"
                ),
                "criteria": (
                    "incomplete_then_profit_drawdown_then_episode30_positive_paired_lower_bounds"
                ),
                "expansion": "stress_survival_and_verified_operating_route_required_not_attestable",
                "limitations": _LIMITATIONS,
                "admission": "always_false",
            }
        )
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise EtfMonthlyError() from None


@dataclass(frozen=True, slots=True)
class EtfMonthlyScore(EtfExploratoryScore):
    live_authorized: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class EtfMonthlyTerminal(_MonthlyRecord):
    run_hash: str
    account: EtfAccountResult
    pending: _Pending | None
    obligations: tuple[tuple[str, int], ...]
    entitlements: tuple[tuple[str, date], ...]


@dataclass(frozen=True, slots=True)
class EtfMonthlyEconomicReport(_MonthlyRecord):
    price_policy_hash: str
    economic_plan_hash: str
    input_hash: str
    code_hash: str
    config_hash: str
    source_hash: str
    calendar_hash: str
    distribution_hash: str
    cost_plan_hash: str
    operating_basis_hash: str
    evaluation_anchor: date | None
    scores: tuple[EtfMonthlyScore, ...]
    terminal_runs: tuple[EtfMonthlyTerminal, ...]
    native_whole_share_quantity: int | None
    fractional_route_verified: Literal[False] = field(default=False, init=False)
    development_previously_examined: Literal[True] = field(default=True, init=False)
    holdout_exposure: Literal["unknown", "examined", "operator-disclosed-unexamined"] = "unknown"
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)
    assumed_cash_yield: Decimal = field(default=Decimal("0"), init=False)
    measured_cash_yield: None = field(default=None, init=False)
    sunk_research_cost: None = field(default=None, init=False)
    sunk_cost_included: Literal[False] = field(default=False, init=False)

    @property
    def result_hash(self) -> str:
        return content_hash(("etf-monthly-economic-development-report-v1", self))


def _trace(out: EtfMonthlyResult) -> EtfExploratoryTrace:
    _markers(out)
    request, protocol = out.request, out.request.protocol
    return EtfExploratoryTrace(
        monthly_policy(protocol.study),
        request.initial_cash,
        protocol.study.risk_equity_reference,
        protocol.study.seed,
        protocol.per_side_cost_bps,
        protocol.side_fee,
        request.bars,
        request.distributions,
        out.points,
        out.account,
        out.events,
        out.attempts,
        sum(d.scheduled == "entry" for d in out.decisions),
        out.incomplete_reasons,
        out.result_hash,
    )


def _monthly_score(score: EtfExploratoryScore) -> EtfMonthlyScore:
    # Explicit field projection preserves the legacy score schema without dynamic
    # copying or giving an arbitrary result a strategy/execution capability.
    return EtfMonthlyScore(
        score.initial_cash,
        score.cost_scenario,
        score.operating_scenario,
        score.monthly_data_assumption,
        score.monthly_compute_assumption,
        score.run_hash,
        score.account_hash,
        score.evaluation_start,
        score.evaluation_end,
        score.evaluation_sessions,
        score.completed_episodes,
        score.independent_opportunities,
        score.fees,
        score.realized_trading_pnl,
        score.marked_trading_pnl,
        score.operating_cost,
        score.operating_profit_proxy,
        score.reference_notional,
        score.candidate_mean_exposure,
        score.reference_mean_exposure,
        score.constrained_benchmark_pnl,
        score.cash_benchmark_pnl,
        score.risk_reference_drawdown_pct,
        score.performance,
        score.uncertainty,
        score.screening_verdict,
        score.incomplete_reasons,
        score.entry_sizing,
    )


def run_etf_monthly_economics(request: EtfMonthlyRequest) -> EtfMonthlyEconomicReport:
    try:
        _check(type(request) is EtfMonthlyRequest)
        request.__post_init__()
        _check(request.protocol.study.cost_plan_hash == etf_monthly_cost_plan_hash())
        _check(request.protocol.study.operating_basis_hash == etf_monthly_operating_basis_hash())
        economic_plan = etf_monthly_economic_plan_hash(request.protocol)
        scores: list[EtfMonthlyScore] = []
        terminal: list[EtfMonthlyTerminal] = []
        with localcontext(_money_context()):
            for capital in request.protocol.study.capital_tiers:
                for name, bps, fee, fee_bound in _COSTS:
                    p = replace(
                        request.protocol,
                        per_side_cost_bps=bps,
                        side_fee=fee,
                        episode_fee_bound=fee_bound,
                    )
                    out = run_etf_monthly_screen(replace(request, protocol=p, initial_cash=capital))
                    trace = _trace(out)
                    scores.extend(
                        _monthly_score(
                            score_etf_exploratory_trace(
                                trace,
                                cost_name=name,
                                budget_name=budget,
                                data_monthly=data,
                                compute_monthly=compute,
                            )
                        )
                        for budget, data, compute in _BUDGETS
                    )
                    terminal.append(
                        EtfMonthlyTerminal(
                            out.result_hash,
                            out.account,
                            out.checkpoint.pending,
                            out.checkpoint.obligations,
                            out.checkpoint.entitlements,
                        )
                    )
        cfg = monthly_policy(request.protocol.study).config
        native = (
            0
            if request.bars
            and all(r.raw.open > cfg.activity.max_order_notional_usd for r in request.bars)
            else None
        )
        p = request.protocol
        return EtfMonthlyEconomicReport(
            p.protocol_hash,
            economic_plan,
            request.request_hash,
            p.study.code_hash,
            p.study.config_hash,
            p.source_hash,
            p.calendar_hash,
            p.distribution_hash,
            etf_monthly_cost_plan_hash(),
            etf_monthly_operating_basis_hash(),
            p.first_evaluation_session,
            tuple(scores),
            tuple(terminal),
            native,
            holdout_exposure=p.study.holdout_exposure,
        )
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise EtfMonthlyError() from None


def monthly_expansion_disposition(
    report: EtfMonthlyEconomicReport,
) -> Literal["STOP_CANDIDATE", "BLOCKED_OPERATING_EVIDENCE", "REQUIRES_SEPARATE_REVIEW"]:
    try:
        _check(type(report) is EtfMonthlyEconomicReport)
        _markers(report)
        _check(report.operating_basis_hash == etf_monthly_operating_basis_hash())
        _check(report.fractional_route_verified is False and len(report.scores) == 24)
        for score in report.scores:
            _check(type(score) is EtfMonthlyScore)
            _check(
                score.source_qualified is False
                and score.cost_qualified is False
                and score.execution_enabled is False
                and score.economic_admitted is False
                and score.evidence_promotable is False
                and score.live_authorized is False
            )
        stress = any(
            s.cost_scenario == "twenty_five_bps_uncalibrated"
            and s.screening_verdict == "PROCEED_TO_FURTHER_RESEARCH"
            for s in report.scores
        )
        # This frozen operating basis contains only unknown routes. A future
        # supported basis needs a separately reviewed contract, never a flag.
        return "BLOCKED_OPERATING_EVIDENCE" if stress else "STOP_CANDIDATE"
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise EtfMonthlyError() from None
