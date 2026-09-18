"""Incremental virtual-time order simulation; no broker or risk capability."""

import heapq
from copy import copy
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from trading_bot.domain import DataHash, Fill, FillId, OrderEvent, OrderState, Side
from trading_bot.simulation.configured_codec import configured_hash, keyed_rng
from trading_bot.simulation.configured_fills import (
    SimulatedOutcome,
    chance,
    plan_fill,
    price_for_request,
)
from trading_bot.simulation.configured_models import (
    GENERATED_PREFIX,
    ConfiguredErrorReason,
    ConfiguredOrderRequest,
    InstrumentConfiguredOrderRequest,
    SyntheticCancelRequest,
    SyntheticInputEvent,
    SyntheticMarketEvent,
    checked,
    deny,
    utc,
)
from trading_bot.simulation.configured_results import (
    ConfiguredDecision,
    ConfiguredOrderResult,
    DecisionReason,
)
from trading_bot.simulation.configured_validation import IndexedEvent, validate_stream
from trading_bot.simulation.events import EventCursor
from trading_bot.simulation.lifecycle import replay_order_lifecycle
from trading_bot.simulation.lifecycle_models import (
    LifecycleControlEvent,
    LifecycleEvent,
    LifecycleFillEvent,
)

type _ActionKind = Literal["expiry", "submission", "cancel_ack", "input"]


@dataclass(frozen=True, order=True, slots=True)
class _Action:
    at: datetime
    priority: int
    sequence: int
    kind: _ActionKind = field(compare=False)
    event_id: str = field(compare=False)
    digest: DataHash = field(compare=False)
    indexed: IndexedEvent | None = field(default=None, compare=False)


class _Run:
    """Private per-call scheduling state; all balances come from authoritative replay."""

    def __init__(self, request: ConfiguredOrderRequest) -> None:
        self.request = request
        settings: dict[str, object] = {
            "simulation": request.simulation.model_dump(),
            "costs": request.costs.model_dump(),
        }
        if type(request) is InstrumentConfiguredOrderRequest:
            settings["execution"] = {
                "version": request.execution_version,
                "instrument": request.instrument,
            }
        self.settings_hash = configured_hash(
            "settings",
            settings,
        )
        self.base = configured_hash(
            "seed_base",
            {
                "initial": request.initial,
                "settings": self.settings_hash,
                "seed": request.seed,
                "submission_window": request.submission_window,
            },
        )
        self.input_hash = configured_hash(
            "input",
            {
                "base": self.base,
                "events": request.events,
                "end_at": request.end_at,
                "expires_at": request.expires_at,
            },
        )
        self.events: tuple[LifecycleEvent, ...] = ()
        self.lifecycle = replay_order_lifecycle(request.initial)
        self.decisions: list[ConfiguredDecision] = []
        self.queue: list[_Action] = []
        self.latency = timedelta(milliseconds=request.simulation.latency_milliseconds)
        self.ack_at = request.initial.submitted.occurred_at + self.latency
        self.race_available = False
        self._schedule("submission", self.ack_at, 1)
        if request.expires_at is not None:
            self._schedule("expiry", request.expires_at, 0)
        for indexed in validate_stream(request):
            event = indexed.event
            heapq.heappush(
                self.queue,
                _Action(
                    event.cursor.occurred_at,
                    2 if isinstance(event, SyntheticCancelRequest) else 4,
                    event.cursor.sequence,
                    "input",
                    event.event_id,
                    indexed.digest,
                    indexed,
                ),
            )

    def _schedule(
        self, kind: _ActionKind, at: datetime, priority: int, trigger: DataHash | None = None
    ) -> None:
        digest = configured_hash(
            "control", {"base": self.base, "kind": kind, "at": at, "trigger": trigger}
        )
        heapq.heappush(
            self.queue, _Action(at, priority, 0, kind, GENERATED_PREFIX + digest, digest)
        )

    def _event_id(self, action: _Action, kind: str) -> str:
        return GENERATED_PREFIX + configured_hash(
            "generated_id", {"base": self.base, "event": action.digest, "kind": kind}
        )

    def _cursor(self, action: _Action) -> EventCursor:
        return EventCursor(
            self.request.initial.submitted.sequence + len(self.events) + 1, action.at
        )

    def _apply(self, event: LifecycleEvent) -> None:
        candidate = (*self.events, event)
        result = replay_order_lifecycle(replace(self.request.initial, events=candidate))
        self.events = candidate
        self.lifecycle = result

    def _control(self, action: _Action, event: OrderEvent) -> None:
        order = self.request.initial.order
        self._apply(
            LifecycleControlEvent(
                self._event_id(action, event.value),
                self._cursor(action),
                order.account_id,
                order.instrument_id,
                order.broker_order_id,
                event,
            )
        )

    def _guard(self, event: SyntheticMarketEvent) -> DecisionReason | None:
        snapshot = self.lifecycle.snapshot
        if snapshot.order.state is OrderState.SUBMISSION_PENDING:
            return DecisionReason.PENDING
        if self.lifecycle.order_terminal or snapshot.remaining_quantity <= 0:
            return DecisionReason.TERMINAL
        if (
            event.cursor.occurred_at < self.ack_at
            or event.cursor.occurred_at <= self.request.initial.submitted.occurred_at
            or event.window.starts_at < self.request.submission_window.ends_at
        ):
            return DecisionReason.SAME_BAR
        if not event.quote.freshness_verified:
            return DecisionReason.UNVERIFIED
        if not event.clock.is_open:
            return DecisionReason.CLOSED
        if event.clock.halted:
            return DecisionReason.HALTED
        if event.clock.trading_disabled:
            return DecisionReason.DISABLED
        if event.clock.cancel_only:
            return DecisionReason.CANCEL_ONLY
        if snapshot.order.state is OrderState.CANCEL_PENDING and not self.race_available:
            return DecisionReason.RACE_SUPPRESSED
        if event.available_quantity <= 0:
            return DecisionReason.NO_LIQUIDITY
        with checked(ConfiguredErrorReason.ARITHMETIC):
            price = price_for_request(self.request, event)
        limit = snapshot.order.limit_price
        if limit is None:
            deny()
        if (snapshot.order.side is Side.BUY and price > limit) or (
            snapshot.order.side is Side.SELL and price < limit
        ):
            return DecisionReason.LIMIT
        return None

    def _market(
        self,
        action: _Action,
        event: SyntheticMarketEvent,
    ) -> tuple[DecisionReason, SimulatedOutcome | None, SimulatedOutcome | None, Decimal | None]:
        reason = self._guard(event)
        if reason is not None:
            return reason, None, None, None
        snapshot = self.lifecycle.snapshot
        if snapshot.order.state is OrderState.CANCEL_PENDING:
            self.race_available = False
        plan = plan_fill(self.request, event, snapshot.remaining_quantity, self.base, action.digest)
        if plan.fill is None:
            return DecisionReason.NO_FILL, plan.outcome, SimulatedOutcome.NO_FILL, plan.percentage
        fill = plan.fill
        identifier = self._event_id(action, "fill")
        cursor = self._cursor(action)
        order = snapshot.order
        self._apply(
            LifecycleFillEvent(
                identifier,
                cursor,
                Fill(
                    FillId(identifier),
                    order.broker_order_id,
                    order.account_id,
                    order.instrument_id,
                    order.side,
                    fill.quantity,
                    fill.price,
                    fill.fee,
                    action.at,
                    configured_hash(
                        "fill", {"base": self.base, "event": action.digest, "fill": fill}
                    ),
                ),
            )
        )
        realized = (
            SimulatedOutcome.FULL
            if self.lifecycle.snapshot.remaining_quantity == 0
            else SimulatedOutcome.PARTIAL
        )
        reason = (
            DecisionReason.FULL if realized is SimulatedOutcome.FULL else DecisionReason.PARTIAL
        )
        return reason, plan.outcome, realized, plan.percentage

    def _process(
        self,
        action: _Action,
    ) -> tuple[DecisionReason, SimulatedOutcome | None, SimulatedOutcome | None, Decimal | None]:
        if action.kind == "input":
            if action.indexed is None:
                deny()
            event = action.indexed.event
            if isinstance(event, SyntheticMarketEvent):
                return self._market(action, event)
            if self.lifecycle.order_terminal:
                return DecisionReason.ALREADY_TERMINAL, None, None, None
            self._control(action, OrderEvent.REQUEST_CANCEL)
            self.race_available = chance(
                self.request.simulation.cancel_race_probability_pct,
                keyed_rng(self.base, action.digest, "cancel_race"),
            )
            self._schedule("cancel_ack", action.at + self.latency, 3, action.digest)
            return DecisionReason.CANCEL_REQUESTED, None, None, None
        if self.lifecycle.order_terminal:
            return DecisionReason.ALREADY_TERMINAL, None, None, None
        if action.kind == "submission":
            rejected = chance(
                self.request.simulation.rejection_probability_pct,
                keyed_rng(self.base, action.digest, "submission"),
            )
            self._control(
                action, OrderEvent.BROKER_REJECTED if rejected else OrderEvent.BROKER_ACCEPTED
            )
            reason = DecisionReason.REJECTED if rejected else DecisionReason.ACCEPTED
        elif action.kind == "expiry":
            self._control(action, OrderEvent.BROKER_EXPIRED)
            reason = DecisionReason.EXPIRED
        else:
            self._control(action, OrderEvent.CANCEL_CONFIRMED)
            reason = DecisionReason.CANCELED
        return reason, None, None, None

    def advance_to(self, now: datetime) -> ConfiguredOrderResult:
        # Peek first: a partial advance must not discard the next future action.
        while self.queue and self.queue[0].at <= now:
            action = heapq.heappop(self.queue)
            before = len(self.events)
            reason, selected, realized, percentage = self._process(action)
            decision = ConfiguredDecision(
                action.event_id,
                action.digest,
                action.at,
                reason,
                selected,
                realized,
                percentage,
                tuple(event.event_id for event in self.events[before:]),
                self.lifecycle.snapshot.snapshot_hash,
                None if action.indexed is None else action.indexed.delivery_index,
            )
            self.decisions.append(decision)
            if action.indexed is not None:
                for index in action.indexed.duplicate_indices:
                    self.decisions.append(
                        replace(
                            decision,
                            reason=DecisionReason.DUPLICATE,
                            selected_outcome=None,
                            realized_outcome=None,
                            partial_percentage=None,
                            generated_event_ids=(),
                            delivery_index=index,
                            original_event_id=decision.event_id,
                        )
                    )
        return self.result()

    def result(self) -> ConfiguredOrderResult:
        decisions = tuple(self.decisions)
        result_hash = configured_hash(
            "result",
            {
                "input": self.input_hash,
                "settings": self.settings_hash,
                "events": self.events,
                "decisions": decisions,
                "lifecycle": self.lifecycle,
            },
        )
        return ConfiguredOrderResult(
            self.lifecycle, self.events, decisions, self.settings_hash, self.input_hash, result_hash
        )


class ConfiguredOrderSession:
    """Publish only complete validated advances of one synthetic order.

    Deliver inputs before advancing through their timestamp. A published timestamp is
    closed to later input, preserving existing control-before-market precedence. Rebuilding
    on delivery intentionally favors deterministic fixture auditability over throughput.
    This class is synchronous and single-owner, not a thread-safe runtime control.
    """

    def __init__(self, request: ConfiguredOrderRequest) -> None:
        with checked():
            if type(request) not in (ConfiguredOrderRequest, InstrumentConfiguredOrderRequest):
                deny()
            validated = replace(request)
            self._run = _Run(validated)
            self._through: datetime | None = None
            self._result = self._run.result()

    @property
    def result(self) -> ConfiguredOrderResult:
        return self._result

    @property
    def next_event_at(self) -> datetime | None:
        queue = self._run.queue
        if queue and queue[0].at <= self._run.request.end_at:
            return queue[0].at
        return None

    def advance_to(self, now: datetime) -> ConfiguredOrderResult:
        with checked():
            utc(now)
            lower = self._run.request.initial.submitted.occurred_at
            if self._through is not None:
                lower = self._through
            if not lower <= now <= self._run.request.end_at:
                deny(ConfiguredErrorReason.ORDERING)
            # Only the queue/decision lists are mutable; all remaining state is frozen.
            # Stage the whole advance so an accounting failure cannot publish its prefix.
            candidate = copy(self._run)
            candidate.queue = list(self._run.queue)
            candidate.decisions = list(self._run.decisions)
            result = candidate.advance_to(now)
            self._run, self._result, self._through = candidate, result, now
            return result

    def deliver(self, event: SyntheticInputEvent) -> None:
        with checked():
            if type(event) not in (SyntheticMarketEvent, SyntheticCancelRequest):
                deny()
            event.__post_init__()
            if self._through is not None and event.cursor.occurred_at <= self._through:
                deny(ConfiguredErrorReason.ORDERING)
            request = replace(self._run.request, events=(*self._run.request.events, event))
            candidate = _Run(request)
            result = (
                candidate.result() if self._through is None else candidate.advance_to(self._through)
            )
            self._run, self._result = candidate, result
