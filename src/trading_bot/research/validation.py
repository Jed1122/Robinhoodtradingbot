"""Leakage-aware deterministic splits and fail-closed research acceptance."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from trading_bot.research.report import ResearchReport


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
    require_edge_persistence_rationale: bool = True


@dataclass(frozen=True, slots=True)
class ResearchAssessment:
    eligible: bool
    promotable: bool
    reason_codes: tuple[str, ...]


def assess_research(report: ResearchReport, policy: ResearchAcceptancePolicy) -> ResearchAssessment:
    reasons: set[str] = set()
    accepted = tuple(item for item in report.attempts if item.status == "accepted")
    if not accepted:
        reasons.add("no_accepted_candidate")
    for attempt in accepted:
        metrics = attempt.metrics
        if metrics is None or metrics.expectancy.value is None or metrics.expectancy.value <= 0:
            reasons.add("nonpositive_after_cost_oos_expectancy")
        if (
            metrics is None
            or not isinstance(metrics.independent_opportunities.value, int)
            or metrics.independent_opportunities.value < policy.minimum_independent_opportunities
        ):
            reasons.add("insufficient_independent_opportunities")
        if (
            metrics is not None
            and isinstance(metrics.maximum_drawdown_pct.value, Decimal)
            and (abs(metrics.maximum_drawdown_pct.value) > policy.maximum_stressed_drawdown_pct)
        ):
            reasons.add("stressed_drawdown_breach")
        reasons.update(
            code
            for code in attempt.reason_codes
            if code
            in {
                "one_trade_dependence",
                "unstable_parameters",
                "leakage",
                "survivorship_bias",
                "missing_edge_persistence_rationale",
            }
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
    return ResearchAssessment(eligible, eligible and report.run.code_clean, tuple(sorted(reasons)))


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
