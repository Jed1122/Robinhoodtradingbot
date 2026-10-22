"""Supervise an existing durably start-fenced research worker, never launch one.

Fixed controller phases bound local work; signals/HTTP completion do not prove
physical exit. Only fresh scoped stopped bytes plus durable recording yield a
result. No service, timer, credential, provider, removal or trading composition.
"""

from __future__ import annotations

import signal
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from types import FrameType
from typing import Any, NoReturn, cast

from infra.hybrid.stock_attempts import (
    AttemptSnapshot,
    AttemptStore,
    _check_clock,
    _clock,
    _integer,
    _stopped,
)
from infra.hybrid.stock_container import _object
from infra.hybrid.stock_engine import StockEngineReader
from infra.hybrid.stock_engine_mutation import _ERRORS, _production_store
from infra.hybrid.stock_engine_termination import StockEngineTerminator, _owned_running

_NS = 1_000_000_000
_ShutdownScope = tuple[int, list[bool], Callable[[int, FrameType | None], None]]
_ACTIVE_SHUTDOWN: _ShutdownScope | None = None


def _deny() -> NoReturn:
    raise ValueError("stock_supervisor_unavailable") from None


def _require(condition: bool) -> None:
    if not condition:
        _deny()


class _Clock:
    def __init__(self) -> None:
        value = _clock()
        _check_clock(value)
        self.boot_id = cast(str, value["boot_id"])
        self.last = cast(int, value["monotonic_ns"])

    def now(self) -> int:
        value = _clock()
        _check_clock(value)
        _require(value["boot_id"] == self.boot_id and value["monotonic_ns"] >= self.last)
        self.last = cast(int, value["monotonic_ns"])
        return self.last


def _check_shutdown(scope: _ShutdownScope) -> None:
    owner, requested, handler = scope
    _require(
        _ACTIVE_SHUTDOWN is scope
        and threading.get_ident() == owner
        and type(requested) is list
        and len(requested) == 1
        and type(requested[0]) is bool
        and all(signal.getsignal(number) is handler for number in (signal.SIGTERM, signal.SIGINT))
    )


@contextmanager
def _shutdown() -> Iterator[list[bool]]:
    """Nested owned operations share sticky state; only the outer scope owns handlers."""
    global _ACTIVE_SHUTDOWN
    _require(threading.current_thread() is threading.main_thread())
    if _ACTIVE_SHUTDOWN is not None:
        nested = _ACTIVE_SHUTDOWN
        _check_shutdown(nested)
        try:
            yield nested[1]
        finally:
            _check_shutdown(nested)
        return
    requested = [False]
    previous: list[tuple[int, Any]] = []
    scope: _ShutdownScope | None = None

    def handler(_number: int, _frame: FrameType | None) -> None:
        requested[0] = True

    try:
        for number in (signal.SIGTERM, signal.SIGINT):
            old = signal.getsignal(number)
            signal.signal(number, handler)
            previous.append((number, old))
        scope = (threading.get_ident(), requested, handler)
        _ACTIVE_SHUTDOWN = scope
        yield requested
    finally:
        failed = False
        if scope is not None:
            try:
                _check_shutdown(scope)
            except _ERRORS:
                failed = True
        try:
            for restored_number, old in reversed(previous):
                try:
                    signal.signal(restored_number, old)
                except _ERRORS:
                    failed = True
        finally:
            _ACTIVE_SHUTDOWN = None
        _require(not failed)


@dataclass(frozen=True, slots=True, repr=False)
class StockSupervisionResult:
    attempt_id: str
    container_id: str
    reason: str
    start_boot_id: str
    start_monotonic_ns: int
    term_deadline_ns: int
    term_attempted: bool
    kill_attempted: bool
    exit_code: int
    oom_killed: bool
    error_present: bool


def _observe(
    store: AttemptStore, target: AttemptSnapshot, reader: StockEngineReader, cap: int
) -> tuple[bytes, bool]:
    if target.container_id is None:
        _deny()
    _require(store.snapshot() == target)
    raw = reader.inspect(target.container_id, not_after_ns=cap)
    _require(store.snapshot() == target)
    value = _object(raw)
    if value["State"]["Status"] == "running":
        _owned_running(raw, target)
        return raw, False
    facts = _stopped(raw, target.attempt, target.container_id)
    # A queued START can still act on created state. It is never terminal proof.
    _require(facts["status"] != "created")
    return raw, True


def _monitor(
    store: AttemptStore,
    target: AttemptSnapshot,
    reader: StockEngineReader,
    clock: _Clock,
    cap: int,
    shutdown: list[bool],
    *,
    run_phase: bool,
) -> tuple[bytes | None, str]:
    while True:
        now = clock.now()
        if now >= cap:
            return None, "deadline"
        if run_phase and shutdown[0]:
            return None, "shutdown"
        try:
            raw, stopped = _observe(store, target, reader, cap)
        except _ERRORS:
            raw, stopped = b"", False
            now = clock.now()
            if run_phase:
                return None, "deadline" if now >= cap else "observation_failed"
        now = clock.now()
        if now <= cap and stopped:
            return raw, "natural_exit"
        if now >= cap:
            return None, "deadline"
        if run_phase and shutdown[0]:
            return None, "shutdown"
        time.sleep(min(1.0, (cap - now) / _NS))


def _finish(
    store: AttemptStore,
    target: AttemptSnapshot,
    raw: bytes,
    reason: str,
    term_attempted: bool,
    kill_attempted: bool,
) -> StockSupervisionResult:
    # Deliberately outside the observation-error catch: persistence failure ends work.
    recorded = store.record_stopped(raw)
    fence = target.start_fence
    if fence is None or target.container_id is None:
        _deny()
    return StockSupervisionResult(
        target.attempt.attempt_id,
        target.container_id,
        reason,
        fence.boot_id,
        fence.start_monotonic_ns,
        fence.term_deadline_ns,
        term_attempted,
        kill_attempted,
        recorded["exit_code"],
        recorded["oom_killed"],
        recorded["error_present"],
    )


@contextmanager
def _shutdown_state(existing: list[bool] | None) -> Iterator[list[bool]]:
    if existing is None:
        with _shutdown() as requested:
            yield requested
    else:
        _require(type(existing) is list and len(existing) == 1 and type(existing[0]) is bool)
        yield existing


def supervise_active(
    store: AttemptStore, *, shutdown: list[bool] | None = None
) -> StockSupervisionResult:
    """Keep the owning lock open; recover/supervise only, with no create/start API."""
    try:
        _production_store(store)
        target = store.cleanup_target()
        fence = target.start_fence
        if fence is None:
            _deny()
        clock = _Clock()
        reader, terminator = StockEngineReader(), StockEngineTerminator()
        now = clock.now()
        same_domain = fence.boot_id == clock.boot_id and now >= fence.start_monotonic_ns
        current_owner = store._owned_attempt == target.attempt.attempt_id
        initial_recovery = not (same_domain and current_owner and now < fence.term_deadline_ns)
        with _shutdown_state(shutdown) as requested:
            if not initial_recovery:
                raw, reason = _monitor(
                    store, target, reader, clock, fence.term_deadline_ns, requested, run_phase=True
                )
                if raw is not None:
                    return _finish(store, target, raw, "natural_exit", False, False)
                now = clock.now()
                origin = (
                    fence.term_deadline_ns
                    if reason == "deadline"
                    else min(now, fence.term_deadline_ns)
                )
            else:
                reason = "recovery"
                origin = min(now, fence.term_deadline_ns) if same_domain else now
            grace_end = origin + 10 * _NS
            # Only an attempt already overdue at entry receives a fresh cleanup budget.
            # A late active RUN keeps its original C/Q, even when they have expired.
            kill_end = (now if initial_recovery and now >= grace_end else grace_end) + 5 * _NS
            verify_end = kill_end + 5 * _NS
            _require(_integer(verify_end, 1))
            term_attempted = kill_attempted = False
            if clock.now() < grace_end:
                term_attempted = True
                with suppress(*_ERRORS):
                    terminator.signal_active(store, "TERM", not_after_ns=grace_end)
                raw, _ = _monitor(
                    store, target, reader, clock, grace_end, requested, run_phase=False
                )
                if raw is not None:
                    return _finish(store, target, raw, reason, term_attempted, False)
            if clock.now() < kill_end:
                kill_attempted = True
                with suppress(*_ERRORS):
                    terminator.signal_active(store, "KILL", not_after_ns=kill_end)
            raw, _ = _monitor(store, target, reader, clock, verify_end, requested, run_phase=False)
            if raw is not None:
                return _finish(store, target, raw, reason, term_attempted, kill_attempted)
            _deny()
    except _ERRORS:
        _deny()
