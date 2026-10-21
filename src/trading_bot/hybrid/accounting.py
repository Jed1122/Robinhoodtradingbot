"""Pure lot accounting and exit quantities. No price prediction or broker calls."""

from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.hybrid.models import Disposal, Lot, Sleeve


def _number(value: Decimal, *, positive: bool = False) -> None:
    if type(value) is not Decimal or not value.is_finite() or value < 0 or (positive and not value):
        raise ValueError("a finite exact nonnegative decimal is required")


def buy_lot(
    lot_id: str,
    symbol: str,
    sleeve: Sleeve,
    quantity: Decimal,
    price: Decimal,
    at: datetime,
    fee: Decimal = Decimal(0),
) -> Lot:
    for value in (quantity, price):
        _number(value, positive=True)
    _number(fee)
    return Lot(
        id=lot_id,
        symbol=symbol,
        sleeve=sleeve,
        quantity=quantity,
        basis=quantity * price + fee,
        acquired_at=require_utc(at),
    )


def dispose(
    lots: tuple[Lot, ...],
    quantity: Decimal,
    price: Decimal,
    at: datetime,
    *,
    fee: Decimal = Decimal(0),
    tax_rate: Decimal | None = None,
    selected_lots: tuple[str, ...] = (),
) -> Disposal:
    _number(quantity, positive=True)
    _number(price, positive=True)
    _number(fee)
    require_utc(at)
    if tax_rate is not None:
        _number(tax_rate)
        if tax_rate > 1:
            raise ValueError("tax rate must be a fraction")
    ids = {lot.id for lot in lots}
    if len(ids) != len(lots) or len({lot.symbol for lot in lots}) != 1:
        raise ValueError("lots must be unique and belong to one security")
    if len(set(selected_lots)) != len(selected_lots) or not set(selected_lots) <= ids:
        raise ValueError("invalid lot selection")
    if any(lot.acquired_at > at for lot in lots):
        raise ValueError("cannot dispose future acquisitions")
    eligible = sorted(
        (lot for lot in lots if not selected_lots or lot.id in selected_lots),
        key=lambda lot: (lot.acquired_at, lot.id),
    )
    if sum((lot.quantity for lot in eligible), Decimal(0)) < quantity:
        raise ValueError("insufficient owned quantity")
    remaining = {lot.id: lot for lot in lots}
    needed, basis, long_gain, short_gain = quantity, Decimal(0), Decimal(0), Decimal(0)
    for lot in eligible:
        if not needed:
            break
        taken = min(needed, lot.quantity)
        taken_basis = lot.basis * taken / lot.quantity
        piece_gain = taken * price - taken_basis - fee * taken / quantity
        # Tax holding periods are calendar based, including leap years.
        try:
            anniversary = lot.acquired_at.replace(year=lot.acquired_at.year + 1)
        except ValueError:
            anniversary = lot.acquired_at.replace(year=lot.acquired_at.year + 1, day=28)
        if at.date() > anniversary.date():
            long_gain += piece_gain
        else:
            short_gain += piece_gain
        basis += taken_basis
        needed -= taken
        if taken == lot.quantity:
            del remaining[lot.id]
        else:
            remaining[lot.id] = lot.model_copy(
                update={
                    "quantity": lot.quantity - taken,
                    "basis": lot.basis - taken_basis,
                }
            )
    proceeds = quantity * price - fee
    if proceeds < 0:
        raise ValueError("fee exceeds proceeds")
    gain = proceeds - basis
    return Disposal(
        lots=tuple(remaining.values()),
        proceeds=proceeds,
        disposed_basis=basis,
        gain=gain,
        short_term_gain=short_gain,
        long_term_gain=long_gain,
        tax_reserve=None if tax_rate is None else max(Decimal(0), gain) * tax_rate,
    )


def exit_quantity(
    method: Literal["principal", "partial_first", "partial_second", "trend"],
    quantity: Decimal,
    price: Decimal,
    allocation: Decimal,
    peak_price: Decimal,
    *,
    completed: bool = False,
    fractional: bool = True,
    original_quantity: Decimal | None = None,
    trigger_pct: Decimal = Decimal(15),
    trailing_pct: Decimal = Decimal(5),
) -> Decimal:
    for value in (quantity, price, allocation, peak_price):
        _number(value, positive=True)
    for value in (trigger_pct, trailing_pct):
        _number(value)
        if value > 100:
            raise ValueError("percentage outside supported bounds")
    if original_quantity is not None:
        _number(original_quantity, positive=True)
    if completed:
        return Decimal(0)
    value = quantity * price
    if method == "principal":
        sell = (
            (value - allocation) / price
            if value >= allocation * (1 + trigger_pct / 100)
            else Decimal(0)
        )
    elif method in ("partial_first", "partial_second"):
        original = original_quantity if original_quantity is not None else quantity
        target = Decimal("12.5") if method == "partial_first" else Decimal(20)
        sell = original / 4 if original * price >= allocation * (1 + target / 100) else Decimal(0)
    elif method == "trend":
        sell = quantity if price <= peak_price * (1 - trailing_pct / 100) else Decimal(0)
    else:
        raise ValueError("unknown exit method")
    return min(quantity, max(Decimal(0), sell)).quantize(
        Decimal(".000001") if fractional else Decimal(1),
        rounding=ROUND_DOWN,
    )


def wash_sale_conflicts(
    symbol: str, sold_at: datetime, purchases: tuple[Lot, ...]
) -> tuple[str, ...]:
    require_utc(sold_at)
    return tuple(
        lot.id
        for lot in purchases
        if lot.symbol == symbol and abs(lot.acquired_at - sold_at) <= timedelta(days=30)
    )
