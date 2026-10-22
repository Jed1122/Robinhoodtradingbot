"""Full probe composition with real files/verifiers/transports and fictional daemon sockets."""

import importlib
import json
import signal
import socket
import sys
import threading
from contextlib import contextmanager, suppress
from itertools import pairwise
from pathlib import Path

import pytest
from test_stock_engine_mutation import response
from test_stock_prestart import CID, IMAGE, encoded
from test_stock_probe_admission import prestart
from test_stock_probe_cleanup import running, stopped
from test_stock_probe_engine import logs_reply
from test_stock_probe_engine import scenario as transport_scenario
from test_stock_probe_output import document, frame


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    return transport_scenario.__wrapped__(tmp_path, monkeypatch)


def module():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_probe_controller.py"
    assert path.is_file(), "The fixed inert probe controller is missing"
    return importlib.import_module("infra.hybrid.stock_probe_controller")


class Daemon:
    def __init__(self, scenario):
        self.scenario = scenario
        self.store = None
        self.cid = CID
        self.created = self.started = self.exited = self.gone = False
        self.reads = 0
        self.exit_after = 1
        self.term_exit = True
        self.kill_exit = True
        self.queued = False
        self.lost_create = self.lost_start = self.lost_delete = False
        self.bad_output = False
        self.bad_prestart = False
        self.reject_create = False
        self.fail_reads = 0
        self.exit_facts = {}
        self.on_request = None
        self.requests = []
        self.threads = []
        self.errors = []

    def snapshot(self):
        return self.store.snapshot()

    def reply(self, method, path, body):
        self.requests.append((method, path, self.scenario[0]._clock()["monotonic_ns"]))
        if self.on_request is not None:
            self.on_request(method, path)
        if path == "/version":
            return response(200, self.scenario[3])
        if path.startswith("/v1.52/images/"):
            return response(200, self.scenario[4])
        if path.startswith("/v1.52/containers/create?"):
            assert method == "POST" and json.loads(body)["NetworkDisabled"] is True
            if self.reject_create:
                return response(500, b"private fictional create rejection")
            self.created = True
            return (
                b""
                if self.lost_create
                else response(201, encoded({"Id": self.cid, "Warnings": []}))
            )
        if path.endswith("/start"):
            assert method == "POST" and body == b""
            self.started = True
            return b"" if self.lost_start else response(204)
        if path.endswith("/json"):
            if self.gone or not self.created:
                identifier = path.split("/")[-2]
                return response(404, encoded({"message": "No such container: " + identifier}))
            snapshot = self.snapshot()
            if not self.started or self.queued:
                value = json.loads(prestart(snapshot))
                value["Id"] = self.cid
                value["Config"]["Hostname"] = self.cid[:12]
                if self.bad_prestart:
                    value["HostConfig"]["NetworkMode"] = "bridge"
                return response(200, encoded(value))
            if self.fail_reads:
                self.fail_reads -= 1
                return response(500, b"private fictional unavailable observation")
            self.reads += 1
            if self.exit_after is not None and self.reads > self.exit_after:
                self.exited = True
            value = stopped(snapshot, **self.exit_facts) if self.exited else running(snapshot)
            value["Id"] = self.cid
            return response(200, encoded(value))
        if "/kill?signal=" in path:
            requested = path.split("=")[-1]
            self.exited = self.exited or (self.term_exit if requested == "TERM" else self.kill_exit)
            return response(204)
        if "/logs?" in path:
            return logs_reply(frame(b"{}") if self.bad_output else frame(document()))
        if method == "DELETE":
            assert path.endswith("?force=false&v=false&link=false")
            assert not self.started or self.exited
            self.gone = True
            return b"" if self.lost_delete else response(204)
        raise AssertionError("Unexpected fictional request")

    def connect(self, deadline):
        client, server = socket.socketpair()

        def serve():
            try:
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
                    method, path, _ = head.split(b"\r\n")[0].decode().split(" ")
                    reply = self.reply(method, path, body)
                    with suppress(OSError):
                        server.sendall(reply)
            except BaseException as error:
                self.errors.append(error)

        thread = threading.Thread(target=serve)
        self.threads.append(thread)
        thread.start()
        return client

    def install(self, monkeypatch, api):
        from infra.hybrid import stock_probe_engine

        @contextmanager
        def namespace():
            from test_stock_probe_admission import opened

            with opened(self.scenario) as store:
                self.store = store
                yield store

        # Only native filesystem root, socket/peer, wall clock and wait are fictional.
        monkeypatch.setattr(api, "probes", namespace)
        monkeypatch.setattr(stock_probe_engine, "_production_store", lambda store: None)
        monkeypatch.setattr(stock_probe_engine, "_connection", self.connect)

        def advance(seconds):
            self.scenario[2]["monotonic_ns"] += max(1, int(seconds * 1e9))

        monkeypatch.setattr(api.time, "sleep", advance)
        return self

    def join(self):
        for thread in self.threads:
            thread.join(timeout=2)
            assert not thread.is_alive()
        assert not self.errors, repr(self.errors)

    def count(self, needle):
        return sum(needle in path for _, path, _ in self.requests)


def request_shutdown():
    handler = signal.getsignal(signal.SIGTERM)
    assert callable(handler), "Controller did not install shutdown before admission"
    handler(signal.SIGTERM, None)


def test_complete_actual_store_transport_composition_publishes_only_after_closed(
    scenario, monkeypatch
):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    result = api.run_probe(IMAGE)
    daemon.join()
    assert (
        result.status == "succeeded" and json.loads(result.configuration)["live_enabled"] is False
    )
    assert daemon.count("/create?") == daemon.count("/start") == daemon.count("/logs?") == 1
    assert sum(method == "DELETE" for method, _, _ in daemon.requests) == 1
    directory = scenario[1] / result.probe_id
    assert json.loads((directory / "closed.json").read_bytes())["outcome"] == "succeeded"
    assert daemon.store._closed and daemon.gone


def test_lost_start_ack_resolves_without_second_start(scenario, monkeypatch):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    daemon.lost_start = True
    result = api.run_probe(IMAGE)
    daemon.join()
    assert result.status == "succeeded" and daemon.count("/start") == 1
    record = json.loads((scenario[1] / result.probe_id / "start.json").read_bytes())
    assert record["run_deadline_ns"] == record["monotonic_ns"] + 30000000000


@pytest.mark.parametrize("at", ["create", "start", "poll", "logs", "delete"])
def test_shutdown_at_native_boundaries_never_publishes_configuration(scenario, monkeypatch, at):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    fired = []

    def shutdown(method, path):
        match = (
            (at == "create" and "/create?" in path)
            or (at == "start" and path.endswith("/start"))
            or (at == "poll" and path.endswith("/json") and daemon.started)
            or (at == "logs" and "/logs?" in path)
            or (at == "delete" and method == "DELETE")
        )
        if match and not fired:
            fired.append(True)
            request_shutdown()

    daemon.on_request = shutdown
    result = api.run_probe(IMAGE)
    daemon.join()
    assert fired and result.status != "succeeded" and result.configuration is None
    assert daemon.count("/create?") == 1 and daemon.count("/start") <= 1
    if at == "create":
        assert daemon.count("/start") == 0


@pytest.mark.parametrize(
    "facts", [{"ExitCode": 7}, {"OOMKilled": True}, {"Error": "private fictional"}]
)
def test_nonclean_actual_exit_closes_failed_without_false_profit_or_success(
    scenario, monkeypatch, facts
):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    daemon.exit_facts = facts
    result = api.run_probe(IMAGE)
    daemon.join()
    assert result.status == "failed" and result.configuration is None and daemon.gone
    closed = (scenario[1] / result.probe_id / "closed.json").read_bytes()
    assert json.loads(closed)["outcome"] == "failed" and b"private" not in closed


def test_complete_invalid_output_closes_failed(scenario, monkeypatch):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    daemon.bad_output = True
    result = api.run_probe(IMAGE)
    daemon.join()
    assert result.status == "failed" and result.configuration is None and daemon.gone
    assert result.reason == "invalid_output"


def test_run_expiry_escalates_once_with_original_caps(scenario, monkeypatch):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    daemon.exit_after, daemon.term_exit = None, False
    result = api.run_probe(IMAGE)
    daemon.join()
    assert result.status == "failed" and result.configuration is None and daemon.gone
    assert daemon.count("signal=TERM") == daemon.count("signal=KILL") == 1
    start = json.loads((scenario[1] / result.probe_id / "start.json").read_bytes())
    times = {path.split("=")[-1]: at for _, path, at in daemon.requests if "/kill?" in path}
    assert times["TERM"] < start["run_deadline_ns"] + 10000000000
    assert (
        start["run_deadline_ns"] + 10000000000
        <= times["KILL"]
        < start["run_deadline_ns"] + 15000000000
    )


def test_queued_start_created_never_becomes_stop_or_delete(scenario, monkeypatch):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    daemon.queued = True
    with pytest.raises(ValueError, match=r"^stock_probe_controller_unavailable$"):
        api.run_probe(IMAGE)
    daemon.join()
    snapshot = daemon.snapshot() if not daemon.store._closed else None
    assert snapshot is None
    assert daemon.count("/start") == 1
    assert not any(method == "DELETE" or "/kill?" in path for method, path, _ in daemon.requests)
    directories = [p for p in scenario[1].iterdir() if p.is_dir()]
    assert len(directories) == 1 and not (directories[0] / "stopped.json").exists()


def test_lost_create_ack_uses_name_lookup_cleanup_and_never_starts(scenario, monkeypatch):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    daemon.lost_create = True
    result = api.run_probe(IMAGE)
    daemon.join()
    assert result.status == "failed" and result.configuration is None and daemon.gone
    assert daemon.count("/create?") == 1 and daemon.count("/start") == 0
    assert any("/containers/hybrid-stock-probe-" in path for _, path, _ in daemon.requests)


def test_lost_delete_ack_waits_for_later_explicit_recovery(scenario, monkeypatch):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    daemon.lost_delete = True
    with pytest.raises(ValueError):
        api.run_probe(IMAGE)
    daemon.join()
    first = len(daemon.requests)
    assert daemon.gone and sum(method == "DELETE" for method, _, _ in daemon.requests) == 1
    result = api.run_probe(IMAGE)
    daemon.join()
    assert result.status == "recovery_only" and result.configuration is None
    assert all(method == "GET" for method, _, _ in daemon.requests[first:])
    assert daemon.count("/create?") == daemon.count("/start") == 1


def test_shutdown_during_terminal_write_suppresses_success_publication(scenario, monkeypatch):
    api = module()
    store_api = scenario[0]
    daemon = Daemon(scenario).install(monkeypatch, api)
    original = store_api._write_new

    def shutdown_after_write(directory, name, *args):
        result = original(directory, name, *args)
        if name == "closed.json":
            request_shutdown()
        return result

    monkeypatch.setattr(store_api, "_write_new", shutdown_after_write)
    with pytest.raises(ValueError):
        api.run_probe(IMAGE)
    daemon.join()
    assert daemon.gone and sum(method == "DELETE" for method, _, _ in daemon.requests) == 1
    directory = next(p for p in scenario[1].iterdir() if p.is_dir())
    assert json.loads((directory / "closed.json").read_bytes())["outcome"] == "succeeded"


def test_cli_is_fixed_and_emits_no_configuration_on_error(scenario, monkeypatch, capsys):
    api = module()
    Daemon(scenario).install(monkeypatch, api)
    for arguments in [[], ["latest"], [IMAGE, "--socket", "/untrusted"], ["--initialize"]]:
        monkeypatch.setattr(sys, "argv", ["probe", *arguments])
        assert api.main() == 1
        captured = capsys.readouterr()
        assert captured.out == "" and json.loads(captured.err)["status"] == "unavailable"


def test_cli_success_emits_owned_result_after_context_closure(scenario, monkeypatch, capsys):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    monkeypatch.setattr(sys, "argv", ["probe", IMAGE])
    assert api.main() == 0
    daemon.join()
    value = json.loads(capsys.readouterr().out)
    assert value["status"] == "succeeded" and value["container_id"] == CID
    assert value["configuration"]["live_enabled"] is False and daemon.store._closed


def test_successor_requires_fresh_absence_and_new_nonreused_cid(scenario, monkeypatch):
    api = module()
    first = Daemon(scenario).install(monkeypatch, api)
    original = api.run_probe(IMAGE)
    first.join()
    second = Daemon(scenario).install(monkeypatch, api)
    second.cid = "e" * 64
    result = api.run_probe(IMAGE)
    second.join()
    assert result.status == "succeeded" and result.probe_id != original.probe_id, (
        result.reason,
        second.requests,
    )
    assert result.container_id == "e" * 64
    request = second.requests[2]
    assert request[:2] == ("GET", "/v1.52/containers/" + CID + "/json")
    assert second.count("/create?") == second.count("/start") == 1


def test_unfinished_no_create_entry_abandons_without_any_native_call(scenario, monkeypatch):
    from test_stock_probe_admission import admitted, opened

    api = module()
    with opened(scenario) as store:
        _, target = admitted(store, scenario)
    daemon = Daemon(scenario).install(monkeypatch, api)
    result = api.run_probe(IMAGE)
    daemon.join()
    assert result.status == "recovery_only" and result.configuration is None
    assert not daemon.requests and result.probe_id == target.probe_id
    value = json.loads((scenario[1] / target.probe_id / "closed.json").read_bytes())
    assert value["outcome"] == "abandoned_before_create"


@pytest.mark.parametrize("new_boot", [False, True])
def test_reopened_old_start_cleanup_never_renews_or_restarts_run(scenario, monkeypatch, new_boot):
    from test_stock_probe_admission import opened
    from test_stock_probe_cleanup import started

    api = module()
    with opened(scenario) as store:
        target = started(store, scenario)
    original = (scenario[1] / target.probe_id / "start.json").read_bytes()
    scenario[2]["monotonic_ns"] += 3600000000000
    if new_boot:
        scenario[2]["boot_id"] = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    daemon = Daemon(scenario).install(monkeypatch, api)
    daemon.created = daemon.started = True
    daemon.exit_after = None
    result = api.run_probe(IMAGE)
    daemon.join()
    assert result.status == "recovery_only" and result.configuration is None and daemon.gone
    assert not daemon.count("/create?") and not daemon.count("/start")
    assert daemon.count("signal=TERM") == 1
    assert (scenario[1] / target.probe_id / "start.json").read_bytes() == original


@pytest.mark.parametrize(
    "slot", ["cid.json", "stopped.json", "output.json", "removed.json", "closed.json"]
)
def test_lost_complete_receipt_ack_never_reconstructs_success(scenario, monkeypatch, slot):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    original = scenario[0]._write_new
    failed = []

    def lost_ack(directory, name, *args):
        result = original(directory, name, *args)
        if name == slot and not failed:
            failed.append(True)
            raise OSError("private fictional lost acknowledgement")
        return result

    monkeypatch.setattr(scenario[0], "_write_new", lost_ack)
    if slot in ("removed.json", "closed.json"):
        with pytest.raises(ValueError):
            api.run_probe(IMAGE)
    else:
        result = api.run_probe(IMAGE)
        assert result.status == "failed" and result.configuration is None
    daemon.join()
    assert failed and daemon.count("/create?") == 1 and daemon.count("/start") <= 1
    assert sum(method == "DELETE" for method, _, _ in daemon.requests) == 1
    if slot == "output.json":
        assert daemon.count("/logs?") == 1


def test_start_receipt_without_dispatch_remains_unresolved_created(scenario, monkeypatch):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    original = scenario[0]._write_new

    def lost_ack(directory, name, *args):
        result = original(directory, name, *args)
        if name == "start.json":
            raise OSError("fictional lost start-fence acknowledgement")
        return result

    monkeypatch.setattr(scenario[0], "_write_new", lost_ack)
    with pytest.raises(ValueError):
        api.run_probe(IMAGE)
    daemon.join()
    assert daemon.count("/create?") == 1 and daemon.count("/start") == 0
    assert not any(method == "DELETE" or "/kill?" in path for method, path, _ in daemon.requests)


def test_torn_output_inventory_is_preserved_and_never_repaired(scenario, monkeypatch):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    original = scenario[0]._write_bytes

    def lost_ack(directory, name, *args):
        result = original(directory, name, *args)
        if name == "configuration.bin":
            raise OSError("fictional configuration persistence uncertainty")
        return result

    monkeypatch.setattr(scenario[0], "_write_bytes", lost_ack)
    with pytest.raises(ValueError):
        api.run_probe(IMAGE)
    daemon.join()
    directory = next(p for p in scenario[1].iterdir() if p.is_dir())
    assert (directory / "configuration.bin").exists() and not (directory / "output.json").exists()
    assert not (directory / "closed.json").exists()
    assert not any(method == "DELETE" for method, _, _ in daemon.requests)


def test_store_context_exit_failure_suppresses_configuration(scenario, monkeypatch):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    original = api.probes

    @contextmanager
    def failed_exit():
        with original() as store:
            yield store
        raise OSError("private fictional store close failure")

    monkeypatch.setattr(api, "probes", failed_exit)
    with pytest.raises(ValueError):
        api.run_probe(IMAGE)
    daemon.join()
    assert daemon.gone and daemon.store._closed
    assert sum(method == "DELETE" for method, _, _ in daemon.requests) == 1


@pytest.mark.parametrize("mode", ["failure", "shutdown"])
def test_handler_restoration_boundary_cannot_publish_configuration(scenario, monkeypatch, mode):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    original = signal.signal
    previous = {number: signal.getsignal(number) for number in (signal.SIGTERM, signal.SIGINT)}
    installed = []

    def restore(number, handler):
        if callable(handler) and "_shutdown.<locals>.handler" in handler.__qualname__:
            installed.append(handler)
        elif installed:
            if mode == "failure":
                raise OSError("fictional handler restoration failure")
            installed[0](signal.SIGTERM, None)
        return original(number, handler)

    monkeypatch.setattr(signal, "signal", restore)
    try:
        with pytest.raises(ValueError):
            api.run_probe(IMAGE)
    finally:
        for number, handler in previous.items():
            original(number, handler)
        daemon.join()
    assert daemon.gone


def test_supervision_reads_remain_spaced_across_cleanup_phases(scenario, monkeypatch):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    daemon.exit_after, daemon.term_exit = None, False
    api.run_probe(IMAGE)
    daemon.join()
    start = next(i for i, (_, path, _) in enumerate(daemon.requests) if path.endswith("/start"))
    end = next(i for i, (method, _, _) in enumerate(daemon.requests) if method == "DELETE")
    times = [
        at
        for method, path, at in daemon.requests[start + 1 : end]
        if method == "GET" and path.endswith("/json")
    ]
    assert len(times) > 30
    assert all(right - left >= 1000000000 for left, right in pairwise(times))


def test_late_wakeup_does_not_renew_missed_cleanup_caps(scenario, monkeypatch):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    daemon.exit_after = None

    def late(_seconds):
        scenario[2]["monotonic_ns"] += 90000000000

    monkeypatch.setattr(api.time, "sleep", late)
    with pytest.raises(ValueError):
        api.run_probe(IMAGE)
    daemon.join()
    assert daemon.count("/start") == 1
    assert not any(method == "DELETE" or "/kill?" in path for method, path, _ in daemon.requests)


@pytest.mark.parametrize("at", ["version", "image"])
def test_shutdown_before_intent_never_creates_native_resource(scenario, monkeypatch, at):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)

    def shutdown(method, path):
        if (at == "version" and path == "/version") or (at == "image" and "/images/" in path):
            request_shutdown()

    daemon.on_request = shutdown
    with pytest.raises(ValueError):
        api.run_probe(IMAGE)
    daemon.join()
    assert daemon.count("/create?") == daemon.count("/start") == 0


def test_cleanup_poll_exchange_is_shortened_to_its_current_phase(scenario, monkeypatch):
    from infra.hybrid import stock_probe_engine

    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    daemon.exit_after, daemon.term_exit = None, False
    original = stock_probe_engine._deadline
    current = []
    observations = []
    phase = ["RUN"]

    def deadline(cap):
        current[:] = [cap]
        return original(cap)

    def observe(method, path):
        if "signal=TERM" in path:
            phase[0] = "TERM"
        elif "signal=KILL" in path:
            phase[0] = "KILL"
        elif (
            method == "GET"
            and path.endswith("/json")
            and phase[0] != "RUN"
            and daemon.store.snapshot().stopped is None
        ):
            observations.append((phase[0], current[0]))

    daemon.on_request = observe
    monkeypatch.setattr(stock_probe_engine, "_deadline", deadline)
    result = api.run_probe(IMAGE)
    daemon.join()
    start = json.loads((scenario[1] / result.probe_id / "start.json").read_bytes())
    term_cap, kill_cap = (
        start["run_deadline_ns"] + 10000000000,
        start["run_deadline_ns"] + 15000000000,
    )
    assert observations
    assert all(cap <= (term_cap if phase == "TERM" else kill_cap) for phase, cap in observations)


def test_prestart_policy_drift_denies_start_and_allows_only_owned_cleanup(scenario, monkeypatch):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    daemon.bad_prestart = True
    result = api.run_probe(IMAGE)
    daemon.join()
    assert result.status == "failed" and result.reason == "prestart_failed"
    assert result.configuration is None and daemon.gone and not daemon.count("/start")


def test_rejected_create_and_name404_stay_unresolved_without_retry(scenario, monkeypatch):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    daemon.reject_create = True
    with pytest.raises(ValueError):
        api.run_probe(IMAGE)
    daemon.join()
    assert daemon.count("/create?") == 1 and daemon.count("/start") == 0
    assert not any(method == "DELETE" for method, _, _ in daemon.requests)
    directory = next(p for p in scenario[1].iterdir() if p.is_dir())
    assert (directory / "create.json").exists() and not (directory / "closed.json").exists()


def test_failed_normal_observation_enters_cleanup_and_cannot_succeed(scenario, monkeypatch):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    daemon.fail_reads = 2
    result = api.run_probe(IMAGE)
    daemon.join()
    assert result.status == "failed" and result.configuration is None and daemon.gone
    assert daemon.count("/start") == 1


def test_cleanup_observation_errors_remain_bounded_and_do_not_repeat_signals(scenario, monkeypatch):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    daemon.exit_after, daemon.term_exit = None, False

    def unavailable_after_term(method, path):
        if method == "POST" and "signal=TERM" in path:
            daemon.fail_reads = 2

    daemon.on_request = unavailable_after_term
    result = api.run_probe(IMAGE)
    daemon.join()
    assert result.status == "failed" and daemon.gone
    assert daemon.count("signal=TERM") == daemon.count("signal=KILL") == 1


@pytest.mark.parametrize("change", ["boot", "monotonic", "utc"])
def test_changed_clock_during_original_run_allows_only_bounded_recovery(
    scenario, monkeypatch, change
):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    changed = []

    def shift(method, path):
        if method == "GET" and path.endswith("/json") and daemon.started and not changed:
            changed.append(True)
            if change == "boot":
                scenario[2]["boot_id"] = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
            elif change == "monotonic":
                scenario[2]["monotonic_ns"] -= 1000000000
            else:
                scenario[2]["utc"] = "2026-10-21T20:59:59+00:00"

    daemon.on_request = shift
    result = api.run_probe(IMAGE)
    daemon.join()
    assert result.status == "failed" and result.configuration is None
    assert daemon.count("/start") == 1 and daemon.gone


def test_repeated_shutdown_never_renews_cleanup_origin(scenario, monkeypatch):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    daemon.exit_after, daemon.term_exit = None, False

    def repeated(method, path):
        if method == "GET" and path.endswith("/json") and daemon.started:
            request_shutdown()

    daemon.on_request = repeated
    result = api.run_probe(IMAGE)
    daemon.join()
    assert result.status == "failed" and result.reason == "shutdown" and daemon.gone
    assert daemon.count("signal=TERM") == daemon.count("signal=KILL") == 1
    directory = scenario[1] / result.probe_id
    start = json.loads((directory / "start.json").read_bytes())
    closed = json.loads((directory / "closed.json").read_bytes())
    assert closed["monotonic_ns"] < start["monotonic_ns"] + 20000000000


def test_fixed_public_api_cannot_receive_dependencies_or_unsafe_image_reference(
    scenario, monkeypatch
):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    for name in ("store", "root", "socket", "engine", "deadline_ns", "live_enabled"):
        with pytest.raises(TypeError):
            api.run_probe(IMAGE, **{name: "untrusted"})
    for image in [None, True, "latest", "sha256:" + "A" * 64, IMAGE + "\n"]:
        with pytest.raises(ValueError):
            api.run_probe(image)
    assert not daemon.requests


@pytest.mark.parametrize("slot", ["intent.json", "cid.json", "created.json"])
def test_shutdown_after_durable_stage_blocks_later_start(scenario, monkeypatch, slot):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    original = scenario[0]._write_new
    fired = []

    def shutdown(directory, name, *args):
        result = original(directory, name, *args)
        if name == slot and not fired:
            fired.append(True)
            request_shutdown()
        return result

    monkeypatch.setattr(scenario[0], "_write_new", shutdown)
    result = api.run_probe(IMAGE)
    daemon.join()
    assert result.status == "failed" and result.configuration is None and not daemon.count("/start")
    if slot == "intent.json":
        assert not daemon.count("/create?")


def test_shutdown_while_waiting_for_next_normal_poll_enters_cleanup(scenario, monkeypatch):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    original = api.time.sleep
    fired = []

    def shutdown(seconds):
        if not fired:
            fired.append(True)
            request_shutdown()
        original(seconds)

    monkeypatch.setattr(api.time, "sleep", shutdown)
    result = api.run_probe(IMAGE)
    daemon.join()
    assert fired and result.status == "failed" and result.reason == "shutdown"
    assert result.configuration is None


def test_missed_term_window_can_only_use_original_remaining_kill_window(scenario, monkeypatch):
    api = module()
    daemon = Daemon(scenario).install(monkeypatch, api)
    daemon.exit_after, daemon.term_exit = None, False
    seen = []

    def delayed(method, path):
        if method == "GET" and path.endswith("/json") and daemon.started:
            seen.append(True)
            if len(seen) == 1:
                request_shutdown()
            elif len(seen) == 2:
                scenario[2]["monotonic_ns"] += 11000000000

    daemon.on_request = delayed
    result = api.run_probe(IMAGE)
    daemon.join()
    assert result.status == "failed" and daemon.gone
    assert daemon.count("signal=TERM") == 0 and daemon.count("signal=KILL") == 1


def test_cli_reports_recovery_with_non_success_exit_and_no_configuration(
    scenario, monkeypatch, capsys
):
    from test_stock_probe_admission import admitted, opened

    api = module()
    with opened(scenario) as store:
        admitted(store, scenario)
    daemon = Daemon(scenario).install(monkeypatch, api)
    monkeypatch.setattr(sys, "argv", ["probe", IMAGE])
    assert api.main() == 2
    daemon.join()
    value = json.loads(capsys.readouterr().out)
    assert value["status"] == "recovery_only" and "configuration" not in value
