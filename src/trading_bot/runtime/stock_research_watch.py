"""Private caller-owned refresh priorities, not authenticated portfolio inventory.

Readers only open existing files read-only and acquire an existing shared lock.
The portfolio/reconciliation owner supplies the watch and its source identity;
this module never looks up an account or invents an empty inventory.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.clock import require_utc
from trading_bot.runtime.stock_capture import _private_directory
from trading_bot.runtime.stock_research_worker import StockResearchWatch

_STATE = "stock-watch.json"
_LOCK = ".stock-watch.lock"
_LIMIT = 8192
_FLAGS = ("source_authenticated", "account_verified", "execution_authorized", "live_authorized")


class StockResearchWatchError(ValueError):
    """Fixed local error text, without private source contents or paths."""


def _check(valid: bool) -> None:
    if not valid:
        raise StockResearchWatchError("stock_watch_unavailable")


def _json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _payload(watch: StockResearchWatch) -> dict[str, Any]:
    _check(type(watch) is StockResearchWatch)
    watch.__post_init__()
    return {
        "held_symbols": list(watch.held_symbols),
        "watch_symbols": list(watch.watch_symbols),
        "as_of": watch.as_of.isoformat(),
        "expires_at": watch.expires_at.isoformat(),
        "source_sha256": watch.source_sha256,
    }


def _body(watch: StockResearchWatch) -> bytes:
    payload = _payload(watch)
    return _json(
        {
            "schema_version": 1,
            "kind": "stock_research_watch",
            "payload": payload,
            "payload_sha256": hashlib.sha256(_json(payload)).hexdigest(),
            **dict.fromkeys(_FLAGS, False),
        }
    )


def _current(watch: StockResearchWatch, now: datetime, *, allow_expired: bool = False) -> None:
    now = require_utc(now)
    _check(watch.as_of <= now and (allow_expired or now < watch.expires_at))


def _decode(body: bytes, now: datetime, *, allow_expired: bool = False) -> StockResearchWatch:
    _check(0 < len(body) <= _LIMIT)
    document = json.loads(body)
    _check(
        type(document) is dict
        and set(document) == {"schema_version", "kind", "payload", "payload_sha256", *_FLAGS}
    )
    _check(
        type(document["schema_version"]) is int
        and document["schema_version"] == 1
        and document["kind"] == "stock_research_watch"
    )
    _check(all(document[key] is False for key in _FLAGS))
    payload = document["payload"]
    _check(
        type(payload) is dict
        and set(payload)
        == {"held_symbols", "watch_symbols", "as_of", "expires_at", "source_sha256"}
    )
    _check(type(payload["held_symbols"]) is list and type(payload["watch_symbols"]) is list)
    _check(type(payload["as_of"]) is str and type(payload["expires_at"]) is str)
    _check(document["payload_sha256"] == hashlib.sha256(_json(payload)).hexdigest())
    watch = StockResearchWatch(
        tuple(payload["held_symbols"]),
        tuple(payload["watch_symbols"]),
        require_utc(datetime.fromisoformat(payload["as_of"])),
        require_utc(datetime.fromisoformat(payload["expires_at"])),
        payload["source_sha256"],
    )
    _check(_body(watch) == body)
    _current(watch, now, allow_expired=allow_expired)
    return watch


def _private(info: os.stat_result, *, empty: bool = False) -> None:
    _check(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_nlink == 1
        and (info.st_size == 0 if empty else 0 < info.st_size <= _LIMIT)
    )


def _stamp(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _named_root(root: Path, directory: int) -> None:
    current = _private_directory(root)
    try:
        fresh, held = os.fstat(current), os.fstat(directory)
        _check((fresh.st_dev, fresh.st_ino) == (held.st_dev, held.st_ino))
    finally:
        os.close(current)


def _anchor(root: Path, directory: int, lock: int) -> None:
    held = os.fstat(lock)
    named = os.stat(_LOCK, dir_fd=directory, follow_symlinks=False)
    _private(held, empty=True)
    _private(named, empty=True)
    _check((held.st_dev, held.st_ino) == (named.st_dev, named.st_ino))
    _named_root(root, directory)


def _inventory(directory: int, *, temporary: str | None = None) -> set[str]:
    allowed = {_STATE, _LOCK} | ({temporary} if temporary is not None else set())
    names = set()
    with os.scandir(directory) as rows:
        for row in rows:
            _check(row.name in allowed and row.name not in names)
            _private(row.stat(follow_symlinks=False), empty=row.name == _LOCK)
            names.add(row.name)
            _check(len(names) <= len(allowed))
    _check(_STATE not in names or _LOCK in names)
    return names


@contextmanager
def _locked(root: Path, *, writer: bool) -> Iterator[tuple[int, int]]:
    directory = lock = -1
    try:
        directory = _private_directory(root)
        _inventory(directory)
        flags = (os.O_RDWR | os.O_CREAT) if writer else os.O_RDONLY
        lock = os.open(
            _LOCK, flags | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=directory
        )
        _anchor(root, directory, lock)
        fcntl.flock(lock, (fcntl.LOCK_EX if writer else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        _anchor(root, directory, lock)
        _inventory(directory)
        if writer:
            os.fsync(lock)
            os.fsync(directory)
        yield directory, lock
        _anchor(root, directory, lock)
        _inventory(directory)
    finally:
        try:
            if lock >= 0:
                os.close(lock)
        finally:
            if directory >= 0:
                os.close(directory)


def _read(directory: int) -> tuple[bytes, tuple[int, ...]]:
    descriptor = os.open(
        _STATE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory
    )
    try:
        before = os.fstat(descriptor)
        _private(before)
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            body = stream.read(_LIMIT + 1)
        named = os.stat(_STATE, dir_fd=directory, follow_symlinks=False)
        _private(named)
        _check(
            _stamp(before) == _stamp(os.fstat(descriptor)) == _stamp(named)
            and len(body) == before.st_size
        )
        return body, _stamp(named)
    finally:
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class StockResearchWatchReceipt:
    file: str
    body_sha256: str
    payload_sha256: str
    source_sha256: str


def _receipt(body: bytes, watch: StockResearchWatch) -> StockResearchWatchReceipt:
    return StockResearchWatchReceipt(
        _STATE,
        hashlib.sha256(body).hexdigest(),
        hashlib.sha256(_json(_payload(watch))).hexdigest(),
        watch.source_sha256,
    )


def read_stock_research_watch(
    *, root: Path, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
) -> StockResearchWatch:
    """Read current owner-supplied priorities without creating or changing files."""
    try:
        now = require_utc(clock())
        with _locked(root, writer=False) as (directory, lock):
            body, _ = _read(directory)
            watch = _decode(body, now)
            after = require_utc(clock())
            _check(after >= now)
            _current(watch, after)
            _anchor(root, directory, lock)
            return watch
    except Exception:
        raise StockResearchWatchError("stock_watch_unavailable") from None


def publish_stock_research_watch(
    *,
    root: Path,
    watch: StockResearchWatch,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> StockResearchWatchReceipt:
    """Atomically replace only known valid old state; never repair unknown state."""
    try:
        now = require_utc(clock())
        body = _body(watch)
        _check(len(body) <= _LIMIT)
        _current(watch, now)
        with _locked(root, writer=True) as (directory, lock):
            names = _inventory(directory)
            previous = None
            if _STATE in names:
                old, previous = _read(directory)
                old_watch = _decode(old, now, allow_expired=True)
                _check(watch.as_of >= old_watch.as_of)
                if watch.as_of == old_watch.as_of:
                    _check(body == old)
                if body == old:
                    after = require_utc(clock())
                    _check(after >= now)
                    _current(watch, after)
                    os.fsync(directory)
                    _anchor(root, directory, lock)
                    return _receipt(body, watch)
            temporary = ".pending-watch-" + uuid.uuid4().hex
            try:
                descriptor = os.open(
                    temporary,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | os.O_NOFOLLOW
                    | os.O_NONBLOCK
                    | os.O_CLOEXEC,
                    0o600,
                    dir_fd=directory,
                )
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(body)
                    stream.flush()
                    os.fsync(stream.fileno())
                    _private(os.fstat(stream.fileno()))
                _inventory(directory, temporary=temporary)
                _anchor(root, directory, lock)
                if previous is not None:
                    _check(
                        _stamp(os.stat(_STATE, dir_fd=directory, follow_symlinks=False)) == previous
                    )
                else:
                    try:
                        os.stat(_STATE, dir_fd=directory, follow_symlinks=False)
                    except FileNotFoundError:
                        pass
                    else:
                        raise StockResearchWatchError("stock_watch_unavailable")
                os.replace(temporary, _STATE, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                with suppress(FileNotFoundError):
                    os.unlink(temporary, dir_fd=directory)
            saved, _ = _read(directory)
            _check(saved == body)
            after = require_utc(clock())
            _check(after >= now)
            _decode(saved, after)
            _anchor(root, directory, lock)
            return _receipt(body, watch)
    except Exception:
        raise StockResearchWatchError("stock_watch_unavailable") from None
