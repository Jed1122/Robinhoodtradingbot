from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from trading_bot.clock import Clock


@dataclass(frozen=True, slots=True)
class HealthCheckResult:
    name: str
    healthy: bool
    reason_code: str
    observed_at: datetime
    details: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    healthy: bool
    checks: tuple[HealthCheckResult, ...]
    observed_at: datetime


class HealthService:
    def __init__(
        self,
        checks: Iterable[Callable[[], HealthCheckResult]],
        clock: Clock,
    ) -> None:
        self._checks, self._clock = tuple(checks), clock

    def snapshot(self) -> HealthSnapshot:
        checks = tuple(check() for check in self._checks)
        return HealthSnapshot(all(check.healthy for check in checks), checks, self._clock.now())


__all__ = ["HealthCheckResult", "HealthService", "HealthSnapshot"]
