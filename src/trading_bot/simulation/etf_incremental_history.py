"""Versioned, bounded-memory research advancement; no execution capability.

Restart verifies the source prefix once. It does not deserialize a trusted owner
from a caller's output, skip ahead to an unverified cursor or qualify market data.
"""

import hashlib
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Literal

from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.etf_source import _ns
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.simulation.etf_history import _session_date
from trading_bot.simulation.etf_native_history import _outcome_steps
from trading_bot.simulation.etf_native_models import (
    EtfHistoryRequest,
    EtfReplayEvent,
    EtfReplayOutcome,
)

MAX_SOURCE_EVENTS = 100_000_000
MAX_CHUNK_EVENTS = 10_000
MAX_DECISIONS = 10_000
# Quote volume may grow; retained baseline facts and source reason vocabulary may not.
MAX_BASELINE_EVENTS = 150_000
MAX_SOURCE_REASONS = 1_024


def _check(condition: bool) -> None:
    if not condition:
        raise ValueError("etf_incremental_history_invalid")


class _Feed(Iterator[EtfReplayEvent | None]):
    def __init__(self) -> None:
        self.events: deque[EtfReplayEvent] = deque()
        self.closed = False

    def __next__(self) -> EtfReplayEvent | None:
        if self.events:
            return self.events.popleft()
        if self.closed:
            raise StopIteration
        return None


@dataclass(frozen=True, slots=True)
class EtfIncrementalHistoryResult:
    context_hash: str
    catalog_hash: str
    source_count: int
    source_prefix_hash: str
    candidate: EtfReplayOutcome
    constrained_benchmark: EtfReplayOutcome
    candidate_decision_counts: tuple[tuple[str, int], ...]
    benchmark_decision_counts: tuple[tuple[str, int], ...]
    source_exhausted: bool
    holdout_boundary_reached: bool
    schema: Literal["etf-incremental-history-v2"] = field(
        default="etf-incremental-history-v2", init=False
    )
    paused: Literal[True] = field(default=True, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    costs_qualified: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    @property
    def result_hash(self) -> str:
        return content_hash(("etf-incremental-history-result-v2", self))


def run_incremental_etf_history(
    context: EtfHistoryRequest,
    source: Iterator[EtfReplayEvent],
    *,
    catalog_hash: str,
    checkpoint: EtfIncrementalHistoryResult | None = None,
    through_count: int | None = None,
    chunk_size: int = MAX_CHUNK_EVENTS,
) -> EtfIncrementalHistoryResult:
    """Consume ordered development inputs, retaining no whole source tuple.

    `source_exhausted` means normal iterator exhaustion only, not complete market
    coverage or accepted economics. Exceptions after a prefix return no result.
    """
    reducers = []
    try:
        _check(type(context) is EtfHistoryRequest)
        replace(context)
        _require_sha256_hex(catalog_hash, "catalog")
        _check(type(chunk_size) is int and 1 <= chunk_size <= MAX_CHUNK_EVENTS)
        if through_count is not None:
            _check(type(through_count) is int and 0 < through_count <= MAX_SOURCE_EVENTS)
        if checkpoint is not None:
            _check(type(checkpoint) is EtfIncrementalHistoryResult)
            _check(not checkpoint.source_exhausted and not checkpoint.holdout_boundary_reached)
            _check(type(checkpoint.source_count) is int)
            _check(0 < checkpoint.source_count <= MAX_SOURCE_EVENTS)
            if through_count is not None:
                _check(through_count > checkpoint.source_count)

        context_hash = content_hash(("etf-incremental-history-context-v2", context.input_hash))
        feeds = (_Feed(), _Feed())
        counts: tuple[dict[str, int], dict[str, int]] = ({}, {})
        for index, benchmark in enumerate((False, True)):
            reducers.append(
                _outcome_steps(
                    context,
                    feeds[index],
                    benchmark=benchmark,
                    maximum_decisions=MAX_DECISIONS,
                    decision_counts=counts[index],
                )
            )
        outcomes = [next(reducer) for reducer in reducers]
        digest = hashlib.sha256(b"[")
        count = 0
        previous: EtfReplayEvent | None = None
        chunk: list[EtfReplayEvent] = []
        verified_checkpoint = checkpoint is None
        holdout = False
        session_dates: set[date] = set()
        source_reasons: set[str] = set()
        baseline_count = 0

        def flush() -> None:
            if chunk:
                for index, reducer in enumerate(reducers):
                    feeds[index].events.extend(chunk)
                    outcomes[index] = next(reducer)
                chunk.clear()

        def result(exhausted: bool = False) -> EtfIncrementalHistoryResult:
            prefix = digest.copy()
            prefix.update(b"]")
            return EtfIncrementalHistoryResult(
                context_hash,
                catalog_hash,
                count,
                prefix.hexdigest(),
                outcomes[0],
                outcomes[1],
                tuple(sorted(counts[0].items())),
                tuple(sorted(counts[1].items())),
                exhausted,
                holdout,
            )

        for event in source:
            _check(type(event) is EtfReplayEvent)
            replace(event)
            _check(
                _ns(context.study.requested_start)
                <= (_ns(event.bar.starts_at) if event.bar is not None else event.event_at_ns)
                < _ns(context.study.requested_end)
            )
            if previous is not None:
                _check(
                    previous.ordinal < event.ordinal
                    and previous.available_at_ns <= event.available_at_ns
                )
            if event.event_at_ns >= _ns(
                context.study.holdout_start
            ) or event.available_at_ns >= _ns(context.study.holdout_start):
                holdout = True
                break
            _check(count < MAX_SOURCE_EVENTS)
            if event.kind != "quote":
                _check(baseline_count < MAX_BASELINE_EVENTS)
                baseline_count += 1
            if event.kind == "session":
                session_date = _session_date(event.event_at_ns)
                _check(session_date not in session_dates)
                session_dates.add(session_date)
            for reason in event.execution_reasons:
                if reason not in source_reasons:
                    _check(len(source_reasons) < MAX_SOURCE_REASONS)
                    source_reasons.add(reason)
            if count:
                digest.update(b",")
            digest.update(canonical_json(event).encode())
            count += 1
            previous = event
            chunk.append(event)
            boundary = (checkpoint is not None and count == checkpoint.source_count) or (
                through_count is not None and count == through_count
            )
            if len(chunk) == chunk_size or boundary:
                flush()
            if checkpoint is not None and count == checkpoint.source_count:
                _check(result() == checkpoint)
                verified_checkpoint = True
            if through_count is not None and count == through_count:
                _check(verified_checkpoint)
                return result()

        _check(verified_checkpoint)
        _check(through_count is None)
        flush()
        for index, reducer in enumerate(reducers):
            feeds[index].closed = True
            try:
                next(reducer)
            except StopIteration as finished:
                _check(type(finished.value) is EtfReplayOutcome)
                outcomes[index] = finished.value
            else:
                raise ValueError("etf_incremental_history_invalid")
        return result(not holdout)
    except (
        ValueError,
        TypeError,
        ArithmeticError,
        AttributeError,
        OSError,
        RuntimeError,
        RecursionError,
    ):
        raise ValueError("etf_incremental_history_invalid") from None
    finally:
        for reducer in reducers:
            reducer.close()
