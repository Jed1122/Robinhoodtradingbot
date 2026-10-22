"""Pure stock maintenance/boot unit contracts; no installed scheduling is implied."""

import configparser
import hashlib
import importlib
from dataclasses import replace
from pathlib import Path

import pytest

from infra.hybrid import stock_units
from infra.hybrid.stock_release import StockRelease

CHECKOUT = Path("/opt/hybrid-stock-research/source/" + "a" * 40)
MAINTENANCE = "/opt/hybrid-stock-research/maintenance/" + "a" * 40 + "/bin/python"
DIRECTORY = Path("/opt/hybrid-stock-research/releases/" + "b" * 64)
MANIFEST = str(DIRECTORY / "manifest.json")
PREFIX = "hybrid-stock-research-"
OAUTH = "/var/lib/hybrid-stock-research/oauth"
SPOOL = "/var/lib/hybrid-stock-maintenance"
OPERATIONS = "/var/lib/hybrid-stock-operations"


def module():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_continuous_units.py"
    assert path.is_file(), "Pure stock maintenance and boot unit generation is not implemented"
    return importlib.import_module("infra.hybrid.stock_continuous_units")


@pytest.fixture
def release():
    compose = b'{"fictional":"already verified input"}\n'
    return StockRelease(
        release_id="b" * 64,
        image_digest="sha256:" + "c" * 64,
        config_hash="d" * 64,
        compose_sha256=hashlib.sha256(compose).hexdigest(),
        max_run_seconds=450,
        scan_interval_seconds=3600,
        attestation_path=DIRECTORY / "runtime-image-attestation.json",
        compose_path=DIRECTORY / "stock-compose.resolved.json",
        compose_bytes=compose,
    )


def parsed(raw):
    assert type(raw) is bytes and raw.endswith(b"\n")
    result = configparser.ConfigParser(interpolation=None)
    result.optionxform = str
    result.read_string(raw.decode("ascii"))
    return result


def units(release):
    return {name: parsed(body) for name, body in module().unit_files(release, CHECKOUT).items()}


def test_new_units_extend_the_exact_unchanged_collector_bytes(release):
    generated = module().unit_files(release, CHECKOUT)
    previous = stock_units.unit_files(release, CHECKOUT)
    assert set(generated) == {
        "hybrid-stock-research.service",
        "hybrid-stock-research.timer",
        PREFIX + "monitor.service",
        PREFIX + "monitor.timer",
        PREFIX + "backup.service",
        PREFIX + "backup.timer",
        PREFIX + "recovery.service",
        PREFIX + "bootstrap.service",
    }
    assert {name: generated[name] for name in previous} == previous


@pytest.mark.parametrize("cadence,deadline", [(900, 60), (1800, 300), (3600, 450)])
def test_collector_cadence_and_deadline_remain_release_bound(release, cadence, deadline):
    selected = replace(release, scan_interval_seconds=cadence, max_run_seconds=deadline)
    actual = module().unit_files(selected, CHECKOUT)
    for name, body in stock_units.unit_files(selected, CHECKOUT).items():
        assert actual[name] == body


@pytest.mark.parametrize("operation", ["monitor", "backup"])
def test_maintenance_uses_the_same_commit_venv_and_fixed_operation_manifest(release, operation):
    actual = units(release)[PREFIX + operation + ".service"]
    service = actual["Service"]
    assert service["ExecStart"] == (
        f"{MAINTENANCE} -B -m infra.hybrid.stock_maintenance {operation} {MANIFEST}"
    )
    assert service["WorkingDirectory"] == str(CHECKOUT)
    assert service["Environment"] == (
        f'"PYTHONDONTWRITEBYTECODE=1" "PYTHONPATH={CHECKOUT}:{CHECKOUT}/src" "PYTHONNOUSERSITE=1"'
    )
    assert service["RemainAfterExit"] == "no"
    assert "Install" not in actual
    assert not {"ExecStartPre", "ExecStartPost", "ExecStop", "ExecStopPost"} & service.keys()


@pytest.mark.parametrize("operation,cadence", [("monitor", "300s"), ("backup", "86400s")])
def test_maintenance_timers_start_at_activation_and_repeat_only_after_completion(
    release, operation, cadence
):
    actual = units(release)[PREFIX + operation + ".timer"]
    assert dict(actual["Timer"]) == {
        "OnActiveSec": cadence,
        "OnUnitInactiveSec": cadence,
        "AccuracySec": "1s",
        "RandomizedDelaySec": "0",
        "Persistent": "false",
        "Unit": PREFIX + operation + ".service",
    }
    assert dict(actual["Install"]) == {"WantedBy": "timers.target"}


@pytest.mark.parametrize(
    "operation,start,stop,memory,tasks,cpu",
    [
        ("monitor", "60s", "15s", "256M", "64", "10%"),
        ("backup", "300s", "45s", "384M", "64", "25%"),
        ("recovery", "45s", "15s", "128M", "32", "50%"),
        ("bootstrap", "60s", "15s", "128M", "32", "10%"),
    ],
)
def test_new_services_bound_resources_and_allow_only_local_unix_operations(
    release, operation, start, stop, memory, tasks, cpu
):
    service = units(release)[PREFIX + operation + ".service"]["Service"]
    assert service["Type"] == "oneshot" and service["Restart"] == "no"
    assert service["User"] == service["Group"] == "root"
    assert service["UMask"] == "0077" and service["KillMode"] == "control-group"
    assert service["TimeoutStartSec"] == start and service["TimeoutStopSec"] == stop
    assert service["MemoryMax"] == memory and service["TasksMax"] == tasks
    assert service["CPUQuota"] == cpu
    assert service["NoNewPrivileges"] == "yes" and service["ProtectSystem"] == "strict"
    assert service["PrivateNetwork"] == "yes"
    assert service["RestrictAddressFamilies"] == "AF_UNIX"
    assert service["ProtectHome"] == service["PrivateTmp"] == "yes"
    assert service["InaccessiblePaths"] == OAUTH
    assert "CapabilityBoundingSet" not in service and "AmbientCapabilities" not in service


def test_monitor_can_write_only_incidents_and_its_existing_read_lock_anchors(release):
    service = units(release)[PREFIX + "monitor.service"]["Service"]
    assert set(service["ReadWritePaths"].split()) == {
        SPOOL + "/incidents",
        SPOOL + "/receipts/.stock-receipts.lock",
        OPERATIONS + "/launcher.lock",
        "/var/lib/hybrid-stock-research/controls/.stock-control.lock",
    }


def test_backup_payloads_are_read_only_except_existing_locks_and_private_staging(release):
    service = units(release)[PREFIX + "backup.service"]["Service"]
    assert set(service["ReadWritePaths"].split()) == {
        SPOOL + "/receipts",
        OPERATIONS + "/launcher.lock",
        "/var/lib/hybrid-stock-backups",
        "/var/lib/hybrid-stock-research/maintenance",
        "/var/lib/hybrid-stock-research/archive/.stock-research.lock",
        "/var/lib/hybrid-stock-research/controls/.stock-control.lock",
        "/var/lib/hybrid-stock-research/exports/.stock-research.lock",
    }


def test_boot_recovery_never_receives_a_release_or_installs_a_direct_boot_trigger(release):
    actual = units(release)[PREFIX + "recovery.service"]
    assert actual["Service"]["ExecStart"] == "/usr/bin/python3 -B -m infra.hybrid.stock_recover"
    assert actual["Service"]["ReadWritePaths"] == OPERATIONS
    assert actual["Service"]["RemainAfterExit"] == "yes"
    assert actual["Unit"]["Requires"] == actual["Unit"]["After"] == "docker.service"
    assert "Install" not in actual


def test_only_separate_bootstrap_is_enabled_by_multi_user_and_runs_after_recovery(release):
    all_units = units(release)
    actual = all_units[PREFIX + "bootstrap.service"]
    assert actual["Service"]["ExecStart"] == (
        "/usr/bin/python3 -B -m infra.hybrid.stock_bootstrap " + MANIFEST
    )
    assert actual["Service"]["RemainAfterExit"] == "yes"
    assert set(actual["Service"]["ReadWritePaths"].split()) == {
        OPERATIONS + "/launcher.lock",
        "/var/lib/hybrid-stock-research/controls/.stock-control.lock",
    }
    assert set(actual["Unit"]["Requires"].split()) == {
        "docker.service",
        PREFIX + "recovery.service",
    }
    assert actual["Unit"]["After"] == actual["Unit"]["Requires"]
    assert dict(actual["Install"]) == {"WantedBy": "multi-user.target"}
    assert [
        name
        for name, value in all_units.items()
        if value.has_section("Install") and value["Install"].get("WantedBy") == "multi-user.target"
    ] == [PREFIX + "bootstrap.service"]
    for name, value in all_units.items():
        if name.startswith(PREFIX):
            assert "hybrid-stock-research.service" not in value["Unit"].get("Requires", "")


@pytest.mark.parametrize("operation", ["monitor", "backup", "bootstrap"])
@pytest.mark.parametrize(
    "target,writers",
    [
        (SPOOL, set()),
        (SPOOL + "/incidents", {"monitor"}),
        (SPOOL + "/incidents/incidents.json", {"monitor"}),
        (SPOOL + "/receipts", {"backup"}),
        (SPOOL + "/receipts/.stock-receipts.lock", {"monitor", "backup"}),
        (SPOOL + "/receipts/backup-" + "a" * 64 + ".json", {"backup"}),
        (OPERATIONS, set()),
        (OPERATIONS + "/launcher.lock", {"monitor", "backup", "bootstrap"}),
        (OPERATIONS + "/namespace.json", set()),
        ("/var/lib/hybrid-stock-research/controls", set()),
        ("/var/lib/hybrid-stock-research/controls/stock-control.json", set()),
        (
            "/var/lib/hybrid-stock-research/controls/.stock-control.lock",
            {"monitor", "backup", "bootstrap"},
        ),
        ("/var/lib/hybrid-stock-research/archive/.stock-research.lock", {"backup"}),
        ("/var/lib/hybrid-stock-research/exports/.stock-research.lock", {"backup"}),
        ("/var/lib/hybrid-stock-research/maintenance", {"backup"}),
        ("/var/lib/hybrid-stock-backups", {"backup"}),
        (OAUTH, set()),
    ],
)
def test_service_write_exceptions_cannot_expose_another_store_or_control_payload(
    release, operation, target, writers
):
    service = units(release)[PREFIX + operation + ".service"]["Service"]
    assert service["ProtectSystem"] == "strict"
    writable = tuple(Path(path) for path in service["ReadWritePaths"].split())
    exposed = any(Path(target).is_relative_to(path) for path in writable)
    assert exposed is (operation in writers)


@pytest.mark.parametrize(
    "checkout",
    [
        Path("/tmp/source/" + "a" * 40),
        Path("/opt/hybrid-stock-research/maintenance/" + "a" * 40),
        Path("/opt/hybrid-stock-research/source/" + "a" * 39),
        Path("/opt/hybrid-stock-research/source/" + "A" * 40),
        Path("/opt/hybrid-stock-research/source/../source/" + "a" * 40),
        Path("/opt/hybrid-stock-research/source/%n"),
        Path("/opt/hybrid-stock-research/source/$HOME"),
        Path("/opt/hybrid-stock-research/source/a\nExecStart=/usr/bin/id"),
        Path("relative/source/" + "a" * 40),
        str(CHECKOUT),
        None,
    ],
)
def test_source_path_validation_also_fences_the_derived_maintenance_interpreter(release, checkout):
    with pytest.raises(ValueError, match=r"^stock_units_unavailable$"):
        module().unit_files(release, checkout)


@pytest.mark.parametrize(
    "field,value",
    [
        ("release_id", "e" * 64),
        ("compose_sha256", "f" * 64),
        ("compose_bytes", b"changed"),
        ("attestation_path", Path("/tmp/untrusted")),
        ("compose_path", DIRECTORY / "%n"),
        ("max_run_seconds", True),
        ("scan_interval_seconds", 901),
    ],
)
def test_all_units_share_existing_release_identity_and_cap_validation(release, field, value):
    with pytest.raises(ValueError, match=r"^stock_units_unavailable$"):
        module().unit_files(replace(release, **{field: value}), CHECKOUT)


def test_rendering_has_no_filesystem_or_installation_side_effects(release, monkeypatch):
    api = module()

    def deny(*args, **kwargs):
        raise AssertionError("a pure renderer cannot access host state")

    for name in ("open", "stat", "resolve", "write_bytes", "mkdir"):
        monkeypatch.setattr(Path, name, deny)
    first = api.unit_files(release, CHECKOUT)
    assert api.unit_files(release, CHECKOUT) == first
