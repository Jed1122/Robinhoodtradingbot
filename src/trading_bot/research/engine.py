"""Research acceptance engine producing non-activating eligibility attestations."""

from datetime import datetime
from typing import Protocol

from trading_bot.domain import (
    CodeHash,
    ConfigHash,
    StrategyEligibilityAttestation,
)
from trading_bot.research.report import ResearchReport
from trading_bot.research.validation import (
    ResearchAcceptancePolicy,
    ResearchAssessment,
    assess_research,
)


class ResearchEvidenceStore(Protocol):
    async def append(
        self,
        attestation: StrategyEligibilityAttestation,
        assessment: ResearchAssessment,
    ) -> None: ...


async def assess_and_persist(
    report: ResearchReport,
    policy: ResearchAcceptancePolicy,
    *,
    observed_at: datetime,
    store: ResearchEvidenceStore,
) -> StrategyEligibilityAttestation:
    assessment = assess_research(report, policy)
    attestation = StrategyEligibilityAttestation(
        # A statistically eligible report is still non-promotable when its exact
        # code identity is not clean.  Downstream runtimes consume this stricter bit.
        eligible=assessment.promotable,
        strategy_version=report.run.strategy_version,
        config_hash=ConfigHash(report.run.config_hash),
        code_hash=CodeHash(report.run.code_hash),
        research_manifest_hash=report.run.data_manifest_hash,
        report_hash=report.report_hash,
        observed_at=observed_at,
    )
    await store.append(attestation, assessment)
    return attestation


__all__ = ["ResearchEvidenceStore", "assess_and_persist"]
