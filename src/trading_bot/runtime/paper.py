"""Restart-safe paper runtime backed exclusively by the simulated execution path."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Protocol

from trading_bot.app import DecisionCycleRequest, DecisionCycleResult, DecisionCycleService
from trading_bot.domain import CodeHash, OrderState
from trading_bot.execution import ExecutionResult
from trading_bot.market_data import content_hash
from trading_bot.persistence.research import PersistedStrategyEligibility

_COMPLETE_EXECUTION_STATES = frozenset(
    {
        OrderState.RISK_REJECTED,
        OrderState.FILLED,
        OrderState.CANCELED,
        OrderState.REJECTED,
        OrderState.EXPIRED,
    }
)


@dataclass(frozen=True, slots=True)
class PaperCycleEvidence:
    """Local cycle diagnostics; never a durable promotion observation."""

    cycle_id: str
    result: DecisionCycleResult
    economic_effect_ids: tuple[str, ...]
    strategy_eligibility_hash: str | None
    research_cycle_eligible: bool
    promotable: bool
    promotion_blockers: tuple[str, ...]


class PaperCycleStore(Protocol):
    def claim(self, cycle_id: str) -> AbstractAsyncContextManager[None]: ...
    async def get(self, cycle_id: str) -> PaperCycleEvidence | None: ...
    async def append(self, evidence: PaperCycleEvidence) -> None: ...


class PaperCycleConflict(RuntimeError):
    pass


class InMemoryPaperCycleStore:
    def __init__(self) -> None:
        self._cycles: dict[str, PaperCycleEvidence] = {}
        self._claims: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def claim(self, cycle_id: str) -> AsyncIterator[None]:
        lock = self._claims.setdefault(cycle_id, asyncio.Lock())
        async with lock:
            yield

    async def get(self, cycle_id: str) -> PaperCycleEvidence | None:
        return self._cycles.get(cycle_id)

    async def append(self, evidence: PaperCycleEvidence) -> None:
        existing = self._cycles.get(evidence.cycle_id)
        if existing is not None and existing != evidence:
            raise PaperCycleConflict("paper cycle evidence identity conflicts")
        self._cycles[evidence.cycle_id] = evidence


class PaperApplication:
    def __init__(
        self,
        cycle_service: DecisionCycleService,
        store: PaperCycleStore,
        eligibility: PersistedStrategyEligibility | None,
        *,
        strategy_version: str | None,
        code_hash: CodeHash | None,
    ) -> None:
        if eligibility is not None and (
            strategy_version is None
            or code_hash is None
            or eligibility.attestation.strategy_version != strategy_version
            or eligibility.attestation.code_hash != code_hash
        ):
            raise ValueError("paper strategy eligibility must match the exact composed build")
        self._cycle_service = cycle_service
        self._store = store
        self._eligibility = eligibility
        self._strategy_version = strategy_version
        self._code_hash = code_hash

    @staticmethod
    def _outcomes_complete(result: DecisionCycleResult) -> bool:
        if len(result.order_outcomes) != len(result.intents):
            return False
        return all(
            type(outcome) is ExecutionResult
            and outcome.intent_id == intent.id
            and outcome.state in _COMPLETE_EXECUTION_STATES
            for intent, outcome in zip(
                result.intents,
                result.order_outcomes,
                strict=True,
            )
        )

    async def run_cycle(self, request: DecisionCycleRequest) -> PaperCycleEvidence:
        eligibility_hash = None if self._eligibility is None else self._eligibility.evidence_hash
        cycle_id = content_hash(
            {
                "code_hash": self._code_hash,
                "request": request,
                "strategy_eligibility_hash": eligibility_hash,
                "strategy_version": self._strategy_version,
            }
        )
        async with self._store.claim(cycle_id):
            existing = await self._store.get(cycle_id)
            if existing is not None:
                return existing
            result = await self._cycle_service.run_cycle(request)
            economic_ids = tuple(str(intent.id) for intent in result.intents)
            persisted_eligibility = self._eligibility
            eligible = None if persisted_eligibility is None else persisted_eligibility.attestation
            decision_versions = {item.strategy_version for item in result.decisions}
            research_cycle_eligible = bool(
                eligible is not None
                and eligible.eligible
                and eligible.config_hash == request.strategy_context_config_hash
                and eligible.code_hash == self._code_hash
                and eligible.strategy_version == self._strategy_version
                and decision_versions == {eligible.strategy_version}
                and self._outcomes_complete(result)
                and bool(result.audit_event_ids)
            )
            evidence = PaperCycleEvidence(
                cycle_id,
                result,
                economic_ids,
                eligibility_hash,
                research_cycle_eligible,
                False,
                ("promotion_observation_not_wired",),
            )
            await self._store.append(evidence)
            return evidence


def build_paper_application(
    cycle_service: DecisionCycleService,
    *,
    store: PaperCycleStore,
    eligibility: PersistedStrategyEligibility | None = None,
    strategy_version: str | None = None,
    code_hash: CodeHash | None = None,
) -> PaperApplication:
    return PaperApplication(
        cycle_service,
        store,
        eligibility,
        strategy_version=strategy_version,
        code_hash=code_hash,
    )


__all__ = [
    "InMemoryPaperCycleStore",
    "PaperApplication",
    "PaperCycleConflict",
    "PaperCycleEvidence",
    "PaperCycleStore",
    "build_paper_application",
]
