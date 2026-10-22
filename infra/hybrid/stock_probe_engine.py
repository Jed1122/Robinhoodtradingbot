"""Fixed inert-probe transport; no worker, credential or broker operations.

Public operations derive routes and bodies from a locked fixed-root ProbeStore.
Socket, peer identity and per-exchange time checks are shared read-only primitives;
existing worker transports, defaults and permitted routes are unchanged.
"""

from __future__ import annotations

import os
import re
import socket
import sys
from collections.abc import Callable
from typing import NoReturn, cast

from infra.hybrid.stock_container import API_VERSION, _object
from infra.hybrid.stock_engine import (
    _HEAD_LIMIT,
    _HEADER,
    _LENGTH,
    _connection,
    _deadline,
    _receive,
    _remaining,
)
from infra.hybrid.stock_engine_mutation import _ERRORS, _not_shutdown
from infra.hybrid.stock_probe_observation import observe_probe
from infra.hybrid.stock_probe_profile import CreatedProbe
from infra.hybrid.stock_probe_store import (
    PROBES_ROOT,
    ProbeCleanup,
    ProbeSetup,
    ProbeSnapshot,
    ProbeStartFence,
    ProbeStore,
)


def _deny() -> NoReturn:
    raise ValueError("stock_probe_engine_unavailable") from None


def _require(condition: bool) -> None:
    if not condition:
        _deny()


def _production_store(store: ProbeStore) -> None:
    _require(type(store) is ProbeStore and sys.platform == "linux" and os.geteuid() == 0)
    _require(store._root == PROBES_ROOT and store._uid == 0)
    store._guard()


def _reply(
    peer: socket.socket,
    deadline: float,
    expected: frozenset[int],
    *,
    maximum: int,
    allow_empty: bool = False,
    multiplexed: bool = False,
) -> tuple[int, bytes]:
    """Private fixed-operation decoder, including final EOF within the same cap."""
    _require(type(maximum) is int and 0 < maximum <= 1048576)
    buffered = b""
    while b"\r\n\r\n" not in buffered:
        _require(len(buffered) < _HEAD_LIMIT)
        chunk = _receive(peer, deadline, min(4096, _HEAD_LIMIT - len(buffered)))
        _require(bool(chunk))
        buffered += chunk
    head, initial = buffered.split(b"\r\n\r\n", 1)
    lines = head.split(b"\r\n")
    match = re.fullmatch(rb"HTTP/1\.[01] ([0-9]{3})(?: [\x20-\x7e]*)?", lines[0])
    if match is None:
        _deny()
    code = int(match[1])
    _require(code in expected)
    headers: dict[str, str] = {}
    for line in lines[1:]:
        name, separator, value = line.partition(b":")
        _require(separator == b":" and _HEADER.fullmatch(name) is not None)
        _require(all(character == 9 or 32 <= character <= 126 for character in value))
        key = name.decode("ascii").lower()
        _require(key not in headers)
        headers[key] = value.decode("ascii").strip(" \t")
    _require("transfer-encoding" not in headers)
    if multiplexed:
        _require(headers.get("content-type") == "application/vnd.docker.multiplexed-stream")
    if code == 204:
        _require(headers.get("content-length", "0") == "0" and not initial)
        body = b""
    elif "content-length" in headers:
        length = headers["content-length"]
        _require(_LENGTH.fullmatch(length) is not None)
        size = int(length)
        _require((allow_empty or size > 0) and size <= maximum and len(initial) <= size)
        body = initial
        while len(body) < size:
            chunk = _receive(peer, deadline, min(65536, size - len(body)))
            _require(bool(chunk))
            body += chunk
    else:
        body = initial
        while True:
            _require(len(body) <= maximum)
            chunk = _receive(peer, deadline, min(65536, maximum + 1 - len(body)))
            if not chunk:
                break
            body += chunk
        _require(allow_empty or bool(body))
    # A successful status or a complete Content-Length does not replace closed EOF.
    _require(not _receive(peer, deadline, 1))
    _remaining(deadline)
    return code, body


def _request(method: str, path: str, body: bytes | None = None) -> bytes:
    head = method + " " + path + " HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n"
    if body is not None:
        head += "Content-Type: application/json\r\nContent-Length: " + str(len(body)) + "\r\n"
    return (head + "\r\n").encode("ascii") + (b"" if body is None else body)


def _exchange(
    request: bytes,
    check: Callable[[], None],
    deadline_ns: int,
    expected: frozenset[int],
    *,
    maximum: int = 1048576,
    allow_empty: bool = False,
    multiplexed: bool = False,
    shutdown: list[bool] | None = None,
) -> tuple[int, bytes]:
    deadline = _deadline(deadline_ns)
    check()
    _not_shutdown(shutdown)
    with _connection(deadline) as peer:
        check()
        _not_shutdown(shutdown)
        peer.settimeout(_remaining(deadline))
        peer.sendall(request)
        result = _reply(
            peer,
            deadline,
            expected,
            maximum=maximum,
            allow_empty=allow_empty,
            multiplexed=multiplexed,
        )
        _remaining(deadline)
    return result


def _missing(raw: bytes, cid: str) -> None:
    value = _object(raw)
    _require(set(value) == {"message"} and value["message"] == "No such container: " + cid)


class StockProbeEngine:
    """One controller session. Public methods expose no native dispatch overrides."""

    def __init__(self) -> None:
        self._admission_issued = False
        self._prestart_issued = False
        self._discovery_issued = False

    def begin_probe(
        self, store: ProbeStore, image_digest: str, *, shutdown: list[bool] | None = None
    ) -> ProbeSnapshot:
        try:
            _require(not self._admission_issued)
            self._admission_issued = True
            _production_store(store)
            _not_shutdown(shutdown)
            token = store.begin_setup(image_digest)

            def check() -> None:
                store.check_setup(token)

            _, engine = _exchange(
                _request("GET", "/version"),
                check,
                token.deadline_ns,
                frozenset({200}),
                shutdown=shutdown,
            )
            _, image = _exchange(
                _request("GET", "/v" + API_VERSION + "/images/" + token.image_digest + "/json"),
                check,
                token.deadline_ns,
                frozenset({200}),
                shutdown=shutdown,
            )
            if token.predecessor_container_id is not None:
                cid = token.predecessor_container_id
                _, raw = _exchange(
                    _request("GET", "/v" + API_VERSION + "/containers/" + cid + "/json"),
                    check,
                    token.deadline_ns,
                    frozenset({404}),
                    shutdown=shutdown,
                )
                _missing(raw, cid)
                proof = store._entry_absence_evidence(token)
                store.record_entry_absence(token, proof)
            check()
            _not_shutdown(shutdown)
            return store.begin(token, engine, image)
        except _ERRORS:
            _deny()

    def create_probe(self, store: ProbeStore, *, shutdown: list[bool] | None = None) -> str:
        try:
            _production_store(store)
            _not_shutdown(shutdown)
            token = store.prepare_create()
            store.claim_create(token)
            body = store.create_request(token)
            path = (
                "/v" + API_VERSION + "/containers/create?name=hybrid-stock-probe-" + token.probe_id
            )
            _, raw = _exchange(
                _request("POST", path, body),
                lambda: store.check_create_fence(token),
                token.deadline_ns,
                frozenset({201}),
                maximum=4096,
                shutdown=shutdown,
            )
            return store.record_cid(token, raw)
        except _ERRORS:
            _deny()

    def verify_created(
        self, store: ProbeStore, *, shutdown: list[bool] | None = None
    ) -> CreatedProbe:
        try:
            _require(not self._prestart_issued)
            self._prestart_issued = True
            _production_store(store)
            _not_shutdown(shutdown)
            token = store._setup_token
            _require(type(token) is ProbeSetup)
            token = cast(ProbeSetup, token)
            snapshot = store.snapshot()
            if snapshot is None or snapshot.container_id is None:
                _deny()
            path = "/v" + API_VERSION + "/containers/" + snapshot.container_id + "/json"
            _, raw = _exchange(
                _request("GET", path),
                lambda: store.check_setup(token),
                token.deadline_ns,
                frozenset({200}),
                shutdown=shutdown,
            )
            _not_shutdown(shutdown)
            return store.record_created(raw)
        except _ERRORS:
            _deny()

    def start_probe(
        self, store: ProbeStore, *, shutdown: list[bool] | None = None
    ) -> ProbeStartFence:
        try:
            _production_store(store)
            _not_shutdown(shutdown)
            token = store.prepare_start()
            store.claim_start(token)
            path = "/v" + API_VERSION + "/containers/" + token.container_id + "/start"
            _, raw = _exchange(
                _request("POST", path, b""),
                lambda: store.check_start_fence(token),
                token.dispatch_deadline_ns,
                frozenset({204}),
                shutdown=shutdown,
            )
            _require(not raw)
            store.check_start_fence(token)
            return token
        except _ERRORS:
            _deny()

    def inspect_probe(
        self, store: ProbeStore, *, cleanup: ProbeCleanup | None = None, phase: str | None = None
    ) -> bytes:
        try:
            _production_store(store)
            node = store._phase_node(cleanup)
            target = node.snapshot
            if target.container_id is None:
                _deny()
            if cleanup is None:
                _require(phase is None)
                _require(store._start_dispatched and target.run_deadline_ns is not None)
                boot, cap = target.boot_id, cast(int, target.run_deadline_ns)
            else:
                _require(
                    phase is None or (type(phase) is str and phase in ("TERM", "KILL", "FINAL"))
                )
                cap = {
                    "TERM": cleanup.term_deadline_ns,
                    "KILL": cleanup.kill_deadline_ns,
                    "FINAL": cleanup.final_deadline_ns,
                }["FINAL" if phase is None else phase]
                boot = cleanup.boot_id

            def check() -> None:
                current = store._phase_node(cleanup)
                _require(current.snapshot == target)
                store._window(boot, cap)

            path = "/v" + API_VERSION + "/containers/" + target.container_id + "/json"
            _, raw = _exchange(_request("GET", path), check, cap, frozenset({200}))
            observe_probe(
                raw,
                probe_id=target.probe_id,
                container_id=target.container_id,
                image_digest=target.image_digest,
            )
            check()
            return raw
        except _ERRORS:
            _deny()

    def discover_probe(self, store: ProbeStore, cleanup: ProbeCleanup) -> str:
        try:
            _require(not self._discovery_issued)
            self._discovery_issued = True
            _production_store(store)
            node = store._cleanup_node(cleanup)
            _require(node.snapshot.container_id is None and "create.json" in node.records)
            path = (
                "/v" + API_VERSION + "/containers/hybrid-stock-probe-" + cleanup.probe_id + "/json"
            )
            _, raw = _exchange(
                _request("GET", path),
                lambda: store.check_cleanup(cleanup),
                cleanup.final_deadline_ns,
                frozenset({200}),
            )
            return store.record_discovered_cid(cleanup, raw)
        except _ERRORS:
            _deny()

    def signal_probe(self, store: ProbeStore, cleanup: ProbeCleanup, signal: str) -> None:
        try:
            _production_store(store)
            token = store.prepare_signal(cleanup, signal)
            # Both GET and POST share this one five-second exchange budget.
            wire_cap = int(_deadline(token.deadline_ns) * 1000000000)
            prefix = "/v" + API_VERSION + "/containers/" + token.container_id

            def check() -> None:
                store.check_signal_fence(token)

            _, raw = _exchange(
                _request("GET", prefix + "/json"),
                check,
                wire_cap,
                frozenset({200}),
            )
            store.claim_signal(token, raw)
            _, body = _exchange(
                _request("POST", prefix + "/kill?signal=" + token.signal, b""),
                check,
                wire_cap,
                frozenset({204}),
            )
            _require(not body)
            store.check_signal_fence(token)
        except _ERRORS:
            _deny()

    def collect_output(self, store: ProbeStore, *, cleanup: ProbeCleanup | None = None) -> str:
        try:
            _production_store(store)
            token = store.prepare_output(cleanup=cleanup)
            store.claim_output(token)
            path = (
                "/v"
                + API_VERSION
                + "/containers/"
                + token.container_id
                + "/logs?stdout=true&stderr=true&follow=false&timestamps=false"
                "&tail=all&details=false"
            )
            _, raw = _exchange(
                _request("GET", path),
                lambda: store.check_output_fence(token),
                token.deadline_ns,
                frozenset({200}),
                maximum=16384,
                allow_empty=True,
                multiplexed=True,
            )
            return store.record_output(token, raw)
        except _ERRORS:
            _deny()

    def retire_probe(self, store: ProbeStore, *, cleanup: ProbeCleanup | None = None) -> None:
        try:
            _production_store(store)
            token = store.prepare_removal(cleanup=cleanup)
            store.claim_retirement(token)

            def check() -> None:
                store.check_removal_fence(token)

            prefix = "/v" + API_VERSION + "/containers/" + token.container_id
            status, raw = _exchange(
                _request("GET", prefix + "/json"),
                check,
                token.deadline_ns,
                frozenset({200, 404}),
            )
            if status == 404:
                _missing(raw, token.container_id)
                kind = "inspect_404"
            else:
                store.claim_removal(token, raw)
                _, body = _exchange(
                    _request("DELETE", prefix + "?force=false&v=false&link=false", b""),
                    check,
                    token.deadline_ns,
                    frozenset({204}),
                )
                _require(not body)
                kind = "delete_204"
            proof = store._retirement_evidence(token, kind)
            store.record_removed(token, proof)
        except _ERRORS:
            _deny()
