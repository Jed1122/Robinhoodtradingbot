"""Declared synthetic SELL/protection assumptions, never a brokerage route."""

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal, localcontext
from typing import Literal

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
from trading_bot.simulation.etf_capital_account import (
    CapitalAccountEvent,
    CapitalAccountSubmission,
    CapitalActionAccountReplay,
    replay_capital_action_account,
)
from trading_bot.simulation.etf_capital_action_events import CapitalActionEvent
from trading_bot.simulation.etf_capital_daily_entry import _CONTEXT, _Offline
from trading_bot.simulation.etf_capital_risk import (
    CapitalRiskObservation,
    CapitalRiskPoint,
    CapitalRiskReplay,
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


def _check(condition: bool) -> None:
    if not condition:
        raise ValueError("capital_daily_exit_invalid")


@dataclass(frozen=True, slots=True)
class CapitalProtectionPrice:
    base_price: Decimal
    reason: str


def select_capital_protection(
    *,
    raw_open: Decimal,
    stop: Decimal,
    target: Decimal,
    high: Decimal | None = None,
    low: Decimal | None = None,
) -> CapitalProtectionPrice | None:
    """Adverse daily precedence; supplied levels/ranges are unverified facts."""
    for value in (raw_open, stop, target):
        require_bounded_decimal(value, "protection price", positive=True)
    _check(stop < target and (high is None) == (low is None))
    if high is not None and low is not None:
        require_bounded_decimal(high, "high", positive=True)
        require_bounded_decimal(low, "low", positive=True)
        _check(low <= raw_open <= high)
    if raw_open <= stop:
        return CapitalProtectionPrice(raw_open, "stop_gap")
    if raw_open >= target:
        return CapitalProtectionPrice(target, "target_gap_conservative")
    if high is not None and low is not None:
        if low <= stop:
            return CapitalProtectionPrice(
                stop, "stop_first_ambiguous" if high >= target else "stop"
            )
        if high >= target:
            return CapitalProtectionPrice(target, "target")
    return None


@dataclass(frozen=True, slots=True)
class CapitalDailyExitRequest(_Offline):
    loaded: LoadedConfig
    initial_cash: Decimal
    events: tuple[CapitalAccountEvent | CapitalActionEvent, ...]
    observations: tuple[CapitalRiskObservation, ...]
    instrument: Instrument
    submitted: EventCursor
    lifecycle_cursors: tuple[EventCursor, ...]
    source_hash: str
    policy_hash: str
    raw_base_price: Decimal
    purpose: OrderPurpose
    side_fee: Decimal
    roundtrip_friction_pct: Decimal
    outcome: Literal["rejected", "unfilled", "filled", "partial"]
    fill_fraction: Decimal


@dataclass(frozen=True, slots=True)
class CapitalDailyExitResult(_Offline):
    assumed_price: Decimal
    events: tuple[CapitalAccountEvent | CapitalActionEvent, ...]
    observations: tuple[CapitalRiskObservation, ...]
    account: CapitalActionAccountReplay
    risk: CapitalRiskReplay
    input_hash: str


@dataclass(frozen=True, slots=True)
class _CapitalDailyExitFacts(_Offline):
    assumed_price: Decimal
    events: tuple[CapitalAccountEvent | CapitalActionEvent, ...]
    observations: tuple[CapitalRiskObservation, ...]
    account: CapitalActionAccountReplay
    input_hash: str


def _validate(request: CapitalDailyExitRequest) -> None:
    _check(type(request) is CapitalDailyExitRequest)
    _check(
        request.source_qualified is False
        and request.cost_qualified is False
        and request.execution_enabled is False
        and request.economic_admitted is False
        and request.evidence_promotable is False
    )
    _check(type(request.events) is tuple and 0 < len(request.events) <= 4093)
    _check(type(request.observations) is tuple and 0 < len(request.observations) < 4096)
    validate_cursor(request.submitted)
    _check(type(request.instrument) is Instrument)
    request.instrument.__post_init__()
    _check(request.instrument.asset_class is AssetClass.EQUITY)
    _check(request.instrument.observed_at <= request.submitted.occurred_at)
    for value in (
        request.instrument.id,
        request.instrument.symbol,
        request.instrument.provider_status,
        request.instrument.correlation_group,
    ):
        _check(type(value) is str and bool(value.strip()) and len(value) <= 256)
    for value in (request.source_hash, request.policy_hash, request.instrument.data_hash):
        _require_sha256_hex(value, "exit source")
    _check(
        type(request.purpose) is OrderPurpose
        and request.purpose in (OrderPurpose.STRATEGY_EXIT, OrderPurpose.PROTECTIVE_EXIT)
    )
    require_bounded_decimal(request.raw_base_price, "exit price", positive=True)
    require_bounded_decimal(request.side_fee, "exit fee", nonnegative=True)
    require_bounded_decimal(request.fill_fraction, "exit fraction", nonnegative=True)
    require_bounded_decimal(request.roundtrip_friction_pct, "friction", nonnegative=True)
    _check(request.roundtrip_friction_pct in tuple(map(Decimal, (".05", ".10", ".20", ".40"))))
    _check(
        type(request.outcome) is str
        and request.outcome in {"rejected", "unfilled", "filled", "partial"}
    )
    if request.outcome in ("rejected", "unfilled"):
        _check(request.fill_fraction == 0 and request.side_fee == 0)
    elif request.outcome == "filled":
        _check(request.fill_fraction == 1)
    else:
        _check(0 < request.fill_fraction < 1)
    _check(
        type(request.lifecycle_cursors) is tuple
        and len(request.lifecycle_cursors) == (2 if request.fill_fraction else 1)
    )
    previous = request.submitted
    for cursor in request.lifecycle_cursors:
        validate_cursor(cursor)
        _check(cursor.sequence > previous.sequence and cursor.occurred_at > previous.occurred_at)
        _check(cursor.occurred_at.date() == request.submitted.occurred_at.date())
        previous = cursor
    last = request.observations[-1]
    _check(type(last) is CapitalRiskObservation)
    last.__post_init__()
    _check(last.source_count == len(request.events))
    _check(last.cursor.occurred_at == request.submitted.occurred_at)
    _check(last.cursor.sequence < request.submitted.sequence)


def _generate_capital_daily_exit(
    request: CapitalDailyExitRequest, point: CapitalRiskPoint
) -> _CapitalDailyExitFacts:
    """Single emission kernel; wrappers freshly reconstruct the input point."""
    with localcontext(_CONTEXT):
        _check(point.decision.allowed)
        original = point.account
        if type(original) is not CapitalActionAccountReplay:
            raise ValueError("capital_daily_exit_invalid")
        _check(original.quantity > 0 and original.average_price is not None)
        opening = None
        for event in request.events:
            cursor = (
                event.request.submitted
                if isinstance(event, CapitalAccountSubmission)
                else event.cursor
            )
            _check(cursor.sequence < request.submitted.sequence)
            if (
                type(event) is CapitalAccountSubmission
                and event.request.order.side is Side.BUY
                and (opening is None or cursor.sequence > opening.request.submitted.sequence)
            ):
                opening = event
        _check(opening is not None)
        if opening is None:
            raise ValueError("capital_daily_exit_invalid")
        account = AccountId("capital-daily-assumed")
        identity = InstrumentId("capital-research:" + request.instrument.symbol)
        _check(
            opening.symbol == request.instrument.symbol
            and opening.request.order.account_id == account
            and opening.request.order.instrument_id == identity
        )
        tick = request.instrument.price_increment
        require_bounded_decimal(tick, "exit tick", positive=True)
        price = request.raw_base_price * (1 - request.roundtrip_friction_pct / Decimal("200"))
        price = (price / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
        require_bounded_decimal(price, "assumed exit price", positive=True)
        value = original.quantity * request.raw_base_price
        require_bounded_decimal(value, "held value", positive=True)
        digest = content_hash(
            (
                "capital-daily-exit-assumption-v1",
                request.loaded.config_hash,
                request.initial_cash,
                request.events,
                request.observations,
                request.instrument,
                request.submitted,
                request.lifecycle_cursors,
                request.source_hash,
                request.policy_hash,
                request.raw_base_price,
                request.purpose,
                request.side_fee,
                request.roundtrip_friction_pct,
                request.outcome,
                request.fill_fraction,
            )
        )
        order = BrokerOrder(
            OrderId(digest),
            BrokerOrderId(digest),
            account,
            None,
            None,
            identity,
            Side.SELL,
            request.purpose,
            OrderType.LIMIT,
            TimeInForce.GOOD_FOR_DAY,
            original.quantity,
            _ZERO,
            price,
            None,
            OrderState.SUBMISSION_PENDING,
            request.submitted.occurred_at,
            request.submitted.occurred_at,
            DataHash(digest),
        )
        position = Position(
            account,
            identity,
            AssetClass.EQUITY,
            original.quantity,
            original.average_price,
            value,
            request.submitted.occurred_at,
            DataHash(digest),
        )
        submission = CapitalAccountSubmission(
            request.instrument.symbol,
            LifecycleRequest(order, position, original.cash, request.submitted, ()),
            opening.episode_fee_bound,
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
        events = (*request.events, submission, control)
        if request.fill_fraction:
            quantity = (
                original.quantity
                if request.outcome == "filled"
                else quantize_down(
                    original.quantity * request.fill_fraction, request.instrument.quantity_increment
                )
            )
            _check(quantity > 0)
            fill = Fill(
                FillId(digest + ":fill"),
                order.broker_order_id,
                account,
                identity,
                Side.SELL,
                quantity,
                price,
                request.side_fee,
                request.lifecycle_cursors[1].occurred_at,
                DataHash(digest),
            )
            events = (
                *events,
                LifecycleFillEvent(digest + ":fill-event", request.lifecycle_cursors[1], fill),
            )
        state = replay_capital_action_account(initial_cash=request.initial_cash, events=events)
        observations = (
            *request.observations,
            CapitalRiskObservation(
                EventCursor(
                    request.lifecycle_cursors[-1].sequence + 1,
                    request.lifecycle_cursors[-1].occurred_at,
                ),
                len(events),
                request.raw_base_price if state.quantity else None,
                False,
                False,
            ),
        )
        return _CapitalDailyExitFacts(price, events, observations, state, digest)


def simulate_capital_daily_exit(request: CapitalDailyExitRequest) -> CapitalDailyExitResult:
    """Reconstruct originals and emit the unchanged full public risk report."""
    _validate(request)
    with localcontext(_CONTEXT):
        before = replay_capital_action_risk(
            loaded=request.loaded,
            initial_cash=request.initial_cash,
            events=request.events,
            observations=request.observations,
            purpose=request.purpose,
        )
        facts = _generate_capital_daily_exit(request, before.points[-1])
        after = replay_capital_action_risk(
            loaded=request.loaded,
            initial_cash=request.initial_cash,
            events=facts.events,
            observations=facts.observations,
            purpose=request.purpose,
        )
        return CapitalDailyExitResult(
            facts.assumed_price,
            facts.events,
            facts.observations,
            facts.account,
            after,
            facts.input_hash,
        )


def _simulate_owned_capital_daily_exit(
    request: CapitalDailyExitRequest, *, progress: _RiskProgress
) -> _CapitalDailyExitFacts:
    """Owner-local facts, with complete original and generated-suffix validation."""
    _validate(request)
    _check(type(progress) is _RiskProgress)
    with localcontext(_CONTEXT):
        before = _replay_risk_points(
            loaded=request.loaded,
            initial_cash=request.initial_cash,
            events=request.events,
            observations=request.observations,
            purpose=request.purpose,
            actions=True,
            _progress=progress,
            _last_only=True,
        )
        facts = _generate_capital_daily_exit(request, before[-1])
        _replay_risk_points(
            loaded=request.loaded,
            initial_cash=request.initial_cash,
            events=facts.events,
            observations=facts.observations,
            purpose=request.purpose,
            actions=True,
            _progress=progress,
            _last_only=True,
        )
        return facts
