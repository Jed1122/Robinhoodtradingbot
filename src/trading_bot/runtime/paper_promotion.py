"""Durable, restart-safe promotion observations for simulated paper cycles."""

from __future__ import annotations

import asyncio
import fcntl
import os
import stat
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from trading_bot.app import DecisionCycleRequest
from trading_bot.clock import Clock
from trading_bot.domain import AccountId
from trading_bot.monitoring.promotion import (
    PromotionIdentity,
    PromotionObservation,
    PromotionStage,
)
from trading_bot.runtime.paper import PaperApplication, PaperCycleEvidence


class PaperCycleAlreadyInProgress(RuntimeError):
    """Raised when another process owns the same paper-cycle claim."""


class PaperPromotionStore(Protocol):
    async def append(self, observation: PromotionObservation) -> bool: ...

    async def list_for_identity(
        self, identity: PromotionIdentity
    ) -> tuple[PromotionObservation, ...]: ...


class PaperCycleMutex:
    """Non-waiting cross-process exclusion for one deterministic paper cycle."""

    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)
        metadata = self._directory.stat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise PermissionError("paper lock directory must be service-owned")
        if metadata.st_mode & 0o077:
            raise PermissionError("paper lock directory must use mode 0700 or stricter")
        self._local_claims: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def acquire(self, cycle_id: str) -> AsyncIterator[None]:
        if len(cycle_id) != 64 or any(
            character not in "0123456789abcdef" for character in cycle_id
        ):
            raise ValueError("paper cycle id must be lowercase SHA-256 hex")
        local_claim = self._local_claims.setdefault(cycle_id, asyncio.Lock())
        async with local_claim:
            path = self._directory / f"paper-{cycle_id}.lock"
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                os.fchmod(descriptor, 0o600)
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise PaperCycleAlreadyInProgress(
                        "paper cycle is already running"
                    ) from None
                try:
                    yield
                finally:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


@dataclass(frozen=True, slots=True)
class PaperPromotionContext:
    """Trusted composition inputs that cannot be inferred from a cycle result."""

    identity: PromotionIdentity
    expected_account_id: AccountId
    provider_evidence_verified: bool
    data_validated: bool
    reconciliation_clean: bool
    fixture_data: bool
    runtime_scope_valid: bool

    def __post_init__(self) -> None:
        if type(self.identity) is not PromotionIdentity:
            raise TypeError("identity must be a PromotionIdentity")
        if type(self.expected_account_id) is not str or not self.expected_account_id:
            raise ValueError("expected account id is required")
        for name in (
            "provider_evidence_verified",
            "data_validated",
            "reconciliation_clean",
            "fixture_data",
            "runtime_scope_valid",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact bool")


@dataclass(frozen=True, slots=True)
class RecordedPaperCycle:
    """A new simulated cycle or an already durable observation after restart."""

    observation: PromotionObservation
    cycle: PaperCycleEvidence | None
    executed: bool


class PaperPromotionApplication:
    """Run a paper cycle once and append its derived promotion observation."""

    def __init__(
        self,
        *,
        paper: PaperApplication,
        context: PaperPromotionContext,
        observations: PaperPromotionStore,
        mutex: PaperCycleMutex,
        clock: Clock,
    ) -> None:
        identity = context.identity
        if (
            paper.strategy_version is None
            or paper.code_hash is None
            or paper.strategy_eligibility_hash is None
            or identity.strategy_version != paper.strategy_version
            or identity.code_hash != paper.code_hash
            or identity.strategy_eligibility_hash != paper.strategy_eligibility_hash
        ):
            raise ValueError("paper promotion identity must match accepted research and code")
        self._paper = paper
        self._context = context
        self._observations = observations
        self._mutex = mutex
        self._clock = clock

    async def run_cycle(self, request: DecisionCycleRequest) -> RecordedPaperCycle:
        cycle_id = self._paper.cycle_id(request)
        async with self._mutex.acquire(cycle_id):
            durable = await self._observations.list_for_identity(self._context.identity)
            existing = tuple(
                item
                for item in durable
                if item.stage is PromotionStage.PAPER and item.cycle_id == cycle_id
            )
            if len(existing) > 1:
                raise RuntimeError("paper cycle has conflicting durable observations")
            if existing:
                return RecordedPaperCycle(existing[0], None, False)

            started_at = self._clock.now()
            cycle = await self._paper.run_cycle(request)
            completed_at = self._clock.now()
            if cycle.cycle_id != cycle_id:
                raise RuntimeError("paper cycle identity changed during execution")
            identity = self._context.identity
            account_identity_matches = (
                request.portfolio.account_id == self._context.expected_account_id
                and request.intent_context.account_id == self._context.expected_account_id
                and request.intent_context.portfolio.account_id
                == self._context.expected_account_id
            )
            config_identity_matches = (
                request.strategy_context_config_hash == identity.config_hash
            )
            outcomes_complete = PaperApplication._outcomes_complete(cycle.result)
            observation = PromotionObservation.create(
                stage=PromotionStage.PAPER,
                cycle_id=cycle_id,
                identity=identity,
                started_at=started_at,
                completed_at=completed_at,
                data_hash=cycle.result.market.data_hash,
                identity_verified=account_identity_matches and config_identity_matches,
                provider_evidence_verified=self._context.provider_evidence_verified,
                strategy_eligible=cycle.research_cycle_eligible,
                authenticated_reads=False,
                data_validated=self._context.data_validated,
                outcomes_complete=outcomes_complete,
                reconciliation_clean=self._context.reconciliation_clean,
                fixture_data=self._context.fixture_data,
                runtime_scope_valid=self._context.runtime_scope_valid,
                order_state_known=outcomes_complete,
            )
            await self._observations.append(observation)
            return RecordedPaperCycle(observation, cycle, True)


__all__ = [
    "PaperCycleAlreadyInProgress",
    "PaperCycleMutex",
    "PaperPromotionApplication",
    "PaperPromotionContext",
    "PaperPromotionStore",
    "RecordedPaperCycle",
]
