"""Append-only accepted and rejected strategy research evidence."""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trading_bot.clock import require_utc
from trading_bot.domain import CodeHash, ConfigHash, StrategyEligibilityAttestation
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data import content_hash
from trading_bot.persistence.base import PersistenceDataError
from trading_bot.persistence.models import ResearchAcceptanceEvidenceRow
from trading_bot.research.validation import ResearchAssessment


@dataclass(frozen=True, slots=True)
class PersistedStrategyEligibility:
    attestation: StrategyEligibilityAttestation
    evidence_hash: str

    def __post_init__(self) -> None:
        if type(self.attestation) is not StrategyEligibilityAttestation:
            raise PersistenceDataError(
                "persisted strategy eligibility must contain an exact attestation"
            )
        _require_sha256_hex(self.evidence_hash, "evidence_hash")
        if not self.attestation.eligible:
            raise PersistenceDataError("persisted strategy eligibility must be accepted")
        expected_hash = content_hash(
            {
                "assessment": ResearchAssessment(True, True, ()),
                "attestation": self.attestation,
            }
        )
        if self.evidence_hash != expected_hash:
            raise PersistenceDataError("persisted strategy eligibility hash is invalid")


class SqlResearchEvidenceStore:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def append(
        self,
        attestation: StrategyEligibilityAttestation,
        assessment: ResearchAssessment,
    ) -> None:
        if (
            assessment.eligible != assessment.promotable
            or attestation.eligible != assessment.promotable
            or assessment.eligible == bool(assessment.reason_codes)
        ):
            raise PersistenceDataError(
                "research assessment and attestation are inconsistent"
            )
        evidence_hash = content_hash({"assessment": assessment, "attestation": attestation})
        async with self._factory.begin() as session:
            session.add(
                ResearchAcceptanceEvidenceRow(
                    id=str(uuid.uuid4()),
                    strategy_version=attestation.strategy_version,
                    eligible=attestation.eligible,
                    config_hash=attestation.config_hash,
                    code_hash=attestation.code_hash,
                    research_manifest_hash=attestation.research_manifest_hash,
                    report_hash=attestation.report_hash,
                    evidence_hash=evidence_hash,
                    reason_codes_json=json.dumps(assessment.reason_codes, separators=(",", ":")),
                    observed_at=attestation.observed_at,
                )
            )

    async def get_eligible(
        self,
        evidence_hash: str,
        *,
        strategy_version: str,
        config_hash: ConfigHash,
        code_hash: CodeHash,
        as_of: datetime,
    ) -> PersistedStrategyEligibility | None:
        """Load one pinned, integrity-checked acceptance for an exact strategy build."""

        as_of = require_utc(as_of)
        async with self._factory() as session:
            row = await session.scalar(
                select(ResearchAcceptanceEvidenceRow).where(
                    ResearchAcceptanceEvidenceRow.evidence_hash == evidence_hash
                )
            )
        if row is None or not row.eligible:
            return None
        if row.reason_codes_json != "[]":
            raise PersistenceDataError(
                "eligible research evidence reasons are not canonical and empty"
            )
        attestation = StrategyEligibilityAttestation(
            eligible=True,
            strategy_version=row.strategy_version,
            config_hash=ConfigHash(row.config_hash),
            code_hash=CodeHash(row.code_hash),
            research_manifest_hash=row.research_manifest_hash,
            report_hash=row.report_hash,
            observed_at=row.observed_at,
        )
        if (
            attestation.strategy_version != strategy_version
            or attestation.config_hash != config_hash
            or attestation.code_hash != code_hash
        ):
            raise PersistenceDataError(
                "pinned research evidence does not match the requested strategy build"
            )
        if attestation.observed_at > as_of:
            raise PersistenceDataError("pinned research evidence is future-dated")
        assessment = ResearchAssessment(True, True, ())
        expected_evidence_hash = content_hash(
            {"assessment": assessment, "attestation": attestation}
        )
        if expected_evidence_hash != row.evidence_hash:
            raise PersistenceDataError("stored eligible research evidence hash is invalid")
        return PersistedStrategyEligibility(attestation, row.evidence_hash)


__all__ = ["PersistedStrategyEligibility", "SqlResearchEvidenceStore"]
