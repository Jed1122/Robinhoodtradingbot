"""Root-private durable worker sequencing; no Docker, broker or control calls.

Only an explicitly initialized namespace is usable. An unfinished attempt can be
recovered for inspection/cleanup, never adopted for a new start. The records are
protocol-immutable consistency receipts, not authenticated container observations.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

from infra.hybrid.stock_container import _object
from infra.hybrid.stock_prestart import CreatedContainer
from infra.hybrid.stock_release import (
    StockRelease,
    _close_all,
    _exact,
    _fingerprint,
    _open_directory,
)

OPERATIONS_ROOT = Path("/var/lib/hybrid-stock-operations")
_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_WRITE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[0-9a-f]{32}\Z")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_BOOT = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
_ERRORS = (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError, AttributeError)
_CLOCK_KEYS = {"boot_id", "utc", "monotonic_ns"}
_INTENT_KEYS = {
    "schema_version",
    "kind",
    "namespace_id",
    "attempt_id",
    "release_id",
    "image_digest",
    "config_hash",
    "compose_sha256",
    "max_run_seconds",
    *_CLOCK_KEYS,
}
_FILES = {"intent.json", "created.json", "start.json", "stopped.json"}


def _deny() -> NoReturn:
    raise ValueError("stock_attempt_unavailable") from None


def _require(condition: bool) -> None:
    if not condition:
        _deny()


@contextmanager
def _sanitized() -> Iterator[None]:
    try:
        yield
    except _ERRORS:
        _deny()


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def _matches(value: Any, pattern: re.Pattern[str]) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def _integer(value: Any, low: int = 0, high: int = 2**63 - 1) -> bool:
    return type(value) is int and low <= value <= high


def _timestamp(value: Any, *, zero: bool = False) -> None:
    _require(type(value) is str and 20 <= len(value) <= 40)
    if zero and value == "0001-01-01T00:00:00Z":
        return
    parsed = datetime.fromisoformat(value)
    _require(parsed.tzinfo is not None and parsed.utcoffset() == UTC.utcoffset(parsed))
    _require(parsed.year >= 1970)


def _check_clock(value: dict[str, Any]) -> None:
    _require(_matches(value["boot_id"], _BOOT) and _integer(value["monotonic_ns"], 1))
    _timestamp(value["utc"])


def _clock() -> dict[str, Any]:
    _require(sys.platform == "linux")
    descriptor = os.open("/proc/sys/kernel/random/boot_id", _READ)
    try:
        boot = os.read(descriptor, 65).decode("ascii").strip()
    finally:
        _close_all((descriptor,))
    value = {
        "boot_id": boot,
        "utc": datetime.now(UTC).isoformat(),
        "monotonic_ns": time.monotonic_ns(),
    }
    _check_clock(value)
    return value


def _directory_info(info: os.stat_result, uid: int) -> None:
    _require(
        stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == uid
    )


def _file_info(info: os.stat_result, uid: int, *, empty: bool = False) -> None:
    _require(
        stat.S_ISREG(info.st_mode)
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_uid == uid
        and info.st_nlink == 1
    )
    _require(info.st_size == 0 if empty else 0 < info.st_size <= 4096)


def _exists(directory: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def _read(directory: int, name: str, uid: int) -> tuple[dict[str, Any], str]:
    descriptor = os.open(name, _READ, dir_fd=directory)
    try:
        before = os.fstat(descriptor)
        _file_info(before, uid)
        raw = b""
        while len(raw) <= 4096:
            chunk = os.read(descriptor, 4097 - len(raw))
            if not chunk:
                break
            raw += chunk
        _require(len(raw) == before.st_size and len(raw) <= 4096)
        stamp = _fingerprint(before)
        _require(stamp == _fingerprint(os.fstat(descriptor)))
        _require(stamp == _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False)))
    finally:
        _close_all((descriptor,))
    value = _object(raw)
    _require(_canonical(value) == raw)
    return value, hashlib.sha256(raw).hexdigest()


def _write_new(directory: int, name: str, value: dict[str, Any], uid: int) -> str:
    raw = _canonical(value)
    _require(0 < len(raw) <= 4096)
    descriptor = os.open(name, _WRITE, 0o600, dir_fd=directory)
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            _require(written > 0)
            offset += written
        _file_info(os.fstat(descriptor), uid)
        os.fsync(descriptor)
        _require(
            _fingerprint(os.fstat(descriptor))
            == _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False))
        )
    finally:
        _close_all((descriptor,))
    os.fsync(directory)
    read_back, digest = _read(directory, name, uid)
    _require(_exact(read_back, value))
    return digest


def _namespace(root_info: os.stat_result, lock_info: os.stat_result) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "stock_operations_namespace",
        "namespace_id": secrets.token_hex(16),
        "root_device": root_info.st_dev,
        "root_inode": root_info.st_ino,
        "lock_device": lock_info.st_dev,
        "lock_inode": lock_info.st_ino,
    }


def _reconfirm_durability(directory: int, name: str, value: dict[str, Any], uid: int) -> str:
    """Flush an unchanged valid receipt only after a fresh explicit observation."""
    descriptor = os.open(name, _READ, dir_fd=directory)
    try:
        before = os.fstat(descriptor)
        _file_info(before, uid)
        expected = _canonical(value)
        raw = b""
        while len(raw) <= 4096:
            chunk = os.read(descriptor, 4097 - len(raw))
            if not chunk:
                break
            raw += chunk
        _require(raw == expected and len(raw) == before.st_size)
        os.fsync(descriptor)
        _require(_fingerprint(before) == _fingerprint(os.fstat(descriptor)))
        _require(
            _fingerprint(before)
            == _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False))
        )
    finally:
        _close_all((descriptor,))
    os.fsync(directory)
    retained, digest = _read(directory, name, uid)
    _require(_exact(retained, value))
    return digest


def _validate_namespace(value: dict[str, Any], root: os.stat_result, lock: os.stat_result) -> None:
    _require(
        set(value)
        == {
            "schema_version",
            "kind",
            "namespace_id",
            "root_device",
            "root_inode",
            "lock_device",
            "lock_inode",
        }
    )
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1)
    _require(value["kind"] == "stock_operations_namespace" and _matches(value["namespace_id"], _ID))
    for key, expected in {
        "root_device": root.st_dev,
        "root_inode": root.st_ino,
        "lock_device": lock.st_dev,
        "lock_inode": lock.st_ino,
    }.items():
        _require(_integer(value[key]) and value[key] == expected)


def _initialize(root: Path, *, trusted_uid: int) -> None:
    """Private fixture seam; production entry point fixes path and UID below."""
    with _sanitized():
        _require(root.is_absolute() and ".." not in root.parts and os.geteuid() == trusted_uid)
        parent = _open_directory(
            root.parent,
            trusted_uid=trusted_uid,
            release_root=Path("/") if root == OPERATIONS_ROOT else root.parent,
        )
        directory: int | None = None
        lock: int | None = None
        try:
            os.mkdir(root.name, 0o700, dir_fd=parent)
            directory = os.open(root.name, _DIRECTORY, dir_fd=parent)
            _directory_info(os.fstat(directory), trusted_uid)
            lock = os.open("launcher.lock", _WRITE, 0o600, dir_fd=directory)
            _file_info(os.fstat(lock), trusted_uid, empty=True)
            os.fsync(lock)
            _write_new(
                directory,
                "namespace.json",
                _namespace(os.fstat(directory), os.fstat(lock)),
                trusted_uid,
            )
            os.fsync(directory)
            os.fsync(parent)
        finally:
            _close_all(fd for fd in (lock, directory, parent) if fd is not None)


def initialize_operations() -> None:
    _require(os.geteuid() == 0)
    _initialize(OPERATIONS_ROOT, trusted_uid=0)


@dataclass(frozen=True, slots=True)
class Attempt:
    namespace_id: str
    attempt_id: str
    release_id: str
    image_digest: str
    config_hash: str
    compose_sha256: str
    max_run_seconds: int
    boot_id: str
    created_utc: str
    created_monotonic_ns: int
    intent_sha256: str


@dataclass(frozen=True, slots=True)
class StartFence:
    attempt_id: str
    container_id: str
    boot_id: str
    start_monotonic_ns: int
    term_deadline_ns: int


def _intent(value: dict[str, Any], digest: str, namespace_id: str, attempt_id: str) -> Attempt:
    _require(
        set(value) == _INTENT_KEYS
        and type(value["schema_version"]) is int
        and value["schema_version"] == 1
        and value["kind"] == "stock_attempt_intent"
    )
    _require(value["namespace_id"] == namespace_id and value["attempt_id"] == attempt_id)
    for key in ("release_id", "config_hash", "compose_sha256"):
        _require(_matches(value[key], _HEX))
    _require(
        _matches(value["image_digest"], _IMAGE) and _integer(value["max_run_seconds"], 60, 450)
    )
    _check_clock(value)
    return Attempt(
        namespace_id,
        attempt_id,
        value["release_id"],
        value["image_digest"],
        value["config_hash"],
        value["compose_sha256"],
        value["max_run_seconds"],
        value["boot_id"],
        value["utc"],
        value["monotonic_ns"],
        digest,
    )


class AttemptStore:
    def __init__(self, root: Path, directory: int, lock: int, uid: int, namespace: dict[str, Any]):
        self._root, self._directory, self._lock, self._uid = root, directory, lock, uid
        self._namespace = namespace
        self._closed = False
        self._used_begin = False
        self._owned_attempt: str | None = None
        self._start_issued = False
        self._cid_record_issued = False
        self._created_acknowledged: str | None = None
        self._terminal_acknowledged: tuple[str, str] | None = None

    def _validate(self) -> None:
        _require(not self._closed and os.geteuid() == self._uid)
        _directory_info(os.fstat(self._directory), self._uid)
        _file_info(os.fstat(self._lock), self._uid, empty=True)
        _require(
            _fingerprint(os.fstat(self._lock))
            == _fingerprint(os.stat("launcher.lock", dir_fd=self._directory, follow_symlinks=False))
        )
        namespace, _ = _read(self._directory, "namespace.json", self._uid)
        _validate_namespace(namespace, os.fstat(self._directory), os.fstat(self._lock))
        _require(_exact(namespace, self._namespace))
        current = _open_directory(
            self._root,
            trusted_uid=self._uid,
            release_root=Path("/") if self._root == OPERATIONS_ROOT else self._root,
        )
        try:
            _require(
                (os.fstat(current).st_dev, os.fstat(current).st_ino)
                == (namespace["root_device"], namespace["root_inode"])
            )
        finally:
            _close_all((current,))

    def _inventory(self) -> set[str]:
        names = os.listdir(self._directory)
        _require(len(names) <= 8195)
        attempts = set(names) - {"launcher.lock", "namespace.json", "active.json"}
        _require(all(_matches(name, _ID) for name in attempts))
        return attempts

    @contextmanager
    def _attempt_directory(self, attempt_id: str) -> Iterator[int]:
        _require(_matches(attempt_id, _ID))
        descriptor = os.open(attempt_id, _DIRECTORY, dir_fd=self._directory)
        try:
            _directory_info(os.fstat(descriptor), self._uid)
            names = set(os.listdir(descriptor))
            _require("intent.json" in names and names.issubset(_FILES))
            yield descriptor
            _require(
                (os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino)
                == (
                    os.stat(attempt_id, dir_fd=self._directory, follow_symlinks=False).st_dev,
                    os.stat(attempt_id, dir_fd=self._directory, follow_symlinks=False).st_ino,
                )
            )
        finally:
            _close_all((descriptor,))

    def _active(self) -> Attempt | None:
        attempts = self._inventory()
        if not _exists(self._directory, "active.json"):
            _require(not attempts)
            return None
        head, _ = _read(self._directory, "active.json", self._uid)
        _require(
            set(head) == {"schema_version", "kind", "namespace_id", "attempt_id", "intent_sha256"}
        )
        _require(
            type(head["schema_version"]) is int
            and head["schema_version"] == 1
            and head["kind"] == "stock_attempt_head"
            and head["namespace_id"] == self._namespace["namespace_id"]
        )
        _require(
            _matches(head["attempt_id"], _ID)
            and head["attempt_id"] in attempts
            and _matches(head["intent_sha256"], _HEX)
        )
        with self._attempt_directory(head["attempt_id"]) as directory:
            value, digest = _read(directory, "intent.json", self._uid)
            _require(digest == head["intent_sha256"])
            return _intent(value, digest, head["namespace_id"], head["attempt_id"])

    def active(self) -> Attempt | None:
        with _sanitized():
            self._validate()
            result = self._active()
            self._validate()
            return result

    def _receipt(self, directory: int, name: str, attempt: Attempt) -> dict[str, Any]:
        value, _ = _read(directory, name, self._uid)
        common = {
            "schema_version",
            "kind",
            "namespace_id",
            "attempt_id",
            "intent_sha256",
            "container_id",
            *_CLOCK_KEYS,
        }
        extra = set()
        if name == "stopped.json":
            extra = {
                "status",
                "exit_code",
                "oom_killed",
                "error_present",
                "start_fence_present",
                "container_started_at",
                "container_finished_at",
            }
        elif name == "start.json":
            extra = {"term_deadline_ns"}
        _require(
            set(value) == common | extra
            and type(value["schema_version"]) is int
            and value["schema_version"] == 1
            and value["kind"] == "stock_attempt_" + name.partition(".")[0]
        )
        _require(
            value["namespace_id"] == attempt.namespace_id
            and value["attempt_id"] == attempt.attempt_id
            and value["intent_sha256"] == attempt.intent_sha256
            and _matches(value["container_id"], _HEX)
        )
        _check_clock(value)
        if name == "stopped.json":
            _require(
                value["status"] in ("created", "exited", "dead")
                and _integer(value["exit_code"], 0, 255)
            )
            _require(
                all(
                    type(value[key]) is bool
                    for key in ("oom_killed", "error_present", "start_fence_present")
                )
            )
            _timestamp(value["container_started_at"], zero=True)
            _timestamp(value["container_finished_at"], zero=True)
        else:
            _require(
                value["boot_id"] == attempt.boot_id
                and value["monotonic_ns"] >= attempt.created_monotonic_ns
            )
            if name == "start.json":
                _require(
                    _integer(value["term_deadline_ns"])
                    and value["term_deadline_ns"]
                    == value["monotonic_ns"] + attempt.max_run_seconds * 1000000000
                )
        return value

    def _created_and_start(self, directory: int, attempt: Attempt) -> dict[str, Any] | None:
        has_start = _exists(directory, "start.json")
        if not _exists(directory, "created.json"):
            _require(not has_start)
            return None
        created = self._receipt(directory, "created.json", attempt)
        if has_start:
            start = self._receipt(directory, "start.json", attempt)
            _require(
                start["container_id"] == created["container_id"]
                and start["boot_id"] == created["boot_id"]
                and start["monotonic_ns"] >= created["monotonic_ns"]
            )
        return created

    def begin(self, release: StockRelease) -> Attempt:
        with _sanitized():
            self._validate()
            _require(not self._used_begin and type(release) is StockRelease)
            active = self._active()
            if active is not None:
                if self._terminal_acknowledged is None:
                    _deny()
                _require(self._terminal_acknowledged[0] == active.attempt_id)
            for old_id in self._inventory():
                with self._attempt_directory(old_id) as directory:
                    raw, digest = _read(directory, "intent.json", self._uid)
                    old = _intent(raw, digest, self._namespace["namespace_id"], old_id)
                    known_created = self._created_and_start(directory, old)
                    stopped = self._receipt(directory, "stopped.json", old)
                    _require(
                        known_created is None
                        or stopped["container_id"] == known_created["container_id"]
                    )
                    if active is not None and old_id == active.attempt_id:
                        _require(
                            self._terminal_acknowledged is not None
                            and self._terminal_acknowledged[1]
                            == hashlib.sha256(_canonical(stopped)).hexdigest()
                        )
            _require(active is None or active.attempt_id in self._inventory())
            self._used_begin = True
            attempt_id = secrets.token_hex(16)
            value = {
                "schema_version": 1,
                "kind": "stock_attempt_intent",
                "namespace_id": self._namespace["namespace_id"],
                "attempt_id": attempt_id,
                "release_id": release.release_id,
                "image_digest": release.image_digest,
                "config_hash": release.config_hash,
                "compose_sha256": release.compose_sha256,
                "max_run_seconds": release.max_run_seconds,
                **_clock(),
            }
            _intent(
                value,
                hashlib.sha256(_canonical(value)).hexdigest(),
                self._namespace["namespace_id"],
                attempt_id,
            )
            os.mkdir(attempt_id, 0o700, dir_fd=self._directory)
            directory = os.open(attempt_id, _DIRECTORY, dir_fd=self._directory)
            try:
                _directory_info(os.fstat(directory), self._uid)
                digest = _write_new(directory, "intent.json", value, self._uid)
            finally:
                _close_all((directory,))
            os.fsync(self._directory)
            self._validate()
            head = {
                "schema_version": 1,
                "kind": "stock_attempt_head",
                "namespace_id": self._namespace["namespace_id"],
                "attempt_id": attempt_id,
                "intent_sha256": digest,
            }
            temporary = ".active-" + secrets.token_hex(16) + ".tmp"
            _write_new(self._directory, temporary, head, self._uid)
            self._validate()
            os.replace(
                temporary, "active.json", src_dir_fd=self._directory, dst_dir_fd=self._directory
            )
            os.fsync(self._directory)
            result = self._active()
            if result is None or result.attempt_id != attempt_id or result.intent_sha256 != digest:
                _deny()
            self._validate()
            self._owned_attempt = attempt_id
            self._created_acknowledged = None
            self._terminal_acknowledged = None
            self._cid_record_issued = False
            self._start_issued = False
            return result

    def _owned(self) -> Attempt:
        self._validate()
        active = self._active()
        if active is None or active.attempt_id != self._owned_attempt:
            _deny()
        with self._attempt_directory(active.attempt_id) as directory:
            _require(not _exists(directory, "stopped.json"))
        return active

    @staticmethod
    def _base(
        attempt: Attempt, kind: str, container_id: str, clock: dict[str, Any]
    ) -> dict[str, Any]:
        _check_clock(clock)
        return {
            "schema_version": 1,
            "kind": "stock_attempt_" + kind,
            "namespace_id": attempt.namespace_id,
            "attempt_id": attempt.attempt_id,
            "intent_sha256": attempt.intent_sha256,
            "container_id": container_id,
            **clock,
        }

    def record_created(self, verified: CreatedContainer) -> None:
        with _sanitized():
            attempt = self._owned()
            _require(not self._cid_record_issued)
            self._cid_record_issued = True
            self._created_acknowledged = None
            _require(type(verified) is CreatedContainer and _matches(verified.container_id, _HEX))
            _require(
                _exact(
                    [
                        verified.attempt_id,
                        verified.release_id,
                        verified.image_digest,
                        verified.config_hash,
                        verified.compose_sha256,
                    ],
                    [
                        attempt.attempt_id,
                        attempt.release_id,
                        attempt.image_digest,
                        attempt.config_hash,
                        attempt.compose_sha256,
                    ],
                )
            )
            value = self._base(attempt, "created", verified.container_id, _clock())
            _require(
                value["boot_id"] == attempt.boot_id
                and value["monotonic_ns"] >= attempt.created_monotonic_ns
            )
            with self._attempt_directory(attempt.attempt_id) as directory:
                digest = _write_new(directory, "created.json", value, self._uid)
            self._validate()
            self._created_acknowledged = digest

    def prepare_start(self) -> StartFence:
        with _sanitized():
            attempt = self._owned()
            _require(not self._start_issued and self._created_acknowledged is not None)
            with self._attempt_directory(attempt.attempt_id) as directory:
                created = self._receipt(directory, "created.json", attempt)
                _require(
                    hashlib.sha256(_canonical(created)).hexdigest() == self._created_acknowledged
                )
                clock = _clock()
                _check_clock(clock)
                _require(
                    clock["boot_id"] == attempt.boot_id
                    and clock["monotonic_ns"] >= created["monotonic_ns"]
                )
                deadline = clock["monotonic_ns"] + attempt.max_run_seconds * 1000000000
                _require(_integer(deadline))
                value = {
                    **self._base(attempt, "start", created["container_id"], clock),
                    "term_deadline_ns": deadline,
                }
                self._start_issued = True
                _write_new(directory, "start.json", value, self._uid)
            self._validate()
            now = _clock()
            _check_clock(now)
            _require(
                now["boot_id"] == attempt.boot_id
                and clock["monotonic_ns"] <= now["monotonic_ns"] < deadline
            )
            return StartFence(
                attempt.attempt_id,
                created["container_id"],
                attempt.boot_id,
                clock["monotonic_ns"],
                deadline,
            )

    def record_stopped(self, raw: bytes) -> dict[str, Any]:
        with _sanitized():
            self._created_acknowledged = None
            self._terminal_acknowledged = None
            self._start_issued = True
            self._validate()
            attempt = self._active()
            if attempt is None:
                _deny()
            with self._attempt_directory(attempt.attempt_id) as directory:
                known_created = self._created_and_start(directory, attempt)
                expected_cid = known_created["container_id"] if known_created is not None else None
                facts = _stopped(raw, attempt, expected_cid)
                if _exists(directory, "stopped.json"):
                    value = self._receipt(directory, "stopped.json", attempt)
                    _require(_exact({key: value[key] for key in facts}, facts))
                    _require(value["start_fence_present"] is _exists(directory, "start.json"))
                    digest = _reconfirm_durability(directory, "stopped.json", value, self._uid)
                else:
                    value = {
                        **self._base(attempt, "stopped", facts.pop("container_id"), _clock()),
                        **facts,
                        "start_fence_present": _exists(directory, "start.json"),
                    }
                    digest = _write_new(directory, "stopped.json", value, self._uid)
                self._receipt(directory, "stopped.json", attempt)
            self._validate()
            self._terminal_acknowledged = (attempt.attempt_id, digest)
            return value


def _stopped(raw: bytes, attempt: Attempt, expected_cid: str | None) -> dict[str, Any]:
    value = _object(raw)
    _require(_matches(value["Id"], _HEX) and (expected_cid is None or value["Id"] == expected_cid))
    _require(
        value["Image"] == attempt.image_digest
        and value["Name"] == "/hybrid-stock-research-" + attempt.attempt_id
    )
    _require(
        value["Platform"] == "linux"
        and type(value["RestartCount"]) is int
        and value["RestartCount"] == 0
    )
    _require(
        _exact(
            value["Config"]["Labels"],
            {
                "org.hybrid.stock.managed": "stock-research",
                "org.hybrid.stock.release": attempt.release_id,
                "org.hybrid.stock.attempt": attempt.attempt_id,
            },
        )
    )
    _require(
        value["HostConfig"]["AutoRemove"] is False
        and _exact(value["HostConfig"]["RestartPolicy"], {"Name": "no", "MaximumRetryCount": 0})
    )
    state = value["State"]
    _require(
        type(state) is dict
        and set(state)
        == {
            "Status",
            "Running",
            "Paused",
            "Restarting",
            "OOMKilled",
            "Dead",
            "Pid",
            "ExitCode",
            "Error",
            "StartedAt",
            "FinishedAt",
        }
    )
    _require(state["Status"] in ("created", "exited", "dead"))
    _require(all(state[key] is False for key in ("Running", "Paused", "Restarting")))
    _require(type(state["Dead"]) is bool and state["Dead"] == (state["Status"] == "dead"))
    _require(
        type(state["Pid"]) is int and state["Pid"] == 0 and _integer(state["ExitCode"], 0, 255)
    )
    _require(
        type(state["OOMKilled"]) is bool
        and type(state["Error"]) is str
        and len(state["Error"]) <= 4096
    )
    for key in ("StartedAt", "FinishedAt"):
        _timestamp(state[key], zero=True)
    return {
        "container_id": value["Id"],
        "status": state["Status"],
        "exit_code": state["ExitCode"],
        "oom_killed": state["OOMKilled"],
        "error_present": bool(state["Error"]),
        "container_started_at": state["StartedAt"],
        "container_finished_at": state["FinishedAt"],
    }


@contextmanager
def _open_operations(root: Path, *, trusted_uid: int) -> Iterator[AttemptStore]:
    with _sanitized():
        directory = _open_directory(
            root,
            trusted_uid=trusted_uid,
            release_root=Path("/") if root == OPERATIONS_ROOT else root,
        )
        lock: int | None = None
        store: AttemptStore | None = None
        try:
            _directory_info(os.fstat(directory), trusted_uid)
            lock = os.open(
                "launcher.lock",
                os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=directory,
            )
            _file_info(os.fstat(lock), trusted_uid, empty=True)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            namespace, _ = _read(directory, "namespace.json", trusted_uid)
            _validate_namespace(namespace, os.fstat(directory), os.fstat(lock))
            store = AttemptStore(root, directory, lock, trusted_uid, namespace)
            store._validate()
            yield store
        finally:
            if store is not None:
                store._closed = True
            _close_all(fd for fd in (lock, directory) if fd is not None)


def operations() -> AbstractContextManager[AttemptStore]:
    """Fixed production namespace; private fixture helper cannot select runtime paths."""
    _require(os.geteuid() == 0)
    return _open_operations(OPERATIONS_ROOT, trusted_uid=0)
