"""Bounded private immutable operational receipt consistency, not operation proof.

The caller independently verifies the actual encrypted artifact, off-host copy or
application restore before recording success. This module never reads ciphertext,
decrypts, copies data, contacts a provider, initializes state or changes controls.
The root directory and permanent empty private lock must already exist.

Publication is exclusive and atomic. Failed/interrupted publication can leave an
unknown pending file; it is retained as an incident and blocks the store rather
than being repaired. There is no mutable latest pointer or automatic retention.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn, cast

_LOCK = ".stock-receipts.lock"
_PENDING = ".stock-receipts.pending"
_KINDS = {"backup", "offhost", "restore"}
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_NAME = re.compile(r"(backup|offhost|restore)-([0-9a-f]{64})\.json\Z")
_BOUND = {
    "ciphertext_sha256",
    "ciphertext_bytes",
    "snapshot_manifest_sha256",
    "config_hash",
    "code_hash",
    "release_id",
    "image_digest",
}
_FIELDS = _BOUND | {"schema_version", "kind", "at"}
_MAX_RECEIPTS = 128
_MAX_BYTES = 4096
_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
type Receipt = dict[str, str | int]
type Fingerprint = tuple[int, ...]


class StockOperationReceiptError(ValueError):
    """Fixed failure without caller paths, artifact metadata or operating-system text."""


def _deny() -> NoReturn:
    raise StockOperationReceiptError("stock_operation_receipts_unavailable") from None


def _require(condition: bool) -> None:
    if not condition:
        _deny()


@contextmanager
def _guard() -> Iterator[None]:
    try:
        yield
    except Exception:
        _deny()


def _clock() -> datetime:
    return datetime.now(UTC)


def _time(value: object) -> str:
    _require(type(value) is datetime)
    value = cast(datetime, value)
    _require(value.tzinfo is not None and value.utcoffset() == timedelta(0))
    return value.isoformat()


def _timestamp(value: object) -> datetime:
    _require(type(value) is str and len(value) <= 40)
    parsed = datetime.fromisoformat(cast(str, value))
    _require(_time(parsed) == value)
    return parsed


def _canonical(value: Receipt) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        _require(key not in result)
        result[key] = value
    return result


def _constant(_value: str) -> NoReturn:
    _deny()


def _receipt(value: object) -> Receipt:
    _require(type(value) is dict)
    record = cast(dict[str, Any], value)
    _require(set(record) == _FIELDS)
    _require(type(record["schema_version"]) is int and record["schema_version"] == 1)
    _require(type(record["kind"]) is str and record["kind"] in _KINDS)
    _timestamp(record["at"])
    for name in _BOUND - {"ciphertext_bytes", "image_digest"}:
        _require(type(record[name]) is str and _HEX.fullmatch(record[name]) is not None)
    _require(
        type(record["image_digest"]) is str and _IMAGE.fullmatch(record["image_digest"]) is not None
    )
    _require(type(record["ciphertext_bytes"]) is int and 1 <= record["ciphertext_bytes"] < 2**63)
    return cast(Receipt, record)


def _fingerprint(value: os.stat_result) -> Fingerprint:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _file(value: os.stat_result, uid: int, *, empty: bool = False) -> None:
    _require(
        stat.S_ISREG(value.st_mode)
        and stat.S_IMODE(value.st_mode) == 0o600
        and value.st_uid == uid
        and value.st_nlink == 1
        and (value.st_size == 0 if empty else 0 < value.st_size <= _MAX_BYTES)
    )


def _directory(value: os.stat_result, uid: int) -> None:
    _require(
        stat.S_ISDIR(value.st_mode) and stat.S_IMODE(value.st_mode) == 0o700 and value.st_uid == uid
    )


def _close_all(descriptors: tuple[int, ...]) -> None:
    failed = False
    for descriptor in descriptors:
        try:
            os.close(descriptor)
        except OSError:
            # An uncertain close may already have released/reused this number.
            failed = True
    if failed:
        _deny()


def _open_root(path: Path, uid: int) -> int:
    descriptor = os.open("/", _DIRECTORY)
    try:
        for component in path.parts[1:]:
            child = os.open(component, _DIRECTORY, dir_fd=descriptor)
            previous, descriptor = descriptor, child
            os.close(previous)
        _directory(os.fstat(descriptor), uid)
        return descriptor
    except BaseException:
        _close_all((descriptor,))
        raise


def _read_record(directory: int, name: str, uid: int) -> tuple[Receipt, bytes, Fingerprint]:
    match = _NAME.fullmatch(name)
    if match is None:
        _deny()
    descriptor = os.open(name, _READ, dir_fd=directory)
    try:
        before = os.fstat(descriptor)
        _file(before, uid)
        body = bytearray()
        while len(body) <= _MAX_BYTES:
            part = os.read(descriptor, _MAX_BYTES + 1 - len(body))
            if not part:
                break
            body.extend(part)
        _require(len(body) == before.st_size)
        stamp = _fingerprint(before)
        _require(stamp == _fingerprint(os.fstat(descriptor)))
        _require(stamp == _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False)))
        raw = bytes(body)
        value = _receipt(json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant))
        _require(_canonical(value) == raw)
        _require(value["kind"] == match[1] and value["ciphertext_sha256"] == match[2])
        return value, raw, stamp
    finally:
        _close_all((descriptor,))


def _names(directory: int) -> set[str]:
    names = set()
    found_lock = False
    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.name == _LOCK:
                _require(not found_lock)
                found_lock = True
            else:
                _require(_NAME.fullmatch(entry.name) is not None)
                names.add(entry.name)
                _require(len(names) <= _MAX_RECEIPTS)
    _require(found_lock)
    return names


def _bound_to_predecessors(value: Receipt, records: dict[str, Receipt]) -> None:
    predecessors = (
        ("backup", "offhost")
        if value["kind"] == "restore"
        else ("backup",)
        if value["kind"] == "offhost"
        else ()
    )
    for kind in predecessors:
        predecessor = records.get(f"{kind}-{value['ciphertext_sha256']}.json")
        if predecessor is None:
            _deny()
        _require(all(value[field] == predecessor[field] for field in _BOUND))
        _require(_timestamp(value["at"]) >= _timestamp(predecessor["at"]))


def _load(directory: int, uid: int, now: datetime) -> dict[str, Receipt]:
    names = _names(directory)
    records: dict[str, Receipt] = {}
    stamps: dict[str, Fingerprint] = {}
    for name in sorted(names):
        value, _, stamp = _read_record(directory, name, uid)
        _require(_timestamp(value["at"]) <= now)
        records[name], stamps[name] = value, stamp
    for value in records.values():
        _bound_to_predecessors(value, records)
    _require(_names(directory) == names)
    for name, stamp in stamps.items():
        _require(stamp == _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False)))
    return records


def _publish(directory: int, name: str, body: bytes, uid: int) -> None:
    descriptor = os.open(
        _PENDING,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=directory,
    )
    try:
        _file(os.fstat(descriptor), uid, empty=True)
        offset = 0
        view = memoryview(body)
        while offset < len(body):
            written = os.write(descriptor, view[offset:])
            _require(type(written) is int and 0 < written <= len(body) - offset)
            offset += written
        os.fsync(descriptor)
        _file(os.fstat(descriptor), uid)
        _require(
            _fingerprint(os.fstat(descriptor))
            == _fingerprint(os.stat(_PENDING, dir_fd=directory, follow_symlinks=False))
        )
        # link is the portable atomic no-overwrite publication primitive. Both
        # names transiently link one inode under the permanent exclusive lock.
        # Any interrupted state is retained and denied; it is never auto-repaired.
        os.link(_PENDING, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        # Retain the pending fence until the final link has a durability
        # acknowledgement. A failed publication must not look like an ordinary
        # committed receipt merely because its final name is currently readable.
        os.fsync(directory)
        os.unlink(_PENDING, dir_fd=directory)
        _file(os.fstat(descriptor), uid)
        os.fsync(directory)
        _, readback, stamp = _read_record(directory, name, uid)
        _require(readback == body and stamp == _fingerprint(os.fstat(descriptor)))
    finally:
        _close_all((descriptor,))


def _reconfirm(directory: int, name: str, expected: Receipt, uid: int) -> None:
    descriptor = os.open(name, _READ, dir_fd=directory)
    try:
        _file(os.fstat(descriptor), uid)
        os.fsync(descriptor)
        os.fsync(directory)
        value, _, stamp = _read_record(directory, name, uid)
        _require(value == expected and stamp == _fingerprint(os.fstat(descriptor)))
    finally:
        _close_all((descriptor,))


class StockOperationReceipts:
    """Owner-local immutable metadata; caller proof and retention remain external.

    Reads reject times before any retained receipt or this instance's previous
    observation. Across instances, only retained immutable timestamps provide a
    clock floor: there is intentionally no mutable clock/latest pointer.
    """

    def __init__(self, root: Path) -> None:
        _require(type(root) is type(Path()) and root.is_absolute() and ".." not in root.parts)
        self._root, self._uid = root, os.geteuid()
        self._last_now: datetime | None = None

    def _observe(self, now: datetime) -> None:
        _time(now)
        _require(self._last_now is None or now >= self._last_now)
        self._last_now = now

    def _current(self, directory: int, lock: int) -> None:
        _require(os.geteuid() == self._uid)
        _directory(os.fstat(directory), self._uid)
        current = _open_root(self._root, self._uid)
        try:
            _require(
                (os.fstat(current).st_dev, os.fstat(current).st_ino)
                == (os.fstat(directory).st_dev, os.fstat(directory).st_ino)
            )
        finally:
            _close_all((current,))
        held, named = os.fstat(lock), os.stat(_LOCK, dir_fd=directory, follow_symlinks=False)
        _file(held, self._uid, empty=True)
        _file(named, self._uid, empty=True)
        _require((held.st_dev, held.st_ino) == (named.st_dev, named.st_ino))

    @contextmanager
    def _locked(self) -> Iterator[int]:
        _require(os.geteuid() == self._uid)
        directory = _open_root(self._root, self._uid)
        lock = -1
        try:
            lock = os.open(
                _LOCK, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory
            )
            _file(os.fstat(lock), self._uid, empty=True)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._current(directory, lock)
            yield directory
            self._current(directory, lock)
        finally:
            _close_all((lock, directory) if lock >= 0 else (directory,))

    def record(
        self,
        *,
        kind: str,
        at: datetime,
        ciphertext_sha256: str,
        ciphertext_bytes: int,
        snapshot_manifest_sha256: str,
        config_hash: str,
        code_hash: str,
        release_id: str,
        image_digest: str,
    ) -> Receipt:
        """Record caller-verified success, never a proof that an operation ran."""
        with _guard():
            value = _receipt(
                {
                    "schema_version": 1,
                    "kind": kind,
                    "at": _time(at),
                    "ciphertext_sha256": ciphertext_sha256,
                    "ciphertext_bytes": ciphertext_bytes,
                    "snapshot_manifest_sha256": snapshot_manifest_sha256,
                    "config_hash": config_hash,
                    "code_hash": code_hash,
                    "release_id": release_id,
                    "image_digest": image_digest,
                }
            )
            body = _canonical(value)
            _require(len(body) <= _MAX_BYTES)
            now = _clock()
            self._observe(now)
            _require(at <= now)
            with self._locked() as directory:
                records = _load(directory, self._uid, now)
                name = f"{kind}-{ciphertext_sha256}.json"
                if name in records:
                    _require(records[name] == value)
                    _reconfirm(directory, name, value, self._uid)
                    return dict(value)
                _require(len(records) < _MAX_RECEIPTS)
                _require(all(at >= _timestamp(previous["at"]) for previous in records.values()))
                # Validate the complete dependency chain before any new file.
                _bound_to_predecessors(value, records)
                _publish(directory, name, body, self._uid)
                _require(_load(directory, self._uid, now)[name] == value)
                return dict(value)
        _deny()

    def all(self, *, now: datetime) -> tuple[Receipt, ...]:
        """Read the complete checked history; no freshness or operation attestation."""
        with _guard():
            self._observe(now)
            with self._locked() as directory:
                records = _load(directory, self._uid, now)
                ordered = sorted(
                    records.values(),
                    key=lambda value: (
                        _timestamp(value["at"]),
                        str(value["kind"]),
                        str(value["ciphertext_sha256"]),
                    ),
                )
                return tuple(dict(value) for value in ordered)
        _deny()

    def latest(self, kind: str, *, now: datetime) -> Receipt | None:
        """Return a kind's latest receipt only after all retained records validate."""
        _require(type(kind) is str and kind in _KINDS)
        return next((value for value in reversed(self.all(now=now)) if value["kind"] == kind), None)
