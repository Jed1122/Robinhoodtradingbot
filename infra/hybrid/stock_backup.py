"""Fixed native backup coordinator; ciphertext publication precedes any receipt.

The operations lock excludes collectors and maintenance. The separately reaped
UID10001 helper performs application replay; this coordinator independently binds
its closed evidence to the exact private snapshot and canonical bundle bytes.
Failed staging and published ciphertext without a receipt remain evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import time
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from nacl.public import PublicKey, SealedBox

from infra.hybrid.stock_attempts import AttemptStore, _stopped, operations
from infra.hybrid.stock_engine import StockEngineReader
from infra.hybrid.stock_maintenance_process import run_local_helper
from infra.hybrid.stock_release import StockRelease, load_release
from infra.hybrid.stock_units import unit_files
from trading_bot.market_data.recording import canonical_json
from trading_bot.runtime.stock_backup_crypto import StockBackupCryptoReceipt
from trading_bot.runtime.stock_backup_files import _directory, _stamp, encrypt_snapshot_bundle
from trading_bot.runtime.stock_operation_receipts import StockOperationReceipts
from trading_bot.runtime.stock_research_controls import StockControlRecord, _encode
from trading_bot.runtime.stock_snapshot_bundle import _file_limit, _header

_ROOT = Path("/var/lib/hybrid-stock-research")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_STAGE = re.compile(r"([0-9a-f]{32})(\.bundle)?\Z")
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_MAXIMUM = 2 * 1024**3
_TREES = ("archive", "exports", "state")
_ROOT_FILES = {"canonical-config.json", "saved-control.json", "manifest.json"}


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError


def _hash(value: object) -> str:
    _require(type(value) is str and _HEX.fullmatch(value) is not None)
    return str(value)


def _integer(value: object, maximum: int, minimum: int = 0) -> int:
    _require(type(value) is int and minimum <= value <= maximum)
    return cast(int, value)


def _private(info: os.stat_result, uid: int, *, mode: int = 0o600) -> None:
    _require(stat.S_ISREG(info.st_mode) and info.st_uid == uid)
    _require(info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == mode)


def _recipient(path: Path) -> bytes:
    with _directory(path.parent, os.geteuid()) as parent:
        descriptor = os.open(path.name, _READ, dir_fd=parent)
        try:
            original = os.fstat(descriptor)
            _private(original, os.geteuid(), mode=0o400)
            _require(original.st_size == 32)
            value = os.read(descriptor, 33)
            _require(len(value) == 32)
            # Length alone permits low-order Curve25519 points. Exercise the
            # actual public-only sealing API before creating private plaintext.
            SealedBox(PublicKey(value)).encrypt(b"stock-backup-recipient-check-v1")
            _require(_stamp(original) == _stamp(os.fstat(descriptor)))
            _require(
                _stamp(original) == _stamp(os.stat(path.name, dir_fd=parent, follow_symlinks=False))
            )
            return value
        finally:
            os.close(descriptor)


def _worker_terminal(store: AttemptStore) -> None:
    target = store.snapshot()
    if target is None or target.abandoned_sha256 is not None:
        return
    if target.stopped_sha256 is None or target.container_id is None:
        raise ValueError
    _stopped(StockEngineReader().inspect(target.container_id), target.attempt, target.container_id)


def _cipher_metadata(directory: int, covered: dict[str, int]) -> dict[str, tuple[int, ...]]:
    result: dict[str, tuple[int, ...]] = {}
    with os.scandir(directory) as entries:
        for entry in entries:
            _require(len(result) < 16)
            digest, separator, suffix = entry.name.partition(".")
            _require(separator == "." and suffix == "stockbackup")
            digest = _hash(digest)
            _require(digest in covered)
            info = entry.stat(follow_symlinks=False)
            _private(info, os.geteuid())
            _require(_integer(info.st_size, _MAXIMUM + 131072, 1) == covered[digest])
            result[entry.name] = _stamp(info)
    return result


def _reconcile_backups(backup_root: Path, receipt_root: Path, *, now: datetime) -> None:
    """Deny unacknowledged generations before creating any new plaintext.

    This admission check bounds metadata to16 retained ciphertexts and128 trusted
    receipts. Publication/copy/restore verify ciphertext bytes; admission binds
    retained names/sizes to those receipts without rehashing up to32GiB. Historical
    release identities remain legitimate, and unknown evidence is never repaired.
    """
    covered: dict[str, int] = {}
    for record in StockOperationReceipts(receipt_root).all(now=now):
        if record["kind"] != "backup":
            continue
        digest = _hash(record["ciphertext_sha256"])
        _require(digest not in covered)
        _require(
            _hash(record["code_hash"])
            == hashlib.sha256(f"oci-image:{record['image_digest']}".encode()).hexdigest()
        )
        for field in ("snapshot_manifest_sha256", "config_hash", "release_id"):
            _hash(record[field])
        covered[digest] = _integer(record["ciphertext_bytes"], _MAXIMUM + 131072, 1)
    with _directory(backup_root, os.geteuid()) as directory:
        before = _cipher_metadata(directory, covered)
        _require(_cipher_metadata(directory, covered) == before)


def _staging(parent: int, uid: int) -> dict[str, tuple[int, ...]]:
    result = {}
    identifiers = set()
    with os.scandir(parent) as entries:
        for entry in entries:
            match = _STAGE.fullmatch(entry.name)
            if match is None:
                raise ValueError
            identifiers.add(match[1])
            _require(len(identifiers) <= 4)
            info = entry.stat(follow_symlinks=False)
            if match[2]:
                _private(info, uid)
                _require(0 <= info.st_size <= _MAXIMUM)
            else:
                _require(stat.S_ISDIR(info.st_mode) and info.st_uid == uid)
                _require(stat.S_IMODE(info.st_mode) == 0o700)
            result[entry.name] = _stamp(info)
    return result


def _json(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw)
    _require(type(value) is dict and canonical_json(value).encode() == raw)
    return dict(value)


def _names(directory: int) -> set[str]:
    result: set[str] = set()
    with os.scandir(directory) as entries:
        for entry in entries:
            _require(len(result) < 20000)
            result.add(entry.name)
    return result


@dataclass(frozen=True)
class _Snapshot:
    manifest: dict[str, Any]
    manifest_sha256: str
    files: dict[str, dict[str, Any]]
    stamps: dict[str, tuple[int, ...]]
    bundle_sha256: str
    stream_bytes: int


def _snapshot(root: Path, uid: int, *, deadline: float) -> _Snapshot:
    """Read bounded descriptors once; also hash the exact canonical USTAR stream."""
    with ExitStack() as stack:
        directories = {"": stack.enter_context(_directory(root, uid))}
        _require(_names(directories[""]) == _ROOT_FILES | set(_TREES))
        for tree in _TREES:
            directories[tree] = stack.enter_context(_directory(root / tree, uid))
        _require(_names(directories["state"]) == {"ledger.sqlite3"})
        stamps = {tree + "/": _stamp(os.fstat(fd)) for tree, fd in directories.items()}
        files: dict[str, dict[str, Any]] = {}
        bodies: dict[str, bytes] = {}
        bundle = hashlib.sha256()
        for tree in _TREES:
            bundle.update(_header(tree, directory=True))
        framed = 5 * 512
        names = sorted(
            (tree + "/" + name if tree else name)
            for tree, fd in directories.items()
            for name in _names(fd)
            if name not in _TREES
        )
        _require(len(names) <= 20000)
        for name in names:
            _require(time.monotonic() < deadline)
            tree, _, leaf = name.rpartition("/")
            directory = directories[tree]
            descriptor = os.open(leaf, _READ, dir_fd=directory)
            try:
                original = os.fstat(descriptor)
                _private(original, uid)
                _require(0 <= original.st_size <= _file_limit(name))
                framed += 512 + original.st_size + (-original.st_size % 512)
                _require(framed <= _MAXIMUM)
                digest = hashlib.sha256()
                bundle.update(_header(name, original.st_size))
                body = bytearray()
                remaining = original.st_size
                while remaining:
                    _require(time.monotonic() < deadline)
                    chunk = os.read(descriptor, min(1024 * 1024, remaining))
                    _require(bool(chunk))
                    remaining -= len(chunk)
                    digest.update(chunk)
                    bundle.update(chunk)
                    if name in _ROOT_FILES:
                        body.extend(chunk)
                _require(os.read(descriptor, 1) == b"")
                bundle.update(b"\0" * (-original.st_size % 512))
                stamp = _stamp(original)
                _require(stamp == _stamp(os.fstat(descriptor)))
                _require(stamp == _stamp(os.stat(leaf, dir_fd=directory, follow_symlinks=False)))
                stamps[name] = stamp
                files[name] = {"sha256": digest.hexdigest(), "size": original.st_size}
                if name in _ROOT_FILES:
                    bodies[name] = bytes(body)
            finally:
                os.close(descriptor)
        bundle.update(b"\0" * 1024)
        _require(stamps == _metadata(root, uid))
        manifest = _json(bodies["manifest.json"])
        control = StockControlRecord.model_validate_json(bodies["saved-control.json"])
        _require(_encode(control) == bodies["saved-control.json"])
        _require(control.changed_at <= datetime.fromisoformat(manifest["created_at"]))
        _require(
            canonical_json(manifest["control"])
            == canonical_json(
                {
                    "control_id": control.control_id,
                    "generation": control.generation,
                    "status": control.status,
                    "state_sha256": files["saved-control.json"]["sha256"],
                }
            )
        )
        return _Snapshot(
            manifest, files["manifest.json"]["sha256"], files, stamps, bundle.hexdigest(), framed
        )


def _metadata(root: Path, uid: int) -> dict[str, tuple[int, ...]]:
    with ExitStack() as stack:
        directories = {"": stack.enter_context(_directory(root, uid))}
        _require(_names(directories[""]) == _ROOT_FILES | set(_TREES))
        for tree in _TREES:
            directories[tree] = stack.enter_context(_directory(root / tree, uid))
        result = {tree + "/": _stamp(os.fstat(fd)) for tree, fd in directories.items()}
        for tree, fd in directories.items():
            for name in _names(fd):
                if not tree and name in _TREES:
                    continue
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                _private(info, uid)
                result[tree + "/" + name if tree else name] = _stamp(info)
        return result


def _evidence(
    value: object,
    identifier: str,
    snapshot: _Snapshot,
    release: StockRelease,
    *,
    started: datetime,
    now: datetime,
) -> None:
    _require(type(value) is dict)
    value = cast(dict[str, Any], value)
    _require(set(value) == {"status", "identifier", "snapshot", "bundle"})
    _require(value["status"] == "snapshot_bundled" and value["identifier"] == identifier)
    result, bundle = value["snapshot"], value["bundle"]
    _require(type(result) is dict and type(bundle) is dict)
    _require(
        set(result)
        == {
            "manifest_sha256",
            "file_count",
            "total_bytes",
            "claim_count",
            "result_count",
            "pending_count",
            "state_sha256",
            "budget_by_day",
        }
    )
    _require(set(bundle) == {"bundle_sha256", "file_count", "total_bytes", "stream_bytes"})
    manifest = snapshot.manifest
    _require(
        set(manifest)
        == {
            "schema_version",
            "kind",
            "created_at",
            "config_hash",
            "code_hash",
            "control",
            "application",
            "files",
        }
    )
    _require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1)
    _require(manifest["kind"] == "stock_application_snapshot")
    created = datetime.fromisoformat(manifest["created_at"])
    _require(created.tzinfo is not None and created.utcoffset() == timedelta(0))
    _require(started <= created <= now)
    code_hash = hashlib.sha256(f"oci-image:{release.image_digest}".encode()).hexdigest()
    _require(manifest["config_hash"] == release.config_hash and manifest["code_hash"] == code_hash)
    _require(snapshot.files["canonical-config.json"]["sha256"] == release.config_hash)
    files = {name: row for name, row in snapshot.files.items() if name != "manifest.json"}
    _require(canonical_json(manifest["files"]) == canonical_json(files))
    _require(_hash(result["manifest_sha256"]) == snapshot.manifest_sha256)
    _require(_integer(result["file_count"], 19999) == len(files))
    _require(
        _integer(result["total_bytes"], _MAXIMUM) == sum(row["size"] for row in files.values())
    )
    application = manifest["application"]
    _require(type(application) is dict)
    _require(
        set(application)
        == {"claim_count", "result_count", "pending_count", "state_sha256", "budget_by_day"}
    )
    for field in ("claim_count", "result_count", "pending_count"):
        _integer(application[field], 100000)
        _require(_integer(result[field], 100000) == application[field])
    _require(
        application["result_count"] + application["pending_count"] == application["claim_count"]
    )
    _require(_hash(result["state_sha256"]) == _hash(application["state_sha256"]))
    budget = application["budget_by_day"]
    _require(type(budget) is dict and len(budget) <= 100000)
    for day, charge in budget.items():
        _require(type(day) is str and date.fromisoformat(day).isoformat() == day)
        _integer(charge, 10**12, 1)
    _require(canonical_json(result["budget_by_day"]) == canonical_json(sorted(budget.items())))
    _require(_hash(bundle["bundle_sha256"]) == snapshot.bundle_sha256)
    _require(_integer(bundle["file_count"], 20000) == len(snapshot.files))
    _require(
        _integer(bundle["total_bytes"], _MAXIMUM)
        == sum(row["size"] for row in snapshot.files.values())
    )
    _require(_integer(bundle["stream_bytes"], _MAXIMUM, 1) == snapshot.stream_bytes)


def _cleanup(
    parent: int,
    root: Path,
    identifier: str,
    uid: int,
    snapshot: _Snapshot,
    before: dict[str, tuple[int, ...]],
    bundle_stamp: tuple[int, ...],
) -> None:
    _require(bool(getattr(shutil.rmtree, "avoids_symlink_attacks", False)))
    _require(_metadata(root / identifier, uid) == snapshot.stamps)
    expected = before | {identifier: snapshot.stamps["/"], identifier + ".bundle": bundle_stamp}
    _require(_staging(parent, uid) == expected)
    shutil.rmtree(identifier, dir_fd=parent)
    _require(
        _stamp(os.stat(identifier + ".bundle", dir_fd=parent, follow_symlinks=False))
        == bundle_stamp
    )
    os.unlink(identifier + ".bundle", dir_fd=parent)
    os.fsync(parent)
    _require(_staging(parent, uid) == before)


def _backup_stock(
    manifest: Path,
    *,
    checkout: Path,
    backup_root: Path,
    staging_root: Path,
    receipt_root: Path,
    recipient_path: Path,
    helper_uid: int,
) -> dict[str, object]:
    """Private fixture seam; production callers use the fixed root-only wrapper."""
    try:
        _integer(helper_uid, 2**31 - 1)
        release = load_release(manifest)
        unit_files(release, checkout)
        recipient = _recipient(recipient_path)
        with operations() as store:
            _worker_terminal(store)
            _reconcile_backups(backup_root, receipt_root, now=datetime.now(UTC))
            with _directory(staging_root, helper_uid) as parent:
                before = _staging(parent, helper_uid)
                _require(len({name[:32] for name in before}) < 4)
                identifier = uuid.uuid4().hex
                _require(identifier not in {name[:32] for name in before})
                started = datetime.now(UTC)
                deadline = time.monotonic() + 300
                value = run_local_helper(
                    checkout,
                    release,
                    "snapshot",
                    identifier=identifier,
                    deadline=time.monotonic() + 220,
                )
                snapshot = _snapshot(staging_root / identifier, helper_uid, deadline=deadline)
                _evidence(
                    value, identifier, snapshot, release, started=started, now=datetime.now(UTC)
                )
                after = _staging(parent, helper_uid)
                bundle_name = identifier + ".bundle"
                expected = before | {
                    identifier: snapshot.stamps["/"],
                    bundle_name: after[bundle_name],
                }
                _require(after == expected and after[bundle_name][6] == snapshot.stream_bytes)
                _require(time.monotonic() < deadline)
                published, encrypted = encrypt_snapshot_bundle(
                    source=staging_root / bundle_name,
                    source_uid=helper_uid,
                    destination_root=backup_root,
                    recipient_public_key=recipient,
                    expected_plaintext_sha256=snapshot.bundle_sha256,
                )
                _require(type(encrypted) is StockBackupCryptoReceipt)
                _require(type(encrypted.version) is int and encrypted.version == 1)
                _require(encrypted.plaintext_sha256 == snapshot.bundle_sha256)
                _require(encrypted.plaintext_bytes == snapshot.stream_bytes)
                _hash(encrypted.ciphertext_sha256)
                _integer(encrypted.ciphertext_bytes, _MAXIMUM + 131072, 1)
                _require(published == backup_root / (encrypted.ciphertext_sha256 + ".stockbackup"))
                _require(time.monotonic() < deadline)
                _cleanup(
                    parent,
                    staging_root,
                    identifier,
                    helper_uid,
                    snapshot,
                    before,
                    after[bundle_name],
                )
                StockOperationReceipts(receipt_root).record(
                    kind="backup",
                    at=datetime.now(UTC),
                    ciphertext_sha256=encrypted.ciphertext_sha256,
                    ciphertext_bytes=encrypted.ciphertext_bytes,
                    snapshot_manifest_sha256=snapshot.manifest_sha256,
                    config_hash=release.config_hash,
                    code_hash=hashlib.sha256(
                        f"oci-image:{release.image_digest}".encode()
                    ).hexdigest(),
                    release_id=release.release_id,
                    image_digest=release.image_digest,
                )
        return {
            "status": "backup_committed",
            "live_enabled": False,
            "ciphertext_sha256": encrypted.ciphertext_sha256,
            "snapshot_manifest_sha256": snapshot.manifest_sha256,
        }
    except Exception:
        raise ValueError("stock_backup_unavailable") from None


def backup_stock(manifest: Path, *, checkout: Path) -> dict[str, object]:
    """Root-only fixed namespace; accepts only the public recipient key."""
    if sys.platform != "linux" or os.geteuid() != 0:
        raise ValueError("stock_backup_unavailable")
    return _backup_stock(
        manifest,
        checkout=checkout,
        backup_root=Path("/var/lib/hybrid-stock-backups"),
        staging_root=_ROOT / "maintenance",
        receipt_root=Path("/var/lib/hybrid-stock-maintenance/receipts"),
        recipient_path=Path("/etc/hybrid-stock-research/backup-recipient.public"),
        helper_uid=10001,
    )
