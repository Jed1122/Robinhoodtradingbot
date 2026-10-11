"""Bounded synthetic account reconstruction; no risk or execution authority.

Recompute from original event prefixes rather than adopting caller snapshots.
This layer owns cash/holdings/fees/settlement and opt-in v3 declared actions.
Canonical entry admission, joint loss latches and durable publication remain
separate composition; none of these records grants execution authority.
"""

from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Context, Decimal, DecimalException, localcontext
from fractions import Fraction
from typing import NoReturn

from trading_bot.domain import AssetClass, DataHash, Side, require_bounded_decimal
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.simulation.etf_capital_action_events import (
    CapitalActionEvent,
)
from trading_bot.simulation.etf_capital_action_events import (
    CapitalDistributionEntitled as CapitalDistributionEntitled,
)
from trading_bot.simulation.etf_capital_action_events import (
    CapitalDistributionPaid as CapitalDistributionPaid,
)
from trading_bot.simulation.etf_capital_action_events import (
    CapitalSplitApplied as CapitalSplitApplied,
)
from trading_bot.simulation.etf_capital_funding import (
    _capital_order_reservation,
    capital_available_cash,
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


def _identifier(value: str) -> None:
    if type(value) is not str or not value.strip() or not 0 < len(value) <= 256:
        _deny()


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
        for value in (
            self.request.order.id,
            self.request.order.broker_order_id,
            self.request.order.account_id,
            self.request.order.instrument_id,
        ):
            _identifier(value)
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
    """Historical unbound v1 evidence; never current finality authority."""

    event_id: str
    cursor: EventCursor
    total_fees: Decimal

    def __post_init__(self) -> None:
        validate_cursor(self.cursor)
        if type(self.event_id) is not str or not 0 < len(self.event_id) <= 256:
            _deny()
        require_bounded_decimal(self.total_fees, "total_fees", nonnegative=True)


@dataclass(frozen=True, slots=True)
class CapitalEpisodeFeesFinal:
    event_id: str
    cursor: EventCursor
    total_fees: Decimal
    account_id: str
    opening_order_id: str

    def __post_init__(self) -> None:
        validate_cursor(self.cursor)
        for value in (self.event_id, self.account_id, self.opening_order_id):
            _identifier(value)
        require_bounded_decimal(self.total_fees, "total_fees", nonnegative=True)


type CapitalAccountEvent = (
    CapitalAccountSubmission
    | LifecycleControlEvent
    | LifecycleFillEvent
    | CapitalSaleSettlement
    | CapitalFeesFinal
    | CapitalEpisodeFeesFinal
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


@dataclass(frozen=True, slots=True)
class CapitalActionAccountReplay(CapitalAccountReplay):
    average_price: Decimal | None
    distribution_receivable: Decimal
    mark: Decimal | None
    marked_equity: Decimal | None
    source_qualified: bool = field(default=False, init=False)


def replay_capital_action_account(
    *, initial_cash: Decimal, events: tuple[CapitalAccountEvent | CapitalActionEvent, ...]
) -> CapitalActionAccountReplay:
    """Opt-in v3 action replay through the original account reducer, offline only."""
    try:
        with localcontext(_CONTEXT):
            result = _replay(initial_cash, events, actions=True)
            if type(result) is not CapitalActionAccountReplay:
                _deny()
            return result
    except (ValueError, TypeError, DecimalException):
        _deny()


def replay_capital_action_account_prefixes(
    *, initial_cash: Decimal, events: tuple[CapitalAccountEvent | CapitalActionEvent, ...]
) -> tuple[CapitalActionAccountReplay, ...]:
    """Validate all originals once, then return immutable aligned v3 prefixes.

    Genesis and duplicate deliveries retain their own tuple positions. No
    result escapes if any later event is invalid; saved balances are not input.
    """
    try:
        with localcontext(_CONTEXT):
            prefixes: list[CapitalAccountReplay] = []
            _replay(initial_cash, events, prefixes, actions=True)
            results: list[CapitalActionAccountReplay] = []
            for prefix in prefixes:
                if type(prefix) is not CapitalActionAccountReplay:
                    _deny()
                results.append(prefix)
            return tuple(results)
    except (ValueError, TypeError, DecimalException):
        _deny()


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


def replay_capital_account_v1(
    *, initial_cash: Decimal, events: tuple[CapitalAccountEvent, ...]
) -> CapitalAccountReplay:
    """Explicit historical reader only; unbound records cannot feed current owners."""
    try:
        with localcontext(_CONTEXT):
            return _replay(initial_cash, events, legacy=True)
    except (ValueError, TypeError, DecimalException):
        _deny()


def replay_capital_account_prefixes(
    *, initial_cash: Decimal, events: tuple[CapitalAccountEvent, ...]
) -> tuple[CapitalAccountReplay, ...]:
    """Reconstruct all original prefixes through the same validated reducer.

    The complete source is validated before returning anything. The owned tuple
    includes genesis and one result per supplied event, including exact duplicate
    delivery. Historical v1 identities and monetary semantics are unchanged.
    """
    try:
        with localcontext(_CONTEXT):
            prefixes: list[CapitalAccountReplay] = []
            _replay(initial_cash, events, prefixes)
            return tuple(prefixes)
    except (ValueError, TypeError, DecimalException):
        _deny()


@dataclass(slots=True)
class _AccountState:
    """One canonical reducer's locals; never accepted by a public frontend."""

    cash: Decimal
    fees: Decimal = _ZERO
    quantity: Decimal = _ZERO
    episode_fees: Decimal = _ZERO
    fee_bound: Decimal = _ZERO
    final: bool = True
    request: LifecycleRequest | None = None
    current: LifecycleResult | None = None
    account_id: str | None = None
    symbol: str | None = None
    opening_order_id: str | None = None
    previous_cursor: EventCursor | None = None
    order_fees_before: Decimal = _ZERO
    seen: dict[str, DataHash] = field(default_factory=dict)
    orders: set[str] = field(default_factory=set)
    fills: set[str] = field(default_factory=set)
    settlements: dict[str, Decimal] = field(default_factory=dict)
    digests: list[DataHash] = field(default_factory=list)
    average_price: Decimal | None = None
    mark: Decimal | None = None
    entitlements: dict[str, tuple[Decimal, CapitalDistributionEntitled]] = field(
        default_factory=dict
    )
    action_ids: set[str] = field(default_factory=set)
    adjusted: bool = False


@dataclass(frozen=True, slots=True)
class _AccountProgress:
    binding: str
    originals: tuple[str, ...]
    state: _AccountState | None
    prefixes: tuple[CapitalAccountReplay, ...]


def _admit_event(
    event: CapitalAccountEvent | CapitalActionEvent, *, legacy: bool, actions: bool
) -> tuple[EventCursor, str]:
    """Validate ORIGINAL records before hashing, copying, or prefix comparison."""
    if type(event) not in (
        CapitalAccountSubmission,
        LifecycleControlEvent,
        LifecycleFillEvent,
        CapitalSaleSettlement,
        CapitalFeesFinal,
        CapitalEpisodeFeesFinal,
        CapitalSplitApplied,
        CapitalDistributionEntitled,
        CapitalDistributionPaid,
    ):
        _deny()
    if not actions and type(event) in (
        CapitalSplitApplied,
        CapitalDistributionEntitled,
        CapitalDistributionPaid,
    ):
        _deny()
    if (isinstance(event, CapitalFeesFinal) and not legacy) or (
        isinstance(event, CapitalEpisodeFeesFinal) and legacy
    ):
        _deny()
    event.__post_init__()
    if isinstance(event, CapitalAccountSubmission):
        if not legacy:
            for optional_id in (
                event.request.order.intent_id,
                event.request.order.client_order_id,
            ):
                if optional_id is not None:
                    _identifier(optional_id)
        return event.request.submitted, "submission:" + event.request.order.id
    _identifier(event.event_id)
    if isinstance(event, LifecycleFillEvent):
        for value in (
            event.fill.id,
            event.fill.account_id,
            event.fill.instrument_id,
            event.fill.broker_order_id,
        ):
            _identifier(value)
    elif isinstance(event, LifecycleControlEvent):
        for value in (event.account_id, event.instrument_id, event.broker_order_id):
            _identifier(value)
    return event.cursor, "event:" + event.event_id


def _account_prefixes_owned(
    progress: _AccountProgress | None,
    *,
    initial_cash: Decimal,
    events: tuple[CapitalAccountEvent | CapitalActionEvent, ...],
    actions: bool,
) -> tuple[_AccountProgress, tuple[CapitalAccountReplay, ...]]:
    """Prepare a detached transaction; only the owner may publish its success."""
    try:
        with localcontext(_CONTEXT):
            require_bounded_decimal(initial_cash, "initial_cash", positive=True)
            if (
                initial_cash not in _TIERS
                or type(events) is not tuple
                or len(events) > 4096
                or type(actions) is not bool
                or (progress is not None and type(progress) is not _AccountProgress)
            ):
                _deny()
            originals = []
            inert_clocks = True
            for event in events:
                _admit_event(event, legacy=False, actions=actions)
                inert_clocks = _inert_event_clocks(event) and inert_clocks
                originals.append(canonical_json(event))
            original_values = tuple(originals)
            binding = canonical_json(
                {"initial_representation": initial_cash.as_tuple(), "actions": actions}
            )
            if not inert_clocks:
                # Valid zero-offset tzinfo objects may have transforming copy
                # hooks. Preserve original batch acceptance/hash semantics; do
                # not retain their mutable graphs or copy them before replay.
                batch: list[CapitalAccountReplay] = []
                _replay(initial_cash, events, batch, actions=actions)
                values = tuple(batch)
                return _AccountProgress(binding, original_values, None, values), deepcopy(values)
            reusable = (
                progress is not None
                and progress.state is not None
                and progress.binding == binding
                and len(progress.originals) <= len(original_values)
                and original_values[: len(progress.originals)] == progress.originals
            )
            count = len(progress.originals) if reusable and progress is not None else 0
            # Clone the ENTIRE candidate, not just its cursor/seen map. Invalid
            # late events may already have changed fills, actions or entitlements.
            state = deepcopy(progress.state) if reusable and progress is not None else None
            completed: list[_AccountState] = []
            suffix_prefixes: list[CapitalAccountReplay] = []
            _replay(
                initial_cash,
                deepcopy(events[count:]),
                suffix_prefixes,
                actions=actions,
                _resume=state,
                _completed=completed,
            )
            prefixes = (
                progress.prefixes + tuple(suffix_prefixes[1:])
                if reusable and progress is not None
                else tuple(suffix_prefixes)
            )
            candidate = _AccountProgress(binding, original_values, completed[0], prefixes)
            # No original or returned nested record aliases the retained state.
            return candidate, deepcopy(prefixes)
    except (ValueError, TypeError, DecimalException, AttributeError):
        _deny()


def _inert_event_clocks(event: CapitalAccountEvent | CapitalActionEvent) -> bool:
    """Continuation eligibility only; never narrow public original admission."""
    clocks: tuple[datetime, ...]
    if isinstance(event, CapitalAccountSubmission):
        clocks = (
            event.request.submitted.occurred_at,
            event.request.order.created_at,
            event.request.order.updated_at,
            event.request.position.observed_at,
        )
    elif isinstance(event, LifecycleFillEvent):
        clocks = (event.cursor.occurred_at, event.fill.occurred_at)
    else:
        clocks = (event.cursor.occurred_at,)
    return all(type(clock) is datetime and clock.tzinfo is UTC for clock in clocks)


def _replay(
    initial: Decimal,
    events: tuple[CapitalAccountEvent | CapitalActionEvent, ...],
    prefixes: list[CapitalAccountReplay] | None = None,
    *,
    legacy: bool = False,
    actions: bool = False,
    _resume: _AccountState | None = None,
    _completed: list[_AccountState] | None = None,
) -> CapitalAccountReplay:
    require_bounded_decimal(initial, "initial_cash", positive=True)
    if initial not in _TIERS or type(events) is not tuple or len(events) > 4096:
        _deny()
    state = _AccountState(initial) if _resume is None else _resume
    cash, fees, quantity = state.cash, state.fees, state.quantity
    episode_fees, fee_bound, final = state.episode_fees, state.fee_bound, state.final
    request, current = state.request, state.current
    account_id, symbol, opening_order_id = state.account_id, state.symbol, state.opening_order_id
    previous_cursor, order_fees_before = state.previous_cursor, state.order_fees_before
    seen, orders, fills = state.seen, state.orders, state.fills
    settlements, digests = state.settlements, state.digests
    average_price, mark = state.average_price, state.mark
    entitlements, action_ids, adjusted = state.entitlements, state.action_ids, state.adjusted
    version = "v1" if legacy else "v3" if actions else "v2"

    def receivable_total() -> Decimal:
        total = sum((row[0] for row in entitlements.values()), _ZERO)
        require_bounded_decimal(total, "distribution_receivable", nonnegative=True)
        return total

    def action_equity(receivable: Decimal) -> Decimal | None:
        equity = (
            cash + receivable
            if quantity == 0
            else (None if mark is None else cash + receivable + quantity * mark)
        )
        if equity is not None:
            require_bounded_decimal(equity, "marked_equity", nonnegative=True)
        return equity

    def snapshot() -> CapitalAccountReplay:
        unsettled = sum(settlements.values(), _ZERO)
        available = cash
        if current is not None:
            reservation = _capital_order_reservation(
                order=current.snapshot.order,
                episode_fee_bound=fee_bound,
                episode_fees=episode_fees,
                episode_fees_final=final,
                held_quantity=quantity,
                legacy_identifiers=legacy,
            )
            available = capital_available_cash(cash, unsettled, reservation)
        receivable = receivable_total()
        base = CapitalAccountReplay(
            cash,
            available,
            quantity,
            fees,
            unsettled,
            final and quantity == 0 and not settlements and not entitlements,
            content_hash(
                {
                    "namespace": "capital-account-replay-" + version,
                    "initial": initial,
                    "applied": tuple(digests),
                }
            ),
        )
        if not actions:
            return base
        equity = action_equity(receivable)
        return CapitalActionAccountReplay(
            base.cash,
            base.available_cash,
            base.quantity,
            base.fees,
            base.unsettled_proceeds,
            base.complete,
            base.economic_hash,
            average_price,
            receivable,
            mark,
            equity,
        )

    if prefixes is not None:
        prefixes.append(snapshot())
    for event in events:
        cursor, event_id = _admit_event(event, legacy=legacy, actions=actions)
        digest = content_hash(
            {
                "namespace": "capital-account-event-" + version,
                "event": event,
            }
        )
        if event_id in seen:
            if seen[event_id] != digest:
                _deny()
            if prefixes is not None:
                prefixes.append(prefixes[-1])
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
                or proposed.position.average_price
                != (average_price if actions else current.snapshot.position.average_price)
                or event.symbol != symbol
            ):
                _deny()
            if proposed.order.side is Side.BUY:
                if quantity != 0 or not final or settlements or entitlements:
                    _deny()
                episode_fees = _ZERO
                fee_bound = event.episode_fee_bound
                final = False
                symbol = event.symbol
                opening_order_id = proposed.order.id
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
            adjusted = False
        elif isinstance(event, (LifecycleControlEvent, LifecycleFillEvent)):
            if request is None or current is None or final or adjusted:
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
            average_price = updated.snapshot.position.average_price if quantity else None
            # A fill changes the held quantity/price; an old mark is not a new
            # executable observation. Flat equity needs no inferred mark.
            if isinstance(event, LifecycleFillEvent):
                mark = None
            current = updated
            if isinstance(event, LifecycleFillEvent) and event.fill.side is Side.SELL:
                proceeds = event.fill.quantity * event.fill.price - event.fill.fee
                require_bounded_decimal(proceeds, "sale_proceeds", nonnegative=True)
                settlements[event.fill.id] = proceeds
        elif isinstance(event, CapitalSaleSettlement):
            if event.fill_id not in settlements:
                _deny()
            del settlements[event.fill_id]
        elif isinstance(
            event, (CapitalSplitApplied, CapitalDistributionEntitled, CapitalDistributionPaid)
        ):
            if (
                current is None
                or not current.order_terminal
                or event.account_id != account_id
                or event.opening_order_id != opening_order_id
                or event.symbol != symbol
            ):
                _deny()
            if isinstance(event, CapitalDistributionPaid):
                if event.entitlement_id not in entitlements:
                    _deny()
                amount, original = entitlements[event.entitlement_id]
                if event.amount != amount or event.cursor.occurred_at.date() < original.pay_date:
                    _deny()
                cash += amount
                require_bounded_decimal(cash, "cash", nonnegative=True)
                del entitlements[event.entitlement_id]
            else:
                if event.action_id in action_ids:
                    _deny()
                action_ids.add(event.action_id)
                if isinstance(event, CapitalSplitApplied):
                    if quantity:
                        if average_price is None:
                            _deny()
                        exact = Fraction(average_price) / Fraction(event.ratio)
                        denominator = exact.denominator
                        for factor in (2, 5):
                            while denominator % factor == 0:
                                denominator //= factor
                        if denominator != 1:
                            _deny()
                        quantity *= event.ratio
                        average_price /= event.ratio
                        require_bounded_decimal(quantity, "quantity", positive=True)
                        require_bounded_decimal(average_price, "average_price", positive=True)
                    mark = event.post_action_mark
                    adjusted = True
                else:
                    amount = quantity * event.amount_per_share
                    require_bounded_decimal(amount, "distribution_receivable", nonnegative=True)
                    if quantity:
                        entitlements[event.action_id] = (amount, event)
                    mark = event.ex_mark
        else:
            if isinstance(event, CapitalEpisodeFeesFinal) and (
                event.account_id != account_id or event.opening_order_id != opening_order_id
            ):
                _deny()
            if (
                final
                or current is None
                or not current.order_terminal
                or quantity != 0
                or settlements
                or entitlements
                or event.total_fees != episode_fees
            ):
                _deny()
            final = True
        # Recompute authoritative capacity after every unique event. Never adopt
        # an externally supplied reservation or release it on end-of-input.
        if actions:
            action_equity(receivable_total())
        if current is not None:
            reservation = _capital_order_reservation(
                order=current.snapshot.order,
                episode_fee_bound=fee_bound,
                episode_fees=episode_fees,
                episode_fees_final=final,
                held_quantity=quantity,
                legacy_identifiers=legacy,
            )
            capital_available_cash(cash, sum(settlements.values(), _ZERO), reservation)
        seen[event_id] = digest
        previous_cursor = cursor
        digests.append(digest)
        if prefixes is not None:
            prefixes.append(snapshot())
    if _completed is not None:
        _completed.append(
            _AccountState(
                cash=cash,
                fees=fees,
                quantity=quantity,
                episode_fees=episode_fees,
                fee_bound=fee_bound,
                final=final,
                request=request,
                current=current,
                account_id=account_id,
                symbol=symbol,
                opening_order_id=opening_order_id,
                previous_cursor=previous_cursor,
                order_fees_before=order_fees_before,
                seen=seen,
                orders=orders,
                fills=fills,
                settlements=settlements,
                digests=digests,
                average_price=average_price,
                mark=mark,
                entitlements=entitlements,
                action_ids=action_ids,
                adjusted=adjusted,
            )
        )
    return snapshot() if prefixes is None else prefixes[-1]
