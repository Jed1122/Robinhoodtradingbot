"""One owned, scrubbed, bounded render of the reviewed stock Compose template.

This private producer stage never installs, starts, authenticates or activates a
worker. Supplied render bytes and old receipts cannot replace the native calls.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from infra.hybrid.stock_process import _capture, _CaptureFailed
from infra.hybrid.stock_release import (
    _canonical,
    _close_all,
    _constant,
    _exact,
    _fingerprint,
    _open_directory,
    _pairs,
    _policy,
)
from infra.hybrid.stock_release_producer import (
    _READ,
    PRODUCER_ROOT,
    _child_directory,
    _Lease,
    _require,
    _sanitized,
    _write_binary,
)

_DOCKER = Path("/usr/bin/docker")


def _workspace(lease: _Lease) -> Path:
    path = lease.root / "attempts" / lease.source.digest / "render"
    descriptor = _child_directory(lease, lease.attempt_fd, "render", path)
    for name in ("docker-config", "home", "empty-path"):
        _child_directory(lease, descriptor, name, path / name)
    for name, raw in (
        ("compose-template.yml", lease.source.compose_template),
        ("compose.env", b""),
    ):
        lease.check()
        digest, stamp = _write_binary(descriptor, name, raw, lease.uid)
        lease.inventories[descriptor].add(name)
        lease.pins.append((descriptor, name, stamp))
        lease.hashes[name] = digest
        lease.check()
    return path


@contextmanager
def _executable(lease: _Lease) -> Iterator[Callable[[], None]]:
    """Pin the fixed binary and its trusted parent through both child cleanups."""
    trust_root = Path("/") if lease.root == PRODUCER_ROOT else _DOCKER.parent
    parent = _open_directory(_DOCKER.parent, trusted_uid=lease.uid, release_root=trust_root)
    descriptors = [parent]
    try:
        directory_id = (os.fstat(parent).st_dev, os.fstat(parent).st_ino)
        binary = os.open(_DOCKER.name, _READ, dir_fd=parent)
        descriptors.append(binary)
        info = os.fstat(binary)
        _require(
            stat.S_ISREG(info.st_mode)
            and info.st_uid == lease.uid
            and info.st_nlink == 1
            and 0 < info.st_size <= 128 * 1024 * 1024
            and info.st_mode & 0o022 == 0
            and info.st_mode & 0o100 != 0
        )
        stamp = _fingerprint(info)

        def named() -> None:
            _require(stamp == _fingerprint(os.stat(_DOCKER, follow_symlinks=False)))
            current = _open_directory(
                _DOCKER.parent, trusted_uid=lease.uid, release_root=trust_root
            )
            try:
                observed = os.fstat(current)
                _require((observed.st_dev, observed.st_ino) == directory_id)
            finally:
                _close_all((current,))

        def check() -> None:
            _require(stamp == _fingerprint(os.fstat(binary)))
            named()

        check()
        yield check
        check()
    finally:
        _close_all(reversed(descriptors))
    named()


def _invoke(
    lease: _Lease,
    binary_check: Callable[[], None],
    argv: tuple[str, ...],
    workspace: Path,
    env: dict[str, str],
    *,
    version: bool,
) -> tuple[bytes, int]:
    cap = min(lease.deadline_ns, int(lease.check()["monotonic_ns"]) + 5_000_000_000)

    def check() -> None:
        lease.check(not_after_ns=cap)
        binary_check()

    prefix = "compose-version" if version else "compose-render"
    try:
        result = _capture(
            argv,
            cwd=workspace,
            env=env,
            limit=128 if version else 65536,
            deadline=cap / 1_000_000_000,
            check=check,
        )
    except _CaptureFailed as failure:
        # These bounded partial bytes grant no acknowledgement or retry permission.
        lease.retain(prefix + ".stdout", failure.output.stdout)
        lease.retain(prefix + ".stderr", failure.output.stderr)
        raise
    lease.retain(prefix + ".stdout", result.stdout)
    lease.retain(prefix + ".stderr", result.stderr)
    check()
    _require(result.stderr == b"")
    return result.stdout, cap


def _render(lease: _Lease) -> bytes:
    with _sanitized():
        _require(type(lease) is _Lease)
        lease.check()
        _require(
            lease.built_image is not None
            and lease.probe_result is not None
            and not lease.render_started
            and {"probe-result.json", "configuration.bin", "build-complete.json"}
            <= lease.hashes.keys()
        )
        lease.render_started = True
        workspace = _workspace(lease)
        image = lease.built_image
        _require(image is not None)
        if image is None:
            raise ValueError("stock_producer_unavailable")
        attestation = lease.release_root / lease.source.digest / "runtime-image-attestation.json"
        env = {
            "DOCKER_CONFIG": str(workspace / "docker-config"),
            "HOME": str(workspace / "home"),
            "PATH": str(workspace / "empty-path"),
            "LC_ALL": "C",
            "STOCK_IMAGE": image.image_digest,
            "STOCK_ATTESTATION_FILE": str(attestation),
        }
        prefix = (
            str(_DOCKER),
            "--config",
            env["DOCKER_CONFIG"],
            "--host",
            "unix:///var/run/docker.sock",
            "compose",
        )
        version_argv = (*prefix, "version", "--short")
        render_argv = (
            *prefix,
            "--ansi",
            "never",
            "--project-name",
            "hybrid-stock-research",
            "--project-directory",
            str(workspace),
            "--env-file",
            str(workspace / "compose.env"),
            "--file",
            str(workspace / "compose-template.yml"),
            "config",
            "--format",
            "json",
            "--resolve-image-digests=false",
            "--lock-image-digests=false",
        )
        lease.record(
            "render-intent.json",
            {
                "schema_version": 1,
                "kind": "stock_producer_render_intent",
                "namespace_id": lease.namespace["namespace_id"],
                "source_sha256": lease.source.digest,
                "image_digest": image.image_digest,
                "probe_result_sha256": lease.hashes["probe-result.json"],
                "configuration_sha256": lease.hashes["configuration.bin"],
                "template_sha256": lease.hashes["compose-template.yml"],
                "env_file_sha256": lease.hashes["compose.env"],
                "version_argv": list(version_argv),
                "render_argv": list(render_argv),
                "cwd": str(workspace),
                "environment": env,
                "started_clock": lease.check(),
            },
        )
        with _executable(lease) as binary_check:
            version, _ = _invoke(lease, binary_check, version_argv, workspace, env, version=True)
            _require(version == b"2.40.3\n")
            raw, cap = _invoke(lease, binary_check, render_argv, workspace, env, version=False)
            value = json.loads(
                raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
            )
            _require(_exact(value, _policy(image.image_digest, attestation)))
            canonical = _canonical(value)
            _require(len(canonical) <= 65536)
            lease.check(not_after_ns=cap)
        lease.check(not_after_ns=cap)
        lease.record(
            "render-complete.json",
            {
                "schema_version": 1,
                "kind": "stock_producer_render_complete",
                "namespace_id": lease.namespace["namespace_id"],
                "source_sha256": lease.source.digest,
                "image_digest": image.image_digest,
                "probe_result_sha256": lease.hashes["probe-result.json"],
                "render_intent_sha256": lease.hashes["render-intent.json"],
                "version_sha256": lease.hashes["compose-version.stdout"],
                "version_stderr_sha256": lease.hashes["compose-version.stderr"],
                "render_sha256": lease.hashes["compose-render.stdout"],
                "render_stderr_sha256": lease.hashes["compose-render.stderr"],
                "compose_sha256": hashlib.sha256(canonical).hexdigest(),
                "completed_clock": lease.check(not_after_ns=cap),
            },
        )
        lease.check(not_after_ns=cap)
        lease.compose_bytes = canonical
        return canonical
