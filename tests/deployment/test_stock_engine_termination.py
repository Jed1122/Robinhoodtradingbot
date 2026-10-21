"""Fictional operations stores and local socketpairs; never use a Docker daemon."""

import hashlib
import importlib
import json
import os
import socket
import threading
import time
from contextlib import suppress
from pathlib import Path

import pytest

from infra.hybrid import stock_attempts
from infra.hybrid.stock_prestart import CreatedContainer
from infra.hybrid.stock_release import RELEASE_ROOT, StockRelease, _policy

IMAGE = "sha256:" + "b" * 64
RELEASE = "d" * 64
CID = "f" * 64
BOOT = "11111111-2222-4333-8444-555555555555"


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def module():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_engine_termination.py"
    assert path.is_file(), "Scoped stock worker termination is not implemented"
    return importlib.import_module("infra.hybrid.stock_engine_termination")


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    root = tmp_path.resolve() / "operations"
    stock_attempts._initialize(root, trusted_uid=os.geteuid())
    clock = {
        "boot_id": BOOT,
        "utc": "2026-10-21T21:00:00+00:00",
        "monotonic_ns": time.monotonic_ns(),
    }
    monkeypatch.setattr(stock_attempts, "_clock", lambda: clock.copy())
    attestation = RELEASE_ROOT / RELEASE / "runtime-image-attestation.json"
    body = encoded(_policy(IMAGE, attestation))
    release = StockRelease(
        RELEASE,
        IMAGE,
        "c" * 64,
        hashlib.sha256(body).hexdigest(),
        450,
        3600,
        attestation,
        attestation.parent / "stock-compose.resolved.json",
        body,
    )
    return root, clock, release


def opened(scenario):
    return stock_attempts._open_operations(scenario[0], trusted_uid=os.geteuid())


def started(store, scenario):
    intent = store.begin(scenario[2])
    store.record_created(
        CreatedContainer(CID, intent.attempt_id, RELEASE, IMAGE, "c" * 64, intent.compose_sha256)
    )
    return intent, store.prepare_start()


def running(intent):
    return {
        "Id": CID,
        "Image": IMAGE,
        "Name": "/hybrid-stock-research-" + intent.attempt_id,
        "Platform": "linux",
        "RestartCount": 0,
        "Config": {
            "Labels": {
                "org.hybrid.stock.managed": "stock-research",
                "org.hybrid.stock.release": RELEASE,
                "org.hybrid.stock.attempt": intent.attempt_id,
            }
        },
        "HostConfig": {
            "AutoRemove": False,
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
        },
        "State": {
            "Status": "running",
            "Running": True,
            "Paused": False,
            "Restarting": False,
            "OOMKilled": False,
            "Dead": False,
            "Pid": 42,
            "ExitCode": 0,
            "Error": "",
            "StartedAt": "2026-10-21T21:00:01Z",
            "FinishedAt": "0001-01-01T00:00:00Z",
        },
    }


def response(status, body=b""):
    return (
        b"HTTP/1.0 "
        + str(status).encode()
        + b" Fictional\r\nContent-Length: "
        + str(len(body)).encode()
        + b"\r\n\r\n"
        + body
    )


def exchange(monkeypatch, store, replies, *, signal="TERM", on_connect=None, direct=False):
    api = module()
    # Only this fixture substitutes the fixed production-root requirement.
    monkeypatch.setattr(api, "_production_store", lambda candidate: None)
    peers = [socket.socketpair() for _ in replies]
    requests = []
    connections = []

    def serve(server, reply, index):
        with server:
            request = b""
            while b"\r\n\r\n" not in request:
                chunk = server.recv(4096)
                if not chunk:
                    return
                request += chunk
            requests.append((index, request))
            with suppress(OSError):
                server.sendall(reply)

    threads = [
        threading.Thread(target=serve, args=(server, reply, index))
        for index, ((_, server), reply) in enumerate(zip(peers, replies, strict=True))
    ]
    for thread in threads:
        thread.start()

    def connection(deadline):
        index = len(connections)
        connections.append(deadline)
        if on_connect is not None:
            on_connect(index)
        assert index < len(peers), "Termination retried or opened an unexpected socket"
        return peers[index][0]

    monkeypatch.setattr(api, "_connection", connection)
    try:
        transport = api.StockEngineTerminator()
        if direct:
            result = transport._exchange(signal, store)
        else:
            result = transport.signal_active(store, signal)
        return result, sorted(requests), connections
    finally:
        for client, _ in peers:
            client.close()
        for thread in threads:
            thread.join(timeout=2)
            assert not thread.is_alive()


@pytest.mark.parametrize("signal", ["TERM", "KILL"])
@pytest.mark.parametrize("direct", [False, True])
def test_signal_inspects_full_owned_cid_and_acknowledges_dispatch_only(
    scenario, monkeypatch, signal, direct
):
    with opened(scenario) as store:
        intent, fence = started(store, scenario)
        result, requests, deadlines = exchange(
            monkeypatch,
            store,
            [response(200, encoded(running(intent))), response(204)],
            signal=signal,
            direct=direct,
        )
        assert result is None and len(requests) == 2 and deadlines[0] == deadlines[1]
        assert (
            requests[0][1]
            == (
                "GET /v1.52/containers/"
                + CID
                + "/json HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n"
            ).encode()
        )
        assert (
            requests[1][1]
            == (
                "POST /v1.52/containers/"
                + CID
                + "/kill?signal="
                + signal
                + " HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
            ).encode()
        )
        assert not (scenario[0] / intent.attempt_id / "stopped.json").exists()
        assert store.snapshot().start_fence == fence
        for operation in [
            store.prepare_start,
            lambda: store.begin(scenario[2]),
            lambda: store.check_start_fence(fence),
        ]:
            with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
                operation()


@pytest.mark.parametrize("mode", ["reopened", "old_boot", "overdue"])
def test_recovery_keeps_original_fence_and_permits_cleanup_only(scenario, monkeypatch, mode):
    with opened(scenario) as store:
        intent, fence = started(store, scenario)
    if mode == "old_boot":
        scenario[1]["boot_id"] = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        scenario[1]["monotonic_ns"] = 1
    elif mode == "overdue":
        scenario[1]["monotonic_ns"] = fence.term_deadline_ns + 1
    before = (scenario[0] / intent.attempt_id / "start.json").read_bytes()
    with opened(scenario) as store:
        exchange(monkeypatch, store, [response(200, encoded(running(intent))), response(204)])
        assert store.snapshot().start_fence == fence
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.prepare_start()
    assert (scenario[0] / intent.attempt_id / "start.json").read_bytes() == before


@pytest.mark.parametrize(
    "path,value",
    [
        (("Id",), "e" * 64),
        (("Image",), "sha256:" + "e" * 64),
        (("Name",), "/foreign"),
        (("Platform",), "windows"),
        (("RestartCount",), 1),
        (("RestartCount",), False),
        (("Config", "Labels", "org.hybrid.stock.managed"), "foreign"),
        (("Config", "Labels", "org.hybrid.stock.attempt"), "0" * 32),
        (("Config", "Labels", "org.hybrid.stock.release"), "0" * 64),
        (("Config", "Labels", "extra"), "unreviewed"),
        (("HostConfig", "AutoRemove"), True),
        (("HostConfig", "AutoRemove"), 0),
        (("HostConfig", "RestartPolicy", "Name"), "always"),
        (("HostConfig", "RestartPolicy", "MaximumRetryCount"), False),
        (("State", "Status"), "exited"),
        (("State", "Running"), False),
        (("State", "Running"), 1),
        (("State", "Paused"), True),
        (("State", "Restarting"), True),
        (("State", "Dead"), True),
        (("State", "OOMKilled"), True),
        (("State", "Pid"), 0),
        (("State", "Pid"), True),
        (("State", "ExitCode"), 1),
        (("State", "ExitCode"), False),
        (("State", "Error"), "private diagnostic"),
        (("State", "StartedAt"), "0001-01-01T00:00:00Z"),
        (("State", "StartedAt"), "2026-10-21T21:00:01"),
        (("State", "FinishedAt"), "2026-10-21T21:00:02Z"),
        (("State", "Unknown"), False),
        (("State",), []),
    ],
)
def test_foreign_or_unsafe_inspection_never_sends_signal(scenario, monkeypatch, path, value):
    with opened(scenario) as store:
        intent, _ = started(store, scenario)
        observation = running(intent)
        parent = observation
        for key in path[:-1]:
            parent = parent[key]
        parent[path[-1]] = value
        with pytest.raises(ValueError, match=r"^stock_engine_termination_unavailable$"):
            exchange(monkeypatch, store, [response(200, encoded(observation))])
        assert not (scenario[0] / intent.attempt_id / "stopped.json").exists()


@pytest.mark.parametrize(
    "signal", ["", "SIGTERM", "15", "9", "term", "STOP", "KILL&all=true", None, 9, True]
)
def test_invalid_signal_rejected_before_connection(scenario, monkeypatch, signal):
    with opened(scenario) as store:
        started(store, scenario)
        with pytest.raises(ValueError, match=r"^stock_engine_termination_unavailable$"):
            exchange(monkeypatch, store, [], signal=signal, direct=True)


@pytest.mark.parametrize(
    "reply",
    [
        response(404, b'{"message":"private no-such-container"}'),
        response(409),
        response(500),
        b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\nContent-Length: 2\r\n\r\n{}",
        b"HTTP/1.0 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
        response(200, b"{}"),
        response(200, b'{"Id":1,"Id":2}'),
        b"HTTP/1.0 200 OK\r\nContent-Length: 2000\r\n\r\n{}",
        b"HTTP/1.0 200 OK\r\nContent-Length: 1048577\r\n\r\n{}",
    ],
)
def test_inspection_error_or_framing_never_becomes_absence_or_signal(scenario, monkeypatch, reply):
    with opened(scenario) as store:
        intent, _ = started(store, scenario)
        with pytest.raises(ValueError, match=r"^stock_engine_termination_unavailable$"):
            exchange(monkeypatch, store, [reply])
        assert not (scenario[0] / intent.attempt_id / "stopped.json").exists()


@pytest.mark.parametrize(
    "reply",
    [
        response(200),
        response(304),
        response(404),
        response(409),
        response(500),
        response(204, b"x"),
        response(204) + b"x",
        b"HTTP/1.0 204 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
        b"HTTP/1.0 204 OK\r\nContent-Length: 0\r\nContent-Length: 0\r\n\r\n",
        b"HTTP/1.0 204 OK\r\nBad Header: yes\r\n\r\n",
        b"",
    ],
)
def test_signal_uncertainty_never_retries_or_records_stopped(scenario, monkeypatch, reply):
    with opened(scenario) as store:
        intent, _ = started(store, scenario)
        with pytest.raises(ValueError, match=r"^stock_engine_termination_unavailable$"):
            exchange(monkeypatch, store, [response(200, encoded(running(intent))), reply])
        assert not (scenario[0] / intent.attempt_id / "stopped.json").exists()
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.begin(scenario[2])


@pytest.mark.parametrize("change", ["closed", "start_bytes", "anchor_mode"])
def test_store_drift_after_signal_connection_prevents_send(scenario, monkeypatch, change):
    with opened(scenario) as store:
        intent, _ = started(store, scenario)

        def drift(index):
            if index != 1:
                return
            if change == "closed":
                store._closed = True
            elif change == "anchor_mode":
                (scenario[0] / "launcher.lock").chmod(0o640)
            else:
                path = scenario[0] / intent.attempt_id / "start.json"
                receipt = json.loads(path.read_bytes())
                receipt["utc"] = "2026-10-21T21:00:01+00:00"
                path.write_bytes(encoded(receipt))

        with pytest.raises(ValueError, match=r"^stock_engine_termination_unavailable$"):
            exchange(
                monkeypatch,
                store,
                [response(200, encoded(running(intent))), response(204)],
                on_connect=drift,
            )


@pytest.mark.parametrize("slow_connection", [0, 1])
def test_absolute_budget_includes_both_connections(scenario, monkeypatch, slow_connection):
    api = module()
    original = api.time.monotonic
    with opened(scenario) as store:
        intent, _ = started(store, scenario)

        def delay(index):
            if index == slow_connection:
                monkeypatch.setattr(api.time, "monotonic", lambda: original() + 6)

        with pytest.raises(ValueError, match=r"^stock_engine_termination_unavailable$"):
            exchange(
                monkeypatch,
                store,
                [response(200, encoded(running(intent))), response(204)],
                on_connect=delay,
            )


def test_production_guard_rejects_fictional_root_without_opening_socket(scenario, monkeypatch):
    api = module()

    def forbidden(deadline):
        pytest.fail("Untrusted store reached the Docker socket")

    monkeypatch.setattr(api, "_connection", forbidden)
    with opened(scenario) as store:
        started(store, scenario)
        with pytest.raises(ValueError, match=r"^stock_engine_termination_unavailable$"):
            api.StockEngineTerminator().signal_active(store, "TERM")
