"""Dedicated private probe persistence foundation; no worker or Engine authority.

The namespace opener deliberately admits only an empty initialized layout until
probe lineage/lifecycle validation is implemented. Readable bytes are not a durable
acknowledgement, a transport observation or permission to dispatch.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import secrets
import stat
import sys
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from infra.hybrid.stock_attempts import _read, _write_new
from infra.hybrid.stock_release import _close_all, _fingerprint, _open_directory

PROBES_ROOT = Path("/var/lib/hybrid-stock-probes")
_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_WRITE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_ERRORS = (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError, AttributeError)
_SLOTS = {
    "engine.bin": 1048576,
    "image.bin": 1048576,
    "request.bin": 1048576,
    "create-response.bin": 4096,
    "prestart.bin": 1048576,
    "stopped.bin": 1048576,
    "framed-logs.bin": 16384,
    "configuration.bin": 4096,
}
_NAMESPACE_KEYS = {
    "schema_version",
    "kind",
    "namespace_id",
    "root_device",
    "root_inode",
    "lock_device",
    "lock_inode",
}


def _deny() -> NoReturn:
    raise ValueError("stock_probe_store_unavailable") from None


def _require(condition: bool) -> None:
    if not condition:
        _deny()


@contextmanager
def _sanitized() -> Iterator[None]:
    try:
        yield
    except _ERRORS:
        _deny()


def _directory_info(info: os.stat_result, uid: int) -> None:
    _require(
        stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == uid
    )


def _file_info(info: os.stat_result, uid: int, *, low: int, high: int) -> None:
    _require(
        stat.S_ISREG(info.st_mode)
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_uid == uid
        and info.st_nlink == 1
        and low <= info.st_size <= high
    )


def _slot(name: str) -> tuple[int, int]:
    _require(type(name) is str and name in _SLOTS)
    return (0 if name == "framed-logs.bin" else 1), _SLOTS[name]


def _read_bytes(directory: int, name: str, uid: int) -> bytes:
    with _sanitized():
        low, high = _slot(name)
        descriptor = os.open(name, _READ, dir_fd=directory)
        try:
            before = os.fstat(descriptor)
            _file_info(before, uid, low=low, high=high)
            raw = b""
            while len(raw) <= high:
                chunk = os.read(descriptor, min(8192, high + 1 - len(raw)))
                if not chunk:
                    break
                raw += chunk
            _require(len(raw) == before.st_size and low <= len(raw) <= high)
            stamp = _fingerprint(before)
            _require(stamp == _fingerprint(os.fstat(descriptor)))
            _require(stamp == _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False)))
        finally:
            _close_all((descriptor,))
        return raw


def _write_bytes(directory: int, name: str, raw: bytes, uid: int) -> str:
    with _sanitized():
        low, high = _slot(name)
        _require(type(raw) is bytes and low <= len(raw) <= high)
        descriptor = os.open(name, _WRITE, 0o600, dir_fd=directory)
        try:
            offset = 0
            while offset < len(raw):
                written = os.write(descriptor, raw[offset:])
                _require(type(written) is int and 0 < written <= len(raw) - offset)
                offset += written
            info = os.fstat(descriptor)
            _file_info(info, uid, low=low, high=high)
            _require(info.st_size == len(raw))
            os.fsync(descriptor)
            _require(_fingerprint(info) == _fingerprint(os.fstat(descriptor)))
            _require(
                _fingerprint(info)
                == _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False))
            )
        finally:
            _close_all((descriptor,))
        os.fsync(directory)
        _require(_read_bytes(directory, name, uid) == raw)
        return hashlib.sha256(raw).hexdigest()


class _ContentCache:
    """Same-lock byte reuse only; no parsed records, durability or authority."""

    def __init__(self) -> None:
        self._entries: dict[tuple[int, int, str], tuple[tuple[int, ...], bytes]] = {}

    def read(self, directory: int, name: str, uid: int) -> bytes:
        with _sanitized():
            low, high = _slot(name)
            parent = os.fstat(directory)
            before = os.stat(name, dir_fd=directory, follow_symlinks=False)
            _file_info(before, uid, low=low, high=high)
            stamp = _fingerprint(before)
            key = (parent.st_dev, parent.st_ino, name)
            cached = self._entries.get(key)
            if cached is None or cached[0] != stamp:
                raw = _read_bytes(directory, name, uid)
            else:
                raw = cached[1]
            _require(stamp == _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False)))
            self._entries[key] = (stamp, raw)
            return raw


def _validate_namespace(value: dict[str, Any], root: os.stat_result, lock: os.stat_result) -> None:
    _require(set(value) == _NAMESPACE_KEYS)
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1)
    _require(value["kind"] == "stock_probe_namespace")
    _require(
        type(value["namespace_id"]) is str
        and re.fullmatch(r"[0-9a-f]{32}", value["namespace_id"]) is not None
    )
    for key, expected in {
        "root_device": root.st_dev,
        "root_inode": root.st_ino,
        "lock_device": lock.st_dev,
        "lock_inode": lock.st_ino,
    }.items():
        _require(type(value[key]) is int and value[key] >= 0 and value[key] == expected)


def _path(root: Path, uid: int) -> None:
    _require(type(uid) is int and uid >= 0 and os.geteuid() == uid)
    _require(
        isinstance(root, Path) and root.is_absolute() and ".." not in root.parts and root.name != ""
    )


def _initialize(root: Path, *, trusted_uid: int) -> None:
    """Private fixture seam. Never repair or reuse a partially initialized root."""
    with _sanitized():
        _path(root, trusted_uid)
        parent = _open_directory(
            root.parent,
            trusted_uid=trusted_uid,
            release_root=Path("/") if root == PROBES_ROOT else root.parent,
        )
        directory: int | None = None
        lock: int | None = None
        try:
            os.mkdir(root.name, 0o700, dir_fd=parent)
            directory = os.open(root.name, _DIRECTORY, dir_fd=parent)
            info = os.fstat(directory)
            _directory_info(info, trusted_uid)
            lock = os.open("launcher.lock", _WRITE, 0o600, dir_fd=directory)
            lock_info = os.fstat(lock)
            _file_info(lock_info, trusted_uid, low=0, high=0)
            os.fsync(lock)
            _write_new(
                directory,
                "namespace.json",
                {
                    "schema_version": 1,
                    "kind": "stock_probe_namespace",
                    "namespace_id": secrets.token_hex(16),
                    "root_device": info.st_dev,
                    "root_inode": info.st_ino,
                    "lock_device": lock_info.st_dev,
                    "lock_inode": lock_info.st_ino,
                },
                trusted_uid,
            )
            os.fsync(directory)
            os.fsync(parent)
        finally:
            _close_all(fd for fd in (lock, directory, parent) if fd is not None)


@dataclass(frozen=True, slots=True)
class _ProbeNamespace:
    namespace_id: str


@contextmanager
def _open_namespace(root: Path, *, trusted_uid: int) -> Iterator[_ProbeNamespace]:
    """Locked empty-layout foundation; unfinished lineage is not yet admitted."""
    with _sanitized():
        _path(root, trusted_uid)
        directory = _open_directory(
            root,
            trusted_uid=trusted_uid,
            release_root=Path("/") if root == PROBES_ROOT else root,
        )
        lock: int | None = None
        try:
            _directory_info(os.fstat(directory), trusted_uid)
            lock = os.open(
                "launcher.lock",
                os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=directory,
            )
            _file_info(os.fstat(lock), trusted_uid, low=0, high=0)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _require(set(os.listdir(directory)) == {"namespace.json", "launcher.lock"})
            value, _ = _read(directory, "namespace.json", trusted_uid)
            _validate_namespace(value, os.fstat(directory), os.fstat(lock))
            _require(
                _fingerprint(os.fstat(lock))
                == _fingerprint(os.stat("launcher.lock", dir_fd=directory, follow_symlinks=False))
            )
            yield _ProbeNamespace(value["namespace_id"])
        finally:
            _close_all(fd for fd in (lock, directory) if fd is not None)


def initialize_probes() -> None:
    """Explicit fixed-root initialization; never invoked by an operator probe run."""
    with _sanitized():
        _require(sys.platform == "linux" and os.geteuid() == 0)
        _initialize(PROBES_ROOT, trusted_uid=0)


def probes() -> AbstractContextManager[_ProbeNamespace]:
    """Fixed production path/UID; no caller-selected alternate namespace."""
    with _sanitized():
        _require(sys.platform == "linux" and os.geteuid() == 0)
        return _open_namespace(PROBES_ROOT, trusted_uid=0)
