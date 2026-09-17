"""Exact simulated spread, slippage, and fee arithmetic."""

from dataclasses import dataclass
from decimal import Decimal, DecimalException

from trading_bot.clock import DomainValidationError
from trading_bot.domain import Side
from trading_bot.domain.decimal_utils import (
    InvalidDecimal,
    _require_exact_enum,
    require_bounded_decimal,
)


@dataclass(frozen=True, slots=True)
class SimulatedCosts:
    slippage_pct: Decimal
    fee_pct: Decimal
    commission: Decimal

    def __post_init__(self) -> None:
        require_bounded_decimal(self.slippage_pct, "slippage_pct", nonnegative=True)
        require_bounded_decimal(self.fee_pct, "fee_pct", nonnegative=True)
        require_bounded_decimal(self.commission, "commission", nonnegative=True)


def _validate_execution_inputs(
    *, side: Side, bid: Decimal, ask: Decimal, costs: SimulatedCosts
) -> None:
    _require_exact_enum(side, Side, "side")
    require_bounded_decimal(bid, "bid", positive=True)
    require_bounded_decimal(ask, "ask", positive=True)
    if bid > ask:
        raise DomainValidationError("bid must not exceed ask")
    if type(costs) is not SimulatedCosts:
        raise DomainValidationError("costs must be SimulatedCosts")


def execution_price(*, side: Side, bid: Decimal, ask: Decimal, costs: SimulatedCosts) -> Decimal:
    _validate_execution_inputs(side=side, bid=bid, ask=ask, costs=costs)
    base = ask if side is Side.BUY else bid
    direction = Decimal("1") if side is Side.BUY else Decimal("-1")
    try:
        price = base * (Decimal("1") + direction * costs.slippage_pct / Decimal("100"))
    except DecimalException as exc:
        raise InvalidDecimal("execution price cannot be represented safely") from exc
    return require_bounded_decimal(price, "execution_price", positive=True)


def execution_fee(quantity: Decimal, price: Decimal, costs: SimulatedCosts) -> Decimal:
    require_bounded_decimal(quantity, "quantity", positive=True)
    require_bounded_decimal(price, "price", positive=True)
    if type(costs) is not SimulatedCosts:
        raise DomainValidationError("costs must be SimulatedCosts")
    try:
        fee = quantity * price * costs.fee_pct / Decimal("100") + costs.commission
    except DecimalException as exc:
        raise InvalidDecimal("execution fee cannot be represented safely") from exc
    return require_bounded_decimal(fee, "execution_fee", nonnegative=True)


__all__ = ["SimulatedCosts", "execution_fee", "execution_price"]
