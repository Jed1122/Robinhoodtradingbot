"""Canonical operator authorization and live-lease records."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal

from trading_bot.clock import DomainValidationError, require_utc
from trading_bot.domain import AccountId, CodeHash, ConfigHash, ExecutionMode
from trading_bot.domain.decimal_utils import canonical_decimal_text, require_bounded_decimal

ACKNOWLEDGEMENT = "I ACCEPT THAT THIS SYSTEM CAN LOSE THE ENTIRE TRADING BALANCE"


def _hash(value: str, name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise DomainValidationError(f"{name} must be lowercase SHA-256 hex")


@dataclass(frozen=True, slots=True)
class PreflightReport:
    account_id: AccountId
    stage: ExecutionMode
    equity: Decimal
    config_hash: ConfigHash
    code_hash: CodeHash
    strategy_eligibility_hash: str
    promotion_evidence_hash: str
    risk_self_test_hash: str
    reconciliation_hash: str
    observed_at: datetime
    account_active: bool
    account_restricted: bool
    code_identity_clean: bool
    strategy_eligible: bool
    promotion_eligible: bool
    kill_switch_active: bool
    reconciliation_clean: bool
    risk_self_test_passed: bool
    critical_alert_count: int
    clock_drift_seconds: Decimal

    def __post_init__(self) -> None:
        require_bounded_decimal(self.equity, "equity", positive=True)
        require_bounded_decimal(self.clock_drift_seconds, "clock_drift_seconds", nonnegative=True)
        require_utc(self.observed_at)
        for value, name in (
            (self.config_hash, "config_hash"),
            (self.code_hash, "code_hash"),
            (self.strategy_eligibility_hash, "strategy_eligibility_hash"),
            (self.promotion_evidence_hash, "promotion_evidence_hash"),
            (self.risk_self_test_hash, "risk_self_test_hash"),
            (self.reconciliation_hash, "reconciliation_hash"),
        ):
            _hash(value, name)
        if self.stage not in {ExecutionMode.MICRO_LIVE, ExecutionMode.NORMAL_LIVE}:
            raise DomainValidationError("preflight stage must be live")
        if type(self.critical_alert_count) is not int or self.critical_alert_count < 0:
            raise DomainValidationError("critical_alert_count must be nonnegative")


@dataclass(frozen=True, slots=True)
class ActivationPayload:
    authorization_id: str
    nonce: str
    account_id: AccountId
    stage: ExecutionMode
    authorized_risk_equity: Decimal
    preflight_hash: str
    acknowledgement_hash: str
    config_hash: ConfigHash
    code_hash: CodeHash
    strategy_eligibility_hash: str
    promotion_evidence_hash: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.authorization_id or not self.nonce:
            raise DomainValidationError("authorization id and nonce are required")
        require_bounded_decimal(
            self.authorized_risk_equity, "authorized_risk_equity", positive=True
        )
        require_utc(self.issued_at)
        require_utc(self.expires_at)
        if self.issued_at >= self.expires_at:
            raise DomainValidationError("activation must expire after issuance")
        for name in (
            "preflight_hash",
            "acknowledgement_hash",
            "config_hash",
            "code_hash",
            "strategy_eligibility_hash",
            "promotion_evidence_hash",
        ):
            _hash(getattr(self, name), name)

    def canonical_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["stage"] = self.stage.value
        result["authorized_risk_equity"] = canonical_decimal_text(self.authorized_risk_equity)
        result["issued_at"] = self.issued_at.isoformat().replace("+00:00", "Z")
        result["expires_at"] = self.expires_at.isoformat().replace("+00:00", "Z")
        return result


@dataclass(frozen=True, slots=True)
class SignedActivationArtifact:
    payload: ActivationPayload
    signature_b64: str


@dataclass(frozen=True, slots=True)
class LiveAuthorization:
    payload: ActivationPayload
    artifact_hash: str
    consumed_at: datetime


@dataclass(frozen=True, slots=True)
class LiveLease:
    authorization_id: str
    account_id: AccountId
    stage: ExecutionMode
    authorized_risk_equity: Decimal
    issued_at: datetime
    expires_at: datetime
    config_hash: ConfigHash
    code_hash: CodeHash
    strategy_eligibility_hash: str
    promotion_evidence_hash: str


def canonical_payload(payload: ActivationPayload) -> bytes:
    """Encode every signed field as deterministic nonsecret JSON."""
    return json.dumps(payload.canonical_dict(), sort_keys=True, separators=(",", ":")).encode()
