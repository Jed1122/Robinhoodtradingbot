"""Bounded synthetic quote execution around the sole ETF account owner.

This seam consumes an already recorded pending-intent reservation and explicit
acknowledgement facts. It cannot select a strategy, create/acknowledge an order,
model an in-flight cancellation race, infer settlement, or certify real quotes.
Raw synthetic provenance is unchanged; all production/promotion flags stay false.
"""

from dataclasses import dataclass, field, replace
from decimal import Decimal, localcontext
from typing import Literal

from trading_bot.domain import Fill, FillId, OrderState, Side
from trading_bot.domain.decimal_utils import quantize_down, require_bounded_decimal
from trading_bot.market_data.etf_source import (
    EtfControlEvent,
    EtfObservedQuote,
    EtfSessionEvent,
    _ceil_time,
    _ns,
    _sequence,
)
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_costs import EtfCostEvidence, _fee_context, etf_execution_charges
from trading_bot.simulation.costs import SimulatedCosts, execution_price
from trading_bot.simulation.etf_account import (
    EtfAccountEvent,
    EtfAccountOrder,
    EtfAccountRequest,
    EtfAccountResult,
    replay_etf_account,
)
from trading_bot.simulation.etf_history import _policy, _session_date

ZERO = Decimal("0")
_SECOND = Decimal("1000000000")
type EtfFixtureExecutionObservation = (
    EtfSessionEvent | EtfControlEvent | EtfObservedQuote | EtfFixtureAccountObservation
)


class EtfFixtureExecutionError(ValueError):
    def __init__(self) -> None:
        super().__init__("etf_fixture_execution_invalid")


def _check(ok: bool) -> None:
    if not ok:
        raise EtfFixtureExecutionError()


@dataclass(frozen=True, slots=True)
class EtfFixtureAccountObservation:
    """Explicit synthetic lifecycle/settlement fact, not a provider receipt.

    It cannot carry an intent, fill or mark. Those remain owned by account
    admission and the quote-execution seam. Acknowledgement and settlement are
    never inferred from elapsed time, a quote, or an end-of-input boundary.
    """

    ordinal: int
    payload: EtfAccountEvent

    def __post_init__(self) -> None:
        _check(type(self.ordinal) is int and 0 <= self.ordinal < 2**63)
        _check(type(self.payload) is EtfAccountEvent)
        replace(self.payload)
        _check(
            self.payload.kind
            in (
                "order_status",
                "settlement",
                "dividend_ex",
                "dividend_pay",
            )
        )

    @property
    def event_at_ns(self) -> int:
        return self.payload.at_ns

    @property
    def available_at_ns(self) -> int:
        return self.payload.at_ns

    @property
    def source_record_hash(self) -> str:
        return content_hash(("synthetic-account-observation-v1", self.ordinal, self.payload))


@dataclass(frozen=True, slots=True)
class EtfFixtureExecutionRequest:
    account: EtfAccountRequest
    observations: tuple[EtfFixtureExecutionObservation, ...]
    costs: EtfCostEvidence
    order_id: str
    context: tuple[EtfSessionEvent | EtfControlEvent | EtfObservedQuote, ...] = ()

    def __post_init__(self) -> None:
        _check(type(self.account) is EtfAccountRequest)
        replace(self.account)
        _check(type(self.costs) is EtfCostEvidence)
        replace(self.costs)
        _check(self.costs.execution_enabled is False and self.costs.evidence_promotable is False)
        _check(type(self.order_id) is str and 0 < len(self.order_id) <= 128)
        state = replay_etf_account(self.account)
        matches = tuple(o for o in state.orders if o.intent.id == self.order_id)
        _check(len(matches) == 1)
        _check(
            any(
                e.kind == "pending_intent" and e.intent is not None and e.intent.id == self.order_id
                for e in self.account.events
            )
        )
        _check(type(self.observations) is tuple and len(self.observations) <= 10000)
        _check(type(self.context) is tuple and len(self.context) <= 10000)
        # Market observations can advance while no accounting fact occurs (for
        # example, a rejected wide quote). Bound consumed context by the next
        # source receipt, rather than requiring an unrelated account mutation.
        context_limit = (
            self.observations[0].available_at_ns if self.observations else state.last_at_ns
        )
        for context_event in self.context:
            _check(type(context_event) in (EtfSessionEvent, EtfControlEvent, EtfObservedQuote))
            replace(context_event.payload)
            replace(context_event)
            _check(context_limit is not None and context_event.available_at_ns <= context_limit)
            _check(
                _ns(self.account.study.requested_start)
                <= context_event.event_at_ns
                < _ns(self.account.study.requested_end)
            )
        previous: EtfFixtureExecutionObservation | None = None
        seen: set[str] = set()
        for event in self.observations:
            _check(
                type(event)
                in (
                    EtfSessionEvent,
                    EtfControlEvent,
                    EtfObservedQuote,
                    EtfFixtureAccountObservation,
                )
            )
            replace(event.payload)
            replace(event)
            _check(
                _ns(self.account.study.requested_start)
                <= event.event_at_ns
                < _ns(self.account.study.requested_end)
            )
            _check(state.last_at_ns is not None and event.available_at_ns > state.last_at_ns)
            _check(event.source_record_hash not in seen)
            if previous is not None:
                _check(previous.ordinal < event.ordinal)
                _check(previous.available_at_ns <= event.available_at_ns)
            seen.add(event.source_record_hash)
            previous = event
        _sequence(
            (
                *self.context,
                *tuple(
                    e for e in self.observations if not isinstance(e, EtfFixtureAccountObservation)
                ),
            )
        )
        _consumed_execution(self, matches[0])


@dataclass(frozen=True, slots=True)
class _Frontier:
    clock: EtfSessionEvent | EtfControlEvent | None = None
    control_conflict: bool = False
    quote: EtfObservedQuote | None = None
    quote_conflict: bool = False


def _observe(
    frontier: _Frontier, event: EtfSessionEvent | EtfControlEvent | EtfObservedQuote
) -> tuple[_Frontier, str | None]:
    if isinstance(event, (EtfSessionEvent, EtfControlEvent)):
        if frontier.clock is None or event.event_at_ns > frontier.clock.event_at_ns:
            frontier = replace(frontier, clock=event, control_conflict=False)
        elif (
            event.event_at_ns == frontier.clock.event_at_ns
            and event.payload != frontier.clock.payload
        ):
            frontier = replace(frontier, control_conflict=True)
        return frontier, None
    if frontier.quote is None or event.event_at_ns > frontier.quote.event_at_ns:
        frontier = replace(frontier, quote=event, quote_conflict=False)
    elif event.event_at_ns < frontier.quote.event_at_ns:
        return frontier, "fixture_quote_native_time_regression"
    elif (event.payload.bid, event.payload.ask) != (
        frontier.quote.payload.bid,
        frontier.quote.payload.ask,
    ):
        frontier = replace(frontier, quote_conflict=True)
    reason = (
        "fixture_conflicting_native_observations"
        if frontier.control_conflict or frontier.quote_conflict
        else None
    )
    return frontier, reason


@dataclass(frozen=True, slots=True)
class EtfFixtureExecutionDecision:
    source_ordinal: int
    source_hash: str
    reason: str
    fill_id: str | None


@dataclass(frozen=True, slots=True)
class EtfFixtureExecutionResult:
    source_count: int
    last_source_ordinal: int | None
    source_prefix_hash: str
    cost_hash: str
    account_events: tuple[EtfAccountEvent, ...]
    account: EtfAccountResult
    decisions: tuple[EtfFixtureExecutionDecision, ...]
    capacity: tuple[tuple[int, Side, Decimal, Decimal], ...]
    fill_count: int
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)


def _market_quote_reason(
    event: EtfObservedQuote,
    clock: EtfSessionEvent | EtfControlEvent | None,
    account: EtfAccountRequest,
) -> str | None:
    cfg = _policy(account.study).config
    if clock is None:
        return "fixture_control_unknown"
    payload = clock.payload
    if not payload.is_open or payload.halted or payload.trading_disabled or payload.cancel_only:
        return "fixture_control_disabled"
    if (
        payload.next_close_at is None
        or payload.next_open_at is None
        or event.available_at_ns >= _ns(payload.next_close_at)
        or _session_date(event.available_at_ns) != _session_date(clock.event_at_ns)
        or _session_date(_ns(payload.next_close_at)) != _session_date(clock.event_at_ns)
        or _session_date(_ns(payload.next_open_at)) <= _session_date(clock.event_at_ns)
    ):
        return "fixture_session_unavailable"
    if event.event_at_ns <= clock.event_at_ns:
        return "fixture_quote_before_control_epoch"
    if event.available_at_ns - event.event_at_ns > (
        cfg.freshness.max_executable_quote_age_seconds * _SECOND
    ):
        return "fixture_quote_stale"
    quote = event.payload
    # Cross-multiplication keeps exact money arithmetic without requiring an
    # otherwise valid spread percentage to have a terminating decimal quotient.
    if (quote.ask - quote.bid) * 100 > cfg.equities.max_spread_pct * quote.ask:
        return "fixture_spread_too_wide"
    return None


def _quote_reason(
    event: EtfObservedQuote,
    clock: EtfSessionEvent | EtfControlEvent | None,
    record: EtfAccountOrder,
    account: EtfAccountRequest,
    latency: Decimal,
) -> str | None:
    reason = _market_quote_reason(event, clock, account)
    if reason is not None:
        return reason
    if event.event_at_ns <= record.submitted_at_ns:
        return "fixture_quote_before_submission"
    if event.event_at_ns - record.submitted_at_ns < latency * _SECOND or event.event_at_ns <= _ns(
        record.order.updated_at
    ):
        return "fixture_latency_or_ack_pending"
    if event.available_at_ns >= _ns(record.intent.expires_at):
        return "fixture_order_expired"
    return None


def _consumed_execution(
    request: EtfFixtureExecutionRequest, record: EtfAccountOrder
) -> tuple[dict[tuple[int, Side], tuple[Decimal, Decimal]], str | None]:
    """Verify prior simulated fills before carrying fees/capacity across owners.

    Account facts alone cannot assert quote consumption. Every prior fill must
    match an actually consumed fixture quote and the frozen schedule identity.
    This is reconstruction of simulation evidence, never broker authority.
    """
    capacity: dict[tuple[int, Side], tuple[Decimal, Decimal]] = {}
    schedule: str | None = None
    quantity = ZERO
    fees = ZERO
    fills = tuple(
        e
        for e in request.account.events
        if e.fill is not None and e.fill.broker_order_id == record.order.broker_order_id
    )
    with localcontext(_fee_context()):
        for event in request.context:
            if not isinstance(event, EtfObservedQuote):
                continue
            key = (event.event_at_ns, record.intent.side)
            displayed = event.ask_size if record.intent.side is Side.BUY else event.bid_size
            cap, used = capacity.get(key, (displayed, ZERO))
            capacity[key] = (min(cap, displayed), used)
            for fact in fills:
                fill = fact.fill
                if fill is None or fact.at_ns != event.available_at_ns:
                    continue
                charges = etf_execution_charges(
                    request.costs,
                    at=_ceil_time(fact.at_ns),
                    prior_quantity=quantity,
                    quantity=fill.quantity,
                    price=fill.price,
                    prior_schedule_hash=schedule,
                )
                digest = content_hash(
                    (
                        "etf-fixture-fill-v1",
                        request.order_id,
                        event.source_record_hash,
                        fill.quantity,
                        fill.price,
                        charges.fee_schedule_hash,
                    )
                )
                if fact.event_id != digest:
                    continue
                _check(fill.id == FillId(digest) and fill.data_hash == digest)
                _check(fill.fee == charges.total_fee_usd)
                cap, used = capacity[key]
                _check(used + fill.quantity <= cap)
                capacity[key] = (cap, used + fill.quantity)
                quantity += fill.quantity
                fees += fill.fee
                schedule = charges.fee_schedule_hash
        _check(quantity == record.order.filled_quantity and fees == record.fees_paid)
    return capacity, schedule


def _run(request: EtfFixtureExecutionRequest, count: int) -> EtfFixtureExecutionResult:
    account_request = request.account
    state = replay_etf_account(account_request)
    origin = next(
        e
        for e in account_request.events
        if e.intent is not None and e.intent.id == request.order_id
    )
    instrument = origin.instrument
    _check(instrument is not None)
    if instrument is None:
        raise EtfFixtureExecutionError()
    decisions: list[EtfFixtureExecutionDecision] = []
    record = next(o for o in state.orders if o.intent.id == request.order_id)
    capacity, schedule_hash = _consumed_execution(request, record)
    frontier = _Frontier()
    for context_event in request.context:
        frontier, _ = _observe(frontier, context_event)
    fills = 0

    def append(event: EtfAccountEvent) -> None:
        nonlocal account_request, state
        proposed = replace(account_request, events=(*account_request.events, event))
        reconstructed = replay_etf_account(proposed)
        account_request, state = proposed, reconstructed

    def ordinal() -> int:
        return 0 if state.last_ordinal is None else state.last_ordinal + 1

    def mark(event: EtfObservedQuote) -> None:
        append(
            EtfAccountEvent(
                content_hash(("etf-fixture-mark-v1", event.source_record_hash, state.prefix_hash)),
                ordinal(),
                event.available_at_ns,
                "mark",
                mark_price=event.payload.bid,
            )
        )

    prefix = request.observations[:count]
    with localcontext(_fee_context()):
        for event in prefix:
            if isinstance(event, EtfFixtureAccountObservation):
                append(event.payload)
                continue
            if isinstance(event, (EtfSessionEvent, EtfControlEvent)):
                frontier, _ = _observe(frontier, event)
                continue
            record = next(o for o in state.orders if o.intent.id == request.order_id)
            reason: str | None = None
            fill_id: str | None = None
            frontier, reason = _observe(frontier, event)
            if reason is not None:
                decisions.append(
                    EtfFixtureExecutionDecision(
                        event.ordinal,
                        event.source_record_hash,
                        reason,
                        None,
                    )
                )
                continue
            try:
                _check(record.intent.limit_price is not None)
                if record.intent.limit_price is None:
                    raise EtfFixtureExecutionError()
                submitted_cost = etf_execution_charges(
                    request.costs,
                    at=_ceil_time(record.submitted_at_ns),
                    prior_quantity=ZERO,
                    quantity=record.intent.quantity,
                    price=record.intent.limit_price,
                )
                rates = {
                    i.role: i.value
                    for i in request.costs.intervals
                    if i.starts_at <= record.intent.created_at < i.ends_at
                }
                reason = _quote_reason(
                    event, frontier.clock, record, account_request, rates["latency"]
                )
                if reason is None:
                    mark(event)
                    if record.order.state not in (
                        OrderState.SUBMITTED,
                        OrderState.PARTIALLY_FILLED,
                    ):
                        reason = "fixture_order_not_fillable"
                    elif record.intent.side is Side.BUY and state.entry_halted:
                        reason = "fixture_entry_halted"
                if reason is None:
                    key = (event.event_at_ns, record.intent.side)
                    displayed = event.ask_size if record.intent.side is Side.BUY else event.bid_size
                    previous_cap, consumed = capacity.get(key, (displayed, ZERO))
                    cap = min(displayed, previous_cap)
                    capacity[key] = (cap, consumed)
                    increment = instrument.quantity_increment
                    if not instrument.fractional_eligible:
                        increment = max(Decimal("1"), increment)
                    quantity = quantize_down(
                        min(record.remaining, max(ZERO, cap - consumed)),
                        increment,
                    )
                    if quantity == 0:
                        reason = "fixture_capacity_exhausted"
                    else:
                        price = execution_price(
                            side=record.intent.side,
                            bid=event.payload.bid,
                            ask=event.payload.ask,
                            costs=SimulatedCosts(rates["extra_slippage"] / 100, ZERO, ZERO),
                        )
                        rounded = quantize_down(price, instrument.price_increment)
                        if record.intent.side is Side.BUY and rounded < price:
                            rounded += instrument.price_increment
                        price = require_bounded_decimal(
                            rounded, "fixture fill price", positive=True
                        )
                        if (
                            record.intent.side is Side.BUY and price > record.intent.limit_price
                        ) or (
                            record.intent.side is Side.SELL and price < record.intent.limit_price
                        ):
                            reason = "fixture_limit_not_marketable"
                        else:
                            charges = etf_execution_charges(
                                request.costs,
                                at=_ceil_time(event.available_at_ns),
                                prior_quantity=record.order.filled_quantity,
                                quantity=quantity,
                                price=price,
                                prior_schedule_hash=schedule_hash,
                            )
                            if charges.fee_schedule_hash != submitted_cost.fee_schedule_hash:
                                reason = "fixture_fee_schedule_changed"
                            else:
                                # Active schedule, consumed source and order identity only:
                                # full future archive/cost hashes never seed earlier fills.
                                digest = content_hash(
                                    (
                                        "etf-fixture-fill-v1",
                                        request.order_id,
                                        event.source_record_hash,
                                        quantity,
                                        price,
                                        charges.fee_schedule_hash,
                                    )
                                )
                                execution = Fill(
                                    FillId(digest),
                                    record.order.broker_order_id,
                                    record.order.account_id,
                                    record.order.instrument_id,
                                    record.intent.side,
                                    quantity,
                                    price,
                                    charges.total_fee_usd,
                                    _ceil_time(event.available_at_ns),
                                    digest,
                                )
                                append(
                                    EtfAccountEvent(
                                        digest,
                                        ordinal(),
                                        event.available_at_ns,
                                        "fill",
                                        fill=execution,
                                    )
                                )
                                capacity[key] = (cap, consumed + quantity)
                                schedule_hash = charges.fee_schedule_hash
                                fills += 1
                                fill_id = digest
                                mark(event)
            except (ValueError, ArithmeticError, KeyError):
                # An invalid execution observation cannot reset account state,
                # release reserves, create shares or retry with a different size.
                reason = "fixture_execution_observation_denied"
            decisions.append(
                EtfFixtureExecutionDecision(
                    event.ordinal,
                    event.source_record_hash,
                    "fixture_fill_observed"
                    if fill_id is not None
                    else (reason or "fixture_denied"),
                    fill_id,
                )
            )
    return EtfFixtureExecutionResult(
        count,
        prefix[-1].ordinal if prefix else None,
        content_hash(prefix)
        if not request.context
        else content_hash(("etf-execution-context-prefix-v1", request.context, prefix)),
        request.costs.cost_hash,
        account_request.events,
        state,
        tuple(decisions),
        tuple((key[0], key[1], cap, used) for key, (cap, used) in sorted(capacity.items())),
        fills,
    )


def run_etf_fixture_execution(
    request: EtfFixtureExecutionRequest,
    *,
    through_ordinal: int | None = None,
) -> EtfFixtureExecutionResult:
    try:
        _check(type(request) is EtfFixtureExecutionRequest)
        replace(request)
        count = len(request.observations)
        if through_ordinal is not None:
            _check(type(through_ordinal) is int and through_ordinal >= 0)
            matches = [
                i + 1 for i, e in enumerate(request.observations) if e.ordinal == through_ordinal
            ]
            _check(len(matches) == 1)
            count = matches[0]
        return _run(request, count)
    except (ValueError, TypeError, ArithmeticError, RuntimeError, AttributeError, RecursionError):
        raise EtfFixtureExecutionError() from None


def resume_etf_fixture_execution(
    request: EtfFixtureExecutionRequest,
    checkpoint: EtfFixtureExecutionResult,
) -> EtfFixtureExecutionResult:
    """Reconstruct quote consumption and accounting, never trust saved authority."""
    try:
        _check(type(checkpoint) is EtfFixtureExecutionResult)
        _check(
            type(checkpoint.source_count) is int
            and 0 <= checkpoint.source_count <= len(request.observations)
        )
        _check(type(request) is EtfFixtureExecutionRequest)
        replace(request)
        _check(_run(request, checkpoint.source_count) == checkpoint)
        return _run(request, len(request.observations))
    except (ValueError, TypeError, ArithmeticError, RuntimeError, AttributeError, RecursionError):
        raise EtfFixtureExecutionError() from None
