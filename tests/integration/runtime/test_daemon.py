from trading_bot.runtime.daemon import build_daemon_application


def test_daemon_defaults_paused() -> None:
    assert build_daemon_application().paused
