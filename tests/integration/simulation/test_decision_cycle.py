from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tests.unit.execution._fixtures import make_intent
from trading_bot.app import (
    DecisionCycleRequest,
    DecisionCycleService,
    ValidatedMarketSnapshot,
)
from trading_bot.domain import AccountId, ConfigHash, DataHash, PortfolioSnapshot
from trading_bot.portfolio import ExitPolicy, IntentPlanningContext, TargetPortfolio
from trading_bot.strategies import FeatureSnapshot

NOW = datetime(2026, 7, 17, tzinfo=UTC)


class Loader:
    async def load(self, universe: tuple, as_of: datetime) -> ValidatedMarketSnapshot:
        return ValidatedMarketSnapshot(as_of, (), "a" * 64)


class Features:
    def compute(self, market: ValidatedMarketSnapshot, *, as_of: datetime) -> FeatureSnapshot:
        return FeatureSnapshot(as_of, (), DataHash("b" * 64))


class Strategy:
    descriptor = None

    def decide(self, context: object) -> tuple:
        return ()


class Portfolio:
    def construct(self, *args: object, **kwargs: object) -> TargetPortfolio:
        return TargetPortfolio(NOW, (), Decimal("100"), ConfigHash("c" * 64), DataHash("d" * 64))


class Planner:
    def plan(self, target: TargetPortfolio, context: IntentPlanningContext) -> tuple:
        return (make_intent(config_hash=ConfigHash("c" * 64)),)


class Execution:
    calls = 0

    async def execute(self, intent: object) -> str:
        self.calls += 1
        return "submitted"


class Journal:
    async def finalize(self, payload: object) -> tuple[str, ...]:
        return ("audit-1",)


def request() -> DecisionCycleRequest:
    portfolio = PortfolioSnapshot(
        AccountId("paper-account"),
        (),
        Decimal("100"),
        Decimal("100"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        NOW,
        DataHash("e" * 64),
    )
    planning = IntentPlanningContext(
        AccountId("paper-account"),
        portfolio,
        (),
        (),
        Decimal("100"),
        Decimal("100"),
        None,
        None,
        timedelta(minutes=1),
    )  # type: ignore[arg-type]
    return DecisionCycleRequest(
        (),
        NOW,
        portfolio,
        "c" * 64,
        Decimal("0.5"),
        ExitPolicy("exit-v1", "atr", Decimal("1"), Decimal("2"), 10),
        planning,
    )


@pytest.mark.asyncio
async def test_cycle_uses_one_execution_path_and_journals_result() -> None:
    execution = Execution()
    service = DecisionCycleService(
        snapshot_loader=Loader(),
        features=Features(),
        strategies=(Strategy(),),
        portfolio=Portfolio(),
        intent_planner=Planner(),
        execution=execution,
        journal=Journal(),
    )  # type: ignore[arg-type]
    result = await service.run_cycle(request())
    assert result.order_outcomes == ("submitted",)
    assert execution.calls == 1
    assert result.audit_event_ids == ("audit-1",)
