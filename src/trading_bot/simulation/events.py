"""Stable replay cursor identities."""

from dataclasses import dataclass
from datetime import datetime

from trading_bot.clock import require_utc


@dataclass(frozen=True, order=True, slots=True)
class EventCursor:
    sequence: int
    occurred_at: datetime

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("event sequence must be nonnegative")
        require_utc(self.occurred_at)


__all__ = ["EventCursor"]
