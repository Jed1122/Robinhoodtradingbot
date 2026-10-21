"""Host-only watchdog contracts using fictional identities and private local fixtures."""

import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)
IMAGE = "sha256:" + "1" * 64
UID = os.geteuid()


def test_entrypoint_accepts_operator_manifest_and_local_state_directory():
    result = subprocess.run(
        [sys.executable, str(ROOT / "infra/hybrid/watchdog.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, "host watchdog entry point is unavailable"
    assert "--manifest" in result.stdout and "--state-dir" in result.stdout


@pytest.fixture
def watchdog():
    source = ROOT / "infra/hybrid/watchdog.py"
    assert source.is_file(), "host watchdog has not been implemented"
    spec = importlib.util.spec_from_file_location("hybrid_watchdog", source)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def setup(tmp_path, watchdog):
    tmp_path.chmod(0o700)
    backups = tmp_path / "backups"
    backups.mkdir(mode=0o700)
    spool = tmp_path / "watchdog"
    spool.mkdir(mode=0o700)
    archive = backups / "fixture.db.age"
    archive.write_bytes(b"fictional encrypted bytes")
    archive.chmod(0o600)
    receipt = {
        "schema_version": 1,
        "completed_at": NOW.isoformat(),
        "release_id": "2" * 64,
        "image_digest": IMAGE,
        "deployment_config_hash": "3" * 64,
        "compose_sha256": "4" * 64,
        "archive_sha256": "5" * 64,
        "archive_name": archive.name,
        "archive_bytes": archive.stat().st_size,
        "encryption": "age-v1",
        "structural_check": True,
        "application_check": True,
    }
    receipt_path = backups / "success.json"
    write_private(receipt_path, receipt)
    document = {
        "schema_version": 1,
        "release_id": "2" * 64,
        "expected_image": IMAGE,
        "deployment_config_hash": "3" * 64,
        "compose_sha256": "4" * 64,
        "container_name": "hybrid-paper-hybrid-paper-1",
        "backup_receipt": str(receipt_path),
        "backup_max_age_seconds": 172800,
        "minimum_free_bytes": 1024,
        "minimum_free_inodes": 10,
        "minimum_available_memory_bytes": 2048,
    }
    manifest_path = tmp_path / "manifest.json"
    write_private(manifest_path, document)
    manifest = watchdog.load_manifest(manifest_path, trusted_uid=UID)
    return SimpleNamespace(
        manifest=manifest,
        manifest_path=manifest_path,
        document=document,
        receipt=receipt,
        receipt_path=receipt_path,
        archive=archive,
        spool=spool,
    )


def write_private(path, value):
    path.write_text(json.dumps(value))
    path.chmod(0o600)


def container(**changes):
    return {
        "Image": IMAGE,
        "Running": True,
        "Status": "running",
        "OOMKilled": False,
        "RestartCount": 0,
        "StartedAt": "2026-10-21T10:00:00Z",
        "Health": "healthy",
    } | changes


def observe(watchdog, setup, *, at=NOW, instance=None, request=None, memory=None, disk=None):
    responses = {
        "/healthz": (200, b'{"healthy":true,"live_enabled":false}'),
        "/readyz": (503, b""),
        "/api/hybrid/snapshot": (401, b""),
    }
    return watchdog.run_watchdog(
        setup.manifest,
        setup.spool,
        at,
        trusted_uid=UID,
        inspector=lambda name: container() if instance is None else instance,
        requester=request or (lambda path: responses[path]),
        memory_reader=memory or (lambda: 4096),
        disk_reader=disk or (lambda path: (4096, 100)),
    )


def test_healthy_probe_writes_private_status_without_pending_external_alerts(watchdog, setup):
    result = observe(watchdog, setup)
    assert result["healthy"] is True
    assert result["pending_local_events"] == 0
    saved = json.loads((setup.spool / "state.json").read_text())
    assert saved["outbox"] == []
    assert (setup.spool / "state.json").stat().st_mode & 0o777 == 0o600


def test_failure_deduplicates_across_restart_and_recovery_is_durable(watchdog, setup):
    first = observe(watchdog, setup, instance=container(Image="sha256:" + "9" * 64))
    assert first["failed_conditions"] == ["image_identity"]
    second = observe(
        watchdog,
        setup,
        at=NOW + timedelta(minutes=5),
        instance=container(Image="sha256:" + "9" * 64),
    )
    assert second["pending_local_events"] == 1
    third = observe(watchdog, setup, at=NOW + timedelta(minutes=10))
    assert third["healthy"] is True and third["pending_local_events"] == 2
    saved = json.loads((setup.spool / "state.json").read_text())
    incident = next(iter(saved["conditions"].values()))
    assert incident["count"] == 2 and incident["active"] is False
    assert incident["first_seen"] == NOW.isoformat()
    assert incident["last_seen"] == (NOW + timedelta(minutes=5)).isoformat()
    assert [row["type"] for row in saved["outbox"]] == [
        "host_operational_failure",
        "host_operational_recovery",
    ]
    assert all(row["status"] == "pending_local" for row in saved["outbox"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("Running", False),
        ("OOMKilled", True),
        ("Health", "unhealthy"),
        ("RestartCount", True),
        ("StartedAt", "not-a-time"),
    ],
)
def test_container_faults_cannot_report_healthy(watchdog, setup, field, value):
    assert observe(watchdog, setup, instance=container(**{field: value}))["healthy"] is False


def test_new_container_start_is_a_local_incident_without_remediation(watchdog, setup):
    observe(watchdog, setup)
    changed = observe(
        watchdog,
        setup,
        at=NOW + timedelta(minutes=5),
        instance=container(StartedAt="2026-10-21T12:01:00Z", RestartCount=1),
    )
    assert changed["failed_conditions"] == ["unexpected_restart"]


@pytest.mark.parametrize(
    "path,response",
    [
        ("/healthz", (200, b'{"healthy":true,"live_enabled":true}')),
        ("/healthz", (200, b"not-json")),
        ("/readyz", (200, b"")),
        ("/api/hybrid/snapshot", (200, b"private payload must never be retained")),
    ],
)
def test_http_failure_is_sanitized_in_local_spool(watchdog, setup, path, response):
    def request(endpoint):
        if endpoint == path:
            return response
        return {
            "/healthz": (200, b'{"healthy":true,"live_enabled":false}'),
            "/readyz": (503, b""),
            "/api/hybrid/snapshot": (401, b""),
        }[endpoint]

    assert observe(watchdog, setup, request=request)["healthy"] is False
    assert "private payload" not in (setup.spool / "state.json").read_text()


def test_unknown_probe_does_not_clear_previous_identity_incident(watchdog, setup):
    observe(watchdog, setup, instance=container(Image="sha256:" + "9" * 64))
    result = observe(watchdog, setup, at=NOW + timedelta(minutes=5), instance={})
    assert result["healthy"] is False
    saved = json.loads((setup.spool / "state.json").read_text())
    incident = next(
        row for row in saved["conditions"].values() if row["reason_code"] == "image_identity"
    )
    assert incident["active"] is True
    assert not any(row["type"] == "host_operational_recovery" for row in saved["outbox"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("completed_at", (NOW - timedelta(days=3)).isoformat()),
        ("completed_at", (NOW + timedelta(seconds=1)).isoformat()),
        ("release_id", "9" * 64),
        ("image_digest", "sha256:" + "9" * 64),
        ("deployment_config_hash", "9" * 64),
        ("compose_sha256", "9" * 64),
        ("archive_name", "../private.db.age"),
        ("archive_bytes", True),
        ("structural_check", False),
        ("application_check", False),
        ("encryption", "none"),
    ],
)
def test_backup_receipt_must_be_fresh_current_private_and_successful(watchdog, setup, field, value):
    write_private(setup.receipt_path, setup.receipt | {field: value})
    result = observe(watchdog, setup)
    assert result["failed_conditions"] == ["backup_receipt"]


def test_receipt_archive_is_checked_only_as_private_regular_file_with_matching_size(
    watchdog, setup
):
    setup.archive.unlink()
    setup.archive.symlink_to(setup.manifest_path)
    assert observe(watchdog, setup)["failed_conditions"] == ["backup_receipt"]


@pytest.mark.parametrize(
    "memory,disk,reason",
    [
        (lambda: 10, None, "memory_available"),
        (None, lambda path: (10, 100), "disk_space"),
        (None, lambda path: (4096, 1), "inode_space"),
    ],
)
def test_resource_thresholds_fail_without_increasing_limits(watchdog, setup, memory, disk, reason):
    assert observe(watchdog, setup, memory=memory, disk=disk)["failed_conditions"] == [reason]


@pytest.mark.parametrize("kind", ["world_readable", "symlink", "unknown_key", "wrong_owner"])
def test_unsafe_manifest_is_rejected_before_observation(watchdog, setup, kind):
    path = setup.manifest_path
    trusted_uid = UID
    if kind == "world_readable":
        path.chmod(0o644)
    elif kind == "symlink":
        path = path.parent / "linked.json"
        path.symlink_to(setup.manifest_path)
    elif kind == "unknown_key":
        write_private(path, setup.document | {"webhook_url": "https://invalid.example"})
    else:
        trusted_uid = UID + 1
    with pytest.raises(watchdog.UnsafeState):
        watchdog.load_manifest(path, trusted_uid=trusted_uid)


def test_tampered_or_future_spool_is_rejected_without_overwrite(watchdog, setup):
    observe(watchdog, setup)
    path = setup.spool / "state.json"
    original = path.read_bytes()
    with pytest.raises(watchdog.UnsafeState):
        observe(watchdog, setup, at=NOW - timedelta(seconds=1))
    assert path.read_bytes() == original
    saved = json.loads(original)
    saved["sequence"] = 42
    write_private(path, saved)
    with pytest.raises(watchdog.UnsafeState):
        observe(watchdog, setup)
    assert json.loads(path.read_bytes())["sequence"] == 42


def test_spool_lock_contention_does_not_corrupt_state(watchdog, setup):
    import fcntl

    observe(watchdog, setup)
    original = (setup.spool / "state.json").read_bytes()
    with (setup.spool / "watchdog.lock").open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(watchdog.UnsafeState):
            observe(watchdog, setup)
    assert (setup.spool / "state.json").read_bytes() == original


def test_spool_write_failure_preserves_previous_status_and_reports_failure(
    watchdog, setup, monkeypatch
):
    observe(watchdog, setup)
    original = (setup.spool / "state.json").read_bytes()

    def fail(*args, **kwargs):
        raise OSError("fictional full disk")

    monkeypatch.setattr(watchdog.os, "replace", fail)
    with pytest.raises(watchdog.UnsafeState):
        observe(watchdog, setup, instance=container(OOMKilled=True))
    assert (setup.spool / "state.json").read_bytes() == original


def test_capacity_exhaustion_does_not_drop_undelivered_events(watchdog, setup, monkeypatch):
    monkeypatch.setattr(watchdog, "MAX_RECORDS", 2)
    observe(watchdog, setup, instance=container(OOMKilled=True))
    original = (setup.spool / "state.json").read_bytes()
    with pytest.raises(watchdog.UnsafeState):
        observe(watchdog, setup, at=NOW + timedelta(minutes=5))
    assert (setup.spool / "state.json").read_bytes() == original


def test_missing_initialized_spool_cannot_silently_reset_incident_history(watchdog, setup):
    observe(watchdog, setup, instance=container(OOMKilled=True))
    (setup.spool / "state.json").unlink()
    with pytest.raises(watchdog.UnsafeState):
        observe(watchdog, setup)
    assert not (setup.spool / "state.json").exists()


def test_byte_capacity_failure_preserves_last_committed_state(watchdog, setup, monkeypatch):
    observe(watchdog, setup)
    original = (setup.spool / "state.json").read_bytes()
    monkeypatch.setattr(watchdog, "MAX_BYTES", len(original) + 10)
    with pytest.raises(watchdog.UnsafeState):
        observe(watchdog, setup, instance=container(OOMKilled=True))
    assert (setup.spool / "state.json").read_bytes() == original


@pytest.mark.parametrize("target", ["state.json", "watchdog.lock", ".state.next"])
def test_symlink_in_spool_is_never_adopted_or_overwritten(watchdog, setup, target):
    if target != "watchdog.lock":
        observe(watchdog, setup)
    outside = setup.spool.parent / "unrelated-private.txt"
    outside.write_text("preserve unrelated private data")
    outside.chmod(0o600)
    path = setup.spool / target
    path.unlink(missing_ok=True)
    path.symlink_to(outside)
    with pytest.raises(watchdog.UnsafeState):
        observe(watchdog, setup)
    assert path.is_symlink()
    assert outside.read_text() == "preserve unrelated private data"


def test_interrupted_uncommitted_write_is_discarded_without_duplicate_incident(watchdog, setup):
    observe(watchdog, setup, instance=container(OOMKilled=True))
    partial = setup.spool / ".state.next"
    partial.write_bytes(b'{"partial"')
    partial.chmod(0o600)
    result = observe(
        watchdog, setup, at=NOW + timedelta(minutes=5), instance=container(OOMKilled=True)
    )
    assert result["pending_local_events"] == 1
    assert not partial.exists()


def test_http_total_deadline_covers_a_stalled_body_without_logging_it(watchdog, monkeypatch):
    import time

    class Response:
        code = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            time.sleep(5)
            return b"private body"

    monkeypatch.setattr(
        watchdog.urllib.request,
        "build_opener",
        lambda *args: SimpleNamespace(open=lambda *args, **kwargs: Response()),
    )
    start = time.monotonic()
    with pytest.raises(watchdog.ObservationError):
        watchdog.request("/healthz", timeout=0.05)
    assert time.monotonic() - start < 1


def test_http_transport_disables_proxies_redirects_and_bounds_body(watchdog, monkeypatch):
    from io import BytesIO

    def opener(*handlers):
        assert any(
            isinstance(item, watchdog.urllib.request.ProxyHandler) and item.proxies == {}
            for item in handlers
        )
        redirect = next(item for item in handlers if isinstance(item, watchdog._NoRedirect))
        assert (
            redirect.redirect_request(
                None, None, 302, "redirect", {}, "https://invalid.example/private"
            )
            is None
        )

        def open_response(url, *, timeout):
            assert url == "http://127.0.0.1:8081/healthz" and timeout == 3
            response = BytesIO(b"x" * 4097)
            response.code = 200
            return response

        return SimpleNamespace(open=open_response)

    monkeypatch.setattr(watchdog.urllib.request, "build_opener", opener)
    with pytest.raises(watchdog.ObservationError):
        watchdog.request("/healthz")


def test_receipt_fifo_is_rejected_without_blocking(watchdog, setup):
    setup.receipt_path.unlink()
    os.mkfifo(setup.receipt_path, mode=0o600)
    assert observe(watchdog, setup)["failed_conditions"] == ["backup_receipt"]


def test_manifest_hardlink_cannot_import_other_private_file(watchdog, setup):
    linked = setup.manifest_path.parent / "hardlink.json"
    os.link(setup.manifest_path, linked)
    with pytest.raises(watchdog.UnsafeState):
        watchdog.load_manifest(linked, trusted_uid=UID)


def test_subprocess_timeout_and_output_are_bounded(watchdog):
    with pytest.raises(watchdog.ObservationError):
        watchdog.bounded_command([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.05)
    with pytest.raises(watchdog.ObservationError):
        watchdog.bounded_command([sys.executable, "-c", "print('x'*65536)"], limit=128)


def test_docker_observation_selects_only_nonsecret_fields(watchdog, monkeypatch):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return json.dumps(container()).encode()

    monkeypatch.setattr(watchdog, "bounded_command", run)
    assert watchdog.inspect_container("hybrid-paper-hybrid-paper-1")["Image"] == IMAGE
    assert len(commands) == 1
    assert commands[0][:3] == ["/usr/bin/docker", "inspect", "--format"]
    assert ".Config.Env" not in commands[0][3] and "json .}}" not in commands[0][3]
    assert commands[0][-1] == "hybrid-paper-hybrid-paper-1"


def test_cli_unsafe_input_has_generic_nonzero_output_without_private_values(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "infra/hybrid/watchdog.py"),
            "--manifest",
            str(tmp_path / "private-token-never-log"),
            "--state-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "private-token-never-log" not in result.stdout + result.stderr
