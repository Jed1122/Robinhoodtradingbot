"""Offline framing boundaries: no daemon, network, or real socket is opened."""

import errno
import importlib

import pytest


def api():
    return importlib.import_module("infra.hybrid.stock_build_engine")


LENGTH = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}"
CHUNKED = (
    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n"
    b"1\r\n{\r\n1\r\n}\r\n0\r\n\r\n"
)


class Lease:
    def __init__(self):
        self.claims = []
        self.retained = []
        self.checks = 0

    def claim(self, request, cap):
        self.claims.append((request, cap))

    def check(self, *, not_after_ns):
        self.checks += 1
        return {"monotonic_ns": 1}

    def retain(self, name, data):
        self.retained.append((name, data))


class Peer:
    def __init__(self, fragments, queued=None):
        self.fragments = list(fragments)
        self.queued = BlockingIOError(errno.EAGAIN, "fixture") if queued is None else queued
        self.timeout = None
        self.closed = False
        self.sent = bytearray()

    def settimeout(self, value):
        self.timeout = value

    def send(self, data):
        self.sent.extend(data)
        return len(data)

    def recv(self, size, flags=0):
        if flags:
            assert self.timeout == 0.0, "queued check must actually be nonblocking"
            result = self.queued
        else:
            assert self.fragments, "a framed response must not wait for socket EOF"
            result = self.fragments.pop(0)
        if isinstance(result, BaseException):
            raise result
        assert len(result) <= size
        return result

    def close(self):
        self.closed = True


@pytest.mark.parametrize("raw", [LENGTH, CHUNKED])
@pytest.mark.parametrize("fragmented", [False, True])
def test_complete_frame_returns_without_waiting_for_peer_close(monkeypatch, raw, fragmented):
    module, lease = api(), Lease()
    fragments = [raw[index : index + 1] for index in range(len(raw))] if fragmented else [raw]
    peer = Peer(fragments)
    monkeypatch.setattr(module, "_connection", lambda deadline: peer)
    assert module._exchange(lease, b"fixed upload", 900_000_000_000) == raw
    assert module._body(raw) == b"{}"
    assert bytes(peer.sent) == b"fixed upload" and peer.closed
    assert lease.claims == [(b"fixed upload", 900_000_000_000)]
    assert lease.retained == [("build-response.http", raw)]


@pytest.mark.parametrize("raw", [LENGTH, CHUNKED])
@pytest.mark.parametrize("queued", [b"", ConnectionResetError(errno.ECONNRESET, "fixture")])
def test_complete_frame_survives_post_frame_eof_or_reset(monkeypatch, raw, queued):
    module, lease, peer = api(), Lease(), Peer([raw], queued)
    monkeypatch.setattr(module, "_connection", lambda deadline: peer)
    assert module._exchange(lease, b"upload", 900_000_000_000) == raw
    assert lease.retained == [("build-response.http", raw)]


@pytest.mark.parametrize("raw", [LENGTH, CHUNKED])
def test_already_queued_trailing_byte_denies_and_retains_it(monkeypatch, raw):
    module, lease, peer = api(), Lease(), Peer([raw], b"x")
    monkeypatch.setattr(module, "_connection", lambda deadline: peer)
    with pytest.raises(ValueError, match="stock_build_engine_unavailable"):
        module._exchange(lease, b"upload", 900_000_000_000)
    assert lease.retained == [("build-response.http", raw + b"x")]
    assert peer.closed and lease.claims == [(b"upload", 900_000_000_000)]


@pytest.mark.parametrize("raw", [LENGTH, CHUNKED])
@pytest.mark.parametrize("ending", [b"", ConnectionResetError(errno.ECONNRESET, "fixture")])
def test_every_incomplete_frame_boundary_denies(monkeypatch, raw, ending):
    module = api()
    for boundary in range(len(raw)):
        prefix = raw[:boundary]
        module_lease, peer = Lease(), Peer(([prefix] if prefix else []) + [ending])
        monkeypatch.setattr(module, "_connection", lambda deadline, peer=peer: peer)
        with pytest.raises((ValueError, OSError)):
            module._exchange(module_lease, b"upload", 900_000_000_000)
        assert module_lease.retained == [("build-response.http", prefix)]
        assert peer.closed


@pytest.mark.parametrize(
    "raw",
    [
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{}",
        LENGTH + b"x",
        LENGTH.replace(b"Content-Length: 2", b"Content-Length: 2\r\nContent-Length: 2"),
        LENGTH.replace(b"Content-Length: 2", b"Content-Length: 2\r\nTransfer-Encoding: chunked"),
        LENGTH.replace(b"Content-Length: 2", b"Content-Length: 02"),
        LENGTH.replace(b"Content-Length: 2", b"Content-Length: 0"),
        LENGTH.replace(b"Content-Length: 2", b"Content-Length: 1048577"),
        CHUNKED.replace(b"Transfer-Encoding: chunked", b"Transfer-Encoding: gzip, chunked"),
        CHUNKED.replace(b"Transfer-Encoding: chunked", b"Transfer-Encoding: chunked; foo=bar"),
        CHUNKED.replace(b"1\r\n{", b"g\r\n{"),
        CHUNKED.replace(b"1\r\n{", b"100001\r\n{"),
        CHUNKED.replace(b"1\r\n{", b"1;foo=bar\r\n{"),
        CHUNKED.replace(b"0\r\n\r\n", b"0\r\nX-Trailer: value\r\n\r\n"),
        CHUNKED.replace(b"1\r\n{\r\n", b"1\r\n{x\r\n"),
        CHUNKED.replace(b"HTTP/1.1", b"HTTP/1.0"),
        CHUNKED.replace(b"0\r\n\r\n", b"00000000000000000\r\n\r\n"),
        CHUNKED.replace(b"1\r\n{", b"1" * 18 + b"\r\n{"),
        CHUNKED.replace(b"Content-Type:", b"Trailer: X-Trailer\r\nContent-Type:"),
        LENGTH.replace(b"Content-Type:", b"Content-Encoding: gzip\r\nContent-Type:"),
        LENGTH.replace(b"Content-Length: 2", b"content-length: 2\r\nContent-Length: 2"),
        LENGTH.replace(b"Content-Type: ", b"Content-Type \t: "),
        LENGTH.replace(b"application/json", b"application/json\x00"),
        LENGTH.replace(b"200 OK", b"100 Continue"),
        CHUNKED.replace(b"1\r\n{\r\n1\r\n}\r\n", b""),
        CHUNKED[:-1],
    ],
)
def test_ambiguous_or_unsupported_framing_denies(raw):
    with pytest.raises(ValueError, match="stock_build_engine_unavailable"):
        api()._body(raw)


def test_chunked_body_is_decoded_before_quiet_record_validation():
    assert api()._body(CHUNKED) == b"{}"


@pytest.mark.parametrize("raw", [LENGTH, CHUNKED])
def test_captured_trailing_byte_denies_without_waiting_or_losing_wire(monkeypatch, raw):
    module, lease, peer = api(), Lease(), Peer([raw + b"x"])
    monkeypatch.setattr(module, "_connection", lambda deadline: peer)
    with pytest.raises(ValueError, match="stock_build_engine_unavailable"):
        module._exchange(lease, b"upload", 900_000_000_000)
    assert lease.retained == [("build-response.http", raw + b"x")]
    assert peer.closed


@pytest.mark.parametrize(
    "failure", [OSError(errno.EIO, "fixture"), TimeoutError(errno.ETIMEDOUT, "fixture")]
)
def test_post_frame_non_reset_socket_failure_still_denies(monkeypatch, failure):
    module, lease, peer = api(), Lease(), Peer([LENGTH], failure)
    monkeypatch.setattr(module, "_connection", lambda deadline: peer)
    with pytest.raises(OSError):
        module._exchange(lease, b"upload", 900_000_000_000)
    assert lease.retained == [("build-response.http", LENGTH)] and peer.closed


def test_expired_lease_after_parsing_cannot_reach_queued_check(monkeypatch):
    module, lease, peer = api(), Lease(), Peer([LENGTH])
    original = module.StockBuildHTTPResponse.feed
    expired = False

    def parse_then_expire(frame, data):
        nonlocal expired
        complete = original(frame, data)
        expired = True
        return complete

    def check(*, not_after_ns):
        if expired:
            raise ValueError("fixture deadline reached")
        return {"monotonic_ns": 1}

    monkeypatch.setattr(lease, "check", check)
    monkeypatch.setattr(module.StockBuildHTTPResponse, "feed", parse_then_expire)
    monkeypatch.setattr(module, "_connection", lambda deadline: peer)
    with pytest.raises(ValueError, match="fixture deadline reached"):
        module._exchange(lease, b"upload", 900_000_000_000)
    assert lease.retained == [("build-response.http", LENGTH)] and peer.closed


@pytest.mark.parametrize("failure", ["close", "retain", "nonblocking"])
def test_successful_frame_does_not_hide_cleanup_or_socket_mode_failure(monkeypatch, failure):
    module, lease, peer = api(), Lease(), Peer([LENGTH])
    close = peer.close
    retain = lease.retain
    settimeout = peer.settimeout

    def fail_close():
        close()
        raise OSError(errno.EIO, "fixture")

    def fail_retain(name, data):
        retain(name, data)
        raise OSError(errno.EIO, "fixture")

    def fail_nonblocking(timeout):
        if timeout == 0.0:
            raise OSError(errno.EIO, "fixture")
        settimeout(timeout)

    if failure == "close":
        monkeypatch.setattr(peer, "close", fail_close)
    elif failure == "retain":
        monkeypatch.setattr(lease, "retain", fail_retain)
    else:
        monkeypatch.setattr(peer, "settimeout", fail_nonblocking)
    monkeypatch.setattr(module, "_connection", lambda deadline: peer)
    with pytest.raises(OSError):
        module._exchange(lease, b"upload", 900_000_000_000)
    assert lease.retained == [("build-response.http", LENGTH)] and peer.closed


@pytest.mark.parametrize("chunked", [False, True])
def test_maximum_body_is_accepted_but_one_more_decoded_byte_denies(chunked):
    body = b"x" * 1048576
    if chunked:
        prefix = CHUNKED.split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n"
        raw = prefix + b"100000\r\n" + body + b"\r\n0\r\n\r\n"
        extra = prefix + b"100000\r\n" + body + b"\r\n1\r\nx\r\n0\r\n\r\n"
    else:
        raw = LENGTH.replace(b"Content-Length: 2", b"Content-Length: 1048576")[:-2] + body
        extra = raw.replace(b"Content-Length: 1048576", b"Content-Length: 1048577") + b"x"
    assert api()._body(raw) == body
    with pytest.raises(ValueError, match="stock_build_engine_unavailable"):
        api()._body(extra)


def test_header_limit_is_enforced_independently_of_body_limit():
    head, body = LENGTH.split(b"\r\n\r\n")
    padding = b"X-Padding: " + b"x" * (8192 - len(head) - len(b"X-Padding: ") - 6)
    raw = head + b"\r\n" + padding + b"\r\n\r\n" + body
    assert raw.index(b"\r\n\r\n") + 4 == 8192
    assert api()._body(raw) == b"{}"
    with pytest.raises(ValueError, match="stock_build_engine_unavailable"):
        api()._body(raw.replace(padding, padding + b"x"))
