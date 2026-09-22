"""Deterministic simulation composition with no network writer."""

from trading_bot.app import DecisionCycleService
from trading_bot.simulation import SimulationEngine


def build_simulation_application(cycle_service: DecisionCycleService) -> SimulationEngine:
    return SimulationEngine(cycle_service)


__all__ = ["build_simulation_application"]
