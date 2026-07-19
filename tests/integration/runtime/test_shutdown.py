from datetime import UTC, datetime, timedelta

import pytest

from trading_bot.domain import RuntimeState
from trading_bot.runtime.shutdown import ShutdownCoordinator


class Clock:
    value = datetime(2026, 7, 17, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


@pytest.mark.asyncio
async def test_shutdown_blocks_new_intents_and_persists_paused_state() -> None:
    calls: list[str] = []

    async def action(name: str, result=None):  # type: ignore[no-untyped-def]
        calls.append(name)
        return result

    coordinator = ShutdownCoordinator(
        clock=Clock(),
        block_new_intents=lambda: calls.append("block"),
        stop_lease_renewal=lambda: action("lease"),
        finish_transactions=lambda: action("transactions"),
        reconcile_inflight=lambda: action("reconcile", True),
        persist_state=lambda state, reason: action(f"persist:{state}:{reason}"),
    )
    result = await coordinator.shutdown("SIGTERM", Clock.value + timedelta(seconds=30))
    assert result.new_intents_blocked and result.state_persisted
    assert result.final_state is RuntimeState.PAUSED
    assert calls == ["block", "lease", "transactions", "reconcile", "persist:paused:SIGTERM"]
