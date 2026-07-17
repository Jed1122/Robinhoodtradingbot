"""Immutable risk decisions and broker-neutral safety attestations."""

from dataclasses import dataclass
from datetime import datetime

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import (
    DomainValidationError,
    _require_exact_bool,
    _require_exact_enum,
    _require_nonempty,
    _require_nonnegative_int,
    _require_sha256_hex,
    _require_tuple,
)
from trading_bot.domain.enums import ExecutionMode
from trading_bot.domain.events import AuditEvent
from trading_bot.domain.identifiers import (
    AccountId,
    CodeHash,
    ConfigHash,
    OrderIntentId,
)

__all__ = [
    "AlertAttestation",
    "AuditEvent",
    "CheckResult",
    "LiveLeaseAttestation",
    "PromotionAttestation",
    "ReconciliationAttestation",
    "RiskEvaluation",
    "StrategyEligibilityAttestation",
]


@dataclass(frozen=True, slots=True)
class CheckResult:
    code: str
    allowed: bool
    observed: str | None
    configured_limit: str | None
    reason: str
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_nonempty(self.code, "code")
        _require_exact_bool(self.allowed, "allowed")
        if self.observed is not None:
            _require_nonempty(self.observed, "observed")
        if self.configured_limit is not None:
            _require_nonempty(self.configured_limit, "configured_limit")
        _require_nonempty(self.reason, "reason")
        require_utc(self.observed_at)


@dataclass(frozen=True, slots=True)
class RiskEvaluation:
    intent_id: OrderIntentId
    allowed: bool
    checks: tuple[CheckResult, ...]
    evaluated_at: datetime
    config_hash: ConfigHash

    def __post_init__(self) -> None:
        _require_nonempty(self.intent_id, "intent_id")
        _require_exact_bool(self.allowed, "allowed")
        _require_tuple(self.checks, "checks")
        if not self.checks:
            raise DomainValidationError("risk evaluation requires at least one check")
        if any(type(check) is not CheckResult for check in self.checks):
            raise DomainValidationError("checks must contain CheckResult records")
        if self.allowed != all(check.allowed for check in self.checks):
            raise DomainValidationError("evaluation outcome must equal all check outcomes")
        require_utc(self.evaluated_at)
        _require_sha256_hex(self.config_hash, "config_hash")


@dataclass(frozen=True, slots=True)
class ReconciliationAttestation:
    account_id: AccountId
    clean: bool
    observed_at: datetime
    evidence_hash: str

    def __post_init__(self) -> None:
        _require_nonempty(self.account_id, "account_id")
        _require_exact_bool(self.clean, "clean")
        require_utc(self.observed_at)
        _require_sha256_hex(self.evidence_hash, "evidence_hash")


@dataclass(frozen=True, slots=True)
class LiveLeaseAttestation:
    valid: bool
    account_id: AccountId
    config_hash: ConfigHash
    mode: ExecutionMode
    expires_at: datetime
    evidence_hash: str

    def __post_init__(self) -> None:
        _require_exact_bool(self.valid, "valid")
        _require_nonempty(self.account_id, "account_id")
        _require_sha256_hex(self.config_hash, "config_hash")
        _require_exact_enum(self.mode, ExecutionMode, "mode")
        require_utc(self.expires_at)
        _require_sha256_hex(self.evidence_hash, "evidence_hash")


@dataclass(frozen=True, slots=True)
class AlertAttestation:
    critical_count: int
    observed_at: datetime
    evidence_hash: str

    def __post_init__(self) -> None:
        _require_nonnegative_int(self.critical_count, "critical_count")
        require_utc(self.observed_at)
        _require_sha256_hex(self.evidence_hash, "evidence_hash")


@dataclass(frozen=True, slots=True)
class StrategyEligibilityAttestation:
    eligible: bool
    strategy_version: str
    config_hash: ConfigHash
    code_hash: CodeHash
    research_manifest_hash: str
    report_hash: str
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_exact_bool(self.eligible, "eligible")
        _require_nonempty(self.strategy_version, "strategy_version")
        _require_sha256_hex(self.config_hash, "config_hash")
        _require_sha256_hex(self.code_hash, "code_hash")
        _require_sha256_hex(self.research_manifest_hash, "research_manifest_hash")
        _require_sha256_hex(self.report_hash, "report_hash")
        require_utc(self.observed_at)


@dataclass(frozen=True, slots=True)
class PromotionAttestation:
    stage: str
    eligible: bool
    evidence_hash: str
    evaluated_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_nonempty(self.stage, "stage")
        _require_exact_bool(self.eligible, "eligible")
        _require_sha256_hex(self.evidence_hash, "evidence_hash")
        require_utc(self.evaluated_at)
        require_utc(self.expires_at)
        if self.evaluated_at >= self.expires_at:
            raise DomainValidationError("evaluated_at must precede expires_at")
