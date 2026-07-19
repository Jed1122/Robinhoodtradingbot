from dataclasses import dataclass
from datetime import datetime

from trading_bot.domain import ExecutionMode
from trading_bot.runtime.live import LivePreflightResult


@dataclass(frozen=True, slots=True)
class ReadinessSnapshot:
    mode: ExecutionMode
    ready: bool
    denials: tuple[str, ...]
    observed_at: datetime


class ReadinessService:
    def __init__(self, mode: ExecutionMode, preflight, clock):  # type: ignore[no-untyped-def]
        self._mode, self._preflight, self._clock = mode, preflight, clock

    def snapshot(self) -> ReadinessSnapshot:
        result: LivePreflightResult = self._preflight()
        return ReadinessSnapshot(self._mode, result.ready, result.reason_codes, self._clock.now())


__all__ = ["ReadinessService", "ReadinessSnapshot"]
