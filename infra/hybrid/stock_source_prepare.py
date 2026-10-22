"""Bounded clean committed Git archive, exclusively written without extraction.

Only local source preparation is performed. No image, broker, credential or
release operation follows from the returned supplied-source digest.
"""

from __future__ import annotations

import hashlib
import os
import re
import selectors

# Fixed local Git, no shell and a scrubbed environment.
import subprocess  # nosec B404
import time
from pathlib import Path
from typing import NoReturn

from infra.hybrid.stock_build_inputs import SourceArchive, inspect_source
from infra.hybrid.stock_release import _close_all, _fingerprint, _open_directory
from infra.hybrid.stock_release_producer import _file, _read_binary

_REPOSITORY = Path(__file__).resolve().parents[2]
_PATHS = (
    "Dockerfile",
    ".docker-base-image",
    "pyproject.toml",
    "uv.lock",
    "alembic.ini",
    "compose.stock-research.yml",
    "src",
    "configs",
    "migrations",
)
_STATUS = ("status", "--porcelain=v1", "-z", "--untracked-files=all")
_ENV = {
    "PATH": "/usr/bin:/bin",
    "LC_ALL": "C",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_NO_REPLACE_OBJECTS": "1",
}
_PREFIX = (
    "/usr/bin/git",
    "--no-pager",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.attributesFile=/dev/null",
    "-c",
    "core.untrackedCache=false",
    "-c",
    "tar.umask=0022",
    "-c",
    "protocol.allow=never",
)
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_WRITE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_ERRORS = (OSError, ValueError, TypeError, KeyError, OverflowError, subprocess.SubprocessError)


def _deny() -> NoReturn:
    raise ValueError("stock_source_prepare_unavailable") from None


def _require(condition: bool) -> None:
    if not condition:
        _deny()


def _remaining(deadline: float) -> float:
    seconds = deadline - time.monotonic()
    _require(seconds > 0)
    return min(1.0, seconds)


def _git(repo: Path, arguments: tuple[str, ...], *, limit: int, deadline: float) -> bytes:
    """Only internal fixed Git argument tuples reach this private process boundary."""
    _remaining(deadline)
    # Fixed Git and internal tuples; never a shell.
    process = subprocess.Popen(  # nosec B603
        [*_PREFIX, *arguments],
        cwd=repo,
        env=dict(_ENV),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
    )
    failed = False
    try:
        if process.stdout is None or process.stderr is None:
            _deny()
        streams = (process.stdout, process.stderr)
        buffers = {stream.fileno(): bytearray() for stream in streams}
        bounds = {streams[0].fileno(): limit, streams[1].fileno(): 16384}
        with selectors.DefaultSelector() as selector:
            for stream in streams:
                os.set_blocking(stream.fileno(), False)
                selector.register(stream.fileno(), selectors.EVENT_READ)
            while selector.get_map():
                for key, _ in selector.select(_remaining(deadline)):
                    descriptor = key.fd
                    data = os.read(
                        descriptor, min(65536, bounds[descriptor] + 1 - len(buffers[descriptor]))
                    )
                    if not data:
                        selector.unregister(descriptor)
                    else:
                        buffers[descriptor].extend(data)
                        _require(len(buffers[descriptor]) <= bounds[descriptor])
                    _remaining(deadline)
        process.wait(timeout=_remaining(deadline))
        _remaining(deadline)
        _require(process.returncode == 0)
        return bytes(buffers[streams[0].fileno()])
    finally:
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
        finally:
            for closing_stream in (process.stdout, process.stderr):
                if closing_stream is not None:
                    try:
                        closing_stream.close()
                    except OSError:
                        failed = True
        _require(not failed)


def _native(
    repo: Path,
    arguments: tuple[str, ...],
    deadline: float,
    *,
    limit: int = 65536,
    archive: bool = False,
) -> bytes:
    return _git(
        repo,
        arguments,
        limit=limit,
        deadline=min(deadline, time.monotonic() + (20 if archive else 5)),
    )


def _identity(fd: int, path: Path, uid: int) -> None:
    current = _open_directory(path, trusted_uid=uid, release_root=path)
    try:
        opened, named = os.fstat(fd), os.fstat(current)
        _require((opened.st_dev, opened.st_ino) == (named.st_dev, named.st_ino))
    finally:
        _close_all((current,))


def _attributes(repo: Path, head: str, deadline: float) -> Path:
    path_raw = _native(
        repo, ("rev-parse", "--path-format=absolute", "--git-path", "info/attributes"), deadline
    )
    _require(path_raw.endswith(b"\n") and b"\0" not in path_raw and path_raw.count(b"\n") == 1)
    attributes = Path(path_raw[:-1].decode("utf-8"))
    _require(attributes.is_absolute() and not os.path.lexists(attributes))
    names = _native(
        repo,
        ("ls-tree", "-r", "--name-only", "-z", head, "--", ".gitattributes", *_PATHS),
        deadline,
    )
    _require(not any(name.rsplit(b"/", 1)[-1] == b".gitattributes" for name in names.split(b"\0")))
    _require(not os.path.lexists(repo / ".gitattributes"))
    return attributes


def _write_source(directory: int, name: str, raw: bytes, uid: int) -> None:
    descriptor = os.open(name, _WRITE, 0o600, dir_fd=directory)
    try:
        offset = 0
        while offset < len(raw):
            count = os.write(descriptor, raw[offset:])
            _require(type(count) is int and 0 < count <= len(raw) - offset)
            offset += count
        before = os.fstat(descriptor)
        _file(before, uid, 1, 16 * 1024 * 1024)
        _require(before.st_size == len(raw))
        os.fsync(descriptor)
        stamp = _fingerprint(before)
        _require(stamp == _fingerprint(os.fstat(descriptor)))
        _require(stamp == _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False)))
    finally:
        _close_all((descriptor,))
    os.fsync(directory)
    _require(_read_binary(directory, name, uid, 1, 16 * 1024 * 1024) == raw)
    _require(stamp == _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False)))


def _assert_head(repo: Path, head: str, deadline: float) -> None:
    _require(_native(repo, _STATUS, deadline) == b"")
    _require(_native(repo, ("rev-parse", "--verify", "HEAD"), deadline) == (head + "\n").encode())


def _capture_source(repo: Path, *, deadline: float) -> SourceArchive:
    """Own a fresh local capture; no supplied archive or receipt can replace this call."""
    _require(isinstance(repo, Path) and repo.is_absolute() and ".." not in repo.parts)
    uid, cap = os.geteuid(), min(deadline, time.monotonic() + 30)
    descriptor = _open_directory(repo, trusted_uid=uid, release_root=repo)
    try:
        _require(_native(repo, _STATUS, cap) == b"")
        head_raw = _native(repo, ("rev-parse", "--verify", "HEAD"), cap)
        _require(re.fullmatch(rb"(?:[0-9a-f]{40}|[0-9a-f]{64})\n", head_raw) is not None)
        head = head_raw[:-1].decode("ascii")
        attributes = _attributes(repo, head, cap)
        raw = _native(
            repo,
            ("archive", "--format=tar", head, "--", *_PATHS),
            cap,
            limit=16 * 1024 * 1024,
            archive=True,
        )
        source = inspect_source(raw, expected_sha256=hashlib.sha256(raw).hexdigest())
        _require(source.commit == head)
        _assert_head(repo, head, cap)
        _require(not os.path.lexists(attributes) and not os.path.lexists(repo / ".gitattributes"))
        _identity(descriptor, repo, uid)
        _remaining(cap)
    finally:
        _close_all((descriptor,))
    _remaining(cap)
    return source


def _prepare_source(output: Path, *, repo: Path) -> str:
    """Private disposable-repository fixture seam; the public repository is fixed."""
    try:
        _require(isinstance(output, Path) and output.is_absolute() and ".." not in output.parts)
        _require(isinstance(repo, Path) and repo.is_absolute() and ".." not in repo.parts)
        _require(re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,127}", output.name) is not None)
        uid, deadline = os.geteuid(), time.monotonic() + 30
        descriptors = []
        try:
            for path in (repo, output.parent):
                descriptors.append(_open_directory(path, trusted_uid=uid, release_root=path))
            repository, parent = descriptors
            _require(not os.path.lexists(output))
            source = _capture_source(repo, deadline=deadline)
            _identity(repository, repo, uid)
            _identity(parent, output.parent, uid)
            _remaining(deadline)
            _write_source(parent, output.name, source.raw, uid)
            _identity(repository, repo, uid)
            _identity(parent, output.parent, uid)
            _assert_head(repo, source.commit, deadline)
            _remaining(deadline)
        finally:
            _close_all(reversed(descriptors))
        _remaining(deadline)
        return source.digest
    except _ERRORS:
        _deny()


def prepare_source(output: Path) -> str:
    """Prepare only this installed checkout's clean committed source, without extraction."""
    return _prepare_source(output, repo=_REPOSITORY)
