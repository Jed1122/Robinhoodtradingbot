"""Exact simulated spread, slippage, and fee arithmetic."""

from dataclasses import dataclass
from decimal import Decimal

from trading_bot.domain import Side


@dataclass(frozen=True, slots=True)
class SimulatedCosts:
    slippage_pct: Decimal
    fee_pct: Decimal
    commission: Decimal


def execution_price(*, side: Side, bid: Decimal, ask: Decimal, costs: SimulatedCosts) -> Decimal:
    base = ask if side is Side.BUY else bid
    direction = Decimal("1") if side is Side.BUY else Decimal("-1")
    return base * (Decimal("1") + direction * costs.slippage_pct / Decimal("100"))


def execution_fee(quantity: Decimal, price: Decimal, costs: SimulatedCosts) -> Decimal:
    return quantity * price * costs.fee_pct / Decimal("100") + costs.commission


__all__ = ["SimulatedCosts", "execution_fee", "execution_price"]
