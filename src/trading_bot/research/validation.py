"""Leakage-aware deterministic splits and fail-closed research acceptance."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from trading_bot.research.report import (
    ResearchReport,
    candidate_promotion_identity,
    report_integrity_reason_codes,
)


@dataclass(frozen=True, slots=True)
class LabeledObservation:
    observed_at: datetime
    label_ends_at: datetime
    value: Decimal


@dataclass(frozen=True, slots=True)
class ValidationSplit:
    train: tuple[LabeledObservation, ...]
    test: tuple[LabeledObservation, ...]


def rolling_walk_forward_splits(
    observations: tuple[LabeledObservation, ...], *, train_size: int, test_size: int
) -> tuple[ValidationSplit, ...]:
    if train_size < 1 or test_size < 1:
        raise ValueError("split sizes must be positive")
    result = []
    for start in range(0, len(observations) - train_size - test_size + 1, test_size):
        result.append(
            ValidationSplit(
                observations[start : start + train_size],
                observations[start + train_size : start + train_size + test_size],
            )
        )
    return tuple(result)


def purged_splits(
    observations: tuple[LabeledObservation, ...],
    *,
    train_size: int,
    test_size: int,
    embargo: timedelta = timedelta(0),
) -> tuple[ValidationSplit, ...]:
    splits = rolling_walk_forward_splits(observations, train_size=train_size, test_size=test_size)
    result = []
    for split in splits:
        test_start = split.test[0].observed_at
        train = tuple(item for item in split.train if item.label_ends_at + embargo < test_start)
        result.append(ValidationSplit(train, split.test))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class ParameterStability:
    stable: bool
    median_score: Decimal | None
    worst_neighbor_score: Decimal | None


def analyze_parameter_stability(
    scores: tuple[Decimal, ...], *, minimum_neighbor_score: Decimal
) -> ParameterStability:
    if not scores:
        return ParameterStability(False, None, None)
    ordered = sorted(scores)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    worst = min(scores)
    return ParameterStability(worst >= minimum_neighbor_score, median, worst)


@dataclass(frozen=True, slots=True)
class ResearchAcceptancePolicy:
    minimum_independent_opportunities: int
    maximum_stressed_drawdown_pct: Decimal
    minimum_positive_walk_forward_folds: int
    maximum_single_opportunity_profit_contribution_pct: Decimal
    maximum_monte_carlo_loss_probability_pct: Decimal
    minimum_benchmark_excess_return_pct: Decimal
    require_edge_persistence_rationale: bool = True
    research_assumptions_validated: bool = False
    research_evidence_promotable: bool = False


@dataclass(frozen=True, slots=True)
class ResearchAssessment:
    eligible: bool
    promotable: bool
    reason_codes: tuple[str, ...]


def assess_research(report: ResearchReport, policy: ResearchAcceptancePolicy) -> ResearchAssessment:
    reasons: set[str] = set(report.run.run_reason_codes)
    reasons.update(report_integrity_reason_codes(report))
    if not report.run.code_clean:
        reasons.add("code_identity_not_clean")
    if not policy.research_assumptions_validated:
        reasons.add("research_assumptions_unvalidated")
    if not policy.research_evidence_promotable:
        reasons.add("research_promotion_disabled")
    accepted = tuple(item for item in report.attempts if item.status == "accepted")
    if not accepted:
        reasons.add("no_accepted_candidate")
    elif len(accepted) != 1:
        reasons.add("accepted_candidate_count_invalid")
    for attempt in accepted:
        metrics = attempt.stressed_metrics
        if metrics is None:
            reasons.add("missing_stressed_metrics")
        if metrics is None or not isinstance(metrics.expectancy.value, Decimal) or (
            metrics.expectancy.value <= 0
        ):
            reasons.add("nonpositive_after_cost_oos_expectancy")
        if (
            metrics is None
            or not isinstance(metrics.independent_opportunities.value, int)
            or metrics.independent_opportunities.value < policy.minimum_independent_opportunities
        ):
            reasons.add("insufficient_independent_opportunities")
        if metrics is None or not isinstance(
            metrics.maximum_drawdown_pct.value, Decimal
        ):
            reasons.add("stressed_drawdown_unavailable")
        elif (
            abs(metrics.maximum_drawdown_pct.value)
            > policy.maximum_stressed_drawdown_pct
        ):
            reasons.add("stressed_drawdown_breach")
        if (
            sum(value > 0 for value in attempt.fold_total_returns_pct)
            < policy.minimum_positive_walk_forward_folds
        ):
            reasons.add("insufficient_positive_walk_forward_folds")
        contribution = attempt.maximum_single_opportunity_profit_contribution_pct
        if contribution is None:
            reasons.add("single_opportunity_contribution_unavailable")
        elif (
            contribution
            > policy.maximum_single_opportunity_profit_contribution_pct
        ):
            reasons.add("one_trade_dependence")
        if attempt.monte_carlo_loss_probability_pct is None:
            reasons.add("monte_carlo_loss_probability_unavailable")
        elif (
            attempt.monte_carlo_loss_probability_pct
            > policy.maximum_monte_carlo_loss_probability_pct
        ):
            reasons.add("monte_carlo_loss_probability_breach")
        total_return = (
            None
            if metrics is None
            or not isinstance(metrics.total_return_pct.value, Decimal)
            else metrics.total_return_pct.value
        )
        if total_return is None or attempt.benchmark_total_return_pct is None:
            reasons.add("benchmark_comparison_unavailable")
        elif (
            total_return - attempt.benchmark_total_return_pct
            < policy.minimum_benchmark_excess_return_pct
        ):
            reasons.add("benchmark_not_beaten")
        if not attempt.parameter_neighbor_stressed_total_returns_pct or any(
            value is None or value <= 0
            for value in attempt.parameter_neighbor_stressed_total_returns_pct
        ):
            reasons.add("unstable_parameters")
        expected_identity = candidate_promotion_identity(
            attempt.strategy_id,
            attempt.strategy_version,
            attempt.parameter_hash,
        )
        if (
            not attempt.strategy_id
            or not attempt.strategy_version
            or report.run.selected_strategy_id != attempt.strategy_id
            or report.run.selected_strategy_version != attempt.strategy_version
            or report.run.selected_parameter_hash != attempt.parameter_hash
            or report.run.strategy_version != expected_identity
        ):
            reasons.add("candidate_parameter_identity_not_promotion_bound")
        reasons.update(
            code for code in attempt.reason_codes if code != "edge_persistence_rationale"
        )
    limitations = " ".join(report.run.data_limitations).lower()
    if "leakage" in limitations:
        reasons.add("leakage")
    if "survivorship" in limitations and "resolved" not in limitations:
        reasons.add("survivorship_bias")
    if policy.require_edge_persistence_rationale and not any(
        any("edge_persistence" in code for code in attempt.reason_codes)
        for attempt in accepted
    ):
        reasons.add("missing_edge_persistence_rationale")
    eligible = not reasons
    return ResearchAssessment(eligible, eligible, tuple(sorted(reasons)))


__all__ = [
    "LabeledObservation",
    "ParameterStability",
    "ResearchAcceptancePolicy",
    "ResearchAssessment",
    "ValidationSplit",
    "analyze_parameter_stability",
    "assess_research",
    "purged_splits",
    "rolling_walk_forward_splits",
]
