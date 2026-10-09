"""Owned original-event daily assumptions; no broker or economic authority."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from typing import Literal
from zoneinfo import ZoneInfo

from trading_bot.config import LoadedConfig
from trading_bot.domain import Instrument, OrderPurpose, Side, require_bounded_decimal
from trading_bot.market_data.etf_capital_features import CapitalFeatureProjection
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_daily_policy import (
    CapitalDailyPolicy,
    CapitalOpeningPolicy,
    capital_daily_policy,
)
from trading_bot.research.etf_capital_feasibility import _config
from trading_bot.research.etf_capital_signals import CapitalCandidate
from trading_bot.simulation.etf_capital_account import (
    CapitalAccountEvent,
    CapitalAccountSubmission,
    CapitalActionAccountReplay,
    CapitalEpisodeFeesFinal,
    CapitalSaleSettlement,
    replay_capital_action_account,
)
from trading_bot.simulation.etf_capital_action_events import (
    CapitalActionEvent,
    CapitalDistributionEntitled,
    CapitalDistributionPaid,
    CapitalSplitApplied,
)
from trading_bot.simulation.etf_capital_daily_entry import (
    _CONTEXT,
    CapitalDailyEntryRequest,
    _Offline,
    simulate_capital_daily_entry,
)
from trading_bot.simulation.etf_capital_daily_exit import (
    CapitalDailyExitRequest,
    select_capital_protection,
    simulate_capital_daily_exit,
)
from trading_bot.simulation.etf_capital_risk import (
    CapitalRiskObservation,
    CapitalRiskReplay,
    replay_capital_action_risk,
)
from trading_bot.simulation.events import EventCursor
from trading_bot.simulation.lifecycle import replay_order_lifecycle
from trading_bot.simulation.lifecycle_models import LifecycleControlEvent, LifecycleFillEvent

type _Event = CapitalAccountEvent | CapitalActionEvent
type _Outcome = Literal["filled", "partial", "rejected", "unfilled"]
_ZONE = ZoneInfo("America/New_York")


def _check(value: bool) -> None:
    if not value:
        raise ValueError("capital_daily_owner_invalid")


@dataclass(frozen=True, slots=True)
class CapitalDailyOriginalFact:
    event: _Event
    mark: Decimal | None
    daily_reset_reconciled: bool = False
    weekly_reset_reviewed: bool = False


@dataclass(frozen=True, slots=True)
class CapitalDailyFrame:
    candidate: CapitalCandidate
    projections: tuple[CapitalFeatureProjection, ...]
    instruments: tuple[Instrument, ...]
    original_facts: tuple[CapitalDailyOriginalFact, ...] = ()
    daily_reset_reconciled: bool = False
    weekly_reset_reviewed: bool = False


@dataclass(frozen=True, slots=True)
class CapitalDailyOwnerRequest(_Offline):
    loaded: LoadedConfig
    initial_cash: Decimal
    frames: tuple[CapitalDailyFrame, ...]
    episode_fee_bound: Decimal | None
    entry_fee: Decimal
    exit_fee: Decimal
    roundtrip_friction_pct: Decimal
    entry_outcome: _Outcome = "filled"
    entry_fill_fraction: Decimal = Decimal(1)
    exit_outcome: _Outcome = "filled"
    exit_fill_fraction: Decimal = Decimal(1)


@dataclass(frozen=True, slots=True)
class CapitalDailyOwnerPoint:
    at: datetime
    equity: Decimal
    account: CapitalActionAccountReplay
    policy: CapitalDailyPolicy
    opening: CapitalOpeningPolicy | None


@dataclass(frozen=True, slots=True)
class CapitalDailyOwnerResult(_Offline):
    events: tuple[_Event, ...]
    observations: tuple[CapitalRiskObservation, ...]
    points: tuple[CapitalDailyOwnerPoint, ...]
    account: CapitalActionAccountReplay
    risk: CapitalRiskReplay
    input_hash: str


def _cursor(event: _Event) -> EventCursor:
    if isinstance(event, CapitalAccountSubmission):
        return event.request.submitted
    return event.cursor


def _active(events: tuple[_Event, ...]) -> bool:
    submissions = tuple(e for e in events if type(e) is CapitalAccountSubmission)
    if not submissions:
        return False
    current = max(submissions, key=lambda e: e.request.submitted.sequence)
    identity = current.request.order.broker_order_id
    controls = tuple(
        e
        for e in events
        if (type(e) is LifecycleControlEvent and e.broker_order_id == identity)
        or (type(e) is LifecycleFillEvent and e.fill.broker_order_id == identity)
    )
    return not replay_order_lifecycle(replace(current.request, events=controls)).order_terminal


def _validate(request: CapitalDailyOwnerRequest) -> None:
    _check(type(request) is CapitalDailyOwnerRequest)
    _check(request.source_qualified is False and request.cost_qualified is False)
    _check(request.execution_enabled is False and request.economic_admitted is False)
    _check(request.evidence_promotable is False)
    _config(request.loaded)
    _check(type(request.frames) is tuple and 0 < len(request.frames) <= 2048)
    for fee in (request.entry_fee, request.exit_fee):
        require_bounded_decimal(fee, "side fee", nonnegative=True)
    if request.episode_fee_bound is not None:
        require_bounded_decimal(request.episode_fee_bound, "episode fee", nonnegative=True)
        _check(request.entry_fee + request.exit_fee <= request.episode_fee_bound)
    _check(request.roundtrip_friction_pct in tuple(map(Decimal, (".05", ".10", ".20", ".40"))))
    for outcome, fraction, fee in (
        (request.entry_outcome, request.entry_fill_fraction, request.entry_fee),
        (request.exit_outcome, request.exit_fill_fraction, request.exit_fee),
    ):
        require_bounded_decimal(fraction, "fill fraction", nonnegative=True)
        _check(type(outcome) is str and outcome in ("filled", "partial", "rejected", "unfilled"))
        _check(
            (outcome == "filled" and fraction == 1)
            or (outcome == "partial" and 0 < fraction < 1)
            or (outcome in ("rejected", "unfilled") and fraction == 0 and fee == 0)
        )


def replay_capital_daily_owner(request: CapitalDailyOwnerRequest) -> CapitalDailyOwnerResult:
    """Recompute a complete assumed trajectory; never adopt saved account state."""
    with localcontext(_CONTEXT):
        _validate(request)
        cfg = _config(request.loaded)
        events: tuple[_Event, ...] = ()
        observations: tuple[CapitalRiskObservation, ...] = ()
        points: list[CapitalDailyOwnerPoint] = []
        bindings: dict[str, CapitalDailyPolicy] = {}
        prior_projections: tuple[CapitalFeatureProjection, ...] = ()
        pending: CapitalDailyPolicy | None = None
        account = replay_capital_action_account(initial_cash=request.initial_cash, events=events)

        def observe(
            at: datetime, mark: Decimal | None, daily: bool = False, weekly: bool = False
        ) -> None:
            nonlocal observations
            sequence = (
                max(
                    (
                        *(_cursor(e).sequence for e in events),
                        *(o.cursor.sequence for o in observations),
                    ),
                    default=-1,
                )
                + 1
            )
            observations = (
                *observations,
                CapitalRiskObservation(EventCursor(sequence, at), len(events), mark, daily, weekly),
            )

        def risk(purpose: OrderPurpose = OrderPurpose.ENTRY) -> CapitalRiskReplay:
            return replay_capital_action_risk(
                loaded=request.loaded,
                initial_cash=request.initial_cash,
                events=events,
                observations=observations,
                purpose=purpose,
            )

        def owned_opening() -> tuple[CapitalOpeningPolicy | None, Decimal | None]:
            if account.quantity == 0:
                return None, None
            buys = tuple(
                e
                for e in events
                if type(e) is CapitalAccountSubmission and e.request.order.side is Side.BUY
            )
            buy = max(buys, key=lambda e: e.request.submitted.sequence)
            instruction = bindings[str(buy.request.order.id)]
            fills = tuple(
                e
                for e in events
                if type(e) is LifecycleFillEvent
                and e.fill.broker_order_id == buy.request.order.broker_order_id
                and e.fill.side is Side.BUY
            )
            fill = min(fills, key=lambda e: e.cursor.sequence)
            if instruction.stop_distance is None:
                raise ValueError("capital_daily_owner_invalid")
            split_ratio = Decimal(1)
            seen_splits: set[str] = set()
            for event in events:
                if (
                    isinstance(event, CapitalSplitApplied)
                    and event.opening_order_id == buy.request.order.id
                    and event.event_id not in seen_splits
                ):
                    split_ratio *= event.ratio
                    seen_splits.add(event.event_id)
            opening = CapitalOpeningPolicy(
                instruction.candidate,
                buy.symbol,
                fill.cursor.occurred_at.astimezone(_ZONE).date(),
                instruction.stop_distance / split_ratio,
            )
            return opening, fill.fill.price / split_ratio

        for frame in request.frames:
            _check(type(frame) is CapitalDailyFrame)
            _check(type(frame.projections) is tuple and len(frame.projections) == 5)
            _check(type(frame.instruments) is tuple and len(frame.instruments) == 5)
            _check(type(frame.original_facts) is tuple)
            prior_raw = {str(p.raw_bars[-1].instrument_id): p.raw_bars for p in prior_projections}
            for projection in frame.projections:
                _check(type(projection) is CapitalFeatureProjection)
                projection.__post_init__()
                symbol = str(projection.raw_bars[-1].instrument_id)
                if prior_projections:
                    _check(symbol in prior_raw)
                    previous = prior_raw[symbol]
                    _check(len(projection.raw_bars) == len(previous) + 1)
                    _check(projection.raw_bars[:-1] == previous)
            prior_projections = frame.projections
            bars = tuple(p.raw_bars[-1] for p in frame.projections)
            opened, closed = bars[0].starts_at, bars[0].ends_at
            _check(all(b.starts_at == opened and b.ends_at == closed for b in bars))
            _check(not points or points[-1].at < opened)
            terms = {i.symbol: i for i in frame.instruments}
            prices = {str(b.instrument_id): b for b in bars}
            _check(set(terms) == set(prices) == {"SPY", "QQQ", "IWM", "SHY", "IEF"})
            for item in frame.instruments:
                _check(type(item) is Instrument)
                item.__post_init__()
                _check(item.observed_at <= opened)
            for fact in frame.original_facts:
                _check(type(fact) is CapitalDailyOriginalFact)
                _check(
                    type(fact.event)
                    in (
                        LifecycleControlEvent,
                        LifecycleFillEvent,
                        CapitalSaleSettlement,
                        CapitalEpisodeFeesFinal,
                        CapitalSplitApplied,
                        CapitalDistributionEntitled,
                        CapitalDistributionPaid,
                    )
                )
                before = account
                candidate_events = (*events, fact.event)
                account = replay_capital_action_account(
                    initial_cash=request.initial_cash, events=candidate_events
                )
                events = candidate_events
                if account.economic_hash != before.economic_hash:
                    _check(_cursor(fact.event).occurred_at <= opened)
                    _check(not points or _cursor(fact.event).occurred_at > points[-1].at)
                    observe(
                        _cursor(fact.event).occurred_at,
                        fact.mark,
                        fact.daily_reset_reconciled,
                        fact.weekly_reset_reviewed,
                    )
            opening, fill_price = owned_opening()
            mark = prices[opening.symbol].open if opening else None
            observe(opened, mark, frame.daily_reset_reconciled, frame.weekly_reset_reviewed)
            risk()

            def exit_at(
                at: datetime,
                base: Decimal,
                purpose: OrderPurpose,
                policy_hash: str,
                owned: CapitalOpeningPolicy,
                instrument: Instrument,
            ) -> None:
                nonlocal events, observations, account
                if _active(events) or not risk(purpose).points[-1].decision.allowed:
                    return
                sequence = observations[-1].cursor.sequence + 1
                cursors: tuple[EventCursor, ...] = (
                    EventCursor(sequence + 1, at + timedelta(seconds=1)),
                )
                if request.exit_fill_fraction:
                    cursors = (*cursors, EventCursor(sequence + 2, at + timedelta(seconds=2)))
                value = simulate_capital_daily_exit(
                    CapitalDailyExitRequest(
                        request.loaded,
                        request.initial_cash,
                        events,
                        observations,
                        instrument,
                        EventCursor(sequence, at),
                        cursors,
                        content_hash(("daily-owner-exit-boundary-v1", owned.symbol, at, base)),
                        policy_hash,
                        base,
                        purpose,
                        request.exit_fee,
                        request.roundtrip_friction_pct,
                        request.exit_outcome,
                        request.exit_fill_fraction,
                    )
                )
                events, observations, account = value.events, value.observations, value.account

            if opening is not None:
                if fill_price is None or mark is None:
                    raise ValueError("capital_daily_owner_invalid")
                stop = fill_price - opening.stop_distance
                target = (
                    fill_price
                    + opening.stop_distance * cfg.equity_strategies.exit_reward_to_initial_risk
                )
                protection = select_capital_protection(raw_open=mark, stop=stop, target=target)
                if protection:
                    exit_at(
                        opened,
                        protection.base_price,
                        OrderPurpose.PROTECTIVE_EXIT,
                        content_hash(opening),
                        opening,
                        terms[opening.symbol],
                    )
                elif pending and pending.action == "exit":
                    exit_at(
                        opened,
                        mark,
                        OrderPurpose.STRATEGY_EXIT,
                        pending.policy_hash,
                        opening,
                        terms[opening.symbol],
                    )
            elif pending and pending.action == "entry" and not _active(events):
                if pending.symbol is None or pending.stop_distance is None:
                    raise ValueError("capital_daily_owner_invalid")
                sequence = observations[-1].cursor.sequence + 1
                entry_cursors: tuple[EventCursor, ...] = (
                    EventCursor(sequence + 1, opened + timedelta(seconds=1)),
                )
                if request.entry_fill_fraction:
                    entry_cursors = (
                        *entry_cursors,
                        EventCursor(sequence + 2, opened + timedelta(seconds=2)),
                    )
                value = simulate_capital_daily_entry(
                    CapitalDailyEntryRequest(
                        request.loaded,
                        request.initial_cash,
                        events,
                        observations,
                        terms[pending.symbol],
                        points[-1].at,
                        EventCursor(sequence, opened),
                        entry_cursors,
                        pending.policy_hash,
                        content_hash(
                            (
                                "daily-owner-entry-boundary-v1",
                                pending.symbol,
                                opened,
                                prices[pending.symbol].open,
                            )
                        ),
                        prices[pending.symbol].open,
                        pending.stop_distance,
                        request.episode_fee_bound,
                        request.entry_fee,
                        request.roundtrip_friction_pct,
                        request.entry_outcome,
                        request.entry_fill_fraction,
                    )
                )
                old_count = len(events)
                events, observations, account = value.events, value.observations, value.account
                if len(events) > old_count:
                    submission = events[old_count]
                    if not isinstance(submission, CapitalAccountSubmission):
                        raise ValueError("capital_daily_owner_invalid")
                    bindings[str(submission.request.order.id)] = pending

            opening, fill_price = owned_opening()
            if opening is not None and not _active(events):
                if fill_price is None:
                    raise ValueError("capital_daily_owner_invalid")
                bar = prices[opening.symbol]
                observe(closed, bar.close)
                stop = fill_price - opening.stop_distance
                target = (
                    fill_price
                    + opening.stop_distance * cfg.equity_strategies.exit_reward_to_initial_risk
                )
                protection = select_capital_protection(
                    raw_open=bar.open, stop=stop, target=target, high=bar.high, low=bar.low
                )
                if protection:
                    exit_at(
                        closed,
                        protection.base_price,
                        OrderPurpose.PROTECTIVE_EXIT,
                        content_hash(opening),
                        opening,
                        terms[opening.symbol],
                    )
            opening, _ = owned_opening()
            at = closed + timedelta(seconds=3)
            observe(at, prices[opening.symbol].close if opening else None)
            final_risk = risk()
            pending = capital_daily_policy(
                loaded=request.loaded,
                candidate=frame.candidate,
                projections=frame.projections,
                as_of=at,
                opening=opening,
            )
            points.append(
                CapitalDailyOwnerPoint(at, final_risk.points[-1].equity, account, pending, opening)
            )
        return CapitalDailyOwnerResult(
            events,
            observations,
            tuple(points),
            account,
            final_risk,
            content_hash(
                (
                    "capital-daily-owner-v1",
                    request.loaded.config_hash,
                    request.initial_cash,
                    request.frames,
                    request.episode_fee_bound,
                    request.entry_fee,
                    request.exit_fee,
                    request.roundtrip_friction_pct,
                    request.entry_outcome,
                    request.entry_fill_fraction,
                    request.exit_outcome,
                    request.exit_fill_fraction,
                )
            ),
        )
