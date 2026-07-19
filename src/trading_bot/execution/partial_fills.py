"""Exact partial-fill accounting with stable external fill deduplication."""

from dataclasses import dataclass, replace
from decimal import Decimal

from trading_bot.domain import BrokerOrder, Fill, Position, Side


@dataclass(frozen=True, slots=True)
class FillApplication:
    position: Position
    remaining_quantity: Decimal
    cash_delta: Decimal
    fee_delta: Decimal
    applied: bool


def apply_fill(
    *,
    position: Position,
    order: BrokerOrder,
    fill: Fill,
    applied_fill_ids: frozenset[str] = frozenset(),
) -> FillApplication:
    """Apply only the actual execution quantity, never the requested quantity."""
    if fill.broker_order_id != order.broker_order_id:
        raise ValueError("fill does not belong to order")
    remaining = order.requested_quantity - order.filled_quantity - fill.quantity
    if remaining < 0:
        raise ValueError("fill exceeds remaining order quantity")
    if str(fill.id) in applied_fill_ids:
        return FillApplication(
            position,
            order.requested_quantity - order.filled_quantity,
            Decimal("0"),
            Decimal("0"),
            False,
        )
    signed = fill.quantity if fill.side is Side.BUY else -fill.quantity
    quantity = position.quantity + signed
    if quantity < 0:
        raise ValueError("fill would create a short position")
    average = position.average_price
    if fill.side is Side.BUY:
        prior_cost = position.quantity * (average or Decimal("0"))
        average = (prior_cost + fill.quantity * fill.price) / quantity
    elif quantity == 0:
        average = None
    updated = replace(
        position,
        quantity=quantity,
        average_price=average,
        market_value=quantity * fill.price,
        observed_at=fill.occurred_at,
        data_hash=fill.data_hash,
    )
    cash_delta = -(fill.quantity * fill.price + fill.fee)
    if fill.side is Side.SELL:
        cash_delta = fill.quantity * fill.price - fill.fee
    return FillApplication(updated, remaining, cash_delta, fill.fee, True)


__all__ = ["FillApplication", "apply_fill"]
