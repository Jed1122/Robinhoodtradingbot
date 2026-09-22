from pathlib import Path

from trading_bot.domain import RuntimeState
from trading_bot.runtime.runner import RuntimeRunner


def test_runner_always_defaults_paused() -> None:
    assert RuntimeRunner().state is RuntimeState.PAUSED


def test_place_factory_occurs_after_all_live_gates() -> None:
    source = Path("src/trading_bot/runtime/live.py").read_text()
    assert source.rindex("place_factory()") > source.index("authorization is None")
    assert source.rindex("place_factory()") > source.index("promotion is None")
