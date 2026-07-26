import asyncio
import inspect
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

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
from trading_bot.domain import (
    CodeHash,
    ConfigHash,
    CorrelationId,
    InstrumentId,
    OrderState,
    StrategyEligibilityAttestation,
)
from trading_bot.execution import ExecutionResult
from trading_bot.market_data import content_hash
from trading_bot.persistence.research import PersistedStrategyEligibility
from trading_bot.research.validation import ResearchAssessment
from trading_bot.runtime.paper import (
    InMemoryPaperCycleStore,
    PaperApplication,
    PaperCycleConflict,
    build_paper_application,
)
from trading_bot.strategies import StrategyAction, StrategyDecision


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


@pytest.mark.asyncio
async def test_overlapping_same_paper_cycle_executes_once() -> None:
    store = InMemoryPaperCycleStore()
    cycle_service = service()
    application = build_paper_application(cycle_service, store=store)

    first, second = await asyncio.gather(
        application.run_cycle(request()),
        application.run_cycle(request()),
    )

    assert first == second
    assert cycle_service.execution.calls == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_changed_portfolio_has_a_distinct_paper_cycle_identity() -> None:
    store = InMemoryPaperCycleStore()
    application = build_paper_application(service(), store=store)
    first_request = request()
    changed_request = replace(
        first_request,
        portfolio=replace(first_request.portfolio, cash=Decimal("99")),
    )

    first = await application.run_cycle(first_request)
    changed = await application.run_cycle(changed_request)

    assert first.cycle_id != changed.cycle_id


@pytest.mark.asyncio
async def test_paper_store_rejects_conflicting_same_cycle_evidence() -> None:
    store = InMemoryPaperCycleStore()
    evidence = await build_paper_application(service(), store=store).run_cycle(request())

    with pytest.raises(PaperCycleConflict):
        await store.append(replace(evidence, promotable=True))


def accepted() -> PersistedStrategyEligibility:
    attestation = StrategyEligibilityAttestation(
        eligible=True,
        strategy_version="strategy-v1",
        config_hash=ConfigHash("c" * 64),
        code_hash=CodeHash("f" * 64),
        research_manifest_hash="a" * 64,
        report_hash="b" * 64,
        observed_at=datetime(2026, 7, 16, tzinfo=UTC),
    )
    return PersistedStrategyEligibility(
        attestation,
        content_hash(
            {
                "assessment": ResearchAssessment(True, True, ()),
                "attestation": attestation,
            }
        ),
    )


def test_paper_rejects_attestation_for_another_composed_build() -> None:
    with pytest.raises(ValueError, match="exact composed build"):
        build_paper_application(
            service(),
            store=InMemoryPaperCycleStore(),
            eligibility=accepted(),
            strategy_version="strategy-v2",
            code_hash=CodeHash("f" * 64),
        )


@pytest.mark.asyncio
async def test_paper_requires_completed_decisions_from_exact_accepted_strategy() -> None:
    application = build_paper_application(
        service(),
        store=InMemoryPaperCycleStore(),
        eligibility=accepted(),
        strategy_version="strategy-v1",
        code_hash=CodeHash("f" * 64),
    )

    empty_decisions = await application.run_cycle(request())

    assert not empty_decisions.research_cycle_eligible
    assert not empty_decisions.promotable


@pytest.mark.asyncio
async def test_paper_exact_strategy_decision_is_diagnostic_only() -> None:
    class DecidingStrategy:
        descriptor = None

        def decide(self, context):  # type: ignore[no-untyped-def]
            return (
                StrategyDecision(
                    context.eligible_instruments[0],
                    context.as_of,
                    StrategyAction.HOLD,
                    Decimal("0"),
                    ("test",),
                    "strategy-v1",
                    context.config_hash,
                    context.features.data_hash,
                ),
            )

    class TypedExecution:
        async def execute(self, intent):  # type: ignore[no-untyped-def]
            return ExecutionResult(
                intent.id,
                OrderState.RISK_REJECTED,
                "simulated_risk_denied",
                CorrelationId(f"paper-{intent.id}"),
                None,
                None,
                None,
            )

    cycle_service = DecisionCycleService(
        snapshot_loader=Loader(),
        features=Features(),
        strategies=(DecidingStrategy(),),
        portfolio=Portfolio(),
        intent_planner=Planner(),
        execution=TypedExecution(),
        journal=Journal(),
    )  # type: ignore[arg-type]
    cycle_request = request()
    cycle_request = replace(cycle_request, universe=(InstrumentId("TEST"),))
    application = build_paper_application(
        cycle_service,
        store=InMemoryPaperCycleStore(),
        eligibility=accepted(),
        strategy_version="strategy-v1",
        code_hash=CodeHash("f" * 64),
    )

    evidence = await application.run_cycle(cycle_request)

    assert evidence.research_cycle_eligible
    assert not evidence.promotable
    assert evidence.promotion_blockers == ("promotion_observation_not_wired",)


@pytest.mark.asyncio
async def test_submitted_resting_order_is_not_a_complete_paper_outcome() -> None:
    result = await service().run_cycle(request())
    intent = result.intents[0]
    submitted = replace(
        result,
        order_outcomes=(
            ExecutionResult(
                intent.id,
                OrderState.SUBMITTED,
                "simulated_resting",
                CorrelationId(f"paper-{intent.id}"),
                None,
                None,
                None,
            ),
        ),
    )

    assert not PaperApplication._outcomes_complete(submitted)
