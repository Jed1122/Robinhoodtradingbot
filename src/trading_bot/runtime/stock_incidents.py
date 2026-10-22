"""Private local incident history; no network, remediation or financial authority.

Updates describe complete observations. An unavailable observation (None), invalid
tuple, or observation_invalid marker preserves unresolved incidents. Only a valid
complete observation can resolve absent codes. Initialization is always explicit;
missing, malformed or unsafe existing state is never reset or repaired.
"""

from __future__ import annotations

import fcntl
import json
import os
import stat
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn

from trading_bot.clock import require_utc
from trading_bot.runtime.stock_health import STOCK_HEALTH_INCIDENTS

_NAME = "stock-incidents.json"
_LOCK = ".stock-incidents.lock"
_MAX_BYTES = 65536
_MAX_HISTORY = 128
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


class StockIncidentSpoolError(ValueError):
    """Fixed error containing no path, incident payload or provider text."""


def _deny() -> NoReturn:
    raise StockIncidentSpoolError("stock_incident_spool_unavailable") from None


def _require(value: bool) -> None:
    if not value:
        _deny()


def _canonical(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _constant(_value: str) -> None:
    _deny()


def _time(value: object) -> datetime:
    _require(type(value) is str)
    if not isinstance(value, str):
        _deny()
    _require(len(value) <= 40)
    checked = require_utc(datetime.fromisoformat(value))
    _require(checked.isoformat() == value)
    return checked


def _now(value: datetime) -> datetime:
    try:
        return require_utc(value)
    except (ValueError, TypeError, OverflowError):
        _deny()


def _close(descriptors: tuple[int, ...]) -> None:
    failed = False
    for descriptor in descriptors:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                failed = True
    if failed:
        _deny()


def _private(info: os.stat_result) -> bool:
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_nlink == 1
    )


def _identity(info: os.stat_result) -> tuple[int, ...]:
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


def _validate(value: Any) -> dict[str, Any]:
    _require(type(value) is dict)
    _require(set(value) == {"schema_version", "kind", "last_observed_at", "incidents"})
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1)
    _require(value["kind"] == "stock_operations_incidents")
    observed_at = _time(value["last_observed_at"])
    rows = value["incidents"]
    _require(type(rows) is list and len(rows) <= _MAX_HISTORY)
    previous: datetime | None = None
    ends: dict[str, datetime | None] = {}
    unique: set[tuple[str, datetime, datetime, datetime | None]] = set()
    for row in rows:
        _require(
            type(row) is dict and set(row) == {"code", "first_seen", "last_seen", "resolved_at"}
        )
        code = row["code"]
        _require(type(code) is str and code in STOCK_HEALTH_INCIDENTS)
        first, last = _time(row["first_seen"]), _time(row["last_seen"])
        resolved = None if row["resolved_at"] is None else _time(row["resolved_at"])
        _require(first <= last <= observed_at)
        _require(resolved is None or last <= resolved <= observed_at)
        _require(previous is None or previous <= first)
        if code in ends:
            end = ends[code]
            _require(end is not None and end <= first)
        episode = code, first, last, resolved
        _require(episode not in unique)
        unique.add(episode)
        previous, ends[code] = first, resolved
    return dict(value)


class StockIncidentSpool:
    """One private mode0700 namespace and stable exclusive local flock anchor."""

    def __init__(self, root: Path) -> None:
        self._root = root

    @staticmethod
    def _inventory(directory: int) -> set[str]:
        names: set[str] = set()
        with os.scandir(directory) as entries:
            for entry in entries:
                _require(entry.name in {_NAME, _LOCK} and len(names) < 2)
                names.add(entry.name)
        return names

    def _check_namespace(self, directory: int, lock: int) -> None:
        current, named = os.fstat(directory), self._root.lstat()
        _require(
            stat.S_ISDIR(current.st_mode)
            and current.st_uid == os.geteuid()
            and stat.S_IMODE(current.st_mode) == 0o700
            and (current.st_dev, current.st_ino) == (named.st_dev, named.st_ino)
        )
        anchor = os.fstat(lock)
        _require(_private(anchor) and anchor.st_size == 0)
        _require(
            _identity(anchor) == _identity(os.stat(_LOCK, dir_fd=directory, follow_symlinks=False))
        )

    @contextmanager
    def _locked(self, *, initializing: bool = False) -> Iterator[tuple[int, int]]:
        directory = lock = -1
        try:
            _require(self._root.is_absolute() and self._root.resolve(strict=True) == self._root)
            directory = os.open(
                self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            )
            info = os.fstat(directory)
            _require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700)
            names = self._inventory(directory)
            _require(_NAME not in names if initializing else names == {_NAME, _LOCK})
            flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
            if initializing and _LOCK not in names:
                flags |= os.O_CREAT | os.O_EXCL
            lock = os.open(_LOCK, flags, 0o600, dir_fd=directory)
            anchor = os.fstat(lock)
            _require(_private(anchor) and anchor.st_size == 0)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._check_namespace(directory, lock)
            names = self._inventory(directory)
            _require(_NAME not in names if initializing else names == {_NAME, _LOCK})
            yield directory, lock
            self._check_namespace(directory, lock)
        except (OSError, ValueError, TypeError, AttributeError, OverflowError, RecursionError):
            _deny()
        finally:
            _close((lock, directory))

    @staticmethod
    def _read(directory: int) -> dict[str, Any]:
        descriptor = os.open(_NAME, _READ, dir_fd=directory)
        try:
            before = os.fstat(descriptor)
            _require(_private(before) and 0 < before.st_size <= _MAX_BYTES)
            body = bytearray()
            while len(body) < before.st_size:
                chunk = os.read(descriptor, before.st_size - len(body))
                _require(bool(chunk))
                body.extend(chunk)
            _require(not os.read(descriptor, 1))
            _require(_identity(before) == _identity(os.fstat(descriptor)))
            _require(
                _identity(before)
                == _identity(os.stat(_NAME, dir_fd=directory, follow_symlinks=False))
            )
            value = json.loads(body, object_pairs_hook=_pairs, parse_constant=_constant)
            checked = _validate(value)
            _require(_canonical(checked) == body)
            return checked
        finally:
            os.close(descriptor)

    def _write(
        self, directory: int, lock: int, record: dict[str, Any], *, exclusive: bool = False
    ) -> dict[str, Any]:
        body = _canonical(_validate(record))
        _require(0 < len(body) <= _MAX_BYTES)
        self._check_namespace(directory, lock)
        self._inventory(directory)
        temporary = ".stock-incidents.pending-" + uuid.uuid4().hex
        descriptor = -1
        created = False
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=directory,
            )
            created = True
            os.fchmod(descriptor, 0o600)
            remaining = memoryview(body)
            while remaining:
                count = os.write(descriptor, remaining)
                _require(count > 0)
                remaining = remaining[count:]
            os.fsync(descriptor)
            owned = descriptor
            descriptor = -1
            os.close(owned)
            self._check_namespace(directory, lock)
            if exclusive:
                os.link(
                    temporary,
                    _NAME,
                    src_dir_fd=directory,
                    dst_dir_fd=directory,
                    follow_symlinks=False,
                )
                os.unlink(temporary, dir_fd=directory)
            else:
                os.replace(temporary, _NAME, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
            retained = self._read(directory)
            _require(_canonical(retained) == body)
            return retained
        finally:
            failed = False
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    failed = True
            if created:
                try:
                    with suppress(FileNotFoundError):
                        os.unlink(temporary, dir_fd=directory)
                except OSError:
                    failed = True
            if failed:
                _deny()

    def initialize(self, *, now: datetime) -> dict[str, Any]:
        """Create an absent history only on this explicit call; never clobber state."""
        now = _now(now)
        with self._locked(initializing=True) as (directory, lock):
            return self._write(
                directory,
                lock,
                {
                    "schema_version": 1,
                    "kind": "stock_operations_incidents",
                    "last_observed_at": now.isoformat(),
                    "incidents": [],
                },
                exclusive=True,
            )

    def read(self) -> dict[str, Any]:
        """Read bounded validated history; missing state is unavailable."""
        with self._locked() as (directory, _lock):
            return self._read(directory)

    def update(self, observed: tuple[str, ...] | None, *, now: datetime) -> dict[str, Any]:
        """Deduplicate active codes and retain at most128 chronological episodes."""
        now = _now(now)
        complete = (
            type(observed) is tuple
            and len(observed) <= _MAX_HISTORY
            and all(type(code) is str and code in STOCK_HEALTH_INCIDENTS for code in observed)
            and "observation_invalid" not in observed
        )
        codes = set(observed) if complete and observed is not None else {"observation_invalid"}
        with self._locked() as (directory, lock):
            record = self._read(directory)
            _require(now >= _time(record["last_observed_at"]))
            rows = record["incidents"]
            active: set[str] = set()
            for row in rows:
                if row["resolved_at"] is not None:
                    continue
                active.add(row["code"])
                if row["code"] in codes:
                    row["last_seen"] = now.isoformat()
                elif complete:
                    row["resolved_at"] = now.isoformat()
            for code in sorted(codes - active):
                rows.append(
                    {
                        "code": code,
                        "first_seen": now.isoformat(),
                        "last_seen": now.isoformat(),
                        "resolved_at": None,
                    }
                )
            while len(rows) > _MAX_HISTORY:
                oldest = min(
                    (i for i, row in enumerate(rows) if row["resolved_at"] is not None),
                    key=lambda i: (_time(rows[i]["resolved_at"]), _time(rows[i]["first_seen"]), i),
                )
                del rows[oldest]
            record["last_observed_at"] = now.isoformat()
            return self._write(directory, lock, record)
