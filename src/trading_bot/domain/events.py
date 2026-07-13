"""Immutable append-only domain event records."""

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
)

__all__ = ["AuditEvent"]


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
            if type(detail) is not tuple or len(detail) != 2:
                raise DomainValidationError("each audit detail must be an immutable key-value pair")
            key, value = detail
            _require_nonempty(key, "audit detail key")
            if type(value) is not str:
                raise DomainValidationError("audit detail values must be strings")
