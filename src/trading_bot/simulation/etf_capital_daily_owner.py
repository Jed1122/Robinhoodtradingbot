"""Owned original-event daily assumptions; no broker or economic authority."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Literal, cast
from zoneinfo import ZoneInfo

from trading_bot.config import LoadedConfig
from trading_bot.domain import Bar, Instrument, OrderPurpose, Side, require_bounded_decimal
from trading_bot.market_data.etf_calendar import EtfCalendarArchive
from trading_bot.market_data.etf_capital_actions import CapitalSplit
from trading_bot.market_data.etf_capital_features import _CONTEXT as _FEATURE_CONTEXT
from trading_bot.market_data.etf_capital_features import (
    CapitalFeatureProjection,
    _capital_split_bar,
)
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_constrained_policy import (
    _CapitalConstrainedOpening,
    _CapitalConstrainedPolicy,
)
from trading_bot.research.etf_capital_daily_policy import (
    CapitalDailyPolicy,
    CapitalOpeningPolicy,
    capital_daily_policy,
)
from trading_bot.research.etf_capital_feasibility import _config
from trading_bot.research.etf_capital_signals import CapitalCandidate
from trading_bot.simulation import etf_capital_risk
from trading_bot.simulation.etf_capital_account import (
    CapitalAccountEvent,
    CapitalAccountSubmission,
    CapitalActionAccountReplay,
    CapitalEpisodeFeesFinal,
    CapitalSaleSettlement,
    _account_prefixes_owned,
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
    _simulate_owned_capital_daily_entry,
)
from trading_bot.simulation.etf_capital_daily_exit import (
    CapitalDailyExitRequest,
    _simulate_owned_capital_daily_exit,
    select_capital_protection,
)
from trading_bot.simulation.etf_capital_risk import (
    CapitalRiskObservation,
    CapitalRiskPoint,
    CapitalRiskReplay,
    _replay_risk_points,
    _RiskProgress,
)
from trading_bot.simulation.events import EventCursor
from trading_bot.simulation.lifecycle import replay_order_lifecycle
from trading_bot.simulation.lifecycle_models import LifecycleControlEvent, LifecycleFillEvent

type _Event = CapitalAccountEvent | CapitalActionEvent
type _Outcome = Literal["filled", "partial", "rejected", "unfilled"]
type _Policy = CapitalDailyPolicy | _CapitalConstrainedPolicy
type _Opening = CapitalOpeningPolicy | _CapitalConstrainedOpening
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
    entry_decision_allowed: bool = True
    entry_submission_allowed: bool = True


@dataclass(frozen=True, slots=True)
class CapitalDailyOwnerRequest(_Offline):
    loaded: LoadedConfig
    initial_cash: Decimal
    frames: tuple[CapitalDailyFrame, ...]
    episode_fee_bound: Decimal | None
    entry_fee: Decimal
    exit_fee: Decimal
    roundtrip_friction_pct: Decimal
    calendar: EtfCalendarArchive
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


@dataclass(frozen=True, slots=True)
class _CapitalOwnerTerms:
    loaded: LoadedConfig
    initial_cash: Decimal
    episode_fee_bound: Decimal | None
    entry_fee: Decimal
    exit_fee: Decimal
    roundtrip_friction_pct: Decimal
    calendar: EtfCalendarArchive
    entry_outcome: _Outcome
    entry_fill_fraction: Decimal
    exit_outcome: _Outcome
    exit_fill_fraction: Decimal


@dataclass(frozen=True, slots=True)
class _CapitalOwnerFrame:
    bars: tuple[Bar, ...]
    instruments: tuple[Instrument, ...]
    original_facts: tuple[CapitalDailyOriginalFact, ...]
    daily_reset_reconciled: bool
    weekly_reset_reviewed: bool
    entry_decision_allowed: bool
    entry_submission_allowed: bool


@dataclass(frozen=True, slots=True)
class _CapitalOwnerPoint:
    at: datetime
    equity: Decimal
    account: CapitalActionAccountReplay
    policy: _Policy | None
    opening: _Opening | None


@dataclass(frozen=True, slots=True)
class _CapitalOwnerReplay:
    events: tuple[_Event, ...]
    observations: tuple[CapitalRiskObservation, ...]
    points: tuple[_CapitalOwnerPoint, ...]
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


def _feature_continuity(
    prior: CapitalFeatureProjection,
    current: CapitalFeatureProjection,
    facts: tuple[CapitalDailyOriginalFact, ...],
    events: tuple[_Event, ...],
    initial_cash: Decimal,
    prior_splits: tuple[CapitalSplit, ...],
) -> tuple[CapitalSplit, ...]:
    """Allow only original position-bound split rebasing, not revised prices."""
    _check(
        (prior.archive_hash, prior.action_hash, prior.calendar_hash)
        == (current.archive_hash, current.action_hash, current.calendar_hash)
    )
    _check(current.distributions[: len(prior.distributions)] == prior.distributions)
    _check(
        all(
            prior.as_of_session < row.ex_date <= current.as_of_session
            for row in current.distributions[len(prior.distributions) :]
        )
    )
    seen = {event.event_id for event in events if type(event) is CapitalSplitApplied}
    splits = list(prior_splits)
    for index, fact in enumerate(facts):
        _check(type(fact) is CapitalDailyOriginalFact)
        event = fact.event
        if type(event) is CapitalSplitApplied and event.event_id not in seen:
            event.__post_init__()
            if event.symbol == str(current.raw_bars[-1].instrument_id):
                account_before = replay_capital_action_account(
                    initial_cash=initial_cash,
                    events=(*events, *(item.event for item in facts[:index])),
                )
                # The reducer validates the action's account, opening order and
                # symbol when consumed. A terminal unfilled BUY is not a held
                # position and cannot authorize feature-history rebasing.
                _check(account_before.quantity > 0)
                splits.append(CapitalSplit(current.as_of_session, event.ratio, event.record_hash))
            seen.add(event.event_id)
    _check(len({split.effective_date for split in splits}) == len(splits))
    return tuple(splits)


def _validate(request: CapitalDailyOwnerRequest) -> None:
    _check(type(request) is CapitalDailyOwnerRequest)
    _check(request.source_qualified is False and request.cost_qualified is False)
    _check(request.execution_enabled is False and request.economic_admitted is False)
    _check(request.evidence_promotable is False)
    _check(type(request.frames) is tuple and 0 < len(request.frames) <= 2048)
    _validate_owner_terms(request)


def _validate_owner_terms(request: CapitalDailyOwnerRequest | _CapitalOwnerTerms) -> None:
    _config(request.loaded)
    _check(type(request.calendar) is EtfCalendarArchive)
    request.calendar.__post_init__()
    calendar_defaults = EtfCalendarArchive(request.calendar.source_hash, request.calendar.sessions)
    _check(
        type(request.calendar.source_kind) is str
        and request.calendar.source_kind == calendar_defaults.source_kind
        and type(request.calendar.limitations) is tuple
        and all(type(item) is str for item in request.calendar.limitations)
        and request.calendar.limitations == calendar_defaults.limitations
    )
    _check(
        request.calendar.source_qualified is False and request.calendar.evidence_promotable is False
    )
    for session in request.calendar.sessions:
        _check(session.opens_at.tzinfo is UTC and session.closes_at.tzinfo is UTC)
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
        prior_projections: tuple[CapitalFeatureProjection, ...] = ()
        basis_splits: dict[str, tuple[CapitalSplit, ...]] = {}
        calendar_hash = request.calendar.archive_hash

        def frame_at(
            index: int, events: tuple[_Event, ...], observations: tuple[CapitalRiskObservation, ...]
        ) -> _CapitalOwnerFrame:
            nonlocal prior_projections
            frame = request.frames[index]
            _check(type(frame) is CapitalDailyFrame)
            _check(type(frame.entry_decision_allowed) is bool)
            _check(type(frame.entry_submission_allowed) is bool)
            _check(type(frame.projections) is tuple and len(frame.projections) == 5)
            _check(type(frame.instruments) is tuple and len(frame.instruments) == 5)
            _check(type(frame.original_facts) is tuple)
            prior_raw = {str(p.raw_bars[-1].instrument_id): p.raw_bars for p in prior_projections}
            prior_features = {str(p.raw_bars[-1].instrument_id): p for p in prior_projections}
            for projection in frame.projections:
                _check(type(projection) is CapitalFeatureProjection)
                projection.__post_init__()
                _check(projection.calendar_hash == calendar_hash)
                expected_sessions = tuple(
                    (row.opens_at, row.closes_at)
                    for row in request.calendar.sessions
                    if row.session_date <= projection.as_of_session
                )
                _check(
                    tuple((bar.starts_at, bar.ends_at) for bar in projection.raw_bars)
                    == expected_sessions
                )
                symbol = str(projection.raw_bars[-1].instrument_id)
                if prior_projections:
                    _check(symbol in prior_raw)
                    previous = prior_raw[symbol]
                    _check(len(projection.raw_bars) == len(previous) + 1)
                    _check(projection.raw_bars[:-1] == previous)
                    basis_splits[symbol] = _feature_continuity(
                        prior_features[symbol],
                        projection,
                        frame.original_facts,
                        events,
                        request.initial_cash,
                        basis_splits.get(symbol, ()),
                    )
                for raw, feature in zip(projection.raw_bars, projection.feature_bars, strict=True):
                    expected = _capital_split_bar(
                        raw,
                        splits=basis_splits.get(symbol, ()),
                        as_of_session=projection.as_of_session,
                    )
                    _check(replace(expected, data_hash=feature.data_hash) == feature)
            prior_projections = frame.projections
            return _CapitalOwnerFrame(
                tuple(p.raw_bars[-1] for p in frame.projections),
                frame.instruments,
                frame.original_facts,
                frame.daily_reset_reconciled,
                frame.weekly_reset_reviewed,
                frame.entry_decision_allowed,
                frame.entry_submission_allowed,
            )

        def policy_at(index: int, at: datetime, opening: _Opening | None) -> CapitalDailyPolicy:
            if opening is not None and type(opening) is not CapitalOpeningPolicy:
                raise ValueError("capital_daily_owner_invalid")
            frame = request.frames[index]
            return capital_daily_policy(
                loaded=request.loaded,
                candidate=frame.candidate,
                projections=frame.projections,
                as_of=at,
                opening=opening,
            )

        def identity() -> str:
            return content_hash(
                (
                    "capital-daily-owner-v5",
                    request.loaded.config_hash,
                    calendar_hash,
                    request.initial_cash,
                    tuple(
                        content_hash(("capital-daily-owner-frame-v1", f)) for f in request.frames
                    ),
                    request.episode_fee_bound,
                    request.entry_fee,
                    request.exit_fee,
                    request.roundtrip_friction_pct,
                    request.entry_outcome,
                    request.entry_fill_fraction,
                    request.exit_outcome,
                    request.exit_fill_fraction,
                )
            )

        result = _replay_capital_owner(
            _CapitalOwnerTerms(
                request.loaded,
                request.initial_cash,
                request.episode_fee_bound,
                request.entry_fee,
                request.exit_fee,
                request.roundtrip_friction_pct,
                request.calendar,
                request.entry_outcome,
                request.entry_fill_fraction,
                request.exit_outcome,
                request.exit_fill_fraction,
            ),
            count=len(request.frames),
            frame_at=frame_at,
            policy_at=policy_at,
            identity=identity,
        )
        public_points = []
        for point in result.points:
            if type(point.policy) is not CapitalDailyPolicy or (
                point.opening is not None and type(point.opening) is not CapitalOpeningPolicy
            ):
                raise ValueError("capital_daily_owner_invalid")
            public_points.append(
                CapitalDailyOwnerPoint(
                    point.at, point.equity, point.account, point.policy, point.opening
                )
            )
        return CapitalDailyOwnerResult(
            result.events,
            result.observations,
            tuple(public_points),
            result.account,
            result.risk,
            result.input_hash,
        )


def _replay_capital_owner(
    request: _CapitalOwnerTerms,
    *,
    count: int,
    frame_at: Callable[
        [int, tuple[_Event, ...], tuple[CapitalRiskObservation, ...]], _CapitalOwnerFrame
    ],
    policy_at: Callable[[int, datetime, _Opening | None], _Policy | None],
    identity: Callable[[], str],
) -> _CapitalOwnerReplay:
    """Single private execution loop; providers are frontend-owned, never public inputs."""
    with localcontext(_CONTEXT):
        _validate_owner_terms(request)
        _check(type(count) is int and 0 < count <= 2048)
        cfg = _config(request.loaded)
        events: tuple[_Event, ...] = ()
        observations: tuple[CapitalRiskObservation, ...] = ()
        points: list[_CapitalOwnerPoint] = []
        bindings: dict[str, _Policy] = {}
        pending: _Policy | None = None
        account = replay_capital_action_account(initial_cash=request.initial_cash, events=events)
        risk_progress = _RiskProgress()

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

        def risk(
            purpose: OrderPurpose = OrderPurpose.ENTRY, *, full: bool = False
        ) -> tuple[CapitalRiskPoint, ...]:
            return _replay_risk_points(
                loaded=request.loaded,
                initial_cash=request.initial_cash,
                events=events,
                observations=observations,
                purpose=purpose,
                actions=True,
                _progress=risk_progress,
                _last_only=not full,
            )

        def owned_opening() -> tuple[_Opening | None, Decimal | None]:
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
            with localcontext(_FEATURE_CONTEXT):
                split_ratio = Decimal(1)
                seen_splits: set[str] = set()
                for event in events:
                    if (
                        isinstance(event, CapitalSplitApplied)
                        and event.opening_order_id == buy.request.order.id
                        and event.event_id not in seen_splits
                    ):
                        split_ratio *= event.ratio
                        require_bounded_decimal(
                            split_ratio, "cumulative split factor", positive=True
                        )
                        seen_splits.add(event.event_id)
                opening: _Opening
                if type(instruction) is CapitalDailyPolicy:
                    opening = CapitalOpeningPolicy(
                        instruction.candidate,
                        buy.symbol,
                        fill.cursor.occurred_at.astimezone(_ZONE).date(),
                        instruction.stop_distance / split_ratio,
                    )
                elif type(instruction) is _CapitalConstrainedPolicy:
                    opening = _CapitalConstrainedOpening(
                        buy.symbol,
                        fill.cursor.occurred_at.astimezone(_ZONE).date(),
                        instruction.stop_distance / split_ratio,
                    )
                else:
                    raise ValueError("capital_daily_owner_invalid")
                return opening, fill.fill.price / split_ratio

        for index in range(count):
            frame = frame_at(index, events, observations)
            _check(type(frame) is _CapitalOwnerFrame)
            _check(type(frame.entry_decision_allowed) is bool)
            _check(type(frame.entry_submission_allowed) is bool)
            _check(type(frame.instruments) is tuple and len(frame.instruments) == 5)
            _check(type(frame.original_facts) is tuple)
            bars = frame.bars
            _check(type(bars) is tuple and len(bars) == 5)
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
                _, candidate_accounts = _account_prefixes_owned(
                    risk_progress.accounts,
                    initial_cash=request.initial_cash,
                    events=candidate_events,
                    actions=True,
                )
                account = cast(CapitalActionAccountReplay, candidate_accounts[-1])
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
            if (
                observations
                and observations[-1].cursor.occurred_at == opened
                and observations[-1].source_count == len(events)
            ):
                prior_observation = observations[-1]
                _check(
                    prior_observation.mark is None or mark is None or prior_observation.mark == mark
                )
                observations = (
                    *observations[:-1],
                    replace(
                        prior_observation,
                        mark=mark if mark is not None else prior_observation.mark,
                        daily_reset_reconciled=(
                            prior_observation.daily_reset_reconciled or frame.daily_reset_reconciled
                        ),
                        weekly_reset_reviewed=(
                            prior_observation.weekly_reset_reviewed or frame.weekly_reset_reviewed
                        ),
                    ),
                )
            else:
                observe(opened, mark, frame.daily_reset_reconciled, frame.weekly_reset_reviewed)
            risk()

            def exit_at(
                at: datetime,
                base: Decimal,
                purpose: OrderPurpose,
                policy_hash: str,
                owned: _Opening,
                instrument: Instrument,
            ) -> None:
                nonlocal events, observations, account
                if _active(events) or not risk(purpose)[-1].decision.allowed:
                    return
                sequence = observations[-1].cursor.sequence + 1
                cursors: tuple[EventCursor, ...] = (
                    EventCursor(sequence + 1, at + timedelta(seconds=1)),
                )
                if request.exit_fill_fraction:
                    cursors = (*cursors, EventCursor(sequence + 2, at + timedelta(seconds=2)))
                value = _simulate_owned_capital_daily_exit(
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
                    ),
                    progress=risk_progress,
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
            elif (
                pending
                and pending.action == "entry"
                and frame.entry_submission_allowed
                and not _active(events)
            ):
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
                value = _simulate_owned_capital_daily_entry(
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
                    ),
                    progress=risk_progress,
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
            final_risk = risk(full=index == count - 1)
            pending = policy_at(index, at, opening)
            if (
                pending is not None
                and pending.action == "entry"
                and not frame.entry_decision_allowed
            ):
                pending = replace(
                    pending,
                    action="wait",
                    symbol=None,
                    stop_distance=None,
                    reason="entry_decision_disabled",
                    policy_hash=content_hash(
                        ("capital-owner-entry-disabled-v2", pending.policy_hash)
                    ),
                )
            points.append(_CapitalOwnerPoint(at, final_risk[-1].equity, account, pending, opening))
        return _CapitalOwnerReplay(
            events,
            observations,
            tuple(points),
            account,
            etf_capital_risk._risk_result(
                request.loaded, request.initial_cash, OrderPurpose.ENTRY, final_risk, actions=True
            ),
            identity(),
        )
