from trading_bot.domain import ExecutionMode
from trading_bot.runtime import mode_capabilities


def test_offline_and_paper_modes_never_enable_live_placement() -> None:
    for mode in (ExecutionMode.BACKTEST, ExecutionMode.SIMULATION, ExecutionMode.PAPER):
        assert not mode_capabilities(mode).live_placement
        assert mode_capabilities(mode).simulated_execution
