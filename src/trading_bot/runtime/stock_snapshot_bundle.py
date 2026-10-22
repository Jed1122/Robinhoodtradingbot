"""Canonical bounded uncompressed USTAR for private stock application snapshots.

This is a closed snapshot container, not a general tar reader. Three ordered
directory headers precede sorted regular-file headers. Canonical original USTAR
headers, zero file padding, exactly two zero end blocks and EOF are required.
No extraction API interprets extensions or follows archive paths. Application
integrity/replay and ciphertext provenance are verified separately by the caller.
Caller-owned streams stay open; their blocking I/O requires a caller deadline.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tarfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, NoReturn

_MAXIMUM_BYTES = 2 * 1024**3
_MAXIMUM_FILES = 20000
_CHUNK = 1024 * 1024
_BLOCK = 512
_ZERO = b"\0" * _BLOCK
_DIRECTORIES = ("archive", "exports", "state")
_ROOT_FILES = {"canonical-config.json", "saved-control.json", "manifest.json"}
_REQUIRED_FILES = _ROOT_FILES | {"state/ledger.sqlite3"}
_ARCHIVE = re.compile(
    r"(?:[0-9a-f]{64}\.stock-(?:observation|capture|dossiers|screen)\.json"
    r"|\.pending-[0-9a-f]{32}|\.stock-research\.lock)\Z"
)
_EXPORT = re.compile(r"(?:stock-research\.json|\.pending-[0-9a-f]{32}|\.stock-research\.lock)\Z")
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


@dataclass(frozen=True, slots=True)
class BundleReceipt:
    bundle_sha256: str
    file_count: int
    total_bytes: int
    stream_bytes: int


@dataclass(frozen=True, slots=True)
class _Entry:
    name: str
    size: int
    stamp: tuple[int, ...]


class StockSnapshotBundleError(ValueError):
    """Fixed error without paths, snapshot payload or stream exception text."""


def _deny() -> NoReturn:
    raise StockSnapshotBundleError("stock_snapshot_bundle_unavailable") from None


def _require(value: bool) -> None:
    if not value:
        _deny()


def _caps(maximum_bytes: int, maximum_files: int) -> None:
    _require(type(maximum_bytes) is int and 1 <= maximum_bytes <= _MAXIMUM_BYTES)
    _require(type(maximum_files) is int and 1 <= maximum_files <= _MAXIMUM_FILES)


def _close(descriptors: tuple[int, ...]) -> None:
    failed = False
    for descriptor in descriptors:
        try:
            os.close(descriptor)
        except OSError:
            failed = True
    if failed:
        _deny()


def _stamp(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _directory(info: os.stat_result) -> None:
    _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid())
    _require(stat.S_IMODE(info.st_mode) == 0o700)


def _private(info: os.stat_result) -> None:
    _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid())
    _require(stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1)


def _file_limit(name: str) -> int:
    _require(type(name) is str and name.isascii() and len(name) <= 100)
    limits = {
        "canonical-config.json": 1024 * 1024,
        "saved-control.json": 8192,
        "manifest.json": 32 * 1024 * 1024,
        "state/ledger.sqlite3": 256 * 1024 * 1024,
    }
    if name in limits:
        return limits[name]
    tree, separator, leaf = name.partition("/")
    _require(separator == "/")
    if tree == "archive" and _ARCHIVE.fullmatch(leaf) is not None:
        return 0 if leaf == ".stock-research.lock" else 9_000_000
    if tree == "exports" and _EXPORT.fullmatch(leaf) is not None:
        return 0 if leaf == ".stock-research.lock" else 262144
    _deny()


def _names(directory: int, maximum: int) -> set[str]:
    result: set[str] = set()
    with os.scandir(directory) as entries:
        for entry in entries:
            _require(len(result) < maximum)
            result.add(entry.name)
    return result


def _inventory(
    directories: dict[str, int], maximum_bytes: int, maximum_files: int
) -> tuple[list[_Entry], int, int]:
    _require(_names(directories[""], 6) == _ROOT_FILES | set(_DIRECTORIES))
    _require(_names(directories["state"], 1) == {"ledger.sqlite3"})
    entries: list[_Entry] = []
    for tree in ("", *_DIRECTORIES):
        names = _ROOT_FILES if not tree else _names(directories[tree], maximum_files)
        for leaf in sorted(names):
            _require(len(entries) < maximum_files)
            name = tree + "/" + leaf if tree else leaf
            limit = _file_limit(name)
            info = os.stat(leaf, dir_fd=directories[tree], follow_symlinks=False)
            _private(info)
            _require(0 <= info.st_size <= limit)
            entries.append(_Entry(name, info.st_size, _stamp(info)))
    entries.sort(key=lambda row: row.name)
    total = sum(row.size for row in entries)
    framed = (len(_DIRECTORIES) + 2) * _BLOCK + sum(
        _BLOCK + row.size + (-row.size % _BLOCK) for row in entries
    )
    _require(framed <= maximum_bytes)
    return entries, total, framed


def _open_directory(path: Path) -> int:
    _require(isinstance(path, Path) and path.is_absolute() and path.resolve(strict=True) == path)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        _directory(os.fstat(descriptor))
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _check_named_root(path: Path, descriptor: int) -> None:
    actual, named = os.fstat(descriptor), path.stat(follow_symlinks=False)
    _directory(actual)
    _directory(named)
    _require((actual.st_dev, actual.st_ino) == (named.st_dev, named.st_ino))


@contextmanager
def _source(root: Path) -> Iterator[dict[str, int]]:
    directories: dict[str, int] = {}
    try:
        directories[""] = _open_directory(root)
        _require(_names(directories[""], 6) == _ROOT_FILES | set(_DIRECTORIES))
        for name in _DIRECTORIES:
            child = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directories[""],
            )
            directories[name] = child
            _directory(os.fstat(child))
        pins = {name: _stamp(os.fstat(fd)) for name, fd in directories.items()}
        yield directories
        _check_named_root(root, directories[""])
        for name, descriptor in directories.items():
            _require(_stamp(os.fstat(descriptor)) == pins[name])
            if name:
                _require(
                    _stamp(os.stat(name, dir_fd=directories[""], follow_symlinks=False))
                    == pins[name]
                )
    finally:
        _close(tuple(reversed(tuple(directories.values()))))


def _header(name: str, size: int = 0, *, directory: bool = False) -> bytes:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE if directory else tarfile.REGTYPE
    info.mode = 0o700 if directory else 0o600
    info.uid = info.gid = info.mtime = 0
    info.size = size
    return info.tobuf(format=tarfile.USTAR_FORMAT, encoding="ascii", errors="strict")


def _parse(raw: bytes) -> tuple[str, int, bool]:
    info = tarfile.TarInfo.frombuf(raw, encoding="ascii", errors="strict")
    _require(info.type in {tarfile.REGTYPE, tarfile.DIRTYPE})
    _require(type(info.size) is int and info.size >= 0)
    directory = info.type == tarfile.DIRTYPE
    if directory:
        _require(info.name in _DIRECTORIES and info.size == 0)
    else:
        _require(info.size <= _file_limit(info.name))
    _require(raw == _header(info.name, info.size, directory=directory))
    return info.name, info.size, directory


class _Writer:
    def __init__(self, stream: BinaryIO, limit: int) -> None:
        self.stream, self.limit = stream, limit
        self.digest, self.count = hashlib.sha256(), 0

    def write(self, raw: bytes) -> None:
        _require(len(raw) <= _CHUNK and self.count + len(raw) <= self.limit)
        remaining = memoryview(raw)
        while remaining:
            written = self.stream.write(remaining)
            _require(type(written) is int and 0 < written <= len(remaining))
            self.digest.update(remaining[:written])
            self.count += written
            remaining = remaining[written:]


class _Reader:
    def __init__(self, stream: BinaryIO, limit: int) -> None:
        self.stream, self.limit = stream, limit
        self.digest, self.count = hashlib.sha256(), 0

    def exact(self, size: int) -> bytes:
        _require(0 <= size <= _CHUNK and self.count + size <= self.limit)
        result = bytearray()
        while len(result) < size:
            part = self.stream.read(size - len(result))
            _require(type(part) is bytes and 0 < len(part) <= size - len(result))
            self.digest.update(part)
            self.count += len(part)
            result.extend(part)
        return bytes(result)

    def eof(self) -> None:
        end = self.stream.read(1)
        _require(type(end) is bytes and end == b"")


def pack_snapshot(
    root: Path,
    destination: BinaryIO,
    *,
    maximum_bytes: int = _MAXIMUM_BYTES,
    maximum_files: int = _MAXIMUM_FILES,
) -> BundleReceipt:
    """Write the closed stream, checking complete size/inventory before first write."""
    try:
        _caps(maximum_bytes, maximum_files)
        writer = _Writer(destination, maximum_bytes)
        with _source(root) as directories:
            entries, total, framed = _inventory(directories, maximum_bytes, maximum_files)
            for name in _DIRECTORIES:
                writer.write(_header(name, directory=True))
            for entry in entries:
                tree, _, leaf = entry.name.rpartition("/")
                descriptor = os.open(leaf, _READ, dir_fd=directories[tree])
                try:
                    _require(_stamp(os.fstat(descriptor)) == entry.stamp)
                    writer.write(_header(entry.name, entry.size))
                    remaining = entry.size
                    while remaining:
                        part = os.read(descriptor, min(_CHUNK, remaining))
                        _require(bool(part))
                        writer.write(part)
                        remaining -= len(part)
                    _require(os.read(descriptor, 1) == b"")
                    _require(_stamp(os.fstat(descriptor)) == entry.stamp)
                    _require(
                        _stamp(os.stat(leaf, dir_fd=directories[tree], follow_symlinks=False))
                        == entry.stamp
                    )
                    writer.write(b"\0" * (-entry.size % _BLOCK))
                finally:
                    os.close(descriptor)
            writer.write(_ZERO * 2)
            _require(_inventory(directories, maximum_bytes, maximum_files)[0] == entries)
            _require(writer.count == framed)
            receipt = BundleReceipt(writer.digest.hexdigest(), len(entries), total, writer.count)
        return receipt
    except Exception:
        _deny()


@contextmanager
def _target(destination: Path) -> Iterator[dict[str, int]]:
    parent = -1
    directories: dict[str, int] = {}
    try:
        _require(isinstance(destination, Path) and destination.is_absolute())
        _require(destination.name not in {"", ".", ".."})
        parent = _open_directory(destination.parent)
        os.mkdir(destination.name, mode=0o700, dir_fd=parent)
        root = os.open(
            destination.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent,
        )
        directories[""] = root
        _directory(os.fstat(root))
        os.fsync(parent)
        yield directories
        _check_named_root(destination, root)
        for name, descriptor in directories.items():
            _directory(os.fstat(descriptor))
            if name:
                actual = os.fstat(descriptor)
                named = os.stat(name, dir_fd=root, follow_symlinks=False)
                _directory(named)
                _require((actual.st_dev, actual.st_ino) == (named.st_dev, named.st_ino))
            os.fsync(descriptor)
        _check_named_root(destination.parent, parent)
        os.fsync(parent)
    finally:
        owned = tuple(reversed(tuple(directories.values())))
        _close(owned + ((parent,) if parent >= 0 else ()))


def _extract_file(reader: _Reader, directories: dict[str, int], name: str, size: int) -> None:
    tree, _, leaf = name.rpartition("/")
    directory = directories[tree]
    descriptor = os.open(
        leaf,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=directory,
    )
    try:
        os.fchmod(descriptor, 0o600)
        remaining = size
        while remaining:
            part = reader.exact(min(_CHUNK, remaining))
            remaining -= len(part)
            pending = memoryview(part)
            while pending:
                written = os.write(descriptor, pending)
                _require(written > 0)
                pending = pending[written:]
        padding = reader.exact(-size % _BLOCK)
        _require(padding == b"\0" * len(padding))
        os.fsync(descriptor)
        info = os.fstat(descriptor)
        _private(info)
        _require(info.st_size == size)
        _require(_stamp(info) == _stamp(os.stat(leaf, dir_fd=directory, follow_symlinks=False)))
    finally:
        os.close(descriptor)


def unpack_snapshot(
    source: BinaryIO,
    *,
    destination: Path,
    maximum_bytes: int = _MAXIMUM_BYTES,
    maximum_files: int = _MAXIMUM_FILES,
) -> BundleReceipt:
    """Extract exclusively into a new private directory; retain failed private partials."""
    try:
        _caps(maximum_bytes, maximum_files)
        reader = _Reader(source, maximum_bytes)
        with _target(destination) as directories:
            for expected in _DIRECTORIES:
                name, size, directory = _parse(reader.exact(_BLOCK))
                _require(directory and name == expected and size == 0)
                os.mkdir(name, mode=0o700, dir_fd=directories[""])
                child = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=directories[""],
                )
                directories[name] = child
                _directory(os.fstat(child))
            names: set[str] = set()
            total, previous = 0, ""
            while True:
                raw = reader.exact(_BLOCK)
                if raw == _ZERO:
                    _require(reader.exact(_BLOCK) == _ZERO)
                    reader.eof()
                    break
                name, size, directory = _parse(raw)
                _require(not directory and name > previous and name not in names)
                _require(len(names) < maximum_files)
                _require(reader.count + size + (-size % _BLOCK) + 2 * _BLOCK <= maximum_bytes)
                _extract_file(reader, directories, name, size)
                names.add(name)
                previous, total = name, total + size
            _require(_REQUIRED_FILES.issubset(names))
            entries, actual_total, framed = _inventory(directories, maximum_bytes, maximum_files)
            _require({entry.name for entry in entries} == names)
            _require(actual_total == total and framed == reader.count)
            receipt = BundleReceipt(reader.digest.hexdigest(), len(names), total, reader.count)
        return receipt
    except Exception:
        _deny()
