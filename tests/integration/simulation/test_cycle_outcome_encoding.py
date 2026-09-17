"""Replay-specific encoding reaches the real cycle journal without object stringification."""

from dataclasses import dataclass, fields, replace

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
from tests.unit.portfolio.test_replay_seams import ID, POLICY, decision
from trading_bot.app import DecisionCycleService, PerInstrumentDecisionCycleRequest
from trading_bot.market_data import content_hash
from trading_bot.portfolio import PortfolioConstructor
from trading_bot.runtime.paper import InMemoryPaperCycleStore, PaperApplication


class CaptureJournal(Journal):
    def __init__(self):
        self.payloads = []

    async def finalize(self, payload):
        self.payloads.append(payload)
        return await super().finalize(payload)


@dataclass(frozen=True)
class Outcome:
    accepted: bool

    def __str__(self):
        raise AssertionError("typed replay outcomes must not be stringified")


class TypedExecution:
    async def execute(self, intent):
        return Outcome(True)


def service(**changes):
    values = dict(
        snapshot_loader=Loader(),
        features=Features(),
        strategies=(Strategy(),),
        portfolio=Portfolio(),
        intent_planner=Planner(),
        execution=Execution(),
        journal=CaptureJournal(),
    )
    values.update(changes)
    return DecisionCycleService(**values)


@pytest.mark.asyncio
async def test_typed_encoder_controls_canonical_outcomes_and_hash():
    def encode(value):
        if type(value) is not Outcome:
            raise ValueError("outcome_type_invalid")
        return {"accepted": value.accepted, "version": "replay-test-v1"}

    runner = service(execution=TypedExecution(), outcome_encoder=encode)
    result = await runner.run_cycle(request())
    assert result.order_outcomes == (Outcome(True),)
    assert runner.journal.payloads[0]["outcomes"] == (
        {"accepted": True, "version": "replay-test-v1"},
    )
    assert result.result_hash == (await runner.run_cycle(request())).result_hash


@pytest.mark.asyncio
async def test_encoder_denial_prevents_journal_publication():
    def deny(value):
        raise ValueError("outcome_type_invalid")

    runner = service(outcome_encoder=deny)
    with pytest.raises(ValueError, match=r"^outcome_type_invalid$"):
        await runner.run_cycle(request())
    assert runner.journal.payloads == []


@pytest.mark.asyncio
async def test_policy_map_is_forwarded_through_actual_decision_cycle():
    class EntryStrategy:
        def decide(self, context):
            return (decision(),)

    runner = service(strategies=(EntryStrategy(),), portfolio=PortfolioConstructor())
    original = replace(request(), exit_policy=None)
    values = {field.name: getattr(original, field.name) for field in fields(original)}
    result = await runner.run_cycle(
        PerInstrumentDecisionCycleRequest(**values, exit_policies=((ID, POLICY),))
    )
    assert result.target.positions[0].exit_policy == POLICY


@pytest.mark.asyncio
async def test_default_encoder_preserves_legacy_outcome_payload():
    runner = service()
    result = await runner.run_cycle(request())
    assert runner.journal.payloads[0]["outcomes"] == ("submitted",)
    assert result.order_outcomes == ("submitted",)
    assert result.result_hash == "574e02b3aee45ab852b636eef33c331465060094490d3f9a5b8699ca816b932e"


def test_default_request_keeps_existing_paper_restart_identity():
    value = request()
    legacy_request = {
        name: getattr(value, name)
        for name in (
            "universe",
            "as_of",
            "portfolio",
            "strategy_context_config_hash",
            "exposure_multiplier",
            "exit_policy",
            "intent_context",
        )
    }
    expected = content_hash(
        {
            "code_hash": None,
            "request": legacy_request,
            "strategy_eligibility_hash": None,
            "strategy_version": None,
        }
    )
    paper = PaperApplication(
        service(),
        InMemoryPaperCycleStore(),
        None,
        strategy_version=None,
        code_hash=None,
    )
    assert paper.cycle_id(value) == expected
