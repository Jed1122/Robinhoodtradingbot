"""Causal synthetic decision prefix using the fixed ETF study and common strategy.

This partial owner never executes orders. The qualified historical account path
is deliberately absent until source, action, execution and settlement contracts
are implemented. Resume revalidates/replays the consumed fixture prefix; it is
not a durable ledger or a production restart mechanism.
"""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Any
from zoneinfo import ZoneInfo

from trading_bot.config import LoadedConfig
from trading_bot.config.loader import _restore_canonical_value, restore_loaded_config
from trading_bot.domain import ConfigHash, InstrumentId
from trading_bot.domain.decimal_utils import require_bounded_decimal
from trading_bot.market_data.etf_source import (
    _MAX_RECORDS,
    EtfActionEvent,
    EtfControlEvent,
    EtfObservedBar,
    EtfObservedQuote,
    EtfSessionEvent,
    EtfSourceEvent,
    _ceil_time,
    _ns,
    _sequence,
)
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_study import EtfStudy
from trading_bot.simulation.etf_history_state import (
    EtfDecisionCheckpoint,
    EtfDecisionFrame,
    EtfDecisionObservation,
    EtfFixturePrefixResult,
    EtfHistoryError,
    _check,
)
from trading_bot.strategies.features import FeaturePipeline
from trading_bot.strategies.momentum import MomentumStrategy
from trading_bot.strategies.protocol import (
    FeatureSnapshot,
    FeatureVector,
    HistoricalSlice,
    StrategyContext,
)

_EVENT_TYPES = (EtfObservedBar, EtfObservedQuote, EtfActionEvent, EtfSessionEvent, EtfControlEvent)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_NEW_YORK = ZoneInfo("America/New_York")


def _restore_value(value: object, annotation: Any) -> object:
    """Decode canonical Decimal text by the existing model, not a second schema."""
    try:
        return _restore_canonical_value(value, annotation)
    except (ValueError, TypeError, ArithmeticError, RecursionError):
        raise EtfHistoryError() from None


def _policy(study: EtfStudy) -> LoadedConfig:
    _check(type(study) is EtfStudy)
    _check(type(study.canonical_config) is str and len(study.canonical_config) <= 1048576)
    loaded = restore_loaded_config(study.canonical_config.encode(), ConfigHash(study.config_hash))
    # Reconstruct the record against its own frozen graph, not mutable files/env.
    reconstructed = replace(study, policy=loaded)
    _check(reconstructed == study and reconstructed.study_hash == study.study_hash)
    return loaded


@dataclass(frozen=True, slots=True)
class EtfFixturePrefixRequest:
    study: EtfStudy
    events: tuple[EtfSourceEvent, ...]
    initial_cash: Decimal

    def __post_init__(self) -> None:
        try:
            _policy(self.study)
            require_bounded_decimal(self.initial_cash, "initial cash", positive=True)
            _check(self.initial_cash in self.study.capital_tiers)
            _check(type(self.events) is tuple and len(self.events) <= _MAX_RECORDS)
            daily_intervals: dict[date, tuple[datetime, datetime]] = {}
            for event in self.events:
                _check(type(event) in _EVENT_TYPES)
                # Recheck domain values, including records altered through unsafe
                # construction; no caller-provided fixture label grants trust.
                replace(event.payload)
                replace(event)
                _check(
                    _ns(self.study.requested_start)
                    <= event.event_at_ns
                    < _ns(self.study.requested_end)
                )
                if isinstance(event, EtfObservedBar):
                    # These fixtures represent one session-local daily interval,
                    # not provider midnight bars or a verified exchange calendar.
                    day = _session_date(event.event_at_ns)
                    interval = (event.payload.starts_at, event.payload.ends_at)
                    _check(_session_date(_ns(interval[0])) == day)
                    if day in daily_intervals:
                        _check(event.revision_of is not None and daily_intervals[day] == interval)
                    daily_intervals[day] = interval
            _sequence(self.events)
        except (ValueError, TypeError, ArithmeticError, AttributeError, RecursionError):
            raise EtfHistoryError() from None


def _visible_bars(events: list[EtfObservedBar], at_ns: int) -> tuple[EtfObservedBar, ...]:
    selected: dict[int, EtfObservedBar] = {}
    for event in events:
        if event.event_at_ns < at_ns and event.available_at_ns < at_ns:
            selected[event.event_at_ns] = event
    return tuple(selected[key] for key in sorted(selected))


def _session_date(at_ns: int) -> date:
    # Floor only for the local-date projection; authoritative ordering stays ns.
    return (_EPOCH + timedelta(microseconds=at_ns // 1000)).astimezone(_NEW_YORK).date()


def _decision_frame(
    request: EtfFixturePrefixRequest,
    policy: LoadedConfig,
    event: EtfSessionEvent,
    bars: list[EtfObservedBar],
    actions: list[EtfActionEvent],
    eligible_sessions: int,
) -> EtfDecisionFrame:
    at_ns = event.available_at_ns
    visible = _visible_bars(bars, at_ns)
    selected = visible[-request.study.windows[1] :]
    selected_hashes = tuple(item.source_record_hash for item in selected)
    reasons = ["synthetic_inputs_only", "source_coverage_unverified", "execution_not_implemented"]
    clock = event.payload
    session_ready = clock.is_open and not (
        clock.halted or clock.trading_disabled or clock.cancel_only
    )
    if not session_ready:
        reasons.append("session_not_eligible")
    if clock.next_open_at is None or clock.next_close_at is None:
        session_ready = False
        reasons.append("session_boundaries_unknown")
    elif clock.is_open:
        day = _session_date(event.event_at_ns)
        if not (
            day == _session_date(at_ns) == _session_date(_ns(clock.next_close_at))
            and _session_date(_ns(clock.next_open_at)) > day
        ):
            session_ready = False
            reasons.append("session_identity_inconsistent")
    if clock.next_close_at is not None and at_ns >= _ns(clock.next_close_at):
        session_ready = False
        reasons.append("session_observation_expired")
    history_ready = len(selected) == request.study.windows[1]
    if not history_ready:
        reasons.append("feature_history_insufficient")
    warmup_ready = len(visible) >= policy.config.research.minimum_history_bars
    if not warmup_ready:
        reasons.append("study_warmup_incomplete")
    # Date-only action records cannot prove entitlement/payability or a safe
    # chronological adjustment. Reject affected visible history, never invent it.
    action_affected = bool(selected) and any(
        action.available_at_ns < at_ns
        and selected[0].payload.starts_at.date()
        <= action.payload.effective_date
        <= _session_date(at_ns)
        for action in actions
    )
    if action_affected:
        reasons.append("corporate_action_normalization_unimplemented")
    signal = None
    vector: FeatureVector | None = None
    atr_ready = False
    if history_ready and not action_affected:
        as_of = _ceil_time(at_ns)
        history = HistoricalSlice(
            InstrumentId("SPY"),
            tuple(item.payload for item in selected),
            None,
            content_hash({"bars": selected, "decision_at_ns": at_ns}),
        )
        vector = FeaturePipeline(short_window=20, long_window=100).compute(history, as_of=as_of)
        features = FeatureSnapshot(as_of, (vector,), content_hash((vector,)))
        context = StrategyContext(
            as_of, features, ConfigHash(request.study.config_hash), (InstrumentId("SPY"),)
        )
        signal = MomentumStrategy(short_window=20, long_window=100).decide(context)[0]
        atr = dict(vector.values).get("average_true_range")
        atr_ready = type(atr) is Decimal and atr > 0
    if not atr_ready:
        reasons.append("atr_unavailable")
    cadence = (
        eligible_sessions
        if session_ready and warmup_ready and history_ready and not action_affected
        else None
    )
    if cadence is not None and cadence % request.study.rebalance_sessions:
        reasons.append("between_rebalance_sessions")
    observation = EtfDecisionObservation(
        request.study.study_hash,
        event.source_record_hash,
        event.ordinal,
        at_ns,
        selected_hashes,
        len(visible),
        cadence,
        signal,
        tuple(reasons),
    )
    return EtfDecisionFrame(observation, vector)


def _frames(request: EtfFixturePrefixRequest, count: int) -> tuple[EtfDecisionFrame, ...]:
    policy = _policy(request.study)
    bars: list[EtfObservedBar] = []
    actions: list[EtfActionEvent] = []
    sessions: set[date] = set()
    frames: list[EtfDecisionFrame] = []
    eligible_sessions = 0
    prefix = request.events[:count]
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        for event in prefix:
            if isinstance(event, EtfObservedBar):
                bars.append(event)
            elif isinstance(event, EtfActionEvent):
                actions.append(event)
            elif isinstance(event, EtfSessionEvent):
                day = _session_date(event.event_at_ns)
                if day in sessions:
                    continue
                frame = _decision_frame(request, policy, event, bars, actions, eligible_sessions)
                frames.append(frame)
                decision = frame.observation
                # An ineligible snapshot cannot consume that day's valid opening.
                if decision.cadence_index is not None:
                    sessions.add(day)
                    eligible_sessions += 1
    return tuple(frames)


def _run(request: EtfFixturePrefixRequest, count: int) -> EtfFixturePrefixResult:
    decisions = tuple(frame.observation for frame in _frames(request, count))
    prefix = request.events[:count]
    checkpoint = EtfDecisionCheckpoint(
        request.study.study_hash,
        request.initial_cash,
        count,
        prefix[-1].ordinal if prefix else None,
        prefix[-1].available_at_ns if prefix else None,
        content_hash({"schema": "etf-consumed-prefix-v1", "events": prefix}),
        content_hash(tuple(decisions)),
    )
    return EtfFixturePrefixResult(
        checkpoint, decisions, request.initial_cash, request.study.risk_equity_reference
    )


def etf_fixture_decision_frames(request: EtfFixturePrefixRequest) -> tuple[EtfDecisionFrame, ...]:
    """Expose the same prior-information features for the fixture account owner.

    No source qualification, risk approval or execution authority is conferred.
    Existing diagnostic records, signal identity and prefix hashes are preserved.
    """
    try:
        _check(type(request) is EtfFixturePrefixRequest)
        replace(request)
        return _frames(request, len(request.events))
    except (ValueError, TypeError, ArithmeticError, AttributeError, RecursionError):
        raise EtfHistoryError() from None


def run_etf_fixture_prefix(
    request: EtfFixturePrefixRequest, *, through_ordinal: int | None = None
) -> EtfFixturePrefixResult:
    """Compute diagnostic signals only; never admits orders or changes cash."""
    try:
        _check(type(request) is EtfFixturePrefixRequest)
        replace(request)
        count = len(request.events)
        if through_ordinal is not None:
            _check(type(through_ordinal) is int and through_ordinal >= 0)
            matches = [
                i + 1 for i, event in enumerate(request.events) if event.ordinal == through_ordinal
            ]
            _check(len(matches) == 1)
            count = matches[0]
        return _run(request, count)
    except (ValueError, TypeError, ArithmeticError, AttributeError, RecursionError):
        raise EtfHistoryError() from None


def resume_etf_fixture_prefix(
    request: EtfFixturePrefixRequest, checkpoint: EtfDecisionCheckpoint
) -> EtfFixturePrefixResult:
    """Reconstruct/compare the exact paused prefix before considering later input."""
    try:
        _check(type(request) is EtfFixturePrefixRequest)
        replace(request)
        _check(type(checkpoint) is EtfDecisionCheckpoint)
        replace(checkpoint)
        _check(checkpoint.processed_count <= len(request.events))
        _check(_run(request, checkpoint.processed_count).checkpoint == checkpoint)
        return _run(request, len(request.events))
    except (ValueError, TypeError, ArithmeticError, AttributeError, RecursionError):
        raise EtfHistoryError() from None


__all__ = [
    "EtfFixturePrefixRequest",
    "EtfHistoryError",
    "etf_fixture_decision_frames",
    "resume_etf_fixture_prefix",
    "run_etf_fixture_prefix",
]
