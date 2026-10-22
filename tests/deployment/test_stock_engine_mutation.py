"""Fictional root stores and socketpairs; never contact a Docker daemon."""

import hashlib
import importlib
import json
import os
import socket
import threading
import time
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

import pytest

from infra.hybrid import stock_attempts
from infra.hybrid.stock_container import ImageProfile
from infra.hybrid.stock_prestart import CreatedContainer, worker_request
from infra.hybrid.stock_release import RELEASE_ROOT, StockRelease, _policy

IMAGE = "sha256:" + "b" * 64
RELEASE = "d" * 64
CID = "f" * 64
BOOT = "11111111-2222-4333-8444-555555555555"


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def module():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_engine_mutation.py"
    assert path.is_file(), "Scoped stock Engine mutation transport is not implemented"
    return importlib.import_module("infra.hybrid.stock_engine_mutation")


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    api = module()
    root = tmp_path.resolve() / "operations"
    stock_attempts._initialize(root, trusted_uid=os.geteuid())
    clock = {
        "boot_id": BOOT,
        "utc": "2026-10-21T21:00:00+00:00",
        "monotonic_ns": time.monotonic_ns(),
    }
    initial_ns = clock["monotonic_ns"]
    monkeypatch.setattr(
        stock_attempts,
        "_clock",
        lambda: {**clock, "monotonic_ns": time.monotonic_ns() + clock["monotonic_ns"] - initial_ns},
    )
    # Only this fictional test substitutes the production fixed-root guard.
    monkeypatch.setattr(api, "_production_store", lambda store: None)
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
    environment = (
        "PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin",
        "LANG=C.UTF-8",
        "GPG_KEY=" + "A" * 40,
        "PYTHON_VERSION=3.12.13",
        "PYTHON_SHA256=" + "a" * 64,
        "PYTHONPATH=/app/src",
        "PYTHONDONTWRITEBYTECODE=1",
        "PYTHONUNBUFFERED=1",
        "LIVE_TRADING_ENABLED=false",
        "PREDICTION_LIVE_ENABLED=false",
    )
    image = ImageProfile(
        IMAGE,
        "amd64",
        environment,
        encoded(
            {
                "Test": ["NONE"],
                "Interval": 15000000000,
                "Timeout": 3000000000,
                "StartPeriod": 5000000000,
                "Retries": 3,
            }
        ),
    )
    return api, root, clock, release, image


def opened(scenario):
    return stock_attempts._open_operations(scenario[1], trusted_uid=os.geteuid())


def verified(intent):
    return CreatedContainer(CID, intent.attempt_id, RELEASE, IMAGE, "c" * 64, intent.compose_sha256)


def prepare_dispatch(store, release):
    claim = store.claim_create(release)
    now = stock_attempts._clock()["monotonic_ns"]
    fence = store.prepare_create(claim, "a" * 64, now + 5000000000)
    store.check_create_fence(fence)
    return fence


def response(status, body=b"", *, length=True):
    return (
        b"HTTP/1.0 "
        + str(status).encode()
        + b" Fictional\r\n"
        + (b"Content-Length: " + str(len(body)).encode() + b"\r\n" if length else b"")
        + b"\r\n"
        + body
    )


def exchange(monkeypatch, scenario, store, reply, *, operation="create", on_connect=None):
    api, _, _, release, image = scenario
    client, server = socket.socketpair()
    requests = []

    def serve():
        with server:
            request = b""
            while b"\r\n\r\n" not in request:
                chunk = server.recv(4096)
                if not chunk:
                    return
                request += chunk
            head, body = request.split(b"\r\n\r\n", 1)
            size = int(
                next(
                    line.split(b":", 1)[1]
                    for line in head.split(b"\r\n")
                    if line.startswith(b"Content-Length:")
                )
            )
            while len(body) < size:
                chunk = server.recv(4096)
                if not chunk:
                    return
                body += chunk
            requests.append((head, body))
            with suppress(OSError):
                server.sendall(reply)

    def connection(deadline):
        if on_connect is not None:
            on_connect()
        return client

    worker = threading.Thread(target=serve)
    worker.start()
    monkeypatch.setattr(api, "_connection", connection)
    try:
        transport = api.StockEngineMutator()
        result = (
            transport.create_worker(store, release, image)
            if operation == "create"
            else transport.start_worker(store)
        )
        return result, requests
    finally:
        client.close()
        worker.join(timeout=2)
        assert not worker.is_alive()


def test_create_derives_exact_name_and_policy_body_without_start_or_cid_receipt(
    scenario, monkeypatch
):
    _, root, _, release, image = scenario
    with opened(scenario) as store:
        intent = store.begin(release)
        result, requests = exchange(
            monkeypatch, scenario, store, response(201, encoded({"Id": CID, "Warnings": []}))
        )
        assert result == CID
        assert len(requests) == 1
        head, body = requests[0]
        assert (
            head.split(b"\r\n")[0]
            == (
                "POST /v1.52/containers/create?name=hybrid-stock-research-"
                + intent.attempt_id
                + " HTTP/1.0"
            ).encode()
        )
        assert body == worker_request(release, image, intent.attempt_id)
        assert set(path.name for path in (root / intent.attempt_id).iterdir()) == {
            "intent.json",
            "create.json",
        }
        create = json.loads((root / intent.attempt_id / "create.json").read_bytes())
        assert create["request_sha256"] == hashlib.sha256(body).hexdigest()


def test_start_derives_issued_fence_and_does_not_claim_completion(scenario, monkeypatch):
    _, root, _, release, _ = scenario
    with opened(scenario) as store:
        intent = store.begin(release)
        prepare_dispatch(store, release)
        store.record_created(verified(intent))
        fence, requests = exchange(monkeypatch, scenario, store, response(204), operation="start")
        assert fence.container_id == CID and fence.attempt_id == intent.attempt_id
        assert (
            requests[0][0].split(b"\r\n")[0]
            == ("POST /v1.52/containers/" + CID + "/start HTTP/1.0").encode()
        )
        assert requests[0][1] == b""
        assert (root / intent.attempt_id / "start.json").is_file()
        assert not (root / intent.attempt_id / "stopped.json").exists()


@pytest.mark.parametrize("operation", ["create", "start"])
@pytest.mark.parametrize("accepted", [False, True])
def test_dispatch_is_one_use_across_transport_objects_even_after_lost_ack(
    scenario, monkeypatch, operation, accepted
):
    api, _, _, release, image = scenario
    with opened(scenario) as store:
        intent = store.begin(release)
        if operation == "start":
            prepare_dispatch(store, release)
            store.record_created(verified(intent))
        reply = (
            (
                response(201, encoded({"Id": CID, "Warnings": None}))
                if operation == "create"
                else response(204)
            )
            if accepted
            else b"truncated"
        )
        if accepted:
            exchange(monkeypatch, scenario, store, reply, operation=operation)
        else:
            with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$"):
                exchange(monkeypatch, scenario, store, reply, operation=operation)
        monkeypatch.setattr(api, "_connection", lambda deadline: pytest.fail("Dispatch replayed"))
        with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$"):
            other = api.StockEngineMutator()
            if operation == "create":
                other.create_worker(store, release, image)
            else:
                other.start_worker(store)


@pytest.mark.parametrize(
    "reply",
    [
        response(200, b"{}"),
        response(204),
        response(304),
        response(404, b"private"),
        response(500, b"private"),
        response(201, b"{}"),
        response(201, encoded({"Id": CID, "Warnings": ["private"]})),
        b"HTTP/1.0 201 OK\r\nContent-Length: 3\r\n\r\n{}",
        b"HTTP/1.0 201 OK\r\nContent-Length: 1048577\r\n\r\n",
        b"HTTP/1.0 201 OK\r\nContent-Length: 2\r\ncontent-length: 2\r\n\r\n{}",
        b"HTTP/1.0 201 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
        b"HTTP/2 201 OK\r\nContent-Length: 2\r\n\r\n{}",
    ],
)
def test_unverified_create_responses_are_sanitized_and_do_not_record_cid(
    scenario, monkeypatch, reply
):
    _, root, _, release, _ = scenario
    with opened(scenario) as store:
        intent = store.begin(release)
        with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$") as error:
            exchange(monkeypatch, scenario, store, reply)
        assert error.value.__cause__ is None
        assert not (root / intent.attempt_id / "created.json").exists()


@pytest.mark.parametrize(
    "reply",
    [
        response(304),
        response(201),
        response(204, b" "),
        b"HTTP/1.0 204 OK\r\nContent-Length: 0\r\n\r\nx",
    ],
)
def test_start_requires_fresh_204_and_empty_response(scenario, monkeypatch, reply):
    _, _, _, release, _ = scenario
    with opened(scenario) as store:
        intent = store.begin(release)
        prepare_dispatch(store, release)
        store.record_created(verified(intent))
        with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$"):
            exchange(monkeypatch, scenario, store, reply, operation="start")


def test_connection_delay_cannot_extend_fence_or_send_expired_start(scenario, monkeypatch):
    _, _, clock, release, _ = scenario
    with opened(scenario) as store:
        intent = store.begin(release)
        prepare_dispatch(store, release)
        store.record_created(verified(intent))

        def expire():
            clock["monotonic_ns"] += 450000000000

        with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$"):
            exchange(
                monkeypatch, scenario, store, response(204), operation="start", on_connect=expire
            )


def test_wrong_release_is_blocked_before_connection_and_burns_create(scenario, monkeypatch):
    api, _, _, release, image = scenario
    with opened(scenario) as store:
        store.begin(release)
        monkeypatch.setattr(api, "_connection", lambda deadline: pytest.fail("Socket opened"))
        with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$"):
            api.StockEngineMutator().create_worker(
                store, replace(release, config_hash="a" * 64), image
            )
        with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$"):
            api.StockEngineMutator().create_worker(store, release, image)


@pytest.mark.parametrize("operation", ["create", "start"])
def test_connect_and_partial_send_errors_never_refund_the_dispatch(
    scenario, monkeypatch, operation
):
    api, _, _, release, image = scenario
    calls = []

    class PartialPeer:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def settimeout(self, seconds):
            assert 0 < seconds <= 5

        def sendall(self, body):
            calls.append(body[:12])
            raise TimeoutError("fictional private diagnostic")

    with opened(scenario) as store:
        intent = store.begin(release)
        if operation == "start":
            prepare_dispatch(store, release)
            store.record_created(verified(intent))
        monkeypatch.setattr(api, "_connection", lambda deadline: PartialPeer())
        for _ in range(2):
            with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$") as error:
                transport = api.StockEngineMutator()
                if operation == "create":
                    transport.create_worker(store, release, image)
                else:
                    transport.start_worker(store)
            assert "private" not in str(error.value) and error.value.__cause__ is None
        assert len(calls) == 1


@pytest.mark.parametrize("operation", ["create", "start"])
def test_failed_connection_consumes_permission_without_retry(scenario, monkeypatch, operation):
    api, _, _, release, image = scenario
    calls = []

    def unavailable(deadline):
        calls.append(deadline)
        raise OSError("fictional private connection diagnostic")

    with opened(scenario) as store:
        intent = store.begin(release)
        if operation == "start":
            prepare_dispatch(store, release)
            store.record_created(verified(intent))
        monkeypatch.setattr(api, "_connection", unavailable)
        for _ in range(2):
            with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$"):
                transport = api.StockEngineMutator()
                if operation == "create":
                    transport.create_worker(store, release, image)
                else:
                    transport.start_worker(store)
        assert len(calls) == 1


@pytest.mark.parametrize("stage", ["created", "start"])
def test_failed_receipt_flush_sends_no_start_bytes(scenario, monkeypatch, stage):
    api, _, _, release, _ = scenario
    with opened(scenario) as store:
        intent = store.begin(release)
        monkeypatch.setattr(api, "_connection", lambda deadline: pytest.fail("Socket opened"))
        prepare_dispatch(store, release)
        if stage == "start":
            store.record_created(verified(intent))
        with monkeypatch.context() as scoped:
            scoped.setattr(
                stock_attempts.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("fictional"))
            )
            if stage == "created":
                with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
                    store.record_created(verified(intent))
            else:
                with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$"):
                    api.StockEngineMutator().start_worker(store)
        with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$"):
            api.StockEngineMutator().start_worker(store)


@pytest.mark.parametrize("operation", ["create", "start"])
def test_reopened_and_closed_stores_cannot_dispatch(scenario, monkeypatch, operation):
    api, _, _, release, image = scenario
    monkeypatch.setattr(api, "_connection", lambda deadline: pytest.fail("Socket opened"))
    with opened(scenario) as store:
        intent = store.begin(release)
        if operation == "start":
            prepare_dispatch(store, release)
            store.record_created(verified(intent))
    with opened(scenario) as recovered:
        for candidate in (store, recovered):
            with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$"):
                if operation == "create":
                    api.StockEngineMutator().create_worker(candidate, release, image)
                else:
                    api.StockEngineMutator().start_worker(candidate)


@pytest.mark.parametrize("operation", ["", "/v1.52/containers/create", "start\r\n", None, True])
def test_shared_exchange_has_no_arbitrary_route_seam(scenario, monkeypatch, operation):
    api, _, _, release, _ = scenario
    with opened(scenario) as store:
        store.begin(release)
        monkeypatch.setattr(api, "_connection", lambda deadline: pytest.fail("Socket opened"))
        with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$"):
            api.StockEngineMutator._exchange(operation, store)


def test_start_exchange_rejects_caller_release_or_image_overrides(scenario, monkeypatch):
    api, _, _, release, image = scenario
    with opened(scenario) as store:
        intent = store.begin(release)
        prepare_dispatch(store, release)
        store.record_created(verified(intent))
        monkeypatch.setattr(api, "_connection", lambda deadline: pytest.fail("Socket opened"))
        with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$"):
            api.StockEngineMutator._exchange("start", store, release, image)


@pytest.mark.parametrize("phase", ["create", "start"])
def test_final_namespace_check_blocks_send_after_connection(scenario, monkeypatch, phase):
    api, root, _, release, image = scenario

    class NoSendPeer:
        def __enter__(self):
            (root / "active.json").write_bytes(b"{}\n")
            return self

        def __exit__(self, *_args):
            return False

        def sendall(self, _body):
            pytest.fail("Request sent after namespace drift")

    with opened(scenario) as store:
        intent = store.begin(release)
        if phase == "start":
            prepare_dispatch(store, release)
            store.record_created(verified(intent))
        monkeypatch.setattr(api, "_connection", lambda deadline: NoSendPeer())
        with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$"):
            if phase == "create":
                api.StockEngineMutator().create_worker(store, release, image)
            else:
                api.StockEngineMutator().start_worker(store)


@pytest.mark.parametrize("operation", ["create", "start"])
def test_one_absolute_io_budget_includes_connection_delay(scenario, monkeypatch, operation):
    api, _, _, release, _ = scenario
    monkeypatch.setattr(api, "_IO_SECONDS", 0.01)
    with opened(scenario) as store:
        intent = store.begin(release)
        if operation == "start":
            prepare_dispatch(store, release)
            store.record_created(verified(intent))
        with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$"):
            exchange(
                monkeypatch,
                scenario,
                store,
                response(201, encoded({"Id": CID, "Warnings": []}))
                if operation == "create"
                else response(204),
                operation=operation,
                on_connect=lambda: time.sleep(0.02),
            )


@pytest.mark.parametrize("length", [False, True])
def test_create_close_framing_is_supported(scenario, monkeypatch, length):
    _, _, _, release, _ = scenario
    with opened(scenario) as store:
        store.begin(release)
        result, _ = exchange(
            monkeypatch,
            scenario,
            store,
            response(201, encoded({"Id": CID, "Warnings": None}), length=length),
        )
        assert result == CID


@pytest.mark.parametrize(
    "platform,uid,root,store_uid",
    [
        ("darwin", 0, stock_attempts.OPERATIONS_ROOT, 0),
        ("linux", 1000, stock_attempts.OPERATIONS_ROOT, 0),
        ("linux", 0, Path("/other"), 0),
        ("linux", 0, stock_attempts.OPERATIONS_ROOT, 1000),
    ],
)
def test_public_guard_requires_fixed_linux_root_store(monkeypatch, platform, uid, root, store_uid):
    api = module()
    store = object.__new__(stock_attempts.AttemptStore)
    store._root, store._uid = root, store_uid
    monkeypatch.setattr(api.sys, "platform", platform)
    monkeypatch.setattr(api.os, "geteuid", lambda: uid)
    monkeypatch.setattr(api, "_connection", lambda deadline: pytest.fail("Socket opened"))
    with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$"):
        api.StockEngineMutator().start_worker(store)


def test_public_guard_does_not_treat_root_path_fields_as_owned_store_authority(monkeypatch):
    api = module()
    store = object.__new__(stock_attempts.AttemptStore)
    store._root, store._uid = stock_attempts.OPERATIONS_ROOT, 0
    monkeypatch.setattr(api.sys, "platform", "linux")
    monkeypatch.setattr(api.os, "geteuid", lambda: 0)
    monkeypatch.setattr(api, "_connection", lambda deadline: pytest.fail("Socket opened"))
    with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$"):
        api.StockEngineMutator().start_worker(store)


def test_public_guard_rejects_an_arbitrary_store_object_before_connection(monkeypatch):
    api = module()
    monkeypatch.setattr(api, "_connection", lambda deadline: pytest.fail("Socket opened"))
    with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$"):
        api.StockEngineMutator().start_worker(object())


@pytest.mark.parametrize("field", ["release", "image"])
def test_missing_create_inputs_cannot_dispatch(scenario, monkeypatch, field):
    api, _, _, release, image = scenario
    with opened(scenario) as store:
        store.begin(release)
        monkeypatch.setattr(api, "_connection", lambda deadline: pytest.fail("Socket opened"))
        with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$"):
            api.StockEngineMutator().create_worker(
                store,
                None if field == "release" else release,
                None if field == "image" else image,
            )


@pytest.mark.parametrize("operation", ["create", "start"])
def test_extra_response_bytes_in_a_later_read_deny_acknowledgement(
    scenario, monkeypatch, operation
):
    api, _, _, release, image = scenario
    if operation == "create":
        body = encoded({"Id": CID, "Warnings": []})
        chunks = [response(201, body), b"x", b""]
    else:
        chunks = [response(204), b"x", b""]

    class SegmentedPeer:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def settimeout(self, seconds):
            assert seconds > 0

        def sendall(self, body):
            assert body.startswith(b"POST ")

        def recv(self, size):
            chunk = chunks.pop(0)
            assert len(chunk) <= size
            return chunk

    with opened(scenario) as store:
        intent = store.begin(release)
        if operation == "start":
            prepare_dispatch(store, release)
            store.record_created(verified(intent))
        monkeypatch.setattr(api, "_connection", lambda deadline: SegmentedPeer())
        with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$"):
            transport = api.StockEngineMutator()
            if operation == "create":
                transport.create_worker(store, release, image)
            else:
                transport.start_worker(store)


def test_slow_response_cannot_renew_the_absolute_io_budget(scenario, monkeypatch):
    api, _, _, release, image = scenario
    tick = {"now": 1000.0}
    received = []
    chunks = [b"HTTP/1.0 201 OK\r\nContent-Length: 2\r\n\r\n", b"{}"]

    class SlowPeer:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def settimeout(self, seconds):
            assert 0 < seconds <= 5

        def sendall(self, body):
            received.append(body)

        def recv(self, size):
            tick["now"] += 3
            return chunks.pop(0)

    with opened(scenario) as store:
        with monkeypatch.context() as scoped:
            scoped.setattr(api.time, "monotonic", lambda: tick["now"])
            scoped.setattr(
                stock_attempts,
                "_clock",
                lambda: {
                    "boot_id": BOOT,
                    "utc": "2026-10-21T21:00:00+00:00",
                    "monotonic_ns": int(tick["now"] * 1000000000),
                },
            )
            store.begin(release)
            scoped.setattr(api, "_connection", lambda deadline: SlowPeer())
            with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$"):
                api.StockEngineMutator().create_worker(store, release, image)
        assert len(received) == 1 and tick["now"] == 1006


def test_create_fence_is_acknowledged_before_connecting_or_sending(scenario, monkeypatch):
    _, root, _, release, image = scenario
    with opened(scenario) as store:
        attempt = store.begin(release)

        def require_fence():
            path = root / attempt.attempt_id / "create.json"
            assert path.exists(), "Transport must durably fence CREATE before socket acquisition"
            value = json.loads(path.read_bytes())
            expected_body = worker_request(release, image, attempt.attempt_id)
            assert value["request_sha256"] == hashlib.sha256(expected_body).hexdigest()

        result, requests = exchange(
            monkeypatch,
            scenario,
            store,
            response(201, encoded({"Id": CID, "Warnings": []})),
            on_connect=require_fence,
        )
        assert result == CID and len(requests) == 1


def test_create_fence_flush_failure_sends_no_request(scenario, monkeypatch):
    api, _, _, release, image = scenario
    with opened(scenario) as store:
        store.begin(release)
        monkeypatch.setattr(api, "_connection", lambda deadline: pytest.fail("Socket opened"))
        monkeypatch.setattr(
            stock_attempts.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("fictional"))
        )
        with pytest.raises(ValueError, match=r"^stock_engine_mutation_unavailable$"):
            api.StockEngineMutator().create_worker(store, release, image)
