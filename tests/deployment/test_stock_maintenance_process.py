"""Fixed maintenance helper commands cannot inherit broker or Python credentials."""

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from infra.hybrid import stock_maintenance_process as module
from infra.hybrid.stock_release import StockRelease

CHECKOUT = Path("/opt/hybrid-stock-research/source/" + "a" * 40)
DIRECTORY = Path("/opt/hybrid-stock-research/releases/" + "b" * 64)


@pytest.fixture(autouse=True)
def verified_runtime(monkeypatch):
    monkeypatch.setattr(module, "verify_local_runtime", lambda *args, **kwargs: None, raising=False)


@pytest.fixture
def release():
    return StockRelease(
        "b" * 64,
        "sha256:" + "c" * 64,
        "d" * 64,
        hashlib.sha256(b"{}").hexdigest(),
        450,
        3600,
        DIRECTORY / "runtime-image-attestation.json",
        DIRECTORY / "stock-compose.resolved.json",
        b"{}",
    )


@pytest.mark.parametrize("action", ["observe", "control-check"])
def test_helper_has_closed_argv_and_reduced_owner(release, action):
    command, env = module.helper_invocation(CHECKOUT, release, action)
    assert command == (
        "/usr/bin/setpriv",
        "--reuid=10001",
        "--regid=10001",
        "--clear-groups",
        "--no-new-privs",
        "/opt/hybrid-stock-research/maintenance/" + "a" * 40 + "/bin/python",
        "-B",
        "-m",
        "trading_bot.runtime.stock_local_state",
        action,
        "d" * 64,
        hashlib.sha256(("oci-image:sha256:" + "c" * 64).encode()).hexdigest(),
    )
    assert env == {
        "PATH": "/usr/bin:/bin",
        "HOME": "/nonexistent",
        "LANG": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(CHECKOUT) + ":" + str(CHECKOUT / "src"),
        "LIVE_TRADING_ENABLED": "false",
        "PREDICTION_LIVE_ENABLED": "false",
    }


@pytest.mark.parametrize(
    "path",
    [
        "/tmp/elsewhere",
        str(CHECKOUT) + "/..",
        "/opt/hybrid-stock-research/source/" + "a" * 39,
        str(CHECKOUT) + "\n",
    ],
)
def test_untrusted_checkout_denied_before_invocation(release, path):
    with pytest.raises(ValueError):
        module.helper_invocation(Path(path), release, "observe")


@pytest.mark.parametrize(
    "action", ["resume", "kill", "refresh", "trade", "observe --oauth-store", ""]
)
def test_helper_actions_are_closed(release, action):
    with pytest.raises(ValueError):
        module.helper_invocation(CHECKOUT, release, action)


@pytest.mark.parametrize(
    "field,value", [("image_digest", "evil"), ("config_hash", "x"), ("compose_sha256", "a" * 64)]
)
def test_invalid_release_denies_helper(release, field, value):
    with pytest.raises(ValueError):
        module.helper_invocation(CHECKOUT, replace(release, **{field: value}), "observe")


def test_helper_output_must_be_complete_bounded_canonical_dict(release, monkeypatch):
    seen = []

    def capture(argv, **kwargs):
        seen.append((argv, kwargs))
        return type("Result", (), {"stdout": b'{"version":1}\n', "stderr": b""})()

    monkeypatch.setattr(module, "_capture", capture)
    result = module.run_local_helper(CHECKOUT, release, "observe", deadline=123.0)
    assert result == {"version": 1}
    assert seen[0][1]["limit"] == 524288
    assert seen[0][1]["deadline"] == 123.0


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":1}secret',
        b'{"x": 1}\n',
        b"private-error",
    ],
)
def test_invalid_helper_output_is_sanitized(release, monkeypatch, raw):
    monkeypatch.setattr(
        module, "_capture", lambda *args, **kwargs: type("R", (), {"stdout": raw})()
    )
    with pytest.raises(ValueError, match="stock_maintenance_helper_unavailable") as error:
        module.run_local_helper(CHECKOUT, release, "observe", deadline=123.0)
    assert "private-error" not in str(error.value)


def test_snapshot_helper_requires_one_closed_staging_identifier(release):
    argv, _ = module.helper_invocation(CHECKOUT, release, "snapshot", identifier="e" * 32)
    assert argv[-4:] == (
        "snapshot",
        release.config_hash,
        hashlib.sha256(("oci-image:" + release.image_digest).encode()).hexdigest(),
        "e" * 32,
    )


def test_integrity_snapshot_keeps_reduced_owner_and_closed_identifier(release):
    command, environment = module.helper_invocation(
        CHECKOUT, release, "snapshot-integrity", identifier="e" * 32
    )
    assert command[-4:] == (
        "snapshot-integrity",
        release.config_hash,
        hashlib.sha256(("oci-image:" + release.image_digest).encode()).hexdigest(),
        "e" * 32,
    )
    assert command[:5] == (
        "/usr/bin/setpriv",
        "--reuid=10001",
        "--regid=10001",
        "--clear-groups",
        "--no-new-privs",
    )
    assert environment["LIVE_TRADING_ENABLED"] == "false"
    for identifier in (None, "../outside", "e" * 31):
        with pytest.raises(ValueError, match="stock_maintenance_helper_unavailable"):
            module.helper_invocation(CHECKOUT, release, "snapshot-integrity", identifier=identifier)


@pytest.mark.parametrize(
    "action,identifier",
    [
        ("snapshot", None),
        ("snapshot", "../bad"),
        ("observe", "e" * 32),
        ("control-check", "e" * 32),
    ],
)
def test_snapshot_identifier_never_enlarges_other_helper_actions(release, action, identifier):
    with pytest.raises(ValueError):
        module.helper_invocation(CHECKOUT, release, action, identifier=identifier)


def test_runtime_verification_failure_never_executes_helper(release, monkeypatch):
    calls = []

    def deny(*args, **kwargs):
        raise ValueError("private runtime detail")

    monkeypatch.setattr(module, "verify_local_runtime", deny)
    monkeypatch.setattr(module, "_capture", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match="stock_maintenance_helper_unavailable"):
        module.run_local_helper(CHECKOUT, release, "observe", deadline=123.0)
    assert calls == []
