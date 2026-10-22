"""Private bounded child capture for fixed local Git and Compose commands.

Callers own the executable, arguments and scrubbed environment. No shell, retry,
input stream or inherited output is available through this boundary.
"""

from __future__ import annotations

import math
import os
import selectors
import signal
import subprocess  # nosec B404 -- fixed internal commands; no shell
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn


@dataclass(frozen=True, slots=True, repr=False)
class _Captured:
    stdout: bytes
    stderr: bytes


class _CaptureFailed(ValueError):
    """Bounded partial diagnostic bytes; never a successful invocation result."""

    def __init__(self, stdout: bytes, stderr: bytes) -> None:
        super().__init__("stock_process_unavailable")
        self.output = _Captured(stdout, stderr)


def _deny() -> NoReturn:
    raise ValueError("stock_process_unavailable") from None


def _capture(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str],
    limit: int,
    deadline: float,
    check: Callable[[], object] | None = None,
) -> _Captured:
    """Return only after bounded reads, successful reaping and checked cleanup."""
    if (
        type(argv) is not tuple
        or not argv
        or any(type(value) is not str or not value or "\0" in value for value in argv)
        or not Path(argv[0]).is_absolute()
        or not isinstance(cwd, Path)
        or not cwd.is_absolute()
        or type(env) is not dict
        or any(type(k) is not str or type(v) is not str for k, v in env.items())
        or type(limit) is not int
        or not 1 <= limit <= 16 * 1024 * 1024
        or type(deadline) not in (int, float)
        or not math.isfinite(deadline)
    ):
        _deny()

    def remaining() -> float:
        if check is not None:
            check()
        seconds = deadline - time.monotonic()
        if not seconds > 0:
            _deny()
        return min(1.0, seconds)

    buffers: dict[int, bytearray] = {}
    stdout_fd: int | None = None
    stderr_fd: int | None = None
    try:
        remaining()
        # Only fixed internal argv reaches this private boundary; never a shell.
        process = subprocess.Popen(  # nosec B603
            argv,
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            start_new_session=True,
        )
        completed = False
        try:
            remaining()
            if process.stdout is None or process.stderr is None:
                _deny()
            streams = (process.stdout, process.stderr)
            buffers = {stream.fileno(): bytearray() for stream in streams}
            stdout_fd = streams[0].fileno()
            stderr_fd = streams[1].fileno()
            bounds = {stdout_fd: limit, stderr_fd: 16384}
            with selectors.DefaultSelector() as selector:
                for stream in streams:
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream.fileno(), selectors.EVENT_READ)
                while selector.get_map():
                    for key, _ in selector.select(remaining()):
                        remaining()
                        descriptor = key.fd
                        data = os.read(
                            descriptor,
                            min(65536, bounds[descriptor] + 1 - len(buffers[descriptor])),
                        )
                        if not data:
                            selector.unregister(descriptor)
                        else:
                            buffers[descriptor].extend(data)
                            if len(buffers[descriptor]) > bounds[descriptor]:
                                del buffers[descriptor][bounds[descriptor] :]
                                _deny()
                        remaining()
            while process.poll() is None:
                try:
                    process.wait(timeout=remaining())
                except subprocess.TimeoutExpired:
                    remaining()
            remaining()
            if process.returncode != 0:
                _deny()
            result = _Captured(bytes(buffers[stdout_fd]), bytes(buffers[stderr_fd]))
            completed = True
        finally:
            failed = False
            try:
                if not completed or process.poll() is None:
                    # Stop this new session even if its launcher exited before a
                    # plugin closed inherited pipes. No daemon stop is inferred.
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=1)
            finally:
                for closing_stream in (process.stdout, process.stderr):
                    if closing_stream is not None:
                        try:
                            closing_stream.close()
                        except OSError:
                            failed = True
            if failed:
                _deny()
        remaining()
        return result
    except (OSError, ValueError, TypeError, OverflowError, subprocess.SubprocessError):
        raise _CaptureFailed(
            bytes(buffers.get(-1 if stdout_fd is None else stdout_fd, b"")),
            bytes(buffers.get(-1 if stderr_fd is None else stderr_fd, b"")),
        ) from None
