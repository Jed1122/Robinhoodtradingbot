"""UTC-only clock abstractions."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable


class DomainValidationError(ValueError):
    """Raised when an immutable domain value violates a canonical invariant."""


class InvalidTimestamp(DomainValidationError):
    """Raised when a domain timestamp is naive or outside UTC."""


def require_utc(value: datetime) -> datetime:
    """Validate an aware UTC datetime and return it with the canonical UTC timezone."""
    if type(value) is not datetime or value.tzinfo is None:
        raise InvalidTimestamp("timestamp must be timezone-aware UTC")
    try:
        offset = value.utcoffset()
    except (OverflowError, ValueError) as exc:
        raise InvalidTimestamp("timestamp must have a valid UTC offset") from exc
    if offset != timedelta(0):
        raise InvalidTimestamp("timestamp must use UTC")
    return value.astimezone(UTC)


@runtime_checkable
class Clock(Protocol):
    """Source of aware UTC wall-clock time."""

    def now(self) -> datetime:
        """Return the current aware UTC timestamp."""
        ...


@dataclass(frozen=True, slots=True)
class SystemClock:
    """Production wall clock backed by the standard library."""

    def now(self) -> datetime:
        return datetime.now(UTC)
