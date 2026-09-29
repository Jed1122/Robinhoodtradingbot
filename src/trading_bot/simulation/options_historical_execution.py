"""Pure modeled acknowledgements and fills. Quotes are observations, not fill proof."""

from dataclasses import replace
from decimal import Decimal, localcontext

from trading_bot.domain import DataHash
from trading_bot.domain.enums import OrderEvent, OrderState, Side
from trading_bot.domain.options import OptionQuote, OptionsOrderIntent
from trading_bot.domain.order_state_machine import transition
from trading_bot.market_data.options_quote_stream_models import OptionsMarketEvent
from trading_bot.market_data.options_session_inputs import _ns
from trading_bot.market_data.options_source_models import check
from trading_bot.market_data.recording import content_hash
from trading_bot.research.options_study_models import StudyScenario
from trading_bot.simulation.options_historical_models import (
    HISTORICAL_TERMINAL as TERMINAL,
)
from trading_bot.simulation.options_historical_models import (
    HistoricalOrder,
    HistoricalOrderStep,
    HistoricalTransition,
)

FILLABLE = frozenset((OrderState.SUBMITTED, OrderState.PARTIALLY_FILLED, OrderState.CANCEL_PENDING))


def _move(order: HistoricalOrder, event: OrderEvent, at: int) -> HistoricalOrderStep:
    following = transition(order.state, event)
    return HistoricalOrderStep(
        replace(order, state=following), (HistoricalTransition(at, event, order.state, following),)
    )


def propose_order(intent: OptionsOrderIntent, *, available_ns: int) -> HistoricalOrderStep:
    order = HistoricalOrder(intent, OrderState.PROPOSED, available_ns)
    transitions: list[HistoricalTransition] = []
    for event in (
        OrderEvent.RISK_ALLOW,
        OrderEvent.REQUEST_REVIEW,
        OrderEvent.REVIEW_ACCEPTED,
        OrderEvent.PREPARE_SUBMISSION,
    ):
        step = _move(order, event, available_ns)
        order = step.order
        transitions.extend(step.transitions)
    return HistoricalOrderStep(order, tuple(transitions))


def request_cancel(order: HistoricalOrder, *, available_ns: int) -> HistoricalOrderStep:
    check(available_ns >= (order.last_event_ns or order.decision_ns))
    return _move(
        replace(
            order,
            cancel_requested_ns=available_ns,
            last_event_ns=available_ns,
            seen_at_last_ns=order.seen_at_last_ns if available_ns == order.last_event_ns else (),
        ),
        OrderEvent.REQUEST_CANCEL,
        available_ns,
    )


def _draw(order: HistoricalOrder, seed: int, purpose: str) -> int:
    # Deterministic research sampling, not a source of cryptographic randomness.
    return int(content_hash((order.intent.intent_id, seed, purpose)), 16) % 1000000


def advance_order(
    order: HistoricalOrder,
    event: OptionsMarketEvent,
    *,
    scenario: StudyScenario,
    seed: int,
    consumed_units: int = 0,
) -> HistoricalOrderStep:
    check(type(order) is HistoricalOrder and type(event) is OptionsMarketEvent)
    check(type(scenario) is StudyScenario and type(seed) is int and 0 <= seed < 2**63)
    check(type(consumed_units) is int and consumed_units >= 0)
    check(order.scenario_hash is None or order.scenario_hash == scenario.scenario_hash)
    check(order.execution_seed is None or order.execution_seed == seed)
    if event.identity in order.seen_at_last_ns or order.state in TERMINAL:
        return HistoricalOrderStep(order)
    check(event.available_ns >= (order.last_event_ns or order.decision_ns))
    with localcontext() as ctx:
        ctx.prec = 2048
        current = replace(
            order,
            last_event_id=event.identity,
            last_event_ns=event.available_ns,
            scenario_hash=scenario.scenario_hash,
            execution_seed=seed,
            seen_at_last_ns=tuple(
                sorted(
                    (
                        *(
                            order.seen_at_last_ns
                            if event.available_ns == order.last_event_ns
                            else ()
                        ),
                        DataHash(event.identity),
                    )
                )
            ),
        )
        return _advance(current, event, scenario, seed, consumed_units)


def _advance(
    order: HistoricalOrder,
    event: OptionsMarketEvent,
    scenario: StudyScenario,
    seed: int,
    consumed: int,
) -> HistoricalOrderStep:
    at = event.available_ns
    if order.state is OrderState.SUBMISSION_PENDING:
        if at < order.decision_ns + scenario.acknowledgement_ns:
            return HistoricalOrderStep(order)
        outcome = _draw(order, seed, "acknowledgement")
        action = (
            OrderEvent.BROKER_REJECTED
            if outcome < scenario.reject_ppm
            else OrderEvent.BROKER_AMBIGUOUS
            if outcome < scenario.reject_ppm + scenario.ambiguous_ppm
            else OrderEvent.BROKER_ACCEPTED
        )
        return _move(
            replace(order, accepted_ns=at if action is OrderEvent.BROKER_ACCEPTED else None),
            action,
            at,
        )
    if order.state not in FILLABLE:
        return HistoricalOrderStep(order)
    cancel_due = (
        order.cancel_requested_ns is not None
        and at >= order.cancel_requested_ns + scenario.cancel_acknowledgement_ns
    )
    if cancel_due and scenario.cancel_race == "ack_before_fill":
        return _move(order, OrderEvent.CANCEL_CONFIRMED, at)
    fill = _fill(order, event, scenario, seed, consumed)
    if fill.fill_units:
        if cancel_due and fill.order.state is OrderState.CANCEL_PENDING:
            canceled = _move(fill.order, OrderEvent.CANCEL_CONFIRMED, at)
            return replace(
                fill,
                order=canceled.order,
                transitions=(*fill.transitions, *canceled.transitions),
            )
        return fill
    if cancel_due:
        return _move(order, OrderEvent.CANCEL_CONFIRMED, at)
    return HistoricalOrderStep(order)


def _fill(
    order: HistoricalOrder,
    event: OptionsMarketEvent,
    scenario: StudyScenario,
    seed: int,
    consumed: int,
) -> HistoricalOrderStep:
    empty = HistoricalOrderStep(order)
    leg = order.intent.structure.legs[0]
    c = leg.contract
    record = event.record
    if (
        order.accepted_ns is None
        or not event.can_follow(order.accepted_ns)
        or event.event_ns <= order.decision_ns
        or event.available_ns < order.decision_ns + scenario.latency_ns
        or event.event_ns < order.decision_ns + scenario.latency_ns
        or event.available_ns >= _ns(order.intent.expires_at)
        or event.symbol != c.standardized_id
        or record is None
        or type(record.value) is not OptionQuote
    ):
        return empty
    quote = record.value
    if (
        quote.contract_id != c.contract_id
        or quote.underlying != c.underlying
        or quote.quality_flags
        or quote.bid <= 0
        or quote.bid >= quote.ask
        or quote.bid % c.tick_size
        or quote.ask % c.tick_size
        or _draw(order, seed, "unfilled") < scenario.unfilled_ppm
    ):
        return empty
    opening = leg.side is Side.BUY
    size = quote.ask_size if opening else quote.bid_size
    if size is None:
        return empty
    available = max(0, int(Decimal(size) * scenario.participation_pct / 100) - consumed)
    units = min(order.intent.quantity - order.filled_units, available)
    slip = c.tick_size * scenario.slippage_ticks
    price = quote.ask + slip if opening else quote.bid - slip
    if (
        units == 0
        or price <= 0
        or (opening and price > order.intent.limit_price)
        or (not opening and price < order.intent.limit_price)
    ):
        return empty
    fee = (scenario.entry_fee if opening else scenario.exit_fee) * units
    cash = price * c.premium_multiplier * units * (-1 if opening else 1) - fee
    filled = order.filled_units + units
    step = _move(
        replace(order, filled_units=filled),
        OrderEvent.FILL if filled == order.intent.quantity else OrderEvent.PARTIAL_FILL,
        event.available_ns,
    )
    return replace(step, fill_units=units, price=price, cash_flow=cash, fee=fee)
