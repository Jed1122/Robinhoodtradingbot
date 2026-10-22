"""Exclusive bounded ciphertext publication; never deletes retained backups.

The caller owns the operations lock and has reaped its snapshot helper. A success
receipt is recorded separately only after this function returns. A published file
whose final durability is uncertain remains forensic evidence, never success.
An independent durable pending fence blocks subsequent admission after failure;
only explicit owner recovery can reconcile retained markers and ciphertexts.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from trading_bot.runtime.stock_backup_crypto import StockBackupCryptoReceipt, encrypt_stream

_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_NAME = re.compile(r"[0-9a-f]{64}\.stockbackup\Z")
_MAXIMUM = 2 * 1024**3


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


def _file(info: os.stat_result, owner: int, maximum: int) -> None:
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != owner
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) != 0o600
        or not 0 < info.st_size <= maximum
    ):
        raise ValueError


def _check_directory(path: Path, descriptor: int, owner: int) -> None:
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError
    info, named = os.fstat(descriptor), path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != owner
        or stat.S_IMODE(info.st_mode) != 0o700
        or (info.st_dev, info.st_ino, info.st_uid, info.st_mode)
        != (named.st_dev, named.st_ino, named.st_uid, named.st_mode)
    ):
        raise ValueError


@contextmanager
def _directory(path: Path, owner: int) -> Iterator[int]:
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        _check_directory(path, descriptor, owner)
        yield descriptor
        _check_directory(path, descriptor, owner)
    finally:
        os.close(descriptor)


def _inventory(directory: int, fence: tuple[str, tuple[int, ...]] | None = None) -> int:
    count = 0
    with os.scandir(directory) as entries:
        for entry in entries:
            if fence is not None and entry.name == fence[0]:
                if _stamp(entry.stat(follow_symlinks=False)) != fence[1]:
                    raise ValueError
                continue
            if _NAME.fullmatch(entry.name) is None:
                raise ValueError
            _file(entry.stat(follow_symlinks=False), os.geteuid(), _MAXIMUM + 131072)
            count += 1
            if count > 16:
                raise ValueError
    return count


def _create_fence(directory: int, name: str) -> tuple[int, ...]:
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=directory,
    )
    try:
        os.fchmod(descriptor, 0o600)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or info.st_size != 0
        ):
            raise ValueError
        os.fsync(descriptor)
        return _stamp(info)
    finally:
        os.close(descriptor)


def _retain_fence(directory: int, name: str) -> None:
    # Recovery never replaces a marker or deletes ciphertext. Even if fsync is
    # failing, leave any newly created blocker visible to the next inventory.
    with suppress(OSError, ValueError):
        _create_fence(directory, name)
    with suppress(OSError):
        os.fsync(directory)


def _check_source(original: os.stat_result, descriptor: int, parent: int, name: str) -> None:
    if _stamp(original) != _stamp(os.fstat(descriptor)) or _stamp(original) != _stamp(
        os.stat(name, dir_fd=parent, follow_symlinks=False)
    ):
        raise ValueError


def _verify_cipher(directory: int, name: str, receipt: StockBackupCryptoReceipt) -> None:
    descriptor = os.open(name, _READ, dir_fd=directory)
    try:
        info = os.fstat(descriptor)
        _file(info, os.geteuid(), _MAXIMUM + 131072)
        if info.st_size != receipt.ciphertext_bytes:
            raise ValueError
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        if (
            digest.hexdigest() != receipt.ciphertext_sha256
            or _stamp(info) != _stamp(os.fstat(descriptor))
            or _stamp(info) != _stamp(os.stat(name, dir_fd=directory, follow_symlinks=False))
        ):
            raise ValueError
    finally:
        os.close(descriptor)


def encrypt_snapshot_bundle(
    *,
    source: Path,
    source_uid: int,
    destination_root: Path,
    recipient_public_key: bytes,
    expected_plaintext_sha256: str,
    maximum_bytes: int = _MAXIMUM,
) -> tuple[Path, StockBackupCryptoReceipt]:
    """Encrypt/read back/fsync/link once. Partial output never becomes a receipt.

    At most16 generations are retained. Capacity exhaustion requires explicit
    audited retention work; no unacknowledged or sole good copy is auto-pruned.
    No secret/private recipient key is accepted or stored here.
    """
    recovery = -1
    fence: str | None = None
    try:
        if (
            type(source_uid) is not int
            or source_uid < 0
            or type(maximum_bytes) is not int
            or not 1 <= maximum_bytes <= _MAXIMUM
            or type(expected_plaintext_sha256) is not str
            or _HEX.fullmatch(expected_plaintext_sha256) is None
        ):
            raise ValueError
        with (
            _directory(source.parent, source_uid) as parent,
            _directory(destination_root, os.geteuid()) as destination,
        ):
            if _inventory(destination) >= 16:
                raise ValueError
            descriptor = os.open(source.name, _READ, dir_fd=parent)
            try:
                original = os.fstat(descriptor)
                _file(original, source_uid, maximum_bytes)
                space = os.fstatvfs(destination)
                if (
                    space.f_bavail * space.f_frsize < original.st_size + 101 * 1024**2
                    or space.f_favail < 128
                ):
                    raise ValueError
                recovery = os.dup(destination)
                fence = ".pending-" + uuid.uuid4().hex
                fence_stamp = _create_fence(destination, fence)
                os.fsync(destination)
                temporary = fence + ".cipher"
                output = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=destination,
                )
                with (
                    os.fdopen(output, "wb") as target,
                    os.fdopen(descriptor, "rb", closefd=False) as plaintext,
                ):
                    receipt = encrypt_stream(
                        plaintext, target, recipient_public_key, max_bytes=maximum_bytes
                    )
                    target.flush()
                    os.fsync(target.fileno())
                if (
                    type(receipt) is not StockBackupCryptoReceipt
                    or receipt.plaintext_sha256 != expected_plaintext_sha256
                    or receipt.plaintext_bytes != original.st_size
                ):
                    raise ValueError
                _check_source(original, descriptor, parent, source.name)
                _verify_cipher(destination, temporary, receipt)
                name = receipt.ciphertext_sha256 + ".stockbackup"
                os.link(
                    temporary,
                    name,
                    src_dir_fd=destination,
                    dst_dir_fd=destination,
                    follow_symlinks=False,
                )
                os.unlink(temporary, dir_fd=destination)
                os.fsync(destination)
                _verify_cipher(destination, name, receipt)
                _check_source(original, descriptor, parent, source.name)
                _check_directory(source.parent, parent, source_uid)
                _check_directory(destination_root, destination, os.geteuid())
                _inventory(destination, (fence, fence_stamp))
                os.unlink(fence, dir_fd=destination)
                os.fsync(destination)
                _check_source(original, descriptor, parent, source.name)
                _check_directory(source.parent, parent, source_uid)
                _check_directory(destination_root, destination, os.geteuid())
                _inventory(destination)
            finally:
                os.close(descriptor)
        return destination_root / name, receipt
    except Exception:
        if recovery >= 0 and fence is not None:
            _retain_fence(recovery, fence)
        raise ValueError("stock_backup_publication_unavailable") from None
    finally:
        if recovery >= 0:
            with suppress(OSError):
                os.close(recovery)
