"""Prediction-market evaluation and calibration; intentionally no live methods."""

from dataclasses import dataclass
from decimal import Decimal

from trading_bot.domain import (
    PredictionContractSnapshot,
    PredictionCosts,
    PredictionEvaluation,
    ProbabilityEstimate,
)


def evaluate_prediction_contract(
    snapshot: PredictionContractSnapshot,
    estimate: ProbabilityEstimate,
    costs: PredictionCosts,
    minimum_margin_of_safety_pct: Decimal,
) -> PredictionEvaluation:
    if snapshot.contract_id != estimate.contract_id:
        raise ValueError("prediction estimate does not match contract")
    yes_gross = estimate.yes_probability - snapshot.yes_ask
    no_probability = Decimal("1") - estimate.yes_probability
    no_gross = no_probability - snapshot.no_ask
    if yes_gross >= no_gross:
        side, entry, gross = "yes", snapshot.yes_ask, yes_gross
    else:
        side, entry, gross = "no", snapshot.no_ask, no_gross
    total_cost = costs.commission + costs.exchange_fee + costs.slippage
    edge = gross - estimate.uncertainty - total_cost
    maximum_loss = entry + total_cost
    maximum_payout = max(Decimal("0"), Decimal("1") - entry - total_cost)
    eligible = edge * Decimal("100") >= minimum_margin_of_safety_pct
    return PredictionEvaluation(
        snapshot.contract_id,
        side,
        entry,
        gross,
        estimate.uncertainty,
        total_cost,
        edge,
        maximum_loss,
        maximum_payout,
        eligible,
    )


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    lower: Decimal
    upper: Decimal
    count: int
    mean_probability: Decimal | None
    observed_frequency: Decimal | None


def calculate_calibration(
    observations: tuple[tuple[Decimal, bool], ...], bins: int
) -> tuple[CalibrationBin, ...]:
    if bins < 2:
        raise ValueError("calibration requires at least two bins")
    width = Decimal("1") / Decimal(bins)
    result = []
    for index in range(bins):
        lower = width * index
        upper = width * (index + 1)
        selected = tuple(
            (probability, outcome)
            for probability, outcome in observations
            if lower <= probability < upper or (index == bins - 1 and probability == upper)
        )
        count = len(selected)
        mean = None if not selected else sum((item[0] for item in selected), Decimal("0")) / count
        frequency = None if not selected else Decimal(sum(item[1] for item in selected)) / count
        result.append(CalibrationBin(lower, upper, count, mean, frequency))
    return tuple(result)


def calculate_brier_score(observations: tuple[tuple[Decimal, bool], ...]) -> Decimal:
    if not observations:
        raise ValueError("Brier score requires observations")
    return sum(
        ((probability - Decimal(outcome)) ** 2 for probability, outcome in observations),
        Decimal("0"),
    ) / Decimal(len(observations))


__all__ = [
    "CalibrationBin",
    "calculate_brier_score",
    "calculate_calibration",
    "evaluate_prediction_contract",
]
