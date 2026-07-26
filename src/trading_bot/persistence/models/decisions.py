"""Strategy, risk, research, and promotion evidence ledger rows."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from trading_bot.persistence.base import (
    ID_LENGTH,
    NAME_LENGTH,
    Base,
    canonical_decimal_column,
    exact_boolean_column,
    exact_nonnegative_integer_column,
    sha256_column,
    utc_datetime_column,
)


class StrategyDecisionRow(Base):
    """Immutable inputs, outputs, identities, and effects of a strategy decision."""

    __tablename__ = "strategy_decisions"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    account_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    instrument_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("instruments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    signal_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("signals.id", ondelete="RESTRICT"),
        nullable=True,
    )
    strategy_version: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    decision: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    decided_at: Mapped[datetime] = utc_datetime_column("decided_at")
    inputs_json: Mapped[str] = mapped_column(Text(), nullable=False)
    output_json: Mapped[str] = mapped_column(Text(), nullable=False)
    risk_result: Mapped[str | None] = mapped_column(String(NAME_LENGTH), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    broker_action: Mapped[str | None] = mapped_column(String(NAME_LENGTH), nullable=True)
    final_position_effect: Mapped[Decimal | None] = canonical_decimal_column(
        "final_position_effect",
        nullable=True,
    )
    config_hash: Mapped[str] = sha256_column("config_hash")
    code_hash: Mapped[str] = sha256_column("code_hash")
    data_hash: Mapped[str] = sha256_column("data_hash")


class RiskEvaluationRow(Base):
    """Append-only-compatible preliminary or final risk evaluation evidence."""

    __tablename__ = "risk_evaluations"
    __table_args__ = (CheckConstraint("check_count > 0", name="check_count_positive"),)

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    intent_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("order_intents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    phase: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    allowed: Mapped[bool] = exact_boolean_column("allowed")
    check_count: Mapped[int] = exact_nonnegative_integer_column("check_count")
    checks_json: Mapped[str] = mapped_column(Text(), nullable=False)
    evaluated_at: Mapped[datetime] = utc_datetime_column("evaluated_at")
    config_hash: Mapped[str] = sha256_column("config_hash")
    corrects_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("risk_evaluations.id", ondelete="RESTRICT"),
        nullable=True,
    )


class ResearchAcceptanceEvidenceRow(Base):
    """Accepted or rejected research eligibility evidence for an exact strategy build."""

    __tablename__ = "research_acceptance_evidence"
    __table_args__ = (UniqueConstraint("evidence_hash"),)

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    strategy_version: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    eligible: Mapped[bool] = exact_boolean_column("eligible")
    config_hash: Mapped[str] = sha256_column("config_hash")
    code_hash: Mapped[str] = sha256_column("code_hash")
    research_manifest_hash: Mapped[str] = sha256_column("research_manifest_hash")
    report_hash: Mapped[str] = sha256_column("report_hash")
    evidence_hash: Mapped[str] = sha256_column("evidence_hash")
    reason_codes_json: Mapped[str] = mapped_column(Text(), nullable=False)
    observed_at: Mapped[datetime] = utc_datetime_column("observed_at")


class PromotionEvidenceRow(Base):
    """Non-activating stage eligibility evidence, including ineligible observations."""

    __tablename__ = "promotion_evidence"
    __table_args__ = (
        UniqueConstraint("evidence_hash"),
        UniqueConstraint("evidence_hash", "stage", "eligible"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    stage: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    eligible: Mapped[bool] = exact_boolean_column("eligible")
    evidence_hash: Mapped[str] = sha256_column("evidence_hash")
    reason_codes_json: Mapped[str] = mapped_column(Text(), nullable=False)
    evaluated_at: Mapped[datetime] = utc_datetime_column("evaluated_at")
    expires_at: Mapped[datetime] = utc_datetime_column("expires_at")


class PromotionObservationRow(Base):
    """Append-only identity-bound paper, shadow, and staged-live cycle evidence."""

    __tablename__ = "promotion_observations"
    __table_args__ = (
        CheckConstraint(
            "stage IN ('paper', 'shadow', 'micro_live', 'normal_live')",
            name="stage_known",
        ),
        CheckConstraint("completed_at >= started_at", name="completion_ordered"),
        UniqueConstraint("stage", "cycle_id"),
        UniqueConstraint("evidence_hash"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    stage: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    cycle_id: Mapped[str] = sha256_column("cycle_id")
    account_fingerprint: Mapped[str] = sha256_column("account_fingerprint")
    provider_evidence_hash: Mapped[str] = sha256_column("provider_evidence_hash")
    strategy_version: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    strategy_eligibility_hash: Mapped[str] = sha256_column("strategy_eligibility_hash")
    config_hash: Mapped[str] = sha256_column("config_hash")
    code_hash: Mapped[str] = sha256_column("code_hash")
    data_hash: Mapped[str] = sha256_column("data_hash")
    started_at: Mapped[datetime] = utc_datetime_column("started_at")
    completed_at: Mapped[datetime] = utc_datetime_column("completed_at")
    identity_verified: Mapped[bool] = exact_boolean_column("identity_verified")
    provider_evidence_verified: Mapped[bool] = exact_boolean_column("provider_evidence_verified")
    strategy_eligible: Mapped[bool] = exact_boolean_column("strategy_eligible")
    authenticated_reads: Mapped[bool] = exact_boolean_column("authenticated_reads")
    data_validated: Mapped[bool] = exact_boolean_column("data_validated")
    outcomes_complete: Mapped[bool] = exact_boolean_column("outcomes_complete")
    reconciliation_clean: Mapped[bool] = exact_boolean_column("reconciliation_clean")
    fixture_data: Mapped[bool] = exact_boolean_column("fixture_data")
    runtime_scope_valid: Mapped[bool] = exact_boolean_column("runtime_scope_valid")
    order_state_known: Mapped[bool] = exact_boolean_column("order_state_known")
    eligible: Mapped[bool] = exact_boolean_column("eligible")
    reason_codes_json: Mapped[str] = mapped_column(Text(), nullable=False)
    evidence_hash: Mapped[str] = sha256_column("evidence_hash")


__all__ = [
    "PromotionEvidenceRow",
    "PromotionObservationRow",
    "ResearchAcceptanceEvidenceRow",
    "RiskEvaluationRow",
    "StrategyDecisionRow",
]
