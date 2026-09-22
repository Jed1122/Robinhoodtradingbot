from trading_bot.runtime import build_backtest_application, build_simulation_application


def test_offline_builders_require_only_the_production_cycle_service() -> None:
    assert build_backtest_application.__code__.co_argcount == 1
    assert build_simulation_application.__code__.co_argcount == 1
