"""Real manifest/store/transport/verifiers; fictional Engine wire and virtual clock."""

import copy
import json
import os
import signal
import subprocess
import sys

import pytest
from test_stock_container import engine, image
from test_stock_engine_mutation import response
from test_stock_prestart import policy as policy
from test_stock_prestart import record
from test_stock_release import release as release

from infra.hybrid import (
    stock_attempts,
    stock_engine,
    stock_engine_mutation,
    stock_engine_retirement,
    stock_engine_termination,
    stock_launcher,
    stock_prestart,
    stock_release,
    stock_supervisor,
)

NS = 1000000000
BOOT = "11111111-2222-4333-8444-555555555555"


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


class Engine:
    def __init__(self, policy, clock):
        self.policy, self.clock = policy, clock
        self.containers, self.requests = {}, []
        self.on_request = None
        self.fault = None
        self.counter = 0

    def route(self, raw):
        head, body = raw.split(b"\r\n\r\n", 1)
        method, path, _ = head.split(b"\r\n")[0].decode().split(" ")
        self.requests.append((method, path, body))
        if method == "GET" and path == "/version":
            result = response(200, encoded(engine()))
        elif method == "GET" and path.startswith("/v1.52/images/"):
            value = image()
            value["Config"]["Env"] = list(self.policy[1].environment)
            result = response(200, encoded(value))
        elif method == "POST" and path.startswith("/v1.52/containers/create?name="):
            request = json.loads(body)
            self.counter += 1
            cid = f"{self.counter:064x}"
            value = record(self.policy)
            value["Id"] = cid
            value["Name"] = "/" + path.partition("?name=")[2]
            value["Config"]["Labels"] = request["Labels"]
            value["Config"]["Hostname"] = cid[:12]
            self.containers[cid] = value
            result = (
                b"truncated"
                if self.fault == "create_ack"
                else response(201, encoded({"Id": cid, "Warnings": []}))
            )
        elif path.startswith("/v1.52/containers/"):
            suffix = path.removeprefix("/v1.52/containers/")
            identifier = suffix.split("/")[0].split("?")[0]
            cid = next(
                (
                    key
                    for key, value in self.containers.items()
                    if key == identifier or value["Name"] == "/" + identifier
                ),
                None,
            )
            if cid is None:
                result = response(404, encoded({"message": "No such container: " + identifier}))
            elif method == "GET" and suffix.endswith("/json"):
                result = response(200, encoded(copy.deepcopy(self.containers[cid])))
            elif method == "POST" and suffix.endswith("/start"):
                self.containers[cid]["State"].update(
                    Status="exited",
                    Running=False,
                    Pid=0,
                    ExitCode=0,
                    StartedAt="2026-10-21T21:00:01Z",
                    FinishedAt="2026-10-21T21:00:02Z",
                )
                result = b"truncated" if self.fault == "start_ack" else response(204)
            elif method == "POST" and suffix.endswith(("/kill?signal=TERM", "/kill?signal=KILL")):
                result = response(204)
            elif method == "DELETE" and suffix.endswith("?force=false&v=false&link=false"):
                del self.containers[cid]
                result = b"truncated" if self.fault == "delete_ack" else response(204)
            else:
                pytest.fail("Unexpected container request")
        else:
            pytest.fail("Unexpected Engine request")
        if self.on_request is not None:
            self.on_request(method, path)
        return result

    def connect(self, deadline):
        assert deadline > self.clock["monotonic_ns"] / NS
        owner = self

        class Peer:
            def __enter__(self):
                self.raw = b""
                return self

            def __exit__(self, *_args):
                return False

            def settimeout(self, seconds):
                assert 0 < seconds <= 5

            def sendall(self, raw):
                self.raw = owner.route(raw)

            def recv(self, size):
                chunk, self.raw = self.raw[:size], self.raw[size:]
                return chunk

        return Peer()


@pytest.fixture
def cycle(tmp_path, monkeypatch, release, policy):
    root = tmp_path.resolve() / "operations"
    stock_attempts._initialize(root, trusted_uid=os.geteuid())
    clock = {"boot_id": BOOT, "utc": "2026-10-21T21:00:00+00:00", "monotonic_ns": 1000 * NS}
    monkeypatch.setattr(stock_attempts, "_clock", lambda: clock.copy())
    monkeypatch.setattr(stock_supervisor, "_clock", lambda: clock.copy())
    monkeypatch.setattr(stock_engine.time, "monotonic", lambda: clock["monotonic_ns"] / NS)

    def sleep(seconds):
        assert 0 < seconds <= 1
        clock["monotonic_ns"] += int(seconds * NS)

    monkeypatch.setattr(stock_supervisor.time, "sleep", sleep)
    release_root, directory, *_ = release
    manifest = directory / "manifest.json"
    loaded = stock_release._load_release(
        manifest, trusted_uid=os.geteuid(), release_root=release_root
    )
    daemon = Engine((loaded, policy[1]), clock)
    monkeypatch.setattr(stock_prestart, "RELEASE_ROOT", release_root)
    monkeypatch.setattr(
        stock_launcher,
        "load_release",
        lambda path: stock_release._load_release(
            path, trusted_uid=os.geteuid(), release_root=release_root
        ),
    )
    monkeypatch.setattr(stock_launcher, "_production_store", lambda store: None)
    monkeypatch.setattr(stock_engine_mutation, "_production_store", lambda store: None)
    monkeypatch.setattr(stock_supervisor, "_production_store", lambda store: None)
    monkeypatch.setattr(stock_engine_termination, "_production_store", lambda store: None)
    for api in (
        stock_engine,
        stock_engine_mutation,
        stock_engine_retirement,
        stock_engine_termination,
    ):
        monkeypatch.setattr(api, "_connection", daemon.connect)
    return root, manifest, loaded, daemon, clock


def opened(cycle):
    return stock_attempts._open_operations(cycle[0], trusted_uid=os.geteuid())


def run(store, path):
    operation = getattr(stock_launcher, "run_research_cycle", None)
    assert callable(operation), "Repeated stock research cycle composition is not implemented"
    return operation(store, path)


def test_three_actual_protocol_cycles_keep_one_retained_worker_and_complete_history(cycle):
    root, manifest, _, daemon, _ = cycle
    ids = []
    for _ in range(3):
        with opened(cycle) as store:
            result = run(store, manifest)
            assert result.status == "completed" and result.supervision.exit_code == 0
            state = store.snapshot()
            assert state.stopped_sha256 and state.create_sha256 and state.start_sha256
            ids.append(state.attempt.attempt_id)
        assert len(daemon.containers) == 1
    assert len(set(ids)) == 3
    assert len([path for path in root.iterdir() if path.is_dir()]) == 3
    assert (
        sum(method == "POST" and path.endswith("/start") for method, path, _ in daemon.requests)
        == 3
    )
    assert sum(method == "DELETE" for method, _, _ in daemon.requests) == 2


def test_manifest_directory_is_rejected_before_admission(cycle):
    _, manifest, _, daemon, _ = cycle
    with opened(cycle) as store:
        with pytest.raises(ValueError, match=r"^stock_launcher_unavailable$"):
            run(store, manifest.parent)
        assert store.snapshot() is None and not daemon.requests


def test_intent_only_recovery_abandons_then_ends_before_next_fresh_invocation(cycle):
    _, manifest, loaded, daemon, _ = cycle
    with opened(cycle) as store:
        first = store.begin(loaded)
    with opened(cycle) as store:
        result = run(store, manifest)
        assert result.status == "recovery_only" and result.supervision is None
        assert store.snapshot().abandoned_sha256 and not daemon.requests
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.begin(loaded)
    with opened(cycle) as store:
        assert run(store, manifest).status == "completed"
        assert store.snapshot().attempt.predecessor_attempt_id == first.attempt_id


@pytest.mark.parametrize("fault", ["create_ack", "delete_ack"])
def test_lost_ack_is_resolved_without_launching_in_the_recovery_invocation(cycle, fault):
    _, manifest, _, daemon, _ = cycle
    if fault == "delete_ack":
        with opened(cycle) as store:
            run(store, manifest)
    daemon.fault = fault
    with (
        opened(cycle) as store,
        pytest.raises(ValueError, match=r"^stock_launcher_unavailable$"),
    ):
        run(store, manifest)
    daemon.fault = None
    requests_before = len(daemon.requests)
    with opened(cycle) as store:
        assert run(store, manifest).status == "recovery_only"
        assert store.snapshot().stopped_sha256 or store.snapshot().abandoned_sha256
    assert all(method == "GET" for method, _, _ in daemon.requests[requests_before:])
    with opened(cycle) as store:
        assert run(store, manifest).status == "completed"


def test_lost_start_ack_supervises_the_original_start_once(cycle):
    _, manifest, _, daemon, _ = cycle
    daemon.fault = "start_ack"
    with opened(cycle) as store:
        result = run(store, manifest)
        assert result.status == "completed" and store.snapshot().stopped_sha256
    assert sum(path.endswith("/start") for _, path, _ in daemon.requests) == 1


def test_unknown_create_name404_is_not_abandonment_or_fresh_admission(cycle):
    _, manifest, loaded, daemon, clock = cycle
    with opened(cycle) as store:
        store.begin(loaded)
        claim = store.claim_create(loaded)
        store.prepare_create(claim, "a" * 64, clock["monotonic_ns"] + 5 * NS)
    with opened(cycle) as store:
        with pytest.raises(ValueError, match=r"^stock_launcher_unavailable$"):
            run(store, manifest)
        assert store.snapshot().abandoned_sha256 is None
        assert store.snapshot().stopped_sha256 is None
    assert len(daemon.requests) == 1 and daemon.requests[0][0] == "GET"


@pytest.mark.parametrize("phase", ["version", "create"])
def test_shutdown_during_a_phase_never_submits_start_or_another_create(cycle, phase):
    _, manifest, _, daemon, _ = cycle

    def stop(method, path):
        if (phase == "version" and path == "/version") or (phase == "create" and method == "POST"):
            handler = signal.getsignal(signal.SIGTERM)
            assert callable(handler)
            handler(signal.SIGTERM, None)

    daemon.on_request = stop
    with opened(cycle) as store:
        assert run(store, manifest).status == "recovery_only"
        state = store.snapshot()
        assert state is None or state.stopped_sha256 or state.abandoned_sha256
    assert all(not path.endswith("/start") for _, path, _ in daemon.requests)
    assert daemon.counter == (0 if phase == "version" else 1)


@pytest.mark.parametrize("has_predecessor", [False, True])
def test_crash_after_admission_resolves_retirement_and_abandonment_without_create(
    cycle, monkeypatch, has_predecessor
):
    _, manifest, _, daemon, _ = cycle
    if has_predecessor:
        with opened(cycle) as store:
            run(store, manifest)
    with opened(cycle) as store:
        original = store.begin

        def lost_ack(release):
            original(release)
            raise OSError("fictional admission acknowledgement loss")

        monkeypatch.setattr(store, "begin", lost_ack)
        with pytest.raises(ValueError, match=r"^stock_launcher_unavailable$"):
            run(store, manifest)
        interrupted = store.snapshot().attempt.attempt_id
    assert daemon.counter == int(has_predecessor)
    with opened(cycle) as store:
        assert run(store, manifest).status == "recovery_only"
        assert store.snapshot().abandoned_sha256
    assert daemon.counter == int(has_predecessor)
    with opened(cycle) as store:
        assert run(store, manifest).status == "completed"
        assert store.snapshot().attempt.predecessor_attempt_id == interrupted


@pytest.mark.parametrize("after_write", [False, True])
def test_cid_receipt_failure_recovers_observed_container_without_start(
    cycle, monkeypatch, after_write
):
    _, manifest, _, daemon, _ = cycle
    original = stock_attempts._write_new

    def fail(directory, name, value, uid):
        if name == "created.json":
            if after_write:
                original(directory, name, value, uid)
            raise OSError("fictional CID receipt failure")
        return original(directory, name, value, uid)

    with opened(cycle) as store, monkeypatch.context() as scoped:
        scoped.setattr(stock_attempts, "_write_new", fail)
        with pytest.raises(ValueError, match=r"^stock_launcher_unavailable$"):
            run(store, manifest)
    with opened(cycle) as store:
        assert run(store, manifest).status == "recovery_only"
        assert store.snapshot().stopped_sha256
    assert daemon.counter == 1
    assert all(not path.endswith("/start") for _, path, _ in daemon.requests)


@pytest.mark.parametrize("after_write", [False, True])
def test_start_receipt_failure_never_retries_or_invents_a_completed_run(
    cycle, monkeypatch, after_write
):
    _, manifest, _, daemon, _ = cycle
    original = stock_attempts._write_new

    def fail(directory, name, value, uid):
        if name == "start.json":
            if after_write:
                original(directory, name, value, uid)
            raise OSError("fictional START fence failure")
        return original(directory, name, value, uid)

    with opened(cycle) as store:
        with monkeypatch.context() as scoped:
            scoped.setattr(stock_attempts, "_write_new", fail)
            with pytest.raises(ValueError, match=r"^stock_launcher_unavailable$"):
                run(store, manifest)
        assert store.snapshot().stopped_sha256 is None
    with opened(cycle) as store:
        if after_write:
            with pytest.raises(ValueError, match=r"^stock_launcher_unavailable$"):
                run(store, manifest)
            assert store.snapshot().stopped_sha256 is None
        else:
            assert run(store, manifest).status == "recovery_only"
            assert store.snapshot().stopped_sha256
    assert daemon.counter == 1
    assert all(not path.endswith("/start") for _, path, _ in daemon.requests)


@pytest.mark.parametrize("after_write", [False, True])
def test_stopped_write_failure_preserves_entry_classification_on_restart(
    cycle, monkeypatch, after_write
):
    _, manifest, _, daemon, _ = cycle
    original = stock_attempts._write_new

    def fail(directory, name, value, uid):
        if name == "stopped.json":
            if after_write:
                original(directory, name, value, uid)
            raise OSError("fictional STOP acknowledgement failure")
        return original(directory, name, value, uid)

    with opened(cycle) as store, monkeypatch.context() as scoped:
        scoped.setattr(stock_attempts, "_write_new", fail)
        with pytest.raises(ValueError, match=r"^stock_launcher_unavailable$"):
            run(store, manifest)
    with opened(cycle) as store:
        result = run(store, manifest)
        assert result.status == ("completed" if after_write else "recovery_only")
        assert store.snapshot().stopped_sha256
    assert daemon.counter == (2 if after_write else 1)


def test_parent_shutdown_after_start_is_preserved_by_supervision(cycle):
    _, manifest, _, daemon, _ = cycle

    def stop(method, path):
        if method == "POST" and path.endswith("/start"):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

    daemon.on_request = stop
    with opened(cycle) as store:
        result = run(store, manifest)
        assert result.status == "completed" and result.supervision.reason == "shutdown"
        assert result.supervision.term_attempted is True
    assert sum(path.endswith("/start") for _, path, _ in daemon.requests) == 1


def test_handler_setup_failure_precedes_release_and_admission(cycle, monkeypatch):
    _, manifest, _, daemon, _ = cycle
    original = signal.signal
    previous = signal.getsignal(signal.SIGTERM)

    def fail_sigint(number, handler):
        if number == signal.SIGINT:
            raise OSError("fictional handler failure")
        return original(number, handler)

    with opened(cycle) as store:
        monkeypatch.setattr(signal, "signal", fail_sigint)
        with pytest.raises(ValueError, match=r"^stock_launcher_unavailable$"):
            run(store, manifest)
        assert store.snapshot() is None and not daemon.requests
    assert signal.getsignal(signal.SIGTERM) is previous


def test_empty_legacy_namespace_never_admits_or_contacts_engine(cycle):
    root, manifest, _, daemon, _ = cycle
    path = root / "namespace.json"
    value = json.loads(path.read_bytes())
    value["schema_version"] = 1
    path.write_bytes(encoded(value))
    with opened(cycle) as store:
        assert run(store, manifest).status == "recovery_only"
        assert store.snapshot() is None and not daemon.requests


def test_cli_without_a_manifest_fails_closed_without_a_native_runtime():
    result = subprocess.run(
        [sys.executable, "-m", "infra.hybrid.stock_launcher"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 1 and result.stdout == ""
    assert json.loads(result.stderr) == {"status": "unavailable"}


def history(cycle):
    identifiers = []
    for _ in range(3):
        with opened(cycle) as store:
            run(store, cycle[1])
            identifiers.append(store.snapshot().attempt.attempt_id)
    return identifiers


def slow_ancestor_reads(cycle, monkeypatch, ancestors):
    # Controlled historical I/O latency, not a renewed transport deadline.
    inodes = {(cycle[0] / item).stat().st_ino for item in ancestors}
    original = stock_attempts._read

    def delayed(directory, name, uid):
        if os.fstat(directory).st_ino in inodes:
            cycle[4]["monotonic_ns"] += 3 * NS
        return original(directory, name, uid)

    monkeypatch.setattr(stock_attempts, "_read", delayed)


def test_retained_history_io_cannot_exhaust_a_new_create_dispatch_budget(cycle, monkeypatch):
    prior = history(cycle)
    with opened(cycle) as store:
        # Complete history was validated at entry, before any dispatch budget.
        actual = stock_engine_retirement.StockEngineRetirer

        class AfterRetirement:
            def retire_predecessor(self, target):
                actual().retire_predecessor(target)
                slow_ancestor_reads(cycle, monkeypatch, prior[:-1])

        monkeypatch.setattr(stock_launcher, "StockEngineRetirer", AfterRetirement)
        assert run(store, cycle[1]).status == "completed"
        assert store.snapshot().stopped_sha256
    assert cycle[3].counter == 4


@pytest.mark.parametrize("signal_name", ["TERM", "KILL"])
def test_retained_history_io_preserves_the_actual_termination_post_budget(
    cycle, monkeypatch, signal_name
):
    prior = history(cycle)
    root, _, loaded, daemon, _ = cycle
    with opened(cycle) as store:
        current = store.snapshot()
        store.record_stopped(stock_engine.StockEngineReader().inspect(current.container_id))
        attempt = store.begin(loaded)
        stock_engine_retirement.StockEngineRetirer().retire_predecessor(store)
        mutator = stock_engine_mutation.StockEngineMutator()
        cid = mutator.create_worker(store, loaded, daemon.policy[1])
        observed = stock_engine.StockEngineReader().inspect(cid)
        store.record_created(
            stock_prestart.verify_created(
                observed,
                release=loaded,
                image=daemon.policy[1],
                attempt_id=attempt.attempt_id,
                container_id=cid,
            )
        )
        fence = mutator.start_worker(store)
        daemon.containers[cid]["State"].update(
            Status="running", Running=True, Pid=42, FinishedAt="0001-01-01T00:00:00Z"
        )
        slow_ancestor_reads(cycle, monkeypatch, prior[:-1])
        stock_engine_termination.StockEngineTerminator().signal_active(store, signal_name)
        assert daemon.requests[-1][:2] == (
            "POST",
            "/v1.52/containers/" + cid + "/kill?signal=" + signal_name,
        )
        assert store.snapshot().start_fence == fence
        assert not (root / attempt.attempt_id / "stopped.json").exists()


def test_unchanged_history_optimization_still_rejects_changed_ancestor_bytes(cycle):
    prior = history(cycle)
    with opened(cycle) as store:
        path = cycle[0] / prior[0] / "stopped.json"
        raw = json.loads(path.read_bytes())
        raw["utc"] = "2026-10-21T21:00:01+00:00"
        path.write_bytes(encoded(raw))
        with pytest.raises(ValueError, match=r"^stock_launcher_unavailable$"):
            run(store, cycle[1])
    assert cycle[3].counter == 3
