"""Actual scoped transport code with socketpairs; no daemon or provider access."""

import importlib
import json
import socket
import threading
import time
from contextlib import suppress
from pathlib import Path

import pytest
from test_stock_engine_mutation import response
from test_stock_prestart import CID, IMAGE, encoded
from test_stock_probe_admission import admitted, created, opened, prestart
from test_stock_probe_admission import scenario as admission_scenario
from test_stock_probe_history import make_probe


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    value = admission_scenario.__wrapped__(tmp_path, monkeypatch)
    initial = time.monotonic_ns()
    value[2]["monotonic_ns"] = initial
    monkeypatch.setattr(
        value[0],
        "_clock",
        lambda: {
            **value[2],
            "monotonic_ns": time.monotonic_ns() + value[2]["monotonic_ns"] - initial,
        },
    )
    return value


def module():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_probe_engine.py"
    assert path.is_file(), "Fixed inert probe Engine transport is missing"
    return importlib.import_module("infra.hybrid.stock_probe_engine")


class Wire:
    def __init__(self, replies, on_connect=None):
        self.replies = list(replies)
        self.on_connect = on_connect
        self.requests = []
        self.threads = []

    def connect(self, deadline):
        assert self.replies, "Unexpected transport retry"
        if self.on_connect is not None:
            self.on_connect(len(self.threads))
        client, server = socket.socketpair()
        reply = self.replies.pop(0)

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
                    chunk = server.recv(4096)
                    if not chunk:
                        return
                    body += chunk
                self.requests.append((head, body))
                with suppress(OSError):
                    server.sendall(reply)

        thread = threading.Thread(target=serve)
        self.threads.append(thread)
        thread.start()
        return client

    def install(self, monkeypatch, api):
        monkeypatch.setattr(api, "_connection", self.connect)
        monkeypatch.setattr(api, "_production_store", lambda store: None)
        return self

    def join(self):
        for thread in self.threads:
            thread.join(timeout=2)
            assert not thread.is_alive()


def test_actual_metadata_reads_precede_durable_intent_and_create_is_fixed(scenario, monkeypatch):
    api = module()
    _, root, _, engine, image = scenario
    wire = Wire(
        [
            response(200, engine),
            response(200, image),
            response(201, encoded({"Id": CID, "Warnings": []})),
        ]
    )
    wire.install(monkeypatch, api)
    with opened(scenario) as store:
        transport = api.StockProbeEngine()
        snapshot = transport.begin_probe(store, IMAGE)
        assert (root / snapshot.probe_id / "engine.bin").read_bytes() == engine
        assert transport.create_probe(store) == CID
        assert store.snapshot().container_id == CID
        assert wire.requests[0][0].split(b"\r\n")[0] == b"GET /version HTTP/1.0"
        assert (
            wire.requests[1][0].split(b"\r\n")[0]
            == ("GET /v1.52/images/" + IMAGE + "/json HTTP/1.0").encode()
        )
        assert (
            wire.requests[2][0].split(b"\r\n")[0]
            == (
                "POST /v1.52/containers/create?name=hybrid-stock-probe-"
                + snapshot.probe_id
                + " HTTP/1.0"
            ).encode()
        )
        assert wire.requests[2][1] == (root / snapshot.probe_id / "request.bin").read_bytes()
        assert json.loads(wire.requests[2][1])["NetworkDisabled"] is True
        with pytest.raises(ValueError):
            transport.create_probe(store)
    wire.join()


def test_strict_actual_prestart_then_single_start(scenario, monkeypatch):
    api = module()
    with opened(scenario) as store:
        _, snapshot, _ = created(store, scenario)
        wire = Wire([response(200, prestart(snapshot)), response(204)]).install(monkeypatch, api)
        transport = api.StockProbeEngine()
        observation = transport.verify_created(store)
        assert observation.container_id == CID
        fence = transport.start_probe(store)
        assert (
            fence.container_id == CID and store.snapshot().run_deadline_ns == fence.run_deadline_ns
        )
        assert [head.split(b"\r\n")[0] for head, _ in wire.requests] == [
            ("GET /v1.52/containers/" + CID + "/json HTTP/1.0").encode(),
            ("POST /v1.52/containers/" + CID + "/start HTTP/1.0").encode(),
        ]
        with pytest.raises(ValueError):
            transport.start_probe(store)
        with pytest.raises(ValueError):
            transport.verify_created(store)
        wire.join()


@pytest.mark.parametrize(
    "reply",
    [
        response(500, b"private fictional daemon error"),
        response(201, encoded({"Id": "f" * 12, "Warnings": []})),
        response(201, encoded({"Id": CID, "Warnings": []})) + b"x",
        b"HTTP/1.0 201 Created\r\nContent-Length: 100\r\n\r\n{}",
        b"HTTP/1.0 201 Created\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
        b"HTTP/1.0 201 Created\r\nContent-Length: 2\r\nContent-Length: 2\r\n\r\n{}",
        response(201, b"x" * 4097),
    ],
)
def test_uncertain_or_rejected_create_retains_fence_without_retry_or_cid(
    scenario, monkeypatch, reply
):
    api = module()
    _, root, *_ = scenario
    with opened(scenario) as store:
        _, snapshot = admitted(store, scenario)
        wire = Wire([reply]).install(monkeypatch, api)
        transport = api.StockProbeEngine()
        with pytest.raises(ValueError, match=r"^stock_probe_engine_unavailable$") as error:
            transport.create_probe(store)
        assert "private" not in str(error.value) and error.value.__cause__ is None
        assert (root / snapshot.probe_id / "create.json").exists()
        assert not (root / snapshot.probe_id / "cid.json").exists()
        with pytest.raises(ValueError):
            api.StockProbeEngine().create_probe(store)
        wire.join()
        assert len(wire.requests) == 1


@pytest.mark.parametrize("reply", [response(500, b"error"), response(204) + b"x", b""])
def test_lost_start_ack_preserves_original_run_and_cannot_retry(scenario, monkeypatch, reply):
    api = module()
    with opened(scenario) as store:
        _, snapshot, _ = created(store, scenario)
        store.record_created(prestart(snapshot))
        wire = Wire([reply]).install(monkeypatch, api)
        with pytest.raises(ValueError):
            api.StockProbeEngine().start_probe(store)
        original = store.snapshot().run_deadline_ns
        assert original is not None
        with pytest.raises(ValueError):
            api.StockProbeEngine().start_probe(store)
        assert store.snapshot().run_deadline_ns == original
        wire.join()
        assert len(wire.requests) == 1


@pytest.mark.parametrize("wrong", ["name", "network", "started"])
def test_non_strict_prestart_cannot_produce_start(scenario, monkeypatch, wrong):
    api = module()
    with opened(scenario) as store:
        _, snapshot, _ = created(store, scenario)
        value = json.loads(prestart(snapshot))
        if wrong == "name":
            value["Name"] = "/unowned"
        elif wrong == "network":
            value["HostConfig"]["NetworkMode"] = "bridge"
        else:
            value["State"]["StartedAt"] = "2026-10-21T21:00:00Z"
        wire = Wire([response(200, encoded(value))]).install(monkeypatch, api)
        transport = api.StockProbeEngine()
        with pytest.raises(ValueError):
            transport.verify_created(store)
        with pytest.raises(ValueError):
            transport.start_probe(store)
        wire.join()
        assert len(wire.requests) == 1


@pytest.mark.parametrize("change", ["shutdown", "deadline"])
def test_create_rechecks_original_cap_and_shutdown_before_wire(scenario, monkeypatch, change):
    api = module()
    _, _, clock, *_ = scenario
    shutdown = [False]
    with opened(scenario) as store:
        admitted(store, scenario)

        def changed(_index):
            if change == "shutdown":
                shutdown[0] = True
            else:
                clock["monotonic_ns"] += 20000000000

        wire = Wire([response(201, encoded({"Id": CID, "Warnings": []}))], changed).install(
            monkeypatch, api
        )
        with pytest.raises(ValueError):
            api.StockProbeEngine().create_probe(store, shutdown=shutdown)
        wire.join()
        assert wire.requests == []
        with pytest.raises(ValueError):
            api.StockProbeEngine().create_probe(store)


@pytest.mark.parametrize("message", [None, "page not found", "No such container: wrong", "correct"])
def test_closed_entry_needs_exact_complete_full_cid_absence(scenario, monkeypatch, message):
    api = module()
    _, root, clock, engine, image = scenario
    previous = make_probe(root)
    clock["monotonic_ns"] = max(
        clock["monotonic_ns"], previous["values"]["closed"]["monotonic_ns"] + 1
    )
    cid = previous["values"]["cid"]["container_id"]
    body = encoded({"message": "No such container: " + cid if message == "correct" else message})
    wire = Wire([response(200, engine), response(200, image), response(404, body)])
    wire.install(monkeypatch, api)
    with opened(scenario) as store:
        transport = api.StockProbeEngine()
        if message == "correct":
            snapshot = transport.begin_probe(store, IMAGE)
            assert snapshot.probe_id != previous["probe_id"]
        else:
            with pytest.raises(ValueError):
                transport.begin_probe(store, IMAGE)
            assert store.snapshot().probe_id == previous["probe_id"]
        wire.join()
        assert (
            wire.requests[2][0].split(b"\r\n")[0]
            == ("GET /v1.52/containers/" + cid + "/json HTTP/1.0").encode()
        )


def test_public_transport_has_no_route_body_cid_socket_or_user_override(scenario):
    api = module()
    with opened(scenario) as store:
        for name in ("path", "body", "container_id", "socket", "uid", "not_after_ns"):
            with pytest.raises(TypeError):
                api.StockProbeEngine().create_probe(store, **{name: "untrusted"})
        with pytest.raises(ValueError):
            api._production_store(store)


def logs_reply(body, *, content_type="application/vnd.docker.multiplexed-stream", length=True):
    raw = response(200, body, length=length)
    if content_type is not None:
        raw = raw.replace(
            b"\r\n\r\n", b"\r\nContent-Type: " + content_type.encode() + b"\r\n\r\n", 1
        )
    return raw


def test_finite_logs_route_retains_entire_original_body(scenario, monkeypatch):
    from test_stock_probe_output import document, frame
    from test_stock_probe_terminal import natural

    api = module()
    _, root, *_ = scenario
    with opened(scenario) as store:
        snapshot, _ = natural(store, scenario)
        raw = frame(document())
        wire = Wire([logs_reply(raw, length=False)]).install(monkeypatch, api)
        assert api.StockProbeEngine().collect_output(store) == "valid"
        wire.join()
        assert (
            wire.requests[0][0].split(b"\r\n")[0]
            == (
                "GET /v1.52/containers/"
                + CID
                + "/logs?stdout=true&stderr=true&follow=false&timestamps=false"
                "&tail=all&details=false HTTP/1.0"
            ).encode()
        )
        assert (root / snapshot.probe_id / "framed-logs.bin").read_bytes() == raw


@pytest.mark.parametrize("mode", ["empty", "stderr", "truncated_frame"])
def test_complete_invalid_logs_are_diagnostics_not_success(scenario, monkeypatch, mode):
    from test_stock_probe_output import document, frame
    from test_stock_probe_terminal import natural

    api = module()
    with opened(scenario) as store:
        natural(store, scenario)
        raw = {
            "empty": b"",
            "stderr": frame(document()) + frame(b"error", 2),
            "truncated_frame": frame(document()) + b"x",
        }[mode]
        wire = Wire([logs_reply(raw)]).install(monkeypatch, api)
        assert api.StockProbeEngine().collect_output(store) == "invalid"
        wire.join()
        assert store.snapshot().output_status == "invalid"


@pytest.mark.parametrize("mode", ["ctype", "no_ctype", "too_large", "short", "extra", "headers"])
def test_incomplete_or_invalid_http_logs_never_become_output_receipt(scenario, monkeypatch, mode):
    from test_stock_probe_output import document, frame
    from test_stock_probe_terminal import natural

    api = module()
    _, root, *_ = scenario
    with opened(scenario) as store:
        snapshot, _ = natural(store, scenario)
        raw = frame(document())
        reply = logs_reply(raw)
        if mode == "ctype":
            reply = logs_reply(raw, content_type="application/json")
        elif mode == "no_ctype":
            reply = logs_reply(raw, content_type=None)
        elif mode == "too_large":
            reply = logs_reply(b"x" * 16385)
        elif mode == "short":
            reply = logs_reply(raw)[:-1]
        elif mode == "extra":
            reply += b"x"
        else:
            reply = b"HTTP/1.0 200 OK\r\nX-Long: " + b"x" * 8192
        wire = Wire([reply]).install(monkeypatch, api)
        transport = api.StockProbeEngine()
        with pytest.raises(ValueError):
            transport.collect_output(store)
        with pytest.raises(ValueError):
            transport.collect_output(store)
        wire.join()
        assert len(wire.requests) == 1
        assert not (root / snapshot.probe_id / "output.json").exists()


@pytest.mark.parametrize("missing", [True, False])
def test_actual_retirement_scoped_404_or_fresh_nonforce_delete(scenario, monkeypatch, missing):
    from test_stock_probe_terminal import natural, output

    api = module()
    _, root, *_ = scenario
    with opened(scenario) as store:
        snapshot, raw = natural(store, scenario)
        output(store)
        replies = (
            [response(404, encoded({"message": "No such container: " + CID}))]
            if missing
            else [response(200, raw), response(204)]
        )
        wire = Wire(replies).install(monkeypatch, api)
        api.StockProbeEngine().retire_probe(store)
        wire.join()
        assert len(wire.requests) == (1 if missing else 2)
        if not missing:
            assert (
                wire.requests[1][0].split(b"\r\n")[0]
                == (
                    "DELETE /v1.52/containers/" + CID + "?force=false&v=false&link=false HTTP/1.0"
                ).encode()
            )
        assert (root / snapshot.probe_id / "removed.json").exists()
        assert json.loads(store.close_success())["live_enabled"] is False


@pytest.mark.parametrize(
    "mode", ["generic404", "wrong404", "running", "changed_lifetime", "204extra"]
)
def test_unresolved_retirement_never_acknowledges_removal(scenario, monkeypatch, mode):
    from test_stock_probe_cleanup import running
    from test_stock_probe_terminal import natural, output

    api = module()
    with opened(scenario) as store:
        snapshot, raw = natural(store, scenario)
        output(store)
        if mode.endswith("404"):
            message = "No such container: wrong" if mode == "wrong404" else "not found"
            replies = [response(404, encoded({"message": message}))]
        elif mode == "running":
            replies = [response(200, encoded(running(snapshot)))]
        elif mode == "changed_lifetime":
            value = json.loads(raw)
            value["State"]["FinishedAt"] = "2026-10-21T21:00:02Z"
            replies = [response(200, encoded(value))]
        else:
            replies = [response(200, raw), response(204) + b"x"]
        wire = Wire(replies).install(monkeypatch, api)
        with pytest.raises(ValueError):
            api.StockProbeEngine().retire_probe(store)
        with pytest.raises(ValueError):
            api.StockProbeEngine().retire_probe(store)
        wire.join()
        assert store._removed_ack is None


@pytest.mark.parametrize("mode", ["running", "stopped", "bad_identity"])
def test_signal_uses_fresh_owned_running_get_then_one_post(scenario, monkeypatch, mode):
    from test_stock_probe_cleanup import cleanup, running, started, stopped

    api = module()
    with opened(scenario) as store:
        snapshot = started(store, scenario)
        token = cleanup(store)
        value = stopped(snapshot) if mode == "stopped" else running(snapshot)
        if mode == "bad_identity":
            value["Name"] = "/unowned"
        replies = [response(200, encoded(value))] + ([response(204)] if mode == "running" else [])
        wire = Wire(replies).install(monkeypatch, api)
        if mode == "running":
            api.StockProbeEngine().signal_probe(store, token, "TERM")
            assert store.snapshot().stopped is None
            assert (
                wire.requests[1][0].split(b"\r\n")[0]
                == ("POST /v1.52/containers/" + CID + "/kill?signal=TERM HTTP/1.0").encode()
            )
        else:
            with pytest.raises(ValueError):
                api.StockProbeEngine().signal_probe(store, token, "TERM")
        with pytest.raises(ValueError):
            api.StockProbeEngine().signal_probe(store, token, "TERM")
        wire.join()
        assert len(wire.requests) == (2 if mode == "running" else 1)


@pytest.mark.parametrize("status", [200, 404])
def test_recovery_name_discovery_is_cleanup_only_and_name_absence_unresolved(
    scenario, monkeypatch, status
):
    from test_stock_probe_cleanup import cleanup, stopped

    api = module()
    with opened(scenario) as store:
        _, snapshot = admitted(store, scenario)
        store.prepare_create()
    with opened(scenario) as recovered:
        token = cleanup(recovered)
        raw = (
            encoded(stopped(snapshot, "created"))
            if status == 200
            else encoded({"message": "No such container: hybrid-stock-probe-" + snapshot.probe_id})
        )
        wire = Wire([response(status, raw)]).install(monkeypatch, api)
        if status == 200:
            assert api.StockProbeEngine().discover_probe(recovered, token) == CID
            assert recovered.snapshot().container_id == CID
            with pytest.raises(ValueError):
                api.StockProbeEngine().start_probe(recovered)
        else:
            with pytest.raises(ValueError):
                api.StockProbeEngine().discover_probe(recovered, token)
            assert recovered.snapshot().container_id is None
        wire.join()


def test_actual_run_poll_preserves_native_owned_bytes_and_original_run(scenario, monkeypatch):
    from test_stock_probe_cleanup import running, started

    api = module()
    with opened(scenario) as store:
        snapshot = started(store, scenario)
        raw = encoded(running(snapshot))
        original = store.snapshot().run_deadline_ns
        wire = Wire([response(200, raw)]).install(monkeypatch, api)
        assert api.StockProbeEngine().inspect_probe(store) == raw
        assert store.snapshot().run_deadline_ns == original and store.snapshot().stopped is None
        wire.join()


def test_signal_inspection_and_post_cannot_renew_five_second_budget(scenario, monkeypatch):
    from test_stock_probe_cleanup import cleanup, running, started

    api = module()
    original = api._deadline
    with opened(scenario) as store:
        snapshot = started(store, scenario)
        token = cleanup(store)
        calls = []

        def earlier_cap(not_after_ns):
            result = original(not_after_ns)
            if not calls:
                result = min(result, time.monotonic() + 0.04)
            calls.append((not_after_ns, result))
            return result

        def delayed_second_connection(index):
            if index == 1:
                time.sleep(0.06)

        wire = Wire(
            [response(200, encoded(running(snapshot))), response(204)], delayed_second_connection
        ).install(monkeypatch, api)
        monkeypatch.setattr(api, "_deadline", earlier_cap)
        with pytest.raises(ValueError):
            api.StockProbeEngine().signal_probe(store, token, "TERM")
        wire.join()
        assert len(wire.requests) == 1 and len(calls) >= 2
        assert all(value[0] <= int(calls[0][1] * 1000000000) for value in calls[1:])
        assert store.snapshot().stopped is None


@pytest.mark.parametrize("kind", ["timeout", "disconnect"])
def test_create_connection_failure_never_retries_or_records_cid(scenario, monkeypatch, kind):
    api = module()
    calls = []

    def failed(deadline):
        calls.append(deadline)
        if kind == "timeout":
            raise TimeoutError("private fictional timeout")
        raise OSError("private fictional disconnect")

    monkeypatch.setattr(api, "_production_store", lambda store: None)
    monkeypatch.setattr(api, "_connection", failed)
    with opened(scenario) as store:
        admitted(store, scenario)
        with pytest.raises(ValueError):
            api.StockProbeEngine().create_probe(store)
        with pytest.raises(ValueError):
            api.StockProbeEngine().create_probe(store)
        assert len(calls) == 1 and store.snapshot().container_id is None


@pytest.mark.parametrize("mode", ["bad_version", "bad_image", "no_length", "large_image"])
def test_metadata_response_bounds_and_original_byte_retention(scenario, monkeypatch, mode):
    api = module()
    _, root, _, engine, image = scenario
    if mode == "bad_version":
        engine = b"{}"
    elif mode == "bad_image":
        image = b"{}"
    elif mode == "large_image":
        value = json.loads(image)
        value["Comment"] = "x" * 100000
        image = encoded(value)
    wire = Wire(
        [
            response(200, engine, length=mode != "no_length"),
            response(200, image, length=mode != "no_length"),
        ]
    ).install(monkeypatch, api)
    with opened(scenario) as store:
        if mode.startswith("bad"):
            with pytest.raises(ValueError):
                api.StockProbeEngine().begin_probe(store, IMAGE)
            assert store.snapshot() is None
        else:
            snapshot = api.StockProbeEngine().begin_probe(store, IMAGE)
            assert (root / snapshot.probe_id / "image.bin").read_bytes() == image
        wire.join()


@pytest.mark.parametrize("kind", ["boot", "shutdown"])
def test_start_rechecks_shutdown_and_clock_before_wire(scenario, monkeypatch, kind):
    api = module()
    _, _, clock, *_ = scenario
    shutdown = [False]
    with opened(scenario) as store:
        _, snapshot, _ = created(store, scenario)
        store.record_created(prestart(snapshot))

        def changed(_):
            if kind == "boot":
                clock["boot_id"] = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
            else:
                shutdown[0] = True

        wire = Wire([response(204)], changed).install(monkeypatch, api)
        with pytest.raises(ValueError):
            api.StockProbeEngine().start_probe(store, shutdown=shutdown)
        wire.join()
        assert not wire.requests and store.snapshot().run_deadline_ns is not None
        with pytest.raises(ValueError):
            api.StockProbeEngine().start_probe(store)


def test_expired_run_poll_has_no_native_exchange(scenario, monkeypatch):
    from test_stock_probe_cleanup import started

    api = module()
    _, _, clock, *_ = scenario
    wire = Wire([]).install(monkeypatch, api)
    with opened(scenario) as store:
        started(store, scenario)
        clock["monotonic_ns"] += 30000000000
        with pytest.raises(ValueError):
            api.StockProbeEngine().inspect_probe(store)
        assert not wire.requests and not wire.threads


def test_fixed_root_uid_and_type_guard_before_any_native_operation(scenario, monkeypatch):
    api = module()
    with opened(scenario) as store:
        with pytest.raises(ValueError):
            api._production_store(None)
        monkeypatch.setattr(api.sys, "platform", "linux")
        monkeypatch.setattr(api.os, "geteuid", lambda: 0)
        with pytest.raises(ValueError):
            api._production_store(store)
        monkeypatch.setattr(store, "_root", api.PROBES_ROOT)
        monkeypatch.setattr(store, "_uid", 0)
        guarded = []
        monkeypatch.setattr(store, "_guard", lambda: guarded.append(True))
        api._production_store(store)
        assert guarded == [True]


@pytest.mark.parametrize("stage", ["setup", "admitted"])
def test_prestart_or_poll_without_retained_cid_performs_no_exchange(scenario, monkeypatch, stage):
    api = module()
    wire = Wire([]).install(monkeypatch, api)
    with opened(scenario) as store:
        if stage == "setup":
            store.begin_setup(IMAGE)
        else:
            admitted(store, scenario)
        with pytest.raises(ValueError):
            api.StockProbeEngine().verify_created(store)
        with pytest.raises(ValueError):
            api.StockProbeEngine().inspect_probe(store)
        assert not wire.threads


def test_cleanup_poll_returns_exact_owned_stopped_bytes(scenario, monkeypatch):
    from test_stock_probe_cleanup import cleanup, started, stopped

    api = module()
    with opened(scenario) as store:
        snapshot = started(store, scenario)
    with opened(scenario) as recovered:
        token = cleanup(recovered)
        raw = encoded(stopped(snapshot))
        wire = Wire([response(200, raw)]).install(monkeypatch, api)
        assert api.StockProbeEngine().inspect_probe(recovered, cleanup=token) == raw
        recovered.record_stopped(raw, cleanup=token)
        assert recovered.snapshot().stopped.status == "exited"
        wire.join()


def test_large_close_framed_metadata_is_bounded_and_fully_read(scenario, monkeypatch):
    api = module()
    _, root, _, engine, image = scenario
    value = json.loads(image)
    value["Comment"] = "x" * 100000
    image = encoded(value)
    wire = Wire([response(200, engine), response(200, image, length=False)])
    wire.install(monkeypatch, api)
    with opened(scenario) as store:
        snapshot = api.StockProbeEngine().begin_probe(store, IMAGE)
        assert (root / snapshot.probe_id / "image.bin").read_bytes() == image
        wire.join()


def test_malformed_http_status_cannot_acknowledge_create(scenario, monkeypatch):
    api = module()
    with opened(scenario) as store:
        admitted(store, scenario)
        wire = Wire([b"HTTP/2 201 Created\r\n\r\n{}"]).install(monkeypatch, api)
        with pytest.raises(ValueError):
            api.StockProbeEngine().create_probe(store)
        wire.join()
        assert store.snapshot().container_id is None


def test_partial_create_send_is_uncertain_and_never_retried(scenario, monkeypatch):
    api = module()
    wire = Wire([response(201, encoded({"Id": CID, "Warnings": []}))])
    wire.install(monkeypatch, api)
    sent = []

    class InterruptedSocket:
        def __init__(self, peer):
            self.peer = peer

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.peer.close()

        def settimeout(self, timeout):
            self.peer.settimeout(timeout)

        def sendall(self, request):
            sent.append(request[: len(request) // 2])
            self.peer.sendall(sent[-1])
            raise OSError("fictional partial-send failure")

    monkeypatch.setattr(
        api, "_connection", lambda deadline: InterruptedSocket(wire.connect(deadline))
    )
    with opened(scenario) as store:
        admitted(store, scenario)
        with pytest.raises(ValueError):
            api.StockProbeEngine().create_probe(store)
        with pytest.raises(ValueError):
            api.StockProbeEngine().create_probe(store)
        wire.join()
        assert len(sent) == 1 and store.snapshot().container_id is None


def test_content_length_without_final_eof_does_not_acknowledge_create(scenario, monkeypatch):
    api = module()
    client, server = socket.socketpair()
    release = threading.Event()
    sent = threading.Event()

    def serve():
        with server:
            request = b""
            while b"\r\n\r\n" not in request:
                request += server.recv(4096)
            server.sendall(response(201, encoded({"Id": CID, "Warnings": []})))
            sent.set()
            release.wait(timeout=1)

    thread = threading.Thread(target=serve)
    monkeypatch.setattr(api, "_production_store", lambda store: None)
    monkeypatch.setattr(api, "_connection", lambda deadline: client)
    original = api._deadline
    monkeypatch.setattr(api, "_deadline", lambda cap: min(original(cap), time.monotonic() + 0.05))
    thread.start()
    try:
        with opened(scenario) as store:
            admitted(store, scenario)
            with pytest.raises(ValueError):
                api.StockProbeEngine().create_probe(store)
            assert sent.is_set() and store.snapshot().container_id is None
            with pytest.raises(ValueError):
                api.StockProbeEngine().create_probe(store)
    finally:
        release.set()
        client.close()
        thread.join(timeout=2)
        assert not thread.is_alive()


@pytest.mark.parametrize("phase", ["TERM", "KILL", "FINAL"])
def test_cleanup_inspection_selects_only_fixed_original_phase_cap(scenario, monkeypatch, phase):
    from test_stock_probe_cleanup import cleanup, running, started

    api = module()
    with opened(scenario) as store:
        target = started(store, scenario)
        token = cleanup(store)
        wire = Wire([response(200, encoded(running(target)))]).install(monkeypatch, api)
        original = api._deadline
        caps = []

        def capture(cap):
            caps.append(cap)
            return original(cap)

        monkeypatch.setattr(api, "_deadline", capture)
        api.StockProbeEngine().inspect_probe(store, cleanup=token, phase=phase)
        expected = {
            "TERM": token.term_deadline_ns,
            "KILL": token.kill_deadline_ns,
            "FINAL": token.final_deadline_ns,
        }[phase]
        assert caps == [expected]
        wire.join()


@pytest.mark.parametrize("phase", ["RUN", "later", "", 123, True])
def test_unknown_or_numeric_cleanup_phase_cannot_extend_any_exchange(scenario, monkeypatch, phase):
    from test_stock_probe_cleanup import cleanup, started

    api = module()
    wire = Wire([]).install(monkeypatch, api)
    with opened(scenario) as store:
        started(store, scenario)
        token = cleanup(store)
        with pytest.raises(ValueError):
            api.StockProbeEngine().inspect_probe(store, cleanup=token, phase=phase)
        assert not wire.threads
