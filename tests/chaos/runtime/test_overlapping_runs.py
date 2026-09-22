import pytest

from trading_bot.runtime.daemon import RunCoordinator


@pytest.mark.asyncio
async def test_second_run_is_denied() -> None:
    coordinator = RunCoordinator()
    assert (await coordinator.try_start()).acquired
    assert not (await coordinator.try_start()).acquired
