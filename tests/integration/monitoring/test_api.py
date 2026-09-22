from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from trading_bot.domain import ExecutionMode
from trading_bot.monitoring import HealthCheckResult, HealthService, ReadinessService
from trading_bot.monitoring.api import build_monitoring_app
from trading_bot.monitoring.metrics import MetricsRegistry
from trading_bot.runtime.live import LivePreflightResult


def test_unready_returns_503() -> None:
    now = datetime(2026, 7, 17, tzinfo=UTC)
    clock = SimpleNamespace(now=lambda: now)
    health = HealthService((lambda: HealthCheckResult("process", True, "ok", now),), clock)
    ready = ReadinessService(
        ExecutionMode.SHADOW, lambda: LivePreflightResult(False, ("paused",)), clock
    )
    client = TestClient(build_monitoring_app(health, ready, MetricsRegistry()))
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 503
