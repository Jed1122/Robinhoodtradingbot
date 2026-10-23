"""Closed historical native facts, never reconstruction of a caller result.

Admission owns fresh reads/flushes under the actual permanent producer lock.
It cannot dispatch, resume, repair, return an old release or enable a worker.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from itertools import pairwise
from pathlib import Path
from typing import Any

from infra.hybrid import stock_release as release
from infra.hybrid.stock_attempts import _check_clock
from infra.hybrid.stock_build_inputs import build_image_id, inspect_source
from infra.hybrid.stock_container import _object, verify_engine_version, verify_image
from infra.hybrid.stock_probe_store import _clock_key
from infra.hybrid.stock_release_producer import (
    _DIRECTORY,
    _READ,
    _SLOTS,
    PRODUCER_ROOT,
    _directory,
    _filesystem,
    _Lease,
    _next_clock,
    _open,
    _read_binary,
    _require,
    _sanitized,
)

_ATTEMPT_FILES = (
    "source.tar",
    "source-preparation.json",
    "engine.bin",
    "build-request.http",
    "dispatch.json",
    "build-response.http",
    "image.bin",
    "build-complete.json",
    "probe-intent.json",
    "probe-result.json",
    "configuration.bin",
    "render-intent.json",
    "compose-version.stdout",
    "compose-version.stderr",
    "compose-render.stdout",
    "compose-render.stderr",
    "render-complete.json",
    "publication-intent.json",
    "publication-files.json",
)
_RENDER_FILES = ("compose-template.yml", "compose.env")
_EMPTY_DIRS = ("docker-config", "home", "empty-path")
_FAILED_FILES = frozenset(_ATTEMPT_FILES[:6])
_FAILED_FACTS = "failed-build-terminal.json"
_Pin = tuple[int, str, tuple[int, ...]]
_Binding = tuple[int, str, int, int, bool]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw, object_pairs_hook=release._pairs, parse_constant=release._constant)
    _require(type(value) is dict and release._canonical(value) == raw)
    return value  # type: ignore[no-any-return]


def _bindings(dirs: dict[str, int], source: str) -> dict[str, _Binding]:
    result = {
        "namespace.json": (dirs["producer"], "namespace.json", 1, 4096, False),
        "producer.lock": (dirs["producer"], "producer.lock", 0, 0, False),
        "inputs/" + source + ".tar": (dirs["inputs"], source + ".tar", 1, 16777216, False),
    }
    for prefix, names, directory in (
        ("attempt/", _ATTEMPT_FILES, "attempt"),
        ("render/", _RENDER_FILES, "render"),
    ):
        for name in names:
            low, high = _SLOTS[name]
            result[prefix + name] = (dirs[directory], name, low, high, False)
    for name, high in release._ARTIFACTS.items():
        result["release/" + name] = (dirs["release"], name, 1, high, True)
    return result


def _roles(lease: _Lease) -> dict[str, int]:
    paths = {path: fd for fd, path in lease.directories}
    attempt = lease.root / "attempts" / lease.source.digest
    roots = {
        "producer": lease.root,
        "inputs": lease.root / "inputs",
        "attempts": lease.root / "attempts",
        "attempt": attempt,
        "render": attempt / "render",
        "release_root": lease.release_root,
        "release": lease.release_root / lease.source.digest,
    }
    roots.update({name: attempt / "render" / name for name in _EMPTY_DIRS})
    return {name: paths[path] for name, path in roots.items()}


def _read(binding: _Binding, uid: int) -> tuple[bytes, tuple[int, ...]]:
    directory, name, low, high, artifact = binding
    stamp = release._fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False))
    if artifact:
        raw, _, observed = release._read_artifact(directory, name, high, uid)
        _require(observed == stamp)
    else:
        raw = _read_binary(directory, name, uid, low, high)
    _require(stamp == release._fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False)))
    return raw, stamp


def _seal(lease: _Lease) -> None:
    """One current terminal write, only after all owned native/file stages acknowledged."""
    with _sanitized():
        _require(type(lease) is _Lease)
        lease.check()
        _require(
            not lease.terminal_started
            and lease.published_manifest is not None
            and lease.built_image is not None
            and lease.probe_result is not None
            and lease.compose_bytes is not None
            and "publication-files.json" in lease.hashes
        )
        lease.terminal_started = True
        dirs = _roles(lease)
        pin_map = {(fd, name): stamp for fd, name, stamp in lease.pins}
        files = {}
        for label, binding in _bindings(dirs, lease.source.digest).items():
            raw, stamp = _read(binding, lease.uid)
            _require(stamp == pin_map[(binding[0], binding[1])])
            files[label] = {"sha256": _sha(raw), "fingerprint": list(stamp)}
            lease.check()
        identities = {
            fd: identity
            for (fd, _), identity in zip(lease.directories, lease.directory_ids, strict=True)
        }
        image = lease.built_image
        _require(image is not None)
        if image is None:
            raise ValueError("stock_producer_unavailable")
        lease.record(
            "terminal.json",
            {
                "schema_version": 1,
                "kind": "stock_producer_terminal_facts",
                "namespace_id": lease.namespace["namespace_id"],
                "source_sha256": lease.source.digest,
                "image_digest": image.image_digest,
                "native_complete": True,
                "origin": lease.origin,
                "producer_deadline_ns": lease.deadline_ns,
                "native_complete_clock": lease.check(),
                "directories": {name: list(identities[fd]) for name, fd in dirs.items()},
                "files": files,
            },
        )
        lease.check()
        lease.terminal_ack = True


class _History:
    """Retained namespace view; no native dispatch authority is exposed."""

    def __init__(
        self,
        *,
        root: Path,
        release_root: Path,
        uid: int,
        descriptors: list[int],
        namespace: dict[str, Any],
        origin: dict[str, Any],
        shutdown: list[bool],
        pins: list[_Pin],
        pending_source: str | None = None,
    ) -> None:
        self.root, self.release_root, self.uid = root, release_root, uid
        self.descriptors, self.namespace = descriptors, namespace
        self.origin, self.last_clock, self.shutdown = origin, origin, shutdown
        self.deadline_ns = int(origin["monotonic_ns"]) + 1_200_000_000_000
        self.directories = [
            (descriptors[0], root),
            (descriptors[2], root / "inputs"),
            (descriptors[3], root / "attempts"),
        ]
        self.directory_ids = [
            (os.fstat(fd).st_dev, os.fstat(fd).st_ino) for fd, _ in self.directories
        ]
        self.inventories = {fd: set(os.listdir(fd)) for fd, _ in self.directories}
        self.pins = list(pins)
        self.sources = set(os.listdir(descriptors[3]))
        self.release_fd: int | None = None
        _require(
            len(self.sources) < 128
            and all(re.fullmatch(r"[0-9a-f]{64}", name) is not None for name in self.sources)
        )
        self.successful_sources: set[str] = set()
        self.failed_sources: set[str] = set()
        _require(pending_source is None or pending_source in self.sources)
        for source in sorted(self.sources):
            fd = os.open(source, _DIRECTORY, dir_fd=descriptors[3])
            try:
                _directory(os.fstat(fd), uid)
                names = set(os.listdir(fd))
            finally:
                release._close_all((fd,))
            if source == pending_source:
                _require(names == _FAILED_FILES)
            elif names == set(_ATTEMPT_FILES) | {"render", "terminal.json"}:
                self.successful_sources.add(source)
            elif names == _FAILED_FILES | {_FAILED_FACTS}:
                self.failed_sources.add(source)
            else:
                _require(False)
        if os.path.lexists(release_root):
            self.release_fd = _open(release_root, uid, production=root == PRODUCER_ROOT)
            self._track(self.release_fd, release_root, self.successful_sources)
        else:
            _require(not self.sources and root != PRODUCER_ROOT)
        self.check()

    def _track(self, fd: int, path: Path, inventory: set[str]) -> None:
        self.descriptors.append(fd)
        info = os.fstat(fd)
        _directory(info, self.uid)
        self.directories.append((fd, path))
        self.directory_ids.append((info.st_dev, info.st_ino))
        self.inventories[fd] = set(inventory)

    def check(self) -> None:
        _filesystem(
            self.uid,
            self.root == PRODUCER_ROOT,
            self.directories,
            self.directory_ids,
            self.inventories,
            self.pins,
        )
        self.last_clock = _next_clock(self.origin, self.last_clock, self.shutdown, self.deadline_ns)

    def _directory(self, parent: int, name: str, path: Path, inventory: set[str]) -> int:
        self.check()
        fd = os.open(name, _DIRECTORY, dir_fd=parent)
        self._track(fd, path, inventory)
        self.check()
        return fd

    def _read(self, binding: _Binding) -> tuple[bytes, tuple[int, ...]]:
        raw, stamp = _read(binding, self.uid)
        self.pins.append((binding[0], binding[1], stamp))
        self.check()
        return raw, stamp

    def _flush(self, binding: _Binding, expected_sha: str, stamp: tuple[int, ...]) -> None:
        self.check()
        directory, name, *_ = binding
        fd = os.open(name, _READ, dir_fd=directory)
        try:
            _require(release._fingerprint(os.fstat(fd)) == stamp)
            os.fsync(fd)
            _require(release._fingerprint(os.fstat(fd)) == stamp)
        finally:
            release._close_all((fd,))
        os.fsync(directory)
        raw, observed = _read(binding, self.uid)
        _require(observed == stamp and _sha(raw) == expected_sha)
        self.check()

    def validate(self, source: str) -> None:
        if source in self.failed_sources:
            self._validate_failed(source)
        else:
            _require(source in self.successful_sources)
            self._validate_successful(source)

    def failed_inputs(
        self, source: str, *, pending: bool = False
    ) -> tuple[dict[str, int], dict[str, _Binding], dict[str, tuple[bytes, tuple[int, ...]]]]:
        _require(self.release_fd is not None and source in self.sources)
        if self.release_fd is None:
            raise ValueError("stock_producer_unavailable")
        names = set(_FAILED_FILES) if pending else set(_FAILED_FILES) | {_FAILED_FACTS}
        root_fd, _, inputs_fd, attempts_fd = self.descriptors[:4]
        dirs = {
            "producer": root_fd,
            "inputs": inputs_fd,
            "attempts": attempts_fd,
            "release_root": self.release_fd,
        }
        dirs["attempt"] = self._directory(
            attempts_fd, source, self.root / "attempts" / source, names
        )
        bindings = {
            "namespace.json": (root_fd, "namespace.json", 1, 4096, False),
            "producer.lock": (root_fd, "producer.lock", 0, 0, False),
            "inputs/" + source + ".tar": (inputs_fd, source + ".tar", 1, 16777216, False),
        }
        for name in sorted(_FAILED_FILES):
            low, high = _SLOTS[name]
            bindings["attempt/" + name] = (dirs["attempt"], name, low, high, False)
        retained = {name: self._read(binding) for name, binding in bindings.items()}
        return dirs, bindings, retained

    def _validate_failed(self, source: str) -> None:
        from infra.hybrid.stock_build_profile import check_failed_capacity
        from infra.hybrid.stock_failed_build_inputs import (
            inspect_failed_build,
            validate_failed_facts,
        )

        dirs, bindings, retained = self.failed_inputs(source)
        evidence = inspect_failed_build(
            source,
            retained["namespace.json"][0],
            retained["inputs/" + source + ".tar"][0],
            {name: retained["attempt/" + name][0] for name in _FAILED_FILES},
        )
        binding = (dirs["attempt"], _FAILED_FACTS, 1, 16384, False)
        raw, stamp = self._read(binding)
        facts = validate_failed_facts(
            raw,
            evidence,
            directories={
                name: [os.fstat(fd).st_dev, os.fstat(fd).st_ino] for name, fd in dirs.items()
            },
            files={
                name: {"sha256": _sha(value), "fingerprint": list(pin)}
                for name, (value, pin) in retained.items()
            },
        )
        completed = facts["reconciled_clock"]
        _require(_clock_key(completed["utc"]) <= _clock_key(self.origin["utc"]))
        if completed["boot_id"] == self.origin["boot_id"]:
            _require(completed["monotonic_ns"] <= self.origin["monotonic_ns"])
        check_failed_capacity(facts["capacity"])
        self.check()
        for name, original_binding in bindings.items():
            value, pin = retained[name]
            self._flush(original_binding, _sha(value), pin)
        self._flush(binding, _sha(raw), stamp)
        for fd in dirs.values():
            os.fsync(fd)
            self.check()

    def _validate_successful(self, source: str) -> None:
        release_fd = self.release_fd
        _require(release_fd is not None)
        if release_fd is None:
            raise ValueError("stock_producer_unavailable")
        root_fd, _, inputs_fd, attempts_fd = self.descriptors[:4]
        path = self.root / "attempts" / source
        dirs = {
            "producer": root_fd,
            "inputs": inputs_fd,
            "attempts": attempts_fd,
            "release_root": release_fd,
        }
        dirs["attempt"] = self._directory(
            attempts_fd, source, path, set(_ATTEMPT_FILES) | {"render", "terminal.json"}
        )
        dirs["render"] = self._directory(
            dirs["attempt"], "render", path / "render", set(_RENDER_FILES) | set(_EMPTY_DIRS)
        )
        for name in _EMPTY_DIRS:
            dirs[name] = self._directory(dirs["render"], name, path / "render" / name, set())
        dirs["release"] = self._directory(
            release_fd, source, self.release_root / source, set(release._ARTIFACTS)
        )
        bindings = _bindings(dirs, source)
        retained = {name: self._read(binding) for name, binding in bindings.items()}
        terminal_binding = (dirs["attempt"], "terminal.json", 1, 8192, False)
        terminal_raw, terminal_stamp = self._read(terminal_binding)
        terminal = _json(terminal_raw)
        identities = {
            fd: identity
            for (fd, _), identity in zip(self.directories, self.directory_ids, strict=True)
        }
        image = _chain(
            {name: raw for name, (raw, _) in retained.items()},
            source,
            self.root,
            self.release_root,
            self.namespace,
            terminal,
            self.uid,
        )
        _require(
            release._exact(
                terminal,
                {
                    "schema_version": 1,
                    "kind": "stock_producer_terminal_facts",
                    "namespace_id": self.namespace["namespace_id"],
                    "source_sha256": source,
                    "image_digest": image,
                    "native_complete": True,
                    "origin": terminal["origin"],
                    "producer_deadline_ns": terminal["producer_deadline_ns"],
                    "native_complete_clock": terminal["native_complete_clock"],
                    "directories": {name: list(identities[fd]) for name, fd in dirs.items()},
                    "files": {
                        name: {"sha256": _sha(raw), "fingerprint": list(stamp)}
                        for name, (raw, stamp) in retained.items()
                    },
                },
            )
        )
        completed = terminal["native_complete_clock"]
        _require(_clock_key(completed["utc"]) <= _clock_key(self.origin["utc"]))
        if completed["boot_id"] == self.origin["boot_id"]:
            _require(completed["monotonic_ns"] <= self.origin["monotonic_ns"])
        for name, binding in bindings.items():
            raw, stamp = retained[name]
            self._flush(binding, _sha(raw), stamp)
        self._flush(terminal_binding, _sha(terminal_raw), terminal_stamp)
        for fd, _ in self.directories:
            os.fsync(fd)
            self.check()


def _admit(*, source_sha256: str, **kwargs: Any) -> _History:
    # The caller already owns the actual permanent exclusive lock. No source can
    # replace itself, even when its old terminal bytes are readable and valid.
    _require(source_sha256 not in os.listdir(kwargs["descriptors"][3]))
    history = _History(**kwargs)
    for source in sorted(history.sources):
        history.validate(source)
    history.check()
    return history


def _chain(
    raws: dict[str, bytes],
    source_id: str,
    root: Path,
    release_root: Path,
    namespace: dict[str, Any],
    terminal: dict[str, Any],
    uid: int,
) -> str:
    """Revalidate every original semantic/hash link; no native operation occurs."""
    from infra.hybrid.stock_build_engine import _body, _source_request
    from infra.hybrid.stock_build_legacy import _body as legacy_body
    from infra.hybrid.stock_build_legacy import _source_request as legacy_request
    from infra.hybrid.stock_compose_render import _COMPOSE_VERSIONS, _recipe

    raw = {
        name.removeprefix("attempt/"): data
        for name, data in raws.items()
        if name.startswith("attempt/")
    }
    documents = {name: _json(data) for name, data in raw.items() if name.endswith(".json")}
    origin, end = terminal["origin"], terminal["native_complete_clock"]
    deadline = terminal["producer_deadline_ns"]
    _require(type(deadline) is int and deadline == origin["monotonic_ns"] + 1_200_000_000_000)
    clocks = [origin]

    def clock(value: Any) -> Any:
        _require(type(value) is dict and set(value) == {"boot_id", "utc", "monotonic_ns"})
        _check_clock(value)
        _require(
            value["boot_id"] == origin["boot_id"]
            and origin["monotonic_ns"] <= value["monotonic_ns"] < deadline
        )
        return value

    clock(origin)

    def expected(name: str, kind: str, **fields: Any) -> None:
        _require(
            release._exact(
                documents[name],
                {
                    "schema_version": 1,
                    "kind": kind,
                    "namespace_id": namespace["namespace_id"],
                    "source_sha256": source_id,
                    **fields,
                },
            )
        )

    source = inspect_source(raw["source.tar"], expected_sha256=source_id)
    _require(raws["inputs/" + source_id + ".tar"] == source.raw)
    _require(
        raws["namespace.json"] == release._canonical(namespace) and raws["producer.lock"] == b""
    )
    preparation = documents["source-preparation.json"]
    expected(
        "source-preparation.json",
        "stock_source_preparation",
        commit=source.commit,
        source_copy_sha256=source_id,
        started_clock=clock(preparation["started_clock"]),
        completed_clock=clock(preparation["completed_clock"]),
    )
    clocks.extend((preparation["started_clock"], preparation["completed_clock"]))
    engine = verify_engine_version(raw["engine.bin"])
    _require(
        _object(raw["engine.bin"]).get("Version") == "29.1.3" and engine.architecture == "amd64"
    )
    legacy_wire = raw["build-request.http"] == legacy_request(source)
    if not legacy_wire:
        _require(raw["build-request.http"] == _source_request(source))
    dispatch = documents["dispatch.json"]
    build_cap = dispatch["build_deadline_ns"]
    dispatched = clock(dispatch["dispatch_clock"])
    _require(
        type(build_cap) is int
        and dispatched["monotonic_ns"] < build_cap <= deadline
        and build_cap - dispatched["monotonic_ns"] <= 900_000_000_000
    )
    expected(
        "dispatch.json",
        "stock_build_dispatch",
        source_copy_sha256=source_id,
        source_preparation_sha256=_sha(raw["source-preparation.json"]),
        engine_sha256=_sha(raw["engine.bin"]),
        request_sha256=_sha(raw["build-request.http"]),
        build_deadline_ns=build_cap,
        producer_deadline_ns=deadline,
        origin=origin,
        dispatch_clock=dispatched,
    )
    response_body = (legacy_body if legacy_wire else _body)(raw["build-response.http"])
    image_id = build_image_id(response_body)
    verify_image(raw["image.bin"], image_id, engine)
    build = documents["build-complete.json"]
    completed = clock(build["completed_clock"])
    _require(completed["monotonic_ns"] < build_cap)
    expected(
        "build-complete.json",
        "stock_build_complete",
        image_digest=image_id,
        dispatch_sha256=_sha(raw["dispatch.json"]),
        response_sha256=_sha(raw["build-response.http"]),
        image_sha256=_sha(raw["image.bin"]),
        build_deadline_ns=build_cap,
        completed_clock=completed,
    )
    clocks.extend((dispatched, completed))
    probe_intent, probe = documents["probe-intent.json"], documents["probe-result.json"]
    expected(
        "probe-intent.json",
        "stock_producer_probe_intent",
        image_digest=image_id,
        build_complete_sha256=_sha(raw["build-complete.json"]),
        started_clock=clock(probe_intent["started_clock"]),
    )
    _require(
        type(probe["probe_id"]) is str
        and re.fullmatch(r"[0-9a-f]{32}", probe["probe_id"]) is not None
    )
    _require(
        type(probe["container_id"]) is str
        and re.fullmatch(r"[0-9a-f]{64}", probe["container_id"]) is not None
    )
    configuration = raw["configuration.bin"]
    _require(release.normalize_configuration_observation(configuration) == configuration)
    expected(
        "probe-result.json",
        "stock_producer_probe_result",
        image_digest=image_id,
        probe_id=probe["probe_id"],
        container_id=probe["container_id"],
        status="succeeded",
        reason="completed",
        configuration_sha256=_sha(configuration),
        build_complete_sha256=_sha(raw["build-complete.json"]),
        probe_intent_sha256=_sha(raw["probe-intent.json"]),
        completed_clock=clock(probe["completed_clock"]),
    )
    clocks.extend((probe_intent["started_clock"], probe["completed_clock"]))
    workspace = root / "attempts" / source_id / "render"
    attestation = release_root / source_id / "runtime-image-attestation.json"
    version_argv, render_argv, env = _recipe(image_id, attestation, workspace)
    _require(
        raws["render/compose-template.yml"] == source.compose_template
        and raws["render/compose.env"] == b""
    )
    rendering, rendered = documents["render-intent.json"], documents["render-complete.json"]
    expected(
        "render-intent.json",
        "stock_producer_render_intent",
        image_digest=image_id,
        probe_result_sha256=_sha(raw["probe-result.json"]),
        configuration_sha256=_sha(configuration),
        template_sha256=_sha(source.compose_template),
        env_file_sha256=_sha(b""),
        version_argv=list(version_argv),
        render_argv=list(render_argv),
        cwd=str(workspace),
        environment=env,
        started_clock=clock(rendering["started_clock"]),
    )
    _require(
        raw["compose-version.stdout"] in _COMPOSE_VERSIONS
        and raw["compose-version.stderr"] == raw["compose-render.stderr"] == b""
    )
    model = json.loads(
        raw["compose-render.stdout"],
        object_pairs_hook=release._pairs,
        parse_constant=release._constant,
    )
    _require(release._exact(model, release._policy(image_id, attestation)))
    compose = release._canonical(model)
    expected(
        "render-complete.json",
        "stock_producer_render_complete",
        image_digest=image_id,
        probe_result_sha256=_sha(raw["probe-result.json"]),
        render_intent_sha256=_sha(raw["render-intent.json"]),
        version_sha256=_sha(raw["compose-version.stdout"]),
        version_stderr_sha256=_sha(b""),
        render_sha256=_sha(raw["compose-render.stdout"]),
        render_stderr_sha256=_sha(b""),
        compose_sha256=_sha(compose),
        completed_clock=clock(rendered["completed_clock"]),
    )
    clocks.extend((rendering["started_clock"], rendered["completed_clock"]))
    manifest_path = release_root / source_id / "manifest.json"
    loaded = (
        release.load_release(manifest_path)
        if root == PRODUCER_ROOT
        else release._load_release(manifest_path, trusted_uid=uid, release_root=release_root)
    )
    _require(
        loaded.image_digest == image_id
        and loaded.compose_bytes == compose
        and raws["release/stock-configuration.json"] == configuration
    )
    files = {name: _sha(raws["release/" + name]) for name in release._ARTIFACTS}
    publishing, published = (
        documents["publication-intent.json"],
        documents["publication-files.json"],
    )
    release_identity = terminal["directories"]["release_root"]
    expected(
        "publication-intent.json",
        "stock_producer_publication_intent",
        image_digest=image_id,
        render_complete_sha256=_sha(raw["render-complete.json"]),
        release_root_device=release_identity[0],
        release_root_inode=release_identity[1],
        files=files,
        started_clock=clock(publishing["started_clock"]),
    )
    expected(
        "publication-files.json",
        "stock_producer_publication_files",
        image_digest=image_id,
        render_complete_sha256=_sha(raw["render-complete.json"]),
        publication_intent_sha256=_sha(raw["publication-intent.json"]),
        files=files,
        completed_clock=clock(published["completed_clock"]),
    )
    clocks.extend((publishing["started_clock"], published["completed_clock"], clock(end)))
    for previous, current in pairwise(clocks):
        _require(
            previous["monotonic_ns"] <= current["monotonic_ns"]
            and _clock_key(previous["utc"]) <= _clock_key(current["utc"])
        )
    return image_id
