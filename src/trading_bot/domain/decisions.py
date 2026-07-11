"""Immutable risk and audit decision records."""

from dataclasses import dataclass
from datetime import datetime

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import (
    DomainValidationError,
    _require_nonempty,
    _require_sha256_hex,
    _require_tuple,
)
from trading_bot.domain.identifiers import (
    AuditEventId,
    CodeHash,
    ConfigHash,
    CorrelationId,
    DataHash,
    OrderIntentId,
)


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
        _require_tuple(self.checks, "checks")
        if any(not isinstance(check, CheckResult) for check in self.checks):
            raise DomainValidationError("checks must contain CheckResult records")
        if self.allowed != all(check.allowed for check in self.checks):
            raise DomainValidationError("evaluation outcome must equal all check outcomes")
        require_utc(self.evaluated_at)
        _require_sha256_hex(self.config_hash, "config_hash")


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: AuditEventId
    occurred_at: datetime
    category: str
    actor: str
    reason_code: str
    correlation_id: CorrelationId
    config_hash: ConfigHash
    code_hash: CodeHash
    data_hash: DataHash | None
    details: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        _require_nonempty(self.id, "id")
        require_utc(self.occurred_at)
        _require_nonempty(self.category, "category")
        _require_nonempty(self.actor, "actor")
        _require_nonempty(self.reason_code, "reason_code")
        _require_nonempty(self.correlation_id, "correlation_id")
        _require_sha256_hex(self.config_hash, "config_hash")
        _require_sha256_hex(self.code_hash, "code_hash")
        if self.data_hash is not None:
            _require_sha256_hex(self.data_hash, "data_hash")
        _require_tuple(self.details, "details")
        for detail in self.details:
            if not isinstance(detail, tuple) or len(detail) != 2:
                raise DomainValidationError("each audit detail must be an immutable key-value pair")
            key, value = detail
            _require_nonempty(key, "audit detail key")
            if not isinstance(value, str):
                raise DomainValidationError("audit detail values must be strings")
