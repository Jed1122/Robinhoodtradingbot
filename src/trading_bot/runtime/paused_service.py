"""Health-only runtime composition that cannot construct broker write capabilities."""

from fastapi import FastAPI

from trading_bot.clock import Clock, SystemClock
from trading_bot.domain import ExecutionMode
from trading_bot.monitoring import HealthCheckResult, HealthService, ReadinessService
from trading_bot.monitoring.api import AdminBindPolicy, build_monitoring_app
from trading_bot.monitoring.metrics import MetricsRegistry
from trading_bot.runtime.live import LivePreflightResult


def build_paused_monitoring_service(
    *,
    mode: ExecutionMode,
    host: str,
    container_loopback_publish: bool,
    clock: Clock | None = None,
) -> FastAPI:
    """Build a process-health API that is deliberately never execution-ready."""

    if mode is not ExecutionMode.SHADOW:
        raise ValueError("paused monitoring service only supports shadow mode")
    AdminBindPolicy.validate(host, container_loopback_publish)
    active_clock = SystemClock() if clock is None else clock

    def process_check() -> HealthCheckResult:
        return HealthCheckResult(
            name="process",
            healthy=True,
            reason_code="paused",
            observed_at=active_clock.now(),
        )

    def locked_preflight() -> LivePreflightResult:
        return LivePreflightResult(False, ("paused", "external_capability_missing"))

    health = HealthService((process_check,), active_clock)
    readiness = ReadinessService(mode, locked_preflight, active_clock)
    metrics = MetricsRegistry()
    metrics.set("trading_bot_up", 1.0)
    metrics.set("trading_bot_paused", 1.0)
    metrics.set("trading_bot_live_enabled", 0.0)
    return build_monitoring_app(health, readiness, metrics)


__all__ = ["build_paused_monitoring_service"]
