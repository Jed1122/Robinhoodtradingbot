"""Exact offline ETF account reconciliation; inputs are explicit synthetic facts.

This component never discovers quotes, creates a broker, infers settlement or
manufactures a closing fill. It reuses common sizing, exposure, transition and
fill accounting. A strategy/execution owner must supply independently admitted
intents and observations; this fixture path cannot certify their market origin.
"""

import hashlib
from collections.abc import Generator
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from typing import Literal, Protocol

from trading_bot.domain import (
    AccountId,
    AssetClass,
    BrokerOrder,
    BrokerOrderId,
    DataHash,
    Fill,
    Instrument,
    InstrumentId,
    OrderEvent,
    OrderId,
    OrderIntent,
    OrderPurpose,
    OrderState,
    Position,
    Side,
)
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.domain.order_state_machine import transition
from trading_bot.market_data.etf_source import _ceil_time, _ns
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.portfolio.sizing import SizingDecision, SizingRequest
from trading_bot.research.etf_study import EtfStudy
from trading_bot.risk.limits import evaluate_exposure_limits
from trading_bot.risk.losses import (
    ActivitySnapshot,
    LossSnapshot,
    evaluate_activity_limits,
    evaluate_loss_limits,
)
from trading_bot.risk.models import ExposureProjection
from trading_bot.risk.options_economics import TrialEpisode, TrialLossState
from trading_bot.simulation.etf_history import _policy
from trading_bot.simulation.events import EventCursor
from trading_bot.simulation.lifecycle_accounting import _context, apply_lifecycle_fill
from trading_bot.simulation.lifecycle_models import LifecycleSnapshot

ZERO = Decimal("0")
_ACCOUNT = AccountId("etf-offline")
_TERMINAL = {OrderState.FILLED, OrderState.CANCELED, OrderState.REJECTED, OrderState.EXPIRED}
_KINDS = {
    "intent",  # Legacy explicit synthetic accepted-intent fact; hashes stay unchanged.
    "pending_intent",  # New scheduling seam: reserves are held before an explicit ack.
    "fill",
    "order_status",
    "settlement",
    "dividend_ex",
    "dividend_pay",
    "mark",
}


class EtfAccountError(ValueError):
    def __init__(self) -> None:
        super().__init__("etf_account_invalid")


def _check(value: bool) -> None:
    if not value:
        raise EtfAccountError()


def _required[T](value: T | None) -> T:
    if value is None:
        raise EtfAccountError()
    return value


@dataclass(frozen=True, slots=True)
class EtfAccountEvent:
    event_id: str
    ordinal: int
    at_ns: int
    kind: str
    intent: OrderIntent | None = None
    instrument: Instrument | None = None
    stop_distance: Decimal | None = None
    fee_bound: Decimal | None = None
    fill: Fill | None = None
    order_id: str | None = None
    order_event: OrderEvent | None = None
    fill_ids: tuple[str, ...] = ()
    action_id: str | None = None
    cash_per_share: Decimal | None = None
    mark_price: Decimal | None = None

    def __post_init__(self) -> None:
        _require_sha256_hex(self.event_id, "event")
        _check(type(self.ordinal) is int and 0 <= self.ordinal < 2**63)
        _check(type(self.at_ns) is int and 0 < self.at_ns < 2**63)
        _check(type(self.kind) is str and self.kind in _KINDS)
        active = {
            name
            for name in (
                "intent",
                "instrument",
                "stop_distance",
                "fee_bound",
                "fill",
                "order_id",
                "order_event",
                "action_id",
                "cash_per_share",
                "mark_price",
            )
            if getattr(self, name) is not None
        }
        expected = {
            "intent": {"intent", "instrument", "stop_distance", "fee_bound"},
            "pending_intent": {"intent", "instrument", "stop_distance", "fee_bound"},
            "fill": {"fill"},
            "order_status": {"order_id", "order_event"},
            "settlement": set(),
            "dividend_ex": {"action_id", "cash_per_share"},
            "dividend_pay": {"action_id"},
            "mark": {"mark_price"},
        }
        _check(active == expected[self.kind])
        _check(type(self.fill_ids) is tuple and len(self.fill_ids) <= 10000)
        _check((bool(self.fill_ids)) == (self.kind == "settlement"))
        _check(all(type(i) is str and 0 < len(i) <= 128 for i in self.fill_ids))
        _check(len(set(self.fill_ids)) == len(self.fill_ids))
        if self.intent is not None:
            _check(type(self.intent) is OrderIntent and type(self.instrument) is Instrument)
            replace(self.intent)
            replace(_required(self.instrument))
            _check(self.intent.account_id == _ACCOUNT and self.intent.instrument_id == "SPY")
            _check(self.intent.asset_class is AssetClass.EQUITY)
            _check(_ns(self.intent.created_at) == self.at_ns)
            require_bounded_decimal(_required(self.stop_distance), "stop", positive=True)
            require_bounded_decimal(_required(self.fee_bound), "fee bound", nonnegative=True)
        if self.fill is not None:
            _check(type(self.fill) is Fill)
            replace(self.fill)
            _check(self.fill.account_id == _ACCOUNT and self.fill.instrument_id == "SPY")
            _check(self.fill.occurred_at == _ceil_time(self.at_ns))
        if self.order_event is not None:
            _check(type(self.order_event) is OrderEvent)
            _check(type(self.order_id) is str and 0 < len(self.order_id) <= 128)
        if self.action_id is not None:
            _require_sha256_hex(self.action_id, "distribution")
        if self.cash_per_share is not None:
            require_bounded_decimal(self.cash_per_share, "distribution amount", nonnegative=True)
        if self.mark_price is not None:
            require_bounded_decimal(self.mark_price, "research mark", positive=True)

    @property
    def event_hash(self) -> str:
        return content_hash({"schema": "etf-account-event-v1", "event": self})


@dataclass(frozen=True, slots=True)
class EtfAccountRequest:
    study: EtfStudy
    initial_cash: Decimal
    events: tuple[EtfAccountEvent, ...]
    source_kind: Literal["synthetic-account-facts-v1"] = field(
        default="synthetic-account-facts-v1", init=False
    )

    def __post_init__(self) -> None:
        _policy(self.study)
        require_bounded_decimal(self.initial_cash, "initial cash", positive=True)
        _check(self.initial_cash in self.study.capital_tiers)
        _check(type(self.events) is tuple and len(self.events) <= 10000)
        for item in self.events:
            _check(type(item) is EtfAccountEvent)
            replace(item)
            _check(_ns(self.study.requested_start) <= item.at_ns < _ns(self.study.requested_end))

    @property
    def run_id(self) -> str:
        return content_hash(("etf-account-run-v1", self.study.study_hash, self.initial_cash))


@dataclass(frozen=True, slots=True)
class EtfAccountOrder:
    intent: OrderIntent
    order: BrokerOrder
    submitted_at_ns: int
    fee_bound: Decimal
    fees_paid: Decimal
    episode_id: str

    @property
    def remaining(self) -> Decimal:
        with localcontext(_context(exact=True)):
            return self.order.requested_quantity - self.order.filled_quantity

    @property
    def reserved_cash(self) -> Decimal:
        if self.order.side is Side.SELL or self.order.state in _TERMINAL:
            return ZERO
        _check(self.order.limit_price is not None)
        with localcontext(_context(exact=True)):
            return self.remaining * _required(self.order.limit_price) + max(
                ZERO, self.fee_bound - self.fees_paid
            )


@dataclass(frozen=True, slots=True)
class EtfAccountResult:
    run_id: str
    study_hash: str
    initial_cash: Decimal
    event_count: int
    last_ordinal: int | None
    last_at_ns: int | None
    prefix_hash: str
    cash: Decimal
    settled_cash: Decimal
    position: Position
    fees: Decimal
    orders: tuple[EtfAccountOrder, ...]
    trial: TrialLossState
    unsettled: tuple[tuple[str, Decimal, str], ...]
    receivables: tuple[tuple[str, Decimal, str], ...]
    entry_halted: bool
    paused: Literal[True] = field(default=True, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    @property
    def shares(self) -> Decimal:
        return self.position.quantity

    @property
    def reserved_cash(self) -> Decimal:
        with localcontext(_context(exact=True)):
            return sum((o.reserved_cash for o in self.orders), ZERO)

    @property
    def dividend_receivable(self) -> Decimal:
        with localcontext(_context(exact=True)):
            return sum((amount for _, amount, _ in self.receivables), ZERO)

    @property
    def complete(self) -> bool:
        return (
            self.shares == 0
            and not self.unsettled
            and not self.receivables
            and all(o.order.state in _TERMINAL for o in self.orders)
            and all(e.complete for e in self.trial.episodes)
        )

    @property
    def state_hash(self) -> str:
        return content_hash({"schema": "etf-account-state-v1", "state": self})


def _order(intent: OrderIntent, at_ns: int, *, accepted: bool = True) -> BrokerOrder:
    state = OrderState.PROPOSED
    for event in (
        OrderEvent.RISK_ALLOW,
        OrderEvent.REQUEST_REVIEW,
        OrderEvent.REVIEW_ACCEPTED,
        OrderEvent.PREPARE_SUBMISSION,
    ):
        state = transition(state, event)
    if accepted:
        state = transition(state, OrderEvent.BROKER_ACCEPTED)
    return BrokerOrder(
        OrderId(intent.id),
        BrokerOrderId(intent.id),
        _ACCOUNT,
        intent.id,
        None,
        intent.instrument_id,
        intent.side,
        intent.purpose,
        intent.order_type,
        intent.time_in_force,
        intent.quantity,
        ZERO,
        intent.limit_price,
        None,
        state,
        intent.created_at,
        _ceil_time(at_ns),
        intent.data_hash,
    )


class _AccountReplayInput(Protocol):
    """Internal economic seam; public historical request guards stay unchanged."""

    @property
    def study(self) -> EtfStudy: ...

    @property
    def initial_cash(self) -> Decimal: ...

    @property
    def events(self) -> tuple[EtfAccountEvent, ...]: ...

    @property
    def run_id(self) -> str: ...


def _steps(
    request: _AccountReplayInput, *, origin: datetime | None = None
) -> Generator[EtfAccountResult, EtfAccountEvent, None]:
    """Shared one-fact owner; never suspend inside a Decimal local context."""
    loaded = _policy(request.study)
    # Only a separately validated forward wrapper supplies an origin. The
    # historical public path retains its original preimages and UTC window.
    starts_at = request.study.requested_start if origin is None else origin
    cfg = loaded.config
    cash = request.initial_cash
    position = Position(
        _ACCOUNT,
        InstrumentId("SPY"),
        AssetClass.EQUITY,
        ZERO,
        None,
        ZERO,
        starts_at,
        content_hash("etf-account-origin"),
    )
    fees = ZERO
    orders: dict[str, EtfAccountOrder] = {}
    episodes: dict[str, TrialEpisode] = {}
    unsettled: dict[str, tuple[Decimal, str]] = {}
    receivables: dict[str, tuple[Decimal, str]] = {}
    distributions: set[str] = set()
    settled_fills: set[str] = set()
    fills: dict[str, tuple[str, str]] = {}
    seen: dict[str, str] = {}
    consumed: list[EtfAccountEvent] = []
    prefix = hashlib.sha256(b"[")
    last: EtfAccountEvent | None = None
    active_episode: str | None = None
    completed: list[tuple[Decimal, datetime]] = []
    peak_equity = request.initial_cash
    day_equity = week_equity = request.initial_cash
    day_start = week_start = starts_at
    weekly_latched = drawdown_latched = False
    loss_snapshot: LossSnapshot | None = None

    def finish_episodes() -> None:
        nonlocal active_episode
        for key, episode in tuple(episodes.items()):
            if episode.complete:
                continue
            relevant = [o for o in orders.values() if o.episode_id == key]
            flat = not any(
                o.order.side is Side.BUY and o.order.filled_quantity > 0 for o in relevant
            ) or (key == active_episode and position.quantity == 0)
            terminal = all(o.order.state in _TERMINAL for o in relevant)
            final = not any(ep == key for _, ep in unsettled.values()) and not any(
                ep == key for _, ep in receivables.values()
            )
            episodes[key] = replace(
                episode, flat=flat, orders_terminal=terminal, settlement_and_fees_final=final
            )
            if episodes[key].complete and key == active_episode:
                completed.append((_required(episode.net_cash_flow), now))
                active_episode = None

    def project() -> EtfAccountResult:
        with localcontext(_context(exact=True)):
            account_ceiling_breached = (
                cash + position.market_value + sum((a for a, _ in receivables.values()), ZERO)
                > cfg.portfolio.live_account_equity_ceiling_usd
            )
            digest = prefix.copy()
            digest.update(b"]")
            return EtfAccountResult(
                request.run_id,
                request.study.study_hash,
                request.initial_cash,
                len(consumed),
                last.ordinal if last else None,
                last.at_ns if last else None,
                digest.hexdigest(),
                cash,
                cash - sum((amount for amount, _ in unsettled.values()), ZERO),
                position,
                fees,
                tuple(orders.values()),
                TrialLossState(tuple(episodes.values())),
                tuple((key, *value) for key, value in unsettled.items()),
                tuple((key, *value) for key, value in receivables.items()),
                account_ceiling_breached
                or weekly_latched
                or drawdown_latched
                or (
                    loss_snapshot is not None
                    and not evaluate_loss_limits(
                        snapshot=loss_snapshot,
                        settings=cfg.loss_limits,
                        purpose=OrderPurpose.ENTRY,
                    ).allowed
                ),
            )

    while True:
        event = yield project()
        with localcontext(_context(exact=True)):
            digest = event.event_hash
            if event.event_id in seen:
                _check(seen[event.event_id] == digest)
                continue
            if last is not None:
                _check(last.ordinal < event.ordinal and last.at_ns <= event.at_ns)
            now = _ceil_time(event.at_ns)
            equity = cash + position.market_value + sum((a for a, _ in receivables.values()), ZERO)
            current_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            current_week = current_day - timedelta(days=current_day.weekday())
            if current_day != day_start:
                day_start, day_equity = current_day, equity
            if current_week != week_start:
                week_start, week_equity = current_week, equity
            if event.kind in ("intent", "pending_intent"):
                intent, instrument = _required(event.intent), _required(event.instrument)
                price = _required(intent.limit_price)
                stop = _required(event.stop_distance)
                fee_bound = _required(event.fee_bound)
                _check(intent.config_hash == request.study.config_hash)
                _check(intent.id not in orders)
                _check(not any(o.order.state not in _TERMINAL for o in orders.values()))
                _check(instrument.id == "SPY" and instrument.asset_class is AssetClass.EQUITY)
                _check(instrument.tradable and instrument.observed_at <= now)
                _check(intent.limit_price is not None)
                _check(intent.quantity >= instrument.minimum_quantity)
                _check(
                    instrument.maximum_quantity is None
                    or intent.quantity <= instrument.maximum_quantity
                )
                _check(intent.quantity % instrument.quantity_increment == 0)
                _check(price % instrument.price_increment == 0)
                _check(instrument.fractional_eligible or intent.quantity % 1 == 0)
                settled_cash = cash - sum((amount for amount, _ in unsettled.values()), ZERO)
                if intent.side is Side.BUY:
                    _check(position.quantity == 0 and active_episode is None)
                    _check(equity <= cfg.portfolio.live_account_equity_ceiling_usd)
                    _check(not weekly_latched and not drawdown_latched)
                    if loss_snapshot is not None:
                        _check(
                            evaluate_loss_limits(
                                snapshot=replace(
                                    loss_snapshot,
                                    daily_loss_pct=max(ZERO, day_equity - equity)
                                    / request.study.risk_equity_reference
                                    * 100,
                                    daily_window_started_at=day_start,
                                    weekly_window_started_at=week_start,
                                    daily_reset_reconciled=not unsettled,
                                    observed_at=now,
                                ),
                                settings=cfg.loss_limits,
                                purpose=OrderPurpose.ENTRY,
                            ).allowed
                        )
                    _check(
                        not any(
                            o.intent.side is Side.BUY and o.intent.created_at.date() == now.date()
                            for o in orders.values()
                        )
                    )
                    if event.kind == "pending_intent":
                        entries = tuple(
                            o.intent.created_at
                            for o in orders.values()
                            if o.intent.side is Side.BUY
                        )
                        todays_entries = sum(at.date() == now.date() for at in entries)
                        activity = ActivitySnapshot(
                            _ACCOUNT,
                            InstrumentId("SPY"),
                            todays_entries,
                            todays_entries,
                            max(entries) if entries else None,
                            current_day,
                            now,
                        )
                        _check(evaluate_activity_limits(activity, settings=cfg.activity).allowed)
                    sizing = SizingRequest.from_config(
                        reconciled_equity=cash,
                        authorized_risk_equity=request.study.risk_equity_reference,
                        stop_distance_per_unit=stop,
                        entry_price=price,
                        instrument=instrument,
                        position_risk=cfg.position_risk,
                        activity=cfg.activity,
                    )
                    _check(
                        SizingDecision.validate_final(
                            quantity=intent.quantity, request=sizing
                        ).allowed
                    )
                    risk_budget = min(cash, request.study.risk_equity_reference) * (
                        cfg.position_risk.max_risk_per_trade_pct / Decimal("100")
                    )
                    _check(intent.quantity * stop + fee_bound <= risk_budget)
                    reserved = intent.quantity * price + fee_bound
                    _check(reserved <= settled_cash)
                    _check(cash - reserved >= cash * cfg.options.min_unencumbered_cash_pct / 100)
                    projection = ExposureProjection(
                        _ACCOUNT,
                        intent.id,
                        InstrumentId("SPY"),
                        AssetClass.EQUITY,
                        instrument.correlation_group,
                        cash,
                        request.study.risk_equity_reference,
                        cash - reserved,
                        intent.quantity * price,
                        1,
                        intent.quantity * price,
                        intent.quantity * price,
                        ZERO,
                        ZERO,
                        now,
                    )
                    _check(
                        all(
                            c.allowed
                            for c in evaluate_exposure_limits(
                                projection,
                                portfolio=cfg.portfolio,
                                position_risk=cfg.position_risk,
                                crypto=cfg.crypto,
                            )
                        )
                    )
                    trial = TrialLossState(tuple(episodes.values()))
                    _check(reserved <= trial.remaining(cfg.options.cumulative_trial_loss_limit_usd))
                    active_episode = intent.id
                    episodes[intent.id] = TrialEpisode(
                        intent.id, reserved, ZERO, False, False, False
                    )
                else:
                    _check(active_episode is not None and 0 < intent.quantity <= position.quantity)
                _check(active_episode is not None)
                orders[intent.id] = EtfAccountOrder(
                    intent,
                    _order(intent, event.at_ns, accepted=event.kind == "intent"),
                    event.at_ns,
                    fee_bound,
                    ZERO,
                    _required(active_episode),
                )
            elif event.kind == "fill":
                fill = _required(event.fill)
                _check(fill.broker_order_id in orders)
                record = orders[fill.broker_order_id]
                if fill.id in fills:
                    _check(fills[fill.id][0] == content_hash(fill))
                else:
                    _check(
                        record.order.state
                        in {
                            OrderState.SUBMITTED,
                            OrderState.PARTIALLY_FILLED,
                            OrderState.CANCEL_PENDING,
                        }
                    )
                    _check(record.submitted_at_ns < event.at_ns < _ns(record.intent.expires_at))
                    _check(fill.quantity <= record.remaining)
                    _check(record.fees_paid + fill.fee <= record.fee_bound)
                    entry_fee_bound = orders[record.episode_id].fee_bound
                    episode_fees = sum(
                        (o.fees_paid for o in orders.values() if o.episode_id == record.episode_id),
                        ZERO,
                    )
                    _check(episode_fees + fill.fee <= entry_fee_bound)
                    snapshot = LifecycleSnapshot(
                        record.order,
                        position,
                        cash,
                        fees,
                        record.remaining,
                        EventCursor(event.ordinal, now),
                        content_hash(record),
                    )
                    applied = apply_lifecycle_fill(snapshot, fill)
                    state = transition(
                        record.order.state,
                        OrderEvent.FILL
                        if applied.remaining_quantity == 0
                        else OrderEvent.PARTIAL_FILL,
                    )
                    record = replace(
                        record,
                        order=replace(
                            record.order,
                            state=state,
                            filled_quantity=applied.filled_quantity,
                            updated_at=now,
                        ),
                        fees_paid=record.fees_paid + fill.fee,
                    )
                    orders[fill.broker_order_id] = record
                    cash, fees, position = applied.cash, applied.fees, applied.position
                    delta = (
                        -(fill.quantity * fill.price + fill.fee)
                        if fill.side is Side.BUY
                        else fill.quantity * fill.price - fill.fee
                    )
                    episode = episodes[record.episode_id]
                    episodes[record.episode_id] = replace(
                        episode, net_cash_flow=_required(episode.net_cash_flow) + delta
                    )
                    unsettled[fill.id] = (max(ZERO, delta), record.episode_id)
                    fills[fill.id] = (content_hash(fill), record.episode_id)
            elif event.kind == "order_status":
                order_id, order_event = _required(event.order_id), _required(event.order_event)
                _check(order_id in orders)
                record = orders[order_id]
                _check(event.at_ns > record.submitted_at_ns)
                # Status labels cannot manufacture cash/share facts or erase
                # observed partial fills. Unknown acceptance retains reserves
                # until a quantity-consistent status and explicit fills reconcile.
                if order_event in (OrderEvent.RECONCILE_SUBMITTED, OrderEvent.RECONCILE_REJECTED):
                    _check(record.order.filled_quantity == 0)
                if order_event is OrderEvent.RECONCILE_PARTIAL:
                    _check(0 < record.order.filled_quantity < record.order.requested_quantity)
                if order_event is OrderEvent.RECONCILE_FILLED:
                    _check(record.order.filled_quantity == record.order.requested_quantity)
                if order_event in (
                    OrderEvent.BROKER_ACCEPTED,
                    OrderEvent.RECONCILE_SUBMITTED,
                    OrderEvent.RECONCILE_PARTIAL,
                ):
                    _check(event.at_ns < _ns(record.intent.expires_at))
                next_state = transition(record.order.state, order_event)
                orders[order_id] = replace(
                    record, order=replace(record.order, state=next_state, updated_at=now)
                )
            elif event.kind == "settlement":
                for fill_id in event.fill_ids:
                    _check(fill_id in fills)
                    if fill_id not in settled_fills:
                        _check(fill_id in unsettled)
                        unsettled.pop(fill_id)
                        settled_fills.add(fill_id)
            elif event.kind == "dividend_ex":
                action_id, cash_per_share = (
                    _required(event.action_id),
                    _required(event.cash_per_share),
                )
                _check(action_id not in distributions)
                distributions.add(action_id)
                amount = position.quantity * cash_per_share
                if amount:
                    _check(active_episode is not None)
                    receivables[action_id] = (amount, _required(active_episode))
            elif event.kind == "dividend_pay":
                _check(event.action_id in distributions)
                if event.action_id in receivables:
                    amount, key = receivables.pop(event.action_id)
                    cash += amount
                    episode = episodes[key]
                    episodes[key] = replace(
                        episode, net_cash_flow=_required(episode.net_cash_flow) + amount
                    )
            elif event.kind == "mark":
                position = replace(
                    position,
                    market_value=position.quantity * _required(event.mark_price),
                    observed_at=now,
                    data_hash=DataHash(event.event_hash),
                )
            finish_episodes()
            equity = cash + position.market_value + sum((a for a, _ in receivables.values()), ZERO)
            peak_equity = max(peak_equity, equity)
            reference = request.study.risk_equity_reference
            daily_pct = min(Decimal("100"), max(ZERO, day_equity - equity) / reference * 100)
            weekly_pct = min(Decimal("100"), max(ZERO, week_equity - equity) / reference * 100)
            drawdown_pct = min(Decimal("100"), max(ZERO, peak_equity - equity) / reference * 100)
            weekly_latched |= weekly_pct >= cfg.loss_limits.max_weekly_loss_pct
            drawdown_latched |= drawdown_pct >= cfg.loss_limits.max_peak_to_trough_drawdown_pct
            consecutive = 0
            for pnl, _ in reversed(completed):
                if pnl >= 0:
                    break
                consecutive += 1
            loss_snapshot = LossSnapshot(
                _ACCOUNT,
                daily_pct,
                weekly_pct,
                drawdown_pct,
                consecutive,
                completed[-1][1] if consecutive else None,
                day_start,
                week_start,
                not unsettled,
                not weekly_latched,
                now,
            )
            seen[event.event_id] = digest
            if consumed:
                prefix.update(b",")
            prefix.update(canonical_json(event).encode())
            consumed.append(event)
            last = event


def _run(
    request: _AccountReplayInput, count: int, *, origin: datetime | None = None
) -> EtfAccountResult:
    reducer = _steps(request, origin=origin)
    try:
        state = next(reducer)
        for event in request.events[:count]:
            state = reducer.send(event)
        return state
    finally:
        reducer.close()


class EtfAccountStepper:
    """Bounded offline advancement; a failed reducer cannot be used again.

    Reconstruction reduces the retained tape once. Results and hashes remain
    legacy v1; this object is not a production risk or authorization capability.
    """

    def __init__(self, request: EtfAccountRequest) -> None:
        _check(type(request) is EtfAccountRequest)
        replace(request)
        self._request = replace(request, events=())
        self._events: list[EtfAccountEvent] = []
        self._failed = False
        self._reducer = _steps(self._request)
        self._state = next(self._reducer)
        for event in request.events:
            self.apply(event)

    @property
    def state(self) -> EtfAccountResult:
        return self._state

    @property
    def events(self) -> tuple[EtfAccountEvent, ...]:
        return tuple(self._events)

    @property
    def failed(self) -> bool:
        return self._failed

    def apply(self, event: EtfAccountEvent) -> EtfAccountResult:
        try:
            _check(not self._failed and len(self._events) < 10000)
            _check(type(event) is EtfAccountEvent)
            replace(event)
            _check(
                _ns(self._request.study.requested_start)
                <= event.at_ns
                < _ns(self._request.study.requested_end)
            )
            state = self._reducer.send(event)
            self._events.append(event)
            self._state = state
            return state
        except (
            ValueError,
            TypeError,
            ArithmeticError,
            AttributeError,
            RuntimeError,
            StopIteration,
        ):
            self._failed = True
            self._reducer.close()
            raise EtfAccountError() from None


def replay_etf_account(
    request: EtfAccountRequest, *, through_ordinal: int | None = None
) -> EtfAccountResult:
    try:
        _check(type(request) is EtfAccountRequest)
        replace(request)
        count = len(request.events)
        if through_ordinal is not None:
            _check(type(through_ordinal) is int and through_ordinal >= 0)
            matches = [
                i + 1 for i, event in enumerate(request.events) if event.ordinal == through_ordinal
            ]
            _check(bool(matches))
            count = matches[-1]
        return _run(request, count)
    except (ValueError, TypeError, ArithmeticError, AttributeError, RuntimeError):
        raise EtfAccountError() from None


def resume_etf_account(
    request: EtfAccountRequest, checkpoint: EtfAccountResult
) -> EtfAccountResult:
    try:
        _check(type(checkpoint) is EtfAccountResult)
        count = (
            0
            if checkpoint.last_ordinal is None
            else next(
                i + 1
                for i, event in enumerate(request.events)
                if event.ordinal == checkpoint.last_ordinal
            )
        )
        _check(_run(request, count) == checkpoint)
        return replay_etf_account(request)
    except (ValueError, TypeError, ArithmeticError, AttributeError, RuntimeError, StopIteration):
        raise EtfAccountError() from None


@dataclass(frozen=True, slots=True)
class EtfPendingAdmission:
    """Account-only synthetic admission, not the production 24-check gate.

    Scheduling can consume this zero-effect denial without a second sizing/risk
    calculator. Allowed results persist only a pending reservation; acceptance,
    fills, costs, settlement and executable provenance remain separate facts.
    """

    allowed: bool
    reason: str
    candidate_hash: str
    state: EtfAccountResult
    scope: Literal["synthetic-account-limits-only-v1"] = field(
        default="synthetic-account-limits-only-v1", init=False
    )
    production_pretrade_eligible: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)


def admit_etf_pending_intent(
    request: EtfAccountRequest, candidate: EtfAccountEvent
) -> EtfPendingAdmission:
    """Reconstruct trusted history first, then apply the same account owner once.

    Invalid existing history raises; it is never replaced with empty cash/state.
    Candidate admission failures return the unchanged reconstructed state. No
    broker, mutable reservation, retry or automatic quantity change is introduced.
    """
    current = replay_etf_account(request)
    _check(type(candidate) is EtfAccountEvent and candidate.kind == "pending_intent")
    replace(candidate)
    intent = _required(candidate.intent)
    if any(item.event_id == candidate.event_id for item in request.events) or any(
        item.intent.id == intent.id for item in current.orders
    ):
        # Idempotent replay is not fresh scheduling authority. Even an identical
        # recorded pending event may now be rejected, ambiguous or filled.
        return EtfPendingAdmission(
            False, "duplicate_pending_identity", candidate.event_hash, current
        )
    try:
        proposed = replay_etf_account(replace(request, events=(*request.events, candidate)))
    except EtfAccountError:
        return EtfPendingAdmission(
            False, "canonical_account_admission_denied", candidate.event_hash, current
        )
    _check(len(proposed.orders) == len(current.orders) + 1)
    record = proposed.orders[-1]
    _check(record.intent == intent and record.order.state is OrderState.SUBMISSION_PENDING)
    _check(record.order.filled_quantity == 0 and proposed.cash == current.cash)
    if intent.side is Side.BUY:
        _check(record.reserved_cash > 0)
    return EtfPendingAdmission(
        True, "canonical_account_limits_allow", candidate.event_hash, proposed
    )
