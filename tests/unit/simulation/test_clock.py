from datetime import UTC, datetime, timedelta

import pytest

from trading_bot.simulation import SimulatedClock


def test_simulated_clock_is_monotonic() -> None:
    now = datetime(2026, 7, 17, tzinfo=UTC)
    clock = SimulatedClock(now)
    clock.set(now + timedelta(seconds=1))
    with pytest.raises(ValueError, match="backward"):
        clock.set(now)
