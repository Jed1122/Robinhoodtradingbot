"""Deterministic correlation-group exposure aggregation."""

from decimal import Decimal, localcontext
from typing import Final

from trading_bot.domain import DomainValidationError, require_bounded_decimal
from trading_bot.domain.decimal_utils import MAX_CANONICAL_DECIMAL_TEXT_LENGTH

_ARITHMETIC_PRECISION: Final = MAX_CANONICAL_DECIMAL_TEXT_LENGTH * 4


def aggregate_correlated_exposure(notionals: tuple[Decimal, ...]) -> Decimal:
    """Sum a complete immutable group of nonnegative position notionals."""

    if type(notionals) is not tuple:
        raise DomainValidationError("notionals must be an exact immutable tuple")
    with localcontext() as context:
        context.prec = max(context.prec, _ARITHMETIC_PRECISION)
        total = Decimal("0")
        for notional in notionals:
            total += require_bounded_decimal(
                notional,
                "notional",
                nonnegative=True,
            )
    return require_bounded_decimal(total, "correlated_group_exposure", nonnegative=True)


__all__ = ["aggregate_correlated_exposure"]
