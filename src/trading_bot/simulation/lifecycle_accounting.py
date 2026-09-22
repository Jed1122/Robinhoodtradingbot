"""Checked offline arithmetic; deliberately not a pretrade risk evaluator."""

from dataclasses import dataclass
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    Underflow,
    localcontext,
)

from trading_bot.domain import Fill, Position, Side
from trading_bot.domain.decimal_utils import require_bounded_decimal
from trading_bot.execution.partial_fills import apply_fill
from trading_bot.simulation.lifecycle_models import (
    LifecycleErrorReason,
    LifecycleSnapshot,
    LifecycleValidationError,
    deny,
    validate_position,
)


@dataclass(frozen=True, slots=True)
class FillAccounting:
    position: Position
    filled_quantity: Decimal
    remaining_quantity: Decimal
    cash: Decimal
    fees: Decimal


def _context(*, exact: bool) -> Context:
    context = Context(
        prec=28,
        rounding=ROUND_HALF_EVEN,
        Emin=-999999,
        Emax=999999,
        capitals=1,
        clamp=0,
    )
    for signal in context.traps:
        context.traps[signal] = signal in {
            InvalidOperation,
            DivisionByZero,
            Overflow,
            Underflow,
        }
    context.traps[Inexact] = exact
    context.clear_flags()
    return context


def apply_lifecycle_fill(snapshot: LifecycleSnapshot, fill: Fill) -> FillAccounting:
    """Apply one already-deduplicated execution without mutating any inputs."""
    try:
        return _apply(snapshot, fill)
    except LifecycleValidationError:
        raise
    except (ValueError, DecimalException):
        deny(LifecycleErrorReason.ACCOUNTING)


def _apply(snapshot: LifecycleSnapshot, fill: Fill) -> FillAccounting:
    if type(snapshot) is not LifecycleSnapshot or type(fill) is not Fill:
        deny(LifecycleErrorReason.INPUT)
    snapshot.__post_init__()
    fill.__post_init__()
    for value in (fill.quantity, fill.price):
        require_bounded_decimal(value, "fill_value", positive=True)
    require_bounded_decimal(fill.fee, "fee", nonnegative=True)
    order = snapshot.order
    if (
        fill.account_id != order.account_id
        or fill.instrument_id != order.instrument_id
        or fill.broker_order_id != order.broker_order_id
        or fill.side is not order.side
    ):
        deny(LifecycleErrorReason.IDENTITY)
    if order.limit_price is None or (
        (fill.side is Side.BUY and fill.price > order.limit_price)
        or (fill.side is Side.SELL and fill.price < order.limit_price)
    ):
        deny(LifecycleErrorReason.ACCOUNTING)
    # Precision is a versioned format contract. Money and quantities never round.
    with localcontext(_context(exact=True)):
        filled = order.filled_quantity + fill.quantity
        remaining = order.requested_quantity - filled
        quantity = snapshot.position.quantity + (
            fill.quantity if fill.side is Side.BUY else -fill.quantity
        )
        gross = fill.quantity * fill.price
        cash_delta = -(gross + fill.fee) if fill.side is Side.BUY else gross - fill.fee
        cash = snapshot.cash + cash_delta
        fees = snapshot.fees + fill.fee
        mark = quantity * fill.price
        for amount in (filled, remaining, quantity, cash, fees, mark):
            require_bounded_decimal(amount, "accounting_value", nonnegative=True)
    # Only the existing helper's weighted average may round. Exact deltas are checked below.
    with localcontext(_context(exact=False)):
        application = apply_fill(position=snapshot.position, order=order, fill=fill)
    if (
        not application.applied
        or application.remaining_quantity != remaining
        or application.cash_delta != cash_delta
        or application.fee_delta != fill.fee
        or application.position.quantity != quantity
        or application.position.market_value != mark
    ):
        deny(LifecycleErrorReason.ACCOUNTING)
    validate_position(application.position)
    return FillAccounting(application.position, filled, remaining, cash, fees)
