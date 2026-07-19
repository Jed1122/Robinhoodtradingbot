from datetime import UTC, datetime
from decimal import Decimal

from trading_bot.domain import (
    DataHash,
    InstrumentId,
    PredictionContractSnapshot,
    PredictionCosts,
    ProbabilityEstimate,
)
from trading_bot.research.prediction import (
    calculate_brier_score,
    calculate_calibration,
    evaluate_prediction_contract,
)

NOW = datetime(2026, 7, 17, tzinfo=UTC)


def snapshot() -> PredictionContractSnapshot:
    return PredictionContractSnapshot(
        InstrumentId("contract"),
        Decimal("0.49"),
        Decimal("0.50"),
        Decimal("0.49"),
        Decimal("0.50"),
        NOW,
        DataHash("a" * 64),
    )


def estimate() -> ProbabilityEstimate:
    return ProbabilityEstimate(
        InstrumentId("contract"), Decimal("0.60"), Decimal("0.02"), NOW, "model-v1"
    )


def test_after_cost_edge_and_loss_are_explicit() -> None:
    result = evaluate_prediction_contract(
        snapshot(),
        estimate(),
        PredictionCosts(Decimal("0.01"), Decimal("0.005"), Decimal("0.005")),
        Decimal("5"),
    )
    assert result.side == "yes"
    assert result.gross_edge == Decimal("0.10")
    assert result.edge == Decimal("0.06")
    assert result.maximum_loss == Decimal("0.52")
    assert result.eligible


def test_calibration_and_brier_use_decimal() -> None:
    observations = ((Decimal("0.8"), True), (Decimal("0.2"), False))
    assert calculate_brier_score(observations) == Decimal("0.04")
    assert sum(item.count for item in calculate_calibration(observations, 5)) == 2
