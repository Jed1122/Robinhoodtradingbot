"""Fail-closed one-shot composition boundary for durable paper promotion evidence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from trading_bot.app import DecisionCycleRequest
from trading_bot.clock import SystemClock
from trading_bot.config import LoadedConfig
from trading_bot.domain import ConfigHash, ExecutionMode
from trading_bot.monitoring.promotion import PromotionEvaluator, PromotionStage
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.persistence.migrations import migrate_sqlite_ledger
from trading_bot.persistence.promotion import (
    SqlPromotionEvidenceStore,
    SqlPromotionObservationStore,
)
from trading_bot.runtime.paper import PaperApplication
from trading_bot.runtime.paper_promotion import (
    PaperCycleMutex,
    PaperPromotionApplication,
    PaperPromotionContext,
)

_MISSING_COMPOSITION_BLOCKERS = (
    "accepted_research_evidence_unavailable",
    "account_identity_unavailable",
    "provider_evidence_unavailable",
    "strategy_cycle_composition_unavailable",
    "validated_market_data_unavailable",
    "clean_reconciliation_unavailable",
    "runtime_scope_attestation_unavailable",
)


class PaperPromotionNotReady(RuntimeError):
    """Raised when a paper command lacks trusted promotion composition inputs."""

    def __init__(self, blockers: tuple[str, ...]) -> None:
        self.blockers = blockers
        super().__init__("paper promotion composition is not ready")


@dataclass(frozen=True, slots=True)
class PaperPromotionComposition:
    """Trusted inputs required before the runtime can simulate and append evidence.

    This object is intentionally constructed only by a future reviewed composition. CLI
    arguments cannot provide identities, validated market data, or reconciliation claims.
    """

    paper: PaperApplication
    context: PaperPromotionContext
    request: DecisionCycleRequest


def _validate_configuration(loaded: LoadedConfig) -> None:
    config = loaded.config
    if (
        config.mode is not ExecutionMode.PAPER
        or config.live_trading_enabled
        or not config.runtime.start_paused
    ):
        raise PaperPromotionNotReady(("unsafe_paper_configuration",))


def run_paper_promotion_once(
    *,
    loaded: LoadedConfig,
    repository_root: str | Path,
    ledger: str | Path,
    lock_directory: str | Path,
    composition: PaperPromotionComposition | None = None,
) -> dict[str, object]:
    """Run exactly one trusted paper cycle, or fail before touching durable state.

    The current public CLI deliberately has no source for ``composition``. This boundary
    therefore reports every absent trusted input without creating a ledger, lock, order,
    or promotion observation. A later reviewed composition must supply the same exact
    research, account, provider, strategy, configuration, and code identities.
    """

    _validate_configuration(loaded)
    if composition is None:
        raise PaperPromotionNotReady(_MISSING_COMPOSITION_BLOCKERS)

    identity = composition.context.identity
    if identity.config_hash != ConfigHash(str(loaded.config_hash)):
        raise PaperPromotionNotReady(("configuration_identity_mismatch",))

    root = Path(repository_root).resolve(strict=True)
    database_url = migrate_sqlite_ledger(
        ledger,
        alembic_ini=root / "alembic.ini",
        migrations_dir=root / "migrations",
    )
    engine = create_engine(database_url)
    clock = SystemClock()

    async def run() -> dict[str, object]:
        try:
            factory = async_session_factory(engine)
            observations = SqlPromotionObservationStore(factory)
            application = PaperPromotionApplication(
                paper=composition.paper,
                context=composition.context,
                observations=observations,
                mutex=PaperCycleMutex(lock_directory),
                clock=clock,
            )
            recorded = await application.run_cycle(composition.request)
            async with application.promotion_observations() as durable:
                evaluated_at = clock.now()
                decision = PromotionEvaluator(loaded.config.promotion).evaluate(
                    stage=PromotionStage.PAPER,
                    identity=identity,
                    observations=durable,
                    now=evaluated_at,
                )
                attestation = await SqlPromotionEvidenceStore(factory).persist(
                    decision,
                    evaluated_at=evaluated_at,
                    expires_at=(
                        evaluated_at
                        + timedelta(seconds=int(loaded.config.freshness.max_preflight_age_seconds))
                    ),
                )
            return {
                "evidence_hash": recorded.observation.evidence_hash,
                "evidence_eligible": recorded.observation.eligible,
                "executed": recorded.executed,
                "ineligible_reasons": recorded.observation.reason_codes,
                "live_enabled": False,
                "promotion_evidence_hash": attestation.evidence_hash,
                "promotion_eligible": attestation.eligible,
                "status": "paper_recorded",
            }
        finally:
            await engine.dispose()

    return asyncio.run(run())


__all__ = [
    "PaperPromotionComposition",
    "PaperPromotionNotReady",
    "run_paper_promotion_once",
]
