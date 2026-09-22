from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from trading_bot.domain import ExecutionMode
from trading_bot.runtime.paused_service import build_paused_monitoring_service


def test_paused_service_is_healthy_but_never_ready() -> None:
    now = datetime(2026, 7, 21, tzinfo=UTC)
    app = build_paused_monitoring_service(
        mode=ExecutionMode.SHADOW,
        host="127.0.0.1",
        container_loopback_publish=False,
        clock=SimpleNamespace(now=lambda: now),
    )
    client = TestClient(app)

    health = client.get("/healthz")
    readiness = client.get("/readyz")
    metrics = client.get("/metrics")

    assert health.status_code == 200
    assert health.json()["checks"][0]["reason_code"] == "paused"
    assert readiness.status_code == 503
    assert readiness.json()["denials"] == ["paused", "external_capability_missing"]
    assert "trading_bot_paused 1.0" in metrics.text
    assert "trading_bot_live_enabled 0.0" in metrics.text


def test_paused_service_rejects_live_modes() -> None:
    with pytest.raises(ValueError, match="only supports shadow"):
        build_paused_monitoring_service(
            mode=ExecutionMode.MICRO_LIVE,
            host="127.0.0.1",
            container_loopback_publish=False,
        )
