"""Independent current metadata is captured only after root filesystem trust checks."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from infra.hybrid import stock_maintenance_verify as module
from infra.hybrid.stock_maintenance_runtime import build_runtime_receipt
from tests.deployment.test_stock_maintenance_process import CHECKOUT
from tests.deployment.test_stock_maintenance_process import release as _release
from tests.deployment.test_stock_maintenance_runtime import LOCK, REQUIREMENTS, facts

release = _release


@pytest.fixture
def current(release, monkeypatch):
    value = facts()
    release = replace(
        release, config_hash=value["config_hash"], release_id=value["source_archive_sha256"]
    )
    directory = Path("/opt/hybrid-stock-research/releases") / release.release_id
    release = replace(
        release,
        attestation_path=directory / "runtime-image-attestation.json",
        compose_path=directory / "stock-compose.resolved.json",
    )
    calls = []
    body = build_runtime_receipt(value)

    def read(path, *args, **kwargs):
        if path.name == "runtime-receipt.json":
            return body
        return LOCK if path.name == "uv.lock" else REQUIREMENTS

    def verify(path, **kwargs):
        calls.append("verify")
        assert kwargs["source_commit"] == CHECKOUT.name
        assert kwargs["source_archive_sha256"] == release.release_id
        assert kwargs["uv_lock_sha256"] == hashlib.sha256(LOCK).hexdigest()
        assert kwargs["requirements_sha256"] == hashlib.sha256(REQUIREMENTS).hexdigest()
        assert build_runtime_receipt(kwargs["actual_facts"]) == body
        return json.loads(body)

    def capture(argv, **kwargs):
        calls.append("facts")
        assert argv[:4] == (
            "/opt/hybrid-stock-research/maintenance/" + "a" * 40 + "/bin/python",
            "-I",
            "-B",
            "-c",
        )
        assert "PYTHONPATH" not in kwargs["env"]
        observed = {key: value[key] for key in module.OBSERVED_FIELDS}
        return SimpleNamespace(
            stdout=(json.dumps(observed, sort_keys=True, separators=(",", ":")) + "\n").encode()
        )

    monkeypatch.setattr(module, "_read", read)
    monkeypatch.setattr(module, "verify_runtime_receipt", verify)
    monkeypatch.setattr(module, "_capture", capture)
    return release, calls, value


def test_runtime_owner_check_precedes_current_metadata_and_full_reverification(current):
    release, calls, _ = current
    module.verify_local_runtime(CHECKOUT, release, deadline=123.0)
    assert calls == ["verify", "facts", "verify"]


def test_untrusted_runtime_never_executes_interpreter(current, monkeypatch):
    release, calls, _ = current

    def deny(*args, **kwargs):
        raise ValueError("private filesystem detail")

    monkeypatch.setattr(module, "verify_runtime_receipt", deny)
    with pytest.raises(ValueError, match="stock_maintenance_verification_unavailable"):
        module.verify_local_runtime(CHECKOUT, release, deadline=123.0)
    assert calls == []


def test_noncanonical_saved_receipt_never_executes_interpreter(current, monkeypatch):
    release, calls, _ = current
    original = module._read

    def noncanonical(path, *args, **kwargs):
        raw = original(path, *args, **kwargs)
        return raw + b" " if path.name == "runtime-receipt.json" else raw

    monkeypatch.setattr(module, "_read", noncanonical)
    with pytest.raises(ValueError, match="stock_maintenance_verification_unavailable"):
        module.verify_local_runtime(CHECKOUT, release, deadline=123.0)
    assert calls == []


@pytest.mark.parametrize("failure", ["inventory", "prefix", "fields", "noncanonical", "duplicate"])
def test_current_runtime_drift_never_reaches_helper(current, monkeypatch, failure):
    release, _, value = current
    observed = {key: value[key] for key in module.OBSERVED_FIELDS}
    if failure == "inventory":
        observed["distributions"] = observed["distributions"][:1]
    elif failure == "prefix":
        observed["sys_prefix"] = "/usr"
    elif failure == "fields":
        observed["unexpected"] = True
    raw = (json.dumps(observed, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if failure == "noncanonical":
        raw += b" "
    elif failure == "duplicate":
        raw = raw.replace(b"{", b'{"platform":"linux",', 1)
    monkeypatch.setattr(module, "_capture", lambda *args, **kwargs: SimpleNamespace(stdout=raw))
    with pytest.raises(ValueError, match="stock_maintenance_verification_unavailable"):
        module.verify_local_runtime(CHECKOUT, release, deadline=123.0)


def test_installed_source_recipe_is_independent_expected_hash(current, monkeypatch):
    release, calls, _ = current
    original = module._read
    monkeypatch.setattr(
        module,
        "_read",
        lambda path, *args, **kwargs: (
            b"changed source recipe\n"
            if path.name == "stock-maintenance-requirements.txt"
            else original(path, *args, **kwargs)
        ),
    )
    with pytest.raises(ValueError):
        module.verify_local_runtime(CHECKOUT, release, deadline=123.0)
    assert "facts" not in calls
