"""Dedicated private probe persistence foundation; no worker or Engine authority.

The namespace opener validates complete bounded retained history. The setup and
CREATE/CID/prestart/START prefix has durable one-use fences; STOP/output/retirement
and native controller paths remain incomplete. Readable bytes are not a durable
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
from itertools import pairwise
from pathlib import Path
from typing import Any, NoReturn, cast

from infra.hybrid.stock_attempts import (
    _canonical,
    _check_clock,
    _clock,
    _integer,
    _read,
    _reconfirm_durability,
    _write_new,
)
from infra.hybrid.stock_container import ImageProfile, _object, verify_engine_version, verify_image
from infra.hybrid.stock_prestart import verify_creation
from infra.hybrid.stock_probe_observation import ProbeObservation, _lifetime, observe_probe
from infra.hybrid.stock_probe_output import decode_probe_output
from infra.hybrid.stock_probe_profile import CreatedProbe, probe_request, verify_probe_created
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
    "discovery.bin": 1048576,
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


@contextmanager
def _open_namespace(root: Path, *, trusted_uid: int) -> Iterator[ProbeStore]:
    """Classify the complete locked entry once; no restart reconstructs dispatch."""
    with _sanitized():
        _path(root, trusted_uid)
        directory = _open_directory(
            root,
            trusted_uid=trusted_uid,
            release_root=Path("/") if root == PROBES_ROOT else root,
        )
        lock: int | None = None
        store: ProbeStore | None = None
        try:
            _directory_info(os.fstat(directory), trusted_uid)
            lock = os.open(
                "launcher.lock",
                os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=directory,
            )
            _file_info(os.fstat(lock), trusted_uid, low=0, high=0)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            value, _ = _read(directory, "namespace.json", trusted_uid)
            _validate_namespace(value, os.fstat(directory), os.fstat(lock))
            _require(
                _fingerprint(os.fstat(lock))
                == _fingerprint(os.stat("launcher.lock", dir_fd=directory, follow_symlinks=False))
            )
            store = ProbeStore(root, directory, lock, trusted_uid, value)
            entry = store.snapshot()
            store._entry_snapshot = entry
            store._recovery_only = entry is not None and entry.closed_outcome is None
            yield store
        finally:
            if store is not None:
                store._closed = True
            _close_all(fd for fd in (lock, directory) if fd is not None)


def initialize_probes() -> None:
    """Explicit fixed-root initialization; never invoked by an operator probe run."""
    with _sanitized():
        _require(sys.platform == "linux" and os.geteuid() == 0)
        _initialize(PROBES_ROOT, trusted_uid=0)


def probes() -> AbstractContextManager[ProbeStore]:
    """Fixed production path/UID; no caller-selected alternate namespace."""
    with _sanitized():
        _require(sys.platform == "linux" and os.geteuid() == 0)
        return _open_namespace(PROBES_ROOT, trusted_uid=0)


_COMMON_KEYS = {
    "schema_version",
    "kind",
    "namespace_id",
    "probe_id",
    "intent_sha256",
    "boot_id",
    "utc",
    "monotonic_ns",
}
_RECEIPT_KEYS = {
    "intent.json": {
        "profile_version",
        "image_digest",
        "engine_sha256",
        "engine_size",
        "image_sha256",
        "image_size",
        "request_sha256",
        "request_size",
        "setup_started_ns",
        "setup_deadline_ns",
        "predecessor_probe_id",
        "predecessor_closed_sha256",
    },
    "create.json": {"request_sha256", "dispatch_deadline_ns"},
    "cid.json": {
        "create_sha256",
        "container_id",
        "evidence_kind",
        "observation_sha256",
        "observation_size",
    },
    "created.json": {"cid_sha256", "prestart_sha256", "prestart_size"},
    "start.json": {"created_sha256", "container_id", "run_deadline_ns"},
    "stopped.json": {
        "container_id",
        "start_sha256",
        "inspection_sha256",
        "inspection_size",
        "status",
        "exit_code",
        "oom_killed",
        "error_present",
        "container_started_at",
        "container_finished_at",
    },
    "output.json": {
        "stopped_sha256",
        "framed_sha256",
        "framed_size",
        "status",
        "canonical_sha256",
        "canonical_size",
    },
    "removal-intent.json": {"container_id", "stopped_sha256", "retirement_deadline_ns"},
    "removed.json": {"removal_intent_sha256", "evidence_kind"},
    "closed.json": {"outcome", "reason", "output_sha256", "removed_sha256"},
}
_FAILED_REASONS = {
    "setup_failed",
    "prestart_failed",
    "start_uncertain",
    "process_failed",
    "run_expired",
    "shutdown",
    "invalid_output",
    "recovery",
}


def _matches(value: Any, pattern: str) -> bool:
    return type(value) is str and re.fullmatch(pattern, value) is not None


def _hash(value: Any) -> bool:
    return _matches(value, r"[0-9a-f]{64}")


def _nullable_hash(value: Any) -> bool:
    return value is None or _hash(value)


def _blob(value: dict[str, Any], prefix: str, high: int, *, low: int = 1) -> None:
    _require(_hash(value[prefix + "_sha256"]) and _integer(value[prefix + "_size"], low, high))


def _decode_receipt(
    raw: bytes, name: str, *, namespace_id: str, probe_id: str, intent_sha256: str | None
) -> dict[str, Any]:
    """Validate canonical supplied receipt bytes, never dispatch/durability authority."""
    with _sanitized():
        _require(type(name) is str and name in _RECEIPT_KEYS)
        _require(_matches(namespace_id, r"[0-9a-f]{32}") and _matches(probe_id, r"[0-9a-f]{32}"))
        _require(intent_sha256 is None if name == "intent.json" else _hash(intent_sha256))
        _require(type(raw) is bytes and 0 < len(raw) <= 4096)
        value = _object(raw)
        _require(_canonical(value) == raw and set(value) == _COMMON_KEYS | _RECEIPT_KEYS[name])
        _require(type(value["schema_version"]) is int and value["schema_version"] == 1)
        _require(value["kind"] == "stock_probe_" + name.removesuffix(".json").replace("-", "_"))
        _require(value["namespace_id"] == namespace_id and value["probe_id"] == probe_id)
        _require(value["intent_sha256"] == intent_sha256)
        _check_clock(value)
        if name == "intent.json":
            _require(type(value["profile_version"]) is int and value["profile_version"] == 1)
            _require(_matches(value["image_digest"], r"sha256:[0-9a-f]{64}"))
            for prefix in ("engine", "image", "request"):
                _blob(value, prefix, 1048576)
            _require(
                _integer(value["setup_started_ns"], 1) and _integer(value["setup_deadline_ns"], 1)
            )
            _require(value["setup_deadline_ns"] == value["setup_started_ns"] + 20000000000)
            _require(
                value["setup_started_ns"] <= value["monotonic_ns"] < value["setup_deadline_ns"]
            )
            predecessor, closed = value["predecessor_probe_id"], value["predecessor_closed_sha256"]
            _require(
                (predecessor is None and closed is None)
                or (
                    _matches(predecessor, r"[0-9a-f]{32}")
                    and predecessor != probe_id
                    and _hash(closed)
                )
            )
        elif name == "create.json":
            _require(_hash(value["request_sha256"]) and _integer(value["dispatch_deadline_ns"], 1))
            _require(
                value["monotonic_ns"]
                < value["dispatch_deadline_ns"]
                <= value["monotonic_ns"] + 5000000000
            )
        elif name == "cid.json":
            _require(_hash(value["create_sha256"]) and _hash(value["container_id"]))
            _require(value["evidence_kind"] in ("create_response", "name_inspection"))
            _blob(
                value,
                "observation",
                4096 if value["evidence_kind"] == "create_response" else 1048576,
            )
        elif name == "created.json":
            _require(_hash(value["cid_sha256"]))
            _blob(value, "prestart", 1048576)
        elif name == "start.json":
            _require(_hash(value["created_sha256"]) and _hash(value["container_id"]))
            _require(
                _integer(value["run_deadline_ns"], 1)
                and value["run_deadline_ns"] == value["monotonic_ns"] + 30000000000
            )
        elif name == "stopped.json":
            _require(_hash(value["container_id"]) and _nullable_hash(value["start_sha256"]))
            _blob(value, "inspection", 1048576)
            _require(
                value["status"] in ("created", "exited", "dead")
                and _integer(value["exit_code"], 0, 255)
            )
            _require(type(value["oom_killed"]) is bool and type(value["error_present"]) is bool)
            started, finished = (
                _lifetime(value["container_started_at"]),
                _lifetime(value["container_finished_at"]),
            )
            if value["status"] == "created":
                _require(value["start_sha256"] is None and started == "0001-01-01T00:00:00Z")
            elif value["status"] == "exited":
                _require(started != "0001-01-01T00:00:00Z" and finished != "0001-01-01T00:00:00Z")
        elif name == "output.json":
            _require(_hash(value["stopped_sha256"]))
            _blob(value, "framed", 16384, low=0)
            _require(value["status"] in ("valid", "invalid"))
            if value["status"] == "valid":
                _blob(value, "canonical", 4096)
            else:
                _require(value["canonical_sha256"] is None and value["canonical_size"] is None)
        elif name == "removal-intent.json":
            _require(_hash(value["container_id"]) and _hash(value["stopped_sha256"]))
            _require(
                _integer(value["retirement_deadline_ns"], 1)
                and value["retirement_deadline_ns"] == value["monotonic_ns"] + 15000000000
            )
        elif name == "removed.json":
            _require(
                _hash(value["removal_intent_sha256"])
                and value["evidence_kind"] in ("delete_204", "inspect_404")
            )
        else:
            _require(value["outcome"] in ("succeeded", "failed", "abandoned_before_create"))
            _require(
                _nullable_hash(value["output_sha256"]) and _nullable_hash(value["removed_sha256"])
            )
            if value["outcome"] == "succeeded":
                _require(
                    value["reason"] == "completed"
                    and _hash(value["output_sha256"])
                    and _hash(value["removed_sha256"])
                )
            elif value["outcome"] == "failed":
                _require(value["reason"] in _FAILED_REASONS and _hash(value["removed_sha256"]))
            else:
                _require(
                    value["reason"] == "abandoned_before_create"
                    and value["output_sha256"] is None
                    and value["removed_sha256"] is None
                )
        return dict(value)


@dataclass(frozen=True, slots=True)
class ProbeSnapshot:
    """Copied retained facts. No acknowledgement, dispatch or publication authority."""

    probe_id: str
    intent_sha256: str
    image_digest: str
    boot_id: str
    setup_started_ns: int
    setup_deadline_ns: int
    container_id: str | None
    run_started_ns: int | None
    run_deadline_ns: int | None
    stopped: ProbeObservation | None
    output_status: str | None
    closed_outcome: str | None
    receipt_hashes: tuple[tuple[str, str], ...]


@dataclass(slots=True)
class _Node:
    snapshot: ProbeSnapshot
    records: dict[str, dict[str, Any]]
    hashes: dict[str, str]
    image: ImageProfile


def _native_key(timestamp: str) -> tuple[str, str]:
    # _lifetime validated RFC3339Nano first. Preserve nanoseconds for success checks.
    return timestamp[:19], timestamp[20:-1].ljust(9, "0") if timestamp[19] == "." else "000000000"


@dataclass(frozen=True, slots=True)
class ProbeSetup:
    probe_id: str
    image_digest: str
    boot_id: str
    started_ns: int
    deadline_ns: int
    predecessor_container_id: str | None


@dataclass(frozen=True, slots=True)
class ProbeCreateFence:
    probe_id: str
    intent_sha256: str
    receipt_sha256: str
    request_sha256: str
    boot_id: str
    issued_ns: int
    deadline_ns: int


@dataclass(frozen=True, slots=True)
class ProbeStartFence:
    probe_id: str
    intent_sha256: str
    container_id: str
    receipt_sha256: str
    boot_id: str
    started_ns: int
    run_deadline_ns: int
    dispatch_deadline_ns: int


def _clock_key(utc: str) -> tuple[str, str]:
    match = re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.([0-9]{1,9}))?(?:Z|\+00:00)",
        utc,
    )
    if match is None:
        _deny()
    return utc[:19], (match[1] or "").ljust(9, "0")


def _reconfirm_bytes(directory: int, name: str, raw: bytes, uid: int) -> None:
    """Fresh unchanged-byte flush/readback, never inferred from content caching."""
    with _sanitized():
        low, high = _slot(name)
        _require(type(raw) is bytes and low <= len(raw) <= high)
        descriptor = os.open(name, _READ, dir_fd=directory)
        try:
            before = os.fstat(descriptor)
            _file_info(before, uid, low=low, high=high)
            _require(_read_bytes(directory, name, uid) == raw)
            os.fsync(descriptor)
            _require(_fingerprint(before) == _fingerprint(os.fstat(descriptor)))
            _require(
                _fingerprint(before)
                == _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False))
            )
        finally:
            _close_all((descriptor,))
        os.fsync(directory)
        _require(_read_bytes(directory, name, uid) == raw)


class ProbeStore:
    """Root-private admission/dispatch sequencing; no Engine or live capability."""

    def __init__(self, root: Path, directory: int, lock: int, uid: int, namespace: dict[str, Any]):
        self._root, self._directory, self._lock, self._uid = root, directory, lock, uid
        self._namespace = dict(namespace)
        self._closed = False
        self._recovery_only = True
        self._entry_snapshot: ProbeSnapshot | None = None
        self._content = _ContentCache()
        self._nodes: dict[str, tuple[tuple[int, ...], dict[str, tuple[int, ...]], _Node]] = {}
        self._last_clock: dict[str, Any] | None = None
        self._setup_issued = False
        self._begin_issued = False
        self._setup_token: ProbeSetup | None = None
        self._owned_id: str | None = None
        self._owned_intent: str | None = None
        self._create_issued = False
        self._create_dispatched = False
        self._create_token: ProbeCreateFence | None = None
        self._create_ack: str | None = None
        self._cid_issued = False
        self._cid_ack: str | None = None
        self._created_issued = False
        self._created_ack: str | None = None
        self._start_issued = False
        self._start_dispatched = False
        self._start_token: ProbeStartFence | None = None
        self._start_ack: str | None = None

    @property
    def namespace_id(self) -> str:
        return str(self._namespace["namespace_id"])

    @property
    def recovery_only(self) -> bool:
        return self._recovery_only

    def _guard(self) -> None:
        _require(not self._closed and os.geteuid() == self._uid)
        _directory_info(os.fstat(self._directory), self._uid)
        _file_info(os.fstat(self._lock), self._uid, low=0, high=0)
        _require(
            _fingerprint(os.fstat(self._lock))
            == _fingerprint(os.stat("launcher.lock", dir_fd=self._directory, follow_symlinks=False))
        )
        value, _ = _read(self._directory, "namespace.json", self._uid)
        _validate_namespace(value, os.fstat(self._directory), os.fstat(self._lock))
        _require(value == self._namespace)
        current = _open_directory(
            self._root,
            trusted_uid=self._uid,
            release_root=Path("/") if self._root == PROBES_ROOT else self._root,
        )
        try:
            info = os.fstat(current)
            _directory_info(info, self._uid)
            _require((info.st_dev, info.st_ino) == (value["root_device"], value["root_inode"]))
        finally:
            _close_all((current,))

    @contextmanager
    def _folder(self, probe_id: str) -> Iterator[int]:
        _require(_matches(probe_id, r"[0-9a-f]{32}"))
        descriptor = os.open(probe_id, _DIRECTORY, dir_fd=self._directory)
        try:
            _directory_info(os.fstat(descriptor), self._uid)
            yield descriptor
            _require(
                _fingerprint(os.fstat(descriptor))
                == _fingerprint(os.stat(probe_id, dir_fd=self._directory, follow_symlinks=False))
            )
        finally:
            _close_all((descriptor,))

    def _node(self, probe_id: str) -> _Node:
        with self._folder(probe_id) as directory:
            names = set(os.listdir(directory))
            _require("intent.json" in names and names <= set(_RECEIPT_KEYS) | set(_SLOTS))
            stamps = {}
            for name in names:
                info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                low, high = _slot(name) if name in _SLOTS else (1, 4096)
                _file_info(info, self._uid, low=low, high=high)
                stamps[name] = _fingerprint(info)
            parent = _fingerprint(os.fstat(directory))
            cached = self._nodes.get(probe_id)
            if cached is not None and cached[0] == parent and cached[1] == stamps:
                _require(set(os.listdir(directory)) == names)
                _require(_fingerprint(os.fstat(directory)) == parent)
                return cached[2]
            intent, intent_hash = _read(directory, "intent.json", self._uid)
            intent = _decode_receipt(
                _canonical(intent),
                "intent.json",
                namespace_id=self.namespace_id,
                probe_id=probe_id,
                intent_sha256=None,
            )
            records, hashes = {"intent.json": intent}, {"intent.json": intent_hash}
            for name in _RECEIPT_KEYS:
                if name in names and name != "intent.json":
                    value, digest = _read(directory, name, self._uid)
                    records[name] = _decode_receipt(
                        _canonical(value),
                        name,
                        namespace_id=self.namespace_id,
                        probe_id=probe_id,
                        intent_sha256=intent_hash,
                    )
                    hashes[name] = digest
            artifacts = {
                name: self._content.read(directory, name, self._uid) for name in names & set(_SLOTS)
            }
            node = self._bind_node(probe_id, records, hashes, artifacts)
            # A node caches validated facts under exact named-file fingerprints.
            # Original payloads stay on disk; do not accumulate hundreds of MiB
            # across retained history on the intended small host.
            self._content = _ContentCache()
            _require(
                stamps
                == {
                    name: _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False))
                    for name in names
                }
            )
            _require(set(os.listdir(directory)) == names)
            _require(_fingerprint(os.fstat(directory)) == parent)
            self._nodes[probe_id] = (parent, stamps, node)
            return node

    def _bind_node(
        self,
        probe_id: str,
        records: dict[str, dict[str, Any]],
        hashes: dict[str, str],
        artifacts: dict[str, bytes],
    ) -> _Node:
        intent = records["intent.json"]
        expected = {"engine.bin", "image.bin", "request.bin"}

        def artifact(slot: str, receipt: dict[str, Any], prefix: str) -> bytes:
            _require(slot in artifacts)
            raw = artifacts[slot]
            _require(
                len(raw) == receipt[prefix + "_size"]
                and hashlib.sha256(raw).hexdigest() == receipt[prefix + "_sha256"]
            )
            expected.add(slot)
            return raw

        engine_raw, image_raw = (
            artifact("engine.bin", intent, "engine"),
            artifact("image.bin", intent, "image"),
        )
        image = verify_image(image_raw, intent["image_digest"], verify_engine_version(engine_raw))
        _require(artifact("request.bin", intent, "request") == probe_request(image, probe_id))
        create, cid, created, start, stopped, output, removal, removed, closed = (
            records.get(name + ".json")
            for name in (
                "create",
                "cid",
                "created",
                "start",
                "stopped",
                "output",
                "removal-intent",
                "removed",
                "closed",
            )
        )
        if create is not None:
            _require(
                create["request_sha256"] == intent["request_sha256"]
                and create["boot_id"] == intent["boot_id"]
            )
            _require(
                intent["monotonic_ns"]
                <= create["monotonic_ns"]
                < create["dispatch_deadline_ns"]
                <= intent["setup_deadline_ns"]
            )
        container_id = None
        if cid is not None:
            if create is None:
                _deny()
            _require(cid["create_sha256"] == hashes["create.json"])
            container_id = str(cid["container_id"])
            slot = (
                "create-response.bin"
                if cid["evidence_kind"] == "create_response"
                else "discovery.bin"
            )
            raw = artifact(slot, cid, "observation")
            if cid["evidence_kind"] == "create_response":
                _require(
                    verify_creation(raw) == container_id and cid["boot_id"] == intent["boot_id"]
                )
                _require(cid["monotonic_ns"] >= create["monotonic_ns"])
            else:
                observe_probe(
                    raw,
                    probe_id=probe_id,
                    container_id=container_id,
                    image_digest=intent["image_digest"],
                )
                _require(created is None and start is None)
        if created is not None:
            if cid is None or container_id is None:
                _deny()
            _require(
                cid["evidence_kind"] == "create_response"
                and created["cid_sha256"] == hashes["cid.json"]
            )
            raw = artifact("prestart.bin", created, "prestart")
            verify_probe_created(raw, image=image, probe_id=probe_id, container_id=container_id)
            _require(
                created["boot_id"] == intent["boot_id"]
                and created["monotonic_ns"] >= cid["monotonic_ns"]
            )
        if start is not None:
            if created is None:
                _deny()
            _require(
                start["created_sha256"] == hashes["created.json"]
                and start["container_id"] == container_id
            )
            _require(
                start["boot_id"] == intent["boot_id"]
                and created["monotonic_ns"] <= start["monotonic_ns"] < intent["setup_deadline_ns"]
            )
        observation = None
        if stopped is not None:
            if cid is None or container_id is None:
                _deny()
            _require(
                stopped["container_id"] == container_id
                and stopped["start_sha256"] == hashes.get("start.json")
            )
            raw = artifact("stopped.bin", stopped, "inspection")
            observation = observe_probe(
                raw,
                probe_id=probe_id,
                container_id=container_id,
                image_digest=intent["image_digest"],
            )
            _require(observation.status in ("created", "exited", "dead"))
            for field in (
                "status",
                "exit_code",
                "oom_killed",
                "error_present",
                "container_started_at",
                "container_finished_at",
            ):
                _require(stopped[field] == getattr(observation, field))
            _require(observation.status != "created" or start is None)
        if output is not None:
            _require(stopped is not None and output["stopped_sha256"] == hashes["stopped.json"])
            raw = artifact("framed-logs.bin", output, "framed")
            try:
                canonical = decode_probe_output(raw)
            except ValueError:
                canonical = None
            if output["status"] == "valid":
                _require(
                    canonical is not None
                    and artifact("configuration.bin", output, "canonical") == canonical
                )
            else:
                _require(canonical is None)
        if removal is not None:
            _require(
                stopped is not None
                and removal["container_id"] == container_id
                and removal["stopped_sha256"] == hashes["stopped.json"]
            )
        if removed is not None:
            _require(
                removal is not None
                and removed["removal_intent_sha256"] == hashes["removal-intent.json"]
            )
        if closed is not None:
            _require(
                closed["output_sha256"] == hashes.get("output.json")
                and closed["removed_sha256"] == hashes.get("removed.json")
            )
            if closed["outcome"] == "abandoned_before_create":
                _require(set(records) == {"intent.json", "closed.json"})
            else:
                _require(removed is not None)
                if closed["outcome"] == "succeeded":
                    _require(
                        set(records) == set(_RECEIPT_KEYS)
                        and output is not None
                        and output["status"] == "valid"
                    )
                    # Exact complete record membership above and the mandatory
                    # stopped binding establish these types; casts add no authority.
                    observation = cast(ProbeObservation, observation)
                    output, stopped, start, removal = (
                        records[name]
                        for name in (
                            "output.json",
                            "stopped.json",
                            "start.json",
                            "removal-intent.json",
                        )
                    )
                    _require(
                        observation.status == "exited"
                        and observation.exit_code == 0
                        and not observation.oom_killed
                        and not observation.error_present
                    )
                    _require(
                        _native_key(observation.container_finished_at)
                        >= _native_key(observation.container_started_at)
                    )
                    ordered = [records[name] for name in _RECEIPT_KEYS]
                    _require(all(record["boot_id"] == intent["boot_id"] for record in ordered))
                    _require(
                        all(
                            left["monotonic_ns"] <= right["monotonic_ns"]
                            for left, right in pairwise(ordered)
                        )
                    )
                    _require(
                        start is not None
                        and stopped is not None
                        and stopped["monotonic_ns"] < start["run_deadline_ns"]
                    )
                    _require(output["monotonic_ns"] < stopped["monotonic_ns"] + 5000000000)
                    _require(
                        removal is not None
                        and closed["monotonic_ns"] < removal["retirement_deadline_ns"]
                    )
        _require(set(artifacts) == expected)
        snapshot = ProbeSnapshot(
            probe_id,
            hashes["intent.json"],
            intent["image_digest"],
            intent["boot_id"],
            intent["setup_started_ns"],
            intent["setup_deadline_ns"],
            container_id,
            None if start is None else start["monotonic_ns"],
            None if start is None else start["run_deadline_ns"],
            observation,
            None if output is None else output["status"],
            None if closed is None else closed["outcome"],
            tuple(sorted(hashes.items())),
        )
        return _Node(snapshot, records, hashes, image)

    def _history(self) -> list[_Node]:
        self._guard()
        names = set(os.listdir(self._directory))
        _require(len(names) <= 131)
        identifiers = names - {"namespace.json", "launcher.lock", "active.json"}
        _require(
            all(_matches(name, r"[0-9a-f]{32}") for name in identifiers) and len(identifiers) <= 128
        )
        if "active.json" not in names:
            _require(not identifiers)
            return []
        head, _ = _read(self._directory, "active.json", self._uid)
        _require(
            set(head) == {"schema_version", "kind", "namespace_id", "probe_id", "intent_sha256"}
        )
        _require(
            type(head["schema_version"]) is int
            and head["schema_version"] == 1
            and head["kind"] == "stock_probe_active"
        )
        _require(
            head["namespace_id"] == self.namespace_id
            and _matches(head["probe_id"], r"[0-9a-f]{32}")
            and _hash(head["intent_sha256"])
        )
        nodes = {probe_id: self._node(probe_id) for probe_id in identifiers}
        _require(
            head["probe_id"] in nodes
            and nodes[head["probe_id"]].snapshot.intent_sha256 == head["intent_sha256"]
        )
        seen, cids, ordered = set(), set(), []
        current = head["probe_id"]
        while current is not None:
            _require(current in nodes and current not in seen)
            seen.add(current)
            node = nodes[current]
            cid = node.snapshot.container_id
            _require(cid is None or cid not in cids)
            if cid is not None:
                cids.add(cid)
            ordered.append(node)
            intent = node.records["intent.json"]
            predecessor = intent["predecessor_probe_id"]
            if predecessor is not None:
                _require(predecessor in nodes)
                prior = nodes[predecessor]
                _require(
                    prior.snapshot.closed_outcome is not None
                    and prior.hashes.get("closed.json") == intent["predecessor_closed_sha256"]
                )
            current = predecessor
        _require(seen == identifiers)
        self._guard()
        _require(set(os.listdir(self._directory)) == names)
        return list(reversed(ordered))

    def snapshot(self) -> ProbeSnapshot | None:
        with _sanitized():
            history = self._history()
            return None if not history else history[-1].snapshot

    def _now(self) -> dict[str, Any]:
        value = _clock()
        _check_clock(value)
        key = _clock_key(value["utc"])
        previous = self._last_clock
        self._last_clock = dict(value)
        if previous is not None and (
            value["boot_id"] != previous["boot_id"]
            or value["monotonic_ns"] < previous["monotonic_ns"]
            or key < _clock_key(previous["utc"])
        ):
            self._recovery_only = True
            self._create_ack = self._created_ack = self._start_ack = None
            _deny()
        return value

    def _window(self, boot_id: str, deadline_ns: int) -> dict[str, Any]:
        now = self._now()
        _require(now["boot_id"] == boot_id and now["monotonic_ns"] < deadline_ns)
        return now

    def _normal(self) -> None:
        _require(not self._closed and not self._recovery_only)

    def begin_setup(self, image_digest: str) -> ProbeSetup:
        with _sanitized():
            _require(not self._setup_issued)
            self._setup_issued = True
            self._setup_token = None
            self._normal()
            origin = self._now()
            _require(_matches(image_digest, r"sha256:[0-9a-f]{64}"))
            history = self._history()
            entry = None if not history else history[-1].snapshot
            _require(
                entry == self._entry_snapshot
                and (entry is None or entry.closed_outcome is not None)
            )
            if history:
                closed = history[-1].records["closed.json"]
                if closed["boot_id"] == origin["boot_id"] and (
                    origin["monotonic_ns"] < closed["monotonic_ns"]
                    or _clock_key(origin["utc"]) < _clock_key(closed["utc"])
                ):
                    self._recovery_only = True
                    _deny()
            probe_id = secrets.token_hex(16)
            _require(
                _matches(probe_id, r"[0-9a-f]{32}")
                and all(node.snapshot.probe_id != probe_id for node in history)
            )
            _require(len(history) < 128)
            deadline = origin["monotonic_ns"] + 20000000000
            _require(_integer(deadline, 1))
            self._window(origin["boot_id"], deadline)
            token = ProbeSetup(
                probe_id,
                image_digest,
                origin["boot_id"],
                origin["monotonic_ns"],
                deadline,
                None if entry is None else entry.container_id,
            )
            self._setup_token = token
            return token

    def check_setup(self, token: ProbeSetup) -> None:
        with _sanitized():
            self._normal()
            _require(token is self._setup_token and type(token) is ProbeSetup)
            self._guard()
            self._window(token.boot_id, token.deadline_ns)

    def _flush_entry(self, token: ProbeSetup, history: list[_Node]) -> None:
        self.check_setup(token)
        _reconfirm_durability(self._directory, "namespace.json", self._namespace, self._uid)
        os.fsync(self._lock)
        for node in history:
            with self._folder(node.snapshot.probe_id) as directory:
                for name in sorted(os.listdir(directory)):
                    self.check_setup(token)
                    if name in node.records:
                        _reconfirm_durability(directory, name, node.records[name], self._uid)
                    else:
                        _reconfirm_bytes(
                            directory, name, _read_bytes(directory, name, self._uid), self._uid
                        )
                    self.check_setup(token)
        if history:
            head, _ = _read(self._directory, "active.json", self._uid)
            _reconfirm_durability(self._directory, "active.json", head, self._uid)
        os.fsync(self._directory)
        parent = _open_directory(
            self._root.parent,
            trusted_uid=self._uid,
            release_root=Path("/") if self._root == PROBES_ROOT else self._root.parent,
        )
        try:
            os.fsync(parent)
        finally:
            _close_all((parent,))
        self.check_setup(token)

    def begin(self, token: ProbeSetup, engine_raw: bytes, image_raw: bytes) -> ProbeSnapshot:
        with _sanitized():
            _require(not self._begin_issued)
            self._begin_issued = True
            self._owned_id = self._owned_intent = None
            self.check_setup(token)
            history = self._history()
            entry = None if not history else history[-1].snapshot
            _require(entry == self._entry_snapshot)
            # The later closed-CID recovery transport must supply fresh absence
            # evidence. This incomplete prefix deliberately cannot bypass it.
            _require(token.predecessor_container_id is None)
            image = verify_image(image_raw, token.image_digest, verify_engine_version(engine_raw))
            request = probe_request(image, token.probe_id)
            self._flush_entry(token, history)
            stamp = self._window(token.boot_id, token.deadline_ns)
            intent = {
                "schema_version": 1,
                "kind": "stock_probe_intent",
                "namespace_id": self.namespace_id,
                "probe_id": token.probe_id,
                "intent_sha256": None,
                **stamp,
                "profile_version": 1,
                "image_digest": token.image_digest,
                "engine_sha256": hashlib.sha256(engine_raw).hexdigest(),
                "engine_size": len(engine_raw),
                "image_sha256": hashlib.sha256(image_raw).hexdigest(),
                "image_size": len(image_raw),
                "request_sha256": hashlib.sha256(request).hexdigest(),
                "request_size": len(request),
                "setup_started_ns": token.started_ns,
                "setup_deadline_ns": token.deadline_ns,
                "predecessor_probe_id": None if entry is None else entry.probe_id,
                "predecessor_closed_sha256": None
                if not history
                else history[-1].hashes["closed.json"],
            }
            _decode_receipt(
                _canonical(intent),
                "intent.json",
                namespace_id=self.namespace_id,
                probe_id=token.probe_id,
                intent_sha256=None,
            )
            os.mkdir(token.probe_id, 0o700, dir_fd=self._directory)
            directory = os.open(token.probe_id, _DIRECTORY, dir_fd=self._directory)
            try:
                _directory_info(os.fstat(directory), self._uid)
                for name, raw in (
                    ("engine.bin", engine_raw),
                    ("image.bin", image_raw),
                    ("request.bin", request),
                ):
                    self.check_setup(token)
                    _write_bytes(directory, name, raw, self._uid)
                    self.check_setup(token)
                digest = _write_new(directory, "intent.json", intent, self._uid)
            finally:
                _close_all((directory,))
            os.fsync(self._directory)
            self.check_setup(token)
            head = {
                "schema_version": 1,
                "kind": "stock_probe_active",
                "namespace_id": self.namespace_id,
                "probe_id": token.probe_id,
                "intent_sha256": digest,
            }
            temporary = ".active-" + token.probe_id + ".tmp"
            _write_new(self._directory, temporary, head, self._uid)
            self.check_setup(token)
            os.replace(
                temporary, "active.json", src_dir_fd=self._directory, dst_dir_fd=self._directory
            )
            os.fsync(self._directory)
            snapshot = self.snapshot()
            _require(
                snapshot is not None
                and snapshot.probe_id == token.probe_id
                and snapshot.intent_sha256 == digest
            )
            self.check_setup(token)
            self._owned_id, self._owned_intent = token.probe_id, digest
            return cast(ProbeSnapshot, snapshot)

    def _owned_node(self) -> _Node:
        self._normal()
        _require(self._owned_id is not None and self._owned_intent is not None)
        history = self._history()
        _require(bool(history))
        node = history[-1]
        _require(
            node.snapshot.probe_id == self._owned_id
            and node.snapshot.intent_sha256 == self._owned_intent
            and node.snapshot.closed_outcome is None
        )
        return node

    def _receipt(
        self, node: _Node, name: str, fields: dict[str, Any], stamp: dict[str, Any]
    ) -> str:
        value = {
            "schema_version": 1,
            "kind": "stock_probe_" + name.removesuffix(".json").replace("-", "_"),
            "namespace_id": self.namespace_id,
            "probe_id": node.snapshot.probe_id,
            "intent_sha256": node.snapshot.intent_sha256,
            **stamp,
            **fields,
        }
        _decode_receipt(
            _canonical(value),
            name,
            namespace_id=self.namespace_id,
            probe_id=node.snapshot.probe_id,
            intent_sha256=node.snapshot.intent_sha256,
        )
        with self._folder(node.snapshot.probe_id) as directory:
            return _write_new(directory, name, value, self._uid)

    def prepare_create(self) -> ProbeCreateFence:
        with _sanitized():
            _require(not self._create_issued)
            self._create_issued = True
            self._create_ack = None
            self._create_token = None
            node = self._owned_node()
            _require("create.json" not in node.records and self._setup_token is not None)
            setup = cast(ProbeSetup, self._setup_token)
            self.check_setup(setup)
            origin = self._now()
            deadline = min(setup.deadline_ns, origin["monotonic_ns"] + 5000000000)
            request_hash = node.records["intent.json"]["request_sha256"]
            digest = self._receipt(
                node,
                "create.json",
                {"request_sha256": request_hash, "dispatch_deadline_ns": deadline},
                origin,
            )
            retained = self._owned_node()
            _require(retained.hashes["create.json"] == digest)
            self._window(origin["boot_id"], deadline)
            token = ProbeCreateFence(
                node.snapshot.probe_id,
                node.snapshot.intent_sha256,
                digest,
                request_hash,
                origin["boot_id"],
                origin["monotonic_ns"],
                deadline,
            )
            self._create_token, self._create_ack = token, digest
            return token

    def check_create_fence(self, token: ProbeCreateFence) -> None:
        with _sanitized():
            self._normal()
            _require(
                type(token) is ProbeCreateFence
                and token is self._create_token
                and self._create_ack == token.receipt_sha256
            )
            node = self._owned_node()
            _require(
                node.hashes.get("create.json") == token.receipt_sha256
                and node.snapshot.probe_id == token.probe_id
                and node.snapshot.intent_sha256 == token.intent_sha256
            )
            receipt = node.records["create.json"]
            _require(
                receipt["request_sha256"] == token.request_sha256
                and receipt["dispatch_deadline_ns"] == token.deadline_ns
            )
            self._window(token.boot_id, token.deadline_ns)

    def claim_create(self, token: ProbeCreateFence) -> None:
        with _sanitized():
            _require(not self._create_dispatched)
            self._create_dispatched = True
            self.check_create_fence(token)

    def create_request(self, token: ProbeCreateFence) -> bytes:
        with _sanitized():
            self.check_create_fence(token)
            with self._folder(token.probe_id) as directory:
                raw = _read_bytes(directory, "request.bin", self._uid)
            _require(hashlib.sha256(raw).hexdigest() == token.request_sha256)
            self.check_create_fence(token)
            return raw

    def record_cid(self, token: ProbeCreateFence, response: bytes) -> str:
        with _sanitized():
            _require(not self._cid_issued)
            self._cid_issued = True
            self._cid_ack = None
            self._normal()
            _require(
                token is self._create_token
                and type(token) is ProbeCreateFence
                and self._create_dispatched
                and self._create_ack == token.receipt_sha256
            )
            node = self._owned_node()
            _require(
                node.hashes.get("create.json") == token.receipt_sha256
                and "cid.json" not in node.records
            )
            cid = verify_creation(response)
            _require(all(prior.snapshot.container_id != cid for prior in self._history()))
            stamp = self._now()
            _require(stamp["boot_id"] == token.boot_id)
            with self._folder(token.probe_id) as directory:
                raw_hash = _write_bytes(directory, "create-response.bin", response, self._uid)
            digest = self._receipt(
                node,
                "cid.json",
                {
                    "create_sha256": token.receipt_sha256,
                    "container_id": cid,
                    "evidence_kind": "create_response",
                    "observation_sha256": raw_hash,
                    "observation_size": len(response),
                },
                stamp,
            )
            retained = self._owned_node()
            _require(
                retained.hashes["cid.json"] == digest and retained.snapshot.container_id == cid
            )
            now = self._now()
            _require(now["boot_id"] == token.boot_id)
            self._cid_ack = digest
            return cid

    def record_created(self, raw: bytes) -> CreatedProbe:
        with _sanitized():
            _require(not self._created_issued)
            self._created_issued = True
            self._created_ack = None
            node = self._owned_node()
            cid = node.snapshot.container_id
            _require(
                cid is not None
                and self._cid_ack is not None
                and node.hashes.get("cid.json") == self._cid_ack
            )
            _require(self._setup_token is not None)
            setup = cast(ProbeSetup, self._setup_token)
            self.check_setup(setup)
            observation = verify_probe_created(
                raw, image=node.image, probe_id=node.snapshot.probe_id, container_id=cast(str, cid)
            )
            stamp = self._now()
            with self._folder(node.snapshot.probe_id) as directory:
                raw_hash = _write_bytes(directory, "prestart.bin", raw, self._uid)
            digest = self._receipt(
                node,
                "created.json",
                {
                    "cid_sha256": self._cid_ack,
                    "prestart_sha256": raw_hash,
                    "prestart_size": len(raw),
                },
                stamp,
            )
            retained = self._owned_node()
            _require(retained.hashes["created.json"] == digest)
            self.check_setup(setup)
            self._created_ack = digest
            return observation

    def prepare_start(self) -> ProbeStartFence:
        with _sanitized():
            _require(not self._start_issued)
            self._start_issued = True
            self._start_ack = None
            self._start_token = None
            node = self._owned_node()
            _require(
                self._created_ack is not None
                and node.hashes.get("created.json") == self._created_ack
                and self._cid_ack is not None
                and node.hashes.get("cid.json") == self._cid_ack
            )
            _require(
                self._create_dispatched
                and "start.json" not in node.records
                and self._setup_token is not None
                and node.snapshot.container_id is not None
            )
            setup = cast(ProbeSetup, self._setup_token)
            self.check_setup(setup)
            origin = self._now()
            run_deadline = origin["monotonic_ns"] + 30000000000
            dispatch_deadline = min(setup.deadline_ns, origin["monotonic_ns"] + 5000000000)
            digest = self._receipt(
                node,
                "start.json",
                {
                    "created_sha256": self._created_ack,
                    "container_id": node.snapshot.container_id,
                    "run_deadline_ns": run_deadline,
                },
                origin,
            )
            retained = self._owned_node()
            _require(retained.hashes["start.json"] == digest)
            self.check_setup(setup)
            self._window(origin["boot_id"], dispatch_deadline)
            token = ProbeStartFence(
                node.snapshot.probe_id,
                node.snapshot.intent_sha256,
                cast(str, node.snapshot.container_id),
                digest,
                origin["boot_id"],
                origin["monotonic_ns"],
                run_deadline,
                dispatch_deadline,
            )
            self._start_token, self._start_ack = token, digest
            return token

    def check_start_fence(self, token: ProbeStartFence) -> None:
        with _sanitized():
            self._normal()
            _require(
                type(token) is ProbeStartFence
                and token is self._start_token
                and self._start_ack == token.receipt_sha256
            )
            node = self._owned_node()
            _require(
                node.hashes.get("start.json") == token.receipt_sha256
                and node.hashes.get("created.json") == self._created_ack
                and node.snapshot.container_id == token.container_id
                and node.snapshot.probe_id == token.probe_id
                and node.snapshot.intent_sha256 == token.intent_sha256
            )
            _require(self._setup_token is not None)
            self.check_setup(cast(ProbeSetup, self._setup_token))
            self._window(token.boot_id, token.dispatch_deadline_ns)

    def claim_start(self, token: ProbeStartFence) -> None:
        with _sanitized():
            _require(not self._start_dispatched)
            self._start_dispatched = True
            self.check_start_fence(token)
