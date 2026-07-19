from datetime import UTC, datetime

import pytest

from trading_bot.monitoring.alerts import Alert, AlertService, AlertType


@pytest.mark.asyncio
async def test_repeated_alerts_are_deduplicated() -> None:
    class Sink:
        calls = 0

        async def send(self, alert):
            self.calls += 1  # type: ignore[no-untyped-def]

    sink = Sink()
    service = AlertService(sink)
    alert = Alert(AlertType.STALE_DATA, "stale", datetime(2026, 7, 17, tzinfo=UTC))
    await service.emit(alert)
    await service.emit(alert)
    assert sink.calls == 1
