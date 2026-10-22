"""Pure unit generation for a verified release; no host or daemon operation."""

import configparser
import hashlib
import importlib
from dataclasses import replace
from pathlib import Path

import pytest

from infra.hybrid.stock_release import StockRelease

CHECKOUT = Path("/opt/hybrid-stock-research/source/" + "a" * 40)
DIRECTORY = Path("/opt/hybrid-stock-research/releases/" + "b" * 64)


def module():
    source = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_units.py"
    assert source.is_file(), "Pure stock systemd unit generator is not implemented"
    return importlib.import_module("infra.hybrid.stock_units")


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


def sections(raw):
    assert type(raw) is bytes and raw.endswith(b"\n")
    parsed = configparser.ConfigParser(interpolation=None)
    parsed.optionxform = str
    parsed.read_string(raw.decode("ascii"))
    return parsed


def test_service_launches_exact_release_from_absolute_trusted_source(release):
    files = module().unit_files(release, CHECKOUT)
    assert set(files) == {"hybrid-stock-research.service", "hybrid-stock-research.timer"}
    service = sections(files["hybrid-stock-research.service"])["Service"]
    assert service["WorkingDirectory"] == str(CHECKOUT)
    assert service["Environment"] == (
        '"PYTHONDONTWRITEBYTECODE=1" '
        f'"PYTHONPATH={CHECKOUT}:{CHECKOUT}/src" "PYTHONNOUSERSITE=1"'
    )
    assert service["ExecStart"] == (
        "/usr/bin/python3 -B -m infra.hybrid.stock_launcher "
        + str(DIRECTORY / "manifest.json")
    )
    assert service["ExecStopPost"] == "/usr/bin/python3 -B -m infra.hybrid.stock_recover"
    assert service["User"] == service["Group"] == "root"


def test_service_never_restarts_or_remains_active_after_its_bounded_attempt(release):
    parsed = sections(module().unit_files(release, CHECKOUT)["hybrid-stock-research.service"])
    service = parsed["Service"]
    assert service["Type"] == "oneshot"
    assert service["Restart"] == "no" and service["RemainAfterExit"] == "no"
    assert service["TimeoutStartSec"] == "510s" and service["TimeoutStopSec"] == "45s"
    assert service["KillMode"] == "control-group" and service["UMask"] == "0077"
    assert service["MemoryMax"] == "256M" and service["TasksMax"] == "64"
    assert service["CPUQuota"] == "50%"
    assert "Install" not in parsed
    assert not ({"ExecStartPre", "ExecStartPost", "ExecStop", "RestartSec"} & service.keys())


def test_timer_has_only_completion_relative_trigger_and_no_activation_command(release):
    parsed = sections(module().unit_files(release, CHECKOUT)["hybrid-stock-research.timer"])
    assert dict(parsed["Timer"]) == {
        "OnUnitInactiveSec": "3600s",
        "AccuracySec": "1s",
        "RandomizedDelaySec": "0",
        "Persistent": "false",
        "Unit": "hybrid-stock-research.service",
    }
    assert dict(parsed["Install"]) == {"WantedBy": "timers.target"}
    assert "Service" not in parsed


@pytest.mark.parametrize("cadence", [900, 960, 1800, 3540, 3600])
@pytest.mark.parametrize("deadline", [60, 300, 450])
def test_canonical_release_cadence_and_finite_run_budget_are_preserved(release, cadence, deadline):
    files = module().unit_files(
        replace(release, scan_interval_seconds=cadence, max_run_seconds=deadline), CHECKOUT
    )
    timer = sections(files["hybrid-stock-research.timer"])["Timer"]
    service = sections(files["hybrid-stock-research.service"])["Service"]
    assert timer["OnUnitInactiveSec"] == f"{cadence}s"
    assert service["TimeoutStartSec"] == f"{deadline + 60}s"


@pytest.mark.parametrize(
    "checkout",
    [
        Path("relative/source/" + "a" * 40),
        Path("/tmp/source/" + "a" * 40),
        Path("/opt/hybrid-stock-research/source/" + "a" * 39),
        Path("/opt/hybrid-stock-research/source/" + "A" * 40),
        Path("/opt/hybrid-stock-research/source/" + "a" * 40 + "/child"),
        Path("/opt/hybrid-stock-research/source/../source/" + "a" * 40),
        Path("/opt/hybrid-stock-research/source/%n"),
        Path("/opt/hybrid-stock-research/source/$HOME"),
        Path("/opt/hybrid-stock-research/source/$(id)"),
        Path("/opt/hybrid-stock-research/source/`id`"),
        Path("/opt/hybrid-stock-research/source/a\nExecStart=/usr/bin/id"),
        Path("/opt/hybrid-stock-research/source/has space"),
        str(CHECKOUT),
        None,
    ],
)
def test_only_the_fixed_source_namespace_and_full_commit_path_are_accepted(release, checkout):
    with pytest.raises(ValueError, match=r"^stock_units_unavailable$"):
        module().unit_files(release, checkout)


@pytest.mark.parametrize(
    "field,value",
    [
        ("release_id", "e" * 64),
        ("release_id", "b" * 63),
        ("release_id", True),
        ("image_digest", "sha256:" + "C" * 64),
        ("image_digest", "sha256:" + "c" * 63),
        ("image_digest", None),
        ("config_hash", "z" * 64),
        ("config_hash", 1),
        ("compose_sha256", "e" * 64),
        ("compose_sha256", True),
        ("compose_bytes", b""),
        ("compose_bytes", b"x" * 65537),
        ("compose_bytes", "fictional"),
        ("attestation_path", Path("/tmp/releases/" + "b" * 64 + "/runtime-image-attestation.json")),
        ("attestation_path", DIRECTORY / "manifest.json"),
        ("attestation_path", DIRECTORY / "../runtime-image-attestation.json"),
        ("attestation_path", str(DIRECTORY / "runtime-image-attestation.json")),
        ("compose_path", Path("/tmp/releases/" + "b" * 64 + "/stock-compose.resolved.json")),
        ("compose_path", DIRECTORY / "runtime-image-attestation.json"),
        ("compose_path", DIRECTORY / "a\nExecStart=/usr/bin/id"),
        ("compose_path", DIRECTORY / "%n"),
        ("compose_path", None),
        ("max_run_seconds", True),
        ("max_run_seconds", 60.0),
        ("max_run_seconds", 59),
        ("max_run_seconds", 451),
        ("scan_interval_seconds", True),
        ("scan_interval_seconds", 900.0),
        ("scan_interval_seconds", "900"),
        ("scan_interval_seconds", 899),
        ("scan_interval_seconds", 901),
        ("scan_interval_seconds", 3601),
    ],
)
def test_forged_release_identity_paths_types_or_caps_fail_closed(release, field, value):
    with pytest.raises(ValueError, match=r"^stock_units_unavailable$"):
        module().unit_files(replace(release, **{field: value}), CHECKOUT)


@pytest.mark.parametrize("release", [None, {}, "release", True])
def test_caller_cannot_replace_verified_release_with_untyped_input(release):
    with pytest.raises(ValueError, match=r"^stock_units_unavailable$"):
        module().unit_files(release, CHECKOUT)


def test_path_subclass_cannot_change_serialization_after_validation(release):
    class ChangingPath(type(Path())):
        calls = 0

        def __str__(self):
            self.calls += 1
            return str(CHECKOUT) if self.calls == 1 else "/tmp/%n\nExecStart=/usr/bin/id"

    with pytest.raises(ValueError, match=r"^stock_units_unavailable$"):
        module().unit_files(release, ChangingPath(CHECKOUT))


@pytest.mark.parametrize("field", ["attestation_path", "compose_path"])
def test_release_path_subclass_cannot_forge_fixed_namespace_equality(release, field):
    class ImpersonatedPath(type(Path())):
        def __eq__(self, other):
            return True

    with pytest.raises(ValueError, match=r"^stock_units_unavailable$"):
        module().unit_files(replace(release, **{field: ImpersonatedPath("/tmp/forged")}), CHECKOUT)


def test_generation_is_repeatable_without_reading_or_writing_paths(release, monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("unit generation must perform no filesystem operation")

    api = module()
    for name in ("open", "stat", "resolve", "write_bytes", "mkdir"):
        monkeypatch.setattr(Path, name, denied)
    first = api.unit_files(release, CHECKOUT)
    assert api.unit_files(release, CHECKOUT) == first
