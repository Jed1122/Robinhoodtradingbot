"""Bounded, invocation-local failure metadata; never dispatch or write authority.

Only fixed phase/family names and allowlisted errno integers are retained. The
collector never keeps an exception, its text, arguments, traceback or payload.
"""

from __future__ import annotations

import errno
import json
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field

_PHASES = frozenset(
    {
        "producer", "source", "begin_build", "version_get", "version_retain",
        "version_verify", "claim", "connect", "send", "receive", "eof", "close",
        "response_retain", "lease_check", "parse", "image_get", "image_retain",
        "image_verify", "build_complete",
    }
)
_ERRNOS = frozenset(
    {
        errno.EACCES, errno.EAGAIN, errno.EBADF, errno.EBUSY, errno.ECONNABORTED,
        errno.ECONNREFUSED, errno.ECONNRESET, errno.EFBIG, errno.EINTR, errno.EIO,
        errno.EMFILE, errno.ENFILE, errno.ENOENT, errno.ENOMEM, errno.ENOSPC,
        errno.ENOTCONN, errno.ENOTSOCK, errno.EPERM, errno.EPIPE, errno.EROFS,
        errno.ETIMEDOUT,
    }
)
_FAMILIES = (ValueError, TypeError, KeyError, OverflowError, AttributeError, RecursionError)


@dataclass(slots=True)
class _Capture:
    first: dict[str, str | int | None] | None = None
    secondary: list[dict[str, str | int | None]] = field(default_factory=list)
    seen: set[int] = field(default_factory=set)


_CURRENT: ContextVar[_Capture | None] = ContextVar("stock_producer_diagnostic", default=None)
_PHASE: ContextVar[str] = ContextVar("stock_producer_diagnostic_phase", default="unknown")


@contextmanager
def capture() -> Iterator[None]:
    """Own one private capture; nested invocations cannot replace an outer one."""
    token = _CURRENT.set(_Capture())
    try:
        yield
    finally:
        _CURRENT.reset(token)


def _record(name: str, error: BaseException) -> None:
    state = _CURRENT.get()
    if state is None or id(error) in state.seen or len(state.seen) >= 5:
        return
    if state.first is not None and name not in ("close", "response_retain"):
        return  # Only secondary cleanup faults supplement the original failure.
    phase_name = name if type(name) is str and name in _PHASES else "unknown"
    family, number = "Exception", None
    if isinstance(error, OSError):
        family = "OSError"
        try:
            candidate = error.errno
            if type(candidate) is int and candidate in _ERRNOS:
                number = candidate
        except BaseException:
            number = None
    else:
        for allowed in _FAMILIES:
            if type(error) is allowed:
                family = allowed.__name__
                break
    entry: dict[str, str | int | None] = {
        "phase": phase_name, "family": family, "errno": number
    }
    state.seen.add(id(error))
    if state.first is None:
        state.first = entry
    else:
        state.secondary.append(entry)


@contextmanager
def phase(name: str) -> Iterator[None]:
    """Observe a failure without replacing, suppressing or retrying that failure."""
    selected = name if type(name) is str and name in _PHASES else "unknown"
    token = _PHASE.set(selected)
    try:
        try:
            yield
        except BaseException as error:
            _failure(error)
            raise
    finally:
        _PHASE.reset(token)


def _failure(error: BaseException, *, cleanup: bool = False) -> None:
    """Observe before a sanitizer; collector faults cannot replace its denial."""
    with suppress(BaseException):
        _record("close" if cleanup else _PHASE.get(), error)


def failure_diagnostic() -> str | None:
    """Return one closed, bounded canonical record, or nothing on collector error."""
    try:
        state = _CURRENT.get()
        if state is None or state.first is None:
            return None
        raw = json.dumps(
            {
                "schema_version": 1,
                "kind": "stock_producer_failure_diagnostic",
                "first": state.first,
                "secondary": state.secondary,
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ) + "\n"
        return raw if len(raw.encode("utf-8")) <= 1024 else None
    except BaseException:
        return None
