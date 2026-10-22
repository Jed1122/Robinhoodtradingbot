"""Owned source-bound stock releases, with no installation or trading operation.

Each source owns fresh bounded native stages. Historical facts admit only a
different source; current success requires final cleanup and the original window.
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
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

from infra.hybrid.stock_attempts import _canonical, _check_clock, _clock, _read, _write_new
from infra.hybrid.stock_build_inputs import SourceArchive, inspect_source
from infra.hybrid.stock_probe_store import _clock_key
from infra.hybrid.stock_release import (
    RELEASE_ROOT,
    _close_all,
    _fingerprint,
    _open_directory,
    normalize_configuration_observation,
)

if TYPE_CHECKING:
    from infra.hybrid.stock_container import ImageProfile
    from infra.hybrid.stock_probe_controller import ProbeResult
    from infra.hybrid.stock_producer_history import _History

PRODUCER_ROOT = Path("/var/lib/hybrid-stock-producer")
_ASSETS_ROOT = Path(__file__).resolve().parents[2]
_ASSETS = ("Dockerfile", ".docker-base-image", "compose.stock-research.yml")
_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
_WRITE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_SLOTS = {
    "source.tar": (1, 16 * 1024 * 1024),
    "engine.bin": (1, 1048576),
    "build-request.http": (1, 16 * 1024 * 1024 + 8192),
    "build-response.http": (0, 1048576 + 8192),
    "image.bin": (1, 1048576),
    "dispatch.json": (1, 4096),
    "build-complete.json": (1, 4096),
    "source-preparation.json": (1, 4096),
    "probe-intent.json": (1, 4096),
    "probe-result.json": (1, 4096),
    "configuration.bin": (1, 4096),
    "compose-template.yml": (1, 1048576),
    "compose.env": (0, 0),
    "compose-version.stdout": (0, 128),
    "compose-version.stderr": (0, 16384),
    "compose-render.stdout": (0, 65536),
    "compose-render.stderr": (0, 16384),
    "render-intent.json": (1, 4096),
    "render-complete.json": (1, 4096),
    "publication-intent.json": (1, 4096),
    "publication-files.json": (1, 4096),
    "terminal.json": (1, 8192),
}
_ERRORS = (OSError, ValueError, TypeError, KeyError, OverflowError, AttributeError, RecursionError)
_ACTIVE: _Lease | None = None


def _deny() -> NoReturn:
    raise ValueError("stock_producer_unavailable") from None


def _require(condition: bool) -> None:
    if not condition:
        _deny()


@contextmanager
def _sanitized() -> Iterator[None]:
    try:
        yield
    except _ERRORS:
        _deny()


def _directory(info: os.stat_result, uid: int) -> None:
    _require(
        stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == uid
    )


def _file(info: os.stat_result, uid: int, low: int, high: int, *, asset: bool = False) -> None:
    _require(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == uid
        and info.st_nlink == 1
        and low <= info.st_size <= high
        and (info.st_mode & 0o022 == 0 if asset else stat.S_IMODE(info.st_mode) == 0o600)
    )


def _read_binary(
    directory: int, name: str, uid: int, low: int, high: int, *, asset: bool = False
) -> bytes:
    descriptor = os.open(name, _READ, dir_fd=directory)
    try:
        before = os.fstat(descriptor)
        _file(before, uid, low, high, asset=asset)
        chunks = []
        size = 0
        while size <= high:
            chunk = os.read(descriptor, min(65536, high + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        _require(size == before.st_size and low <= size <= high)
        stamp = _fingerprint(before)
        _require(stamp == _fingerprint(os.fstat(descriptor)))
        _require(stamp == _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False)))
        return b"".join(chunks)
    finally:
        _close_all((descriptor,))


def _write_binary(directory: int, name: str, raw: bytes, uid: int) -> tuple[str, tuple[int, ...]]:
    low, high = _SLOTS[name]
    _require(type(raw) is bytes and low <= len(raw) <= high)
    descriptor = os.open(name, _WRITE, 0o600, dir_fd=directory)
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            _require(type(written) is int and 0 < written <= len(raw) - offset)
            offset += written
        before = os.fstat(descriptor)
        _file(before, uid, low, high)
        _require(before.st_size == len(raw))
        os.fsync(descriptor)
        _require(_fingerprint(before) == _fingerprint(os.fstat(descriptor)))
        _require(
            _fingerprint(before)
            == _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False))
        )
    finally:
        _close_all((descriptor,))
    os.fsync(directory)
    _require(_read_binary(directory, name, uid, low, high) == raw)
    stamp = _fingerprint(before)
    _require(stamp == _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False)))
    return hashlib.sha256(raw).hexdigest(), stamp


def _path(root: Path, uid: int) -> None:
    _require(type(uid) is int and uid >= 0 and os.geteuid() == uid)
    _require(
        isinstance(root, Path) and root.is_absolute() and ".." not in root.parts and root.name != ""
    )


def _open(root: Path, uid: int, *, production: bool = False) -> int:
    return _open_directory(root, trusted_uid=uid, release_root=Path("/") if production else root)


def _next_clock(
    origin: dict[str, Any], last: dict[str, Any], shutdown: list[bool], deadline_ns: int
) -> dict[str, Any]:
    _require(type(shutdown) is list and len(shutdown) == 1 and shutdown[0] is False)
    now = _clock()
    _check_clock(now)
    _require(
        now["boot_id"] == origin["boot_id"]
        and last["monotonic_ns"] <= now["monotonic_ns"] < deadline_ns
        and _clock_key(last["utc"]) <= _clock_key(now["utc"])
    )
    return now


def _filesystem(
    uid: int,
    production: bool,
    directories: list[tuple[int, Path]],
    directory_ids: list[tuple[int, int]],
    inventories: dict[int, set[str]],
    pins: list[tuple[int, str, tuple[int, ...]]],
    *,
    assets_fd: int | None = None,
) -> None:
    for (fd, path), identity in zip(directories, directory_ids, strict=True):
        info = os.fstat(fd)
        _require((info.st_dev, info.st_ino) == identity)
        if fd != assets_fd:
            _directory(info, uid)
        current = _open(path, uid, production=production)
        try:
            info = os.fstat(current)
            _require((info.st_dev, info.st_ino) == identity)
        finally:
            _close_all((current,))
    for fd, expected in inventories.items():
        _require(set(os.listdir(fd)) == expected)
    for directory, name, stamp in pins:
        _require(_fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False)) == stamp)


def _initialize(root: Path, *, trusted_uid: int) -> None:
    """Explicit private fixture seam; partial/existing namespaces are never repaired."""
    with _sanitized():
        _path(root, trusted_uid)
        parent = _open(root.parent, trusted_uid, production=root == PRODUCER_ROOT)
        descriptors = [parent]
        try:
            os.mkdir(root.name, 0o700, dir_fd=parent)
            directory = os.open(root.name, _DIRECTORY, dir_fd=parent)
            descriptors.append(directory)
            _directory(os.fstat(directory), trusted_uid)
            for name in ("inputs", "attempts"):
                os.mkdir(name, 0o700, dir_fd=directory)
                child = os.open(name, _DIRECTORY, dir_fd=directory)
                try:
                    _directory(os.fstat(child), trusted_uid)
                    os.fsync(child)
                finally:
                    _close_all((child,))
            lock = os.open("producer.lock", _WRITE, 0o600, dir_fd=directory)
            descriptors.append(lock)
            lock_info, root_info = os.fstat(lock), os.fstat(directory)
            _file(lock_info, trusted_uid, 0, 0)
            os.fsync(lock)
            _write_new(
                directory,
                "namespace.json",
                {
                    "schema_version": 1,
                    "kind": "stock_producer_namespace",
                    "namespace_id": secrets.token_hex(16),
                    "root_device": root_info.st_dev,
                    "root_inode": root_info.st_ino,
                    "lock_device": lock_info.st_dev,
                    "lock_inode": lock_info.st_ino,
                },
                trusted_uid,
            )
            os.fsync(directory)
            os.fsync(parent)
        finally:
            _close_all(reversed(descriptors))


def initialize_producer() -> None:
    """Initialize the fixed Linux root-owned namespace once, without any build."""
    _require(sys.platform == "linux" and os.geteuid() == 0)
    _initialize(PRODUCER_ROOT, trusted_uid=0)


class _Lease:
    """Authority is the current exact context, not a constructed/copied data record."""

    def __init__(
        self,
        source: SourceArchive,
        root: Path,
        assets_root: Path,
        uid: int,
        descriptors: list[int],
        namespace: dict[str, Any],
        shutdown: list[bool],
        origin: dict[str, Any],
        release_root: Path,
        history: _History,
    ) -> None:
        self.source, self.root, self.assets_root, self.uid = source, root, assets_root, uid
        self.release_root, self.descriptors = release_root, descriptors
        self.root_fd, self.lock_fd, self.inputs_fd, self.attempts_fd = descriptors[:4]
        self.assets_fd, self.attempt_fd = descriptors[-2:]
        self.release_fd = history.release_fd
        self.completed_sources = set(history.sources)
        self.namespace, self.shutdown, self.origin = namespace, shutdown, origin
        self.deadline_ns = int(origin["monotonic_ns"]) + 1_200_000_000_000
        self.last_clock = history.last_clock
        self.closed = False
        self.preparation_started = False
        self.prepared = False
        self.started = False
        self.dispatched = False
        self.built_image: ImageProfile | None = None
        self.probe_started = False
        self.probe_result: ProbeResult | None = None
        self.render_started = False
        self.compose_bytes: bytes | None = None
        self.publication_started = False
        self.published_manifest: Path | None = None
        self.terminal_started = False
        self.terminal_ack = False
        self.pins: list[tuple[int, str, tuple[int, ...]]] = list(history.pins)
        self.directories = [
            (self.root_fd, root),
            (self.inputs_fd, root / "inputs"),
            (self.attempts_fd, root / "attempts"),
            (self.attempt_fd, root / "attempts" / source.digest),
            (self.assets_fd, assets_root),
        ]
        self.directory_ids = [
            (os.fstat(fd).st_dev, os.fstat(fd).st_ino) for fd, _ in self.directories
        ]
        for item, identity in zip(history.directories, history.directory_ids, strict=True):
            if item[0] not in {fd for fd, _ in self.directories}:
                self.directories.append(item)
                self.directory_ids.append(identity)
        self.inventories = {
            self.root_fd: set(os.listdir(self.root_fd)),
            self.inputs_fd: set(os.listdir(self.inputs_fd)),
            self.attempts_fd: self.completed_sources | {source.digest},
            self.attempt_fd: set(),
        }
        for fd, inventory in history.inventories.items():
            if fd not in self.inventories:
                self.inventories[fd] = set(inventory)
        self.hashes: dict[str, str] = {}

    def _filesystem(self) -> None:
        _require(type(self) is _Lease and _ACTIVE is self and not self.closed)
        _filesystem(
            self.uid,
            self.root == PRODUCER_ROOT,
            self.directories,
            self.directory_ids,
            self.inventories,
            self.pins,
            assets_fd=self.assets_fd,
        )

    def check(self, *, not_after_ns: int | None = None) -> dict[str, Any]:
        self._filesystem()
        deadline = self.deadline_ns if not_after_ns is None else min(self.deadline_ns, not_after_ns)
        now = _next_clock(self.origin, self.last_clock, self.shutdown, deadline)
        self.last_clock = now
        return now

    def retain(self, name: str, raw: bytes) -> str:
        # Failure evidence may be retained after shutdown/expiry; this grants no dispatch.
        self._filesystem()
        _require(name not in self.inventories[self.attempt_fd])
        digest, stamp = _write_binary(self.attempt_fd, name, raw, self.uid)
        self.inventories[self.attempt_fd].add(name)
        self.pins.append((self.attempt_fd, name, stamp))
        self.hashes[name] = digest
        self._filesystem()
        return digest

    def record(self, name: str, value: dict[str, Any]) -> str:
        self._filesystem()
        _require(
            name
            in {
                "dispatch.json",
                "build-complete.json",
                "source-preparation.json",
                "probe-intent.json",
                "probe-result.json",
                "render-intent.json",
                "render-complete.json",
                "publication-intent.json",
                "publication-files.json",
                "terminal.json",
            }
            and name not in self.inventories[self.attempt_fd]
        )
        digest, stamp = _write_binary(self.attempt_fd, name, _canonical(value), self.uid)
        self.inventories[self.attempt_fd].add(name)
        self.pins.append((self.attempt_fd, name, stamp))
        self.hashes[name] = digest
        self._filesystem()
        return digest

    def begin_build(self) -> int:
        now = self.check()
        _require(self.prepared and not self.started)
        self.started = True
        return min(self.deadline_ns, int(now["monotonic_ns"]) + 900_000_000_000)

    def claim(self, request: bytes, deadline_ns: int) -> None:
        self.check(not_after_ns=deadline_ns)
        _require(
            self.prepared
            and self.started
            and not self.dispatched
            and "source-preparation.json" in self.hashes
            and "engine.bin" in self.hashes
        )
        self.retain("build-request.http", request)
        self.record(
            "dispatch.json",
            {
                "schema_version": 1,
                "kind": "stock_build_dispatch",
                "namespace_id": self.namespace["namespace_id"],
                "source_sha256": self.source.digest,
                "source_copy_sha256": self.hashes["source.tar"],
                "source_preparation_sha256": self.hashes["source-preparation.json"],
                "engine_sha256": self.hashes["engine.bin"],
                "request_sha256": self.hashes["build-request.http"],
                "build_deadline_ns": deadline_ns,
                "producer_deadline_ns": self.deadline_ns,
                "origin": self.origin,
                "dispatch_clock": self.check(not_after_ns=deadline_ns),
            },
        )
        self.check(not_after_ns=deadline_ns)
        self.dispatched = True  # Spent before connection/send; uncertainty is never replayable.


def _child_directory(lease: _Lease, parent: int, name: str, path: Path) -> int:
    """Register original directory identity before acknowledging its durability."""
    lease.check()
    _require(name not in lease.inventories[parent])
    os.mkdir(name, 0o700, dir_fd=parent)
    descriptor = os.open(name, _DIRECTORY, dir_fd=parent)
    lease.descriptors.append(descriptor)
    info = os.fstat(descriptor)
    _directory(info, lease.uid)
    lease.directories.append((descriptor, path))
    lease.directory_ids.append((info.st_dev, info.st_ino))
    lease.inventories[parent].add(name)
    lease.inventories[descriptor] = set()
    os.fsync(descriptor)
    os.fsync(parent)
    lease.check()
    return descriptor


@contextmanager
def _lease(
    source_sha256: str,
    shutdown: list[bool],
    *,
    root: Path = PRODUCER_ROOT,
    assets_root: Path = _ASSETS_ROOT,
    trusted_uid: int = 0,
    release_root: Path = RELEASE_ROOT,
) -> Iterator[_Lease]:
    global _ACTIVE
    with _sanitized():
        _path(root, trusted_uid)
        _path(assets_root, trusted_uid)
        _path(release_root, trusted_uid)
        _require(type(source_sha256) is str and _HEX.fullmatch(source_sha256) is not None)
        _require(
            _ACTIVE is None
            and type(shutdown) is list
            and len(shutdown) == 1
            and shutdown[0] is False
        )
        origin = _clock()
        _check_clock(origin)
        descriptors: list[int] = []
        lease: _Lease | None = None
        try:
            directory = _open(root, trusted_uid, production=root == PRODUCER_ROOT)
            descriptors.append(directory)
            _directory(os.fstat(directory), trusted_uid)
            _require(
                set(os.listdir(directory))
                == {"inputs", "attempts", "producer.lock", "namespace.json"}
            )
            lock = os.open(
                "producer.lock",
                os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=directory,
            )
            descriptors.append(lock)
            _file(os.fstat(lock), trusted_uid, 0, 0)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_stamp = _fingerprint(os.fstat(lock))
            namespace_stamp = _fingerprint(
                os.stat("namespace.json", dir_fd=directory, follow_symlinks=False)
            )
            namespace, _ = _read(directory, "namespace.json", trusted_uid)
            _require(
                namespace_stamp
                == _fingerprint(os.stat("namespace.json", dir_fd=directory, follow_symlinks=False))
            )
            expected = {
                "schema_version": 1,
                "kind": "stock_producer_namespace",
                "namespace_id": namespace.get("namespace_id"),
                "root_device": os.fstat(directory).st_dev,
                "root_inode": os.fstat(directory).st_ino,
                "lock_device": os.fstat(lock).st_dev,
                "lock_inode": os.fstat(lock).st_ino,
            }
            _require(
                type(expected["namespace_id"]) is str
                and re.fullmatch(r"[0-9a-f]{32}", expected["namespace_id"]) is not None
                and _canonical(namespace) == _canonical(expected)
            )
            for name in ("inputs", "attempts"):
                fd = os.open(name, _DIRECTORY, dir_fd=directory)
                descriptors.append(fd)
                _directory(os.fstat(fd), trusted_uid)
            inputs, attempts = descriptors[-2:]
            names = os.listdir(inputs)
            _require(len(names) <= 128)
            input_pins = []
            for name in names:
                _require(re.fullmatch(r"[0-9a-f]{64}\.tar", name) is not None)
                info = os.stat(name, dir_fd=inputs, follow_symlinks=False)
                _file(info, trusted_uid, 1, 16 * 1024 * 1024)
                input_pins.append((inputs, name, _fingerprint(info)))
            from infra.hybrid.stock_producer_history import _admit

            history = _admit(
                root=root,
                release_root=release_root,
                uid=trusted_uid,
                descriptors=descriptors,
                namespace=namespace,
                origin=origin,
                shutdown=shutdown,
                source_sha256=source_sha256,
                pins=[
                    *input_pins,
                    (directory, "namespace.json", namespace_stamp),
                    (directory, "producer.lock", lock_stamp),
                ],
            )
            assets = _open(assets_root, trusted_uid, production=root == PRODUCER_ROOT)
            descriptors.append(assets)
            source = inspect_source(
                _read_binary(inputs, source_sha256 + ".tar", trusted_uid, 1, 16 * 1024 * 1024),
                expected_sha256=source_sha256,
            )
            reviewed = []
            asset_pins = []
            for name in _ASSETS:
                before = _fingerprint(os.stat(name, dir_fd=assets, follow_symlinks=False))
                reviewed.append(_read_binary(assets, name, trusted_uid, 1, 1048576, asset=True))
                _require(
                    before == _fingerprint(os.stat(name, dir_fd=assets, follow_symlinks=False))
                )
                asset_pins.append((assets, name, before))
            _require(
                reviewed
                == [source.dockerfile, (source.base_ref + "\n").encode(), source.compose_template]
            )
            os.mkdir(source_sha256, 0o700, dir_fd=attempts)
            attempt = os.open(source_sha256, _DIRECTORY, dir_fd=attempts)
            descriptors.append(attempt)
            _directory(os.fstat(attempt), trusted_uid)
            os.fsync(attempt)
            os.fsync(attempts)
            lease = _Lease(
                source,
                root,
                assets_root,
                trusted_uid,
                descriptors,
                namespace,
                shutdown,
                origin,
                release_root,
                history,
            )
            _ACTIVE = lease
            lease.inventories[directory] = {"inputs", "attempts", "producer.lock", "namespace.json"}
            lease.inventories[inputs] = set(names)
            lease.pins.extend(input_pins + asset_pins)
            lease.pins.extend(
                [
                    (directory, "namespace.json", namespace_stamp),
                    (directory, "producer.lock", lock_stamp),
                ]
            )
            lease.retain("source.tar", source.raw)
            lease.check()
            yield lease
            lease.check()
        finally:
            if lease is not None:
                lease.closed = True
                _ACTIVE = None
            _close_all(reversed(descriptors))


def _current_source(lease: _Lease) -> None:
    """Current-context acknowledgement of one fresh matching clean Git capture."""
    from infra.hybrid.stock_source_prepare import _capture_source

    _require(type(lease) is _Lease)
    origin = lease.check()
    _require(not lease.preparation_started)
    lease.preparation_started = True
    source = _capture_source(lease.assets_root, deadline=lease.deadline_ns / 1_000_000_000)
    lease.check()
    _require(
        source.raw == lease.source.raw
        and source.digest == lease.source.digest
        and source.commit == lease.source.commit
    )
    lease.record(
        "source-preparation.json",
        {
            "schema_version": 1,
            "kind": "stock_source_preparation",
            "namespace_id": lease.namespace["namespace_id"],
            "source_sha256": source.digest,
            "commit": source.commit,
            "source_copy_sha256": lease.hashes["source.tar"],
            "started_clock": origin,
            "completed_clock": lease.check(),
        },
    )
    lease.check()
    lease.prepared = True


def _fresh_probe(lease: _Lease) -> ProbeResult:
    """One fixed current probe; old/supplied results never replace the owned call."""
    from infra.hybrid.stock_probe_controller import ProbeResult, run_probe

    _require(type(lease) is _Lease)
    started = lease.check()
    _require(
        lease.built_image is not None
        and "build-complete.json" in lease.hashes
        and not lease.probe_started
    )
    lease.probe_started = True
    image = lease.built_image
    if image is None:
        _deny()
    lease.record(
        "probe-intent.json",
        {
            "schema_version": 1,
            "kind": "stock_producer_probe_intent",
            "namespace_id": lease.namespace["namespace_id"],
            "source_sha256": lease.source.digest,
            "image_digest": image.image_digest,
            "build_complete_sha256": lease.hashes["build-complete.json"],
            "started_clock": started,
        },
    )
    lease.check()
    result = run_probe(image.image_digest)
    _require(type(result) is ProbeResult and result.image_digest == image.image_digest)
    _require(
        result.status in {"succeeded", "failed", "recovery_only"}
        and type(result.reason) is str
        and re.fullmatch(r"[a-z_]{1,64}", result.reason) is not None
    )
    _require(
        type(result.probe_id) is str and re.fullmatch(r"[0-9a-f]{32}", result.probe_id) is not None
    )
    _require(
        result.container_id is None
        or (type(result.container_id) is str and _HEX.fullmatch(result.container_id) is not None)
    )
    raw = result.configuration
    _require(raw is None or (type(raw) is bytes and 0 < len(raw) <= 4096))
    completed = _clock()
    _check_clock(completed)
    lease.record(
        "probe-result.json",
        {
            "schema_version": 1,
            "kind": "stock_producer_probe_result",
            "namespace_id": lease.namespace["namespace_id"],
            "source_sha256": lease.source.digest,
            "image_digest": result.image_digest,
            "probe_id": result.probe_id,
            "container_id": result.container_id,
            "status": result.status,
            "reason": result.reason,
            "configuration_sha256": None if raw is None else hashlib.sha256(raw).hexdigest(),
            "build_complete_sha256": lease.hashes["build-complete.json"],
            "probe_intent_sha256": lease.hashes["probe-intent.json"],
            "completed_clock": completed,
        },
    )
    lease.check()
    _require(
        result.status == "succeeded"
        and result.reason == "completed"
        and result.container_id is not None
        and raw is not None
    )
    if raw is None:
        _deny()
    _require(normalize_configuration_observation(raw) == raw)
    lease.retain("configuration.bin", raw)
    lease.check()
    lease.probe_result = result
    return result


class _Final:
    """Original identities and window, usable after all owning handles are closed."""

    def __init__(self, lease: _Lease) -> None:
        lease.check()
        _require(lease.terminal_ack and lease.published_manifest is not None)
        if lease.published_manifest is None:
            _deny()
        self.manifest = lease.published_manifest
        self.root, self.uid = lease.root, lease.uid
        self.origin, self.last_clock = dict(lease.origin), dict(lease.last_clock)
        self.deadline_ns, self.shutdown = lease.deadline_ns, lease.shutdown
        self.directories = [
            (
                path,
                identity,
                fd == lease.assets_fd,
                frozenset(lease.inventories[fd]) if fd in lease.inventories else None,
            )
            for (fd, path), identity in zip(lease.directories, lease.directory_ids, strict=True)
        ]
        paths = dict(lease.directories)
        self.pins = [(paths[fd], name, stamp) for fd, name, stamp in lease.pins]

    def check(self) -> None:
        """No original FD or cleanup acknowledgement is reconstructed from files."""
        with _sanitized():
            _require(os.geteuid() == self.uid)
            self.last_clock = _next_clock(
                self.origin, self.last_clock, self.shutdown, self.deadline_ns
            )
            descriptors: list[int] = []
            opened: dict[Path, int] = {}
            try:
                for path, identity, asset, inventory in self.directories:
                    fd = _open(path, self.uid, production=self.root == PRODUCER_ROOT)
                    descriptors.append(fd)
                    info = os.fstat(fd)
                    _require((info.st_dev, info.st_ino) == identity)
                    if not asset:
                        _directory(info, self.uid)
                    if inventory is not None:
                        _require(set(os.listdir(fd)) == inventory)
                    opened[path] = fd
                for path, name, stamp in self.pins:
                    _require(
                        stamp
                        == _fingerprint(os.stat(name, dir_fd=opened[path], follow_symlinks=False))
                    )
            finally:
                _close_all(reversed(descriptors))
            self.last_clock = _next_clock(
                self.origin, self.last_clock, self.shutdown, self.deadline_ns
            )


@contextmanager
def _production_lease(source_sha256: str, shutdown: list[bool]) -> Iterator[_Lease]:
    """The only production namespace; tests replace this filesystem boundary."""
    _require(sys.platform == "linux" and os.geteuid() == 0)
    with _lease(source_sha256, shutdown) as lease:
        yield lease


@contextmanager
def _completed_release(source_sha256: str) -> Iterator[_Final]:
    from infra.hybrid.stock_build_engine import _build
    from infra.hybrid.stock_compose_render import _render
    from infra.hybrid.stock_producer_history import _seal
    from infra.hybrid.stock_release_publication import _publish_files
    from infra.hybrid.stock_supervisor import _shutdown

    with _sanitized():
        _require(type(source_sha256) is str and _HEX.fullmatch(source_sha256) is not None)
        with _shutdown() as requested:
            with _production_lease(source_sha256, requested) as lease:
                _build(lease)
                _fresh_probe(lease)
                _render(lease)
                _publish_files(lease)
                _seal(lease)
                finished = _Final(lease)
                yield finished
                lease.check()
                finished.last_clock = dict(lease.last_clock)
            finished.check()
        finished.check()


def produce_release(source_sha256: str) -> Path:
    """Own one fixed release; success follows every original-window cleanup gate."""
    with _completed_release(source_sha256) as finished:
        manifest = finished.manifest
    return manifest
