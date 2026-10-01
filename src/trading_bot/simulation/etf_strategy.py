"""Bounded synthetic SPY coordinator; no broker or qualified-history capability.

The common strategy, portfolio planner, account owner and quote driver remain
responsible for their respective decisions. Explicit fixture notices represent
acknowledgements, cancellation and settlement. This module never infers them.
"""

from dataclasses import dataclass, field, replace
from decimal import Decimal, localcontext
from itertools import pairwise
from typing import Literal, cast

from trading_bot.domain import (
    AccountId,
    DataHash,
    Instrument,
    OrderEvent,
    OrderIntentId,
    OrderPurpose,
    OrderState,
    PortfolioSnapshot,
    Side,
)
from trading_bot.domain.decimal_utils import require_bounded_decimal
from trading_bot.market_data.etf_source import (
    EtfControlEvent,
    EtfObservedBar,
    EtfObservedQuote,
    EtfSessionEvent,
    _ceil_time,
    _ns,
)
from trading_bot.market_data.recording import content_hash
from trading_bot.portfolio.intents import IntentPlanner, IntentPlanningContext
from trading_bot.portfolio.targets import ExitPolicy, PortfolioConstructor
from trading_bot.research.etf_costs import EtfCostEvidence, _fee_context
from trading_bot.simulation.etf_account import (
    EtfAccountEvent,
    EtfAccountRequest,
    EtfAccountResult,
    admit_etf_pending_intent,
    replay_etf_account,
)
from trading_bot.simulation.etf_fixture_execution import (
    EtfFixtureAccountObservation,
    EtfFixtureExecutionRequest,
    _Frontier,
    _market_quote_reason,
    _observe,
    run_etf_fixture_execution,
)
from trading_bot.simulation.etf_history import (
    EtfFixturePrefixRequest,
    _policy,
    _session_date,
    _visible_bars,
    etf_fixture_decision_frames,
)
from trading_bot.simulation.etf_history_state import EtfDecisionFrame, EtfHistoryError, _check
from trading_bot.strategies.protocol import StrategyAction

ZERO = Decimal("0")
_TERMINAL = (OrderState.FILLED, OrderState.CANCELED, OrderState.REJECTED, OrderState.EXPIRED)
type _Native = EtfSessionEvent | EtfControlEvent | EtfObservedQuote
type _Observation = _Native | EtfObservedBar | EtfFixtureAccountObservation


@dataclass(frozen=True, slots=True)
class EtfFixtureStrategyRequest:
    prefix: EtfFixturePrefixRequest
    instrument: Instrument
    costs: EtfCostEvidence
    notices: tuple[EtfFixtureAccountObservation, ...]
    episode_fee_bound: Decimal

    def __post_init__(self) -> None:
        _check(type(self.prefix) is EtfFixturePrefixRequest)
        replace(self.prefix)
        _check(type(self.instrument) is Instrument)
        replace(self.instrument)
        _check(self.instrument.id == "SPY")
        _check(type(self.costs) is EtfCostEvidence)
        replace(self.costs)
        require_bounded_decimal(self.episode_fee_bound, "episode fee bound", nonnegative=True)
        _check(type(self.notices) is tuple and len(self.notices) <= 10000)
        for notice in self.notices:
            _check(type(notice) is EtfFixtureAccountObservation)
            replace(notice.payload)
            replace(notice)
        _check(
            all(
                type(e) in (EtfObservedBar, EtfSessionEvent, EtfControlEvent, EtfObservedQuote)
                for e in self.prefix.events
            )
        )
        events = _observations(self)
        _check(len(events) <= 10000)
        _check(len({e.ordinal for e in events}) == len(events))
        _check(all(a.ordinal < b.ordinal for a, b in pairwise(events)))
        _check(
            all(
                _ns(self.prefix.study.requested_start)
                <= e.event_at_ns
                < _ns(self.prefix.study.requested_end)
                for e in events
            )
        )


def _observations(request: EtfFixtureStrategyRequest) -> tuple[_Observation, ...]:
    return tuple(
        sorted(
            (*cast(tuple[_Observation, ...], request.prefix.events), *request.notices),
            key=lambda e: (e.available_at_ns, e.ordinal),
        )
    )


@dataclass(frozen=True, slots=True)
class EtfEntryPolicy:
    order_id: str
    source_ordinal: int
    feature_hash: str
    entry_limit: Decimal
    stop_distance: Decimal
    stop_price: Decimal
    target_price: Decimal
    maximum_holding_bars: int
    exit_on_regime_change: bool


@dataclass(frozen=True, slots=True)
class EtfStrategyDecision:
    source_ordinal: int
    reason: str
    order_id: str | None = None


@dataclass(frozen=True, slots=True)
class EtfFixtureStrategyResult:
    source_count: int
    last_source_ordinal: int | None
    source_prefix_hash: str
    cost_hash: str
    account_events: tuple[EtfAccountEvent, ...]
    account: EtfAccountResult
    policies: tuple[EtfEntryPolicy, ...]
    decisions: tuple[EtfStrategyDecision, ...]
    paused: Literal[True] = field(default=True, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)


def _run(request: EtfFixtureStrategyRequest, count: int) -> EtfFixtureStrategyResult:
    policy = _policy(request.prefix.study)
    cfg = policy.config
    settings = cfg.equity_strategies
    account = EtfAccountRequest(request.prefix.study, request.prefix.initial_cash, ())
    state = replay_etf_account(account)
    frames = {f.observation.source_ordinal: f for f in etf_fixture_decision_frames(request.prefix)}
    frame: EtfDecisionFrame | None = None
    frontier = _Frontier()
    context: list[_Native] = []
    bars: list[EtfObservedBar] = []
    decisions: list[EtfStrategyDecision] = []
    policies: list[EtfEntryPolicy] = []
    triggered: dict[str, str] = {}
    attempted_sessions: set[object] = set()

    def ordinal() -> int:
        return 0 if state.last_ordinal is None else state.last_ordinal + 1

    def append(event: EtfAccountEvent) -> None:
        nonlocal account, state
        candidate = replace(account, events=(*account.events, event))
        restored = replay_etf_account(candidate)
        account, state = candidate, restored

    def decide(event: _Observation, reason: str, order_id: str | None = None) -> None:
        decisions.append(EtfStrategyDecision(event.ordinal, reason, order_id))

    def mark(event: EtfObservedQuote) -> None:
        append(
            EtfAccountEvent(
                content_hash(("etf-strategy-mark-v1", event.source_record_hash, state.prefix_hash)),
                ordinal(),
                event.available_at_ns,
                "mark",
                mark_price=event.payload.bid,
            )
        )

    def propose(event: EtfObservedQuote, *, protective: EtfEntryPolicy | None = None) -> None:
        nonlocal account, state
        if frame is None or frame.observation.signal is None or frontier.clock is None:
            decide(event, "fixture_signal_unavailable")
            return
        signal = frame.observation.signal
        now = _ceil_time(event.available_at_ns)
        close = frontier.clock.payload.next_close_at
        _check(close is not None)
        if close is None:
            raise EtfHistoryError()
        price = event.payload.ask if protective is None else event.payload.bid
        if protective is None:
            atr = frame.atr
            _check(atr is not None)
            if atr is None:
                raise EtfHistoryError()
            distance = atr * settings.stop_loss_atr_multiplier
            if price - distance <= 0:
                decide(event, "fixture_stop_nonpositive")
                return
            exit_policy = ExitPolicy(
                "etf-canonical-exit-v1",
                "atr",
                distance,
                settings.exit_reward_to_initial_risk,
                settings.maximum_holding_bars,
            )
        else:
            distance = protective.stop_distance
            exit_policy = None
            signal = replace(signal, action=StrategyAction.EXIT_LONG)
        position = replace(
            state.position,
            market_value=state.shares * event.payload.bid,
            observed_at=now,
            data_hash=event.source_record_hash,
        )
        exposure = position.market_value
        snapshot = PortfolioSnapshot(
            AccountId("etf-offline"),
            (position,) if state.shares else (),
            state.cash,
            state.cash + exposure + state.dividend_receivable,
            exposure,
            exposure,
            ZERO,
            ZERO,
            ZERO,
            now,
            DataHash(state.prefix_hash),
        )
        target = PortfolioConstructor().construct(
            (signal,),
            snapshot,
            as_of=now,
            config_hash=policy.config_hash,
            exposure_multiplier=Decimal("1"),
            exit_policies=((request.instrument.id, exit_policy),) if exit_policy else (),
        )
        identity = content_hash(
            (
                "etf-strategy-order-v1",
                request.prefix.study.study_hash,
                event.source_record_hash,
                state.prefix_hash,
                protective,
            )
        )
        planned = IntentPlanner(id_factory=lambda: OrderIntentId(identity)).plan(
            target,
            IntentPlanningContext(
                snapshot.account_id,
                snapshot,
                (request.instrument,),
                (("SPY", price),),
                snapshot.equity,
                request.prefix.study.risk_equity_reference,
                cfg.position_risk,
                cfg.activity,
                close - now,
            ),
        )
        if not planned:
            decide(event, "fixture_common_sizing_denied")
            return
        intent = replace(
            planned[0],
            data_hash=content_hash((target.data_hash, event.source_record_hash)),
            purpose=OrderPurpose.ENTRY if protective is None else OrderPurpose.PROTECTIVE_EXIT,
        )
        candidate = EtfAccountEvent(
            content_hash(("etf-strategy-pending-v1", intent)),
            ordinal(),
            _ns(now),
            "pending_intent",
            intent=intent,
            instrument=request.instrument,
            stop_distance=distance,
            fee_bound=request.episode_fee_bound,
        )
        admission = admit_etf_pending_intent(account, candidate)
        if not admission.allowed:
            decide(event, "fixture_account_admission_denied")
            return
        account = replace(account, events=(*account.events, candidate))
        state = admission.state
        if protective is None:
            policies.append(
                EtfEntryPolicy(
                    intent.id,
                    event.ordinal,
                    signal.data_hash,
                    price,
                    distance,
                    price - distance,
                    price + distance * settings.exit_reward_to_initial_risk,
                    settings.maximum_holding_bars,
                    settings.exit_on_regime_change,
                )
            )
        decide(
            event,
            "fixture_protective_reserved" if protective else "fixture_entry_reserved",
            intent.id,
        )

    observations = _observations(request)[:count]
    with localcontext(_fee_context()):
        for event in observations:
            if isinstance(event, EtfFixtureAccountObservation):
                append(event.payload)
                continue
            if isinstance(event, EtfObservedBar):
                bars.append(event)
                continue
            if isinstance(event, (EtfSessionEvent, EtfControlEvent)):
                frontier, _ = _observe(frontier, event)
                context.append(event)
                if event.ordinal in frames:
                    frame = frames[event.ordinal]
                continue
            frontier, reason = _observe(frontier, event)
            reason = reason or _market_quote_reason(event, frontier.clock, account)
            if reason is not None:
                decide(event, reason)
                context.append(event)
                continue
            # The current source record is not in the driver's consumed context.
            active = next((o for o in state.orders if o.order.state not in _TERMINAL), None)
            entry_policy = next(
                (
                    p
                    for p in reversed(policies)
                    if any(o.episode_id == p.order_id for o in state.orders)
                    and (state.shares > 0 or (active and active.intent.side is Side.BUY))
                ),
                None,
            )
            if entry_policy is not None and entry_policy.order_id not in triggered:
                entry_fills = tuple(
                    e
                    for e in account.events
                    if e.fill is not None
                    and e.fill.side is Side.BUY
                    and e.fill.broker_order_id
                    == next(
                        o.order.broker_order_id
                        for o in state.orders
                        if o.intent.id == entry_policy.order_id
                    )
                )
                first_fill = min((e.at_ns for e in entry_fills), default=None)
                holding = len(
                    tuple(
                        b
                        for b in _visible_bars(bars, event.available_at_ns)
                        if first_fill is not None and b.event_at_ns > first_fill
                    )
                )
                trigger = None
                if event.payload.bid <= entry_policy.stop_price:
                    trigger = "fixture_stop_triggered"
                elif event.payload.bid >= entry_policy.target_price:
                    trigger = "fixture_target_triggered"
                elif first_fill is not None and holding >= entry_policy.maximum_holding_bars:
                    trigger = "fixture_maximum_holding"
                elif (
                    entry_policy.exit_on_regime_change
                    and frame is not None
                    and frame.observation.on_cadence
                    and _session_date(frame.observation.observed_at_ns)
                    == _session_date(event.available_at_ns)
                    and frame.atr is not None
                    and frame.observation.signal is not None
                    and frame.observation.signal.action is StrategyAction.HOLD
                    and set(frame.observation.reasons)
                    <= {
                        "synthetic_inputs_only",
                        "source_coverage_unverified",
                        "execution_not_implemented",
                    }
                ):
                    trigger = "fixture_regime_exit"
                if trigger is not None:
                    triggered[entry_policy.order_id] = trigger
                    decide(event, trigger, entry_policy.order_id)
            if entry_policy is not None and entry_policy.order_id in triggered:
                if active is None or active.intent.side is Side.BUY:
                    mark(event)
                if active is not None and active.intent.side is Side.BUY:
                    if active.order.state in (OrderState.SUBMITTED, OrderState.PARTIALLY_FILLED):
                        append(
                            EtfAccountEvent(
                                content_hash(
                                    (
                                        "etf-strategy-cancel-v1",
                                        event.source_record_hash,
                                        active.intent.id,
                                    )
                                ),
                                ordinal(),
                                event.available_at_ns,
                                "order_status",
                                order_id=active.intent.id,
                                order_event=OrderEvent.REQUEST_CANCEL,
                            )
                        )
                    decide(event, "fixture_entry_cancel_reconciliation_required", active.intent.id)
                    context.append(event)
                    continue
                if active is None and state.shares > 0:
                    propose(event, protective=entry_policy)
                    context.append(event)
                    continue
            if active is not None:
                if state.last_at_ns is not None and event.available_at_ns > state.last_at_ns:
                    try:
                        execution = run_etf_fixture_execution(
                            EtfFixtureExecutionRequest(
                                account,
                                (event,),
                                request.costs,
                                active.intent.id,
                                tuple(context),
                            )
                        )
                        account = replace(account, events=execution.account_events)
                        state = execution.account
                        for decision in execution.decisions:
                            decide(event, decision.reason, active.intent.id)
                    except ValueError:
                        decide(event, "fixture_execution_context_denied", active.intent.id)
            elif state.shares > 0:
                mark(event)
            elif (
                frame is not None
                and frame.can_propose_fixture_entry
                and _session_date(frame.observation.observed_at_ns)
                == _session_date(event.available_at_ns)
                and _session_date(event.available_at_ns) not in attempted_sessions
            ):
                attempted_sessions.add(_session_date(event.available_at_ns))
                propose(event)
            context.append(event)
    return EtfFixtureStrategyResult(
        count,
        observations[-1].ordinal if observations else None,
        content_hash(("etf-strategy-consumed-v1", observations)),
        request.costs.cost_hash,
        account.events,
        state,
        tuple(policies),
        tuple(decisions),
    )


def run_etf_fixture_strategy(
    request: EtfFixtureStrategyRequest,
    *,
    through_ordinal: int | None = None,
) -> EtfFixtureStrategyResult:
    try:
        _check(type(request) is EtfFixtureStrategyRequest)
        replace(request)
        events = _observations(request)
        count = len(events)
        if through_ordinal is not None:
            _check(type(through_ordinal) is int and through_ordinal >= 0)
            matches = [i + 1 for i, e in enumerate(events) if e.ordinal == through_ordinal]
            _check(len(matches) == 1)
            count = matches[0]
        return _run(request, count)
    except (ValueError, TypeError, ArithmeticError, AttributeError, RuntimeError, RecursionError):
        raise EtfHistoryError() from None


def resume_etf_fixture_strategy(
    request: EtfFixtureStrategyRequest,
    checkpoint: EtfFixtureStrategyResult,
) -> EtfFixtureStrategyResult:
    try:
        _check(type(request) is EtfFixtureStrategyRequest)
        replace(request)
        _check(type(checkpoint) is EtfFixtureStrategyResult)
        _check(
            type(checkpoint.source_count) is int
            and 0 <= checkpoint.source_count <= len(_observations(request))
        )
        _check(_run(request, checkpoint.source_count) == checkpoint)
        return _run(request, len(_observations(request)))
    except (ValueError, TypeError, ArithmeticError, AttributeError, RuntimeError, RecursionError):
        raise EtfHistoryError() from None
