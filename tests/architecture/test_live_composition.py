import inspect

from trading_bot.runtime.live import build_cancel_only_recovery


def test_cancel_only_recovery_has_no_place_dependency() -> None:
    assert "broker_place" not in inspect.signature(build_cancel_only_recovery).parameters
