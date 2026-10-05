"""Independent bounded local projection; no provider transport or risk approval."""

from dataclasses import replace
from decimal import Context, Decimal, DecimalException, Inexact, localcontext

from trading_bot.accounting.owned_economic_codec import encode_economic_event, fee_obligation_id
from trading_bot.accounting.owned_economic_models import (
    MAX_EVENTS,
    Allocation,
    Bind,
    Complete,
    EconomicEvent,
    EconomicState,
    Execution,
    FinalFees,
    Funding,
    Obligation,
    Opening,
    Release,
    Reserve,
    Settlement,
    deny,
)
from trading_bot.domain import AssetClass, OrderState, Position, Side
from trading_bot.domain.owned_order_lifecycle import advance_owned_order
from trading_bot.risk.options_economics import TrialEpisode, TrialLossState

_ZERO = Decimal(0)
_TERMINAL = {OrderState.FILLED, OrderState.CANCELED, OrderState.EXPIRED, OrderState.REJECTED}


def _holds(a: Allocation) -> Allocation:
    if a.released:
        return replace(a, cash_hold=_ZERO, share_hold=_ZERO)
    i = a.reservation.intent
    filled = _ZERO if a.order is None else a.order.filled_quantity
    remaining = i.quantity - filled
    fees = a.reservation.fee_bound - a.recorded_fees
    if fees < 0 or remaining < 0 or i.limit_price is None:
        deny()
    return replace(
        a,
        cash_hold=fees + (remaining * i.limit_price if i.side is Side.BUY else _ZERO),
        share_hold=remaining if i.side is Side.SELL else _ZERO,
    )


def _available(
    cash: Decimal, orders: dict[str, Allocation], obligations: dict[str, Obligation]
) -> Decimal:
    return (
        cash
        - sum((a.cash_hold for a in orders.values()), _ZERO)
        + sum((min(_ZERO, o.amount) for o in obligations.values()), _ZERO)
    )


def project_economics(events: tuple[EconomicEvent, ...]) -> EconomicState:
    return project_economics_and_references(events)[0]


def project_economics_and_references(
    events: tuple[EconomicEvent, ...],
) -> tuple[EconomicState, tuple[tuple[str | None, str | None, str | None], ...]]:
    """Derive journal links from the same actual obligations as money, once."""
    try:
        if type(events) is not tuple or not 1 <= len(events) <= MAX_EVENTS:
            deny()
        context = Context(prec=28)
        context.traps[Inexact] = True
        with localcontext(context):
            return _project(events)
    except (ValueError, TypeError, AttributeError, KeyError, DecimalException):
        deny()


def _project(
    events: tuple[EconomicEvent, ...],
) -> tuple[EconomicState, tuple[tuple[str | None, str | None, str | None], ...]]:
    # Existing arithmetic imports execution's service bootstrap. Defer that import
    # until module initialization is complete, without duplicating its accounting.
    from trading_bot.simulation.events import EventCursor
    from trading_bot.simulation.lifecycle_accounting import apply_lifecycle_fill
    from trading_bot.simulation.lifecycle_models import LifecycleSnapshot

    first = events[0]
    encode_economic_event(first)
    if type(first.payload) is not Opening:
        deny()
    account, config = first.account_id, first.config_hash
    cash = first.payload.cash
    position = Position(
        account,
        first.payload.instrument_id,
        AssetClass.EQUITY,
        _ZERO,
        None,
        _ZERO,
        first.occurred_at,
        first.source_hash,
    )
    orders: dict[str, Allocation] = {}
    order_ids: dict[str, str] = {}
    obligations: dict[str, Obligation] = {}
    obligations_seen: set[str] = set()
    execution_seen: set[str] = set()
    native_seen: set[str] = set()
    fill_counts: dict[str, int] = {}
    episodes: dict[str, TrialEpisode] = {}
    flows: dict[str, Decimal] = {}
    seen = {first.id: encode_economic_event(first)}
    previous_at = first.occurred_at
    references: list[tuple[str | None, str | None, str | None]] = [(None, None, None)]
    for e in events[1:]:
        encoded = encode_economic_event(e)
        if e.id in seen:
            if seen[e.id] != encoded:
                deny()
            continue
        if e.account_id != account or e.config_hash != config or e.occurred_at < previous_at:
            deny()
        seen[e.id] = encoded
        previous_at = e.occurred_at
        p = e.payload
        intent_id: str | None = None
        order_id: str | None = None
        owned_id: str | None = None
        if type(p) is Reserve:
            i = p.intent
            intent_id = i.id
            if (
                i.id in orders
                or i.account_id != account
                or i.instrument_id != position.instrument_id
                or i.config_hash != config
                or not i.created_at <= e.occurred_at < i.expires_at
            ):
                deny()
            if i.side is Side.BUY:
                if (
                    position.quantity != 0
                    or any(not ep.complete for ep in episodes.values())
                    or p.episode_id in episodes
                ):
                    deny()
                episodes[p.episode_id] = TrialEpisode(
                    p.episode_id, p.reserved_risk, None, False, False, False
                )
                flows[p.episode_id] = _ZERO
            else:
                ep = episodes.get(p.episode_id)
                if (
                    ep is None
                    or ep.complete
                    or ep.reserved_risk != p.reserved_risk
                    or i.quantity
                    > position.quantity - sum((a.share_hold for a in orders.values()), _ZERO)
                ):
                    deny()
            allocation = _holds(Allocation(p, None, _ZERO, False, False, _ZERO, _ZERO))
            if allocation.cash_hold > _available(cash, orders, obligations):
                deny()
            orders[i.id] = allocation
        elif type(p) is Bind:
            b = p.order
            a = orders.get(b.intent_id or "")
            if a is None or a.order is not None or b.id in order_ids:
                deny()
            i = a.reservation.intent
            intent_id, order_id = i.id, b.id
            if (
                b.account_id,
                b.instrument_id,
                b.side,
                b.purpose,
                b.order_type,
                b.time_in_force,
                b.requested_quantity,
                b.limit_price,
                b.stop_price,
            ) != (
                i.account_id,
                i.instrument_id,
                i.side,
                i.purpose,
                i.order_type,
                i.time_in_force,
                i.quantity,
                i.limit_price,
                i.stop_price,
            ) or not i.created_at <= b.created_at <= b.updated_at <= e.occurred_at:
                deny()
            order_ids[b.id] = i.id
            orders[i.id] = _holds(replace(a, order=b))
        elif type(p) is Execution:
            fact = p.event
            if fact.id in execution_seen:
                deny()
            key = order_ids.get(fact.order_id)
            if key is None:
                deny()
            a = orders[key]
            intent_id, order_id, owned_id = a.reservation.intent.id, fact.order_id, fact.id
            if a.released or a.fees_final or a.order is None:
                deny()
            projected = advance_owned_order(a.order, fact)
            fill = fact.fill
            if fill is not None:
                if (
                    fill.id in obligations_seen
                    or fact.external_execution_key in native_seen
                    or fact.occurrence_ordinal != fill_counts.get(fact.order_id, 0)
                ):
                    deny()
                if fact.external_execution_key is None:
                    deny()
                native_seen.add(fact.external_execution_key)
                fill_counts[fact.order_id] = fill_counts.get(fact.order_id, 0) + 1
                book = cash + sum((x.amount for x in obligations.values()), _ZERO)
                snapshot = LifecycleSnapshot(
                    a.order,
                    position,
                    book,
                    a.recorded_fees,
                    a.order.requested_quantity - a.order.filled_quantity,
                    EventCursor(len(seen), e.occurred_at),
                    e.source_hash,
                )
                applied = apply_lifecycle_fill(snapshot, fill)
                delta = applied.cash - book
                obligations[fill.id] = Obligation(fill.id, fact.order_id, delta)
                obligations_seen.add(fill.id)
                position = applied.position
                flows[a.reservation.episode_id] += delta
                a = replace(a, recorded_fees=applied.fees)
            execution_seen.add(fact.id)
            orders[key] = _holds(replace(a, order=projected))
        elif type(p) is FinalFees:
            key = order_ids[p.order_id]
            a = orders[key]
            intent_id, order_id = a.reservation.intent.id, p.order_id
            if (
                a.order is None
                or a.order.state not in _TERMINAL
                or a.fees_final
                or not a.recorded_fees <= p.total <= a.reservation.fee_bound
            ):
                deny()
            delta = p.total - a.recorded_fees
            if delta != 0:
                obligation_id = fee_obligation_id(e)
                if obligation_id in obligations_seen:
                    deny()
                obligations[obligation_id] = Obligation(obligation_id, p.order_id, -delta)
                obligations_seen.add(obligation_id)
                flows[a.reservation.episode_id] -= delta
            orders[key] = _holds(replace(a, recorded_fees=p.total, fees_final=True))
        elif type(p) is Settlement:
            obligation = obligations.get(p.obligation_id)
            if obligation is None or obligation.amount != p.amount:
                deny()
            order_id = obligation.order_id
            intent_id = orders[order_ids[order_id]].reservation.intent.id
            cash += p.amount
            del obligations[p.obligation_id]
        elif type(p) is Release:
            key = order_ids[p.order_id]
            a = orders[key]
            intent_id, order_id = a.reservation.intent.id, p.order_id
            if (
                a.released
                or not a.fees_final
                or a.order is None
                or a.order.state not in _TERMINAL
                or any(x.order_id == p.order_id for x in obligations.values())
            ):
                deny()
            orders[key] = _holds(replace(a, released=True))
        elif type(p) is Complete:
            ep = episodes.get(p.episode_id)
            members = [a for a in orders.values() if a.reservation.episode_id == p.episode_id]
            if (
                ep is None
                or ep.complete
                or position.quantity != 0
                or not members
                or any(not a.released for a in members)
            ):
                deny()
            episodes[p.episode_id] = TrialEpisode(
                p.episode_id, ep.reserved_risk, flows[p.episode_id], True, True, True
            )
        elif type(p) is Funding:
            if p.amount < 0 and -p.amount > _available(cash, orders, obligations):
                deny()
            cash += p.amount
        else:
            deny()
        references.append((intent_id, order_id, owned_id))
        if cash < 0 or cash + sum((x.amount for x in obligations.values()), _ZERO) < 0:
            deny()
    state = EconomicState(
        account,
        config,
        position,
        cash,
        cash + sum((o.amount for o in obligations.values()), _ZERO),
        _available(cash, orders, obligations),
        tuple(orders.values()),
        tuple(obligations.values()),
        TrialLossState(tuple(episodes.values())),
        len(seen),
    )
    return state, tuple(references)
