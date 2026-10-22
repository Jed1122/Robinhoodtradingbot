"""End-to-end fictional stock backup, decrypt and actual application restore."""

import asyncio
import hashlib
import io
import os
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from nacl.public import PrivateKey

from infra.hybrid import stock_backup as module
from tests.deployment.test_stock_maintenance_process import CHECKOUT
from tests.deployment.test_stock_maintenance_process import release as _release
from tests.unit.runtime import test_stock_snapshot as snapshot_tests
from tests.unit.runtime.test_stock_snapshot import sample as _sample
from trading_bot.domain import CodeHash
from trading_bot.runtime.stock_backup_crypto import decrypt_stream
from trading_bot.runtime.stock_local_state import create_local_snapshot_bundle
from trading_bot.runtime.stock_operation_receipts import StockOperationReceipts
from trading_bot.runtime.stock_snapshot import restore_snapshot_controls, verify_stock_snapshot
from trading_bot.runtime.stock_snapshot_bundle import unpack_snapshot

release = _release
sample = _sample


@pytest.fixture
def native(sample, release, tmp_path, monkeypatch):
    root = tmp_path.resolve()
    for name in ("maintenance", "receipts", "backups", "keys"):
        (root / name).mkdir(mode=0o700)
    (root / "receipts/.stock-receipts.lock").write_bytes(b"")
    (root / "receipts/.stock-receipts.lock").chmod(0o600)
    key = PrivateKey.generate()
    (root / "keys/recipient.public").write_bytes(bytes(key.public_key))
    (root / "keys/recipient.public").chmod(0o400)
    release = replace(release, config_hash=str(sample["loaded"].config_hash))
    calls = []
    target = SimpleNamespace(snapshot=lambda: None)

    @contextmanager
    def operations():
        calls.append("lock")
        yield target
        calls.append("unlock")

    monkeypatch.setattr(module, "operations", operations)
    monkeypatch.setattr(module, "load_release", lambda _path: release)

    def helper(checkout, release, action, *, identifier, deadline):
        calls.append(action)
        assert action == "snapshot"
        return asyncio.run(
            create_local_snapshot_bundle(
                loaded=sample["loaded"],
                code_hash=hashlib.sha256(f"oci-image:{release.image_digest}".encode()).hexdigest(),
                data_root=root,
                destination_root=root / "maintenance",
                identifier=identifier,
                now=module.datetime.now(module.UTC),
            )
        )

    monkeypatch.setattr(module, "run_local_helper", helper)
    return root, release, key, calls, target


def backup(native):
    root, release, _, _, _ = native
    return module._backup_stock(
        release.attestation_path.parent / "manifest.json",
        checkout=CHECKOUT,
        backup_root=root / "backups",
        staging_root=root / "maintenance",
        receipt_root=root / "receipts",
        recipient_path=root / "keys/recipient.public",
        helper_uid=os.geteuid(),
    )


def test_complete_encrypted_backup_reconstructs_actual_application(native, sample, monkeypatch):
    root, _, key, calls, _ = native
    expected_code = CodeHash(
        hashlib.sha256(f"oci-image:{native[1].image_digest}".encode()).hexdigest()
    )
    monkeypatch.setattr(snapshot_tests, "CODE", expected_code)
    asyncio.run(snapshot_tests.discovery(sample))
    asyncio.run(snapshot_tests.reserve(sample, at=snapshot_tests.NOW + timedelta(hours=1)))
    result = backup(native)
    assert result["status"] == "backup_committed" and result["live_enabled"] is False
    assert calls == ["lock", "snapshot", "unlock"]
    assert list((root / "maintenance").iterdir()) == []
    receipt = StockOperationReceipts(root / "receipts").latest(
        "backup", now=module.datetime.now(module.UTC)
    )
    cipher = root / "backups" / (receipt["ciphertext_sha256"] + ".stockbackup")
    plaintext = io.BytesIO()
    decrypt_stream(io.BytesIO(cipher.read_bytes()), plaintext, bytes(key))
    plaintext.seek(0)
    restored = root / "restored"
    unpack_snapshot(plaintext, destination=restored)
    actual = asyncio.run(verify_stock_snapshot(restored, now=module.datetime.now(module.UTC)))
    assert actual.manifest_sha256 == receipt["snapshot_manifest_sha256"]
    assert (actual.claim_count, actual.result_count, actual.pending_count) == (2, 1, 1)
    assert actual.budget_by_day == (("2026-10-22", 19),)
    controls = restore_snapshot_controls(
        restored, destination=root / "restored-controls", now=module.datetime.now(module.UTC)
    )
    assert controls.offline_only is True
    assert controls.generation == 1


def test_missing_public_recipient_never_creates_plaintext_snapshot(native):
    root, _, _, calls, _ = native
    (root / "keys/recipient.public").unlink()
    with pytest.raises(ValueError):
        backup(native)
    assert "snapshot" not in calls
    assert list((root / "maintenance").iterdir()) == []


def test_unresolved_worker_never_snapshots_or_publishes(native):
    root, _, _, calls, target = native
    target.snapshot = lambda: SimpleNamespace(stopped_sha256=None, abandoned_sha256=None)
    with pytest.raises(ValueError):
        backup(native)
    assert "snapshot" not in calls
    assert list((root / "backups").iterdir()) == []


def test_partial_helper_receipt_never_creates_success(native, monkeypatch):
    root, _, _, _, _ = native
    monkeypatch.setattr(
        module, "run_local_helper", lambda *args, **kwargs: {"status": "snapshot_bundled"}
    )
    with pytest.raises(ValueError):
        backup(native)
    assert StockOperationReceipts(root / "receipts").all(now=module.datetime.now(module.UTC)) == ()
    assert list((root / "backups").iterdir()) == []


def test_encryption_failure_preserves_private_staging_without_receipt(native, monkeypatch):
    root, _, _, _, _ = native

    def fail(**kwargs):
        raise OSError("private encryption failure")

    monkeypatch.setattr(module, "encrypt_snapshot_bundle", fail)
    with pytest.raises(ValueError, match="stock_backup_unavailable"):
        backup(native)
    assert StockOperationReceipts(root / "receipts").all(now=module.datetime.now(module.UTC)) == ()
    assert len(list((root / "maintenance").iterdir())) == 2


@pytest.mark.parametrize("change", ["mode", "length", "link", "symlink", "parent"])
def test_invalid_recipient_denies_before_helper(native, change):
    root, _, _, calls, _ = native
    recipient = root / "keys/recipient.public"
    if change == "mode":
        recipient.chmod(0o600)
    elif change == "length":
        recipient.chmod(0o600)
        recipient.write_bytes(b"short")
        recipient.chmod(0o400)
    elif change == "link":
        os.link(recipient, root / "keys/other.public")
    elif change == "symlink":
        recipient.rename(root / "keys/other.public")
        recipient.symlink_to(root / "keys/other.public")
    else:
        recipient.parent.chmod(0o755)
    with pytest.raises(ValueError, match="stock_backup_unavailable"):
        backup(native)
    assert "snapshot" not in calls
    assert list((root / "maintenance").iterdir()) == []


@pytest.mark.parametrize("public_key", [b"\0" * 32, b"\1" + b"\0" * 31])
def test_low_order_recipient_denies_before_any_plaintext_snapshot(native, public_key):
    root, _, _, calls, _ = native
    recipient = root / "keys/recipient.public"
    recipient.chmod(0o600)
    recipient.write_bytes(public_key)
    recipient.chmod(0o400)
    with pytest.raises(ValueError, match=r"^stock_backup_unavailable$"):
        backup(native)
    assert "snapshot" not in calls
    assert list((root / "maintenance").iterdir()) == []
    assert list((root / "backups").iterdir()) == []


@pytest.mark.parametrize("change", ["extra", "boolean", "count", "identity", "bundle", "stage"])
def test_helper_evidence_is_bound_to_exact_owned_snapshot(native, monkeypatch, change):
    root, _, _, _, _ = native
    actual = module.run_local_helper

    def altered(*args, **kwargs):
        value = actual(*args, **kwargs)
        if change == "extra":
            value["unexpected"] = "ignored"
        elif change == "boolean":
            value["snapshot"]["claim_count"] = False
        elif change == "count":
            value["bundle"]["file_count"] += 1
        elif change == "identity":
            value["identifier"] = "a" * 32
        elif change == "bundle":
            value["bundle"]["bundle_sha256"] = "f" * 64
        else:
            (root / "maintenance" / value["identifier"] / "canonical-config.json").write_bytes(
                b"{}"
            )
        return value

    monkeypatch.setattr(module, "run_local_helper", altered)
    with pytest.raises(ValueError, match="stock_backup_unavailable"):
        backup(native)
    assert list((root / "backups").iterdir()) == []
    assert StockOperationReceipts(root / "receipts").all(now=module.datetime.now(module.UTC)) == ()
    assert len(list((root / "maintenance").iterdir())) == 2


def test_cleanup_failure_retains_published_ciphertext_without_success_receipt(native, monkeypatch):
    root, _, _, calls, _ = native

    def fail(*args, **kwargs):
        raise OSError("private staging cleanup failure")

    fail.avoids_symlink_attacks = True
    monkeypatch.setattr(module.shutil, "rmtree", fail)
    with pytest.raises(ValueError, match="stock_backup_unavailable"):
        backup(native)
    assert len(list((root / "backups").iterdir())) == 1
    assert len(list((root / "maintenance").iterdir())) == 2
    assert StockOperationReceipts(root / "receipts").all(now=module.datetime.now(module.UTC)) == ()
    previous = calls.count("snapshot")
    with pytest.raises(ValueError, match="stock_backup_unavailable"):
        backup(native)
    assert calls.count("snapshot") == previous
    assert len(list((root / "backups").iterdir())) == 1


def test_receipt_failure_retains_published_ciphertext_and_never_claims_success(native, monkeypatch):
    root, _, _, calls, _ = native

    def fail(*args, **kwargs):
        raise OSError("private receipt failure")

    monkeypatch.setattr(module.StockOperationReceipts, "record", fail)
    with pytest.raises(ValueError, match="stock_backup_unavailable"):
        backup(native)
    assert len(list((root / "backups").iterdir())) == 1
    assert list((root / "maintenance").iterdir()) == []
    previous = calls.count("snapshot")
    with pytest.raises(ValueError, match="stock_backup_unavailable"):
        backup(native)
    assert calls.count("snapshot") == previous
    assert len(list((root / "backups").iterdir())) == 1


@pytest.mark.parametrize("name", ["f" * 64 + ".stockbackup", ".pending-" + "a" * 32])
def test_unacknowledged_cipher_or_pending_fence_denies_before_helper(native, name):
    root, _, _, calls, _ = native
    orphan = root / "backups" / name
    orphan.write_bytes(b"retained forensic evidence")
    orphan.chmod(0o600)
    with pytest.raises(ValueError, match="stock_backup_unavailable"):
        backup(native)
    assert "snapshot" not in calls
    assert orphan.read_bytes() == b"retained forensic evidence"
    assert list((root / "maintenance").iterdir()) == []


def test_retained_cipher_size_must_match_trusted_receipt_before_new_helper(native):
    root, _, _, calls, _ = native
    backup(native)
    ciphertext = next((root / "backups").iterdir())
    with ciphertext.open("ab") as stream:
        stream.write(b"changed")
    previous = calls.count("snapshot")
    with pytest.raises(ValueError, match="stock_backup_unavailable"):
        backup(native)
    assert calls.count("snapshot") == previous
    assert list((root / "maintenance").iterdir()) == []


def test_trusted_historical_release_backup_does_not_block_current_release(native, monkeypatch):
    root, release, _, calls, _ = native
    backup(native)
    directory = release.attestation_path.parent.parent / ("e" * 64)
    upgraded = replace(
        release,
        release_id="e" * 64,
        image_digest="sha256:" + "e" * 64,
        attestation_path=directory / "runtime-image-attestation.json",
        compose_path=directory / "stock-compose.resolved.json",
    )
    monkeypatch.setattr(module, "load_release", lambda _path: upgraded)
    assert backup(native)["status"] == "backup_committed"
    assert calls.count("snapshot") == 2
    assert len(list((root / "backups").iterdir())) == 2


def test_existing_failed_staging_is_preserved(native):
    root, _, _, _, _ = native
    retained = root / "maintenance" / ("a" * 32)
    retained.mkdir(mode=0o700)
    (retained / "forensic").write_bytes(b"retained evidence")
    result = backup(native)
    assert result["status"] == "backup_committed"
    assert (retained / "forensic").read_bytes() == b"retained evidence"
    assert list((root / "maintenance").iterdir()) == [retained]


def test_terminal_worker_is_reinspected_with_exact_attempt_identity(native, monkeypatch):
    _, _, _, _, target = native
    attempt = object()
    target.snapshot = lambda: SimpleNamespace(
        stopped_sha256="b" * 64,
        abandoned_sha256=None,
        container_id="c" * 64,
        attempt=attempt,
    )
    observed = []
    inspection = object()

    class Reader:
        def inspect(self, identifier):
            observed.append(identifier)
            return inspection

    def stopped(actual, expected_attempt, expected_id):
        assert actual is inspection and expected_attempt is attempt
        assert expected_id == "c" * 64
        observed.append("owned-terminal")

    monkeypatch.setattr(module, "StockEngineReader", Reader)
    monkeypatch.setattr(module, "_stopped", stopped)
    assert backup(native)["status"] == "backup_committed"
    assert observed == ["c" * 64, "owned-terminal"]


def test_full_staging_retention_denies_new_helper_without_pruning(native):
    root, _, _, calls, _ = native
    for index in range(4):
        (root / "maintenance" / f"{index:032x}").mkdir(mode=0o700)
    with pytest.raises(ValueError, match="stock_backup_unavailable"):
        backup(native)
    assert "snapshot" not in calls
    assert len(list((root / "maintenance").iterdir())) == 4


def test_unknown_staging_namespace_denies_without_removing_evidence(native):
    root, _, _, calls, _ = native
    evidence = root / "maintenance/unrecognized"
    evidence.write_bytes(b"retained")
    with pytest.raises(ValueError, match="stock_backup_unavailable"):
        backup(native)
    assert "snapshot" not in calls
    assert evidence.read_bytes() == b"retained"


def test_staging_changed_during_encryption_is_retained_without_receipt(native, monkeypatch):
    root, _, _, _, _ = native
    actual = module.encrypt_snapshot_bundle

    def changed(**kwargs):
        result = actual(**kwargs)
        identifier = kwargs["source"].name.removesuffix(".bundle")
        (root / "maintenance" / identifier / "canonical-config.json").write_bytes(b"{}")
        return result

    monkeypatch.setattr(module, "encrypt_snapshot_bundle", changed)
    with pytest.raises(ValueError, match="stock_backup_unavailable"):
        backup(native)
    assert len(list((root / "backups").iterdir())) == 1
    assert len(list((root / "maintenance").iterdir())) == 2
    assert StockOperationReceipts(root / "receipts").all(now=module.datetime.now(module.UTC)) == ()


def test_public_wrapper_requires_root_linux_and_binds_fixed_paths(monkeypatch):
    observed = []
    monkeypatch.setattr(module.sys, "platform", "darwin")
    with pytest.raises(ValueError, match="stock_backup_unavailable"):
        module.backup_stock(CHECKOUT / "manifest.json", checkout=CHECKOUT)
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module.os, "geteuid", lambda: 10001)
    with pytest.raises(ValueError, match="stock_backup_unavailable"):
        module.backup_stock(CHECKOUT / "manifest.json", checkout=CHECKOUT)
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)

    def fake(manifest, **kwargs):
        observed.append((manifest, kwargs))
        return {"status": "fixture"}

    monkeypatch.setattr(module, "_backup_stock", fake)
    assert module.backup_stock(CHECKOUT / "manifest.json", checkout=CHECKOUT) == {
        "status": "fixture"
    }
    assert observed[0][1] == {
        "checkout": CHECKOUT,
        "backup_root": module.Path("/var/lib/hybrid-stock-backups"),
        "staging_root": module.Path("/var/lib/hybrid-stock-research/maintenance"),
        "receipt_root": module.Path("/var/lib/hybrid-stock-maintenance/receipts"),
        "recipient_path": module.Path("/etc/hybrid-stock-research/backup-recipient.public"),
        "helper_uid": 10001,
    }
