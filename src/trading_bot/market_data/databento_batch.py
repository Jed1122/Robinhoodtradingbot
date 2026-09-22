"""Offline definitions-only batch integrity. No credentials, network or trading objects."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import BinaryIO

from trading_bot.market_data.bundle_codec import _array, _json, _mapping, _string
from trading_bot.market_data.bundle_models import BundleError, BundleLimits
from trading_bot.market_data.bundle_store import _directory_flags, _open_root, _private
from trading_bot.market_data.recording import canonical_json

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_HASH = re.compile(r"sha256:([0-9a-f]{64})\Z")
_JSON_LIMITS = BundleLimits(1048576, 1048576, 1048576, 10000, 12)


class DatabentoImportError(ValueError):
    """Errors contain no provider payload, URL, private path or identifier."""

    def __init__(self, code: str = "databento_batch_invalid") -> None:
        if code not in {
            "databento_batch_invalid",
            "databento_dependency_missing",
            "databento_dbn_invalid",
            "databento_limit_exceeded",
            "databento_command_invalid",
        }:
            code = "databento_batch_invalid"
        super().__init__(code)
        self.code = code


def require(condition: bool, code: str = "databento_batch_invalid") -> None:
    if not condition:
        raise DatabentoImportError(code)


@dataclass(frozen=True, slots=True)
class DefinitionRequest:
    parent: str
    start_ns: int
    end_ns: int

    def __post_init__(self) -> None:
        require(
            type(self.parent) is str and re.fullmatch(r"[A-Z]{1,6}\.OPT", self.parent) is not None
        )
        require(type(self.start_ns) is int and type(self.end_ns) is int)
        require(0 < self.start_ns < self.end_ns < 2**63)

    def query(self) -> dict[str, object]:
        return {
            "dataset": "OPRA.PILLAR",
            "schema": "definition",
            "symbols": [self.parent],
            "stype_in": "parent",
            "stype_out": "instrument_id",
            "start": self.start_ns,
            "end": self.end_ns,
            "limit": None,
            "encoding": "dbn",
            "compression": "zstd",
        }


@dataclass(frozen=True, slots=True)
class BatchFile:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class VerifiedBatch:
    request: DefinitionRequest
    files: tuple[BatchFile, ...]
    definition_file: str
    conditions: tuple[tuple[str, str], ...]
    job_id: str = field(repr=False)
    production_eligible: bool = field(default=False, init=False)
    economic_evidence: bool = field(default=False, init=False)
    record_validation_complete: bool = field(default=False, init=False)


def _source_root(path: Path) -> int:
    require(path.is_absolute() and ".." not in path.parts)
    descriptor = os.open(path.anchor, _directory_flags())
    try:
        for component in path.parts[1:]:
            child = os.open(component, _directory_flags(), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        info = os.fstat(descriptor)
        require(info.st_uid == os.geteuid() and not stat.S_IMODE(info.st_mode) & 0o022)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _file(parent: int, name: str, max_bytes: int) -> BinaryIO:
    require(_NAME.fullmatch(name) is not None and ".." not in name)
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid())
        require(not stat.S_IMODE(info.st_mode) & 0o022 and info.st_size <= max_bytes)
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def _fingerprint(stream: BinaryIO, name: str, max_bytes: int) -> BatchFile:
    digest, count = hashlib.sha256(), 0
    while block := stream.read(65536):
        count += len(block)
        require(count <= max_bytes)
        digest.update(block)
    return BatchFile(name, count, digest.hexdigest())


def _metadata(parent: int, name: str) -> object:
    with _file(parent, name, _JSON_LIMITS.max_blob_bytes) as stream:
        return _json(
            stream.read(_JSON_LIMITS.max_blob_bytes + 1),
            max_bytes=_JSON_LIMITS.max_blob_bytes,
            limits=_JSON_LIMITS,
        )


def _conditions(value: object, expected: DefinitionRequest) -> tuple[tuple[str, str], ...]:
    result = []
    for item in _array(value):
        row = _mapping(item, {"date", "condition", "last_modified_date"})
        stamp = _string(row["date"])
        parsed = date.fromisoformat(stamp)
        require(parsed.isoformat() == stamp)
        ns = int(datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC).timestamp()) * 10**9
        require(expected.start_ns <= ns < expected.end_ns)
        state = _string(row["condition"])
        require(state in {"available", "degraded", "missing"})
        if row["last_modified_date"] is not None:
            modified = _string(row["last_modified_date"])
            require(date.fromisoformat(modified).isoformat() == modified)
        result.append((stamp, state))
    require(bool(result) and len({stamp for stamp, _ in result}) == len(result))
    return tuple(sorted(result))


def validate_batch(
    source: Path, *, expected: DefinitionRequest, max_file_bytes: int = 512 * 1024**2
) -> VerifiedBatch:
    """Verify provider hashes and exact requested scope; not yet decoded-record validation."""
    try:
        require(type(expected) is DefinitionRequest)
        require(type(max_file_bytes) is int and 0 < max_file_bytes <= 2**30)
        with ExitStack() as stack:
            parent = _source_root(source)
            stack.callback(os.close, parent)
            manifest = _mapping(_metadata(parent, "manifest.json"), {"job_id", "files"})
            job_id = _string(manifest["job_id"])
            require(_NAME.fullmatch(job_id) is not None)
            files = []
            entries = _array(manifest["files"])
            require(len(entries) == 3)
            for item in entries:
                entry = _mapping(item, {"filename", "size", "hash", "urls"})
                name, digest = _string(entry["filename"]), _string(entry["hash"])
                match = _HASH.fullmatch(digest)
                require(match is not None)
                require(type(entry["size"]) is int and 0 < entry["size"] <= max_file_bytes)
                # URLs are never fetched, copied into a report, or interpreted as instructions.
                require(type(entry["urls"]) is dict)
                with _file(parent, name, max_file_bytes) as stream:
                    observed = _fingerprint(stream, name, max_file_bytes)
                require(observed.size == entry["size"] and "sha256:" + observed.sha256 == digest)
                files.append(observed)
            names = {item.name for item in files}
            require(len(names) == 3 and {"metadata.json", "condition.json"} <= names)
            definition = next(iter(names - {"metadata.json", "condition.json"}))
            require(definition.endswith(".definition.dbn.zst"))
            require(set(os.listdir(parent)) == names | {"manifest.json"})
            metadata = _mapping(
                _metadata(parent, "metadata.json"), {"job_id", "version", "query", "customizations"}
            )
            require(type(metadata["version"]) is int and metadata["version"] == 1)
            require(metadata["job_id"] == job_id)
            require(canonical_json(metadata["query"]) == canonical_json(expected.query()))
            require(
                canonical_json(metadata["customizations"])
                == canonical_json(
                    {
                        "pretty_px": False,
                        "pretty_ts": False,
                        "map_symbols": False,
                        "split_symbols": False,
                        "split_duration": None,
                        "split_size": None,
                        "packaging": None,
                        "delivery": "download",
                    }
                )
            )
            conditions = _conditions(_metadata(parent, "condition.json"), expected)
            with _file(parent, "manifest.json", _JSON_LIMITS.max_blob_bytes) as stream:
                files.append(_fingerprint(stream, "manifest.json", _JSON_LIMITS.max_blob_bytes))
            return VerifiedBatch(
                expected, tuple(sorted(files, key=lambda f: f.name)), definition, conditions, job_id
            )
    except DatabentoImportError:
        raise
    except (OSError, ValueError, TypeError, BundleError):
        raise DatabentoImportError() from None


def _copy(parent: int, destination: int, expected: BatchFile) -> None:
    temporary = ".import-" + secrets.token_hex(16)
    with _file(parent, expected.name, expected.size) as source:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=destination,
        )
        try:
            with os.fdopen(descriptor, "wb") as output:
                digest, size = hashlib.sha256(), 0
                while block := source.read(65536):
                    size += len(block)
                    require(size <= expected.size)
                    digest.update(block)
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            require(size == expected.size and digest.hexdigest() == expected.sha256)
            try:
                os.link(
                    temporary,
                    expected.name,
                    src_dir_fd=destination,
                    dst_dir_fd=destination,
                    follow_symlinks=False,
                )
            except FileExistsError:
                with _file(destination, expected.name, expected.size) as existing:
                    _private(existing.fileno(), directory=False)
                    require(_fingerprint(existing, expected.name, expected.size) == expected)
            os.fsync(destination)
        finally:
            os.unlink(temporary, dir_fd=destination)


def preserve_batch(
    source: Path, destination: Path, batch: VerifiedBatch, *, repository_root: Path
) -> None:
    """Keep a verified private copy; never remove the user's download or overwrite conflicts."""
    try:
        require(type(batch) is VerifiedBatch)
        with ExitStack() as stack:
            parent = _source_root(source)
            target = _open_root(destination, repository_root)
            stack.callback(os.close, parent)
            stack.callback(os.close, target)
            for artifact in batch.files:
                _copy(parent, target, artifact)
    except DatabentoImportError:
        raise
    except (OSError, ValueError, TypeError, BundleError):
        raise DatabentoImportError() from None
