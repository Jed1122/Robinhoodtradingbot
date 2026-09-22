"""Append-only durable promotion-cycle observation storage."""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trading_bot.clock import require_utc
from trading_bot.domain import PromotionAttestation
from trading_bot.monitoring.promotion import (
    PromotionDecision,
    PromotionIdentity,
    PromotionObservation,
    PromotionStage,
)
from trading_bot.persistence.base import PersistenceDataError
from trading_bot.persistence.models import PromotionEvidenceRow, PromotionObservationRow


class PromotionObservationConflict(PersistenceDataError):
    """Raised when one stage/cycle identity is presented with different evidence."""


def _row_from_observation(observation: PromotionObservation) -> PromotionObservationRow:
    identity = observation.identity
    return PromotionObservationRow(
        id=str(uuid.uuid4()),
        stage=observation.stage.value,
        cycle_id=observation.cycle_id,
        account_fingerprint=identity.account_fingerprint,
        provider_evidence_hash=identity.provider_evidence_hash,
        strategy_version=identity.strategy_version,
        strategy_eligibility_hash=identity.strategy_eligibility_hash,
        config_hash=identity.config_hash,
        code_hash=identity.code_hash,
        data_hash=observation.data_hash,
        started_at=observation.started_at,
        completed_at=observation.completed_at,
        identity_verified=observation.identity_verified,
        provider_evidence_verified=observation.provider_evidence_verified,
        strategy_eligible=observation.strategy_eligible,
        authenticated_reads=observation.authenticated_reads,
        data_validated=observation.data_validated,
        outcomes_complete=observation.outcomes_complete,
        reconciliation_clean=observation.reconciliation_clean,
        fixture_data=observation.fixture_data,
        runtime_scope_valid=observation.runtime_scope_valid,
        order_state_known=observation.order_state_known,
        eligible=observation.eligible,
        reason_codes_json=json.dumps(observation.reason_codes, separators=(",", ":")),
        evidence_hash=observation.evidence_hash,
    )


def _observation_from_row(row: PromotionObservationRow) -> PromotionObservation:
    try:
        raw_reasons: object = json.loads(row.reason_codes_json)
    except (TypeError, ValueError) as exc:
        raise PersistenceDataError("stored promotion reason codes are invalid") from exc
    if type(raw_reasons) is not list or any(type(item) is not str for item in raw_reasons):
        raise PersistenceDataError("stored promotion reason codes are invalid")
    try:
        return PromotionObservation(
            stage=PromotionStage(row.stage),
            cycle_id=row.cycle_id,
            identity=PromotionIdentity(
                account_fingerprint=row.account_fingerprint,
                provider_evidence_hash=row.provider_evidence_hash,
                strategy_version=row.strategy_version,
                strategy_eligibility_hash=row.strategy_eligibility_hash,
                config_hash=row.config_hash,
                code_hash=row.code_hash,
            ),
            started_at=row.started_at,
            completed_at=row.completed_at,
            data_hash=row.data_hash,
            identity_verified=row.identity_verified,
            provider_evidence_verified=row.provider_evidence_verified,
            strategy_eligible=row.strategy_eligible,
            authenticated_reads=row.authenticated_reads,
            data_validated=row.data_validated,
            outcomes_complete=row.outcomes_complete,
            reconciliation_clean=row.reconciliation_clean,
            fixture_data=row.fixture_data,
            runtime_scope_valid=row.runtime_scope_valid,
            order_state_known=row.order_state_known,
            eligible=row.eligible,
            reason_codes=tuple(raw_reasons),
            evidence_hash=row.evidence_hash,
        )
    except (TypeError, ValueError) as exc:
        raise PersistenceDataError("stored promotion observation is invalid") from exc


class SqlPromotionObservationStore:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def append(self, observation: PromotionObservation) -> bool:
        if type(observation) is not PromotionObservation:
            raise TypeError("observation must be a PromotionObservation")
        async with self._factory.begin() as session:
            existing = await session.scalar(
                select(PromotionObservationRow).where(
                    PromotionObservationRow.stage == observation.stage.value,
                    PromotionObservationRow.cycle_id == observation.cycle_id,
                )
            )
            if existing is not None:
                if _observation_from_row(existing).evidence_hash == observation.evidence_hash:
                    return False
                raise PromotionObservationConflict(
                    "promotion stage/cycle already has different durable evidence"
                )
            session.add(_row_from_observation(observation))
            try:
                await session.flush()
            except IntegrityError as exc:
                raise PromotionObservationConflict(
                    "promotion observation conflicts with durable evidence"
                ) from exc
        return True

    async def list_for_identity(
        self,
        identity: PromotionIdentity,
    ) -> tuple[PromotionObservation, ...]:
        if type(identity) is not PromotionIdentity:
            raise TypeError("identity must be a PromotionIdentity")
        async with self._factory() as session:
            rows = (
                await session.scalars(
                    select(PromotionObservationRow)
                    .where(
                        PromotionObservationRow.account_fingerprint
                        == identity.account_fingerprint,
                        PromotionObservationRow.provider_evidence_hash
                        == identity.provider_evidence_hash,
                        PromotionObservationRow.strategy_version == identity.strategy_version,
                        PromotionObservationRow.strategy_eligibility_hash
                        == identity.strategy_eligibility_hash,
                        PromotionObservationRow.config_hash == identity.config_hash,
                        PromotionObservationRow.code_hash == identity.code_hash,
                    )
                    .order_by(
                        PromotionObservationRow.completed_at,
                        PromotionObservationRow.stage,
                        PromotionObservationRow.cycle_id,
                    )
                )
            ).all()
        return tuple(_observation_from_row(row) for row in rows)


class SqlPromotionEvidenceStore:
    """Append immutable evaluator decisions and issue only matching attestations."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    @staticmethod
    def _attestation(row: PromotionEvidenceRow) -> PromotionAttestation:
        try:
            raw_reasons: object = json.loads(row.reason_codes_json)
            if (
                type(raw_reasons) is not list
                or any(type(item) is not str or not item for item in raw_reasons)
                or row.eligible is not (not raw_reasons)
            ):
                raise ValueError
            stage = PromotionStage(row.stage).value
            return PromotionAttestation(
                stage=stage,
                eligible=row.eligible,
                evidence_hash=row.evidence_hash,
                evaluated_at=row.evaluated_at,
                expires_at=row.expires_at,
            )
        except (TypeError, ValueError) as exc:
            raise PersistenceDataError("stored promotion decision is invalid") from exc

    async def persist(
        self,
        decision: PromotionDecision,
        *,
        evaluated_at: datetime,
        expires_at: datetime,
    ) -> PromotionAttestation:
        if type(decision) is not PromotionDecision:
            raise TypeError("decision must be a PromotionDecision")
        evaluated_at = require_utc(evaluated_at)
        expires_at = require_utc(expires_at)
        if evaluated_at >= expires_at:
            raise ValueError("promotion evidence must expire after evaluation")
        reasons_json = json.dumps(decision.reasons, separators=(",", ":"))
        async with self._factory.begin() as session:
            existing = await session.scalar(
                select(PromotionEvidenceRow).where(
                    PromotionEvidenceRow.evidence_hash == decision.evidence_hash
                )
            )
            if existing is not None:
                if (
                    existing.stage != decision.evidence.stage.value
                    or existing.eligible is not decision.eligible
                    or existing.reason_codes_json != reasons_json
                ):
                    raise PromotionObservationConflict(
                        "promotion decision hash conflicts with durable evidence"
                    )
                return self._attestation(existing)
            row = PromotionEvidenceRow(
                id=str(uuid.uuid4()),
                stage=decision.evidence.stage.value,
                eligible=decision.eligible,
                evidence_hash=decision.evidence_hash,
                reason_codes_json=reasons_json,
                evaluated_at=evaluated_at,
                expires_at=expires_at,
            )
            session.add(row)
            try:
                await session.flush()
            except IntegrityError as exc:
                raise PromotionObservationConflict(
                    "promotion decision conflicts with durable evidence"
                ) from exc
            return self._attestation(row)

    async def get(self, evidence_hash: str) -> PromotionAttestation | None:
        async with self._factory() as session:
            row = await session.scalar(
                select(PromotionEvidenceRow).where(
                    PromotionEvidenceRow.evidence_hash == evidence_hash
                )
            )
        return None if row is None else self._attestation(row)


__all__ = [
    "PromotionObservationConflict",
    "SqlPromotionEvidenceStore",
    "SqlPromotionObservationStore",
]
