"""Private exclusive four-file publication after this lease's owned render.

This is not terminal producer success, historical admission or installation.
All live/worker controls remain untouched. Partial releases are never repaired.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from infra.hybrid import stock_release
from infra.hybrid.stock_release_producer import (
    _WRITE,
    PRODUCER_ROOT,
    _child_directory,
    _deny,
    _Lease,
    _read_binary,
    _require,
    _sanitized,
)


def _artifact(directory: int, name: str, raw: bytes, uid: int) -> tuple[int, ...]:
    limit = stock_release._ARTIFACTS[name]
    _require(type(raw) is bytes and 0 < len(raw) <= limit)
    descriptor = os.open(name, _WRITE, 0o600, dir_fd=directory)
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            _require(type(written) is int and 0 < written <= len(raw) - offset)
            offset += written
        os.fchmod(descriptor, 0o444)
        before = os.fstat(descriptor)
        _require(before.st_size == len(raw))
        stamp = stock_release._fingerprint(before)
        os.fsync(descriptor)
        _require(stamp == stock_release._fingerprint(os.fstat(descriptor)))
        _require(
            stamp
            == stock_release._fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False))
        )
    finally:
        stock_release._close_all((descriptor,))
    os.fsync(directory)
    reread, _, observed = stock_release._read_artifact(directory, name, limit, uid)
    _require(reread == raw and observed == stamp)
    _require(
        stamp == stock_release._fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False))
    )
    return stamp


def _publish_files(lease: _Lease) -> Path:
    """Keep current acknowledgement only after all durable writes and loader checks."""
    with _sanitized():
        _require(type(lease) is _Lease)
        lease.check()
        image, probe, compose = lease.built_image, lease.probe_result, lease.compose_bytes
        if image is None or probe is None or probe.configuration is None or compose is None:
            _deny()
        _require(not lease.publication_started and "render-complete.json" in lease.hashes)
        lease.publication_started = True
        configuration = probe.configuration
        configuration_hash = hashlib.sha256(configuration).hexdigest()
        compose_hash = hashlib.sha256(compose).hexdigest()
        _require(configuration_hash == lease.hashes["configuration.bin"])
        render_raw = _read_binary(lease.attempt_fd, "render-complete.json", lease.uid, 1, 4096)
        _require(hashlib.sha256(render_raw).hexdigest() == lease.hashes["render-complete.json"])
        render = json.loads(render_raw, object_pairs_hook=stock_release._pairs)
        _require(compose_hash == render["compose_sha256"])
        observation = json.loads(configuration, object_pairs_hook=stock_release._pairs)
        _require(stock_release.normalize_configuration_observation(configuration) == configuration)
        config_hash = observation["config_hash"]
        canonical = stock_release._canonical
        files = {
            "stock-configuration.json": configuration,
            "stock-compose.resolved.json": compose,
            "runtime-image-attestation.json": canonical(
                {
                    "schema_version": 1,
                    "image_digest": image.image_digest,
                    "deployment_config_hash": config_hash,
                    "compose_sha256": compose_hash,
                    "release_key": "-".join([image.image_digest[7:], config_hash, compose_hash]),
                }
            ),
            "manifest.json": canonical(
                {
                    "schema_version": 1,
                    "kind": "stock_research_release",
                    "release_id": lease.source.digest,
                    "image_digest": image.image_digest,
                    "config_hash": config_hash,
                    "compose_sha256": compose_hash,
                    "configuration_observation_sha256": configuration_hash,
                    "max_run_seconds": observation["max_run_seconds"],
                    "scan_interval_seconds": observation["scan_interval_seconds"],
                }
            ),
        }
        root = lease.release_fd
        _require(root is not None)
        if root is None:
            raise ValueError("stock_producer_unavailable")
        info = os.fstat(root)
        _require(set(os.listdir(root)) == lease.completed_sources)
        lease.check()
        file_hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}
        lease.record(
            "publication-intent.json",
            {
                "schema_version": 1,
                "kind": "stock_producer_publication_intent",
                "namespace_id": lease.namespace["namespace_id"],
                "source_sha256": lease.source.digest,
                "image_digest": image.image_digest,
                "render_complete_sha256": lease.hashes["render-complete.json"],
                "release_root_device": info.st_dev,
                "release_root_inode": info.st_ino,
                "files": file_hashes,
                "started_clock": lease.check(),
            },
        )
        path = lease.release_root / lease.source.digest
        directory = _child_directory(lease, root, lease.source.digest, path)
        for name, raw in files.items():
            lease.check()
            stamp = _artifact(directory, name, raw, lease.uid)
            lease.inventories[directory].add(name)
            lease.pins.append((directory, name, stamp))
            lease.check()
        manifest = path / "manifest.json"
        if lease.root == PRODUCER_ROOT:
            _require(lease.uid == 0 and lease.release_root == stock_release.RELEASE_ROOT)
            loaded = stock_release.load_release(manifest)
        else:
            loaded = stock_release._load_release(
                manifest, trusted_uid=lease.uid, release_root=lease.release_root
            )
        lease.check()
        _require(
            loaded.release_id == lease.source.digest
            and loaded.image_digest == image.image_digest
            and loaded.compose_bytes == compose
            and loaded.config_hash == config_hash
        )
        lease.record(
            "publication-files.json",
            {
                "schema_version": 1,
                "kind": "stock_producer_publication_files",
                "namespace_id": lease.namespace["namespace_id"],
                "source_sha256": lease.source.digest,
                "image_digest": image.image_digest,
                "render_complete_sha256": lease.hashes["render-complete.json"],
                "publication_intent_sha256": lease.hashes["publication-intent.json"],
                "files": file_hashes,
                "completed_clock": lease.check(),
            },
        )
        lease.check()
        lease.published_manifest = manifest
        return manifest
