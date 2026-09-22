"""Research-only prediction contract records with no execution surface."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import (
    _require_decimal,
    _require_nonempty,
    _require_sha256_hex,
)
from trading_bot.domain.identifiers import DataHash, InstrumentId


@dataclass(frozen=True, slots=True)
class PredictionContractSnapshot:
    contract_id: InstrumentId
    yes_bid: Decimal
    yes_ask: Decimal
    no_bid: Decimal
    no_ask: Decimal
    observed_at: datetime
    data_hash: DataHash

    def __post_init__(self) -> None:
        _require_nonempty(self.contract_id, "contract_id")
        for name in ("yes_bid", "yes_ask", "no_bid", "no_ask"):
            value = getattr(self, name)
            _require_decimal(value, name, nonnegative=True)
            if value > 1:
                raise ValueError("prediction prices cannot exceed one")
        if self.yes_bid > self.yes_ask or self.no_bid > self.no_ask:
            raise ValueError("prediction quote cannot be crossed")
        require_utc(self.observed_at)
        _require_sha256_hex(self.data_hash, "data_hash")


@dataclass(frozen=True, slots=True)
class ProbabilityEstimate:
    contract_id: InstrumentId
    yes_probability: Decimal
    uncertainty: Decimal
    estimated_at: datetime
    model_version: str

    def __post_init__(self) -> None:
        for name in ("yes_probability", "uncertainty"):
            value = getattr(self, name)
            _require_decimal(value, name, nonnegative=True)
            if value > 1:
                raise ValueError("probability values cannot exceed one")
        require_utc(self.estimated_at)
        _require_nonempty(self.model_version, "model_version")


@dataclass(frozen=True, slots=True)
class PredictionCosts:
    commission: Decimal
    exchange_fee: Decimal
    slippage: Decimal

    def __post_init__(self) -> None:
        for name in ("commission", "exchange_fee", "slippage"):
            _require_decimal(getattr(self, name), name, nonnegative=True)


@dataclass(frozen=True, slots=True)
class PredictionEvaluation:
    contract_id: InstrumentId
    side: str
    entry_price: Decimal
    gross_edge: Decimal
    uncertainty_deduction: Decimal
    total_cost: Decimal
    edge: Decimal
    maximum_loss: Decimal
    maximum_payout: Decimal
    eligible: bool


__all__ = [
    "PredictionContractSnapshot",
    "PredictionCosts",
    "PredictionEvaluation",
    "ProbabilityEstimate",
]
