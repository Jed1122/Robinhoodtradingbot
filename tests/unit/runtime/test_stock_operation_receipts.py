"""Private local receipt consistency only; no copy, encryption or restore is attested."""

import importlib
import json
import os
import shutil
import stat
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

NOW = datetime(2026, 10, 22, 23, 0, tzinfo=UTC)
AT = NOW - timedelta(minutes=5)
LOCK = ".stock-receipts.lock"
ERROR = r"^stock_operation_receipts_unavailable$"


def module():
    path = (
        Path(__file__).resolve().parents[3] / "src/trading_bot/runtime/stock_operation_receipts.py"
    )
    assert path.is_file(), "Private immutable stock operation receipts are not implemented"
    return importlib.import_module("trading_bot.runtime.stock_operation_receipts")


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def fields(**changes):
    return {
        "kind": "backup",
        "at": AT,
        "ciphertext_sha256": "a" * 64,
        "ciphertext_bytes": 512,
        "snapshot_manifest_sha256": "b" * 64,
        "config_hash": "c" * 64,
        "code_hash": "d" * 64,
        "release_id": "e" * 64,
        "image_digest": "sha256:" + "f" * 64,
    } | changes


@pytest.fixture
def setup(tmp_path, monkeypatch):
    api = module()
    root = tmp_path.resolve() / "receipts"
    root.mkdir(mode=0o700)
    (root / LOCK).touch(mode=0o600)
    monkeypatch.setattr(api, "_clock", lambda: NOW)
    return api, root, api.StockOperationReceipts(root)


def saved(root, kind="backup", digest="a" * 64):
    return root / f"{kind}-{digest}.json"


def test_preinitialized_empty_store_has_no_receipts_or_implicit_files(tmp_path):
    api = module()
    root = tmp_path.resolve() / "receipts"
    root.mkdir(mode=0o700)
    (root / LOCK).touch(mode=0o600)
    store = api.StockOperationReceipts(root)
    before = (root / LOCK).stat()
    assert store.all(now=NOW) == () and store.latest("backup", now=NOW) is None
    assert list(root.iterdir()) == [root / LOCK]
    assert (root / LOCK).read_bytes() == b"" and (root / LOCK).stat().st_ino == before.st_ino


def test_record_is_private_immutable_canonical_and_has_only_closed_metadata(setup):
    _, root, store = setup
    result = store.record(**fields())
    assert result == {
        "schema_version": 1,
        "kind": "backup",
        "at": "2026-10-22T22:55:00+00:00",
        "ciphertext_sha256": "a" * 64,
        "ciphertext_bytes": 512,
        "snapshot_manifest_sha256": "b" * 64,
        "config_hash": "c" * 64,
        "code_hash": "d" * 64,
        "release_id": "e" * 64,
        "image_digest": "sha256:" + "f" * 64,
    }
    path = saved(root)
    assert path.read_bytes() == encoded(result)
    info = path.stat()
    assert info.st_uid == os.geteuid() and info.st_mode & 0o7777 == 0o600 and info.st_nlink == 1
    assert store.latest("backup", now=NOW) == result and store.all(now=NOW) == (result,)
    assert {p.name for p in root.iterdir()} == {LOCK, path.name}


def test_offhost_and_restore_form_a_bound_chronological_chain(setup):
    _, _, store = setup
    backup = store.record(**fields())
    offhost = store.record(**fields(kind="offhost", at=AT + timedelta(seconds=1)))
    restore = store.record(**fields(kind="restore", at=AT + timedelta(seconds=2)))
    assert store.all(now=NOW) == (backup, offhost, restore)
    assert store.latest("offhost", now=NOW) == offhost
    assert store.latest("restore", now=NOW) == restore


def test_historical_identical_repeat_remains_idempotent_without_replacing_inode(setup):
    _, root, store = setup
    original = store.record(**fields())
    stamp = saved(root).stat()
    store.record(**fields(kind="offhost", at=AT + timedelta(seconds=1)))
    assert store.record(**fields()) == original
    assert saved(root).stat().st_ino == stamp.st_ino
    assert saved(root).stat().st_mtime_ns == stamp.st_mtime_ns
    assert len(store.all(now=NOW)) == 2


@pytest.mark.parametrize("kind", ["offhost", "restore"])
def test_successor_without_its_prior_operation_is_denied(setup, kind):
    _, root, store = setup
    with pytest.raises(ValueError, match=ERROR):
        store.record(**fields(kind=kind))
    assert list(root.iterdir()) == [root / LOCK]
    if kind == "restore":
        store.record(**fields())
        with pytest.raises(ValueError, match=ERROR):
            store.record(**fields(kind=kind, at=AT + timedelta(seconds=1)))


@pytest.mark.parametrize("kind", ["offhost", "restore"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("ciphertext_sha256", "1" * 64),
        ("ciphertext_bytes", 513),
        ("snapshot_manifest_sha256", "2" * 64),
        ("config_hash", "3" * 64),
        ("code_hash", "4" * 64),
        ("release_id", "5" * 64),
        ("image_digest", "sha256:" + "6" * 64),
    ],
)
def test_successor_must_match_every_backup_and_offhost_identity(setup, kind, field, value):
    _, _, store = setup
    store.record(**fields())
    if kind == "restore":
        store.record(**fields(kind="offhost"))
    with pytest.raises(ValueError, match=ERROR):
        store.record(**fields(kind=kind, **{field: value}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("at", AT + timedelta(seconds=1)),
        ("ciphertext_bytes", 513),
        ("snapshot_manifest_sha256", "2" * 64),
        ("config_hash", "3" * 64),
        ("code_hash", "4" * 64),
        ("release_id", "5" * 64),
        ("image_digest", "sha256:" + "6" * 64),
    ],
)
def test_existing_filename_cannot_be_overwritten_with_changed_metadata(setup, field, value):
    _, root, store = setup
    original = store.record(**fields())
    with pytest.raises(ValueError, match=ERROR):
        store.record(**fields(**{field: value}))
    assert saved(root).read_bytes() == encoded(original)


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "unknown"),
        ("kind", "../backup"),
        ("kind", True),
        ("at", "2026-10-22T22:55:00Z"),
        ("at", datetime(2026, 10, 22)),
        ("at", AT.astimezone(timezone(timedelta(hours=1)))),
        ("ciphertext_sha256", "A" * 64),
        ("ciphertext_sha256", "a" * 63),
        ("ciphertext_bytes", True),
        ("ciphertext_bytes", 512.0),
        ("ciphertext_bytes", 0),
        ("ciphertext_bytes", -1),
        ("ciphertext_bytes", 2**63),
        ("snapshot_manifest_sha256", None),
        ("config_hash", True),
        ("code_hash", "z" * 64),
        ("release_id", "e" * 65),
        ("image_digest", "sha256:" + "F" * 64),
    ],
)
def test_input_types_bounds_and_utc_are_closed(setup, field, value):
    _, root, store = setup
    with pytest.raises(ValueError, match=ERROR):
        store.record(**fields(**{field: value}))
    assert list(root.iterdir()) == [root / LOCK]


def test_new_receipts_deny_future_or_rollback_times_but_allow_equal_times(setup, monkeypatch):
    api, _, store = setup
    store.record(**fields())
    with pytest.raises(ValueError, match=ERROR):
        store.record(**fields(ciphertext_sha256="1" * 64, at=AT - timedelta(seconds=1)))
    with pytest.raises(ValueError, match=ERROR):
        store.record(**fields(ciphertext_sha256="1" * 64, at=NOW + timedelta(seconds=1)))
    store.record(**fields(ciphertext_sha256="1" * 64))
    monkeypatch.setattr(api, "_clock", lambda: AT - timedelta(seconds=1))
    with pytest.raises(ValueError, match=ERROR):
        store.record(**fields())


@pytest.mark.parametrize("kind", ["backup", "offhost", "restore"])
def test_any_future_receipt_denies_all_reads_and_wrong_now_is_rejected(setup, kind):
    _, _, store = setup
    store.record(**fields())
    for now in [AT - timedelta(seconds=1), datetime(2026, 10, 22), "now"]:
        with pytest.raises(ValueError, match=ERROR):
            store.latest(kind, now=now)
    with pytest.raises(ValueError, match=ERROR):
        store.all(now=AT - timedelta(seconds=1))


def test_same_instance_cannot_move_observation_clock_backwards_even_with_no_receipts(setup):
    _, _, store = setup
    assert store.all(now=NOW) == ()
    with pytest.raises(ValueError, match=ERROR):
        store.all(now=NOW - timedelta(seconds=1))


def test_latest_is_chronological_and_caller_cannot_mutate_retained_state(setup):
    _, _, store = setup
    first = store.record(**fields())
    second = store.record(**fields(ciphertext_sha256="1" * 64, at=AT + timedelta(seconds=1)))
    latest = store.latest("backup", now=NOW)
    assert latest == second
    latest["config_hash"] = "changed"
    first["code_hash"] = "changed"
    assert store.latest("backup", now=NOW) == second


@pytest.mark.parametrize("name", ["latest.json", ".stock-receipts.pending", "backup-%n.json"])
def test_unknown_entries_are_retained_and_deny_every_operation(setup, name):
    _, root, store = setup
    path = root / name
    path.write_bytes(b"unresolved private evidence")
    path.chmod(0o600)
    for call in [lambda: store.all(now=NOW), lambda: store.record(**fields())]:
        with pytest.raises(ValueError, match=ERROR):
            call()
    assert path.read_bytes() == b"unresolved private evidence"


@pytest.mark.parametrize(
    "mutation",
    [
        "writable",
        "symlink",
        "hardlink",
        "directory",
        "fifo",
        "oversize",
        "malformed",
        "spaces",
        "extra",
        "missing",
        "duplicate",
        "bool_version",
        "wrong_filename",
    ],
)
def test_retained_receipts_require_safe_metadata_closed_canonical_json_and_name_binding(
    setup, mutation
):
    _, root, store = setup
    value = store.record(**fields())
    path = saved(root)
    if mutation == "writable":
        path.chmod(0o644)
    elif mutation == "symlink":
        path.unlink()
        path.symlink_to(root / LOCK)
    elif mutation == "hardlink":
        os.link(path, root / ("offhost-" + "a" * 64 + ".json"))
    elif mutation in {"directory", "fifo"}:
        path.unlink()
        path.mkdir() if mutation == "directory" else os.mkfifo(path, 0o600)
    else:
        if mutation == "oversize":
            body = b"x" * 4097
        elif mutation == "malformed":
            body = b"{"
        elif mutation == "spaces":
            body = encoded(value) + b" "
        elif mutation == "duplicate":
            body = b'{"schema_version":1,"schema_version":1}\n'
        else:
            if mutation == "extra":
                value["unknown"] = "private"
            elif mutation == "missing":
                del value["config_hash"]
            elif mutation == "bool_version":
                value["schema_version"] = True
            else:
                value["ciphertext_sha256"] = "1" * 64
            body = encoded(value)
        path.write_bytes(body)
    with pytest.raises(ValueError, match=ERROR):
        store.all(now=NOW)


def test_broken_successor_in_retained_inventory_blocks_even_backup_latest(setup):
    _, root, store = setup
    value = store.record(**fields())
    value.update(kind="offhost", config_hash="1" * 64)
    saved(root, "offhost").write_bytes(encoded(value))
    saved(root, "offhost").chmod(0o600)
    with pytest.raises(ValueError, match=ERROR):
        store.latest("backup", now=NOW)


@pytest.mark.parametrize("mutation", ["missing", "nonempty", "writable", "symlink", "hardlink"])
def test_permanent_empty_private_single_link_lock_is_never_recreated_or_repaired(setup, mutation):
    _, root, store = setup
    anchor = root / LOCK
    if mutation == "missing":
        anchor.unlink()
    elif mutation == "nonempty":
        anchor.write_bytes(b"unsafe")
    elif mutation == "writable":
        anchor.chmod(0o644)
    elif mutation == "symlink":
        anchor.unlink()
        anchor.symlink_to(root / "absent")
    else:
        os.link(anchor, root / "unrelated")
    with pytest.raises(ValueError, match=ERROR):
        store.record(**fields())
    assert mutation != "missing" or not anchor.exists()


def test_root_must_preexist_be_private_and_cannot_have_symlink_ancestors(setup, tmp_path):
    api, root, store = setup
    absent = tmp_path.resolve() / "missing"
    with pytest.raises(ValueError, match=ERROR):
        api.StockOperationReceipts(absent).all(now=NOW)
    assert not absent.exists()
    alias = tmp_path.resolve() / "alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match=ERROR):
        api.StockOperationReceipts(alias).all(now=NOW)
    root.chmod(0o755)
    with pytest.raises(ValueError, match=ERROR):
        store.all(now=NOW)
    assert root.stat().st_mode & 0o777 == 0o755


def test_lock_contention_fails_without_modifying_receipts(setup):
    import fcntl

    _, root, store = setup
    with (root / LOCK).open("r+b") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match=ERROR):
            store.record(**fields())
    assert list(root.iterdir()) == [root / LOCK]


def test_capacity_denies_new_record_but_keeps_exact_idempotence(setup):
    _, root, store = setup
    first = None
    for index in range(128):
        result = store.record(**fields(ciphertext_sha256=f"{index:064x}"))
        if index == 0:
            first = result
    assert len(store.all(now=NOW)) == 128
    with pytest.raises(ValueError, match=ERROR):
        store.record(**fields(ciphertext_sha256="a" * 64))
    assert store.record(**fields(ciphertext_sha256="0" * 64)) == first
    assert len(list(root.iterdir())) == 129


def test_short_writes_are_completed_before_receipt_acknowledgement(setup, monkeypatch):
    api, _, store = setup
    actual = api.os.write
    monkeypatch.setattr(api.os, "write", lambda fd, body: actual(fd, body[:3]))
    assert store.record(**fields())["ciphertext_bytes"] == 512


def test_interrupted_publication_preserves_pending_incident_and_existing_receipts(
    setup, monkeypatch
):
    api, root, store = setup
    original = store.record(**fields())

    def fail(*args):
        raise OSError("fictional private failure")

    monkeypatch.setattr(api.os, "fsync", fail)
    with pytest.raises(ValueError, match=ERROR):
        store.record(**fields(ciphertext_sha256="1" * 64))
    assert saved(root).read_bytes() == encoded(original)
    assert (root / ".stock-receipts.pending").exists()
    with pytest.raises(ValueError, match=ERROR):
        store.all(now=NOW)


def test_failed_publication_directory_fsync_keeps_pending_fence_until_link_is_durable(
    setup, monkeypatch
):
    api, root, store = setup
    actual = api.os.fsync

    def fail_directory(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("fictional unacknowledged publication")
        actual(descriptor)

    monkeypatch.setattr(api.os, "fsync", fail_directory)
    with pytest.raises(ValueError, match=ERROR):
        store.record(**fields())
    assert (root / ".stock-receipts.pending").exists()
    with pytest.raises(ValueError, match=ERROR):
        store.latest("backup", now=NOW)


def test_replaced_root_during_read_is_denied_without_adopting_replacement(setup, monkeypatch):
    api, root, store = setup
    store.record(**fields())
    actual = api._read_record
    replaced = False

    def replace_root(*args):
        nonlocal replaced
        result = actual(*args)
        if not replaced:
            replaced = True
            old = root.with_name("preserved")
            root.rename(old)
            shutil.copytree(old, root)
        return result

    monkeypatch.setattr(api, "_read_record", replace_root)
    with pytest.raises(ValueError, match=ERROR):
        store.all(now=NOW)
