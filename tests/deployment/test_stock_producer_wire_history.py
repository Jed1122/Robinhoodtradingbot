"""Versioned historical wire proofs, with memory peers and no native sockets."""

import errno
import hashlib
import socket
from urllib.parse import quote

import pytest
from test_stock_build_engine import Wire
from test_stock_prestart import IMAGE
from test_stock_probe_controller import Daemon
from test_stock_producer_history import complete, next_source, rehash_records
from test_stock_release_producer import opened
from test_stock_release_publication import scenario as publication_scenario

from infra.hybrid import stock_build_engine, stock_build_legacy, stock_engine
from infra.hybrid.stock_build_inputs import SourceArchive


class MemoryPeer:
    """Only the external byte transport is fictional; all history checks are real."""

    def __init__(self, reply):
        self.reply = reply
        self.request = bytearray()
        self.buffered = None
        self.blocking = True

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def settimeout(self, seconds):
        self.blocking = seconds != 0

    def setblocking(self, blocking):
        self.blocking = blocking

    def send(self, raw):
        self.request.extend(raw)
        return len(raw)

    def sendall(self, raw):
        self.request.extend(raw)

    def recv(self, maximum, flags=0):
        if self.buffered is None:
            head, separator, body = bytes(self.request).partition(b"\r\n\r\n")
            assert separator == b"\r\n\r\n"
            headers = {
                key.lower(): value.strip()
                for key, value in (row.split(b":", 1) for row in head.split(b"\r\n")[1:])
            }
            assert len(body) == int(headers.get(b"content-length", b"0"))
            self.buffered = self.reply(head, body)
        if not self.buffered and not self.blocking:
            raise BlockingIOError(errno.EAGAIN, "fictional open peer has no queued bytes")
        result = self.buffered[:maximum]
        if not flags & socket.MSG_PEEK:
            self.buffered = self.buffered[maximum:]
        return result

    def close(self):
        pass


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    def no_socket(*_args, **_kwargs):
        pytest.fail("Wire-history fixtures must never open a real socket")

    monkeypatch.setattr(socket, "socketpair", no_socket)

    def build_connect(wire, _deadline):
        assert wire.replies, "Unexpected build request replay"
        reply = wire.replies.pop(0)
        assert type(reply) is bytes

        def respond(head, body):
            wire.requests.append((head, body))
            return reply

        return MemoryPeer(respond)

    def probe_connect(daemon, _deadline):
        def respond(head, body):
            method, path, _version = head.split(b"\r\n", 1)[0].decode("ascii").split(" ")
            return daemon.reply(method, path, body)

        return MemoryPeer(respond)

    monkeypatch.setattr(Wire, "connect", build_connect)
    monkeypatch.setattr(Daemon, "connect", probe_connect)
    return publication_scenario.__wrapped__(tmp_path, monkeypatch)


def legacy_request(source):
    """Hand-written historical query; never computed by either product encoder."""
    prefix = (
        b"POST /v1.52/build?version=1&q=true&dockerfile=Dockerfile&pull=false&rm=true"
        b"&forcerm=false&networkmode=bridge&platform=linux%2Famd64&memory=536870912"
        b"&memswap=536870912&cpuperiod=100000&cpuquota=50000"
        b"&buildargs=%7B%22PYTHON_BASE_IMAGE%22%3A%22"
    )
    return (
        prefix
        + quote(source.base_ref, safe="").encode("ascii")
        + b"%22%7D HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n"
        b"Content-Type: application/x-tar\r\nContent-Length: "
        + str(len(source.raw)).encode("ascii")
        + b"\r\n\r\n"
        + source.raw
    )


def forward_request(source):
    return legacy_request(source).replace(b" HTTP/1.0\r\n", b" HTTP/1.1\r\n", 1)


def quiet_body():
    return b'{"stream":"' + IMAGE.encode("ascii") + b'\\n"}\r\n'


def reply(kind):
    body = quiet_body()
    if kind == "legacy":
        return b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n" + body
    head = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
    if kind == "length":
        return head + b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
    chunked = (
        head
        + b"Transfer-Encoding: chunked\r\n\r\n"
        + format(len(body), "x").encode()
        + b"\r\n"
        + body
        + b"\r\n0\r\n\r\n"
    )
    assert kind in {"chunked", "truncated_chunked"}
    return chunked[:-2] if kind == "truncated_chunked" else chunked


def historical_wire(scenario, monkeypatch, generation="legacy", response="legacy"):
    """Retain a balanced adversarial fixture, preserving all other real stage proofs."""
    old = complete(scenario, monkeypatch)
    directory = old.root / "attempts" / old.source.digest
    request = legacy_request(old.source) if generation == "legacy" else forward_request(old.source)
    if generation == "unknown":
        request = request.replace(b" HTTP/1.1\r\n", b" HTTP/1.2\r\n", 1)
    elif generation == "wrong_source":
        request += b"not-the-source-archive"
    (directory / "build-request.http").write_bytes(request)
    rehash_records(
        old,
        scenario[1],
        "dispatch.json",
        lambda record: record.__setitem__("request_sha256", hashlib.sha256(request).hexdigest()),
    )
    response_raw = reply(response)
    (directory / "build-response.http").write_bytes(response_raw)
    rehash_records(
        old,
        scenario[1],
        "build-complete.json",
        lambda record: record.__setitem__(
            "response_sha256", hashlib.sha256(response_raw).hexdigest()
        ),
    )
    return old


def test_frozen_legacy_request_has_independent_golden_bytes():
    source = SourceArchive(
        "a" * 64,
        "b" * 40,
        b"tar-v1\n",
        "python:3.12-slim-bookworm@sha256:" + "1" * 64,
        b"",
        b"",
    )
    expected = (
        b"POST /v1.52/build?version=1&q=true&dockerfile=Dockerfile&pull=false&rm=true"
        b"&forcerm=false&networkmode=bridge&platform=linux%2Famd64&memory=536870912"
        b"&memswap=536870912&cpuperiod=100000&cpuquota=50000"
        b"&buildargs=%7B%22PYTHON_BASE_IMAGE%22%3A%22python%3A3.12-slim-bookworm%40sha256%3A"
        + b"1"
        * 64
        + b"%22%7D HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n"
        b"Content-Type: application/x-tar\r\nContent-Length: 7\r\n\r\ntar-v1\n"
    )
    assert stock_build_legacy._source_request(source) == expected


def test_frozen_legacy_close_delimited_witness_is_data_only():
    body = b'{"stream":"sha256:' + b"a" * 64 + b'\\n"}\r\n'
    raw = b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n" + body
    assert stock_build_legacy._body(raw) == body
    with pytest.raises(ValueError):
        stock_build_legacy._body(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n"
        )


@pytest.mark.parametrize(
    "changed", ["encoder_raises", "encoder_changes", "parser_raises", "parser_changes"]
)
def test_legacy_positive_history_survives_forward_wire_changes(scenario, monkeypatch, changed):
    old = historical_wire(scenario, monkeypatch)
    state = next_source(scenario)

    def unavailable(*_args):
        raise AssertionError("Historical HTTP/1.0 proof called the forward wire helper")

    if changed == "encoder_raises":
        monkeypatch.setattr(stock_build_engine, "_source_request", unavailable)
    elif changed == "encoder_changes":
        monkeypatch.setattr(stock_build_engine, "_source_request", forward_request)
    elif changed == "parser_raises":
        monkeypatch.setattr(stock_build_engine, "_source_request", legacy_request)
        monkeypatch.setattr(stock_build_engine, "_body", unavailable)
    else:
        monkeypatch.setattr(stock_build_engine, "_source_request", legacy_request)
        monkeypatch.setattr(stock_build_engine, "_body", lambda _raw: b"changed future format")
    with opened(state, release_root=scenario[1]) as current:
        assert current.completed_sources == {old.source.digest}
        assert current.built_image is None and current.terminal_ack is False


@pytest.mark.parametrize("response", ["length", "chunked"])
def test_forward_history_uses_the_strict_forward_parser(scenario, monkeypatch, response):
    old = historical_wire(scenario, monkeypatch, generation="forward", response=response)
    state = next_source(scenario)

    def wrong_generation(_raw):
        raise AssertionError("HTTP/1.1 proof was sent to the historical witness parser")

    monkeypatch.setattr(stock_build_legacy, "_body", wrong_generation)
    with opened(state, release_root=scenario[1]) as current:
        assert current.completed_sources == {old.source.digest}


@pytest.mark.parametrize(
    "generation,response",
    [
        ("legacy", "chunked"),
        ("forward", "legacy"),
        ("forward", "truncated_chunked"),
        ("unknown", "length"),
        ("wrong_source", "length"),
    ],
)
def test_balanced_history_cannot_mix_or_guess_wire_generations(
    scenario, monkeypatch, generation, response
):
    old = historical_wire(scenario, monkeypatch, generation, response)
    state = next_source(scenario)
    with pytest.raises(ValueError), opened(state, release_root=scenario[1]):
        pytest.fail("Balanced mismatched historical wire was admitted")
    assert not (old.root / "attempts" / state[3]).exists()


def test_fresh_build_never_uses_a_legacy_witness_as_transport_fallback(scenario, monkeypatch):
    old = historical_wire(scenario, monkeypatch)
    state = next_source(scenario)
    version = scenario[0][0][0][2]
    requests = []

    def respond(head, body):
        requests.append((head, body))
        if head.startswith(b"GET /version "):
            return (
                b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                + str(len(version)).encode()
                + b"\r\n\r\n"
                + version
            )
        assert head.startswith(b"POST /v1.52/build?"), "Unframed response reached image inspection"
        return reply("legacy")

    def connect(_deadline):
        return MemoryPeer(respond)

    monkeypatch.setattr(stock_build_engine, "_connection", connect)
    monkeypatch.setattr(stock_engine, "_connection", connect)
    with opened(state, release_root=scenario[1]) as current:
        with pytest.raises(ValueError):
            stock_build_engine._build(current)
        with pytest.raises(ValueError):
            stock_build_engine._build(current)
        assert current.completed_sources == {old.source.digest}
    directory = old.root / "attempts" / state[3]
    assert len(requests) == 2
    assert (directory / "build-response.http").read_bytes() == reply("legacy")
    assert not (directory / "image.bin").exists()
    assert not (directory / "build-complete.json").exists()
