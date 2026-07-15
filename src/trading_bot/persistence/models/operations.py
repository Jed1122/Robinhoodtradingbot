"""Operational, authorization, lease, reconciliation, and audit ledger rows."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from trading_bot.persistence.base import (
    ID_LENGTH,
    NAME_LENGTH,
    STATE_LENGTH,
    Base,
    canonical_decimal_column,
    exact_boolean_column,
    exact_nonnegative_integer_column,
    sha256_column,
    utc_datetime_column,
)


class AlertRow(Base):
    """Redacted operational alert state and evidence."""

    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    account_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    deduplication_key: Mapped[str] = sha256_column("deduplication_key")
    severity: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    code: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    raised_at: Mapped[datetime] = utc_datetime_column("raised_at")
    cleared_at: Mapped[datetime | None] = utc_datetime_column("cleared_at", nullable=True)
    evidence_hash: Mapped[str] = sha256_column("evidence_hash")
    correlation_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    config_hash: Mapped[str] = sha256_column("config_hash")


class ReconciliationEventRow(Base):
    """Append-only-compatible reconciliation result and every sanitized difference."""

    __tablename__ = "reconciliation_events"
    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    reconciliation_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    account_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    clean: Mapped[bool] = exact_boolean_column("clean")
    drift_count: Mapped[int] = exact_nonnegative_integer_column("drift_count")
    differences_json: Mapped[str] = mapped_column(Text(), nullable=False)
    observed_at: Mapped[datetime] = utc_datetime_column("observed_at")
    evidence_hash: Mapped[str] = sha256_column("evidence_hash")
    config_hash: Mapped[str] = sha256_column("config_hash")
    code_hash: Mapped[str] = sha256_column("code_hash")
    corrects_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("reconciliation_events.id", ondelete="RESTRICT"),
        nullable=True,
    )


class ConfigurationVersionRow(Base):
    """Content-addressed, nonsecret configuration evidence."""

    __tablename__ = "configuration_versions"
    __table_args__ = (UniqueConstraint("config_hash"),)

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    config_hash: Mapped[str] = sha256_column("config_hash")
    code_hash: Mapped[str] = sha256_column("code_hash")
    created_at: Mapped[datetime] = utc_datetime_column("created_at")
    source: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    canonical_nonsecret_config_json: Mapped[str] = mapped_column(Text(), nullable=False)
    corrects_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("configuration_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )


class LiveAuthorizationRow(Base):
    """Nonsecret metadata for one bounded, one-time live activation authorization."""

    __tablename__ = "live_authorizations"
    __table_args__ = (
        UniqueConstraint("activation_nonce"),
        UniqueConstraint("id", "activation_nonce", "artifact_hash"),
        UniqueConstraint(
            "id",
            "account_id",
            "stage",
            "authorized_risk_equity",
            "config_hash",
            "code_hash",
            "strategy_eligibility_hash",
            "promotion_evidence_hash",
        ),
        CheckConstraint("promotion_eligible = 1", name="promotion_must_be_eligible"),
        CheckConstraint(
            "stage IN ('micro_live', 'normal_live')",
            name="stage_live_only",
        ),
        ForeignKeyConstraint(
            ["promotion_evidence_hash", "stage", "promotion_eligible"],
            [
                "promotion_evidence.evidence_hash",
                "promotion_evidence.stage",
                "promotion_evidence.eligible",
            ],
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    stage: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    activation_nonce: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    artifact_hash: Mapped[str] = sha256_column("artifact_hash")
    preflight_hash: Mapped[str] = sha256_column("preflight_hash")
    acknowledgement_hash: Mapped[str] = sha256_column("acknowledgement_hash")
    config_hash: Mapped[str] = sha256_column("config_hash")
    code_hash: Mapped[str] = sha256_column("code_hash")
    strategy_eligibility_hash: Mapped[str] = sha256_column("strategy_eligibility_hash")
    promotion_evidence_hash: Mapped[str] = sha256_column("promotion_evidence_hash")
    promotion_eligible: Mapped[bool] = exact_boolean_column("promotion_eligible")
    authorized_risk_equity: Mapped[Decimal] = canonical_decimal_column("authorized_risk_equity")
    issued_at: Mapped[datetime] = utc_datetime_column("issued_at")
    expires_at: Mapped[datetime] = utc_datetime_column("expires_at")
    consumed_at: Mapped[datetime | None] = utc_datetime_column("consumed_at", nullable=True)
    status: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    evidence_hash: Mapped[str] = sha256_column("evidence_hash")
    corrects_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("live_authorizations.id", ondelete="RESTRICT"),
        nullable=True,
    )


class LiveLeaseRow(Base):
    """Bounded authorization lease; execution leadership is stored separately."""

    __tablename__ = "live_leases"
    __table_args__ = (
        UniqueConstraint("authorization_id"),
        UniqueConstraint("id", "evidence_hash", "account_id", "stage"),
        CheckConstraint(
            "stage IN ('micro_live', 'normal_live')",
            name="stage_live_only",
        ),
        ForeignKeyConstraint(
            ["promotion_evidence_hash"],
            ["promotion_evidence.evidence_hash"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "authorization_id",
                "account_id",
                "stage",
                "authorized_risk_equity",
                "config_hash",
                "code_hash",
                "strategy_eligibility_hash",
                "promotion_evidence_hash",
            ],
            [
                "live_authorizations.id",
                "live_authorizations.account_id",
                "live_authorizations.stage",
                "live_authorizations.authorized_risk_equity",
                "live_authorizations.config_hash",
                "live_authorizations.code_hash",
                "live_authorizations.strategy_eligibility_hash",
                "live_authorizations.promotion_evidence_hash",
            ],
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    authorization_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    account_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    stage: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    issued_at: Mapped[datetime] = utc_datetime_column("issued_at")
    expires_at: Mapped[datetime] = utc_datetime_column("expires_at")
    revoked_at: Mapped[datetime | None] = utc_datetime_column("revoked_at", nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    authorized_risk_equity: Mapped[Decimal] = canonical_decimal_column("authorized_risk_equity")
    config_hash: Mapped[str] = sha256_column("config_hash")
    code_hash: Mapped[str] = sha256_column("code_hash")
    strategy_eligibility_hash: Mapped[str] = sha256_column("strategy_eligibility_hash")
    promotion_evidence_hash: Mapped[str] = sha256_column("promotion_evidence_hash")
    evidence_hash: Mapped[str] = sha256_column("evidence_hash")


class UsedNonceRow(Base):
    """Durable replay-prevention record for consumed activation nonces."""

    __tablename__ = "used_nonces"
    __table_args__ = (
        ForeignKeyConstraint(
            ["authorization_id", "nonce", "artifact_hash"],
            [
                "live_authorizations.id",
                "live_authorizations.activation_nonce",
                "live_authorizations.artifact_hash",
            ],
            ondelete="RESTRICT",
        ),
    )

    nonce: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    authorization_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    artifact_hash: Mapped[str] = sha256_column("artifact_hash")
    used_at: Mapped[datetime] = utc_datetime_column("used_at")


class KillSwitchEventRow(Base):
    """Append-only-compatible activation or clearing event."""

    __tablename__ = "kill_switch_events"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    action: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    occurred_at: Mapped[datetime] = utc_datetime_column("occurred_at")
    actor: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    acknowledgement_hash: Mapped[str | None] = sha256_column(
        "acknowledgement_hash",
        nullable=True,
    )
    evidence_hash: Mapped[str] = sha256_column("evidence_hash")
    correlation_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    config_hash: Mapped[str] = sha256_column("config_hash")
    code_hash: Mapped[str] = sha256_column("code_hash")
    corrects_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("kill_switch_events.id", ondelete="RESTRICT"),
        nullable=True,
    )


class HeartbeatRow(Base):
    """Process-instance heartbeat used for clean versus unexpected shutdown evidence."""

    __tablename__ = "heartbeats"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    process_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    account_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    execution_mode: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    runtime_state: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    healthy: Mapped[bool] = exact_boolean_column("healthy")
    observed_at: Mapped[datetime] = utc_datetime_column("observed_at")
    clean_shutdown: Mapped[bool] = exact_boolean_column("clean_shutdown")
    config_hash: Mapped[str] = sha256_column("config_hash")
    code_hash: Mapped[str] = sha256_column("code_hash")
    evidence_hash: Mapped[str] = sha256_column("evidence_hash")


class ExecutionLeaseRow(Base):
    """Mutable account-scoped single-leader lease with monotonically fenced ownership."""

    __tablename__ = "execution_leases"
    __table_args__ = (UniqueConstraint("account_id"),)

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    owner_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    fencing_token: Mapped[int] = exact_nonnegative_integer_column("fencing_token")
    acquired_at: Mapped[datetime] = utc_datetime_column("acquired_at")
    heartbeat_at: Mapped[datetime] = utc_datetime_column("heartbeat_at")
    expires_at: Mapped[datetime] = utc_datetime_column("expires_at")
    evidence_hash: Mapped[str] = sha256_column("evidence_hash")


class AuditEventRow(Base):
    """Canonical durable audit event without provider payloads or secret material."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    occurred_at: Mapped[datetime] = utc_datetime_column("occurred_at")
    category: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    actor: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    config_hash: Mapped[str] = sha256_column("config_hash")
    code_hash: Mapped[str] = sha256_column("code_hash")
    data_hash: Mapped[str | None] = sha256_column("data_hash", nullable=True)
    sanitized_details_json: Mapped[str] = mapped_column(Text(), nullable=False)
    corrects_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("audit_events.id", ondelete="RESTRICT"),
        nullable=True,
    )


__all__ = [
    "AlertRow",
    "AuditEventRow",
    "ConfigurationVersionRow",
    "ExecutionLeaseRow",
    "HeartbeatRow",
    "KillSwitchEventRow",
    "LiveAuthorizationRow",
    "LiveLeaseRow",
    "ReconciliationEventRow",
    "UsedNonceRow",
]
