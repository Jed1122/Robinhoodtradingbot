"""One fixed inert probe or one cleanup-only recovery, never both.

No installation, image build/pull, credential, account, order or live activation.
Only successful acknowledged completion can publish configuration; recorded bytes
alone and all recovered lifecycles remain non-authoritative data.
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from typing import NoReturn

from infra.hybrid import stock_probe_engine
from infra.hybrid.stock_engine_mutation import _ERRORS
from infra.hybrid.stock_probe_observation import observe_probe
from infra.hybrid.stock_probe_store import ProbeCleanup, ProbeSnapshot, ProbeStore, probes
from infra.hybrid.stock_supervisor import _shutdown

_NS = 1000000000


def _deny() -> NoReturn:
    raise ValueError("stock_probe_controller_unavailable") from None


def _require(condition: bool) -> None:
    if not condition:
        _deny()


@dataclass(frozen=True, slots=True, repr=False)
class ProbeResult:
    status: str
    reason: str
    probe_id: str
    container_id: str | None
    image_digest: str
    configuration: bytes | None = None


class _CleanupRequested(Exception):
    def __init__(self, reason: str):
        self.reason = reason


def _clock_at(store: ProbeStore, boot: str) -> int:
    now = store._now()
    _require(now["boot_id"] == boot)
    return int(now["monotonic_ns"])


class _Observer:
    """One observation schedule across RUN, signals, cleanup and retirement."""

    def __init__(self) -> None:
        self.next_ns: int | None = None

    def mark(self, store: ProbeStore) -> None:
        self.next_ns = int(store._now()["monotonic_ns"]) + _NS

    def wait(self, store: ProbeStore, boot: str, cap: int) -> bool:
        while True:
            now = _clock_at(store, boot)
            if now >= cap:
                return False
            if self.next_ns is None or now >= self.next_ns:
                return True
            time.sleep(min(self.next_ns - now, cap - now) / _NS)


def _stopped(raw: bytes, target: ProbeSnapshot) -> bool:
    if target.container_id is None:
        _deny()
    value = observe_probe(
        raw,
        probe_id=target.probe_id,
        container_id=target.container_id,
        image_digest=target.image_digest,
    )
    return value.status in ("exited", "dead") or (
        value.status == "created" and target.run_deadline_ns is None
    )


def _monitor(
    store: ProbeStore,
    engine: stock_probe_engine.StockProbeEngine,
    observer: _Observer,
    requested: list[bool],
    boot: str,
    cap: int,
    *,
    cleanup: ProbeCleanup | None = None,
    phase: str | None = None,
) -> tuple[bytes | None, str]:
    while True:
        if cleanup is None and requested[0]:
            return None, "shutdown"
        if not observer.wait(store, boot, cap):
            return None, "run_expired"
        if cleanup is None and requested[0]:
            return None, "shutdown"
        try:
            raw = engine.inspect_probe(store, cleanup=cleanup, phase=phase)
        except _ERRORS:
            observer.mark(store)
            if cleanup is None:
                return None, "shutdown" if requested[0] else "recovery"
            continue
        observer.mark(store)
        if cleanup is None and requested[0]:
            return None, "shutdown"
        if _clock_at(store, boot) >= cap:
            return None, "run_expired"
        target = store.snapshot()
        if target is None:
            _deny()
        if _stopped(raw, target):
            return raw, "process_failed"


def _result(
    status: str, reason: str, target: ProbeSnapshot, raw: bytes | None = None
) -> ProbeResult:
    return ProbeResult(
        status, reason, target.probe_id, target.container_id, target.image_digest, raw
    )


def _recover(
    store: ProbeStore,
    engine: stock_probe_engine.StockProbeEngine,
    observer: _Observer,
    requested: list[bool],
    reason: str,
    *,
    entry_recovery: bool,
) -> ProbeResult:
    token = store.begin_cleanup()
    if token is None:
        _deny()
    target = store.cleanup_target(token)
    status = "recovery_only" if entry_recovery else "failed"
    if "create.json" not in dict(target.receipt_hashes):
        store.abandon(token)
        return _result(status, "abandoned_before_create", target)
    if target.container_id is None:
        _require(observer.wait(store, token.boot_id, token.final_deadline_ns))
        engine.discover_probe(store, token)
        observer.mark(store)
        target = store.cleanup_target(token)
    if target.stopped is None:
        # A first actual read can prove already stopped without attempting a signal.
        raw = None
        if observer.wait(store, token.boot_id, token.final_deadline_ns):
            try:
                observed = engine.inspect_probe(store, cleanup=token)
            except _ERRORS:
                observer.mark(store)
            else:
                observer.mark(store)
                if _stopped(observed, target):
                    raw = observed
        if raw is None and token.start_sha256 is not None:
            for signal_name, cap in (
                ("TERM", token.term_deadline_ns),
                ("KILL", token.kill_deadline_ns),
            ):
                if not observer.wait(store, token.boot_id, cap):
                    continue
                # One signal attempt only. Later reads establish state, not ACK.
                with suppress(*_ERRORS):
                    engine.signal_probe(store, token, signal_name)
                observer.mark(store)
                raw, _ = _monitor(
                    store,
                    engine,
                    observer,
                    requested,
                    token.boot_id,
                    cap,
                    cleanup=token,
                    phase=signal_name,
                )
                if raw is not None:
                    break
        if raw is None:
            raw, _ = _monitor(
                store,
                engine,
                observer,
                requested,
                token.boot_id,
                token.final_deadline_ns,
                cleanup=token,
                phase="FINAL",
            )
        if raw is None:
            _deny()
        store.record_stopped(raw, cleanup=token)
    _require(observer.wait(store, token.boot_id, token.final_deadline_ns))
    # From here onward a failure ends this invocation. Never retire twice.
    engine.retire_probe(store, cleanup=token)
    store.close_failed("shutdown" if requested[0] else reason)
    return _result(status, "shutdown" if requested[0] else reason, target)


def _compose(store: ProbeStore, image_digest: str, requested: list[bool]) -> ProbeResult:
    stock_probe_engine._production_store(store)
    _require(type(requested) is list and len(requested) == 1 and type(requested[0]) is bool)
    engine = stock_probe_engine.StockProbeEngine()
    observer = _Observer()
    if store.recovery_only:
        return _recover(store, engine, observer, requested, "recovery", entry_recovery=True)
    stage = "setup_failed"
    try:
        if requested[0]:
            raise _CleanupRequested("shutdown")
        engine.begin_probe(store, image_digest, shutdown=requested)
        if requested[0]:
            raise _CleanupRequested("shutdown")
        engine.create_probe(store, shutdown=requested)
        if requested[0]:
            raise _CleanupRequested("shutdown")
        stage = "prestart_failed"
        engine.verify_created(store, shutdown=requested)
        if requested[0]:
            raise _CleanupRequested("shutdown")
        stage = "start_uncertain"
        try:
            engine.start_probe(store, shutdown=requested)
        except _ERRORS:
            node = store._owned_node()
            _require(store._start_dispatched and "start.json" in node.records)
            # A missing reply never causes another START; only observed original RUN.
        if requested[0]:
            raise _CleanupRequested("shutdown")
        target = store._owned_node().snapshot
        if target.run_deadline_ns is None:
            _deny()
        stage = "process_failed"
        raw, reason = _monitor(
            store, engine, observer, requested, target.boot_id, target.run_deadline_ns
        )
        if raw is None:
            raise _CleanupRequested(reason)
        store.record_stopped(raw)
        if requested[0]:
            raise _CleanupRequested("shutdown")
        stage = "invalid_output"
        output = engine.collect_output(store)
        # Normal retirement enters before the original output cap, with no renewal.
        stop = store._owned_node().records["stopped.json"]
        _require(observer.wait(store, target.boot_id, stop["monotonic_ns"] + 5 * _NS))
    except _CleanupRequested as cleanup:
        return _recover(store, engine, observer, requested, cleanup.reason, entry_recovery=False)
    except _ERRORS:
        return _recover(
            store,
            engine,
            observer,
            requested,
            "shutdown" if requested[0] else stage,
            entry_recovery=False,
        )
    # No generic cleanup fallback covers either retirement or terminal finalization.
    engine.retire_probe(store)
    if requested[0]:
        store.close_failed("shutdown")
        return _result("failed", "shutdown", target)
    if store._natural_stopped_ack is None or output != "valid":
        reason = "process_failed" if store._natural_stopped_ack is None else "invalid_output"
        store.close_failed(reason)
        return _result("failed", reason, target)
    canonical = store.close_success()
    if requested[0]:
        _deny()
    return _result("succeeded", "completed", target, canonical)


@contextmanager
def _completed_probe(image_digest: str) -> Iterator[ProbeResult]:
    """Keep the original session's clock gate through preparation of public output."""
    try:
        _require(
            type(image_digest) is str
            and re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest) is not None
        )
        with _shutdown() as requested, probes() as store:
            result = _compose(store, image_digest, requested)
            fence = store._removal_token
        yield result
        if result.configuration is not None:
            if fence is None:
                _deny()
            _require(
                store._closed
                and fence is store._removal_token
                and fence.cleanup is None
            )
            # No descriptors/history are used after closure, and no cap is renewed.
            store._window(fence.boot_id, fence.deadline_ns)
            _require(not requested[0])
    except _ERRORS:
        _deny()


def run_probe(image_digest: str) -> ProbeResult:
    """Fixed public entry: no store, socket, account, path, deadline or mode override."""
    with _completed_probe(image_digest) as result:
        return result


def main() -> int:
    try:
        _require(len(sys.argv) == 2)
        with _completed_probe(sys.argv[1]) as result:
            value = {
                "schema_version": 1,
                "kind": "stock_probe_result",
                "status": result.status,
                "reason": result.reason,
                "probe_id": result.probe_id,
                "container_id": result.container_id,
                "image_digest": result.image_digest,
            }
            if result.configuration is not None:
                value["configuration"] = json.loads(result.configuration)
            raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
            _require(len(raw.encode("utf-8")) <= 8192)
        print(raw)
        return 0 if result.status == "succeeded" else 2
    except _ERRORS:
        print('{"status":"unavailable"}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
