"""Replay determinism assertion helper."""

from trading_bot.simulation.engine import SimulationEngine, SimulationRequest, SimulationResult


async def replay_twice(
    engine: SimulationEngine, request: SimulationRequest
) -> tuple[SimulationResult, SimulationResult]:
    first = await engine.run(request)
    second = await engine.run(request)
    if first.result_hash != second.result_hash:
        raise RuntimeError("identical replay inputs produced different hashes")
    return first, second


__all__ = ["replay_twice"]
