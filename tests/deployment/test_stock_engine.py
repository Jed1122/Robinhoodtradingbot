"""Fixed-socket metadata reads against fictional responses, never Docker."""

import importlib
import socket
import stat
import struct
import threading
import time
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import pytest

CID = "f" * 64
IMAGE = "sha256:" + "b" * 64
ATTEMPT = "e" * 32


def module():
    source = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_engine.py"
    assert source.is_file(), "Fixed-socket Engine metadata reader is not implemented"
    return importlib.import_module("infra.hybrid.stock_engine")


def run(monkeypatch, response, call="version", argument=None):
    api = module()
    client, server = socket.socketpair()
    received = []

    def serve():
        with server:
            request = b""
            while b"\r\n\r\n" not in request:
                request += server.recv(4096)
            received.append(request)
            # A bounded reader may correctly close during an oversized reply.
            with suppress(OSError):
                server.sendall(response)

    worker = threading.Thread(target=serve)
    worker.start()
    monkeypatch.setattr(api, "_connection", lambda _deadline: client)
    try:
        reader = api.StockEngineReader()
        result = (
            getattr(reader, call)(argument) if argument is not None else getattr(reader, call)()
        )
        return result, received
    finally:
        client.close()
        worker.join(timeout=2)
        assert not worker.is_alive()


@pytest.mark.parametrize(
    "call,argument,path",
    [
        ("version", None, "/version"),
        ("image", IMAGE, "/v1.52/images/" + IMAGE + "/json"),
        ("inspect", CID, "/v1.52/containers/" + CID + "/json"),
        (
            "inspect_attempt",
            ATTEMPT,
            "/v1.52/containers/hybrid-stock-research-" + ATTEMPT + "/json",
        ),
    ],
)
def test_read_routes_are_fixed_and_return_bounded_bytes(monkeypatch, call, argument, path):
    body, sent = run(
        monkeypatch, b"HTTP/1.0 200 OK\r\nContent-Length: 3\r\n\r\n{}\n", call, argument
    )
    assert body == b"{}\n"
    assert sent == [
        ("GET " + path + " HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n").encode()
    ]


def test_close_delimited_response_is_also_bounded(monkeypatch):
    assert run(monkeypatch, b"HTTP/1.0 200 OK\r\nServer: fictional\r\n\r\n{}")[0] == b"{}"


@pytest.mark.parametrize(
    "response",
    [
        b"HTTP/1.0 404 Missing\r\nContent-Length: 0\r\n\r\n",
        b"HTTP/1.0 500 Private diagnostic\r\nContent-Length: 7\r\n\r\nprivate",
        b"HTTP/1.0 200 OK\r\nContent-Length: 5\r\n\r\n{}",
        b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\n{}extra",
        b"HTTP/1.0 200 OK\r\nContent-Length: -1\r\n\r\n",
        b"HTTP/1.0 200 OK\r\nContent-Length: 1048577\r\n\r\n",
        b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\ncontent-length: 2\r\n\r\n{}",
        b"HTTP/1.0 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
        b"HTTP/1.0 200 OK\r\n folded: header\r\n\r\n{}",
        b"HTTP/1.0 200 OK\r\nMissing-Colon\r\n\r\n{}",
        b"HTTP/2 200 OK\r\n\r\n{}",
        b"HTTP/1.0 100 Continue\r\n\r\n",
        b"HTTP/1.0 200 OK\r\nX-Value: \xff\r\n\r\n{}",
        b"incomplete",
    ],
    ids=[
        "404",
        "private-error",
        "truncated",
        "extra-body",
        "negative-length",
        "large-length",
        "duplicate",
        "chunked",
        "folded",
        "colon",
        "protocol",
        "interim",
        "header-encoding",
        "truncated-header",
    ],
)
def test_invalid_or_ambiguous_http_is_sanitized(monkeypatch, response):
    with pytest.raises(ValueError, match=r"^stock_engine_unavailable$") as error:
        run(monkeypatch, response)
    assert error.value.__cause__ is None


@pytest.mark.parametrize(
    "call,argument",
    [
        ("image", IMAGE + "?query"),
        ("image", "other:latest"),
        ("image", "b" * 64),
        ("inspect", CID[:12]),
        ("inspect", CID + "/archive"),
        ("inspect", True),
        ("inspect_attempt", "../" + ATTEMPT),
        ("inspect_attempt", "E" * 32),
    ],
)
def test_invalid_routes_deny_before_socket(monkeypatch, call, argument):
    api = module()
    monkeypatch.setattr(api, "_connection", lambda _deadline: pytest.fail("Socket was opened"))
    with pytest.raises(ValueError, match=r"^stock_engine_unavailable$"):
        getattr(api.StockEngineReader(), call)(argument)


def test_peer_and_socket_failures_do_not_expose_exception_text(monkeypatch):
    api = module()

    def failed(_deadline):
        raise OSError("fictional private path")

    monkeypatch.setattr(api, "_connection", failed)
    with pytest.raises(ValueError, match=r"^stock_engine_unavailable$") as error:
        api.StockEngineReader().version()
    assert error.value.__cause__ is None


def test_slow_drip_cannot_reset_the_absolute_operation_budget(monkeypatch):
    api = module()
    client, server = socket.socketpair()
    monkeypatch.setattr(api, "_connection", lambda _deadline: client)
    monkeypatch.setattr(api, "_IO_SECONDS", 0.08)

    def serve():
        with server:
            server.recv(4096)
            for piece in b"HTTP/1.0 200 OK\r\n\r\n{}":
                try:
                    server.send(bytes([piece]))
                    time.sleep(0.015)
                except OSError:
                    break

    worker = threading.Thread(target=serve)
    worker.start()
    started = time.monotonic()
    try:
        with pytest.raises(ValueError, match=r"^stock_engine_unavailable$"):
            api.StockEngineReader().version()
        assert time.monotonic() - started < 0.4
    finally:
        client.close()
        worker.join(timeout=2)
        assert not worker.is_alive()


@pytest.mark.parametrize(
    "response",
    [
        b"HTTP/1.0 200 OK\r\nX-Large: " + b"a" * 8192 + b"\r\n\r\n{}",
        b"HTTP/1.0 200 OK\r\n\r\n" + b"a" * 1048577,
        b"HTTP/1.0 200 OK\r\nContent-Length: 0\r\n\r\n",
        b"HTTP/1.0 200 OK\r\n\r\n",
    ],
    ids=["header-budget", "body-budget", "zero-length", "empty-close-body"],
)
def test_header_and_both_body_framing_budgets_are_enforced(monkeypatch, response):
    with pytest.raises(ValueError, match=r"^stock_engine_unavailable$"):
        run(monkeypatch, response)


@pytest.fixture
def connector(monkeypatch):
    api = module()
    calls = []

    class Peer:
        identity = (123, 0, 0)

        def settimeout(self, timeout):
            assert 0 < timeout <= 5
            calls.append("timeout")

        def connect(self, path):
            assert path == "/var/run/docker.sock"
            calls.append("connect")

        def getsockopt(self, level, option, size):
            assert level == socket.SOL_SOCKET and option == 17 and size == 12
            calls.append("peer")
            return struct.pack("3i", *self.identity)

        def close(self):
            calls.append("close")

    peer = Peer()

    def create(family, kind):
        assert family == socket.AF_UNIX and kind == socket.SOCK_STREAM
        calls.append("socket")
        return peer

    def metadata(path):
        assert path == "/var/run/docker.sock"
        calls.append("lstat")
        return SimpleNamespace(st_mode=stat.S_IFSOCK | 0o660, st_uid=0)

    monkeypatch.setattr(api.sys, "platform", "linux")
    monkeypatch.setattr(api.os, "geteuid", lambda: 0)
    monkeypatch.setattr(api.os, "lstat", metadata)
    monkeypatch.setattr(api.socket, "SO_PEERCRED", 17, raising=False)
    monkeypatch.setattr(api.socket, "socket", create)
    return api, peer, calls


def test_public_connector_is_fixed_root_linux_unix_and_checks_peer(connector):
    api, peer, calls = connector
    assert api._connection(time.monotonic() + 1) is peer
    assert calls == ["lstat", "socket", "timeout", "connect", "peer"]
    peer.close()


@pytest.mark.parametrize("identity", [(123, 1000, 1000), (0, 0, 0)])
def test_bad_peer_fails_and_closes_once(connector, identity):
    api, peer, calls = connector
    peer.identity = identity
    with pytest.raises(ValueError, match=r"^stock_engine_unavailable$"):
        api._connection(time.monotonic() + 1)
    assert calls.count("close") == 1


@pytest.mark.parametrize(
    "mode,uid",
    [
        (stat.S_IFLNK | 0o777, 0),
        (stat.S_IFSOCK | 0o666, 0),
        (stat.S_IFSOCK | 0o660, 1000),
    ],
)
def test_unsafe_socket_metadata_denies_before_connection(connector, monkeypatch, mode, uid):
    api, _, calls = connector
    monkeypatch.setattr(api.os, "lstat", lambda _path: SimpleNamespace(st_mode=mode, st_uid=uid))
    with pytest.raises(ValueError, match=r"^stock_engine_unavailable$"):
        api._connection(time.monotonic() + 1)
    assert "socket" not in calls


@pytest.mark.parametrize("platform,uid", [("darwin", 0), ("linux", 1000)])
def test_unsupported_host_denies_without_socket_metadata(connector, monkeypatch, platform, uid):
    api, _, calls = connector
    monkeypatch.setattr(api.sys, "platform", platform)
    monkeypatch.setattr(api.os, "geteuid", lambda: uid)
    with pytest.raises(ValueError, match=r"^stock_engine_unavailable$"):
        api._connection(time.monotonic() + 1)
    assert not calls


def test_missing_peer_credentials_support_denies_with_fixed_error(connector, monkeypatch):
    api, _, _calls = connector
    monkeypatch.delattr(api.socket, "SO_PEERCRED")
    with pytest.raises(ValueError, match=r"^stock_engine_unavailable$"):
        api.StockEngineReader().version()
