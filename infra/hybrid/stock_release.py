"""Read-only verification of an immutable, root-owned stock research release.

This verifies retained artifacts, not their production or an executing container.
There is no Docker, credential, ledger, control or activation operation here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RELEASE_ROOT = Path("/opt/hybrid-stock-research/releases")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ARTIFACTS = {
    "manifest.json": 4096,
    "stock-compose.resolved.json": 65536,
    "stock-configuration.json": 4096,
    "runtime-image-attestation.json": 4096,
}
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


@dataclass(frozen=True)
class StockRelease:
    release_id: str
    image_digest: str
    config_hash: str
    compose_sha256: str
    max_run_seconds: int
    scan_interval_seconds: int
    attestation_path: Path
    compose_path: Path
    compose_bytes: bytes


def _deny() -> None:
    raise ValueError("stock_release_unavailable")


def _require(condition: bool) -> None:
    if not condition:
        _deny()


def _hex(value: Any) -> bool:
    return type(value) is str and _HEX.fullmatch(value) is not None


def _integer(value: Any, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _exact(left: Any, right: Any) -> bool:
    """Equality must not accept booleans in place of integer policy fields."""
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(_exact(left[key], right[key]) for key in left)
    if type(left) is list:
        return len(left) == len(right) and all(
            _exact(a, b) for a, b in zip(left, right, strict=True)
        )
    return bool(left == right)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _constant(_value: str) -> None:
    _deny()


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def _fingerprint(value: os.stat_result) -> tuple[int, ...]:
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


def _close_all(descriptors: Iterable[int]) -> None:
    failed = False
    for descriptor in descriptors:
        try:
            os.close(descriptor)
        except OSError:
            # A failed close can already have released/reused its descriptor.
            # Never retry it; still attempt cleanup of every other owned handle.
            failed = True
    if failed:
        raise ValueError("stock_release_unavailable") from None


def _open_directory(path: Path, *, trusted_uid: int, release_root: Path) -> int:
    """Traverse every component without following links; check the trust namespace.

    Public production loads also require root-owned non-writable ancestors. The
    private fixture seam checks its selected root and descendants, allowing tests
    in an ordinary user's temporary directory without weakening the public API.
    """
    descriptor = os.open("/", _DIRECTORY_FLAGS)
    try:
        current = Path("/")
        for component in path.parts[1:]:
            child = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
            previous = descriptor
            descriptor = child
            os.close(previous)
            current /= component
            info = os.fstat(descriptor)
            _require(stat.S_ISDIR(info.st_mode))
            if release_root == RELEASE_ROOT or current.is_relative_to(release_root):
                _require(info.st_uid == trusted_uid and info.st_mode & 0o022 == 0)
        return descriptor
    except BaseException:
        _close_all((descriptor,))
        raise


def _read_artifact(
    directory: int, name: str, limit: int, trusted_uid: int
) -> tuple[bytes, Any, tuple[int, ...]]:
    descriptor = os.open(name, _FILE_FLAGS, dir_fd=directory)
    try:
        before = os.fstat(descriptor)
        _require(
            stat.S_ISREG(before.st_mode)
            and stat.S_IMODE(before.st_mode) == 0o444
            and before.st_uid == trusted_uid
            and before.st_nlink == 1
            and 0 < before.st_size <= limit
        )
        body = b""
        while len(body) <= limit:
            chunk = os.read(descriptor, min(8192, limit + 1 - len(body)))
            if not chunk:
                break
            body += chunk
        _require(len(body) == before.st_size and len(body) <= limit)
        stamp = _fingerprint(before)
        _require(stamp == _fingerprint(os.fstat(descriptor)))
        _require(stamp == _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False)))
    finally:
        _close_all((descriptor,))
    value = json.loads(body.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    _require(type(value) is dict and _canonical(value) == body)
    return body, value, stamp


def _policy(image: str, attestation: Path) -> dict[str, Any]:
    volumes: list[dict[str, Any]] = [
        {
            "type": "bind",
            "source": "/var/lib/hybrid-stock-research/" + name,
            "target": "/stock-" + name,
            "bind": {"create_host_path": False},
        }
        for name in ("state", "archive", "controls", "exports", "oauth")
    ]
    volumes.append(
        {
            "type": "bind",
            "source": str(attestation),
            "target": "/run/trading-bot/stock-image-attestation.json",
            "read_only": True,
            "bind": {"create_host_path": False},
        }
    )
    return {
        "name": "hybrid-stock-research",
        "services": {
            "stock-research": {
                "image": image,
                "pull_policy": "never",
                "user": "10001:10001",
                "read_only": True,
                "init": True,
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"],
                "pids_limit": 128,
                "cpus": 0.5,
                "mem_limit": "536870912",
                "memswap_limit": "536870912",
                "restart": "no",
                "stop_signal": "SIGTERM",
                "stop_grace_period": "10s",
                "network_mode": "bridge",
                "healthcheck": {"disable": True},
                "volumes": volumes,
                # Comparison-only Docker policy; no host temporary file is opened.
                "tmpfs": ["/tmp:size=32m,mode=1777,noexec,nosuid,nodev"],  # nosec B108
                "environment": {
                    "LIVE_TRADING_ENABLED": "false",
                    "PREDICTION_LIVE_ENABLED": "false",
                },
                "entrypoint": ["python", "-m", "trading_bot.runtime.stock_research_worker"],
                "command": [
                    "--config-root",
                    "/app/configs",
                    "--database",
                    "/stock-state/ledger.sqlite3",
                    "--oauth-store",
                    "/stock-oauth",
                    "--archive-dir",
                    "/stock-archive",
                    "--control-dir",
                    "/stock-controls",
                    "--export-dir",
                    "/stock-exports",
                    "--image-digest",
                    image,
                    "--image-attestation",
                    "/run/trading-bot/stock-image-attestation.json",
                ],
                "logging": {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}},
            }
        },
    }


def _validate_manifest(value: dict[str, Any], release_id: str) -> None:
    _require(
        set(value)
        == {
            "schema_version",
            "kind",
            "release_id",
            "image_digest",
            "config_hash",
            "compose_sha256",
            "configuration_observation_sha256",
            "max_run_seconds",
            "scan_interval_seconds",
        }
    )
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1)
    _require(value["kind"] == "stock_research_release" and value["release_id"] == release_id)
    _require(
        type(value["image_digest"]) is str and _IMAGE.fullmatch(value["image_digest"]) is not None
    )
    for name in ("config_hash", "compose_sha256", "configuration_observation_sha256"):
        _require(_hex(value[name]))
    _require(_integer(value["max_run_seconds"], 60, 450))
    _require(_integer(value["scan_interval_seconds"], 900, 3600))
    _require(value["scan_interval_seconds"] % 60 == 0)


def _validate_configuration_observation(value: dict[str, Any]) -> None:
    _require(
        set(value)
        == {
            "status",
            "schema_version",
            "kind",
            "config_hash",
            "scan_interval_seconds",
            "max_run_seconds",
            "max_daily_calls",
            "max_calls_per_cycle",
            "maximum_source_age_seconds",
            "live_enabled",
        }
    )
    _require(
        value["status"] == "succeeded" and value["kind"] == "stock_research_configuration_identity"
    )
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1)
    _require(value["live_enabled"] is False and _hex(value["config_hash"]))
    _require(_integer(value["max_run_seconds"], 60, 450))
    _require(_integer(value["scan_interval_seconds"], 900, 3600))
    _require(value["scan_interval_seconds"] % 60 == 0)
    _require(_integer(value["max_daily_calls"], 1, 1024))
    _require(_integer(value["max_calls_per_cycle"], 1, 32))
    _require(value["max_daily_calls"] >= value["max_calls_per_cycle"])
    _require(_integer(value["maximum_source_age_seconds"], 60, 86400))
    _require(value["maximum_source_age_seconds"] % 60 == 0)


def normalize_configuration_observation(raw: bytes) -> bytes:
    """Normalize supplied probe output only; no image or execution provenance."""
    try:
        _require(type(raw) is bytes and 0 < len(raw) <= 4096)
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
        _require(type(value) is dict)
        _validate_configuration_observation(value)
        return _canonical(value)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise ValueError("stock_release_unavailable") from None


def _validate_observation(value: dict[str, Any], manifest: dict[str, Any]) -> None:
    _validate_configuration_observation(value)
    for name in ("config_hash", "max_run_seconds", "scan_interval_seconds"):
        _require(value[name] == manifest[name])


def _load_release(path: Path, *, trusted_uid: int, release_root: Path) -> StockRelease:
    """Private root/owner injection is solely for fictional filesystem tests."""
    descriptors: list[int] = []
    try:
        _require(type(trusted_uid) is int and trusted_uid >= 0)
        _require(isinstance(path, Path) and isinstance(release_root, Path))
        _require(path.is_absolute() and release_root.is_absolute())
        _require(".." not in path.parts and ".." not in release_root.parts)
        _require(path.name == "manifest.json" and path.parent.parent == release_root)
        release_id = path.parent.name
        _require(_hex(release_id))
        root_fd = _open_directory(release_root, trusted_uid=trusted_uid, release_root=release_root)
        descriptors.append(root_fd)
        root_stamp = _fingerprint(os.fstat(root_fd))
        directory = _open_directory(path.parent, trusted_uid=trusted_uid, release_root=release_root)
        descriptors.append(directory)
        directory_stamp = _fingerprint(os.fstat(directory))
        records = {
            name: _read_artifact(directory, name, limit, trusted_uid)
            for name, limit in _ARTIFACTS.items()
        }
        manifest = records["manifest.json"][1]
        _validate_manifest(manifest, release_id)
        model_bytes, model, _ = records["stock-compose.resolved.json"]
        observation_bytes, observation, _ = records["stock-configuration.json"]
        _require(hashlib.sha256(model_bytes).hexdigest() == manifest["compose_sha256"])
        _require(
            hashlib.sha256(observation_bytes).hexdigest()
            == manifest["configuration_observation_sha256"]
        )
        attestation_path = path.parent / "runtime-image-attestation.json"
        _require(_exact(model, _policy(manifest["image_digest"], attestation_path)))
        _validate_observation(observation, manifest)
        _require(
            _exact(
                records["runtime-image-attestation.json"][1],
                {
                    "schema_version": 1,
                    "image_digest": manifest["image_digest"],
                    "deployment_config_hash": manifest["config_hash"],
                    "compose_sha256": manifest["compose_sha256"],
                    "release_key": "-".join(
                        [
                            manifest["image_digest"][7:],
                            manifest["config_hash"],
                            manifest["compose_sha256"],
                        ]
                    ),
                },
            )
        )
        # Bind the retained bytes to still-named files and the still-named namespace.
        for name, (_, _, stamp) in records.items():
            _require(stamp == _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False)))
        for named, stamp in ((release_root, root_stamp), (path.parent, directory_stamp)):
            check_fd = _open_directory(named, trusted_uid=trusted_uid, release_root=release_root)
            try:
                _require(stamp == _fingerprint(os.fstat(check_fd)))
            finally:
                _close_all((check_fd,))
        return StockRelease(
            release_id=release_id,
            image_digest=manifest["image_digest"],
            config_hash=manifest["config_hash"],
            compose_sha256=manifest["compose_sha256"],
            max_run_seconds=manifest["max_run_seconds"],
            scan_interval_seconds=manifest["scan_interval_seconds"],
            attestation_path=attestation_path,
            compose_path=path.parent / "stock-compose.resolved.json",
            compose_bytes=model_bytes,
        )
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise ValueError("stock_release_unavailable") from None
    finally:
        _close_all(reversed(descriptors))


def load_release(path: Path) -> StockRelease:
    """Production callers cannot override the root-owned release namespace."""
    return _load_release(path, trusted_uid=0, release_root=RELEASE_ROOT)
