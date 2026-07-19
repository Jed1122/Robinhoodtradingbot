"""Static capability policy for offline and connected runtime modes."""

from dataclasses import dataclass

from trading_bot.domain import ExecutionMode


@dataclass(frozen=True, slots=True)
class ModeCapabilities:
    network_reads: bool
    simulated_execution: bool
    live_placement: bool
    starts_paused: bool


def mode_capabilities(mode: ExecutionMode) -> ModeCapabilities:
    if mode in {ExecutionMode.BACKTEST, ExecutionMode.SIMULATION, ExecutionMode.PAPER}:
        return ModeCapabilities(False, True, False, mode is ExecutionMode.PAPER)
    if mode is ExecutionMode.SHADOW:
        return ModeCapabilities(True, True, False, True)
    return ModeCapabilities(True, False, False, True)


__all__ = ["ModeCapabilities", "mode_capabilities"]
