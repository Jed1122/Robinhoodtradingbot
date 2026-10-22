"""Owner-run encrypted stock restore drill into a new private offline namespace.

Trusted ciphertext and snapshot-manifest hashes are mandatory. No recipient key
is generated, returned, logged or hashed. Restored controls are always killed and
offline-only; this command never creates an executable operations namespace.
Failed private staging remains for explicit owner recovery. The caller still owns
disk quotas and an outer process deadline for blocking regular-file system calls.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import BinaryIO, NoReturn, cast

from trading_bot.clock import require_utc
from trading_bot.runtime.stock_backup_crypto import StockBackupCryptoReceipt, decrypt_stream
from trading_bot.runtime.stock_research_controls import StockResearchControls
from trading_bot.runtime.stock_snapshot import (
    ControlRestoreResult,
    restore_snapshot_controls,
    verify_stock_snapshot,
)
from trading_bot.runtime.stock_snapshot_bundle import pack_snapshot, unpack_snapshot

_MAXIMUM_BYTES = 2 * 1024**3
_CHUNK = 1024 * 1024
_MAXIMUM_CIPHERTEXT = 113 + _MAXIMUM_BYTES + 21 * ((_MAXIMUM_BYTES + _CHUNK - 1) // _CHUNK + 1)
_RESERVE_BYTES = 100 * 1024 * 1024
_TEMPORARY = ".snapshot-bundle.tmp"
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


class StockBackupRestoreError(ValueError):
    """Fixed public error without keys, paths, plaintext or provider exception text."""


@dataclass(frozen=True, slots=True)
class StockBackupRestoreReceipt:
    """Bundle counts include manifest.json; job counts come from application replay."""

    ciphertext_sha256: str
    snapshot_manifest_sha256: str
    bundle_sha256: str
    file_count: int
    total_bytes: int
    claim_count: int
    result_count: int
    pending_count: int
    state_sha256: str
    control_id: str
    control_generation: int
    offline_only: bool


def _deny() -> NoReturn:
    raise StockBackupRestoreError("stock_backup_restore_unavailable") from None


def _require(value: bool) -> None:
    if not value:
        _deny()


def _digest(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


class _Window:
    def __init__(self) -> None:
        self.origin = self.last = monotonic()
        _require(type(self.origin) in {float, int} and math.isfinite(self.origin))
        self.wall_origin = self.last_wall = require_utc(datetime.now(UTC))

    def check(self) -> None:
        current = monotonic()
        _require(type(current) in {float, int} and math.isfinite(current))
        _require(self.last <= current < self.origin + 300)
        wall = require_utc(datetime.now(UTC))
        _require(self.last_wall <= wall < self.wall_origin + timedelta(seconds=300))
        self.last = current
        self.last_wall = wall

    def remaining(self) -> float:
        self.check()
        return self.origin + 300 - self.last


class _TimedStream:
    def __init__(self, stream: BinaryIO, window: _Window, *, maximum_write: int = 0) -> None:
        self.stream, self.window = stream, window
        self.maximum_write, self.written = maximum_write, 0

    def read(self, size: int = -1) -> bytes:
        self.window.check()
        _require(type(size) is int and 0 < size <= _CHUNK + 17)
        result = self.stream.read(size)
        self.window.check()
        _require(type(result) is bytes and len(result) <= size)
        return result

    def write(self, body: bytes) -> int:
        self.window.check()
        _require(len(body) <= _CHUNK and self.written + len(body) <= self.maximum_write)
        count = self.stream.write(body)
        self.window.check()
        _require(type(count) is int and 0 < count <= len(body))
        self.written += count
        return count


class _Discard:
    def write(self, body: bytes) -> int:
        return len(body)


def _stamp(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _close(descriptors: tuple[int, ...]) -> None:
    failed = False
    for descriptor in descriptors:
        try:
            os.close(descriptor)
        except OSError:
            failed = True
    if failed:
        _deny()


def _path(path: Path) -> None:
    _require(isinstance(path, Path) and path.is_absolute() and len(str(path)) <= 4096)
    _require(path.name not in {"", ".", ".."})
    _require(path.parent.resolve(strict=True) == path.parent)


def _open_directory(path: Path) -> int:
    _require(path.is_absolute() and path.resolve(strict=True) == path)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(descriptor)
        _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid())
        _require(stat.S_IMODE(info.st_mode) == 0o700)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _private(info: os.stat_result) -> None:
    _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid())
    _require(stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1)


@dataclass(frozen=True, slots=True)
class _Input:
    path: Path
    parent: int
    descriptor: int
    info: os.stat_result

    def check(self) -> None:
        _require(_stamp(self.info) == _stamp(os.fstat(self.descriptor)))
        _require(
            _stamp(self.info)
            == _stamp(os.stat(self.path.name, dir_fd=self.parent, follow_symlinks=False))
        )
        current, named = os.fstat(self.parent), self.path.parent.stat(follow_symlinks=False)
        _require(stat.S_ISDIR(named.st_mode) and named.st_uid == os.geteuid())
        _require(stat.S_IMODE(named.st_mode) == 0o700)
        _require((current.st_dev, current.st_ino) == (named.st_dev, named.st_ino))


@contextmanager
def _input(path: Path, *, minimum: int, maximum: int) -> Iterator[_Input]:
    parent = descriptor = -1
    try:
        _path(path)
        parent = _open_directory(path.parent)
        descriptor = os.open(path.name, _READ, dir_fd=parent)
        info = os.fstat(descriptor)
        _private(info)
        _require(minimum <= info.st_size <= maximum)
        observation = _Input(path, parent, descriptor, info)
        observation.check()
        yield observation
        observation.check()
    finally:
        _close(tuple(fd for fd in (descriptor, parent) if fd >= 0))


def _hash(source: _Input, window: _Window) -> str:
    digest, count = hashlib.sha256(), 0
    while True:
        window.check()
        part = os.read(source.descriptor, min(_CHUNK, source.info.st_size - count + 1))
        window.check()
        if not part:
            break
        count += len(part)
        _require(count <= source.info.st_size)
        digest.update(part)
    _require(count == source.info.st_size)
    source.check()
    return digest.hexdigest()


def _read_key(source: _Input, window: _Window) -> bytes:
    key = bytearray()
    while True:
        window.check()
        part = os.read(source.descriptor, 33 - len(key))
        window.check()
        if not part:
            break
        key.extend(part)
        _require(len(key) <= 32)
    _require(len(key) == 32)
    source.check()
    return bytes(key)


@dataclass(frozen=True, slots=True)
class _Destination:
    path: Path
    parent: int
    descriptor: int

    def check(self) -> None:
        current, named = os.fstat(self.descriptor), self.path.stat(follow_symlinks=False)
        _require((current.st_dev, current.st_ino) == (named.st_dev, named.st_ino))
        _require(stat.S_ISDIR(named.st_mode) and named.st_uid == os.geteuid())
        _require(stat.S_IMODE(named.st_mode) == 0o700)
        current, named = os.fstat(self.parent), self.path.parent.stat(follow_symlinks=False)
        _require((current.st_dev, current.st_ino) == (named.st_dev, named.st_ino))
        _require(stat.S_ISDIR(named.st_mode) and named.st_uid == os.geteuid())
        _require(stat.S_IMODE(named.st_mode) == 0o700)
        _require(self.path.parent.resolve(strict=True) == self.path.parent)

    def sync(self) -> None:
        os.fsync(self.descriptor)
        os.fsync(self.parent)
        self.check()


@contextmanager
def _new_root(destination: Path, plaintext_bound: int, window: _Window) -> Iterator[_Destination]:
    parent = descriptor = -1
    try:
        _path(destination)
        parent = _open_directory(destination.parent)
        window.check()
        space = os.fstatvfs(parent)
        _require(space.f_bavail >= 0 and space.f_frsize > 0 and space.f_favail >= 0)
        entries = min(20000, plaintext_bound // 512) + 16
        # Each canonical entry has a 512-byte header, but tiny files can each
        # allocate a full filesystem fragment. Include isolated control staging.
        required_bytes = 2 * plaintext_bound + entries * space.f_frsize + _RESERVE_BYTES
        _require(space.f_bavail * space.f_frsize >= required_bytes)
        _require(space.f_favail >= entries)
        os.mkdir(destination.name, mode=0o700, dir_fd=parent)
        descriptor = os.open(
            destination.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent,
        )
        _require(stat.S_IMODE(os.fstat(descriptor).st_mode) == 0o700)
        os.fsync(parent)
        namespace = _Destination(destination, parent, descriptor)
        yield namespace
        # The caller syncs before its final byte proof. Exit performs read-only
        # identity checks so no later fsync separates that proof from success.
        namespace.check()
    finally:
        _close(tuple(fd for fd in (descriptor, parent) if fd >= 0))


def _killed_proof(
    destination: Path, controls: ControlRestoreResult, now: datetime, window: _Window
) -> tuple[object, ...]:
    root = destination / "killed-controls"
    paths = (root, root / "controls")
    descriptors: list[int] = []
    try:
        for path in paths:
            window.check()
            descriptors.append(_open_directory(path))
        original = tuple(_stamp(os.fstat(descriptor)) for descriptor in descriptors)
        _require(set(os.listdir(descriptors[0])) == {"saved-control.json", "controls"})
        _require(set(os.listdir(descriptors[1])) == {"stock-control.json", ".stock-control.lock"})
        files = []
        for name in (
            "saved-control.json",
            "controls/stock-control.json",
            "controls/.stock-control.lock",
        ):
            lock = name.endswith(".lock")
            with _input(
                root / name, minimum=0 if lock else 1, maximum=0 if lock else 8192
            ) as source:
                files.append((name, _stamp(source.info), _hash(source, window)))
        with _input(destination / "snapshot/saved-control.json", minimum=1, maximum=8192) as saved:
            _require(_hash(saved, window) == files[0][2])
        killed = StockResearchControls(root / "controls", clock=lambda: now).read()
        _require(killed.record.status == "killed" and killed.sha256 == controls.state_sha256)
        _require(killed.record.control_id == controls.control_id)
        _require(killed.record.generation == controls.generation)
        for path, descriptor, info in zip(paths, descriptors, original, strict=True):
            _require(
                _stamp(os.fstat(descriptor)) == info == _stamp(path.stat(follow_symlinks=False))
            )
        window.check()
        return killed, original, tuple(files)
    finally:
        _close(tuple(reversed(descriptors)))


def _decrypt(
    source: _Input, secret: _Input, root: int, plaintext_bound: int, window: _Window
) -> tuple[StockBackupCryptoReceipt, tuple[int, ...]]:
    descriptor = os.open(
        _TEMPORARY,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=root,
    )
    try:
        os.fchmod(descriptor, 0o600)
        key = _read_key(secret, window)
        try:
            os.lseek(source.descriptor, 0, os.SEEK_SET)
            with (
                os.fdopen(source.descriptor, "rb", closefd=False) as encrypted,
                os.fdopen(descriptor, "wb", closefd=False) as plain,
            ):
                crypto = decrypt_stream(
                    cast(BinaryIO, _TimedStream(encrypted, window)),
                    cast(BinaryIO, _TimedStream(plain, window, maximum_write=plaintext_bound)),
                    key,
                    max_bytes=_MAXIMUM_BYTES,
                )
                window.check()
                plain.flush()
                os.fsync(descriptor)
        finally:
            del key
        original = os.fstat(descriptor)
        _private(original)
        _require(original.st_size == crypto.plaintext_bytes)
        _require(crypto.ciphertext_bytes == source.info.st_size)
        source.check()
        secret.check()
        os.fsync(root)
        return crypto, _stamp(original)
    finally:
        os.close(descriptor)


async def restore_encrypted_stock_backup(
    ciphertext: Path,
    private_key_file: Path,
    *,
    destination: Path,
    expected_ciphertext_sha256: str,
    expected_snapshot_manifest_sha256: str,
    now: datetime,
) -> StockBackupRestoreReceipt:
    """Verify trusted identities, decrypt/replay privately, and restore killed controls.

    Recipient/public encryption does not authenticate a sender: both expected
    hashes must come from the owner's separately trusted backup receipt. An absent
    authoritative control high-water makes every successful drill offline-only.
    """
    try:
        _require(_digest(expected_ciphertext_sha256) and _digest(expected_snapshot_manifest_sha256))
        now = require_utc(now)
        window = _Window()
        with _input(ciphertext, minimum=134, maximum=_MAXIMUM_CIPHERTEXT) as source:
            actual_ciphertext = _hash(source, window)
            _require(actual_ciphertext == expected_ciphertext_sha256)
            plaintext_bound = min(_MAXIMUM_BYTES, source.info.st_size)
            with (
                _input(private_key_file, minimum=32, maximum=32) as secret,
                _new_root(destination, plaintext_bound, window) as namespace,
            ):
                root = namespace.descriptor
                crypto, original = _decrypt(source, secret, root, plaintext_bound, window)
                _require(crypto.ciphertext_sha256 == actual_ciphertext)
                with _input(destination / _TEMPORARY, minimum=1, maximum=plaintext_bound) as plain:
                    _require(_stamp(plain.info) == original)
                    with os.fdopen(plain.descriptor, "rb", closefd=False) as stream:
                        bundle = unpack_snapshot(
                            cast(BinaryIO, _TimedStream(stream, window)),
                            destination=destination / "snapshot",
                        )
                _require(bundle.bundle_sha256 == crypto.plaintext_sha256)
                _require(bundle.stream_bytes == crypto.plaintext_bytes)
                window.check()
                manifest_path = destination / "snapshot/manifest.json"
                with _input(manifest_path, minimum=1, maximum=32 * 1024 * 1024) as manifest:
                    manifest_sha256 = _hash(manifest, window)
                    manifest_size = manifest.info.st_size
                _require(manifest_sha256 == expected_snapshot_manifest_sha256)
                async with asyncio.timeout(window.remaining()):
                    snapshot = await verify_stock_snapshot(destination / "snapshot", now=now)
                window.check()
                _require(snapshot.manifest_sha256 == expected_snapshot_manifest_sha256)
                _require(bundle.file_count == snapshot.file_count + 1)
                _require(bundle.total_bytes == snapshot.total_bytes + manifest_size)
                controls = restore_snapshot_controls(
                    destination / "snapshot",
                    destination=destination / "killed-controls",
                    now=now,
                )
                window.check()
                _require(controls.offline_only is True)
                killed_proof = _killed_proof(destination, controls, now, window)
                _require(
                    _stamp(os.stat(_TEMPORARY, dir_fd=root, follow_symlinks=False)) == original
                )
                _require(set(os.listdir(root)) == {_TEMPORARY, "snapshot", "killed-controls"})
                with _input(manifest_path, minimum=1, maximum=32 * 1024 * 1024) as manifest:
                    _require(_hash(manifest, window) == expected_snapshot_manifest_sha256)
                async with asyncio.timeout(window.remaining()):
                    _require(
                        await verify_stock_snapshot(destination / "snapshot", now=now) == snapshot
                    )
                _require(_killed_proof(destination, controls, now, window) == killed_proof)
                os.unlink(_TEMPORARY, dir_fd=root)
                namespace.sync()
                # Repacking into a bounded discard sink proves that every final
                # byte still matches the authenticated bundle after cleanup IO.
                final_bundle = pack_snapshot(
                    destination / "snapshot",
                    cast(
                        BinaryIO,
                        _TimedStream(
                            cast(BinaryIO, _Discard()), window, maximum_write=bundle.stream_bytes
                        ),
                    ),
                    maximum_bytes=bundle.stream_bytes,
                    maximum_files=bundle.file_count,
                )
                _require(final_bundle == bundle)
                _require(_killed_proof(destination, controls, now, window) == killed_proof)
                _require(set(os.listdir(root)) == {"snapshot", "killed-controls"})
                source.check()
                secret.check()
                namespace.check()
                window.check()
                receipt = StockBackupRestoreReceipt(
                    actual_ciphertext,
                    snapshot.manifest_sha256,
                    bundle.bundle_sha256,
                    bundle.file_count,
                    bundle.total_bytes,
                    snapshot.claim_count,
                    snapshot.result_count,
                    snapshot.pending_count,
                    snapshot.state_sha256,
                    controls.control_id,
                    controls.generation,
                    True,
                )
        window.check()
        return receipt
    except Exception:
        _deny()


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        _deny()


def main(argv: list[str] | None = None) -> int:
    try:
        parser = _Parser(description=__doc__)
        parser.add_argument("--ciphertext", type=Path, required=True)
        parser.add_argument("--private-key-file", type=Path, required=True)
        parser.add_argument("--destination", type=Path, required=True)
        parser.add_argument("--expected-ciphertext-sha256", required=True)
        parser.add_argument("--expected-snapshot-manifest-sha256", required=True)
        args = parser.parse_args(argv)
        receipt = asyncio.run(
            restore_encrypted_stock_backup(
                args.ciphertext,
                args.private_key_file,
                destination=args.destination,
                expected_ciphertext_sha256=args.expected_ciphertext_sha256,
                expected_snapshot_manifest_sha256=args.expected_snapshot_manifest_sha256,
                now=datetime.now(UTC),
            )
        )
        print(
            json.dumps(
                {"status": "offline_restore_verified", **asdict(receipt), "live_enabled": False},
                sort_keys=True,
            )
        )
        return 0
    except Exception:
        print(
            '{"status":"failed","reason":"stock_backup_restore_unavailable",'
            '"offline_only":true,"live_enabled":false}'
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
