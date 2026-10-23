"""Bounded supplied negative facts; never I/O, native authority or release success.

Every encoded observation is caller-supplied data. The root owner must separately
obtain fresh observations, hold the actual lease and durably bind original files.
Historical capacity observations never establish current filesystem headroom.
"""

from __future__ import annotations

import hashlib
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any, NoReturn

from infra.hybrid.stock_attempts import _canonical, _check_clock, _integer
from infra.hybrid.stock_build_cohorts import _source_cohort
from infra.hybrid.stock_build_inputs import build_image_id, inspect_source
from infra.hybrid.stock_build_legacy import _body, _source_request
from infra.hybrid.stock_container import _object, verify_engine_version
from infra.hybrid.stock_probe_store import _clock_key

_ENGINE_SHA256 = "657cc3c9b56b63ae49d7e175d83afa6eabdb68637ad552e26e015f43f0733d3a"
_OWNER_UID = 0
_OWNER_GID = 0
_BINARY_SHA256 = "237b0603cc24496c74433aeb32d70a16931ae7e015f183b8f3c7c7db83c72a5f"
_BINARY_BYTES = 83879288
_SERVICE_SHA256 = "2e35580df3c26dc898440289f4abad013fbd62722f00c93f994dba002e468873"
_SOCKET_SHA256 = "96c04477e86bd6f724560f3a78b7c0b00b539d5254a251d247641029fc7ad92e"
_PRODUCER_WINDOW = 1_200_000_000_000
_BUILD_WINDOW = 900_000_000_000
_RECONCILER_WINDOW = 120_000_000_000
_FACTS_LIMIT = 16384
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[0-9a-f]{32}\Z")
_ERRORS = (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError, AttributeError)
_ORIGINAL_LIMITS = {
    "source.tar": 16777216,
    "source-preparation.json": 4096,
    "engine.bin": 1048576,
    "build-request.http": 16777216 + 8192,
    "dispatch.json": 4096,
    "build-response.http": 1048576 + 8192,
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
_CLOCK_KEYS = {"boot_id", "utc", "monotonic_ns"}
_OBSERVATION_KEYS = {
    "reconciler_origin",
    "reconciler_deadline_ns",
    "reconciled_clock",
    "daemon_profile",
    "capacity",
}
_DAEMON_KEYS = {
    "profile_id",
    "binary_sha256",
    "binary_bytes",
    "peer_pid",
    "daemon_pid",
    "daemon_start_boottime_upper_ns",
    "socket_activation",
    "boot_id",
    "observed_clock",
    "source_profile_id",
    "source_tree",
    "docker_root",
}
_SOCKET_KEYS = {
    "mode",
    "service_unit_sha256",
    "socket_unit_sha256",
    "listener_inode",
    "socket_file_fingerprint",
}
_DIRECTORY_KEYS = {"producer", "inputs", "attempts", "attempt", "release_root"}
_CAPACITY_PATHS = {
    "producer": "/var/lib/hybrid-stock-producer",
    "release_root": "/opt/hybrid-stock-research/releases",
    "docker": "/var/lib/docker",
}


def _deny() -> NoReturn:
    raise ValueError("stock_failed_build_inputs_unavailable") from None


def _require(condition: bool) -> None:
    if not condition:
        _deny()


def _closed(value: Any, keys: set[str]) -> None:
    _require(type(value) is dict)
    _require(all(type(key) is str for key in value) and set(value) == keys)


def _literal(value: Any, expected: Any) -> None:
    _require(type(value) is type(expected) and value == expected)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(raw: bytes, limit: int = 4096) -> dict[str, Any]:
    _require(type(raw) is bytes and 0 < len(raw) <= limit)
    value = _object(raw)
    _require(_canonical(value) == raw)
    return value


def _clock(value: Any) -> dict[str, Any]:
    _closed(value, _CLOCK_KEYS)
    _check_clock(value)
    _clock_key(value["utc"])
    return dict(value)


def _utc_ns(value: dict[str, Any]) -> int:
    """Exact integer UTC nanoseconds; datetime.timestamp would lose precision."""
    second, fraction = _clock_key(value["utc"])
    parsed = datetime.fromisoformat(second).replace(tzinfo=UTC)
    elapsed = parsed - datetime(1970, 1, 1, tzinfo=UTC)
    return (elapsed.days * 86400 + elapsed.seconds) * 1_000_000_000 + int(fraction)


def _ordered(clocks: list[dict[str, Any]]) -> None:
    for previous, current in pairwise(clocks):
        _require(
            previous["boot_id"] == current["boot_id"]
            and previous["monotonic_ns"] <= current["monotonic_ns"]
            and _clock_key(previous["utc"]) <= _clock_key(current["utc"])
        )


@dataclass(frozen=True, slots=True, repr=False)
class FailedBuildEvidence:
    """Immutable parsed data; construction or possession grants no authority."""

    namespace_id: str
    source_sha256: str
    source_commit: str
    image_digest: str
    _namespace_raw: bytes
    _input_raw: bytes
    _original_raw: tuple[tuple[str, bytes], ...]
    _origin_raw: bytes
    _dispatch_raw: bytes
    _preparation_started_raw: bytes
    _preparation_completed_raw: bytes

    @property
    def original_origin(self) -> dict[str, Any]:
        return _json(self._origin_raw)

    @property
    def original_dispatch_clock(self) -> dict[str, Any]:
        return _json(self._dispatch_raw)

    @property
    def preparation_started_clock(self) -> dict[str, Any]:
        return _json(self._preparation_started_raw)

    @property
    def preparation_completed_clock(self) -> dict[str, Any]:
        return _json(self._preparation_completed_raw)

    @property
    def original_hashes(self) -> dict[str, str]:
        return {name: _sha(raw) for name, raw in self._original_raw}

    def _file_bytes(self) -> dict[str, bytes]:
        return {
            "namespace.json": self._namespace_raw,
            "producer.lock": b"",
            "inputs/" + self.source_sha256 + ".tar": self._input_raw,
            **{"attempt/" + name: raw for name, raw in self._original_raw},
        }

    @property
    def file_hashes(self) -> dict[str, str]:
        return {name: _sha(raw) for name, raw in self._file_bytes().items()}

    @property
    def file_sizes(self) -> dict[str, int]:
        return {name: len(raw) for name, raw in self._file_bytes().items()}


def inspect_failed_build(
    source_sha256: str, namespace_raw: bytes, input_raw: bytes, original: dict[str, bytes]
) -> FailedBuildEvidence:
    """Decode the qualified six-file witness without extraction or native I/O."""
    try:
        _require(type(source_sha256) is str and _HEX.fullmatch(source_sha256) is not None)
        _closed(original, set(_ORIGINAL_LIMITS))
        for name, limit in _ORIGINAL_LIMITS.items():
            _require(type(original[name]) is bytes and 0 < len(original[name]) <= limit)
        _require(type(input_raw) is bytes and input_raw == original["source.tar"])
        source = inspect_source(input_raw, expected_sha256=source_sha256)
        cohort = _source_cohort(source.digest)
        _literal(source.commit, cohort.commit)
        namespace = _json(namespace_raw)
        _closed(namespace, _NAMESPACE_KEYS)
        _literal(namespace["schema_version"], 1)
        _literal(namespace["kind"], "stock_producer_namespace")
        _require(
            type(namespace["namespace_id"]) is str
            and _ID.fullmatch(namespace["namespace_id"]) is not None
        )
        for key in ("root_device", "lock_device", "root_inode", "lock_inode"):
            _require(_integer(namespace[key], 1 if key.endswith("inode") else 0))

        preparation = _json(original["source-preparation.json"])
        dispatch = _json(original["dispatch.json"])
        origin = _clock(dispatch["origin"])
        started = _clock(preparation["started_clock"])
        completed = _clock(preparation["completed_clock"])
        dispatched = _clock(dispatch["dispatch_clock"])
        _ordered([origin, started, completed, dispatched])
        deadline, build_cap = dispatch["producer_deadline_ns"], dispatch["build_deadline_ns"]
        _require(_integer(deadline, 1) and deadline == origin["monotonic_ns"] + _PRODUCER_WINDOW)
        _require(
            _integer(build_cap, 1)
            and dispatched["monotonic_ns"] < build_cap <= deadline
            and build_cap - dispatched["monotonic_ns"] <= _BUILD_WINDOW
        )
        common = {
            "schema_version": 1,
            "namespace_id": namespace["namespace_id"],
            "source_sha256": source_sha256,
        }
        _require(
            _canonical(
                {
                    **common,
                    "kind": "stock_source_preparation",
                    "commit": source.commit,
                    "source_copy_sha256": source_sha256,
                    "started_clock": started,
                    "completed_clock": completed,
                }
            )
            == original["source-preparation.json"]
        )
        version = verify_engine_version(original["engine.bin"])
        engine = _object(original["engine.bin"])
        _require(_sha(original["engine.bin"]) == _ENGINE_SHA256)
        for key, expected in (
            ("Version", "29.1.3"),
            ("ApiVersion", "1.52"),
            ("GitCommit", "29.1.3-0ubuntu3~24.04.2"),
        ):
            _literal(engine[key], expected)
        _require(version.architecture == "amd64")
        _require(original["build-request.http"] == _source_request(source))
        _require(
            _canonical(
                {
                    **common,
                    "kind": "stock_build_dispatch",
                    "source_copy_sha256": source_sha256,
                    "source_preparation_sha256": _sha(original["source-preparation.json"]),
                    "engine_sha256": _sha(original["engine.bin"]),
                    "request_sha256": _sha(original["build-request.http"]),
                    "origin": origin,
                    "build_deadline_ns": build_cap,
                    "producer_deadline_ns": deadline,
                    "dispatch_clock": dispatched,
                }
            )
            == original["dispatch.json"]
        )
        image = build_image_id(_body(original["build-response.http"]))
        return FailedBuildEvidence(
            namespace["namespace_id"],
            source_sha256,
            source.commit,
            image,
            namespace_raw,
            input_raw,
            tuple(sorted(original.items())),
            _canonical(origin),
            _canonical(dispatched),
            _canonical(started),
            _canonical(completed),
        )
    except _ERRORS:
        _deny()


def _evidence(value: FailedBuildEvidence) -> FailedBuildEvidence:
    _require(type(value) is FailedBuildEvidence)
    _require(
        all(
            type(item) is str
            for item in (
                value.namespace_id,
                value.source_sha256,
                value.source_commit,
                value.image_digest,
            )
        )
    )
    _require(
        all(
            type(item) is bytes
            for item in (
                value._namespace_raw,
                value._input_raw,
                value._origin_raw,
                value._dispatch_raw,
                value._preparation_started_raw,
                value._preparation_completed_raw,
            )
        )
    )
    _require(
        type(value._original_raw) is tuple and len(value._original_raw) == len(_ORIGINAL_LIMITS)
    )
    _require(
        all(
            type(row) is tuple and len(row) == 2 and type(row[0]) is str and type(row[1]) is bytes
            for row in value._original_raw
        )
    )
    checked = inspect_failed_build(
        value.source_sha256, value._namespace_raw, value._input_raw, dict(value._original_raw)
    )
    _require(value == checked)
    return checked


def _fingerprint(value: Any) -> list[int]:
    _require(type(value) is list and len(value) == 9)
    _require(all(_integer(item) for item in value) and value[1] > 0 and value[5] == 1)
    return list(value)


def _bindings(
    evidence: FailedBuildEvidence,
    directories: dict[str, list[int]],
    files: dict[str, dict[str, Any]],
) -> None:
    _closed(directories, _DIRECTORY_KEYS)
    for identity in directories.values():
        _require(
            type(identity) is list
            and len(identity) == 2
            and _integer(identity[0])
            and _integer(identity[1], 1)
        )
    _require(len({tuple(identity) for identity in directories.values()}) == len(directories))
    namespace = _json(evidence._namespace_raw)
    _require(directories["producer"] == [namespace["root_device"], namespace["root_inode"]])
    hashes, sizes = evidence.file_hashes, evidence.file_sizes
    _closed(files, set(hashes))
    identities = set()
    for name, entry in files.items():
        _closed(entry, {"sha256", "fingerprint"})
        _literal(entry["sha256"], hashes[name])
        stamp = _fingerprint(entry["fingerprint"])
        _require(stamp[2:7] == [stat.S_IFREG | 0o600, _OWNER_UID, _OWNER_GID, 1, sizes[name]])
        role = (
            "attempt"
            if name.startswith("attempt/")
            else "inputs"
            if name.startswith("inputs/")
            else "producer"
        )
        _require(stamp[0] == directories[role][0])
        file_identity = (stamp[0], stamp[1])
        _require(
            file_identity not in identities and list(file_identity) not in directories.values()
        )
        identities.add(file_identity)
    _require(
        files["producer.lock"]["fingerprint"][:2]
        == [namespace["lock_device"], namespace["lock_inode"]]
    )


def _observation(
    value: dict[str, Any],
    evidence: FailedBuildEvidence,
    directories: dict[str, list[int]],
) -> None:
    _closed(value, _OBSERVATION_KEYS)
    origin, end = _clock(value["reconciler_origin"]), _clock(value["reconciled_clock"])
    deadline = value["reconciler_deadline_ns"]
    _require(_integer(deadline, 1) and deadline == origin["monotonic_ns"] + _RECONCILER_WINDOW)
    original, dispatched = evidence.original_origin, evidence.original_dispatch_clock
    _require(origin["monotonic_ns"] > dispatched["monotonic_ns"])
    daemon = value["daemon_profile"]
    _closed(daemon, _DAEMON_KEYS)
    cohort = _source_cohort(evidence.source_sha256)
    expected: dict[str, Any] = {
        "profile_id": "ubuntu-docker-legacy-q-29.1.3-v1",
        "binary_sha256": _BINARY_SHA256,
        "binary_bytes": _BINARY_BYTES,
        "peer_pid": 1,
        "boot_id": original["boot_id"],
        "source_profile_id": cohort.profile_id,
        "source_tree": cohort.tree,
        "docker_root": _CAPACITY_PATHS["docker"],
    }
    for key, required in expected.items():
        _literal(daemon[key], required)
    _require(_integer(daemon["daemon_pid"], 2))
    upper = daemon["daemon_start_boottime_upper_ns"]
    _require(_integer(upper, 1) and upper < original["monotonic_ns"])
    observed = _clock(daemon["observed_clock"])
    _ordered([dispatched, origin, observed, end])
    _require(end["monotonic_ns"] < deadline)
    socket = daemon["socket_activation"]
    _closed(socket, _SOCKET_KEYS)
    for key, required in (
        ("mode", "systemd_socket_activation"),
        ("service_unit_sha256", _SERVICE_SHA256),
        ("socket_unit_sha256", _SOCKET_SHA256),
    ):
        _literal(socket[key], required)
    _require(_integer(socket["listener_inode"], 1))
    stamp = _fingerprint(socket["socket_file_fingerprint"])
    _require(
        stat.S_ISSOCK(stamp[2])
        and stamp[2] & 0o007 == 0
        and stamp[3] == 0
        and stamp[8] < _utc_ns(original)
    )
    _closed(value["capacity"], set(_CAPACITY_PATHS))
    for name, path in _CAPACITY_PATHS.items():
        capacity = value["capacity"][name]
        _closed(capacity, {"path", "device", "inode", "available_bytes", "available_inodes"})
        _literal(capacity["path"], path)
        _require(
            _integer(capacity["device"])
            and _integer(capacity["inode"], 1)
            and _integer(capacity["available_bytes"], 5 * 1024**3)
            and _integer(capacity["available_inodes"], 4096)
        )
        if name in directories:
            _require([capacity["device"], capacity["inode"]] == directories[name])


def encode_failed_facts(
    evidence: FailedBuildEvidence,
    *,
    observation: dict[str, Any],
    directories: dict[str, list[int]],
    files: dict[str, dict[str, Any]],
) -> bytes:
    """Encode negative observations; does not authenticate them or write anything."""
    try:
        evidence = _evidence(evidence)
        _bindings(evidence, directories, files)
        _observation(observation, evidence, directories)
        raw = _canonical(
            {
                "schema_version": 1,
                "kind": "stock_failed_build_terminal_facts",
                "namespace_id": evidence.namespace_id,
                "source_sha256": evidence.source_sha256,
                "source_commit": evidence.source_commit,
                "image_digest": evidence.image_digest,
                "backend_terminal": True,
                "producer_success": False,
                "release_qualified": False,
                "cleanup_qualified": False,
                "source_replay_permitted": False,
                "original_origin": evidence.original_origin,
                "original_dispatch_clock": evidence.original_dispatch_clock,
                **observation,
                "directories": directories,
                "files": files,
            }
        )
        _require(len(raw) <= _FACTS_LIMIT)
        return raw
    except _ERRORS:
        _deny()


def validate_failed_facts(
    raw: bytes,
    evidence: FailedBuildEvidence,
    *,
    directories: dict[str, list[int]],
    files: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Revalidate data against supplied fresh pins; never a caller acknowledgement."""
    try:
        value = _json(raw, _FACTS_LIMIT)
        observation = {key: value[key] for key in _OBSERVATION_KEYS}
        expected = encode_failed_facts(
            evidence, observation=observation, directories=directories, files=files
        )
        _require(raw == expected)
        return value
    except _ERRORS:
        _deny()
