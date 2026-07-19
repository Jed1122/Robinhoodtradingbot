"""Deterministic event-priority simulation over the production decision cycle."""

from dataclasses import dataclass
from enum import IntEnum

from trading_bot.app import DecisionCycleRequest, DecisionCycleResult, DecisionCycleService
from trading_bot.market_data import content_hash


class EventPriority(IntEnum):
    CORPORATE_AND_SESSION = 0
    MARKET_DATA = 1
    BROKER_UPDATE = 2
    STRATEGY_CYCLE = 3
    RECONCILIATION = 4
    REPORTING = 5


@dataclass(frozen=True, slots=True)
class SimulationRequest:
    cycles: tuple[DecisionCycleRequest, ...]
    seed: int


@dataclass(frozen=True, slots=True)
class SimulationResult:
    cycles: tuple[DecisionCycleResult, ...]
    seed: int
    result_hash: str


class SimulationEngine:
    def __init__(self, cycle_service: DecisionCycleService) -> None:
        self._cycle_service = cycle_service

    async def run(self, request: SimulationRequest) -> SimulationResult:
        ordered = tuple(sorted(request.cycles, key=lambda item: item.as_of))
        results = tuple([await self._cycle_service.run_cycle(cycle) for cycle in ordered])
        result_hash = content_hash(
            {"cycle_hashes": tuple(item.result_hash for item in results), "seed": request.seed}
        )
        return SimulationResult(results, request.seed, result_hash)


__all__ = ["EventPriority", "SimulationEngine", "SimulationRequest", "SimulationResult"]
