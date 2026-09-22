"""Exact package terminal-payoff research, not execution or account-risk admission.

Bounds assume all legs survive to a common expiry and settle at the same underlying
value. They exclude early assignment, exercise liquidity, pin risk and broken packages;
those lifecycle liabilities can exceed the terminal bound. No margin rule is inferred.
"""

from dataclasses import dataclass
from decimal import Decimal, localcontext

from trading_bot.domain.decimal_utils import DomainValidationError, require_bounded_decimal
from trading_bot.domain.enums import Side
from trading_bot.domain.options import OptionKind, OptionsOrderIntent, PositionEffect


@dataclass(frozen=True, slots=True)
class PayoffBounds:
    max_loss: Decimal
    max_profit: Decimal | None


def _validate(intent: OptionsOrderIntent, total_fees: Decimal) -> None:
    if type(intent) is not OptionsOrderIntent:
        raise DomainValidationError("exact options intent required")
    if intent.structure.legs[0].effect is not PositionEffect.OPEN:
        raise DomainValidationError("terminal payoff requires an opening intent")
    require_bounded_decimal(total_fees, "complete episode fee bound", nonnegative=True)


def terminal_pnl(intent: OptionsOrderIntent, *, spot: Decimal, total_fees: Decimal) -> Decimal:
    """Net episode cash including the package premium and fee bound exactly once.

    Use the premium actually paid/received (already reflecting execution spread/slippage).
    Subtracting an additional spread charge here would double-count execution costs.
    """
    _validate(intent, total_fees)
    require_bounded_decimal(spot, "expiry underlying value", nonnegative=True)
    with localcontext() as context:
        context.prec = 4096
        multiplier = intent.structure.legs[0].contract.premium_multiplier
        entry = intent.limit_price * multiplier * intent.quantity
        result = -entry if intent.net_effect == "debit" else entry
        for leg in intent.structure.legs:
            difference = spot - leg.contract.strike
            intrinsic = max(
                Decimal(0), difference if leg.contract.kind is OptionKind.CALL else -difference
            )
            payoff = intrinsic * leg.contract.premium_multiplier * intent.quantity * leg.ratio
            result += payoff if leg.opening_side is Side.BUY else -payoff
        return result - total_fees


def payoff_bounds(intent: OptionsOrderIntent, *, total_fees: Decimal) -> PayoffBounds:
    """Evaluate every piecewise-linear vertex and the right-tail slope exactly."""
    _validate(intent, total_fees)
    vertices = {Decimal(0), *(leg.contract.strike for leg in intent.structure.legs)}
    values = [terminal_pnl(intent, spot=spot, total_fees=total_fees) for spot in vertices]
    with localcontext() as context:
        context.prec = 4096
        tail_slope = sum(
            (
                leg.contract.premium_multiplier
                * leg.ratio
                * intent.quantity
                * (1 if leg.opening_side is Side.BUY else -1)
                for leg in intent.structure.legs
                if leg.contract.kind is OptionKind.CALL
            ),
            Decimal(0),
        )
        if tail_slope < 0:
            # Currently unreachable for validated supported structures; never turn an
            # unexpected unbounded short tail into a finite-risk result.
            raise DomainValidationError("unbounded loss structure is unsupported")
        return PayoffBounds(max(Decimal(0), -min(values)), None if tail_slope > 0 else max(values))
