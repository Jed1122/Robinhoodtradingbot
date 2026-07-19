"""Single production decision-cycle composition used by every runtime mode."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from trading_bot.domain import ConfigHash, InstrumentId, OrderIntent, PortfolioSnapshot
from trading_bot.market_data import content_hash
from trading_bot.portfolio import (
    ExitPolicy,
    IntentPlanner,
    IntentPlanningContext,
    PortfolioConstructor,
    TargetPortfolio,
)
from trading_bot.strategies import (
    FeatureSnapshot,
    HistoricalSlice,
    Strategy,
    StrategyContext,
    StrategyDecision,
)


@dataclass(frozen=True, slots=True)
class ValidatedMarketSnapshot:
    as_of: datetime
    histories: tuple[HistoricalSlice, ...]
    data_hash: str


class MarketSnapshotLoader(Protocol):
    async def load(
        self, universe: tuple[InstrumentId, ...], as_of: datetime
    ) -> ValidatedMarketSnapshot: ...


class FeatureStage(Protocol):
    def compute(self, market: ValidatedMarketSnapshot, *, as_of: datetime) -> FeatureSnapshot: ...


class ExecutionStage(Protocol):
    async def execute(self, intent: OrderIntent) -> object: ...


class CycleJournal(Protocol):
    async def finalize(self, payload: object) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class DecisionCycleRequest:
    universe: tuple[InstrumentId, ...]
    as_of: datetime
    portfolio: PortfolioSnapshot
    strategy_context_config_hash: str
    exposure_multiplier: Decimal
    exit_policy: ExitPolicy
    intent_context: IntentPlanningContext


@dataclass(frozen=True, slots=True)
class DecisionCycleResult:
    market: ValidatedMarketSnapshot
    features: FeatureSnapshot
    decisions: tuple[StrategyDecision, ...]
    target: TargetPortfolio
    intents: tuple[OrderIntent, ...]
    order_outcomes: tuple[object, ...]
    audit_event_ids: tuple[str, ...]
    result_hash: str


class DecisionCycleService:
    def __init__(
        self,
        *,
        snapshot_loader: MarketSnapshotLoader,
        features: FeatureStage,
        strategies: tuple[Strategy, ...],
        portfolio: PortfolioConstructor,
        intent_planner: IntentPlanner,
        execution: ExecutionStage,
        journal: CycleJournal,
    ) -> None:
        self.snapshot_loader = snapshot_loader
        self.features = features
        self.strategies = strategies
        self.portfolio = portfolio
        self.intent_planner = intent_planner
        self.execution = execution
        self.journal = journal

    async def run_cycle(self, request: DecisionCycleRequest) -> DecisionCycleResult:
        market = await self.snapshot_loader.load(request.universe, request.as_of)
        features = self.features.compute(market, as_of=request.as_of)
        context = StrategyContext(
            request.as_of,
            features,
            ConfigHash(request.strategy_context_config_hash),
            request.universe,
        )
        decisions = tuple(
            decision for strategy in self.strategies for decision in strategy.decide(context)
        )
        target = self.portfolio.construct(
            decisions,
            request.portfolio,
            as_of=request.as_of,
            config_hash=context.config_hash,
            exposure_multiplier=request.exposure_multiplier,
            exit_policy=request.exit_policy,
        )
        intents = self.intent_planner.plan(target, request.intent_context)
        outcomes = tuple([await self.execution.execute(intent) for intent in intents])
        payload = {
            "decisions": decisions,
            "features": features,
            "intents": intents,
            "market_hash": market.data_hash,
            "outcomes": tuple(str(item) for item in outcomes),
            "target": target,
        }
        audit_ids = await self.journal.finalize(payload)
        return DecisionCycleResult(
            market,
            features,
            decisions,
            target,
            intents,
            outcomes,
            audit_ids,
            content_hash({"audit_ids": audit_ids, "payload": payload}),
        )


__all__ = [
    "DecisionCycleRequest",
    "DecisionCycleResult",
    "DecisionCycleService",
    "MarketSnapshotLoader",
    "ValidatedMarketSnapshot",
]
