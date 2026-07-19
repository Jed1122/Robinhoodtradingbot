"""Deterministic exposure regime classification."""

from decimal import Decimal


def regime_multiplier(*, price: Decimal, long_average: Decimal, drawdown_pct: Decimal) -> Decimal:
    if price < long_average or drawdown_pct <= Decimal("-20"):
        return Decimal("0")
    if drawdown_pct <= Decimal("-10"):
        return Decimal("0.5")
    return Decimal("1")


__all__ = ["regime_multiplier"]
