"""One source-bound offline options episode. No broker or live capability exists here.

This is an engineering research consumer, not continuous account qualification.
Completed simulations remain economically ineligible until separate full-path,
calibrated-cost and out-of-sample assessments exist.
"""

import hashlib
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from itertools import islice
from pathlib import Path
from typing import Literal

from trading_bot.config import LoadedConfig
from trading_bot.domain import InstrumentId
from trading_bot.domain.enums import Side
from trading_bot.domain.options import (
    OptionContract,
    OptionKind,
    OptionLeg,
    OptionQuote,
    OptionsOrderIntent,
    OptionStructure,
    PositionEffect,
    StructureKind,
    executable_quote_reasons,
)
from trading_bot.lifecycle.options_expiry import OptionExpiryCalendar, assess_option_expiry
from trading_bot.market_data.bundle_codec import _boolean, _digest, _integer, _json, _mapping
from trading_bot.market_data.options_quote_stream import iter_quote_events
from trading_bot.market_data.options_quote_stream_models import (
    OptionsMarketEvent,
    QuoteStreamRequest,
)
from trading_bot.market_data.options_session_inputs import _fact, _ns
from trading_bot.market_data.options_source_models import PrivateArtifactRef, check
from trading_bot.market_data.options_source_verify import ceil_available_at, verify_source_bundle
from trading_bot.market_data.options_source_wire import encode_source_bundle
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research.options_native_io import read_native_document
from trading_bot.research.options_shortlist_v2 import (
    VerifiedShortlistInput,
    select_verified_shortlist,
)
from trading_bot.research.options_shortlist_v2_wire import encode_verified_shortlist_input
from trading_bot.research.options_study_models import (
    OptionsStudySpec,
    StudyScenario,
    VerifiedHistoryCoverage,
)
from trading_bot.research.options_study_registration import (
    history_is_verified,
    validate_study_registration,
)
from trading_bot.research.options_study_wire import encode_study_spec
from trading_bot.simulation.options_historical_clock import HistoricalClockResult, _EpisodeClock
from trading_bot.simulation.options_historical_models import (
    HISTORICAL_TERMINAL,
    OptionsAccountPathState,
)
from trading_bot.simulation.options_historical_policy import (
    evaluate_historical_entry,
    historical_signal,
)
from trading_bot.simulation.options_historical_restart import clock_state_hash
from trading_bot.simulation.options_replay_wire import replay_file_limits
from trading_bot.strategies.protocol import HistoricalSlice, StrategyAction, StrategyDecision


@dataclass(frozen=True, slots=True)
class HistoricalOptionsRequest:
    spec: OptionsStudySpec
    history: VerifiedHistoryCoverage
    shortlist: VerifiedShortlistInput
    stream: QuoteStreamRequest
    scenario: StudyScenario
    initial: OptionsAccountPathState
    calendars: tuple[OptionExpiryCalendar, ...]
    subsequent_history: tuple[VerifiedHistoryCoverage, ...]
    frozen_spec: PrivateArtifactRef

    def __post_init__(self) -> None:
        for value, cls in (
            (self.spec, OptionsStudySpec),
            (self.history, VerifiedHistoryCoverage),
            (self.shortlist, VerifiedShortlistInput),
            (self.stream, QuoteStreamRequest),
            (self.scenario, StudyScenario),
            (self.initial, OptionsAccountPathState),
            (self.frozen_spec, PrivateArtifactRef),
        ):
            check(type(value) is cls)
        check(type(self.calendars) is tuple and len(self.calendars) == 2)
        check(all(type(c) is OptionExpiryCalendar for c in self.calendars))
        check(type(self.subsequent_history) is tuple and len(self.subsequent_history) <= 10000)
        check(all(type(h) is VerifiedHistoryCoverage for h in self.subsequent_history))


@dataclass(frozen=True, slots=True)
class HistoricalOptionsResult:
    status: Literal["denied", "completed", "incomplete"]
    study_hash: str
    decisions: tuple[tuple[OptionKind, StrategyDecision], ...]
    intents: tuple[OptionsOrderIntent, ...]
    clock: HistoricalClockResult
    reasons: tuple[str, ...]
    priced_candidates: tuple[tuple[str, OptionQuote], ...]
    processed_events: int
    event_prefix_hash: str
    clock_state_hash: str
    production_eligible: Literal[False] = field(default=False, init=False)
    economic_eligible: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    @property
    def net_cash_flow(self) -> Decimal:
        return self.clock.net_cash_flow

    @property
    def fees(self) -> Decimal:
        return self.clock.fees


def _stream_hash(stream: QuoteStreamRequest) -> str:
    return content_hash(
        (
            tuple(f.fact for f in stream.feeds),
            encode_source_bundle(stream.source_bundle).decode(),
            stream.context,
            stream.contracts,
            stream.sessions,
            stream.start_ns,
            stream.end_ns,
        )
    )


def _request_hash(r: HistoricalOptionsRequest) -> str:
    return content_hash(
        (
            r.spec.study_hash,
            r.history.history_hash,
            encode_verified_shortlist_input(r.shortlist).decode(),
            _stream_hash(r.stream),
            r.scenario,
            r.initial,
            r.calendars,
            tuple(h.history_hash for h in r.subsequent_history),
            r.frozen_spec.sha256,
            r.frozen_spec.byte_count,
        )
    )


def _verify(r: HistoricalOptionsRequest, loaded: LoadedConfig, root: Path) -> None:
    # Freeze is read before opening any outcome stream. This cannot certify that
    # someone outside this process has never inspected the outcomes.
    body = read_native_document(r.frozen_spec.path, loaded=loaded, repository_root=root)
    check(len(body) == r.frozen_spec.byte_count)
    check(hashlib.sha256(body).hexdigest() == r.frozen_spec.sha256)
    check(body == encode_study_spec(r.spec))
    report = validate_study_registration(
        r.spec, history=r.history, loaded=loaded, repository_root=root
    )
    allowed = {"research_history_insufficient", "study_splits_invalid"}
    check(
        not report.reasons
        or (r.spec.purpose == "engineering_pilot" and set(report.reasons) <= allowed)
    )
    start = _ns(r.shortlist.session.current.opens_at)
    check(r.history.end_ns == start == r.initial.start_ns)
    check(r.stream.start_ns <= start < r.stream.end_ns)
    check(r.stream.end_ns <= start + r.spec.max_outcome_ns)
    check(r.shortlist.session.current == r.spec.decision_sessions[0])
    check(r.initial.study_hash == r.spec.study_hash)
    check(r.initial.authorized_capital in r.spec.capital_tiers)
    check(dict(r.spec.scenario_hashes)[r.scenario.name] == r.scenario.scenario_hash)
    # Genesis is independently reconstructed by the clock. This API deliberately
    # does not accept a caller-supplied balance as a continuing account path.
    selected = select_verified_shortlist(r.shortlist, loaded=loaded, repository_root=root)
    check(selected.status == "selected")
    check(len(r.stream.contracts) == 2)
    for candidate, contract in zip(selected.candidates, r.stream.contracts, strict=True):
        check(candidate.contract_id == contract.contract_id)
        check(dict(candidate.selected_input_hashes)["contract"] == content_hash(contract))
        check(candidate.reference_close_hash == content_hash(r.history.observations[-1].bar))
        check(contract in r.spec.contracts)
    sources = verify_source_bundle(
        r.stream.source_bundle, context=r.stream.context, loaded=loaded, repository_root=root
    )
    check(sources.status == "verified")
    check(
        tuple(c.contract_id for c in r.calendars)
        == tuple(c.contract_id for c in r.stream.contracts)
    )
    for calendar in r.calendars:
        check(
            _fact(
                sources, "calendar", {"kind": "historical-expiry-calendar-v1", "calendar": calendar}
            )
        )
    previous = r.history
    for history in r.subsequent_history:
        check(history.end_ns > previous.end_ns)
        check(history.observations[: len(previous.observations)] == previous.observations)
        check(history.end_ns in {_ns(s.opens_at) for s in r.stream.sessions})
        verified = verify_source_bundle(
            history.source_bundle, context=history.context, loaded=loaded, repository_root=root
        )
        check(history_is_verified(history, verified))
        previous = history
    for bundle in (
        r.shortlist.bundle,
        r.stream.source_bundle,
        *(h.source_bundle for h in r.subsequent_history),
    ):
        check(
            all(ref.sha256 in r.spec.source_hashes for ref in bundle.references + bundle.manifests)
        )


def _signals(
    history: VerifiedHistoryCoverage, loaded: LoadedConfig
) -> tuple[tuple[OptionKind, StrategyDecision], ...]:
    return historical_signal(
        HistoricalSlice(
            InstrumentId("SPY"),
            tuple(o.bar for o in history.observations),
            None,
            history.history_hash,
        ),
        at=ceil_available_at(history.end_ns),
        loaded=loaded,
    )


def run_historical_options_episode(
    request: HistoricalOptionsRequest,
    *,
    loaded: LoadedConfig,
    repository_root: Path,
    event_limit: int | None = None,
) -> HistoricalOptionsResult:
    check(type(request) is HistoricalOptionsRequest)
    with closing(
        iter_quote_events(request.stream, loaded=loaded, repository_root=repository_root)
    ) as stream:
        return _run_episode(
            request,
            loaded=loaded,
            repository_root=repository_root,
            event_limit=event_limit,
            stream=stream,
        )


def _run_episode(
    request: HistoricalOptionsRequest,
    *,
    loaded: LoadedConfig,
    repository_root: Path,
    event_limit: int | None,
    stream: Iterator[OptionsMarketEvent],
) -> HistoricalOptionsResult:
    check(
        event_limit is None
        or (
            type(event_limit) is int
            and 0 <= event_limit <= loaded.config.options.replay_max_records
        )
    )
    r = request
    _verify(r, loaded, repository_root)
    clock = _EpisodeClock(
        r.initial, (), loaded=loaded, scenario=r.scenario, seed=r.spec.execution_seed
    )
    for contract, calendar in zip(r.stream.contracts, r.calendars, strict=True):
        clock.watch_expiry(contract, calendar)
    decisions = list(_signals(r.history, loaded))
    direction = next((k for k, d in decisions if d.action is StrategyAction.ENTER_LONG), None)
    contracts = {c.kind: c for c in r.stream.contracts}
    calendars = {c.contract_id: c for c in r.calendars}
    quotes: dict[str, OptionQuote] = {}
    intents: list[OptionsOrderIntent] = []
    reasons: set[str] = set()
    priced: tuple[tuple[str, OptionQuote], ...] = ()
    entry_decided = False
    exit_requested = False
    last_close_id: str | None = None
    histories = {h.end_ns: h for h in r.subsequent_history}
    sessions = iter(s for s in r.stream.sessions if _ns(s.opens_at) > clock.now_ns)
    next_session = next(sessions, None)
    first_session = r.shortlist.session.current
    processed_events = 0
    event_prefix_hash = content_hash(("historical-event-prefix-v1", _stream_hash(r.stream)))

    def quote_valid(c: OptionContract, q: OptionQuote) -> bool:
        return (
            not executable_quote_reasons(
                c,
                q,
                as_of=ceil_available_at(clock.now_ns),
                max_age_seconds=loaded.config.freshness.max_executable_quote_age_seconds,
                max_underlying_skew_seconds=loaded.config.market_data.max_cross_response_timestamp_skew_seconds,
                allow_locked=loaded.config.options.allow_locked_quotes,
            )
            and q.bid > 0
        )

    def intent(c: OptionContract, q: OptionQuote, closing: bool) -> OptionsOrderIntent:
        at = ceil_available_at(clock.now_ns)
        session = next(s for s in c.eligible_sessions if s.opens_at <= at < s.closes_at)
        deadline = min(
            session.closes_at,
            at + timedelta(seconds=loaded.config.runtime.remainder_order_max_age_seconds),
        )
        kind = StructureKind.LONG_CALL if c.kind is OptionKind.CALL else StructureKind.LONG_PUT
        return OptionsOrderIntent(
            content_hash(
                ("historical-intent-v1", clock.state.journal_hash, clock.now_ns, c, q, closing)
            ),
            clock.state.path_id,
            OptionStructure(
                kind,
                (
                    OptionLeg(
                        c,
                        Side.SELL if closing else Side.BUY,
                        PositionEffect.CLOSE if closing else PositionEffect.OPEN,
                        1,
                    ),
                ),
            ),
            1,
            q.bid if closing else q.ask,
            "credit" if closing else "debit",
            at,
            deadline,
            "unvalidated-momentum-20-100-v1",
            loaded.config_hash,
            content_hash((c, q)),
            r.spec.exit_policy,
            "limit",
            "day",
        )

    for event in islice(stream, event_limit):
        processed_events += 1
        check(processed_events <= loaded.config.options.replay_max_records)
        event_prefix_hash = content_hash((event_prefix_hash, event.identity))
        if event.available_ns < r.initial.start_ns:
            continue
        while next_session is not None and _ns(next_session.opens_at) <= event.available_ns:
            clock.advance_time(_ns(next_session.opens_at))
            quotes.clear()
            if clock.state.positions:
                history = histories.get(clock.now_ns)
                if history is None:
                    reasons.add("signal_history_unavailable")
                else:
                    following = _signals(history, loaded)
                    decisions.extend(following)
                    exit_requested |= any(
                        k is direction and d.action is not StrategyAction.ENTER_LONG
                        for k, d in following
                    )
            next_session = next(sessions, None)
        clock.advance(event)
        if (
            event.record is not None
            and isinstance(event.record.value, OptionQuote)
            and not event.quality_reasons
        ):
            quotes[event.record.value.contract_id] = event.record.value
        elif event.symbol == "SPY":
            if event.state != "quote" or event.quality_reasons:
                quotes.clear()
        else:
            for c in r.stream.contracts:
                if c.standardized_id == event.symbol:
                    quotes.pop(c.contract_id, None)
        if (
            not entry_decided
            and clock.now_ns < _ns(first_session.closes_at)
            and all(
                c.contract_id in quotes and quote_valid(c, quotes[c.contract_id])
                for c in r.stream.contracts
            )
        ):
            priced = tuple((c.contract_id, quotes[c.contract_id]) for c in r.stream.contracts)
            entry_decided = True
            if direction is None:
                reasons.add("no_momentum_candidate")
            else:
                c = contracts[direction]
                q = quotes[c.contract_id]
                denied = evaluate_historical_entry(
                    state=clock.state,
                    contract=c,
                    quote=q,
                    calendar=calendars[c.contract_id],
                    session=first_session,
                    at=ceil_available_at(clock.now_ns),
                    scenario=r.scenario,
                    loaded=loaded,
                    loss_reasons=(),
                )
                reasons.update(denied)
                if not denied:
                    opening = intent(c, q, False)
                    clock.submit(
                        "episode:" + opening.intent_id,
                        first_session.session_id,
                        opening,
                        available_ns=clock.now_ns,
                    )
                    intents.append(opening)
        if clock.state.positions:
            position = clock.state.positions[0]
            c = position.contract
            expiry = assess_option_expiry(
                contract=c,
                calendar=calendars[c.contract_id],
                as_of=ceil_available_at(clock.now_ns),
                has_exposure=True,
            )
            exit_requested |= bool(expiry.reasons)
            closing_quote = quotes.get(c.contract_id)
            session = next(
                (
                    s
                    for s in c.eligible_sessions
                    if _ns(s.opens_at) <= clock.now_ns < _ns(s.closes_at)
                ),
                None,
            )
            close_terminal_ns = clock.terminal_at(last_close_id) if last_close_id else 0
            if (
                exit_requested
                and closing_quote is not None
                and quote_valid(c, closing_quote)
                and session is not None
                and event.record is not None
                and isinstance(event.record.value, OptionQuote)
                and event.record.value == closing_quote
                and not event.quality_reasons
                and close_terminal_ns is not None
                and event.event_ns > close_terminal_ns
                and all(o.state in HISTORICAL_TERMINAL for o in clock.state.orders)
            ):
                # One new risk-reducing intent per later native quote, never a
                # transport retry or a resend with pending/unknown acceptance.
                # The canonical event cap and frozen horizon bound all attempts.
                closing = intent(c, closing_quote, True)
                clock.submit(
                    position.episode_id, session.session_id, closing, available_ns=clock.now_ns
                )
                intents.append(closing)
                last_close_id = closing.intent_id
    if event_limit is None:
        clock.advance_time(r.stream.end_ns)
    else:
        reasons.add("input_prefix_incomplete")
    result = clock.result()
    if not entry_decided:
        reasons.add("candidate_quotes_unavailable")
    reasons.update(result.reasons)
    status: Literal["denied", "completed", "incomplete"] = (
        "incomplete"
        if event_limit is not None or result.status == "incomplete" or (intents and reasons)
        else "completed"
        if intents
        else "denied"
    )
    return HistoricalOptionsResult(
        status,
        r.spec.study_hash,
        tuple(decisions),
        tuple(intents),
        result,
        tuple(sorted(reasons)),
        priced,
        processed_events,
        event_prefix_hash,
        clock_state_hash(clock),
    )


def encode_episode_checkpoint(
    request: HistoricalOptionsRequest, result: HistoricalOptionsResult, *, loaded: LoadedConfig
) -> bytes:
    """A continuation receipt, not trusted state; restore replays/reverifies its prefix."""
    check(type(request) is HistoricalOptionsRequest and type(result) is HistoricalOptionsResult)
    check(result.study_hash == request.spec.study_hash)
    body = canonical_json(
        {
            "schema": "historical-episode-checkpoint-v1",
            "request_hash": _request_hash(request),
            "processed_events": result.processed_events,
            "prefix_only": "input_prefix_incomplete" in result.reasons,
            "result_hash": content_hash(result),
        }
    ).encode()
    check(len(body) <= replay_file_limits(loaded).max_envelope_bytes)
    return body


def resume_historical_options_episode(
    request: HistoricalOptionsRequest,
    *,
    checkpoint: bytes,
    expected_sha256: str,
    loaded: LoadedConfig,
    repository_root: Path,
) -> HistoricalOptionsResult:
    """Bounded replay-from-genesis recovery, not production restart or broker resubmission.

    No cached risk decision, future fill or balance is trusted. Retained native
    archives, reference facts and the frozen study are all reverified on every run.
    """
    limits = replay_file_limits(loaded)
    check(type(checkpoint) is bytes and len(checkpoint) <= limits.max_envelope_bytes)
    check(hashlib.sha256(checkpoint).hexdigest() == _digest(expected_sha256))
    row = _mapping(
        _json(checkpoint, max_bytes=limits.max_envelope_bytes, limits=limits),
        {"schema", "request_hash", "processed_events", "prefix_only", "result_hash"},
    )
    check(row["schema"] == "historical-episode-checkpoint-v1")
    check(_digest(row["request_hash"]) == _request_hash(request))
    count = _integer(row["processed_events"])
    check(0 <= count <= limits.max_records)
    prefix_only = _boolean(row["prefix_only"])
    prefix = run_historical_options_episode(
        request,
        loaded=loaded,
        repository_root=repository_root,
        event_limit=count if prefix_only else None,
    )
    check(prefix.processed_events == count)
    check(_digest(row["result_hash"]) == content_hash(prefix))
    if not prefix_only:
        return prefix
    return run_historical_options_episode(request, loaded=loaded, repository_root=repository_root)
