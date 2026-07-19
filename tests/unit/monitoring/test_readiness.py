from datetime import UTC, datetime
from types import SimpleNamespace

from trading_bot.domain import ExecutionMode
from trading_bot.monitoring import ReadinessService
from trading_bot.runtime.live import LivePreflightResult


def test_readiness_reuses_live_preflight_denials() -> None:
    now = datetime(2026, 7, 17, tzinfo=UTC)
    snapshot = ReadinessService(
        ExecutionMode.MICRO_LIVE,
        lambda: LivePreflightResult(False, ("lease",)),
        SimpleNamespace(now=lambda: now),
    ).snapshot()
    assert not snapshot.ready and snapshot.denials == ("lease",)
