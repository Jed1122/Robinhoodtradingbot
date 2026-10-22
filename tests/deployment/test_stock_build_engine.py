"""Fixed build transport over real socketpairs; native Docker is default-denied."""

import copy
import hashlib
import importlib
import json
import socket
import threading
import time
from contextlib import suppress
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from test_stock_container import engine, image
from test_stock_prestart import ENV, IMAGE, encoded
from test_stock_release_producer import opened
from test_stock_release_producer import scenario as producer_scenario


def api():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_build_engine.py"
    assert path.is_file(), "Fixed stock build Engine transport is missing"
    return importlib.import_module("infra.hybrid.stock_build_engine")


def response(body, headers=b"", status=b"200 OK"):
    return (
        b"HTTP/1.0 "
        + status
        + b"\r\nContent-Type: application/json\r\nContent-Length: "
        + str(len(body)).encode()
        + b"\r\n"
        + headers
        + b"\r\n"
        + body
    )


def terminal():
    return json.dumps({"stream": IMAGE + "\n"}, separators=(",", ":")).encode() + b"\r\n"


class Wire:
    def __init__(self, replies, on_connect=None):
        self.replies, self.requests, self.threads = list(replies), [], []
        self.on_connect = on_connect

    def connect(self, deadline):
        assert self.replies, "Unexpected request replay"
        if self.on_connect:
            self.on_connect(len(self.threads))
        reply = self.replies.pop(0)
        client, server = socket.socketpair()

        def serve():
            with server:
                request = b""
                while b"\r\n\r\n" not in request:
                    chunk = server.recv(4096)
                    if not chunk:
                        return
                    request += chunk
                head, body = request.split(b"\r\n\r\n", 1)
                headers = dict(line.split(b":", 1) for line in head.split(b"\r\n")[1:])
                size = int(headers.get(b"Content-Length", b"0"))
                while len(body) < size:
                    chunk = server.recv(65536)
                    if not chunk:
                        return
                    body += chunk
                self.requests.append((head, body))
                with suppress(OSError):
                    if callable(reply):
                        reply(server)
                    else:
                        server.sendall(reply)

        thread = threading.Thread(target=serve)
        self.threads.append(thread)
        thread.start()
        return client

    def install(self, monkeypatch, module):
        from infra.hybrid import stock_engine

        monkeypatch.setattr(stock_engine, "_connection", self.connect)
        monkeypatch.setattr(module, "_connection", self.connect)
        return self

    def join(self):
        for thread in self.threads:
            thread.join(timeout=3)
            assert not thread.is_alive()


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    value = producer_scenario.__wrapped__(tmp_path, monkeypatch)
    module = api()

    def denied(*args, **kwargs):
        raise AssertionError("Native Docker is forbidden in these fixtures")

    monkeypatch.setattr(module, "_connection", denied)
    version = {**engine(), "Version": "29.1.3", "Arch": "amd64"}
    metadata = image()
    metadata["Config"]["Env"] = ENV.copy()
    return value, module, encoded(version), encoded(metadata)


def test_durable_owned_build_sends_exact_tar_then_inspects_only_terminal_id(scenario, monkeypatch):
    state, module, version, metadata = scenario
    _, root, _, sha, raw, _, _ = state
    directory = root / "attempts" / sha

    def check_dispatch(index):
        if index == 1:
            assert (directory / "source.tar").read_bytes() == raw
            intent = json.loads((directory / "dispatch.json").read_bytes())
            request = (directory / "build-request.http").read_bytes()
            assert intent["request_sha256"] == hashlib.sha256(request).hexdigest()
            assert intent["source_copy_sha256"] == sha
            assert intent["engine_sha256"] == hashlib.sha256(version).hexdigest()

    wire = Wire(
        [response(version), response(terminal()), response(metadata)], check_dispatch
    ).install(monkeypatch, module)
    with opened(state) as lease:
        result = module._build(lease)
        assert result.image_digest == IMAGE
        assert lease.dispatched
        with pytest.raises(ValueError):
            module._build(lease)
    wire.join()
    assert len(wire.requests) == 3
    assert wire.requests[0][0].split(b"\r\n")[0] == b"GET /version HTTP/1.0"
    head, sent = wire.requests[1]
    method, path, protocol = head.split(b"\r\n")[0].decode().split(" ")
    assert (method, urlsplit(path).path, protocol) == ("POST", "/v1.52/build", "HTTP/1.0")
    query = parse_qs(urlsplit(path).query)
    assert query == {
        "version": ["1"],
        "q": ["true"],
        "dockerfile": ["Dockerfile"],
        "pull": ["false"],
        "rm": ["true"],
        "forcerm": ["false"],
        "networkmode": ["bridge"],
        "platform": ["linux/amd64"],
        "memory": ["536870912"],
        "memswap": ["536870912"],
        "cpuperiod": ["100000"],
        "cpuquota": ["50000"],
        "buildargs": [
            json.dumps({"PYTHON_BASE_IMAGE": lease.source.base_ref}, separators=(",", ":"))
        ],
    }
    assert sent == raw and b"Authorization" not in head and b"Registry" not in head
    assert (directory / "build-request.http").read_bytes() == head + b"\r\n\r\n" + raw
    assert (
        wire.requests[2][0].split(b"\r\n")[0]
        == ("GET /v1.52/images/" + IMAGE + "/json HTTP/1.0").encode()
    )
    complete = json.loads((directory / "build-complete.json").read_bytes())
    assert complete["image_digest"] == IMAGE
    assert complete["response_sha256"] == hashlib.sha256(response(terminal())).hexdigest()
    assert (directory / "image.bin").read_bytes() == metadata


@pytest.mark.parametrize(
    "field,value",
    [
        ("Version", "29.1.2"),
        ("Version", None),
        ("Arch", "arm64"),
        ("Os", "windows"),
        ("ApiVersion", "1.51"),
    ],
)
def test_unqualified_engine_denies_post(scenario, monkeypatch, field, value):
    state, module, version, _ = scenario
    record = json.loads(version)
    record[field] = value
    wire = Wire([response(encoded(record))]).install(monkeypatch, module)
    with opened(state) as lease, pytest.raises(ValueError):
        module._build(lease)
    wire.join()
    assert len(wire.requests) == 1
    assert not (state[1] / "attempts" / state[3] / "dispatch.json").exists()


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"HTTP/1.0 200 OK\r\n",
        response(b"{}"),
        response(terminal()[:-1]),
        response(terminal() + terminal()),
        response(b'{"aux":{"ID":"' + IMAGE.encode() + b'"}}\r\n'),
        response(terminal(), status=b"500 error"),
        response(terminal(), headers=b"Content-Length: 1\r\n"),
        response(terminal(), headers=b"Transfer-Encoding: chunked\r\n"),
        response(terminal()).replace(b"application/json", b"text/plain"),
        response(terminal()).replace(b"Content-Length: ", b"Content-Length: 0"),
        response(terminal()) + b"unexpected",
        response(terminal())[:-3],
    ],
)
def test_ambiguous_reply_is_retained_but_never_inspected_or_replayed(scenario, monkeypatch, raw):
    state, module, version, _ = scenario
    wire = Wire([response(version), raw]).install(monkeypatch, module)
    with opened(state) as lease:
        with pytest.raises(ValueError):
            module._build(lease)
        with pytest.raises(ValueError):
            module._build(lease)
    wire.join()
    directory = state[1] / "attempts" / state[3]
    assert len(wire.requests) == 2
    assert (directory / "build-response.http").read_bytes() == raw
    assert not (directory / "build-complete.json").exists()


def test_single_socket_idle_timeout_does_not_replay_or_renew_original_cap(scenario, monkeypatch):
    state, module, version, metadata = scenario

    def delayed(server):
        time.sleep(1.1)
        server.sendall(response(terminal()))

    wire = Wire([response(version), delayed, response(metadata)]).install(monkeypatch, module)
    with opened(state) as lease:
        initial_deadline = lease.deadline_ns
        assert module._build(lease).image_digest == IMAGE
        assert lease.deadline_ns == initial_deadline
    wire.join()
    assert len(wire.requests) == 3


@pytest.mark.parametrize("kind", ["shutdown", "build_cap", "producer_cap"])
def test_idle_expiry_or_shutdown_preserves_partial_response_without_replay(
    scenario, monkeypatch, kind
):
    state, module, version, _ = scenario
    clock, shutdown = state[5:]
    prefix = b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n"

    wire = Wire([response(version), prefix]).install(monkeypatch, module)

    class InterruptAfterRead:
        def __init__(self, peer):
            self.peer = peer

        def __getattr__(self, name):
            return getattr(self.peer, name)

        def recv(self, size):
            chunk = self.peer.recv(size)
            if kind == "shutdown":
                shutdown[0] = True
            else:
                clock["monotonic_ns"] += (900 if kind == "build_cap" else 1200) * 1_000_000_000
            return chunk

    monkeypatch.setattr(
        module, "_connection", lambda deadline: InterruptAfterRead(wire.connect(deadline))
    )
    with pytest.raises(ValueError), opened(state) as lease:
        module._build(lease)
    wire.join()
    directory = state[1] / "attempts" / state[3]
    assert len(wire.requests) == 2
    assert (directory / "build-response.http").read_bytes() == prefix
    assert not (directory / "build-complete.json").exists()


def test_intent_fsync_failure_prevents_post(scenario, monkeypatch):
    state, module, version, _ = scenario
    wire = Wire([response(version)]).install(monkeypatch, module)
    original = state[0].os.fsync
    with pytest.raises(ValueError), opened(state) as lease:

        def fail_dispatch(fd):
            if Path("/dev/fd/" + str(fd)).is_file():
                # Failing all later regular-file fsyncs includes the original request.
                raise OSError("fixture disk failure")
            original(fd)

        monkeypatch.setattr(state[0].os, "fsync", fail_dispatch)
        module._build(lease)
    monkeypatch.setattr(state[0].os, "fsync", original)
    wire.join()
    assert len(wire.requests) == 1


def test_copied_or_supplied_context_never_acquires_build_authority(scenario):
    state, module, _, _ = scenario
    with opened(state) as lease:
        for supplied in (object(), lease.source, copy.copy(lease)):
            with pytest.raises(ValueError):
                module._build(supplied)


@pytest.mark.parametrize("kind", ["partial_send", "send_timeout", "recv_timeout"])
def test_same_socket_partial_io_keeps_one_dispatch(scenario, monkeypatch, kind):
    state, module, version, metadata = scenario
    wire = Wire([response(version), response(terminal()), response(metadata)]).install(
        monkeypatch, module
    )

    class Partial:
        def __init__(self, peer):
            self.peer, self.sent_once, self.read_once = peer, False, False

        def __getattr__(self, name):
            return getattr(self.peer, name)

        def send(self, raw):
            if kind == "send_timeout" and not self.sent_once:
                self.sent_once = True
                raise TimeoutError("fixture upload idle")
            return self.peer.send(raw[:31] if kind == "partial_send" else raw)

        def recv(self, size):
            if kind == "recv_timeout" and not self.read_once:
                self.read_once = True
                raise TimeoutError("fixture read idle")
            return self.peer.recv(size)

    monkeypatch.setattr(module, "_connection", lambda deadline: Partial(wire.connect(deadline)))
    with opened(state) as lease:
        assert module._build(lease).image_digest == IMAGE
    wire.join()
    assert len(wire.requests) == 3 and wire.requests[1][1] == state[4]


@pytest.mark.parametrize("kind", ["connection", "zero_send", "upload_cap", "close"])
def test_ambiguous_transport_failure_never_replays_or_completes(scenario, monkeypatch, kind):
    state, module, version, _ = scenario
    wire = Wire([response(version), response(terminal())]).install(monkeypatch, module)
    clock = state[5]

    class Failed:
        def __init__(self, peer):
            self.peer = peer

        def __getattr__(self, name):
            return getattr(self.peer, name)

        def send(self, raw):
            if kind == "zero_send":
                return 0
            if kind == "upload_cap":
                count = self.peer.send(raw[:31])
                clock["monotonic_ns"] += 30_000_000_000
                return count
            return self.peer.send(raw)

        def close(self):
            self.peer.close()
            if kind == "close":
                raise OSError("fixture close failure")

    def connect(deadline):
        if kind == "connection":
            raise OSError("fixture unavailable daemon")
        return Failed(wire.connect(deadline))

    monkeypatch.setattr(module, "_connection", connect)
    with opened(state) as lease:
        with pytest.raises(ValueError):
            module._build(lease)
        with pytest.raises(ValueError):
            module._build(lease)
    wire.join()
    assert len(wire.requests) <= 2
    assert not (state[1] / "attempts" / state[3] / "build-complete.json").exists()


@pytest.mark.parametrize("kind", ["wrong_id", "unsafe_image", "late_inspect", "late_version"])
def test_metadata_must_match_exact_image_and_original_window(scenario, monkeypatch, kind):
    state, module, version, metadata = scenario
    row = json.loads(metadata)
    if kind == "wrong_id":
        row["Id"] = "sha256:" + "c" * 64
    elif kind == "unsafe_image":
        row["Config"]["User"] = "0"

    def late(index):
        if (kind == "late_inspect" and index == 2) or (kind == "late_version" and index == 0):
            state[5]["monotonic_ns"] += 900_000_000_000

    wire = Wire([response(version), response(terminal()), response(encoded(row))], late).install(
        monkeypatch, module
    )
    with pytest.raises(ValueError), opened(state) as lease:
        module._build(lease)
    wire.join()
    assert len(wire.requests) == (1 if kind == "late_version" else 3)
    assert not (state[1] / "attempts" / state[3] / "build-complete.json").exists()


@pytest.mark.parametrize("name", ["build-request.http", "dispatch.json"])
@pytest.mark.parametrize("failure", ["fsync", "shutdown"])
def test_request_and_dispatch_durability_are_required_before_any_post(
    scenario, monkeypatch, name, failure
):
    state, module, version, _ = scenario
    wire = Wire([response(version)]).install(monkeypatch, module)
    producer, root, _, sha, _, _, shutdown = state
    target = root / "attempts" / sha / name
    original = producer.os.fsync
    reached = False

    def interrupted(fd):
        nonlocal reached
        if target.exists():
            info, expected = producer.os.fstat(fd), target.stat()
            if (info.st_dev, info.st_ino) == (expected.st_dev, expected.st_ino):
                reached = True
                if failure == "fsync":
                    raise OSError("fixture dispatch durability failure")
                shutdown[0] = True
        original(fd)

    with pytest.raises(ValueError), opened(state) as lease:
        monkeypatch.setattr(producer.os, "fsync", interrupted)
        module._build(lease)
    monkeypatch.setattr(producer.os, "fsync", original)
    wire.join()
    assert reached and len(wire.requests) == 1
    assert not (target.parent / "build-complete.json").exists()
