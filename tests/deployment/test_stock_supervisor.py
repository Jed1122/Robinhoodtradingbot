"""Actual receipt protocol with fictional daemon boundaries and virtual time only."""

import hashlib
import importlib
import json
import os
import signal
from dataclasses import dataclass
from pathlib import Path

import pytest

from infra.hybrid import stock_attempts
from infra.hybrid.stock_prestart import CreatedContainer
from infra.hybrid.stock_release import RELEASE_ROOT, StockRelease, _policy

NS = 1_000_000_000
IMAGE = "sha256:" + "b" * 64
RELEASE = "d" * 64
CID = "f" * 64
BOOT = "11111111-2222-4333-8444-555555555555"


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def module():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_supervisor.py"
    assert path.is_file(), "Active stock worker supervision is not implemented"
    return importlib.import_module("infra.hybrid.stock_supervisor")


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    root = tmp_path.resolve() / "operations"
    stock_attempts._initialize(root, trusted_uid=os.geteuid())
    clock = {"boot_id": BOOT, "utc": "2026-10-21T21:00:00+00:00", "monotonic_ns": 1000 * NS}
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
    dispatch_prepared(store, scenario)
    store.record_created(
        CreatedContainer(CID, intent.attempt_id, RELEASE, IMAGE, "c" * 64, intent.compose_sha256)
    )
    return intent, store.prepare_start()


def dispatch_prepared(store, scenario):
    claim = store.claim_create(scenario[2])
    fence = store.prepare_create(claim, "a" * 64, scenario[1]["monotonic_ns"] + 5 * NS)
    store.check_create_fence(fence)


def observation(intent, *, status="running", exit_code=0, oom=False, error=""):
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
            "Status": status,
            "Running": status == "running",
            "Paused": False,
            "Restarting": False,
            "OOMKilled": oom,
            "Dead": status == "dead",
            "Pid": 42 if status == "running" else 0,
            "ExitCode": exit_code,
            "Error": error,
            "StartedAt": "0001-01-01T00:00:00Z" if status == "created" else "2026-10-21T21:00:01Z",
            "FinishedAt": "0001-01-01T00:00:00Z"
            if status in {"running", "created"}
            else "2026-10-21T21:00:02Z",
        },
    }


@dataclass
class Action:
    delay: int = 0
    state: str | None = None
    fail: bool = False


class Daemon:
    """Model only the bounded external I/O; controller and durable store stay real."""

    def __init__(self, scenario, intent):
        self.scenario, self.intent = scenario, intent
        self.state, self.exit_code, self.oom, self.error = "running", 0, False, ""
        self.actions = {"TERM": Action(), "KILL": Action(state="exited")}
        self.inspections, self.signals, self.sleeps = [], [], []
        self.rows = []
        self.on_read = None
        self.handlers = {signal.SIGTERM: signal.SIG_DFL, signal.SIGINT: signal.default_int_handler}
        self.initial_handlers = self.handlers.copy()

    @property
    def now(self):
        return self.scenario[1]["monotonic_ns"]

    def advance(self, seconds):
        self.scenario[1]["monotonic_ns"] += int(seconds * NS)

    def install(self, monkeypatch):
        api = module()
        monkeypatch.setattr(api, "_production_store", lambda store: None)
        monkeypatch.setattr(api, "_clock", lambda: self.scenario[1].copy())
        monkeypatch.setattr(api.time, "sleep", self.sleep)
        monkeypatch.setattr(api.signal, "getsignal", lambda number: self.handlers[number])

        def handler(number, callback):
            old = self.handlers[number]
            self.handlers[number] = callback
            return old

        monkeypatch.setattr(api.signal, "signal", handler)
        boundary = self

        class Reader:
            def inspect(self, cid, *, not_after_ns):
                return boundary.inspect(cid, not_after_ns)

        class Terminator:
            def signal_active(self, store, name, *, not_after_ns):
                return boundary.send(name, not_after_ns)

        monkeypatch.setattr(api, "StockEngineReader", Reader)
        monkeypatch.setattr(api, "StockEngineTerminator", Terminator)
        return api

    def sleep(self, seconds):
        assert 0 < seconds <= 1
        self.sleeps.append(seconds)
        self.advance(seconds)

    def inspect(self, cid, cap):
        assert cid == CID and type(cap) is int and self.now < cap
        self.inspections.append((self.now, cap))
        if self.on_read is not None:
            self.on_read()
        row = self.rows.pop(0) if self.rows else self.state
        if isinstance(row, Exception):
            raise row
        if isinstance(row, tuple):
            seconds, row = row
            finish = self.now + int(seconds * NS)
            if finish >= cap:
                self.scenario[1]["monotonic_ns"] = cap
                raise ValueError("fictional phase I/O exhausted")
            self.advance(seconds)
        if type(row) is bytes:
            return row
        return encoded(
            observation(
                self.intent, status=row, exit_code=self.exit_code, oom=self.oom, error=self.error
            )
        )

    def send(self, name, cap):
        assert name in {"TERM", "KILL"} and self.now < cap
        self.signals.append((name, self.now, cap))
        if self.state != "running":
            raise ValueError("fictional running profile unavailable")
        action = self.actions[name]
        self.scenario[1]["monotonic_ns"] = min(self.now + action.delay * NS, cap)
        if action.state is not None:
            self.state = action.state
            self.exit_code = 137 if name == "KILL" else 0
        if action.fail:
            raise ValueError("fictional response uncertainty")


def assert_closed_launch(store, scenario, fence):
    for operation in [
        store.prepare_start,
        lambda: store.begin(scenario[2]),
        lambda: store.check_start_fence(fence),
    ]:
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            operation()


@pytest.mark.parametrize(
    "code,oom,error",
    [(0, False, ""), (7, False, ""), (137, True, ""), (1, False, "private daemon diagnostic")],
)
def test_natural_exit_records_real_receipt_without_claiming_research_success(
    scenario, monkeypatch, code, oom, error
):
    with opened(scenario) as store:
        intent, fence = started(store, scenario)
        daemon = Daemon(scenario, intent)
        daemon.state, daemon.exit_code, daemon.oom, daemon.error = "exited", code, oom, error
        api = daemon.install(monkeypatch)
        result = api.supervise_active(store)
        assert result.reason == "natural_exit" and result.exit_code == code
        assert result.oom_killed is oom and result.error_present is bool(error)
        assert result.term_deadline_ns == fence.term_deadline_ns
        assert not result.term_attempted and not result.kill_attempted and not daemon.signals
        receipt = json.loads((scenario[0] / intent.attempt_id / "stopped.json").read_bytes())
        assert receipt["exit_code"] == code and receipt["start_fence_present"] is True
        assert "private daemon diagnostic" not in repr(result)
        assert daemon.handlers == daemon.initial_handlers
        assert_closed_launch(store, scenario, fence)


def test_deadline_initiates_term_once_and_retains_original_timing(scenario, monkeypatch):
    with opened(scenario) as store:
        intent, fence = started(store, scenario)
        before = (scenario[0] / intent.attempt_id / "start.json").read_bytes()
        daemon = Daemon(scenario, intent)
        daemon.actions["TERM"] = Action(state="exited")
        result = daemon.install(monkeypatch).supervise_active(store)
        assert result.reason == "deadline" and result.term_attempted and not result.kill_attempted
        assert daemon.signals == [
            ("TERM", fence.term_deadline_ns, fence.term_deadline_ns + 10 * NS)
        ]
        assert all(cap == fence.term_deadline_ns for _, cap in daemon.inspections[:-1])
        assert (scenario[0] / intent.attempt_id / "start.json").read_bytes() == before


@pytest.mark.parametrize("delay,uncertain", [(0, False), (8, False), (5, True)])
def test_term_delay_or_uncertainty_never_renews_grace(scenario, monkeypatch, delay, uncertain):
    with opened(scenario) as store:
        intent, fence = started(store, scenario)
        daemon = Daemon(scenario, intent)
        daemon.actions["TERM"] = Action(delay=delay, fail=uncertain)
        result = daemon.install(monkeypatch).supervise_active(store)
        assert result.term_attempted and result.kill_attempted and result.exit_code == 137
        assert daemon.signals == [
            ("TERM", fence.term_deadline_ns, fence.term_deadline_ns + 10 * NS),
            ("KILL", fence.term_deadline_ns + 10 * NS, fence.term_deadline_ns + 15 * NS),
        ]
        assert daemon.now <= fence.term_deadline_ns + 20 * NS


def test_kill_uncertainty_can_be_reconciled_by_later_actual_exit(scenario, monkeypatch):
    with opened(scenario) as store:
        intent, fence = started(store, scenario)
        daemon = Daemon(scenario, intent)
        daemon.actions["KILL"] = Action(delay=5, state="exited", fail=True)
        result = daemon.install(monkeypatch).supervise_active(store)
        assert result.kill_attempted and result.exit_code == 137
        assert daemon.now == fence.term_deadline_ns + 15 * NS
        assert len(daemon.signals) == 2
        assert (scenario[0] / intent.attempt_id / "stopped.json").is_file()


def test_unobserved_stop_ends_unresolved_without_renewal_or_terminal_receipt(scenario, monkeypatch):
    with opened(scenario) as store:
        intent, fence = started(store, scenario)
        daemon = Daemon(scenario, intent)
        daemon.actions["KILL"] = Action(fail=True)
        api = daemon.install(monkeypatch)
        with pytest.raises(ValueError, match=r"^stock_supervisor_unavailable$"):
            api.supervise_active(store)
        assert daemon.now == fence.term_deadline_ns + 20 * NS
        assert len(daemon.signals) == 2
        assert not (scenario[0] / intent.attempt_id / "stopped.json").exists()
        assert daemon.handlers == daemon.initial_handlers
        assert_closed_launch(store, scenario, fence)


def test_poll_near_run_end_cannot_obtain_a_new_full_io_window(scenario, monkeypatch):
    with opened(scenario) as store:
        intent, fence = started(store, scenario)
        scenario[1]["monotonic_ns"] = fence.term_deadline_ns - NS
        daemon = Daemon(scenario, intent)
        daemon.rows = [(5, "running")]
        daemon.actions["TERM"] = Action(state="exited")
        result = daemon.install(monkeypatch).supervise_active(store)
        assert result.reason == "deadline"
        assert daemon.signals[0][1] == fence.term_deadline_ns


@pytest.mark.parametrize(
    "mode", ["reopened", "old_boot", "clock_rollback", "overdue", "grace_overdue"]
)
def test_recovery_never_receives_a_fresh_run_allowance(scenario, monkeypatch, mode):
    with opened(scenario) as store:
        intent, fence = started(store, scenario)
    if mode == "old_boot":
        scenario[1]["boot_id"] = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        scenario[1]["monotonic_ns"] = 100 * NS
    elif mode == "clock_rollback":
        scenario[1]["monotonic_ns"] = fence.start_monotonic_ns - NS
    elif mode == "overdue":
        scenario[1]["monotonic_ns"] = fence.term_deadline_ns + NS
    elif mode == "grace_overdue":
        scenario[1]["monotonic_ns"] = fence.term_deadline_ns + 30 * NS
    began = scenario[1]["monotonic_ns"]
    before = (scenario[0] / intent.attempt_id / "start.json").read_bytes()
    with opened(scenario) as store:
        daemon = Daemon(scenario, intent)
        daemon.actions["TERM"] = Action(state="exited")
        result = daemon.install(monkeypatch).supervise_active(store)
        assert result.reason == "recovery" and daemon.signals[0][1] == began
        assert daemon.now <= began + 20 * NS
        assert result.term_deadline_ns == fence.term_deadline_ns
        if mode == "grace_overdue":
            assert daemon.signals[0][0] == "KILL"
        assert (scenario[0] / intent.attempt_id / "start.json").read_bytes() == before
        assert_closed_launch(store, scenario, fence)


def test_lost_start_ack_in_owning_session_uses_persisted_fence_once(scenario, monkeypatch):
    with opened(scenario) as store:
        intent, fence = started(store, scenario)
        # No Engine ACK is assumed: prepare_start wrote only the local durable fence.
        daemon = Daemon(scenario, intent)
        daemon.rows = ["running", "exited"]
        result = daemon.install(monkeypatch).supervise_active(store)
        assert result.reason == "natural_exit" and not daemon.signals
        assert daemon.now == fence.start_monotonic_ns + NS
        assert_closed_launch(store, scenario, fence)


@pytest.mark.parametrize("stage", ["empty", "intent", "created", "pending_start"])
def test_missing_or_pending_start_state_cannot_become_terminal_authority(
    scenario, monkeypatch, stage
):
    with opened(scenario) as store:
        intent = None
        if stage != "empty":
            intent = store.begin(scenario[2])
            if stage != "intent":
                dispatch_prepared(store, scenario)
                store.record_created(
                    CreatedContainer(
                        CID, intent.attempt_id, RELEASE, IMAGE, "c" * 64, intent.compose_sha256
                    )
                )
            if stage == "pending_start":
                store.prepare_start()
        daemon = Daemon(scenario, intent)
        daemon.state = "created"
        api = daemon.install(monkeypatch)
        with pytest.raises(ValueError, match=r"^stock_supervisor_unavailable$"):
            api.supervise_active(store)
        if stage != "empty":
            assert not (scenario[0] / intent.attempt_id / "stopped.json").exists()
        if stage != "pending_start":
            assert not daemon.inspections and not daemon.signals


@pytest.mark.parametrize("event", [signal.SIGTERM, signal.SIGINT])
def test_shutdown_intent_uses_one_fixed_earlier_cleanup_window(scenario, monkeypatch, event):
    with opened(scenario) as store:
        intent, fence = started(store, scenario)
        daemon = Daemon(scenario, intent)
        began = daemon.now
        daemon.on_read = lambda: daemon.handlers[event](event, None)
        result = daemon.install(monkeypatch).supervise_active(store)
        assert result.reason == "shutdown" and result.term_attempted and result.kill_attempted
        assert daemon.now <= began + 21 * NS
        assert len(daemon.signals) == 2
        assert daemon.signals[1][1] == daemon.signals[0][1] + 10 * NS
        assert daemon.handlers == daemon.initial_handlers
        assert result.term_deadline_ns == fence.term_deadline_ns


def test_stopped_receipt_failure_is_not_treated_as_running_and_retried(scenario, monkeypatch):
    with opened(scenario) as store:
        intent, _ = started(store, scenario)
        daemon = Daemon(scenario, intent)
        daemon.state = "exited"
        api = daemon.install(monkeypatch)

        def fail(raw):
            raise OSError("private local write error")

        monkeypatch.setattr(store, "record_stopped", fail)
        with pytest.raises(ValueError, match=r"^stock_supervisor_unavailable$"):
            api.supervise_active(store)
        assert len(daemon.inspections) == 1 and not daemon.signals
        assert not (scenario[0] / intent.attempt_id / "stopped.json").exists()
        assert daemon.handlers == daemon.initial_handlers


@pytest.mark.parametrize("change", ["boot", "rollback"])
def test_local_clock_discontinuity_does_not_renew_selected_phase(scenario, monkeypatch, change):
    with opened(scenario) as store:
        intent, _ = started(store, scenario)
        daemon = Daemon(scenario, intent)

        def drift():
            if change == "boot":
                scenario[1]["boot_id"] = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
            else:
                scenario[1]["monotonic_ns"] -= NS

        daemon.on_read = drift
        with pytest.raises(ValueError, match=r"^stock_supervisor_unavailable$"):
            daemon.install(monkeypatch).supervise_active(store)
        assert len(daemon.inspections) == 1 and not daemon.signals
        assert not (scenario[0] / intent.attempt_id / "stopped.json").exists()
        assert daemon.handlers == daemon.initial_handlers


def test_production_guard_rejects_fictional_root_without_daemon(scenario, monkeypatch):
    api = module()
    monkeypatch.setattr(
        api, "StockEngineReader", lambda: pytest.fail("Untrusted root reached daemon")
    )
    with opened(scenario) as store:
        started(store, scenario)
        with pytest.raises(ValueError, match=r"^stock_supervisor_unavailable$"):
            api.supervise_active(store)


def test_failed_run_observation_triggers_early_fixed_cleanup_without_fabricated_exit(
    scenario, monkeypatch
):
    with opened(scenario) as store:
        intent, fence = started(store, scenario)
        daemon = Daemon(scenario, intent)
        began = daemon.now
        daemon.rows = [ValueError("private missing container response")]
        result = daemon.install(monkeypatch).supervise_active(store)
        assert result.reason == "observation_failed" and result.exit_code == 137
        assert daemon.signals == [
            ("TERM", began, began + 10 * NS),
            ("KILL", began + 10 * NS, began + 15 * NS),
        ]
        assert daemon.now < fence.term_deadline_ns


@pytest.mark.parametrize("kind", ["wrong_cid", "wrong_image", "paused", "unavailable", "malformed"])
def test_untrusted_or_unavailable_observations_cannot_record_terminal_evidence(
    scenario, monkeypatch, kind
):
    with opened(scenario) as store:
        intent, _ = started(store, scenario)
        daemon = Daemon(scenario, intent)
        observed = observation(intent, status="exited")
        if kind == "wrong_cid":
            observed["Id"] = "a" * 64
        elif kind == "wrong_image":
            observed["Image"] = "sha256:" + "a" * 64
        elif kind == "paused":
            observed["State"]["Paused"] = True
        raw = b"{not_json" if kind == "malformed" else encoded(observed)
        daemon.rows = (
            [ValueError("private unavailable")] * 50 if kind == "unavailable" else [raw] * 50
        )
        with pytest.raises(ValueError, match=r"^stock_supervisor_unavailable$"):
            daemon.install(monkeypatch).supervise_active(store)
        assert not (scenario[0] / intent.attempt_id / "stopped.json").exists()
        assert daemon.now <= 1020 * NS
        assert len(daemon.signals) == 2 and daemon.handlers == daemon.initial_handlers


def test_store_drift_after_inspection_never_yields_terminal_authority(scenario, monkeypatch):
    with opened(scenario) as store:
        intent, _ = started(store, scenario)
        daemon = Daemon(scenario, intent)
        daemon.state = "exited"
        path = scenario[0] / intent.attempt_id / "start.json"
        receipt = json.loads(path.read_bytes())
        receipt["utc"] = "2026-10-21T21:00:02+00:00"
        daemon.on_read = lambda: path.write_bytes(encoded(receipt))
        with pytest.raises(ValueError, match=r"^stock_supervisor_unavailable$"):
            daemon.install(monkeypatch).supervise_active(store)
        assert len(daemon.inspections) == 1
        assert not (scenario[0] / intent.attempt_id / "stopped.json").exists()
        assert daemon.handlers == daemon.initial_handlers


def test_handler_setup_failure_restores_first_handler_before_daemon_work(scenario, monkeypatch):
    with opened(scenario) as store:
        intent, _ = started(store, scenario)
        daemon = Daemon(scenario, intent)
        api = daemon.install(monkeypatch)
        installed = []

        def install(number, callback):
            installed.append(number)
            if number == signal.SIGINT:
                raise ValueError("fictional unavailable signal registration")
            old = daemon.handlers[number]
            daemon.handlers[number] = callback
            return old

        monkeypatch.setattr(api.signal, "signal", install)
        with pytest.raises(ValueError, match=r"^stock_supervisor_unavailable$"):
            api.supervise_active(store)
        assert installed == [signal.SIGTERM, signal.SIGINT, signal.SIGTERM]
        assert daemon.handlers == daemon.initial_handlers
        assert not daemon.inspections and not daemon.signals


def test_handler_restore_failure_still_attempts_both_and_returns_no_result(scenario, monkeypatch):
    with opened(scenario) as store:
        intent, _ = started(store, scenario)
        daemon = Daemon(scenario, intent)
        daemon.state = "exited"
        api = daemon.install(monkeypatch)
        restored = []

        def install(number, callback):
            if callback == daemon.initial_handlers[number]:
                restored.append(number)
                if number == signal.SIGINT:
                    raise OSError("fictional restoration failure")
            old = daemon.handlers[number]
            daemon.handlers[number] = callback
            return old

        monkeypatch.setattr(api.signal, "signal", install)
        with pytest.raises(ValueError, match=r"^stock_supervisor_unavailable$"):
            api.supervise_active(store)
        assert restored == [signal.SIGINT, signal.SIGTERM]
        assert daemon.handlers[signal.SIGTERM] == daemon.initial_handlers[signal.SIGTERM]


def test_past_phase_result_from_an_invalid_boundary_is_not_admitted(scenario, monkeypatch):
    with opened(scenario) as store:
        intent, fence = started(store, scenario)
        scenario[1]["monotonic_ns"] = fence.term_deadline_ns - NS
        daemon = Daemon(scenario, intent)
        daemon.state = "exited"

        def late():
            # Stress a misbehaving boundary: the actual reader separately rejects this.
            scenario[1]["monotonic_ns"] = fence.term_deadline_ns + NS

        daemon.on_read = late
        result = daemon.install(monkeypatch).supervise_active(store)
        assert result.reason == "deadline" and result.term_attempted
        assert len(daemon.inspections) == 2
        assert result.term_deadline_ns == fence.term_deadline_ns


@pytest.mark.parametrize("mode", ["read", "read_error", "wakeup"])
@pytest.mark.parametrize("offset", [11, 16, 30])
def test_active_run_stall_never_renews_original_cleanup_caps(scenario, monkeypatch, mode, offset):
    with opened(scenario) as store:
        intent, fence = started(store, scenario)
        daemon = Daemon(scenario, intent)
        api = daemon.install(monkeypatch)
        late = fence.term_deadline_ns + offset * NS
        fired = False

        def stall():
            nonlocal fired
            if not fired:
                scenario[1]["monotonic_ns"] = late
                fired = True

        if mode == "wakeup":

            def wake(seconds):
                if not fired:
                    stall()
                else:
                    daemon.sleep(seconds)

            monkeypatch.setattr(api.time, "sleep", wake)
        else:
            daemon.on_read = stall
            if mode == "read_error":
                daemon.rows = [ValueError("fictional delayed timeout")]

        if offset == 11:
            result = api.supervise_active(store)
            assert result.reason == "deadline" and result.kill_attempted
            assert daemon.signals == [("KILL", late, fence.term_deadline_ns + 15 * NS)]
            assert daemon.now <= fence.term_deadline_ns + 20 * NS
        else:
            with pytest.raises(ValueError, match=r"^stock_supervisor_unavailable$"):
                api.supervise_active(store)
            assert not daemon.signals
            assert not (scenario[0] / intent.attempt_id / "stopped.json").exists()
        assert daemon.handlers == daemon.initial_handlers
