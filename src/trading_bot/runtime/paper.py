"""Restart-safe paper runtime backed exclusively by the simulated execution path."""

from dataclasses import dataclass
from typing import Protocol

from trading_bot.app import DecisionCycleRequest, DecisionCycleResult, DecisionCycleService
from trading_bot.domain import StrategyEligibilityAttestation
from trading_bot.market_data import content_hash


@dataclass(frozen=True, slots=True)
class PaperCycleEvidence:
    cycle_id: str
    result: DecisionCycleResult
    economic_effect_ids: tuple[str, ...]
    promotable: bool


class PaperCycleStore(Protocol):
    async def get(self, cycle_id: str) -> PaperCycleEvidence | None: ...
    async def append(self, evidence: PaperCycleEvidence) -> None: ...


class InMemoryPaperCycleStore:
    def __init__(self) -> None:
        self._cycles: dict[str, PaperCycleEvidence] = {}

    async def get(self, cycle_id: str) -> PaperCycleEvidence | None:
        return self._cycles.get(cycle_id)

    async def append(self, evidence: PaperCycleEvidence) -> None:
        self._cycles.setdefault(evidence.cycle_id, evidence)


class PaperApplication:
    def __init__(
        self,
        cycle_service: DecisionCycleService,
        store: PaperCycleStore,
        eligibility: StrategyEligibilityAttestation | None,
    ) -> None:
        self._cycle_service = cycle_service
        self._store = store
        self._eligibility = eligibility

    async def run_cycle(self, request: DecisionCycleRequest) -> PaperCycleEvidence:
        cycle_id = content_hash(
            {
                "as_of": request.as_of,
                "config_hash": request.strategy_context_config_hash,
                "universe": request.universe,
            }
        )
        existing = await self._store.get(cycle_id)
        if existing is not None:
            return existing
        result = await self._cycle_service.run_cycle(request)
        economic_ids = tuple(str(intent.id) for intent in result.intents)
        eligible = self._eligibility
        promotable = bool(
            eligible is not None
            and eligible.eligible
            and eligible.config_hash == request.strategy_context_config_hash
        )
        evidence = PaperCycleEvidence(cycle_id, result, economic_ids, promotable)
        await self._store.append(evidence)
        return evidence


def build_paper_application(
    cycle_service: DecisionCycleService,
    *,
    store: PaperCycleStore,
    eligibility: StrategyEligibilityAttestation | None = None,
) -> PaperApplication:
    return PaperApplication(cycle_service, store, eligibility)


__all__ = [
    "InMemoryPaperCycleStore",
    "PaperApplication",
    "PaperCycleEvidence",
    "PaperCycleStore",
    "build_paper_application",
]
