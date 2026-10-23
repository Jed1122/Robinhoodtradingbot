"""Explicit negative-only incident reconciliation under the permanent producer lock.

No store initializer, native mutation, source replay, release or worker operation
is exposed. The fixed read-only observer is freshly owned before the sole write.
"""

from __future__ import annotations

import fcntl
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from infra.hybrid.stock_attempts import _check_clock, _clock
from infra.hybrid.stock_build_profile import observe_build_profile
from infra.hybrid.stock_failed_build_inputs import encode_failed_facts, inspect_failed_build
from infra.hybrid.stock_producer_history import _FAILED_FACTS, _FAILED_FILES, _History, _sha
from infra.hybrid.stock_release import RELEASE_ROOT, _close_all, _fingerprint
from infra.hybrid.stock_release_producer import (
    _DIRECTORY,
    _HEX,
    PRODUCER_ROOT,
    _directory,
    _file,
    _filesystem,
    _next_clock,
    _open,
    _path,
    _read_binary,
    _require,
    _sanitized,
    _write_binary,
)


class _Final:
    """Post-cleanup identities/window; stored facts do not reconstruct caller success."""

    def __init__(self, history: _History, facts: Path) -> None:
        history.check()
        self.facts = facts
        self.root, self.uid = history.root, history.uid
        self.origin, self.last_clock = dict(history.origin), dict(history.last_clock)
        self.deadline_ns, self.shutdown = history.deadline_ns, history.shutdown
        self.directories = [
            (path, identity, set(history.inventories[fd]))
            for (fd, path), identity in zip(history.directories, history.directory_ids, strict=True)
        ]
        paths = dict(history.directories)
        self.pins = [(paths[fd], name, stamp) for fd, name, stamp in history.pins]

    def check(self) -> None:
        with _sanitized():
            _require(os.geteuid() == self.uid)
            self.last_clock = _next_clock(
                self.origin, self.last_clock, self.shutdown, self.deadline_ns
            )
            descriptors: list[int] = []
            try:
                opened = {}
                directories = []
                identities = []
                inventories = {}
                for path, identity, inventory in self.directories:
                    fd = _open(path, self.uid, production=self.root == PRODUCER_ROOT)
                    descriptors.append(fd)
                    opened[path] = fd
                    directories.append((fd, path))
                    identities.append(identity)
                    inventories[fd] = inventory
                pins = [(opened[path], name, stamp) for path, name, stamp in self.pins]
                _filesystem(
                    self.uid, self.root == PRODUCER_ROOT, directories, identities, inventories, pins
                )
            finally:
                _close_all(reversed(descriptors))
            self.last_clock = _next_clock(
                self.origin, self.last_clock, self.shutdown, self.deadline_ns
            )


@contextmanager
def _reconciliation(
    source_sha256: str,
    shutdown: list[bool],
    *,
    root: Path = PRODUCER_ROOT,
    release_root: Path = RELEASE_ROOT,
    trusted_uid: int = 0,
) -> Iterator[_Final]:
    """Private disposable-filesystem seam; public operation has fixed root/UID."""
    with _sanitized():
        _path(root, trusted_uid)
        _path(release_root, trusted_uid)
        _require(type(source_sha256) is str and _HEX.fullmatch(source_sha256) is not None)
        origin = _clock()
        _check_clock(origin)
        descriptors: list[int] = []
        try:
            directory = _open(root, trusted_uid, production=root == PRODUCER_ROOT)
            descriptors.append(directory)
            _directory(os.fstat(directory), trusted_uid)
            _require(
                set(os.listdir(directory))
                == {"namespace.json", "producer.lock", "inputs", "attempts"}
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
            ns_raw = _read_binary(directory, "namespace.json", trusted_uid, 1, 4096)
            ns_stamp = _fingerprint(
                os.stat("namespace.json", dir_fd=directory, follow_symlinks=False)
            )
            from infra.hybrid.stock_producer_history import _json

            namespace = _json(ns_raw)
            _require(
                namespace.get("root_device") == os.fstat(directory).st_dev
                and namespace.get("root_inode") == os.fstat(directory).st_ino
                and namespace.get("lock_device") == lock_stamp[0]
                and namespace.get("lock_inode") == lock_stamp[1]
            )
            for name in ("inputs", "attempts"):
                fd = os.open(name, _DIRECTORY, dir_fd=directory)
                descriptors.append(fd)
                _directory(os.fstat(fd), trusted_uid)
            inputs, _attempts = descriptors[-2:]
            names = os.listdir(inputs)
            _require(len(names) <= 128)
            pins = [
                (directory, "producer.lock", lock_stamp),
                (directory, "namespace.json", ns_stamp),
            ]
            for name in names:
                _require(name.endswith(".tar") and _HEX.fullmatch(name[:-4]) is not None)
                info = os.stat(name, dir_fd=inputs, follow_symlinks=False)
                _file(info, trusted_uid, 1, 16 * 1024 * 1024)
                pins.append((inputs, name, _fingerprint(info)))
            history = _History(
                root=root,
                release_root=release_root,
                uid=trusted_uid,
                descriptors=descriptors,
                namespace=namespace,
                origin=origin,
                shutdown=shutdown,
                pins=pins,
                pending_source=source_sha256,
            )
            history.deadline_ns = int(origin["monotonic_ns"]) + 120_000_000_000
            history.check()
            for source in sorted(history.sources - {source_sha256}):
                history.validate(source)
            dirs, bindings, retained = history.failed_inputs(source_sha256, pending=True)
            evidence = inspect_failed_build(
                source_sha256,
                retained["namespace.json"][0],
                retained["inputs/" + source_sha256 + ".tar"][0],
                {name: retained["attempt/" + name][0] for name in _FAILED_FILES},
            )
            for name, binding in bindings.items():
                value, stamp = retained[name]
                history._flush(binding, _sha(value), stamp)
            for fd in dirs.values():
                os.fsync(fd)
                history.check()
            observation = observe_build_profile(
                evidence.source_commit,
                retained["attempt/engine.bin"][0],
                evidence.original_origin,
                not_after_ns=history.deadline_ns,
            )
            history.check()
            raw = encode_failed_facts(
                evidence,
                observation={
                    "reconciler_origin": origin,
                    "reconciler_deadline_ns": history.deadline_ns,
                    "reconciled_clock": history.last_clock,
                    **observation,
                },
                directories={
                    name: [os.fstat(fd).st_dev, os.fstat(fd).st_ino] for name, fd in dirs.items()
                },
                files={
                    name: {"sha256": _sha(value), "fingerprint": list(stamp)}
                    for name, (value, stamp) in retained.items()
                },
            )
            history.check()
            digest, stamp = _write_binary(dirs["attempt"], _FAILED_FACTS, raw, trusted_uid)
            history.inventories[dirs["attempt"]].add(_FAILED_FACTS)
            history.pins.append((dirs["attempt"], _FAILED_FACTS, stamp))
            history.check()
            _require(digest == _sha(raw))
            finished = _Final(history, root / "attempts" / source_sha256 / _FAILED_FACTS)
            yield finished
            history.check()
            finished.last_clock = dict(history.last_clock)
        finally:
            _close_all(reversed(descriptors))
        finished.check()


@contextmanager
def _completed_reconciliation(source_sha256: str) -> Iterator[_Final]:
    from infra.hybrid.stock_supervisor import _shutdown

    with _sanitized():
        _require(sys.platform == "linux" and os.geteuid() == 0)
        with _shutdown() as shutdown:
            with _reconciliation(source_sha256, shutdown) as finished:
                yield finished
            finished.check()
        finished.check()


def reconcile_failed_build(source_sha256: str) -> Path:
    """Negative-only closure; no source input can supply an observation/authority."""
    with _completed_reconciliation(source_sha256) as finished:
        result = finished.facts
    return result
