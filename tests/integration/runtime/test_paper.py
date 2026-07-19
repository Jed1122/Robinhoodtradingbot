import inspect

import pytest

from tests.integration.simulation.test_decision_cycle import (
    Execution,
    Features,
    Journal,
    Loader,
    Planner,
    Portfolio,
    Strategy,
    request,
)
from trading_bot.app import DecisionCycleService
from trading_bot.runtime.paper import InMemoryPaperCycleStore, build_paper_application


def service() -> DecisionCycleService:
    return DecisionCycleService(
        snapshot_loader=Loader(),
        features=Features(),
        strategies=(Strategy(),),
        portfolio=Portfolio(),
        intent_planner=Planner(),
        execution=Execution(),
        journal=Journal(),
    )  # type: ignore[arg-type]


def test_paper_composition_cannot_accept_place_capability() -> None:
    assert "broker_place" not in inspect.signature(build_paper_application).parameters


@pytest.mark.asyncio
async def test_paper_restart_does_not_duplicate_effect() -> None:
    store = InMemoryPaperCycleStore()
    first = await build_paper_application(service(), store=store).run_cycle(request())
    second = await build_paper_application(service(), store=store).run_cycle(request())
    assert second.economic_effect_ids == first.economic_effect_ids
    assert second.result.result_hash == first.result.result_hash
