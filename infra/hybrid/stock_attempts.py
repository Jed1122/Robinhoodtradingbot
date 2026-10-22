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
_LINEAGE_KEYS = {
    "predecessor_attempt_id",
    "predecessor_terminal_kind",
    "predecessor_terminal_sha256",
    "retirement_attempt_id",
    "retirement_container_id",
    "retirement_stopped_sha256",
}
_V1_FILES = {"intent.json", "created.json", "start.json", "stopped.json"}
_FILES = _V1_FILES | {"create.json", "removal-intent.json", "removed.json", "abandoned.json"}
_TARGET_KEYS = {"target_attempt_id", "target_container_id", "target_stopped_sha256"}
_EXTRA_KEYS = {
    "create.json": {"request_sha256", "dispatch_deadline_ns"},
    "removal-intent.json": _TARGET_KEYS,
    "removed.json": _TARGET_KEYS | {"removal_intent_sha256", "evidence_kind"},
    "abandoned.json": {"removed_sha256"},
    "created.json": {"container_id"},
    "start.json": {"container_id", "term_deadline_ns"},
    "stopped.json": {
        "container_id",
        "status",
        "exit_code",
        "oom_killed",
        "error_present",
        "start_fence_present",
        "container_started_at",
        "container_finished_at",
    },
}
_KINDS = {
    name: "stock_attempt_"
    + (
        "abandoned_before_dispatch"
        if name == "abandoned.json"
        else name.removesuffix(".json").replace("-", "_")
    )
    for name in _EXTRA_KEYS
}


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
        "schema_version": 2,
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
    _require(type(value["schema_version"]) is int and value["schema_version"] in (1, 2))
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
    schema_version: int
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
    predecessor_attempt_id: str | None
    predecessor_terminal_kind: str | None
    predecessor_terminal_sha256: str | None
    retirement_attempt_id: str | None
    retirement_container_id: str | None
    retirement_stopped_sha256: str | None


@dataclass(frozen=True, slots=True)
class CreateFence:
    attempt_id: str
    intent_sha256: str
    receipt_sha256: str
    request_sha256: str
    boot_id: str
    dispatch_deadline_ns: int


@dataclass(frozen=True, slots=True)
class RemovalFence:
    attempt_id: str
    intent_sha256: str
    target_attempt_id: str
    target_container_id: str
    target_stopped_sha256: str
    removal_intent_sha256: str
    boot_id: str
    issued_monotonic_ns: int
    deadline_ns: int


@dataclass(frozen=True, slots=True)
class RetirementProof:
    """Trusted closed-transport result; copied receipts are not this authority."""

    fence: RemovalFence
    evidence_kind: str
    boot_id: str
    observed_monotonic_ns: int


@dataclass(frozen=True, slots=True)
class StartFence:
    attempt_id: str
    container_id: str
    boot_id: str
    start_monotonic_ns: int
    term_deadline_ns: int


@dataclass(frozen=True, slots=True)
class AttemptSnapshot:
    """Copied durable identity/timing, with no execution or durability authority."""

    attempt: Attempt
    container_id: str | None
    start_fence: StartFence | None
    created_sha256: str | None
    start_sha256: str | None
    stopped_sha256: str | None
    create_sha256: str | None
    removal_intent_sha256: str | None
    removed_sha256: str | None
    abandoned_sha256: str | None


def _intent(
    value: dict[str, Any], digest: str, namespace_id: str, attempt_id: str, version: int
) -> Attempt:
    _require(
        set(value) == (_INTENT_KEYS | (_LINEAGE_KEYS if version == 2 else set()))
        and type(value["schema_version"]) is int
        and value["schema_version"] == version
        and value["kind"] == "stock_attempt_intent"
    )
    _require(value["namespace_id"] == namespace_id and value["attempt_id"] == attempt_id)
    for key in ("release_id", "config_hash", "compose_sha256"):
        _require(_matches(value[key], _HEX))
    _require(
        _matches(value["image_digest"], _IMAGE) and _integer(value["max_run_seconds"], 60, 450)
    )
    _check_clock(value)
    if version == 2:
        logical = [
            value[key]
            for key in (
                "predecessor_attempt_id",
                "predecessor_terminal_kind",
                "predecessor_terminal_sha256",
            )
        ]
        physical = [
            value[key]
            for key in (
                "retirement_attempt_id",
                "retirement_container_id",
                "retirement_stopped_sha256",
            )
        ]
        _require(
            all(item is None for item in logical)
            or (
                _matches(logical[0], _ID)
                and logical[1] in ("stopped", "abandoned_before_dispatch")
                and _matches(logical[2], _HEX)
            )
        )
        _require(
            all(item is None for item in physical)
            or (
                _matches(physical[0], _ID)
                and _matches(physical[1], _HEX)
                and _matches(physical[2], _HEX)
            )
        )
    return Attempt(
        version,
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
        value.get("predecessor_attempt_id"),
        value.get("predecessor_terminal_kind"),
        value.get("predecessor_terminal_sha256"),
        value.get("retirement_attempt_id"),
        value.get("retirement_container_id"),
        value.get("retirement_stopped_sha256"),
    )


class AttemptStore:
    def __init__(self, root: Path, directory: int, lock: int, uid: int, namespace: dict[str, Any]):
        self._root, self._directory, self._lock, self._uid = root, directory, lock, uid
        self._namespace = namespace
        self._closed = False
        self._used_begin = True
        self._owned_attempt: str | None = None
        self._create_issued = False
        self._create_claim: Attempt | None = None
        self._start_issued = False
        self._start_fence: StartFence | None = None
        self._start_acknowledged: str | None = None
        self._cid_record_issued = False
        self._created_acknowledged: str | None = None
        self._terminal_acknowledged: tuple[str, str] | None = None
        self._create_fence: CreateFence | None = None
        self._create_acknowledged: str | None = None
        self._create_prepared = False
        self._removal_fence: RemovalFence | None = None
        self._removal_issued = False
        self._removed_acknowledged: str | None = None
        self._recovery_only = False
        # The opener classifies the checked entry state before exposing this store.
        self._entry_unfinished = True
        self._entry_terminal: tuple[str, str, str, str] | None = None
        # Per-lock content validation, usable only while every named file retains
        # its checked inode/owner/mode/links/size/mtime/ctime. Never an authority.
        self._snapshots: dict[str, tuple[AttemptSnapshot, dict[str, tuple[int, ...]]]] = {}

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
            and head["schema_version"] == self._namespace["schema_version"]
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
            return _intent(
                value,
                digest,
                head["namespace_id"],
                head["attempt_id"],
                self._namespace["schema_version"],
            )

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
            *_CLOCK_KEYS,
        }
        _require(
            set(value) == common | _EXTRA_KEYS[name]
            and type(value["schema_version"]) is int
            and value["schema_version"] == attempt.schema_version
            and value["kind"] == _KINDS[name]
            and (attempt.schema_version == 2 or name in _V1_FILES)
        )
        _require(
            value["namespace_id"] == attempt.namespace_id
            and value["attempt_id"] == attempt.attempt_id
            and value["intent_sha256"] == attempt.intent_sha256
        )
        if name in ("created.json", "start.json", "stopped.json"):
            _require(_matches(value["container_id"], _HEX))
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
            _require(value["start_fence_present"] is _exists(directory, "start.json"))
            _require(value["status"] != "created" or value["start_fence_present"] is False)
            _timestamp(value["container_started_at"], zero=True)
            _timestamp(value["container_finished_at"], zero=True)
        elif name in ("created.json", "start.json", "create.json"):
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
            elif name == "create.json":
                _require(
                    _matches(value["request_sha256"], _HEX)
                    and _integer(value["dispatch_deadline_ns"])
                    and value["monotonic_ns"]
                    < value["dispatch_deadline_ns"]
                    <= value["monotonic_ns"] + 5000000000
                )
        elif name in ("removal-intent.json", "removed.json"):
            _require(
                value["target_attempt_id"] == attempt.retirement_attempt_id
                and value["target_container_id"] == attempt.retirement_container_id
                and value["target_stopped_sha256"] == attempt.retirement_stopped_sha256
                and _matches(value["target_attempt_id"], _ID)
                and _matches(value["target_container_id"], _HEX)
                and _matches(value["target_stopped_sha256"], _HEX)
            )
            if name == "removed.json":
                _require(
                    _matches(value["removal_intent_sha256"], _HEX)
                    and value["evidence_kind"] in ("delete_204", "inspect_404")
                )
        elif name == "abandoned.json":
            _require(value["removed_sha256"] is None or _matches(value["removed_sha256"], _HEX))
        return value

    def _created_and_start(self, directory: int, attempt: Attempt) -> dict[str, Any] | None:
        has_start = _exists(directory, "start.json")
        create = None
        if attempt.schema_version == 2:
            if _exists(directory, "create.json"):
                create = self._receipt(directory, "create.json", attempt)
            else:
                _require(
                    not any(
                        _exists(directory, name)
                        for name in ("created.json", "start.json", "stopped.json")
                    )
                )
        if not _exists(directory, "created.json"):
            _require(not has_start)
            return None
        created = self._receipt(directory, "created.json", attempt)
        if create is not None:
            _require(created["monotonic_ns"] >= create["monotonic_ns"])
        if has_start:
            start = self._receipt(directory, "start.json", attempt)
            _require(
                start["container_id"] == created["container_id"]
                and start["boot_id"] == created["boot_id"]
                and start["monotonic_ns"] >= created["monotonic_ns"]
            )
        return created

    def _local_snapshot(self, attempt: Attempt) -> AttemptSnapshot:
        with self._attempt_directory(attempt.attempt_id) as directory:
            names = set(os.listdir(directory))
            _require(attempt.schema_version == 2 or names.issubset(_V1_FILES))
            stamps = {
                name: _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False))
                for name in names
            }
            cached = self._snapshots.get(attempt.attempt_id)
            if cached is not None and cached[0].attempt == attempt and cached[1] == stamps:
                return cached[0]
            created = self._created_and_start(directory, attempt)
            receipts = {
                name: self._receipt(directory, name, attempt) for name in names - {"intent.json"}
            }
            hashes = {
                name: hashlib.sha256(_canonical(value)).hexdigest()
                for name, value in receipts.items()
            }
            container_id = created["container_id"] if created is not None else None
            start = receipts.get("start.json")
            fence = (
                None
                if start is None
                else StartFence(
                    attempt.attempt_id,
                    start["container_id"],
                    start["boot_id"],
                    start["monotonic_ns"],
                    start["term_deadline_ns"],
                )
            )
            stopped = receipts.get("stopped.json")
            if stopped is not None:
                _require(container_id is None or stopped["container_id"] == container_id)
                container_id = stopped["container_id"]
            if attempt.schema_version == 2:
                removed = receipts.get("removed.json")
                if removed is not None:
                    _require(removed["removal_intent_sha256"] == hashes.get("removal-intent.json"))
                if attempt.retirement_attempt_id is None:
                    _require("removed.json" not in names and "removal-intent.json" not in names)
                elif "create.json" in names or "abandoned.json" in names:
                    _require(removed is not None)
                abandoned = receipts.get("abandoned.json")
                if abandoned is not None:
                    _require(
                        not names.intersection(
                            {"create.json", "created.json", "start.json", "stopped.json"}
                        )
                    )
                    _require(abandoned["removed_sha256"] == hashes.get("removed.json"))
            result = AttemptSnapshot(
                attempt,
                container_id,
                fence,
                hashes.get("created.json"),
                hashes.get("start.json"),
                hashes.get("stopped.json"),
                hashes.get("create.json"),
                hashes.get("removal-intent.json"),
                hashes.get("removed.json"),
                hashes.get("abandoned.json"),
            )
            _require(
                stamps
                == {
                    name: _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False))
                    for name in set(os.listdir(directory))
                }
            )
            self._snapshots[attempt.attempt_id] = (result, stamps)
            return result

    def _history(self) -> dict[str, AttemptSnapshot]:
        active = self._active()
        if active is None:
            return {}
        history = {}
        cids = set()
        for attempt_id in self._inventory():
            with self._attempt_directory(attempt_id) as directory:
                stamp = _fingerprint(
                    os.stat("intent.json", dir_fd=directory, follow_symlinks=False)
                )
                cached = self._snapshots.get(attempt_id)
                if cached is not None and cached[1]["intent.json"] == stamp:
                    attempt = cached[0].attempt
                    _require(
                        attempt.attempt_id == attempt_id
                        and attempt.namespace_id == self._namespace["namespace_id"]
                        and attempt.schema_version == self._namespace["schema_version"]
                    )
                else:
                    value, digest = _read(directory, "intent.json", self._uid)
                    attempt = _intent(
                        value,
                        digest,
                        self._namespace["namespace_id"],
                        attempt_id,
                        self._namespace["schema_version"],
                    )
            state = self._local_snapshot(attempt)
            history[attempt_id] = state
            if active.schema_version == 2 and state.container_id is not None:
                _require(state.container_id not in cids)
                cids.add(state.container_id)
            if attempt_id != active.attempt_id:
                _require(state.stopped_sha256 is not None or state.abandoned_sha256 is not None)
        if active.schema_version == 1:
            return history
        visited = set()
        cursor: AttemptSnapshot | None = history[active.attempt_id]
        while cursor is not None:
            attempt = cursor.attempt
            _require(attempt.attempt_id not in visited)
            visited.add(attempt.attempt_id)
            predecessor_id = attempt.predecessor_attempt_id
            if predecessor_id is None:
                _require(attempt.retirement_attempt_id is None)
                cursor = None
                continue
            _require(predecessor_id in history)
            predecessor = history[predecessor_id]
            if attempt.predecessor_terminal_kind == "stopped":
                _require(
                    predecessor.stopped_sha256 is not None
                    and attempt.predecessor_terminal_sha256 == predecessor.stopped_sha256
                    and attempt.retirement_attempt_id == predecessor_id
                    and attempt.retirement_container_id == predecessor.container_id
                    and attempt.retirement_stopped_sha256 == predecessor.stopped_sha256
                )
            else:
                _require(
                    predecessor.abandoned_sha256 is not None
                    and attempt.predecessor_terminal_sha256 == predecessor.abandoned_sha256
                    and attempt.retirement_attempt_id is None
                )
            cursor = predecessor
        _require(visited == set(history))
        return history

    def snapshot(self) -> AttemptSnapshot | None:
        """Read the checked active receipt chain without acknowledging or repairing it."""
        with _sanitized():
            self._validate()
            attempt = self._active()
            history = self._history()
            result = None if attempt is None else history[attempt.attempt_id]
            self._validate()
            _require(self._active() == attempt)
            return result

    def _burn_recovery(self) -> None:
        self._recovery_only = True
        self._used_begin = True
        self._create_issued = self._create_prepared = self._cid_record_issued = True
        self._start_issued = True
        self._create_claim = None
        self._create_fence = None
        self._create_acknowledged = None
        self._created_acknowledged = None
        self._start_fence = None
        self._start_acknowledged = None
        self._terminal_acknowledged = None
        self._removal_fence = None
        self._removed_acknowledged = None

    def recovery_snapshot(self) -> AttemptSnapshot | None:
        with _sanitized():
            self._burn_recovery()
            return self.snapshot()

    def cleanup_target(self) -> AttemptSnapshot:
        """Revoke fresh execution before obtaining a start-fenced cleanup target."""
        with _sanitized():
            result = self.recovery_snapshot()
            if result is None:
                _deny()
            _require(
                result.container_id is not None
                and result.created_sha256 is not None
                and result.start_sha256 is not None
                and result.start_fence is not None
                and result.stopped_sha256 is None
            )
            return result

    def begin(self, release: StockRelease) -> Attempt:
        with _sanitized():
            self._validate()
            _require(
                self._namespace["schema_version"] == 2
                and not self._used_begin
                and not self._recovery_only
                and type(release) is StockRelease
            )
            active = self._active()
            history = self._history()
            lineage = dict.fromkeys(_LINEAGE_KEYS)
            if active is not None:
                if self._terminal_acknowledged is None:
                    _deny()
                _require(self._terminal_acknowledged[0] == active.attempt_id)
                predecessor = history[active.attempt_id]
                kind = (
                    "stopped"
                    if predecessor.stopped_sha256 is not None
                    else "abandoned_before_dispatch"
                )
                terminal_hash = predecessor.stopped_sha256 or predecessor.abandoned_sha256
                _require(
                    terminal_hash is not None
                    and self._terminal_acknowledged[1] == terminal_hash
                    and self._entry_terminal
                    == (active.attempt_id, active.intent_sha256, kind, terminal_hash)
                )
                lineage.update(
                    {
                        "predecessor_attempt_id": active.attempt_id,
                        "predecessor_terminal_kind": kind,
                        "predecessor_terminal_sha256": terminal_hash,
                    }
                )
                if kind == "stopped":
                    lineage.update(
                        {
                            "retirement_attempt_id": active.attempt_id,
                            "retirement_container_id": predecessor.container_id,
                            "retirement_stopped_sha256": predecessor.stopped_sha256,
                        }
                    )
            _require(active is None or active.attempt_id in self._inventory())
            self._used_begin = True
            attempt_id = secrets.token_hex(16)
            value = {
                "schema_version": 2,
                "kind": "stock_attempt_intent",
                "namespace_id": self._namespace["namespace_id"],
                "attempt_id": attempt_id,
                "release_id": release.release_id,
                "image_digest": release.image_digest,
                "config_hash": release.config_hash,
                "compose_sha256": release.compose_sha256,
                "max_run_seconds": release.max_run_seconds,
                **lineage,
                **_clock(),
            }
            _intent(
                value,
                hashlib.sha256(_canonical(value)).hexdigest(),
                self._namespace["namespace_id"],
                attempt_id,
                2,
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
                "schema_version": 2,
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
            self._create_issued = False
            self._create_claim = None
            self._create_prepared = False
            self._create_fence = None
            self._create_acknowledged = None
            self._removal_fence = None
            self._removal_issued = False
            self._removed_acknowledged = None
            self._created_acknowledged = None
            self._terminal_acknowledged = None
            self._cid_record_issued = False
            self._start_issued = False
            self._start_fence = None
            self._start_acknowledged = None
            return result

    def _owned(self) -> Attempt:
        self._validate()
        _require(self._namespace["schema_version"] == 2 and not self._recovery_only)
        active = self._active()
        if active is None or active.attempt_id != self._owned_attempt:
            _deny()
        with self._attempt_directory(active.attempt_id) as directory:
            _require(
                not any(_exists(directory, name) for name in ("stopped.json", "abandoned.json"))
            )
        state = self._history()[active.attempt_id]
        if active.retirement_attempt_id is not None:
            _require(
                self._removed_acknowledged is not None
                and state.removed_sha256 == self._removed_acknowledged
            )
        return active

    def claim_create(self, release: StockRelease) -> Attempt:
        """Consume one fresh owner's create claim, including on validation failure."""
        with _sanitized():
            issued = self._create_issued
            self._create_issued = True
            self._create_claim = None
            _require(not issued)
            attempt = self._owned()
            _require(type(release) is StockRelease)
            _require(
                _exact(
                    [
                        release.release_id,
                        release.image_digest,
                        release.config_hash,
                        release.compose_sha256,
                        release.max_run_seconds,
                    ],
                    [
                        attempt.release_id,
                        attempt.image_digest,
                        attempt.config_hash,
                        attempt.compose_sha256,
                        attempt.max_run_seconds,
                    ],
                )
            )
            self._create_claim = attempt
            self.check_create_claim(attempt)
            return attempt

    def check_create_claim(self, claim: Attempt) -> None:
        """Recheck supplied claim consistency; this performs no dispatch itself."""
        with _sanitized():
            _require(type(claim) is Attempt and self._create_claim is claim)
            attempt = self._owned()
            _require(
                attempt == claim
                and self._create_issued
                and not self._cid_record_issued
                and not self._start_issued
            )
            with self._attempt_directory(attempt.attempt_id) as directory:
                expected = {"intent.json"}
                if attempt.retirement_attempt_id is not None:
                    expected |= {"removal-intent.json", "removed.json"}
                _require(set(os.listdir(directory)) == expected)
            self._validate()
            clock = _clock()
            _check_clock(clock)
            _require(
                clock["boot_id"] == attempt.boot_id
                and clock["monotonic_ns"] >= attempt.created_monotonic_ns
            )

    @staticmethod
    def _base(
        attempt: Attempt, kind: str, container_id: str | None, clock: dict[str, Any]
    ) -> dict[str, Any]:
        _check_clock(clock)
        return {
            "schema_version": attempt.schema_version,
            "kind": "stock_attempt_" + kind,
            "namespace_id": attempt.namespace_id,
            "attempt_id": attempt.attempt_id,
            "intent_sha256": attempt.intent_sha256,
            **({"container_id": container_id} if container_id is not None else {}),
            **clock,
        }

    def prepare_create(
        self, claim: Attempt, request_sha256: str, dispatch_deadline_ns: int
    ) -> CreateFence:
        with _sanitized():
            prepared = self._create_prepared
            self._create_prepared = True
            self._create_fence = None
            self._create_acknowledged = None
            _require(not prepared)
            self.check_create_claim(claim)
            clock = _clock()
            _check_clock(clock)
            _require(
                _matches(request_sha256, _HEX)
                and _integer(dispatch_deadline_ns)
                and clock["boot_id"] == claim.boot_id
                and claim.created_monotonic_ns
                <= clock["monotonic_ns"]
                < dispatch_deadline_ns
                <= clock["monotonic_ns"] + 5000000000
            )
            value = {
                **self._base(claim, "create", None, clock),
                "request_sha256": request_sha256,
                "dispatch_deadline_ns": dispatch_deadline_ns,
            }
            with self._attempt_directory(claim.attempt_id) as directory:
                digest = _write_new(directory, "create.json", value, self._uid)
            fence = CreateFence(
                claim.attempt_id,
                claim.intent_sha256,
                digest,
                request_sha256,
                claim.boot_id,
                dispatch_deadline_ns,
            )
            self._create_fence, self._create_acknowledged = fence, digest
            try:
                self.check_create_fence(fence)
            except _ERRORS:
                self._create_fence = None
                self._create_acknowledged = None
                raise
            return fence

    def _acknowledged_create(self, attempt: Attempt) -> dict[str, Any]:
        _require(self._create_fence is not None and self._create_acknowledged is not None)
        with self._attempt_directory(attempt.attempt_id) as directory:
            value = self._receipt(directory, "create.json", attempt)
        fence = self._create_fence
        if fence is None:
            _deny()
        _require(
            hashlib.sha256(_canonical(value)).hexdigest()
            == self._create_acknowledged
            == fence.receipt_sha256
            and fence.attempt_id == attempt.attempt_id
            and fence.intent_sha256 == attempt.intent_sha256
            and value["request_sha256"] == fence.request_sha256
            and value["boot_id"] == fence.boot_id
            and value["dispatch_deadline_ns"] == fence.dispatch_deadline_ns
        )
        return value

    def check_create_fence(self, fence: CreateFence) -> None:
        with _sanitized():
            _require(type(fence) is CreateFence and self._create_fence is fence)
            attempt = self._owned()
            _require(not self._cid_record_issued and not self._start_issued)
            value = self._acknowledged_create(attempt)
            clock = _clock()
            _check_clock(clock)
            _require(
                clock["boot_id"] == fence.boot_id
                and value["monotonic_ns"] <= clock["monotonic_ns"] < fence.dispatch_deadline_ns
            )

    def _retirement_state(self) -> AttemptSnapshot:
        self._validate()
        _require(self._namespace["schema_version"] == 2)
        state = self.snapshot()
        if state is None:
            _deny()
        _require(
            (self._owned_attempt == state.attempt.attempt_id or self._recovery_only)
            and state.attempt.retirement_attempt_id is not None
            and state.create_sha256 is None
            and state.abandoned_sha256 is None
            and state.removed_sha256 is None
        )
        return state

    def prepare_removal(self) -> RemovalFence:
        with _sanitized():
            issued = self._removal_issued
            self._removal_issued = True
            self._removal_fence = None
            _require(not issued)
            state = self._retirement_state()
            attempt = state.attempt
            clock = _clock()
            _check_clock(clock)
            deadline = clock["monotonic_ns"] + 15000000000
            _require(_integer(deadline))
            with self._attempt_directory(attempt.attempt_id) as directory:
                if state.removal_intent_sha256 is None:
                    value = {
                        **self._base(attempt, "removal_intent", None, clock),
                        "target_attempt_id": attempt.retirement_attempt_id,
                        "target_container_id": attempt.retirement_container_id,
                        "target_stopped_sha256": attempt.retirement_stopped_sha256,
                    }
                    digest = _write_new(directory, "removal-intent.json", value, self._uid)
                else:
                    value = self._receipt(directory, "removal-intent.json", attempt)
                    digest = _reconfirm_durability(
                        directory, "removal-intent.json", value, self._uid
                    )
            if (
                attempt.retirement_attempt_id is None
                or attempt.retirement_container_id is None
                or attempt.retirement_stopped_sha256 is None
            ):
                _deny()
            fence = RemovalFence(
                attempt.attempt_id,
                attempt.intent_sha256,
                attempt.retirement_attempt_id,
                attempt.retirement_container_id,
                attempt.retirement_stopped_sha256,
                digest,
                clock["boot_id"],
                clock["monotonic_ns"],
                deadline,
            )
            self._removal_fence = fence
            try:
                self.check_removal_fence(fence)
            except _ERRORS:
                self._removal_fence = None
                raise
            return fence

    def _check_removal(self, fence: RemovalFence) -> None:
        state = self._retirement_state()
        attempt = state.attempt
        _require(
            state.removal_intent_sha256 == fence.removal_intent_sha256
            and attempt.attempt_id == fence.attempt_id
            and attempt.intent_sha256 == fence.intent_sha256
            and attempt.retirement_attempt_id == fence.target_attempt_id
            and attempt.retirement_container_id == fence.target_container_id
            and attempt.retirement_stopped_sha256 == fence.target_stopped_sha256
        )
        clock = _clock()
        _check_clock(clock)
        _require(
            clock["boot_id"] == fence.boot_id
            and fence.issued_monotonic_ns <= clock["monotonic_ns"] < fence.deadline_ns
        )

    def check_removal_fence(self, fence: RemovalFence) -> None:
        with _sanitized():
            _require(type(fence) is RemovalFence and self._removal_fence is fence)
            self._check_removal(fence)

    def check_removal_observation(self, fence: RemovalFence, raw: bytes) -> None:
        """Bind a fresh stopped observation to the retained predecessor lifetime."""
        with _sanitized():
            self.check_removal_fence(fence)
            target = self._history()[fence.target_attempt_id]
            _require(target.stopped_sha256 == fence.target_stopped_sha256)
            facts = _stopped(raw, target.attempt, fence.target_container_id)
            with self._attempt_directory(target.attempt.attempt_id) as directory:
                retained = self._receipt(directory, "stopped.json", target.attempt)
                _require(_exact({key: retained[key] for key in facts}, facts))
            self.check_removal_fence(fence)

    def record_removed(self, fence: RemovalFence, proof: RetirementProof) -> None:
        with _sanitized():
            issued = self._removal_fence
            self._removal_fence = None
            self._removed_acknowledged = None
            _require(type(fence) is RemovalFence and issued is fence)
            self._check_removal(fence)
            _require(
                type(proof) is RetirementProof
                and proof.fence is fence
                and proof.evidence_kind in ("delete_204", "inspect_404")
                and proof.boot_id == fence.boot_id
                and _integer(proof.observed_monotonic_ns)
            )
            clock = _clock()
            _check_clock(clock)
            _require(
                clock["boot_id"] == fence.boot_id
                and fence.issued_monotonic_ns
                <= proof.observed_monotonic_ns
                <= clock["monotonic_ns"]
                < fence.deadline_ns
            )
            attempt = self._active()
            if attempt is None:
                _deny()
            value = {
                **self._base(attempt, "removed", None, clock),
                "target_attempt_id": fence.target_attempt_id,
                "target_container_id": fence.target_container_id,
                "target_stopped_sha256": fence.target_stopped_sha256,
                "removal_intent_sha256": fence.removal_intent_sha256,
                "evidence_kind": proof.evidence_kind,
            }
            with self._attempt_directory(attempt.attempt_id) as directory:
                digest = _write_new(directory, "removed.json", value, self._uid)
            state = self.snapshot()
            _require(state is not None and state.removed_sha256 == digest)
            self._removed_acknowledged = digest

    def record_abandoned_before_dispatch(self) -> None:
        with _sanitized():
            self._burn_recovery()
            state = self.snapshot()
            if state is None:
                _deny()
            _require(
                state.attempt.schema_version == 2
                and state.create_sha256 is None
                and state.container_id is None
                and state.start_sha256 is None
                and state.stopped_sha256 is None
                and state.abandoned_sha256 is None
                and (
                    state.attempt.retirement_attempt_id is None or state.removed_sha256 is not None
                )
            )
            if state.removed_sha256 is not None:
                with self._attempt_directory(state.attempt.attempt_id) as directory:
                    removed = self._receipt(directory, "removed.json", state.attempt)
                    digest = _reconfirm_durability(directory, "removed.json", removed, self._uid)
                _require(digest == state.removed_sha256 and self.snapshot() == state)
            value = {
                **self._base(state.attempt, "abandoned_before_dispatch", None, _clock()),
                "removed_sha256": state.removed_sha256,
            }
            with self._attempt_directory(state.attempt.attempt_id) as directory:
                _write_new(directory, "abandoned.json", value, self._uid)
            self.snapshot()

    def acknowledge_abandoned_terminal(self) -> None:
        with _sanitized():
            self._terminal_acknowledged = None
            _require(not self._used_begin and not self._recovery_only)
            state = self.snapshot()
            if state is None or state.abandoned_sha256 is None:
                _deny()
            _require(
                self._entry_terminal
                == (
                    state.attempt.attempt_id,
                    state.attempt.intent_sha256,
                    "abandoned_before_dispatch",
                    state.abandoned_sha256,
                )
            )
            with self._attempt_directory(state.attempt.attempt_id) as directory:
                value = self._receipt(directory, "abandoned.json", state.attempt)
                digest = _reconfirm_durability(directory, "abandoned.json", value, self._uid)
            self._validate()
            _require(self.snapshot() == state and digest == state.abandoned_sha256)
            self._terminal_acknowledged = (state.attempt.attempt_id, digest)

    def record_created(self, verified: CreatedContainer) -> None:
        with _sanitized():
            self._create_claim = None
            attempt = self._owned()
            _require(not self._cid_record_issued)
            self._cid_record_issued = True
            self._created_acknowledged = None
            create = self._acknowledged_create(attempt)
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
            _require(
                all(
                    state.container_id != verified.container_id
                    for key, state in self._history().items()
                    if key != attempt.attempt_id
                )
            )
            value = self._base(attempt, "created", verified.container_id, _clock())
            _require(
                value["boot_id"] == attempt.boot_id
                and value["monotonic_ns"] >= create["monotonic_ns"]
            )
            with self._attempt_directory(attempt.attempt_id) as directory:
                digest = _write_new(directory, "created.json", value, self._uid)
            self._validate()
            self._created_acknowledged = digest

    def prepare_start(self) -> StartFence:
        with _sanitized():
            self._start_fence = None
            self._start_acknowledged = None
            attempt = self._owned()
            self._acknowledged_create(attempt)
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
                digest = _write_new(directory, "start.json", value, self._uid)
            self._validate()
            now = _clock()
            _check_clock(now)
            _require(
                now["boot_id"] == attempt.boot_id
                and clock["monotonic_ns"] <= now["monotonic_ns"] < deadline
            )
            fence = StartFence(
                attempt.attempt_id,
                created["container_id"],
                attempt.boot_id,
                clock["monotonic_ns"],
                deadline,
            )
            self._start_acknowledged = digest
            self._start_fence = fence
            return fence

    def check_start_fence(self, fence: StartFence) -> None:
        """Recheck the exact issued fence and acknowledged bytes before dispatch."""
        with _sanitized():
            _require(type(fence) is StartFence and self._start_fence is fence)
            attempt = self._owned()
            self._acknowledged_create(attempt)
            _require(
                self._start_issued
                and self._created_acknowledged is not None
                and self._start_acknowledged is not None
                and fence.attempt_id == attempt.attempt_id
            )
            with self._attempt_directory(attempt.attempt_id) as directory:
                created = self._created_and_start(directory, attempt)
                _require(created is not None)
                start = self._receipt(directory, "start.json", attempt)
                _require(
                    hashlib.sha256(_canonical(created)).hexdigest() == self._created_acknowledged
                    and hashlib.sha256(_canonical(start)).hexdigest() == self._start_acknowledged
                )
                _require(
                    start["container_id"] == fence.container_id
                    and start["boot_id"] == fence.boot_id
                    and start["monotonic_ns"] == fence.start_monotonic_ns
                    and start["term_deadline_ns"] == fence.term_deadline_ns
                )
            self._validate()
            clock = _clock()
            _check_clock(clock)
            _require(
                clock["boot_id"] == fence.boot_id
                and fence.start_monotonic_ns <= clock["monotonic_ns"] < fence.term_deadline_ns
            )

    def record_stopped(self, raw: bytes) -> dict[str, Any]:
        with _sanitized():
            if self._entry_unfinished:
                self._burn_recovery()
            self._create_claim = None
            self._create_fence = None
            self._create_acknowledged = None
            self._start_fence = None
            self._start_acknowledged = None
            self._created_acknowledged = None
            self._terminal_acknowledged = None
            self._start_issued = True
            self._validate()
            self._history()
            attempt = self._active()
            if attempt is None:
                _deny()
            with self._attempt_directory(attempt.attempt_id) as directory:
                known_created = self._created_and_start(directory, attempt)
                expected_cid = known_created["container_id"] if known_created is not None else None
                facts = _stopped(raw, attempt, expected_cid)
                has_start = _exists(directory, "start.json")
                # A queued/uncertain START may still act on a presently created container.
                _require(facts["status"] != "created" or not has_start)
                if _exists(directory, "stopped.json"):
                    value = self._receipt(directory, "stopped.json", attempt)
                    _require(_exact({key: value[key] for key in facts}, facts))
                    _require(value["start_fence_present"] is has_start)
                    digest = _reconfirm_durability(directory, "stopped.json", value, self._uid)
                else:
                    value = {
                        **self._base(attempt, "stopped", facts.pop("container_id"), _clock()),
                        **facts,
                        "start_fence_present": has_start,
                    }
                    digest = _write_new(directory, "stopped.json", value, self._uid)
                self._receipt(directory, "stopped.json", attempt)
            self._validate()
            _require(self.snapshot() is not None)
            if not self._recovery_only and not self._used_begin:
                _require(
                    self._entry_terminal
                    == (attempt.attempt_id, attempt.intent_sha256, "stopped", digest)
                )
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
            entry = store.snapshot()
            store._entry_unfinished = entry is not None and (
                entry.stopped_sha256 is None and entry.abandoned_sha256 is None
            )
            if entry is not None and not store._entry_unfinished:
                kind = (
                    "stopped" if entry.stopped_sha256 is not None else "abandoned_before_dispatch"
                )
                digest = entry.stopped_sha256 or entry.abandoned_sha256
                if digest is None:
                    _deny()
                store._entry_terminal = (
                    entry.attempt.attempt_id,
                    entry.attempt.intent_sha256,
                    kind,
                    digest,
                )
            if namespace["schema_version"] == 2 and not store._entry_unfinished:
                store._used_begin = False
            else:
                store._burn_recovery()
            yield store
        finally:
            if store is not None:
                store._closed = True
            _close_all(fd for fd in (lock, directory) if fd is not None)


def operations() -> AbstractContextManager[AttemptStore]:
    """Fixed production namespace; private fixture helper cannot select runtime paths."""
    _require(os.geteuid() == 0)
    return _open_operations(OPERATIONS_ROOT, trusted_uid=0)
