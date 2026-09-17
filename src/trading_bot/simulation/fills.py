"""Seeded fill model with no same-event fills."""

import random
from dataclasses import dataclass
from decimal import Decimal

from trading_bot.clock import DomainValidationError
from trading_bot.domain import Side
from trading_bot.domain.decimal_utils import (
    InvalidDecimal,
    _require_exact_bool,
    require_bounded_decimal,
)
from trading_bot.simulation.costs import (
    SimulatedCosts,
    _validate_execution_inputs,
    execution_fee,
    execution_price,
)
from trading_bot.simulation.events import EventCursor


@dataclass(frozen=True, slots=True)
class FillRequest:
    submitted: EventCursor
    market: EventCursor
    side: Side
    quantity: Decimal
    available_quantity: Decimal
    bid: Decimal
    ask: Decimal
    rejection_probability: Decimal
    fill_probability: Decimal
    partial_fill_probability: Decimal
    market_open: bool
    costs: SimulatedCosts

    def __post_init__(self) -> None:
        if type(self.submitted) is not EventCursor or type(self.market) is not EventCursor:
            raise DomainValidationError("submitted and market must be EventCursor values")
        _require_exact_bool(self.market_open, "market_open")
        require_bounded_decimal(self.quantity, "quantity", positive=True)
        require_bounded_decimal(self.available_quantity, "available_quantity", nonnegative=True)
        _validate_execution_inputs(side=self.side, bid=self.bid, ask=self.ask, costs=self.costs)
        for field_name, probability in (
            ("rejection_probability", self.rejection_probability),
            ("fill_probability", self.fill_probability),
            ("partial_fill_probability", self.partial_fill_probability),
        ):
            require_bounded_decimal(probability, field_name, nonnegative=True)
            if probability > 1:
                raise InvalidDecimal(f"{field_name} must not exceed one")


@dataclass(frozen=True, slots=True)
class PlannedFill:
    quantity: Decimal
    price: Decimal
    fee: Decimal


@dataclass(frozen=True, slots=True)
class FillPlan:
    fills: tuple[PlannedFill, ...]
    rejected: bool
    reason_code: str


def _draw(rng: random.Random) -> Decimal:
    return Decimal(rng.getrandbits(53)) / Decimal(2**53)


class FillModel:
    def evaluate(self, request: FillRequest, *, rng: random.Random) -> FillPlan:
        if request.market.sequence <= request.submitted.sequence:
            return FillPlan((), False, "same_event_fill_forbidden")
        if not request.market_open:
            return FillPlan((), False, "market_closed")
        if _draw(rng) < request.rejection_probability:
            return FillPlan((), True, "simulated_rejection")
        if _draw(rng) >= request.fill_probability:
            return FillPlan((), False, "no_fill")
        quantity = min(request.quantity, request.available_quantity)
        if quantity <= 0:
            return FillPlan((), False, "no_liquidity")
        if quantity == request.quantity and _draw(rng) < request.partial_fill_probability:
            quantity = request.quantity / Decimal("2")
        price = execution_price(
            side=request.side, bid=request.bid, ask=request.ask, costs=request.costs
        )
        fill = PlannedFill(quantity, price, execution_fee(quantity, price, request.costs))
        return FillPlan((fill,), False, "partial_fill" if quantity < request.quantity else "filled")


__all__ = ["FillModel", "FillPlan", "FillRequest", "PlannedFill"]
