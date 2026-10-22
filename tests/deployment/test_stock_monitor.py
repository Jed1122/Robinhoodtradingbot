"""Complete local observations alone can resolve stock incidents."""

import hashlib
import inspect
import json
import os
import runpy
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from infra.hybrid import stock_maintenance as module
from tests.deployment.test_stock_attempts import CID, IMAGE, RELEASE, encoded, stopped
from tests.deployment.test_stock_maintenance_process import CHECKOUT
from tests.deployment.test_stock_maintenance_process import release as _release
from tests.unit.runtime.test_stock_dashboard_export import data as _data
from tests.unit.runtime.test_stock_local_state import local as _local
from trading_bot.runtime.stock_dashboard_export import publish_stock_dashboard
from trading_bot.runtime.stock_incidents import StockIncidentSpool
from trading_bot.runtime.stock_local_state import read_local_stock_state

release = _release
data = _data
local = _local


@pytest.fixture
def observed(local, release, tmp_path, monkeypatch):
    export, loaded, projection, control, _, _ = local
    release = replace(release, config_hash=str(loaded.config_hash))
    publish_stock_dashboard(
        root=export,
        export=projection.model_copy(
            update={
                "code_hash": hashlib.sha256(
                    f"oci-image:{release.image_digest}".encode()
                ).hexdigest()
            }
        ),
    )
    maintenance_root = tmp_path.resolve() / "hybrid-stock-maintenance"
    maintenance_root.mkdir(mode=0o700)
    spool_root = maintenance_root / "incidents"
    spool_root.mkdir(mode=0o700)
    spool = StockIncidentSpool(spool_root)
    spool.initialize(now=module.datetime.now(module.UTC))
    receipt_root = maintenance_root / "receipts"
    receipt_root.mkdir(mode=0o700)
    lock = receipt_root / ".stock-receipts.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)

    @contextmanager
    def operations():
        yield SimpleNamespace(snapshot=lambda: None)

    monkeypatch.setattr(module, "operations", operations)
    monkeypatch.setattr(module, "load_release", lambda _path: release)
    monkeypatch.setattr(module, "load_stock_worker_configuration", lambda _path: loaded)
    original_statvfs = os.statvfs
    monkeypatch.setattr(module.os, "statvfs", lambda _path: original_statvfs(tmp_path))
    monkeypatch.setattr(
        module,
        "run_local_helper",
        lambda *args, **kwargs: read_local_stock_state(
            loaded=loaded,
            control_dir=control,
            export_dir=export,
            now=module.datetime.now(module.UTC),
        ),
    )
    monkeypatch.setattr(
        module,
        "_capture",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=b"ActiveState=active\nUnitFileState=enabled\n"
        ),
    )
    return release, spool_root, receipt_root, spool


def run(observed):
    release, spool_root, receipt_root, _ = observed
    return module.monitor_stock(
        release.attestation_path.parent / "manifest.json",
        checkout=CHECKOUT,
        spool_root=spool_root,
        receipt_root=receipt_root,
    )


def active(spool):
    return {row["code"] for row in spool.read()["incidents"] if row["resolved_at"] is None}


def test_production_default_layout_keeps_closed_stores_as_siblings(observed):
    defaults = inspect.signature(module.monitor_stock).parameters
    spool = defaults["spool_root"].default
    receipts = defaults["receipt_root"].default
    parent = Path("/var/lib/hybrid-stock-maintenance")
    assert spool == parent / "incidents"
    assert receipts == parent / "receipts"
    assert run(observed)["status"] == "observed"


@pytest.mark.parametrize("fault", ["missing", "config_hash", "code_hash", "cadence"])
def test_unusable_projection_preserves_previous_unresolved_research_incidents(
    observed, monkeypatch, fault
):
    previous = {"source_stale", "worker_failed", "worker_result_stale"}
    observed[-1].update(tuple(sorted(previous)), now=module.datetime.now(module.UTC))
    original = module.run_local_helper

    def unusable(*args, **kwargs):
        value = original(*args, **kwargs)
        if fault == "missing":
            value["projection"] = None
        elif fault == "cadence":
            claimed = module.datetime.now(module.UTC) - timedelta(seconds=120)
            value["projection"]["worker"].update(
                last_claim_at=claimed.isoformat(),
                last_result_at=(claimed + timedelta(seconds=30)).isoformat(),
                phase="discovery",
                status="succeeded",
                reason="complete",
                next_eligible_at=(claimed + timedelta(seconds=900)).isoformat(),
            )
        else:
            value["projection"][fault] = "f" * 64
        # Identity/cadence faults remain structurally valid JSON projections;
        # only comparison with the installed release makes them unusable.
        module._local(value, now=module.datetime.now(module.UTC))
        return value

    monkeypatch.setattr(module, "run_local_helper", unusable)
    assert run(observed)["status"] == "unavailable"
    assert previous | {"observation_invalid"} <= active(observed[-1])


def test_paused_state_observes_backup_gaps_without_research_false_alarm(observed):
    assert run(observed)["status"] == "observed"
    assert active(observed[-1]) == {"backup_missing", "offhost_copy_missing", "restore_missing"}


def test_transient_helper_failure_preserves_active_incidents(observed, monkeypatch):
    run(observed)

    def failed(*args, **kwargs):
        raise ValueError("private fixture diagnostic")

    monkeypatch.setattr(module, "run_local_helper", failed)
    result = run(observed)
    assert result["status"] == "unavailable" and result["live_enabled"] is False
    assert active(observed[-1]) == {
        "backup_missing",
        "offhost_copy_missing",
        "restore_missing",
        "observation_invalid",
    }
    assert "private fixture" not in str(result)


@pytest.mark.parametrize(
    "failure", ["control_digest", "control_extra", "version", "extra", "projection"]
)
def test_malformed_helper_cannot_resolve_incidents(observed, monkeypatch, failure):
    run(observed)
    original = module.run_local_helper

    def bad(*args, **kwargs):
        value = original(*args, **kwargs)
        if failure == "control_digest":
            value["control_sha256"] = "a" * 64
        elif failure == "control_extra":
            value["control"]["live_enabled"] = True
        elif failure == "version":
            value["version"] = True
        elif failure == "extra":
            value["foo"] = 1
        else:
            value["projection"] = {"live_enabled": True}
        return value

    monkeypatch.setattr(module, "run_local_helper", bad)
    assert run(observed)["status"] == "unavailable"
    assert "backup_missing" in active(observed[-1])
    assert "observation_invalid" in active(observed[-1])


def test_invalid_receipt_store_keeps_uncertainty(observed):
    run(observed)
    unknown = observed[2] / "unknown"
    unknown.write_bytes(b"preserve")
    unknown.chmod(0o600)
    assert run(observed)["status"] == "unavailable"
    assert unknown.read_bytes() == b"preserve"
    assert "observation_invalid" in active(observed[-1])


@pytest.fixture
def owned_worker(observed, monkeypatch):
    """Keep the real ownership/terminal decoder behind a fictional Engine read."""
    attempt = SimpleNamespace(attempt_id="a" * 32, image_digest=IMAGE, release_id=RELEASE)
    target = SimpleNamespace(
        stopped_sha256="b" * 64,
        abandoned_sha256=None,
        container_id=CID,
        attempt=attempt,
    )
    reads = []
    metadata = stopped(attempt)

    @contextmanager
    def operations():
        yield SimpleNamespace(snapshot=lambda: target)

    class Engine:
        def inspect(self, container_id):
            reads.append(container_id)
            return encoded(metadata)

    monkeypatch.setattr(module, "operations", operations)
    monkeypatch.setattr(module, "StockEngineReader", Engine)
    return target, metadata, reads


@pytest.mark.parametrize("fault", ["missing_stop", "missing_cid", "running", "foreign_id"])
def test_unresolved_or_unowned_worker_observation_preserves_incidents(
    observed, owned_worker, fault
):
    target, metadata, _ = owned_worker
    observed[-1].update(("source_stale",), now=module.datetime.now(module.UTC))
    if fault == "missing_stop":
        target.stopped_sha256 = None
    elif fault == "missing_cid":
        target.container_id = None
    elif fault == "running":
        metadata["State"].update(Status="running", Running=True, Pid=42)
    else:
        metadata["Id"] = "e" * 64
    assert run(observed)["status"] == "unavailable"
    assert {"source_stale", "observation_invalid"} <= active(observed[-1])


@pytest.mark.parametrize("error", ["oom", "daemon_error"])
def test_actual_owned_worker_error_remains_an_incident_even_with_zero_exit(
    observed, owned_worker, error
):
    _, metadata, reads = owned_worker
    if error == "oom":
        metadata["State"]["OOMKilled"] = True
    else:
        metadata["State"]["Error"] = "private fictional daemon diagnostic"
    result = run(observed)
    assert result["status"] == "observed"
    assert reads == [CID]
    assert "worker_exit_failed" in active(observed[-1])
    assert "private" not in str(result)


def test_abandoned_before_dispatch_does_not_invent_worker_exit(observed, owned_worker):
    target, _, reads = owned_worker
    target.abandoned_sha256 = "c" * 64
    assert run(observed)["status"] == "observed"
    assert reads == []
    assert "worker_exit_failed" not in active(observed[-1])


def test_future_projection_is_uncertainty_without_resolving_old_incidents(observed, monkeypatch):
    observed[-1].update(("source_stale",), now=module.datetime.now(module.UTC))
    original = module.run_local_helper

    def future(*args, **kwargs):
        value = original(*args, **kwargs)
        value["projection"]["generated_at"] = (
            module.datetime.now(module.UTC) + timedelta(hours=1)
        ).isoformat()
        return value

    monkeypatch.setattr(module, "run_local_helper", future)
    assert run(observed)["status"] == "unavailable"
    assert {"source_stale", "observation_invalid"} <= active(observed[-1])


@pytest.mark.parametrize(
    "raw",
    [
        b"ActiveState=active\n",
        b"ActiveState=unknown\nUnitFileState=enabled\n",
        b"ActiveState=active\nUnitFileState=unknown\n",
        b"ActiveState=active\nActiveState=active\n",
    ],
)
def test_incomplete_or_unknown_systemd_state_cannot_clear_incidents(observed, monkeypatch, raw):
    observed[-1].update(("timer_inactive",), now=module.datetime.now(module.UTC))
    monkeypatch.setattr(module, "_capture", lambda *args, **kwargs: SimpleNamespace(stdout=raw))
    assert run(observed)["status"] == "unavailable"
    assert {"timer_inactive", "observation_invalid"} <= active(observed[-1])


def test_current_release_configuration_mismatch_stops_before_helper(observed, monkeypatch):
    release = replace(observed[0], config_hash="f" * 64)
    monkeypatch.setattr(module, "load_release", lambda *args: release)
    monkeypatch.setattr(
        module, "run_local_helper", lambda *args, **kwargs: pytest.fail("must not read helper")
    )
    assert run(observed)["status"] == "unavailable"
    assert "observation_invalid" in active(observed[-1])


def test_malformed_incident_history_is_never_reset_by_monitor(observed):
    history = observed[1] / "stock-incidents.json"
    history.write_bytes(b"private malformed incident fixture")
    with pytest.raises(ValueError, match=r"^stock_monitor_unavailable$"):
        run(observed)
    assert history.read_bytes() == b"private malformed incident fixture"


def test_monitor_cli_denies_any_live_enabled_result(monkeypatch, capsys):
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module.sys, "argv", ["stock_maintenance", "monitor", "/fixture/manifest"])
    monkeypatch.setattr(
        module,
        "monitor_stock",
        lambda *args, **kwargs: {"status": "observed", "live_enabled": True},
    )
    assert module.main() == 2
    assert json.loads(capsys.readouterr().out) == {
        "live_enabled": False,
        "status": "stock_maintenance_unavailable",
    }


def test_monitor_module_entry_requires_fixed_arguments_before_host_access(monkeypatch, capsys):
    monkeypatch.setattr(module.sys, "argv", ["stock_maintenance"])
    with pytest.raises(SystemExit) as exited:
        runpy.run_path(module.__file__, run_name="__main__")
    assert exited.value.code == 2
    assert json.loads(capsys.readouterr().out)["status"] == "stock_maintenance_unavailable"
