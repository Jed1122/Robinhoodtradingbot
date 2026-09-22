"""Private, bounded, no-overwrite local storage for synthetic research artifacts."""

import errno
import os
import secrets
import stat
from contextlib import ExitStack, suppress
from dataclasses import fields
from pathlib import Path

from trading_bot.domain import DataHash
from trading_bot.market_data.bundle_codec import _array, _digest, _json, _mapping
from trading_bot.market_data.bundle_models import (
    _HASH,
    BundleEnvelope,
    BundleError,
    BundleLimits,
    BundlePackage,
    SourceDescriptor,
    _check,
)
from trading_bot.market_data.bundle_verify import VerifiedBundle, verify_bundle

_SUPPORTED = (
    all(hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_NONBLOCK", "O_DIRECTORY"))
    and os.open in os.supports_dir_fd
    and os.mkdir in os.supports_dir_fd
    and os.unlink in os.supports_dir_fd
    and os.link in os.supports_dir_fd
    and os.link in os.supports_follow_symlinks
)


def _private(descriptor: int, *, directory: bool) -> None:
    info = os.fstat(descriptor)
    _check(
        (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600),
        "bundle_path_invalid",
    )


def _directory_flags() -> int:
    _check(_SUPPORTED, "bundle_storage_unavailable")
    return os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_DIRECTORY


def _open_root(root: Path, repository_root: Path) -> int:
    _check(isinstance(root, Path) and isinstance(repository_root, Path), "bundle_path_invalid")
    _check(
        root.is_absolute()
        and repository_root.is_absolute()
        and ".." not in root.parts
        and ".." not in repository_root.parts,
        "bundle_path_invalid",
    )
    descriptor = -1
    try:
        repository = repository_root.resolve(strict=True)
        _check(not root.is_relative_to(repository), "bundle_path_invalid")
        descriptor = os.open(root.anchor, _directory_flags())
        for component in root.parts[1:]:
            child = os.open(component, _directory_flags(), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        _private(descriptor, directory=True)
        return descriptor
    except BundleError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except OSError:
        if descriptor >= 0:
            os.close(descriptor)
    raise BundleError("bundle_path_invalid")


def _subdirectory(parent: int, name: str, *, create: bool) -> int:
    if create:
        with suppress(FileExistsError):
            os.mkdir(name, mode=0o700, dir_fd=parent)
    try:
        descriptor = os.open(name, _directory_flags(), dir_fd=parent)
    except OSError:
        pass
    else:
        try:
            _private(descriptor, directory=True)
            if create:
                # Existing entries may be retained from an earlier uncertain mkdir/fsync.
                os.fsync(parent)
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor
    raise BundleError("bundle_path_invalid")


def _read_descriptor(descriptor: int, max_bytes: int) -> bytes:
    _private(descriptor, directory=False)
    _check(os.fstat(descriptor).st_size <= max_bytes, "bundle_input_too_large")
    chunks: list[bytes] = []
    remaining = max_bytes + 1
    while remaining:
        chunk = os.read(descriptor, min(remaining, 65536))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    body = b"".join(chunks)
    _check(len(body) <= max_bytes, "bundle_input_too_large")
    return body


def _read(directory: int, name: str, max_bytes: int) -> bytes:
    invalid = False
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except OSError as error:
        invalid = error.errno in (errno.ELOOP, errno.ENOTDIR)
        if not invalid:
            raise
    else:
        try:
            return _read_descriptor(descriptor, max_bytes)
        finally:
            os.close(descriptor)
    raise BundleError("bundle_path_invalid")


def _existing(directory: int, name: str, body: bytes) -> bool:
    too_large = False
    try:
        existing = _read(directory, name, len(body))
    except FileNotFoundError:
        return False
    except BundleError as error:
        if error.code != "bundle_input_too_large":
            raise
        too_large = True
    else:
        _check(existing == body, "bundle_storage_conflict")
        # Retrying publication also re-establishes directory durability after uncertainty.
        os.fsync(directory)
        return True
    _check(not too_large, "bundle_storage_conflict")
    return False


def _publish(directory: int, name: str, body: bytes) -> None:
    if _existing(directory, name, body):
        return
    temporary = ".tmp-" + secrets.token_hex(16)
    descriptor = os.open(
        temporary,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK,
        0o600,
        dir_fd=directory,
    )
    try:
        os.fchmod(descriptor, 0o600)
        written = 0
        while written < len(body):
            count = os.write(descriptor, memoryview(body)[written:])
            _check(count > 0, "bundle_storage_unavailable")
            written += count
        os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        _check(_read_descriptor(descriptor, len(body)) == body, "bundle_storage_conflict")
        try:
            os.link(
                temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False
            )
        except FileExistsError:
            _check(_existing(directory, name, body), "bundle_storage_conflict")
        # A failure here leaves a complete but durability-uncertain artifact, never rollback.
        os.fsync(directory)
    finally:
        os.close(descriptor)
        os.unlink(temporary, dir_fd=directory)


def write_bundle(
    root: Path,
    package: BundlePackage,
    *,
    repository_root: Path,
    limits: BundleLimits,
) -> DataHash:
    verified = verify_bundle(package, limits=limits)
    try:
        with ExitStack() as stack:
            parent = _open_root(root, repository_root)
            stack.callback(os.close, parent)
            blobs = _subdirectory(parent, "blobs", create=True)
            stack.callback(os.close, blobs)
            bundles = _subdirectory(parent, "bundles", create=True)
            stack.callback(os.close, bundles)
            for digest, body in package.blobs:
                _publish(blobs, digest + ".raw", body)
            digest = verified.envelope.bundle_hash
            _publish(bundles, digest + ".json", package.envelope_bytes)
            return digest
    except OSError:
        pass
    raise BundleError("bundle_storage_unavailable")


def read_bundle(
    root: Path,
    bundle_hash: DataHash,
    *,
    repository_root: Path,
    limits: BundleLimits,
) -> VerifiedBundle:
    _check(type(limits) is BundleLimits, "bundle_limits_invalid")
    _check(
        type(bundle_hash) is str and _HASH.fullmatch(bundle_hash) is not None, "bundle_path_invalid"
    )
    try:
        with ExitStack() as stack:
            parent = _open_root(root, repository_root)
            stack.callback(os.close, parent)
            bundles = _subdirectory(parent, "bundles", create=False)
            stack.callback(os.close, bundles)
            blobs = _subdirectory(parent, "blobs", create=False)
            stack.callback(os.close, blobs)
            encoded = _read(bundles, bundle_hash + ".json", limits.max_envelope_bytes)
            wire = _mapping(
                _json(encoded, max_bytes=limits.max_envelope_bytes, limits=limits),
                {item.name for item in fields(BundleEnvelope)},
            )
            _check(_digest(wire["bundle_hash"]) == bundle_hash, "bundle_hash_mismatch")
            _check(len(_array(wire["records"])) <= limits.max_records, "bundle_input_too_large")
            digests = {
                _digest(
                    _mapping(source, {item.name for item in fields(SourceDescriptor)})[
                        "blob_sha256"
                    ]
                )
                for source in _array(wire["sources"])
            }
            total = len(encoded)
            bodies: list[tuple[str, bytes]] = []
            for digest in sorted(digests):
                remaining = limits.max_total_bytes - total
                _check(remaining >= 0, "bundle_input_too_large")
                body = _read(blobs, digest + ".raw", min(limits.max_blob_bytes, remaining))
                total += len(body)
                bodies.append((digest, body))
            return verify_bundle(BundlePackage(encoded, tuple(bodies)), limits=limits)
    except OSError:
        pass
    raise BundleError("bundle_storage_unavailable")
