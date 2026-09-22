"""Monotonic controllable UTC clock for replay."""

from datetime import datetime

from trading_bot.clock import require_utc


class SimulatedClock:
    def __init__(self, current: datetime) -> None:
        self._current = require_utc(current)

    def now(self) -> datetime:
        return self._current

    def set(self, current: datetime) -> None:
        current = require_utc(current)
        if current < self._current:
            raise ValueError("simulated clock cannot move backward")
        self._current = current


__all__ = ["SimulatedClock"]
