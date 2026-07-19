import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum


class PromotionStage(StrEnum):
    SIMULATION = "simulation"
    PAPER = "paper"
    SHADOW = "shadow"
    MICRO = "micro"
    NORMAL = "normal"


@dataclass(frozen=True, slots=True)
class PromotionEvidence:
    stage: PromotionStage
    unique_observations: int
    calendar_days: int
    clean_reconciliation: bool
    security_clean: bool
    acknowledgement_current: bool
    complete: bool


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    eligible: bool
    reasons: tuple[str, ...]
    evidence_hash: str
    override_allowed: bool = False


class PromotionEvaluator:
    def evaluate(self, evidence: PromotionEvidence) -> PromotionDecision:
        reasons = []
        required_observations = (
            100 if evidence.stage in {PromotionStage.PAPER, PromotionStage.NORMAL} else 1
        )
        required_days = (
            30
            if evidence.stage is PromotionStage.NORMAL
            else (7 if evidence.stage is PromotionStage.SHADOW else 0)
        )
        if evidence.unique_observations < required_observations:
            reasons.append("insufficient_observations")
        if evidence.calendar_days < required_days:
            reasons.append("insufficient_calendar_days")
        if not evidence.clean_reconciliation:
            reasons.append("dirty_reconciliation")
        if not evidence.security_clean:
            reasons.append("security_findings")
        if not evidence.acknowledgement_current:
            reasons.append("acknowledgement_missing")
        if not evidence.complete:
            reasons.append("incomplete_evidence")
        digest = hashlib.sha256(
            json.dumps(asdict(evidence), default=str, sort_keys=True).encode()
        ).hexdigest()
        return PromotionDecision(not reasons, tuple(reasons), digest)


class EvidenceLedger:
    def __init__(self) -> None:
        self._hashes: set[str] = set()

    def append_unique(self, evidence_hash: str) -> bool:
        before = len(self._hashes)
        self._hashes.add(evidence_hash)
        return len(self._hashes) > before


__all__ = [
    "EvidenceLedger",
    "PromotionDecision",
    "PromotionEvaluator",
    "PromotionEvidence",
    "PromotionStage",
]
