"""Bounded synthetic account reconstruction; no risk or execution authority.

Recompute from original event prefixes rather than adopting caller snapshots.
This layer owns cash/holdings/fees/settlement only. Canonical entry admission,
corporate actions, loss latches and durable publication are separate composition.
"""

from dataclasses import dataclass, field, replace
from decimal import Context, Decimal, DecimalException, localcontext
from typing import NoReturn

from trading_bot.domain import AssetClass, DataHash, Side, require_bounded_decimal
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation.etf_capital_funding import (
    capital_available_cash,
    capital_order_reservation,
)
from trading_bot.simulation.events import EventCursor
from trading_bot.simulation.lifecycle import replay_order_lifecycle
from trading_bot.simulation.lifecycle_models import (
    LifecycleControlEvent,
    LifecycleFillEvent,
    LifecycleRequest,
    LifecycleResult,
    validate_cursor,
)

_ZERO = Decimal("0")
_CONTEXT = Context(prec=2048)
_TIERS = tuple(map(Decimal, ("100", "250", "500", "1000", "5000", "10000")))
_SYMBOLS = ("SPY", "QQQ", "IWM", "SHY", "IEF")


def _deny() -> NoReturn:
    raise ValueError("capital_account_invalid") from None


@dataclass(frozen=True, slots=True)
class CapitalAccountSubmission:
    symbol: str
    request: LifecycleRequest
    episode_fee_bound: Decimal
    execution_enabled: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.symbol) is not str or self.symbol not in _SYMBOLS:
            _deny()
        if type(self.request) is not LifecycleRequest:
            _deny()
        self.request.__post_init__()
        require_bounded_decimal(self.episode_fee_bound, "fee_bound", nonnegative=True)
        if (
            self.request.events
            or self.request.order.instrument_id != "capital-research:" + self.symbol
            or self.request.position.asset_class is not AssetClass.EQUITY
            or self.execution_enabled is not False
        ):
            _deny()


@dataclass(frozen=True, slots=True)
class CapitalSaleSettlement:
    event_id: str
    cursor: EventCursor
    fill_id: str

    def __post_init__(self) -> None:
        validate_cursor(self.cursor)
        if any(
            type(value) is not str or not 0 < len(value) <= 256
            for value in (self.event_id, self.fill_id)
        ):
            _deny()


@dataclass(frozen=True, slots=True)
class CapitalFeesFinal:
    event_id: str
    cursor: EventCursor
    total_fees: Decimal

    def __post_init__(self) -> None:
        validate_cursor(self.cursor)
        if type(self.event_id) is not str or not 0 < len(self.event_id) <= 256:
            _deny()
        require_bounded_decimal(self.total_fees, "total_fees", nonnegative=True)


type CapitalAccountEvent = (
    CapitalAccountSubmission
    | LifecycleControlEvent
    | LifecycleFillEvent
    | CapitalSaleSettlement
    | CapitalFeesFinal
)


@dataclass(frozen=True, slots=True)
class CapitalAccountReplay:
    cash: Decimal
    available_cash: Decimal
    quantity: Decimal
    fees: Decimal
    unsettled_proceeds: Decimal
    complete: bool
    economic_hash: DataHash
    execution_enabled: bool = field(default=False, init=False)
    evidence_promotable: bool = field(default=False, init=False)


def replay_capital_account(
    *, initial_cash: Decimal, events: tuple[CapitalAccountEvent, ...]
) -> CapitalAccountReplay:
    """Reconstruct one cash account from at most 4096 supplied events.

    Exact duplicate events are ignored; conflicting identifiers deny. Explicit
    final fees and settled sales are required to close an episode. An input end
    never forces a fill, settlement or reserve release. Replay is not admission,
    authenticated evidence, persistence, or deployed restart verification.
    """
    try:
        with localcontext(_CONTEXT):
            return _replay(initial_cash, events)
    except (ValueError, TypeError, DecimalException):
        _deny()


def _replay(initial: Decimal, events: tuple[CapitalAccountEvent, ...]) -> CapitalAccountReplay:
    require_bounded_decimal(initial, "initial_cash", positive=True)
    if initial not in _TIERS or type(events) is not tuple or len(events) > 4096:
        _deny()
    cash = initial
    fees = _ZERO
    quantity = _ZERO
    episode_fees = _ZERO
    fee_bound = _ZERO
    final = True
    request: LifecycleRequest | None = None
    current: LifecycleResult | None = None
    account_id: str | None = None
    symbol: str | None = None
    previous_cursor: EventCursor | None = None
    order_fees_before = _ZERO
    seen: dict[str, DataHash] = {}
    orders: set[str] = set()
    fills: set[str] = set()
    settlements: dict[str, Decimal] = {}
    digests: list[DataHash] = []
    for event in events:
        if type(event) not in (
            CapitalAccountSubmission,
            LifecycleControlEvent,
            LifecycleFillEvent,
            CapitalSaleSettlement,
            CapitalFeesFinal,
        ):
            _deny()
        event.__post_init__()
        if isinstance(event, CapitalAccountSubmission):
            cursor = event.request.submitted
            event_id = "submission:" + event.request.order.id
        else:
            cursor = event.cursor
            event_id = "event:" + event.event_id
        digest = content_hash({"namespace": "capital-account-event-v1", "event": event})
        if event_id in seen:
            if seen[event_id] != digest:
                _deny()
            continue
        if previous_cursor is not None and (
            cursor.sequence <= previous_cursor.sequence
            or cursor.occurred_at < previous_cursor.occurred_at
        ):
            _deny()
        if isinstance(event, CapitalAccountSubmission):
            proposed = event.request
            if current is not None and not current.order_terminal:
                _deny()
            if proposed.order.broker_order_id in orders:
                _deny()
            if account_id is not None and proposed.order.account_id != account_id:
                _deny()
            if proposed.cash != cash or proposed.position.quantity != quantity:
                _deny()
            if quantity != 0 and (
                current is None
                or proposed.position.average_price != current.snapshot.position.average_price
                or event.symbol != symbol
            ):
                _deny()
            if proposed.order.side is Side.BUY:
                if quantity != 0 or not final or settlements:
                    _deny()
                episode_fees = _ZERO
                fee_bound = event.episode_fee_bound
                final = False
                symbol = event.symbol
            elif (
                quantity == 0
                or event.symbol != symbol
                or event.episode_fee_bound != fee_bound
                or proposed.order.requested_quantity > quantity
            ):
                _deny()
            request = proposed
            current = replay_order_lifecycle(request)
            order_fees_before = episode_fees
            account_id = proposed.order.account_id
            orders.add(proposed.order.broker_order_id)
        elif isinstance(event, (LifecycleControlEvent, LifecycleFillEvent)):
            if request is None or current is None or final:
                _deny()
            if isinstance(event, LifecycleFillEvent):
                if event.fill.id in fills:
                    _deny()
                fills.add(event.fill.id)
            request = replace(request, events=(*request.events, event))
            updated = replay_order_lifecycle(request)
            fees += updated.snapshot.fees - current.snapshot.fees
            episode_fees = order_fees_before + updated.snapshot.fees
            cash = updated.snapshot.cash
            quantity = updated.snapshot.position.quantity
            current = updated
            if isinstance(event, LifecycleFillEvent) and event.fill.side is Side.SELL:
                proceeds = event.fill.quantity * event.fill.price - event.fill.fee
                require_bounded_decimal(proceeds, "sale_proceeds", nonnegative=True)
                settlements[event.fill.id] = proceeds
        elif isinstance(event, CapitalSaleSettlement):
            if event.fill_id not in settlements:
                _deny()
            del settlements[event.fill_id]
        else:
            if (
                final
                or current is None
                or not current.order_terminal
                or quantity != 0
                or settlements
                or event.total_fees != episode_fees
            ):
                _deny()
            final = True
        # Recompute authoritative capacity after every unique event. Never adopt
        # an externally supplied reservation or release it on end-of-input.
        if current is not None:
            reservation = capital_order_reservation(
                order=current.snapshot.order,
                episode_fee_bound=fee_bound,
                episode_fees=episode_fees,
                episode_fees_final=final,
                held_quantity=quantity,
            )
            capital_available_cash(cash, sum(settlements.values(), _ZERO), reservation)
        seen[event_id] = digest
        previous_cursor = cursor
        digests.append(digest)
    unsettled = sum(settlements.values(), _ZERO)
    available = cash
    if current is not None:
        reservation = capital_order_reservation(
            order=current.snapshot.order,
            episode_fee_bound=fee_bound,
            episode_fees=episode_fees,
            episode_fees_final=final,
            held_quantity=quantity,
        )
        available = capital_available_cash(cash, unsettled, reservation)
    return CapitalAccountReplay(
        cash,
        available,
        quantity,
        fees,
        unsettled,
        final and quantity == 0 and not settlements,
        content_hash(
            {
                "namespace": "capital-account-replay-v1",
                "initial": initial,
                "applied": tuple(digests),
            }
        ),
    )
