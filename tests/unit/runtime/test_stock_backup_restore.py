"""Offline encrypted restore rehearsals with fictional keys and real application replay."""

import asyncio
import hashlib
import importlib
import io
import json
import os
import sqlite3
import stat
from dataclasses import asdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from nacl.public import PrivateKey
from test_stock_snapshot import CODE, NOW, discovery, reserve
from test_stock_snapshot import sample as snapshot_sample

from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.runtime.stock_backup_crypto import encrypt_stream
from trading_bot.runtime.stock_dashboard_export import export_stock_dashboard
from trading_bot.runtime.stock_research_controls import StockResearchControls
from trading_bot.runtime.stock_snapshot import create_stock_snapshot, verify_stock_snapshot
from trading_bot.runtime.stock_snapshot_bundle import pack_snapshot

DENIAL = r"^stock_backup_restore_unavailable$"
PRIVATE = bytes(range(32))


def module():
    path = Path(__file__).resolve().parents[3] / "src/trading_bot/runtime/stock_backup_restore.py"
    assert path.is_file(), "The offline encrypted stock restore backend is missing"
    return importlib.import_module("trading_bot.runtime.stock_backup_restore")


@pytest.fixture
def sample(tmp_path):
    return snapshot_sample.__wrapped__(tmp_path)


def seal(root, *, plaintext=None):
    body = io.BytesIO()
    if plaintext is None:
        pack_snapshot(root / "snapshot", body)
    else:
        body.write(plaintext)
    output = io.BytesIO()
    receipt = encrypt_stream(
        io.BytesIO(body.getvalue()), output, bytes(PrivateKey(PRIVATE).public_key)
    )
    ciphertext = root / "backup.box"
    ciphertext.write_bytes(output.getvalue())
    ciphertext.chmod(0o600)
    return receipt


@pytest.fixture
async def ready(sample):
    owner = StockResearchControls(sample["control_dir"], clock=lambda: NOW)
    saved = owner.read()
    saved = owner.change(
        "resume",
        expected_sha256=saved.sha256,
        config_hash=str(sample["loaded"].config_hash),
        code_hash=CODE,
    )
    await reserve(sample)
    snapshot = await create_stock_snapshot(**sample)
    root = sample["destination"].parent
    key = root / "receiver.key"
    key.write_bytes(PRIVATE)
    key.chmod(0o600)
    encrypted = seal(root)
    return {
        "args": {
            "ciphertext": root / "backup.box",
            "private_key_file": key,
            "destination": root / "offline-drill",
            "expected_ciphertext_sha256": encrypted.ciphertext_sha256,
            "expected_snapshot_manifest_sha256": snapshot.manifest_sha256,
            "now": NOW + timedelta(hours=1),
        },
        "snapshot": snapshot,
        "encrypted": encrypted,
        "saved": saved,
        "sample": sample,
    }


@pytest.mark.asyncio
async def test_actual_roundtrip_replays_pending_charges_and_kills_the_saved_running_identity(ready):
    result = await module().restore_encrypted_stock_backup(**ready["args"])
    assert result.ciphertext_sha256 == ready["encrypted"].ciphertext_sha256
    assert result.snapshot_manifest_sha256 == ready["snapshot"].manifest_sha256
    assert result.bundle_sha256 == ready["encrypted"].plaintext_sha256
    assert (
        result.total_bytes
        == ready["snapshot"].total_bytes
        + (ready["sample"]["destination"] / "manifest.json").stat().st_size
    )
    assert (result.claim_count, result.result_count, result.pending_count) == (1, 0, 1)
    assert result.state_sha256 == ready["snapshot"].state_sha256
    assert result.offline_only is True and result.control_id == ready["saved"].record.control_id
    assert result.control_generation == ready["saved"].record.generation + 1
    root = ready["args"]["destination"]
    assert {path.name for path in root.iterdir()} == {"snapshot", "killed-controls"}
    restored = StockResearchControls(root / "killed-controls/controls").read()
    assert restored.record.status == "killed"
    assert restored.record.previous_sha256 == ready["saved"].sha256
    assert restored.record.control_id == result.control_id
    assert await verify_stock_snapshot(root / "snapshot") == ready["snapshot"]
    for path in (root, *root.rglob("*")):
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)
    encoded = json.dumps(asdict(result))
    assert PRIVATE.hex() not in encoded and str(root) not in encoded
    assert str(ready["args"]["private_key_file"]) not in encoded


@pytest.mark.asyncio
async def test_ciphertext_trusted_hash_is_checked_before_any_decryption_or_key_loading(
    ready, monkeypatch
):
    api = module()
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("must not decrypt or load key")

    monkeypatch.setattr(api, "decrypt_stream", forbidden)
    monkeypatch.setattr(api, "_read_key", forbidden)
    ready["args"]["expected_ciphertext_sha256"] = "f" * 64
    with pytest.raises(ValueError, match=DENIAL):
        await api.restore_encrypted_stock_backup(**ready["args"])
    assert calls == [] and not ready["args"]["destination"].exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("which", ["ciphertext", "private_key_file"])
@pytest.mark.parametrize("change", ["public", "symlink", "hardlink", "fifo"])
async def test_private_regular_single_link_inputs_are_mandatory(ready, which, change):
    path = ready["args"][which]
    if change == "public":
        path.chmod(0o644)
    elif change == "symlink":
        other = path.with_name("other-" + path.name)
        path.rename(other)
        path.symlink_to(other)
    elif change == "hardlink":
        os.link(path, path.with_name("other-" + path.name))
    else:
        path.unlink()
        os.mkfifo(path, 0o600)
    with pytest.raises(ValueError, match=DENIAL):
        await module().restore_encrypted_stock_backup(**ready["args"])
    assert not ready["args"]["destination"].exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [0, 31, 33])
async def test_private_key_is_exactly_32_bytes(ready, size):
    ready["args"]["private_key_file"].write_bytes(b"x" * size)
    with pytest.raises(ValueError, match=DENIAL):
        await module().restore_encrypted_stock_backup(**ready["args"])
    assert not ready["args"]["destination"].exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_ciphertext_sha256", "A" * 64),
        ("expected_snapshot_manifest_sha256", None),
        ("expected_snapshot_manifest_sha256", "f" * 63),
        ("now", NOW.replace(tzinfo=None)),
        ("now", NOW.astimezone(timezone(timedelta(hours=1)))),
    ],
)
async def test_strict_expected_identities_and_utc_clock_are_required(ready, field, value):
    ready["args"][field] = value
    with pytest.raises(ValueError, match=DENIAL):
        await module().restore_encrypted_stock_backup(**ready["args"])
    assert not ready["args"]["destination"].exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["cipher-final", "wrong-key", "bad-bundle", "trailing-bundle"])
async def test_failed_authentication_or_bundle_framing_retains_private_unpublished_plaintext(
    ready, change
):
    root = ready["args"]["destination"].parent
    if change == "cipher-final":
        path = ready["args"]["ciphertext"]
        path.write_bytes(path.read_bytes()[:-1])
        ready["args"]["expected_ciphertext_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    elif change == "wrong-key":
        ready["args"]["private_key_file"].write_bytes(b"x" * 32)
    else:
        body = io.BytesIO()
        pack_snapshot(root / "snapshot", body)
        receipt = seal(root, plaintext=b"bad" if change == "bad-bundle" else body.getvalue() + b"x")
        ready["args"]["expected_ciphertext_sha256"] = receipt.ciphertext_sha256
    with pytest.raises(ValueError, match=DENIAL):
        await module().restore_encrypted_stock_backup(**ready["args"])
    destination = ready["args"]["destination"]
    assert (destination / ".snapshot-bundle.tmp").exists()
    assert not (destination / "killed-controls").exists()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    assert stat.S_IMODE((destination / ".snapshot-bundle.tmp").stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_wrong_snapshot_manifest_denies_before_application_replay(ready, monkeypatch):
    called = []

    async def forbidden(*args, **kwargs):
        called.append(True)
        raise AssertionError("wrong trusted manifest")

    monkeypatch.setattr(module(), "verify_stock_snapshot", forbidden)
    ready["args"]["expected_snapshot_manifest_sha256"] = "f" * 64
    with pytest.raises(ValueError, match=DENIAL):
        await module().restore_encrypted_stock_backup(**ready["args"])
    assert called == []
    assert (ready["args"]["destination"] / ".snapshot-bundle.tmp").exists()


@pytest.mark.asyncio
async def test_rehashed_sqlite_trigger_tampering_is_rejected_by_actual_application_reader(ready):
    root = ready["args"]["destination"].parent
    snapshot = root / "snapshot"
    ledger = snapshot / "state/ledger.sqlite3"
    db = sqlite3.connect(ledger)
    try:
        db.execute("DROP TRIGGER trg_audit_events_append_only_update")
        db.commit()
    finally:
        db.close()
    manifest = snapshot / "manifest.json"
    value = json.loads(manifest.read_bytes())
    value["files"]["state/ledger.sqlite3"].update(
        sha256=hashlib.sha256(ledger.read_bytes()).hexdigest(), size=ledger.stat().st_size
    )
    manifest.write_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())
    ready["args"]["expected_snapshot_manifest_sha256"] = hashlib.sha256(
        manifest.read_bytes()
    ).hexdigest()
    ready["args"]["expected_ciphertext_sha256"] = seal(root).ciphertext_sha256
    with pytest.raises(ValueError, match=DENIAL):
        await module().restore_encrypted_stock_backup(**ready["args"])
    assert not (ready["args"]["destination"] / "killed-controls").exists()


@pytest.mark.asyncio
async def test_existing_destination_is_never_overwritten_or_reused(ready):
    target = ready["args"]["destination"]
    target.mkdir(mode=0o700)
    marker = target / "preserve"
    marker.write_bytes(b"existing state")
    with pytest.raises(ValueError, match=DENIAL):
        await module().restore_encrypted_stock_backup(**ready["args"])
    assert marker.read_bytes() == b"existing state"
    assert {path.name for path in target.iterdir()} == {"preserve"}


@pytest.mark.asyncio
async def test_low_disk_denies_before_plaintext_staging_or_decryption(ready, monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("insufficient capacity")

    monkeypatch.setattr(
        module().os,
        "fstatvfs",
        lambda fd: SimpleNamespace(f_bavail=0, f_frsize=4096, f_favail=100000),
    )
    monkeypatch.setattr(module(), "decrypt_stream", forbidden)
    with pytest.raises(ValueError, match=DENIAL):
        await module().restore_encrypted_stock_backup(**ready["args"])
    assert calls == [] and not ready["args"]["destination"].exists()


@pytest.mark.asyncio
async def test_disk_budget_covers_fragment_rounding_for_bounded_tiny_file_count(ready, monkeypatch):
    fragment = 1024 * 1024
    bound = ready["args"]["ciphertext"].stat().st_size
    payload_and_reserve = 2 * bound + 100 * 1024 * 1024
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("allocation rounding exceeds capacity")

    monkeypatch.setattr(
        module().os,
        "fstatvfs",
        lambda fd: SimpleNamespace(
            f_bavail=(payload_and_reserve + fragment - 1) // fragment + 1,
            f_frsize=fragment,
            f_favail=100000,
        ),
    )
    monkeypatch.setattr(module(), "decrypt_stream", forbidden)
    with pytest.raises(ValueError, match=DENIAL):
        await module().restore_encrypted_stock_backup(**ready["args"])
    assert calls == [] and not ready["args"]["destination"].exists()


@pytest.mark.asyncio
async def test_expired_or_rollback_monotonic_window_is_denied_without_staging(ready, monkeypatch):
    ticks = iter((100.0, 100.0, 401.0))
    monkeypatch.setattr(module(), "monotonic", lambda: next(ticks))
    with pytest.raises(ValueError, match=DENIAL):
        await module().restore_encrypted_stock_backup(**ready["args"])
    assert not ready["args"]["destination"].exists()


@pytest.mark.asyncio
async def test_input_replacement_after_decryption_is_denied_and_plaintext_is_retained(
    ready, monkeypatch
):
    original = module().decrypt_stream

    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        ready["args"]["private_key_file"].write_bytes(b"x" * 32)
        return result

    monkeypatch.setattr(module(), "decrypt_stream", mutate)
    with pytest.raises(ValueError, match=DENIAL):
        await module().restore_encrypted_stock_backup(**ready["args"])
    assert (ready["args"]["destination"] / ".snapshot-bundle.tmp").exists()


def test_cli_uses_actual_utc_and_emits_only_safe_receipt_fields(ready, capsys, monkeypatch):
    args = ready["args"]
    original = module().restore_encrypted_stock_backup
    observed = []

    async def capture(*args, **kwargs):
        observed.append(kwargs["now"])
        return await original(*args, **kwargs)

    monkeypatch.setattr(module(), "restore_encrypted_stock_backup", capture)
    started = datetime.now(UTC)
    code = module().main(
        [
            "--ciphertext",
            str(args["ciphertext"]),
            "--private-key-file",
            str(args["private_key_file"]),
            "--destination",
            str(args["destination"]),
            "--expected-ciphertext-sha256",
            args["expected_ciphertext_sha256"],
            "--expected-snapshot-manifest-sha256",
            args["expected_snapshot_manifest_sha256"],
        ]
    )
    assert code == 0
    assert len(observed) == 1 and started <= observed[0] <= datetime.now(UTC)
    output = capsys.readouterr()
    record = json.loads(output.out)
    assert record["offline_only"] is True and record["live_enabled"] is False
    assert str(args["private_key_file"]) not in output.out + output.err
    assert str(args["ciphertext"]) not in output.out + output.err


def test_cli_refuses_time_override_and_reports_sanitized_errors(ready, capsys):
    assert module().main(["--now", "fictional-provider-secret"]) == 2
    output = capsys.readouterr()
    assert "fictional-provider-secret" not in output.out + output.err
    assert json.loads(output.out)["reason"] == "stock_backup_restore_unavailable"


@pytest.mark.asyncio
async def test_nonempty_committed_report_keeps_its_original_observation_time(sample):
    report = await discovery(sample)
    snapshot = await create_stock_snapshot(**sample)
    root = sample["destination"].parent
    key = root / "receiver.key"
    key.write_bytes(PRIVATE)
    key.chmod(0o600)
    cipher = seal(root)
    destination = root / "drill"
    result = await module().restore_encrypted_stock_backup(
        root / "backup.box",
        key,
        destination=destination,
        expected_ciphertext_sha256=cipher.ciphertext_sha256,
        expected_snapshot_manifest_sha256=snapshot.manifest_sha256,
        now=NOW + timedelta(days=1),
    )
    assert (result.claim_count, result.result_count, result.pending_count) == (1, 1, 0)
    restored = destination / "snapshot/archive" / (report.report_sha256 + ".stock-screen.json")
    original = sample["archive_dir"] / restored.name
    assert restored.read_bytes() == original.read_bytes()
    assert json.loads(restored.read_bytes())["as_of"] == NOW.isoformat()


@pytest.mark.asyncio
async def test_recipient_key_material_never_enters_a_hash_or_public_receipt(ready, monkeypatch):
    original = hashlib.sha256
    hashed = []

    class GuardedHash:
        def __init__(self, body=b""):
            assert bytes(body) != PRIVATE
            self.inner = original(body)

        def update(self, body):
            assert bytes(body) != PRIVATE
            hashed.append(len(body))
            self.inner.update(body)

        def __getattr__(self, key):
            return getattr(self.inner, key)

    monkeypatch.setattr(module().hashlib, "sha256", GuardedHash)
    result = await module().restore_encrypted_stock_backup(**ready["args"])
    assert hashed and PRIVATE.hex() not in json.dumps(asdict(result))


@pytest.mark.asyncio
async def test_no_free_inodes_denies_before_staging(ready, monkeypatch):
    monkeypatch.setattr(
        module().os,
        "fstatvfs",
        lambda fd: SimpleNamespace(f_bavail=2**40, f_frsize=4096, f_favail=0),
    )
    with pytest.raises(ValueError, match=DENIAL):
        await module().restore_encrypted_stock_backup(**ready["args"])
    assert not ready["args"]["destination"].exists()


@pytest.mark.asyncio
async def test_deadline_is_checked_inside_decrypt_io_before_plaintext_write(ready, monkeypatch):
    api = module()
    original_decrypt, original_clock = api.decrypt_stream, api.monotonic

    def expire(*args, **kwargs):
        monkeypatch.setattr(api, "monotonic", lambda: original_clock() + 301)
        return original_decrypt(*args, **kwargs)

    monkeypatch.setattr(api, "decrypt_stream", expire)
    with pytest.raises(ValueError, match=DENIAL):
        await api.restore_encrypted_stock_backup(**ready["args"])
    assert (ready["args"]["destination"] / ".snapshot-bundle.tmp").stat().st_size == 0


@pytest.mark.asyncio
async def test_async_application_replay_respects_remaining_deadline(ready, monkeypatch):
    async def slow(*args, **kwargs):
        await asyncio.sleep(1)
        raise AssertionError("must time out first")

    monkeypatch.setattr(module(), "verify_stock_snapshot", slow)
    monkeypatch.setattr(module()._Window, "remaining", lambda self: 0.001)
    with pytest.raises(ValueError, match=DENIAL):
        await module().restore_encrypted_stock_backup(**ready["args"])
    assert (ready["args"]["destination"] / ".snapshot-bundle.tmp").exists()
    assert not (ready["args"]["destination"] / "killed-controls").exists()


@pytest.mark.parametrize("elapsed", [-1, 301])
def test_local_wall_window_rejects_rollback_or_elapsed_budget(monkeypatch, elapsed):
    stamps = iter((NOW, NOW + timedelta(seconds=elapsed)))

    class Clock:
        @staticmethod
        def now(zone):
            assert zone is UTC
            return next(stamps)

    monkeypatch.setattr(module(), "datetime", Clock)
    monkeypatch.setattr(module(), "monotonic", lambda: 0.0)
    window = module()._Window()
    with pytest.raises(ValueError, match=DENIAL):
        window.check()


@pytest.mark.asyncio
async def test_short_private_key_reads_are_accumulated_for_a_successful_restore(ready, monkeypatch):
    inode = ready["args"]["private_key_file"].stat().st_ino
    original = os.read
    reads = []

    def short(descriptor, size):
        if os.fstat(descriptor).st_ino == inode:
            reads.append(size)
            return original(descriptor, min(size, 3))
        return original(descriptor, size)

    monkeypatch.setattr(module().os, "read", short)
    result = await module().restore_encrypted_stock_backup(**ready["args"])
    assert result.offline_only is True and len(reads) > 10


@pytest.mark.asyncio
async def test_final_cleanup_latency_cannot_return_a_receipt_after_the_deadline(ready, monkeypatch):
    api = module()
    original_sync, original_clock = os.fsync, api.monotonic

    def late(descriptor):
        original_sync(descriptor)
        root = ready["args"]["destination"]
        if (root / "killed-controls").exists() and not (root / ".snapshot-bundle.tmp").exists():
            monkeypatch.setattr(api, "monotonic", lambda: original_clock() + 301)

    monkeypatch.setattr(api.os, "fsync", late)
    with pytest.raises(ValueError, match=DENIAL):
        await api.restore_encrypted_stock_backup(**ready["args"])


@pytest.mark.parametrize("drift", ["replaced", "public"])
def test_new_namespace_rechecks_its_named_private_parent_before_success(tmp_path, drift):
    api = module()
    parent = tmp_path / "private-output"
    parent.mkdir(mode=0o700)
    destination = parent / "offline-drill"
    with pytest.raises(ValueError, match=DENIAL), api._new_root(destination, 0, api._Window()):
        if drift == "public":
            parent.chmod(0o755)
        else:
            original = tmp_path / "displaced-output"
            parent.rename(original)
            parent.mkdir(mode=0o700)
            (original / destination.name).rename(destination)
    assert destination.is_dir()


@pytest.fixture
async def populated_restore(sample):
    await discovery(sample)
    engine = create_engine(f"sqlite+aiosqlite:///{sample['database']}")
    try:
        await export_stock_dashboard(
            loaded=sample["loaded"],
            code_hash=CODE,
            factory=async_session_factory(engine),
            archive_dir=sample["archive_dir"],
            export_dir=sample["export_dir"],
            clock=lambda: NOW,
        )
    finally:
        await engine.dispose()
    snapshot = await create_stock_snapshot(**sample)
    root = sample["destination"].parent
    key = root / "receiver.key"
    key.write_bytes(PRIVATE)
    key.chmod(0o600)
    cipher = seal(root)
    return {
        "ciphertext": root / "backup.box",
        "private_key_file": key,
        "destination": root / "offline-drill",
        "expected_ciphertext_sha256": cipher.ciphertext_sha256,
        "expected_snapshot_manifest_sha256": snapshot.manifest_sha256,
        "now": NOW + timedelta(hours=1),
    }


def mutate_snapshot(root, target):
    if target == "ledger":
        connection = sqlite3.connect(root / "state/ledger.sqlite3")
        try:
            connection.execute("PRAGMA user_version = 7")
            connection.commit()
        finally:
            connection.close()
    elif target == "archive":
        next((root / "archive").glob("*.stock-screen.json")).write_bytes(b"changed research")
    else:
        (root / "exports/stock-research.json").write_bytes(b"{}")


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["ledger", "archive", "export"])
async def test_actual_snapshot_mutation_after_restore_checks_denies_receipt(
    populated_restore, monkeypatch, target
):
    api = module()
    destination = populated_restore["destination"]
    original = api._hash
    mutated = []

    def late(source, window):
        result = original(source, window)
        if (
            source.path == destination / "snapshot/manifest.json"
            and (destination / "killed-controls").exists()
            and not mutated
        ):
            before = source.path.read_bytes()
            mutate_snapshot(destination / "snapshot", target)
            assert source.path.read_bytes() == before
            mutated.append(True)
        return result

    monkeypatch.setattr(api, "_hash", late)
    with pytest.raises(ValueError, match=DENIAL):
        await api.restore_encrypted_stock_backup(**populated_restore)
    assert mutated == [True] and (destination / ".snapshot-bundle.tmp").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["altered", "replaced", "saved-copy"])
async def test_restored_killed_namespace_must_remain_exact_at_final_boundary(
    ready, monkeypatch, change
):
    api = module()
    destination = ready["args"]["destination"]
    original = api._hash
    mutated = []

    def late(source, window):
        result = original(source, window)
        if (
            source.path == destination / "snapshot/manifest.json"
            and (destination / "killed-controls").exists()
            and not mutated
        ):
            path = destination / "killed-controls/controls/stock-control.json"
            if change == "altered":
                body = json.loads(path.read_bytes())
                body["changed_at"] = "2026-10-22T12:30:00Z"
                path.write_bytes(
                    (json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n").encode()
                )
            elif change == "replaced":
                replacement = path.with_name("replacement")
                replacement.write_bytes(path.read_bytes())
                replacement.chmod(0o600)
                replacement.replace(path)
            else:
                (destination / "killed-controls/saved-control.json").write_bytes(b"{}\n")
            mutated.append(True)
        return result

    monkeypatch.setattr(api, "_hash", late)
    with pytest.raises(ValueError, match=DENIAL):
        await api.restore_encrypted_stock_backup(**ready["args"])
    assert mutated == [True] and (destination / ".snapshot-bundle.tmp").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["ledger", "killed"])
async def test_final_cleanup_fsync_mutation_cannot_escape_receipt_proof(ready, monkeypatch, target):
    api = module()
    destination = ready["args"]["destination"]
    original = os.fsync
    mutated = []

    def late(descriptor):
        original(descriptor)
        if (
            not mutated
            and (destination / "killed-controls").exists()
            and not (destination / ".snapshot-bundle.tmp").exists()
        ):
            if target == "ledger":
                mutate_snapshot(destination / "snapshot", "ledger")
            else:
                path = destination / "killed-controls/controls/stock-control.json"
                path.write_bytes(b"{}\n")
            mutated.append(True)

    monkeypatch.setattr(api.os, "fsync", late)
    with pytest.raises(ValueError, match=DENIAL):
        await api.restore_encrypted_stock_backup(**ready["args"])
    assert mutated == [True] and (destination / "snapshot").is_dir()


@pytest.mark.asyncio
async def test_final_application_replay_uses_the_remaining_outer_deadline(ready, monkeypatch):
    api = module()
    original_verify, original_remaining = api.verify_stock_snapshot, api._Window.remaining
    calls = []

    async def slow(root, *, now):
        calls.append(True)
        if len(calls) == 2:
            await asyncio.sleep(1)
            raise AssertionError("remaining outer deadline must cancel final replay")
        return await original_verify(root, now=now)

    def remaining(window):
        value = original_remaining(window)
        return 0.001 if calls else value

    monkeypatch.setattr(api, "verify_stock_snapshot", slow)
    monkeypatch.setattr(api._Window, "remaining", remaining)
    with pytest.raises(ValueError, match=DENIAL):
        await api.restore_encrypted_stock_backup(**ready["args"])
    assert len(calls) == 2 and (ready["args"]["destination"] / ".snapshot-bundle.tmp").exists()


@pytest.mark.asyncio
async def test_final_canonical_byte_proof_checks_deadline_inside_stream_io(ready, monkeypatch):
    api = module()
    original_pack, original_clock = api.pack_snapshot, api.monotonic
    calls = []

    def expired(*args, **kwargs):
        calls.append(True)
        monkeypatch.setattr(api, "monotonic", lambda: original_clock() + 301)
        return original_pack(*args, **kwargs)

    monkeypatch.setattr(api, "pack_snapshot", expired)
    with pytest.raises(ValueError, match=DENIAL):
        await api.restore_encrypted_stock_backup(**ready["args"])
    assert calls == [True] and (ready["args"]["destination"] / "snapshot").is_dir()


@pytest.mark.asyncio
async def test_byte_mutation_after_final_replay_returns_cannot_become_a_success(ready, monkeypatch):
    api = module()
    original = api.verify_stock_snapshot
    calls = []

    async def late(root, *, now):
        result = await original(root, now=now)
        calls.append(True)
        if len(calls) == 2:
            mutate_snapshot(root, "ledger")
        return result

    monkeypatch.setattr(api, "verify_stock_snapshot", late)
    with pytest.raises(ValueError, match=DENIAL):
        await api.restore_encrypted_stock_backup(**ready["args"])
    assert len(calls) == 2 and (ready["args"]["destination"] / "snapshot").is_dir()
