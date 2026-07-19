"""Recorded-data backtest composition with simulated execution only."""

from trading_bot.app import DecisionCycleService
from trading_bot.simulation import SimulationEngine


def build_backtest_application(cycle_service: DecisionCycleService) -> SimulationEngine:
    return SimulationEngine(cycle_service)


__all__ = ["build_backtest_application"]
