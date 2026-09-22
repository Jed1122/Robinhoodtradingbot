from datetime import UTC, datetime
from types import SimpleNamespace

from trading_bot.monitoring import HealthCheckResult, HealthService


def test_health_fails_when_any_check_fails() -> None:
    now = datetime(2026, 7, 17, tzinfo=UTC)
    service = HealthService(
        (lambda: HealthCheckResult("db", False, "down", now),), SimpleNamespace(now=lambda: now)
    )
    assert not service.snapshot().healthy
