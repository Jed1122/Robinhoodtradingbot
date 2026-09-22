"""Non-promotable shadow-cycle harness whose economic effects stay simulated."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from trading_bot.app import DecisionCycleRequest, DecisionCycleResult
from trading_bot.brokers.fake import FakeBroker
from trading_bot.brokers.protocols import BrokerRead
from trading_bot.clock import Clock
from trading_bot.domain import AccountId
from trading_bot.market_data import content_hash


class ShadowCycle(Protocol):
    async def run_cycle(self, request: DecisionCycleRequest) -> DecisionCycleResult: ...


@dataclass(frozen=True, slots=True)
class ShadowConfig:
    account_id: AccountId
    account_equity_ceiling: str
    config_hash: str
    code_hash: str
    fixture_data: bool = False


@dataclass(frozen=True, slots=True)
class ShadowCycleEvidence:
    cycle_id: str
    started_at: datetime
    completed_at: datetime
    config_hash: str
    data_hash: str
    code_hash: str
    provider_ready: bool
    strategy_eligibility_hash: str
    simulated_outcomes: tuple[str, ...]
    reconciliation_equal: bool
    evidence_eligible: bool
    result: DecisionCycleResult


class ShadowEvidenceStore(Protocol):
    async def append_shadow(self, evidence: ShadowCycleEvidence) -> None: ...


class ShadowApplication:
    def __init__(
        self,
        config: ShadowConfig,
        broker_read: BrokerRead,
        cycle: ShadowCycle,
        fake_broker: FakeBroker,
        repositories: ShadowEvidenceStore,
        clock: Clock,
    ) -> None:
        self._config = config
        self._broker_read = broker_read
        self._cycle = cycle
        self._fake_broker = fake_broker
        self._repositories = repositories
        self._clock = clock

    async def run_cycle(self, request: DecisionCycleRequest) -> ShadowCycleEvidence:
        started = self._clock.now()
        accounts = await self._broker_read.get_accounts()
        matching = tuple(a for a in accounts if a.account_id == self._config.account_id)
        if len(matching) != 1:
            raise RuntimeError("shadow account selection changed")
        account = await self._broker_read.get_account_state(self._config.account_id)
        if account.account_id != self._config.account_id:
            raise RuntimeError("shadow account identity changed")
        if account.restricted:
            raise RuntimeError("shadow account is restricted")
        if account.equity > Decimal(self._config.account_equity_ceiling):
            raise RuntimeError("shadow account equity exceeds configured ceiling")
        await self._broker_read.get_positions(self._config.account_id)
        await self._broker_read.get_open_orders(self._config.account_id)
        # Holding this reference documents and enforces simulated execution composition.
        if not isinstance(self._fake_broker, FakeBroker):
            raise RuntimeError("shadow execution is not simulated")
        result = await self._cycle.run_cycle(request)
        completed = self._clock.now()
        eligibility_hash = content_hash(
            {
                "config_hash": self._config.config_hash,
                "eligible": False,
                "reason": "strategy_attestation_not_wired",
            }
        )
        evidence = ShadowCycleEvidence(
            cycle_id=content_hash(
                {
                    "account": str(self._config.account_id),
                    "as_of": request.as_of,
                    "code_hash": self._config.code_hash,
                    "config_hash": self._config.config_hash,
                    "data_hash": result.market.data_hash,
                }
            ),
            started_at=started,
            completed_at=completed,
            config_hash=self._config.config_hash,
            data_hash=result.market.data_hash,
            code_hash=self._config.code_hash,
            provider_ready=False,
            strategy_eligibility_hash=eligibility_hash,
            simulated_outcomes=tuple(str(item) for item in result.order_outcomes),
            reconciliation_equal=False,
            evidence_eligible=False,
            result=result,
        )
        await self._repositories.append_shadow(evidence)
        return evidence


def build_shadow_application(
    config: ShadowConfig,
    broker_read: BrokerRead,
    market_data: ShadowCycle,
    fake_broker: FakeBroker,
    repositories: ShadowEvidenceStore,
    clock: Clock,
) -> ShadowApplication:
    """Compose a non-promotable harness without any live placement capability."""
    return ShadowApplication(config, broker_read, market_data, fake_broker, repositories, clock)


__all__ = [
    "ShadowApplication",
    "ShadowConfig",
    "ShadowCycleEvidence",
    "ShadowEvidenceStore",
    "build_shadow_application",
]
