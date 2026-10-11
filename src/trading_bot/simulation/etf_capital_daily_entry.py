"""Declared next-open entry assumptions through shared original-state gates.

This bounded adapter is not a signal scheduler, broker route, quote record or
economic evaluator. LIMIT-shaped lifecycle records encode hypothetical prices
only. No credential, transport, live intent or source qualification is supplied.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_CEILING, Context, Decimal, localcontext
from typing import Literal, cast

from trading_bot.config import LoadedConfig
from trading_bot.domain import (
    AccountId,
    AssetClass,
    BrokerOrder,
    BrokerOrderId,
    DataHash,
    Fill,
    FillId,
    Instrument,
    InstrumentId,
    OrderEvent,
    OrderId,
    OrderPurpose,
    OrderState,
    OrderType,
    Position,
    Side,
    TimeInForce,
    quantize_down,
    require_bounded_decimal,
)
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_feasibility import CapitalEntryDecision
from trading_bot.simulation.etf_capital_account import (
    CapitalAccountEvent,
    CapitalAccountSubmission,
    CapitalActionAccountReplay,
    _account_prefixes_owned,
    _AccountProgress,
    replay_capital_action_account,
)
from trading_bot.simulation.etf_capital_action_events import CapitalActionEvent
from trading_bot.simulation.etf_capital_risk import (
    CapitalRiskObservation,
    CapitalRiskPoint,
    CapitalRiskReplay,
    _entry_point,
    _replay_risk_points,
    _RiskProgress,
    replay_capital_action_risk,
)
from trading_bot.simulation.events import EventCursor
from trading_bot.simulation.lifecycle_models import (
    LifecycleControlEvent,
    LifecycleFillEvent,
    LifecycleRequest,
    validate_cursor,
)

_ZERO = Decimal("0")
_CONTEXT = Context(prec=2048)


def _check(value: bool) -> None:
    if not value:
        raise ValueError("capital_daily_entry_invalid")


@dataclass(frozen=True, slots=True)
class _Offline:
    source_qualified: bool = field(default=False, init=False)
    cost_qualified: bool = field(default=False, init=False)
    execution_enabled: bool = field(default=False, init=False)
    economic_admitted: bool = field(default=False, init=False)
    evidence_promotable: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class CapitalDailyEntryRequest(_Offline):
    loaded: LoadedConfig
    initial_cash: Decimal
    events: tuple[CapitalAccountEvent | CapitalActionEvent, ...]
    observations: tuple[CapitalRiskObservation, ...]
    instrument: Instrument
    decision_at: datetime
    opened: EventCursor
    lifecycle_cursors: tuple[EventCursor, ...]
    decision_hash: str
    source_hash: str
    raw_open: Decimal
    stop_distance: Decimal
    episode_fee_bound: Decimal | None
    side_fee: Decimal
    roundtrip_friction_pct: Decimal
    outcome: Literal["rejected", "unfilled", "filled", "partial"]
    fill_fraction: Decimal


@dataclass(frozen=True, slots=True)
class CapitalDailyEntryResult(_Offline):
    admission: CapitalEntryDecision
    assumed_price: Decimal
    events: tuple[CapitalAccountEvent | CapitalActionEvent, ...]
    observations: tuple[CapitalRiskObservation, ...]
    account: CapitalActionAccountReplay
    risk: CapitalRiskReplay
    input_hash: str


@dataclass(frozen=True, slots=True)
class _CapitalDailyEntryFacts(_Offline):
    admission: CapitalEntryDecision
    assumed_price: Decimal
    events: tuple[CapitalAccountEvent | CapitalActionEvent, ...]
    observations: tuple[CapitalRiskObservation, ...]
    account: CapitalActionAccountReplay
    input_hash: str


def _validate(request: CapitalDailyEntryRequest) -> None:
    _check(type(request) is CapitalDailyEntryRequest)
    _check(
        request.source_qualified is False
        and request.cost_qualified is False
        and request.execution_enabled is False
        and request.economic_admitted is False
        and request.evidence_promotable is False
    )
    _check(type(request.events) is tuple and len(request.events) <= 4093)
    _check(type(request.observations) is tuple and 0 < len(request.observations) < 4096)
    validate_cursor(request.opened)
    _check(type(request.decision_at) is datetime)
    validate_cursor(EventCursor(0, request.decision_at))
    _check(request.decision_at < request.opened.occurred_at)
    _check(request.decision_at.date() < request.opened.occurred_at.date())
    _check(type(request.instrument) is Instrument)
    request.instrument.__post_init__()
    _check(request.instrument.observed_at <= request.opened.occurred_at)
    for value in (
        request.instrument.id,
        request.instrument.symbol,
        request.instrument.provider_status,
        request.instrument.correlation_group,
    ):
        _check(type(value) is str and bool(value.strip()) and len(value) <= 256)
    for value in (request.decision_hash, request.source_hash, request.instrument.data_hash):
        _require_sha256_hex(value, "source identity")
    for name, money in (("open", request.raw_open), ("stop", request.stop_distance)):
        require_bounded_decimal(money, name, positive=True)
    require_bounded_decimal(request.side_fee, "side fee", nonnegative=True)
    require_bounded_decimal(request.fill_fraction, "fill fraction", nonnegative=True)
    require_bounded_decimal(request.roundtrip_friction_pct, "friction", nonnegative=True)
    _check(request.roundtrip_friction_pct in tuple(map(Decimal, (".05", ".10", ".20", ".40"))))
    _check(
        type(request.outcome) is str
        and request.outcome
        in {
            "rejected",
            "unfilled",
            "filled",
            "partial",
        }
    )
    if request.episode_fee_bound is not None:
        require_bounded_decimal(request.episode_fee_bound, "fee bound", nonnegative=True)
        _check(request.side_fee <= request.episode_fee_bound)
    if request.outcome in ("rejected", "unfilled"):
        _check(request.fill_fraction == 0 and request.side_fee == 0)
    elif request.outcome == "filled":
        _check(request.fill_fraction == 1)
    else:
        _check(0 < request.fill_fraction < 1)
    _check(type(request.lifecycle_cursors) is tuple)
    _check(len(request.lifecycle_cursors) == (2 if request.fill_fraction else 1))
    prior = request.opened
    for cursor in request.lifecycle_cursors:
        validate_cursor(cursor)
        _check(cursor.sequence > prior.sequence and cursor.occurred_at > prior.occurred_at)
        _check(cursor.occurred_at.date() == request.opened.occurred_at.date())
        prior = cursor
    last = request.observations[-1]
    _check(type(last) is CapitalRiskObservation)
    last.__post_init__()
    _check(last.source_count == len(request.events))
    _check(last.cursor.occurred_at == request.opened.occurred_at)
    _check(request.opened.sequence > last.cursor.sequence)


def _entry_price(request: CapitalDailyEntryRequest) -> Decimal:
    with localcontext(_CONTEXT):
        price = request.raw_open * (1 + request.roundtrip_friction_pct / Decimal("200"))
        increment = request.instrument.price_increment
        require_bounded_decimal(increment, "price increment", positive=True)
        price = (price / increment).to_integral_value(rounding=ROUND_CEILING) * increment
        require_bounded_decimal(price, "assumed price", positive=True)
        _check(request.stop_distance < price)
        return price


def _generate_capital_daily_entry(
    request: CapitalDailyEntryRequest,
    current: CapitalRiskPoint,
    price: Decimal,
    *,
    _account_progress: _AccountProgress | None = None,
) -> _CapitalDailyEntryFacts:
    """One emission kernel; terminal facts come only from fresh original replay."""
    with localcontext(_CONTEXT):
        admission = _entry_point(
            request.loaded,
            current,
            request.instrument,
            price,
            request.stop_distance,
            request.episode_fee_bound,
        )
        original = current.account
        _check(type(original) is CapitalActionAccountReplay)
        digest = content_hash(
            (
                "capital-daily-entry-assumption-v1",
                request.loaded.config_hash,
                request.initial_cash,
                request.events,
                request.observations,
                request.instrument,
                request.decision_at,
                request.opened,
                request.lifecycle_cursors,
                request.decision_hash,
                request.source_hash,
                request.raw_open,
                request.stop_distance,
                request.episode_fee_bound,
                request.side_fee,
                request.roundtrip_friction_pct,
                request.outcome,
                request.fill_fraction,
            )
        )
        events = request.events
        observations = request.observations
        if admission.allowed:
            _check(request.episode_fee_bound is not None)
            for event in events:
                cursor = (
                    event.request.submitted
                    if isinstance(event, CapitalAccountSubmission)
                    else event.cursor
                )
                _check(cursor.sequence < request.opened.sequence)
            account = AccountId("capital-daily-assumed")
            for event in events:
                if type(event) is CapitalAccountSubmission:
                    _check(event.request.order.account_id == account)
            identity = InstrumentId("capital-research:" + request.instrument.symbol)
            order = BrokerOrder(
                OrderId(digest),
                BrokerOrderId(digest),
                account,
                None,
                None,
                identity,
                Side.BUY,
                OrderPurpose.ENTRY,
                OrderType.LIMIT,
                TimeInForce.GOOD_FOR_DAY,
                admission.quantity,
                _ZERO,
                price,
                None,
                OrderState.SUBMISSION_PENDING,
                request.opened.occurred_at,
                request.opened.occurred_at,
                DataHash(digest),
            )
            position = Position(
                account,
                identity,
                AssetClass.EQUITY,
                _ZERO,
                None,
                _ZERO,
                request.opened.occurred_at,
                DataHash(digest),
            )
            submission = CapitalAccountSubmission(
                request.instrument.symbol,
                LifecycleRequest(order, position, original.cash, request.opened, ()),
                request.episode_fee_bound,  # type: ignore[arg-type]
            )
            control = LifecycleControlEvent(
                digest + ":control",
                request.lifecycle_cursors[0],
                account,
                identity,
                order.broker_order_id,
                OrderEvent.BROKER_REJECTED
                if request.outcome == "rejected"
                else OrderEvent.BROKER_ACCEPTED,
            )
            events = (*events, submission, control)
            if request.fill_fraction:
                quantity = quantize_down(
                    admission.quantity * request.fill_fraction,
                    request.instrument.quantity_increment,
                )
                _check(quantity > 0)
                fill = Fill(
                    FillId(digest + ":fill"),
                    order.broker_order_id,
                    account,
                    identity,
                    Side.BUY,
                    quantity,
                    price,
                    request.side_fee,
                    request.lifecycle_cursors[1].occurred_at,
                    DataHash(digest),
                )
                events = (
                    *events,
                    LifecycleFillEvent(
                        digest + ":fill-event",
                        request.lifecycle_cursors[1],
                        fill,
                    ),
                )
            observations = (
                *observations,
                CapitalRiskObservation(
                    EventCursor(
                        request.lifecycle_cursors[-1].sequence + 1,
                        request.lifecycle_cursors[-1].occurred_at,
                    ),
                    len(events),
                    request.raw_open if request.fill_fraction else None,
                    False,
                    False,
                ),
            )
        if _account_progress is None:
            state = replay_capital_action_account(initial_cash=request.initial_cash, events=events)
        else:
            _, accounts = _account_prefixes_owned(
                _account_progress, initial_cash=request.initial_cash, events=events, actions=True
            )
            state = cast(CapitalActionAccountReplay, accounts[-1])
        return _CapitalDailyEntryFacts(admission, price, events, observations, state, digest)


def simulate_capital_daily_entry(request: CapitalDailyEntryRequest) -> CapitalDailyEntryResult:
    """Declared original-state entry; no real order or brokerage claim."""
    _validate(request)
    price = _entry_price(request)
    original = replay_capital_action_risk(
        loaded=request.loaded,
        initial_cash=request.initial_cash,
        events=request.events,
        observations=request.observations,
    )
    facts = _generate_capital_daily_entry(request, original.points[-1], price)
    risk = replay_capital_action_risk(
        loaded=request.loaded,
        initial_cash=request.initial_cash,
        events=facts.events,
        observations=facts.observations,
    )
    return CapitalDailyEntryResult(
        facts.admission,
        facts.assumed_price,
        facts.events,
        facts.observations,
        facts.account,
        risk,
        facts.input_hash,
    )


def _simulate_owned_capital_daily_entry(
    request: CapitalDailyEntryRequest, *, progress: _RiskProgress
) -> _CapitalDailyEntryFacts:
    """Invocation-local facts; original and generated tapes are both validated."""
    _validate(request)
    _check(type(progress) is _RiskProgress)
    price = _entry_price(request)
    original = _replay_risk_points(
        loaded=request.loaded,
        initial_cash=request.initial_cash,
        events=request.events,
        observations=request.observations,
        purpose=OrderPurpose.ENTRY,
        actions=True,
        _progress=progress,
        _last_only=True,
    )
    facts = _generate_capital_daily_entry(
        request, original[-1], price, _account_progress=progress.accounts
    )
    _replay_risk_points(
        loaded=request.loaded,
        initial_cash=request.initial_cash,
        events=facts.events,
        observations=facts.observations,
        purpose=OrderPurpose.ENTRY,
        actions=True,
        _progress=progress,
        _last_only=True,
    )
    return facts
