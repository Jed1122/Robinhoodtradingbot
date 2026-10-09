"""Bounded offline funding arithmetic, not sizing or pretrade approval."""

from dataclasses import dataclass, field
from decimal import Context, Decimal, DecimalException, localcontext
from typing import NoReturn

from trading_bot.domain import BrokerOrder, DataHash, OrderState, OrderType, Side
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.recording import content_hash

_CONTEXT = Context(prec=2048)
_ACTIVE = frozenset(
    {
        OrderState.SUBMISSION_PENDING,
        OrderState.SUBMITTED,
        OrderState.PARTIALLY_FILLED,
        OrderState.CANCEL_PENDING,
        OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
    }
)
_TERMINAL = frozenset(
    {
        OrderState.FILLED,
        OrderState.CANCELED,
        OrderState.EXPIRED,
        OrderState.REJECTED,
    }
)


def _deny() -> NoReturn:
    raise ValueError("capital_funding_invalid") from None


@dataclass(frozen=True, slots=True)
class CapitalOrderReservation:
    """Informational single-order capacity; cannot authorize an entry."""

    input_hash: DataHash
    pending_notional: Decimal
    fee_reservation: Decimal
    total_reservation: Decimal
    execution_enabled: bool = field(default=False, init=False)
    evidence_promotable: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        try:
            _require_sha256_hex(self.input_hash, "input_hash")
            for value in (self.pending_notional, self.fee_reservation, self.total_reservation):
                require_bounded_decimal(value, "reservation", nonnegative=True)
            with localcontext(_CONTEXT):
                if self.total_reservation != self.pending_notional + self.fee_reservation:
                    _deny()
            if self.execution_enabled is not False or self.evidence_promotable is not False:
                _deny()
        except (ValueError, DecimalException):
            _deny()

    @property
    def reservation_hash(self) -> DataHash:
        self.__post_init__()
        return content_hash({"namespace": "capital-order-reservation-v1", "record": self})


def capital_order_reservation(
    *,
    order: BrokerOrder,
    episode_fee_bound: Decimal,
    episode_fees: Decimal,
    episode_fees_final: bool,
    held_quantity: Decimal,
) -> CapitalOrderReservation:
    """Keep unfilled limit notional and unused whole-episode fees unavailable.

    Inputs are supplied research observations, not broker-authenticated facts.
    Unknown/reconciling orders retain capacity. Terminality releases only the
    unfilled notional; final episode fees additionally require flat holdings.
    An account owner must independently validate identities, risk, quantities,
    chronology, settlement and exactly-once delivery before using this result.
    """
    try:
        if type(order) is not BrokerOrder or type(episode_fees_final) is not bool:
            _deny()
        order.__post_init__()
        for value in (episode_fee_bound, episode_fees, held_quantity):
            require_bounded_decimal(value, "episode_value", nonnegative=True)
        if order.order_type is not OrderType.LIMIT or order.limit_price is None:
            _deny()
        for value in (order.requested_quantity, order.limit_price):
            require_bounded_decimal(value, "order_value", positive=True)
        require_bounded_decimal(order.filled_quantity, "filled_quantity", nonnegative=True)
        if order.state not in _ACTIVE | _TERMINAL or episode_fees > episode_fee_bound:
            _deny()
        if order.state in {OrderState.SUBMISSION_PENDING, OrderState.REJECTED} and (
            order.filled_quantity != 0
        ):
            _deny()
        if episode_fees_final and (order.state in _ACTIVE or held_quantity != 0):
            _deny()
        with localcontext(_CONTEXT):
            if (
                order.side is Side.SELL
                and order.state in _ACTIVE
                and (order.requested_quantity - order.filled_quantity > held_quantity)
            ):
                _deny()
            pending = (
                (order.requested_quantity - order.filled_quantity) * order.limit_price
                if order.side is Side.BUY and order.state in _ACTIVE
                else Decimal("0")
            )
            fees = Decimal("0") if episode_fees_final else episode_fee_bound - episode_fees
            return CapitalOrderReservation(
                content_hash(
                    {
                        "namespace": "capital-funding-input-v1",
                        "order": order,
                        "episode_fee_bound": episode_fee_bound,
                        "episode_fees": episode_fees,
                        "episode_fees_final": episode_fees_final,
                        "held_quantity": held_quantity,
                    }
                ),
                pending,
                fees,
                pending + fees,
            )
    except (ValueError, TypeError, DecimalException):
        _deny()


def capital_available_cash(
    cash: Decimal,
    unsettled_proceeds: Decimal,
    reservation: CapitalOrderReservation,
) -> Decimal:
    """Subtract explicit unsettled sale proceeds and one current reservation.

    Cash is total economic cash. Unknown settlement must be represented by its
    unreleased amount, not zero. This function is not an account-wide source
    completeness check, cash-floor decision, order admission or broker balance.
    """
    try:
        if type(reservation) is not CapitalOrderReservation:
            _deny()
        reservation.__post_init__()
        for value in (cash, unsettled_proceeds):
            require_bounded_decimal(value, "cash", nonnegative=True)
        with localcontext(_CONTEXT):
            available = cash - unsettled_proceeds - reservation.total_reservation
        require_bounded_decimal(available, "available_cash", nonnegative=True)
        return available
    except (ValueError, TypeError, DecimalException):
        _deny()
