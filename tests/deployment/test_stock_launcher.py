"""First-attempt integration through real receipts/supervision, fictional daemon only."""

import importlib
import json
import os
from pathlib import Path

import pytest
from test_stock_container import engine, image
from test_stock_prestart import CID, IMAGE, RELEASE, encoded, record
from test_stock_prestart import policy as policy

from infra.hybrid import stock_attempts, stock_supervisor
from infra.hybrid.stock_engine_mutation import _production_store
from infra.hybrid.stock_prestart import CreatedContainer

NS = 1_000_000_000
BOOT = "11111111-2222-4333-8444-555555555555"


def module():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_launcher.py"
    assert path.is_file(), "Fresh stock attempt composition is not implemented"
    return importlib.import_module("infra.hybrid.stock_launcher")


def verified(store):
    intent = store.active()
    return CreatedContainer(CID, intent.attempt_id, RELEASE, IMAGE, "c" * 64, intent.compose_sha256)


class Daemon:
    def __init__(self, root, policy, clock):
        self.root, self.policy, self.clock = root, policy, clock
        self.events = []
        self.store = None
        self.running = False
        self.reads = 0
        self.fail_at = None
        self.change = None
        self.start_after_fence = False
        self.exit_code = 0

    def event(self, name):
        self.events.append(name)
        if self.fail_at == name:
            raise ValueError("fictional private boundary detail")

    def load(self, path):
        self.event("release")
        assert path == self.policy[0].attestation_path.parent
        return self.policy[0]

    def version(self):
        self.event("version")
        value = engine()
        if self.change == "version":
            value["ApiVersion"] = "1.51"
        return encoded(value)

    def image(self, digest):
        self.event("image")
        assert digest == IMAGE
        value = image()
        value["Config"]["Env"] = list(self.policy[1].environment)
        if self.change == "image":
            value["Id"] = "sha256:" + "a" * 64
        return encoded(value)

    def inspect(self, cid, *, not_after_ns=None):
        self.event("inspect" if not_after_ns is None else "supervise")
        assert cid == CID
        assert self.store is not None
        intent = self.store.active()
        value = record(self.policy)
        value["Name"] = "/hybrid-stock-research-" + intent.attempt_id
        value["Config"]["Labels"]["org.hybrid.stock.attempt"] = intent.attempt_id
        if not_after_ns is None:
            if self.change == "cid":
                value["Id"] = "a" * 64
            if self.change == "mount":
                value["Mounts"][0]["Source"] = "/fictional/unsafe"
            if self.change == "command":
                value["Config"]["Cmd"] = ["unreviewed"]
            if self.change == "already_running":
                value["State"]["Running"] = True
                value["State"]["Status"] = "running"
            return encoded(value)
        assert self.running and self.clock["monotonic_ns"] < not_after_ns
        value["State"]["StartedAt"] = "2026-10-21T21:00:00Z"
        if self.reads == 0:
            value["State"].update(Status="running", Running=True, Pid=42)
        else:
            value["State"].update(
                Status="exited",
                Running=False,
                Pid=0,
                ExitCode=self.exit_code,
                FinishedAt="2026-10-21T21:00:01Z",
            )
        self.reads += 1
        return encoded(value)

    def create_worker(self, store, release, profile):
        self.store = store
        claim = store.claim_create(release)
        store.check_create_claim(claim)
        assert release is self.policy[0] and profile.image_digest == IMAGE
        self.event("create")
        return CID

    def start_worker(self, store):
        self.event("start")
        fence = store.prepare_start()
        store.check_start_fence(fence)
        self.running = True
        if self.start_after_fence:
            self.clock["monotonic_ns"] += 17 * NS
            raise ValueError("fictional lost start acknowledgement")
        return fence

    def sleep(self, seconds):
        assert 0 < seconds <= 1
        self.clock["monotonic_ns"] += int(seconds * NS)


@pytest.fixture
def scenario(tmp_path, monkeypatch, policy):
    api = module()
    root = tmp_path.resolve() / "operations"
    stock_attempts._initialize(root, trusted_uid=os.geteuid())
    clock = {"boot_id": BOOT, "utc": "2026-10-21T21:00:00+00:00", "monotonic_ns": 1000 * NS}
    monkeypatch.setattr(stock_attempts, "_clock", lambda: clock.copy())
    daemon = Daemon(root, policy, clock)
    monkeypatch.setattr(api, "_production_store", lambda store: None)
    monkeypatch.setattr(api, "load_release", daemon.load)
    monkeypatch.setattr(api, "StockEngineReader", lambda: daemon)
    monkeypatch.setattr(api, "StockEngineMutator", lambda: daemon)
    monkeypatch.setattr(stock_supervisor, "_production_store", lambda store: None)
    monkeypatch.setattr(stock_supervisor, "_clock", lambda: clock.copy())
    monkeypatch.setattr(stock_supervisor, "StockEngineReader", lambda: daemon)
    monkeypatch.setattr(stock_supervisor.time, "sleep", daemon.sleep)
    return api, daemon, policy[0].attestation_path.parent


def opened(scenario):
    return stock_attempts._open_operations(scenario[1].root, trusted_uid=os.geteuid())


def test_full_first_attempt_uses_original_prestart_bytes_and_real_supervisor(scenario):
    api, daemon, path = scenario
    with opened(scenario) as store:
        result = api.launch_fresh_attempt(store, path)
        assert daemon.events == [
            "release",
            "version",
            "image",
            "create",
            "inspect",
            "start",
            "supervise",
            "supervise",
        ]
        target = store.snapshot()
        assert target.stopped_sha256 is not None
        assert result.attempt_id == target.attempt.attempt_id and result.container_id == CID
        assert result.reason == "natural_exit" and result.exit_code == 0
        assert result.term_deadline_ns == 1450 * NS and result.start_monotonic_ns == 1000 * NS
        assert not result.term_attempted and not result.kill_attempted
        assert "qualified" not in result.__dataclass_fields__
        assert "research_succeeded" not in result.__dataclass_fields__


def test_nonzero_worker_exit_is_lifecycle_evidence_not_a_research_success(scenario):
    api, daemon, path = scenario
    daemon.exit_code = 2
    with opened(scenario) as store:
        assert api.launch_fresh_attempt(store, path).exit_code == 2


@pytest.mark.parametrize("state", ["intent", "created", "fenced", "stopped"])
def test_every_nonempty_namespace_denies_without_release_or_daemon_work(scenario, state):
    api, daemon, path = scenario
    with opened(scenario) as store:
        store.begin(daemon.policy[0])
        if state != "intent":
            store.record_created(verified(store))
        if state == "fenced":
            store.prepare_start()
        if state == "stopped":
            daemon.store = store
            store.record_stopped(daemon.inspect(CID))
            daemon.events.clear()
        with pytest.raises(ValueError, match=r"^stock_launcher_unavailable$"):
            api.launch_fresh_attempt(store, path)
        assert not daemon.events


def test_actual_fixed_root_guard_runs_before_a_release_or_daemon_operation(scenario, monkeypatch):
    api, daemon, path = scenario
    monkeypatch.setattr(api, "_production_store", _production_store)
    with opened(scenario) as store:
        with pytest.raises(ValueError, match=r"^stock_launcher_unavailable$"):
            api.launch_fresh_attempt(store, path)
        assert store.snapshot() is None and not daemon.events


@pytest.mark.parametrize(
    "change", ["version", "image", "cid", "mount", "command", "already_running"]
)
def test_actual_policy_verification_blocks_unsafe_creation_before_start(scenario, change):
    api, daemon, path = scenario
    daemon.change = change
    with opened(scenario) as store:
        with pytest.raises(ValueError, match=r"^stock_launcher_unavailable$"):
            api.launch_fresh_attempt(store, path)
        assert "start" not in daemon.events and "supervise" not in daemon.events
        target = store.snapshot()
        if change in {"version", "image"}:
            assert target is None and "create" not in daemon.events
        else:
            assert target is not None and target.created_sha256 is None


@pytest.mark.parametrize("fail_at", ["release", "version", "image", "create", "inspect", "start"])
def test_boundary_errors_never_retry_or_infer_execution_authority(scenario, fail_at):
    api, daemon, path = scenario
    daemon.fail_at = fail_at
    with opened(scenario) as store:
        with pytest.raises(ValueError, match=r"^stock_launcher_unavailable$") as error:
            api.launch_fresh_attempt(store, path)
        assert "private" not in str(error.value)
        assert daemon.events.count("create") <= 1 and daemon.events.count("start") <= 1
        assert "supervise" not in daemon.events
        target = store.snapshot()
        if fail_at in {"release", "version", "image"}:
            assert target is None
        else:
            assert target is not None and target.start_fence is None


@pytest.mark.parametrize("after_write", [False, True])
def test_created_persistence_failure_never_leads_to_start(scenario, monkeypatch, after_write):
    api, daemon, path = scenario
    with opened(scenario) as store:
        actual = store.record_created

        def failed(value):
            if after_write:
                actual(value)
            raise OSError("fictional lost persistence acknowledgement")

        monkeypatch.setattr(store, "record_created", failed)
        with pytest.raises(ValueError, match=r"^stock_launcher_unavailable$"):
            api.launch_fresh_attempt(store, path)
        target = store.snapshot()
        assert (target.created_sha256 is not None) is after_write
        assert target.start_fence is None and "start" not in daemon.events


def test_uncertain_start_with_valid_fence_supervises_original_attempt_once(scenario):
    api, daemon, path = scenario
    daemon.start_after_fence = True
    with opened(scenario) as store:
        result = api.launch_fresh_attempt(store, path)
        assert result.start_monotonic_ns == 1000 * NS and result.term_deadline_ns == 1450 * NS
        assert daemon.events.count("start") == 1 and daemon.events.count("create") == 1
        assert store.snapshot().stopped_sha256 is not None


def test_failed_start_with_corrupt_fence_never_adopts_or_rewrites_it(scenario, monkeypatch):
    api, daemon, path = scenario
    actual = daemon.start_worker

    def failed(store):
        actual(store)
        target = store.snapshot()
        receipt = daemon.root / target.attempt.attempt_id / "start.json"
        raw = json.loads(receipt.read_bytes())
        raw["container_id"] = "a" * 64
        receipt.write_bytes(encoded(raw))
        raise ValueError("fictional corrupt receipt")

    monkeypatch.setattr(daemon, "start_worker", failed)
    with opened(scenario) as store:
        with pytest.raises(ValueError, match=r"^stock_launcher_unavailable$"):
            api.launch_fresh_attempt(store, path)
        assert "supervise" not in daemon.events and daemon.events.count("start") == 1


def test_successful_ack_without_a_durable_start_does_not_bypass_supervision(scenario, monkeypatch):
    api, daemon, path = scenario
    monkeypatch.setattr(daemon, "start_worker", lambda store: None)
    with opened(scenario) as store:
        with pytest.raises(ValueError, match=r"^stock_launcher_unavailable$"):
            api.launch_fresh_attempt(store, path)
        assert store.snapshot().start_fence is None and "supervise" not in daemon.events


def test_supervisor_failure_preserves_start_uncertainty_without_new_dispatch(scenario):
    api, daemon, path = scenario
    daemon.fail_at = "supervise"
    with opened(scenario) as store:
        with pytest.raises(ValueError, match=r"^stock_launcher_unavailable$"):
            api.launch_fresh_attempt(store, path)
        target = store.snapshot()
        assert target.start_fence is not None and target.stopped_sha256 is None
        assert daemon.events.count("create") == daemon.events.count("start") == 1


@pytest.mark.parametrize("after_write", [False, True])
def test_admission_failure_is_never_retried_into_create(scenario, monkeypatch, after_write):
    api, daemon, path = scenario
    with opened(scenario) as store:
        actual = store.begin

        def failed(release):
            if after_write:
                actual(release)
            raise OSError("fictional lost admission acknowledgement")

        monkeypatch.setattr(store, "begin", failed)
        with pytest.raises(ValueError, match=r"^stock_launcher_unavailable$"):
            api.launch_fresh_attempt(store, path)
        assert (store.snapshot() is not None) is after_write
        assert "create" not in daemon.events


def test_stopped_persistence_error_cannot_return_success_or_dispatch_again(scenario, monkeypatch):
    api, daemon, path = scenario
    with opened(scenario) as store:

        def failed(raw):
            raise OSError("fictional stopped durability failure")

        monkeypatch.setattr(store, "record_stopped", failed)
        with pytest.raises(ValueError, match=r"^stock_launcher_unavailable$"):
            api.launch_fresh_attempt(store, path)
        assert store.snapshot().stopped_sha256 is None
        assert daemon.events.count("create") == daemon.events.count("start") == 1
