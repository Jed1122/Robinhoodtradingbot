"""Simulation-only normalization for prediction markets with live refusal."""

from dataclasses import dataclass
from decimal import Decimal

from trading_bot.capabilities.models import EvidenceLevel, UnsupportedCapabilityError

PREDICTION_LIVE_ENABLED = False


@dataclass(frozen=True, slots=True)
class PredictionContract:
    market_id: str
    contract_id: str
    title: str


@dataclass(frozen=True, slots=True)
class PredictionQuote:
    contract_id: str
    yes_price: Decimal
    no_price: Decimal

    def __post_init__(self) -> None:
        if not (Decimal("0") <= self.yes_price <= Decimal("1")):
            raise ValueError("yes price must be a probability")
        if not (Decimal("0") <= self.no_price <= Decimal("1")):
            raise ValueError("no price must be a probability")


class RobinhoodPredictionAdapter:
    """Normalize fixture research data while rejecting every live operation."""

    def normalize_contract(self, payload: dict[str, str]) -> PredictionContract:
        return PredictionContract(
            market_id=payload["market_id"],
            contract_id=payload["contract_id"],
            title=payload["title"],
        )

    def normalize_quote(self, payload: dict[str, str]) -> PredictionQuote:
        return PredictionQuote(
            contract_id=payload["contract_id"],
            yes_price=Decimal(payload["yes_price"]),
            no_price=Decimal(payload["no_price"]),
        )

    @staticmethod
    def _unsupported(operation: str) -> UnsupportedCapabilityError:
        error = UnsupportedCapabilityError(
            "robinhood-prediction", operation, EvidenceLevel.AUTHENTICATED_WRITE_REVIEWED
        )
        error.args = ("prediction live execution is not verified",)
        return error

    async def review_order(self, intent: object) -> None:
        del intent
        raise self._unsupported("review_order")

    async def place_order(self, submission: object) -> None:
        del submission
        raise self._unsupported("place_order")

    async def cancel_known_order(self, account_id: object, order_id: object) -> None:
        del account_id, order_id
        raise self._unsupported("cancel_order")


__all__ = [
    "PREDICTION_LIVE_ENABLED",
    "PredictionContract",
    "PredictionQuote",
    "RobinhoodPredictionAdapter",
]
