"""Append-only accepted and rejected strategy research evidence."""

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trading_bot.domain import StrategyEligibilityAttestation
from trading_bot.market_data import content_hash
from trading_bot.persistence.models import ResearchAcceptanceEvidenceRow
from trading_bot.research.validation import ResearchAssessment


class SqlResearchEvidenceStore:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def append(
        self,
        attestation: StrategyEligibilityAttestation,
        assessment: ResearchAssessment,
    ) -> None:
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


__all__ = ["SqlResearchEvidenceStore"]
