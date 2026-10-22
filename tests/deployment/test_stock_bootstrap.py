"""Boot scheduling never replays recovery or bypasses paused/unknown authority."""

import json
import runpy
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from infra.hybrid import stock_bootstrap as module
from tests.deployment.test_stock_attempts import CID, IMAGE, RELEASE, encoded, stopped
from tests.deployment.test_stock_maintenance_process import CHECKOUT
from tests.deployment.test_stock_maintenance_process import release as _release

release = _release


@pytest.fixture
def native(release, monkeypatch):
    calls = []
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module, "load_release", lambda _path: release)
    store = SimpleNamespace(snapshot=lambda: None)

    @contextmanager
    def operations():
        calls.append("lock")
        yield store
        calls.append("unlock")

    monkeypatch.setattr(module, "operations", operations)
    monkeypatch.setattr(
        module,
        "run_local_helper",
        lambda *args, **kwargs: {
            "status": "running",
            "control_sha256": "e" * 64,
            "control_id": "f" * 32,
            "generation": 1,
        },
    )

    def capture(argv, **kwargs):
        calls.append(argv)
        body = b"ActiveState=active\nUnitFileState=enabled\n" if "show" in argv else b""
        return SimpleNamespace(stdout=body, stderr=b"")

    monkeypatch.setattr(module, "_capture", capture)
    return calls, store


def test_bootstrap_releases_nonblocking_worker_lock_before_single_queue(native, release):
    calls, _ = native
    result = module.bootstrap_research(
        release.attestation_path.parent / "manifest.json", checkout=CHECKOUT
    )
    assert result == {"status": "queued", "live_enabled": False}
    assert calls[0] == "lock" and calls[-2] == "unlock"
    assert sum("start" in item for item in calls if isinstance(item, tuple)) == 1
    assert calls[-1] == (
        "/usr/bin/systemctl",
        "--no-block",
        "start",
        "hybrid-stock-research.service",
    )


def test_unfinished_attempt_cannot_dispatch_a_new_cycle(native, release):
    calls, store = native
    store.snapshot = lambda: SimpleNamespace(stopped_sha256=None, abandoned_sha256=None)
    with pytest.raises(ValueError):
        module.bootstrap_research(
            release.attestation_path.parent / "manifest.json", checkout=CHECKOUT
        )
    assert not any(isinstance(item, tuple) and "start" in item for item in calls)


@pytest.mark.parametrize("failure", ["denied", "malformed", "extra", "generation", "control_id"])
def test_invalid_or_paused_grant_never_dispatches(native, release, monkeypatch, failure):
    calls, _ = native

    def helper(*args, **kwargs):
        if failure == "denied":
            raise ValueError("private fixture error")
        value = {
            "status": "running",
            "control_sha256": "e" * 64,
            "control_id": "f" * 32,
            "generation": 1,
        }
        if failure == "malformed":
            value["status"] = "paused"
        elif failure == "extra":
            value["enable_live"] = True
        elif failure == "generation":
            value["generation"] = True
        else:
            value["control_id"] = "invalid"
        return value

    monkeypatch.setattr(module, "run_local_helper", helper)
    with pytest.raises(ValueError, match="stock_bootstrap_unavailable"):
        module.bootstrap_research(
            release.attestation_path.parent / "manifest.json", checkout=CHECKOUT
        )
    assert not any(isinstance(item, tuple) and "start" in item for item in calls)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"ActiveState=inactive\nUnitFileState=enabled\n",
        b"ActiveState=active\nUnitFileState=disabled\n",
        b"ActiveState=active\nUnitFileState=enabled\nUnitFileState=enabled\n",
    ],
)
def test_inactive_disabled_or_unknown_timer_never_dispatches(native, release, monkeypatch, raw):
    calls, _ = native
    monkeypatch.setattr(module, "_capture", lambda *args, **kwargs: SimpleNamespace(stdout=raw))
    with pytest.raises(ValueError):
        module.bootstrap_research(
            release.attestation_path.parent / "manifest.json", checkout=CHECKOUT
        )
    assert not any(isinstance(item, tuple) and "start" in item for item in calls)


def test_ambiguous_queue_failure_is_not_retried(native, release, monkeypatch):
    calls, _ = native
    original = module._capture

    def capture(argv, **kwargs):
        if "start" in argv:
            calls.append("ambiguous_queue")
            raise ValueError("private systemd error")
        return original(argv, **kwargs)

    monkeypatch.setattr(module, "_capture", capture)
    with pytest.raises(ValueError):
        module.bootstrap_research(
            release.attestation_path.parent / "manifest.json", checkout=CHECKOUT
        )
    assert calls.count("ambiguous_queue") == 1


@pytest.fixture
def owned_terminal(native, monkeypatch):
    """Only daemon I/O is fictional; the production terminal verifier still runs."""
    calls, store = native
    attempt = SimpleNamespace(attempt_id="a" * 32, image_digest=IMAGE, release_id=RELEASE)
    target = SimpleNamespace(
        stopped_sha256="b" * 64,
        abandoned_sha256=None,
        container_id=CID,
        attempt=attempt,
    )
    store.snapshot = lambda: target
    metadata = stopped(attempt)

    class Engine:
        def inspect(self, container_id):
            calls.append(("inspect", container_id))
            return encoded(metadata)

    monkeypatch.setattr(module, "StockEngineReader", Engine)
    return calls, target, metadata


def test_owned_terminal_must_be_independently_inspected_before_boot_dispatch(
    owned_terminal, release
):
    calls, _, _ = owned_terminal
    result = module.bootstrap_research(
        release.attestation_path.parent / "manifest.json", checkout=CHECKOUT
    )
    assert result["status"] == "queued"
    inspection = ("inspect", CID)
    assert calls.count(inspection) == 1
    queue = ("/usr/bin/systemctl", "--no-block", "start", "hybrid-stock-research.service")
    assert calls.index(inspection) < calls.index(queue)


@pytest.mark.parametrize("fault", ["missing_cid", "running", "foreign_id", "foreign_labels"])
def test_persisted_stop_receipt_cannot_bypass_actual_owned_terminal_gate(
    owned_terminal, release, monkeypatch, fault
):
    calls, target, metadata = owned_terminal
    if fault == "missing_cid":
        target.container_id = None
    elif fault == "running":
        metadata["State"].update(Status="running", Running=True, Pid=42)
    elif fault == "foreign_id":
        metadata["Id"] = "e" * 64
    else:
        metadata["Config"]["Labels"]["org.hybrid.stock.attempt"] = "e" * 32
    monkeypatch.setattr(
        module, "run_local_helper", lambda *args, **kwargs: pytest.fail("authority not reached")
    )
    with pytest.raises(ValueError, match=r"^stock_bootstrap_unavailable$"):
        module.bootstrap_research(
            release.attestation_path.parent / "manifest.json", checkout=CHECKOUT
        )
    assert not any(isinstance(item, tuple) and "start" in item for item in calls)


@pytest.mark.parametrize("platform,uid", [("darwin", 0), ("linux", 10001)])
def test_bootstrap_host_authority_is_checked_before_release_or_operations(
    native, release, monkeypatch, platform, uid
):
    calls, _ = native
    monkeypatch.setattr(module.sys, "platform", platform)
    monkeypatch.setattr(module.os, "geteuid", lambda: uid)
    monkeypatch.setattr(
        module, "load_release", lambda *args: pytest.fail("must not read host release")
    )
    with pytest.raises(ValueError, match=r"^stock_bootstrap_unavailable$"):
        module.bootstrap_research(
            release.attestation_path.parent / "manifest.json", checkout=CHECKOUT
        )
    assert calls == []


def test_bootstrap_cli_queues_only_the_selected_manifest(monkeypatch, capsys):
    calls = []
    manifest = Path("/fixture/manifest.json")
    monkeypatch.setattr(module.sys, "argv", ["stock_bootstrap", str(manifest)])

    def queue(path, *, checkout):
        calls.append((path, checkout))
        return {"status": "queued", "live_enabled": False}

    monkeypatch.setattr(module, "bootstrap_research", queue)
    assert module.main() == 0
    assert calls == [(manifest, Path(module.__file__).resolve().parents[2])]
    assert json.loads(capsys.readouterr().out) == {"live_enabled": False, "status": "queued"}


@pytest.mark.parametrize("args", [[], ["/fixture/manifest.json", "--resume"]])
def test_bootstrap_cli_rejects_extra_authority_without_dispatch(monkeypatch, capsys, args):
    monkeypatch.setattr(module.sys, "argv", ["stock_bootstrap", *args])
    monkeypatch.setattr(
        module, "bootstrap_research", lambda *args, **kwargs: pytest.fail("must not dispatch")
    )
    assert module.main() == 2
    assert json.loads(capsys.readouterr().out) == {
        "live_enabled": False,
        "status": "stock_bootstrap_unavailable",
    }


def test_bootstrap_module_entry_fails_closed_before_host_access(monkeypatch, capsys):
    monkeypatch.setattr(module.sys, "argv", ["stock_bootstrap"])
    with pytest.raises(SystemExit) as exited:
        runpy.run_path(module.__file__, run_name="__main__")
    assert exited.value.code == 2
    assert json.loads(capsys.readouterr().out)["status"] == "stock_bootstrap_unavailable"
