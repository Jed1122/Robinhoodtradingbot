"""Order intent, review, submission, broker order, transition, and fill rows."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Computed,
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
    PROVIDER_LENGTH,
    STATE_LENGTH,
    Base,
    canonical_decimal_column,
    exact_nonnegative_integer_column,
    sha256_column,
    utc_datetime_column,
)


class OrderIntentRow(Base):
    """Durable local intent; its identifier is the client-visible UUID-backed key."""

    __tablename__ = "order_intents"
    __table_args__ = (
        UniqueConstraint("id", "account_id", "instrument_id"),
        UniqueConstraint(
            "id",
            "account_id",
            "instrument_id",
            "side",
            "purpose",
            "order_type",
            "time_in_force",
            "quantity",
            "limit_price_identity",
            "stop_price_identity",
        ),
        ForeignKeyConstraint(
            ["instrument_id", "asset_class"],
            ["instruments.id", "instruments.asset_class"],
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    instrument_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    strategy_decision_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("strategy_decisions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    asset_class: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    side: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    purpose: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    order_type: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    time_in_force: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    quantity: Mapped[Decimal] = canonical_decimal_column("quantity")
    limit_price: Mapped[Decimal | None] = canonical_decimal_column(
        "limit_price",
        nullable=True,
    )
    stop_price: Mapped[Decimal | None] = canonical_decimal_column("stop_price", nullable=True)
    limit_price_identity: Mapped[str] = mapped_column(
        Text(),
        Computed(
            "CASE WHEN limit_price IS NULL THEN '0:' ELSE '1:' || limit_price END",
            persisted=True,
        ),
        nullable=False,
    )
    stop_price_identity: Mapped[str] = mapped_column(
        Text(),
        Computed(
            "CASE WHEN stop_price IS NULL THEN '0:' ELSE '1:' || stop_price END",
            persisted=True,
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = utc_datetime_column("created_at")
    expires_at: Mapped[datetime] = utc_datetime_column("expires_at")
    strategy_version: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    config_hash: Mapped[str] = sha256_column("config_hash")
    code_hash: Mapped[str] = sha256_column("code_hash")
    data_hash: Mapped[str] = sha256_column("data_hash")
    exit_policy_version: Mapped[str | None] = mapped_column(String(NAME_LENGTH), nullable=True)


class BrokerReviewRow(Base):
    """Sanitized review evidence bound to the exact normalized intent."""

    __tablename__ = "broker_reviews"
    __table_args__ = (
        UniqueConstraint("id", "intent_id"),
        UniqueConstraint("id", "intent_id", "client_order_id_identity"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    intent_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("order_intents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    reviewed_at: Mapped[datetime] = utc_datetime_column("reviewed_at")
    expires_at: Mapped[datetime] = utc_datetime_column("expires_at")
    estimated_notional: Mapped[Decimal] = canonical_decimal_column("estimated_notional")
    estimated_fees: Mapped[Decimal] = canonical_decimal_column("estimated_fees")
    client_order_id: Mapped[str | None] = mapped_column(String(ID_LENGTH), nullable=True)
    client_order_id_identity: Mapped[str] = mapped_column(
        Text(),
        Computed(
            "CASE WHEN client_order_id IS NULL THEN '0:' ELSE '1:' || client_order_id END",
            persisted=True,
        ),
        nullable=False,
    )
    outbound_payload_sha256: Mapped[str] = sha256_column("outbound_payload_sha256")
    normalized_intent_hash: Mapped[str] = sha256_column("normalized_intent_hash")
    sanitized_response_hash: Mapped[str] = sha256_column("sanitized_response_hash")
    broker_review_id: Mapped[str | None] = mapped_column(String(ID_LENGTH), nullable=True)


class SubmissionAttemptRow(Base):
    """The database-enforced one-attempt crash and idempotency boundary."""

    __tablename__ = "submission_attempts"
    __table_args__ = (
        UniqueConstraint("intent_id"),
        UniqueConstraint("deduplication_key"),
        UniqueConstraint("provider", "provider_client_reference"),
        UniqueConstraint(
            "id",
            "intent_id",
            "review_id",
            "account_id",
            "instrument_id",
            "provider",
            "provider_client_reference_identity",
        ),
        CheckConstraint(
            "(execution_mode IN ('micro_live', 'normal_live') "
            "AND live_lease_id IS NOT NULL AND live_lease_evidence_hash IS NOT NULL) OR "
            "(execution_mode IN ('backtest', 'simulation', 'paper', 'shadow') "
            "AND live_lease_id IS NULL AND live_lease_evidence_hash IS NULL)",
            name="execution_mode_live_lease_provenance",
        ),
        ForeignKeyConstraint(
            ["review_id", "intent_id", "provider_client_reference_identity"],
            [
                "broker_reviews.id",
                "broker_reviews.intent_id",
                "broker_reviews.client_order_id_identity",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["intent_id", "account_id", "instrument_id"],
            ["order_intents.id", "order_intents.account_id", "order_intents.instrument_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["account_id", "provider"],
            ["accounts.id", "accounts.provider"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["instrument_id", "provider"],
            ["instruments.id", "instruments.provider"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "live_lease_id",
                "live_lease_evidence_hash",
                "account_id",
                "execution_mode",
            ],
            [
                "live_leases.id",
                "live_leases.evidence_hash",
                "live_leases.account_id",
                "live_leases.stage",
            ],
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    intent_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    review_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    account_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    instrument_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    deduplication_key: Mapped[str] = sha256_column("deduplication_key")
    provider: Mapped[str] = mapped_column(String(PROVIDER_LENGTH), nullable=False)
    provider_client_reference: Mapped[str | None] = mapped_column(String(ID_LENGTH), nullable=True)
    provider_client_reference_identity: Mapped[str] = mapped_column(
        Text(),
        Computed(
            "CASE WHEN provider_client_reference IS NULL THEN '0:' "
            "ELSE '1:' || provider_client_reference END",
            persisted=True,
        ),
        nullable=False,
    )
    fencing_token: Mapped[int] = exact_nonnegative_integer_column("fencing_token")
    attempt_started_at: Mapped[datetime] = utc_datetime_column("attempt_started_at")
    execution_mode: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    live_lease_id: Mapped[str | None] = mapped_column(String(ID_LENGTH), nullable=True)
    live_lease_evidence_hash: Mapped[str | None] = sha256_column(
        "live_lease_evidence_hash",
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = utc_datetime_column("completed_at", nullable=True)
    outcome_class: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    sanitized_response_hash: Mapped[str | None] = sha256_column(
        "sanitized_response_hash",
        nullable=True,
    )


class OrderRow(Base):
    """Broker order state, including reconciled external orders without local intent."""

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("provider", "broker_order_id"),
        UniqueConstraint("submission_attempt_id"),
        UniqueConstraint("id", "intent_id"),
        UniqueConstraint(
            "id",
            "provider",
            "broker_order_id",
            "account_id",
            "instrument_id",
            "side",
        ),
        CheckConstraint(
            "(intent_id IS NULL AND review_id IS NULL AND submission_attempt_id IS NULL) OR "
            "(intent_id IS NOT NULL AND review_id IS NOT NULL "
            "AND submission_attempt_id IS NOT NULL)",
            name="local_submission_chain_all_or_none",
        ),
        ForeignKeyConstraint(
            ["review_id", "intent_id", "client_order_id_identity"],
            [
                "broker_reviews.id",
                "broker_reviews.intent_id",
                "broker_reviews.client_order_id_identity",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "submission_attempt_id",
                "intent_id",
                "review_id",
                "account_id",
                "instrument_id",
                "provider",
                "client_order_id_identity",
            ],
            [
                "submission_attempts.id",
                "submission_attempts.intent_id",
                "submission_attempts.review_id",
                "submission_attempts.account_id",
                "submission_attempts.instrument_id",
                "submission_attempts.provider",
                "submission_attempts.provider_client_reference_identity",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "intent_id",
                "account_id",
                "instrument_id",
                "side",
                "purpose",
                "order_type",
                "time_in_force",
                "requested_quantity",
                "limit_price_identity",
                "stop_price_identity",
            ],
            [
                "order_intents.id",
                "order_intents.account_id",
                "order_intents.instrument_id",
                "order_intents.side",
                "order_intents.purpose",
                "order_intents.order_type",
                "order_intents.time_in_force",
                "order_intents.quantity",
                "order_intents.limit_price_identity",
                "order_intents.stop_price_identity",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["account_id", "provider"],
            ["accounts.id", "accounts.provider"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["instrument_id", "provider"],
            ["instruments.id", "instruments.provider"],
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    intent_id: Mapped[str | None] = mapped_column(String(ID_LENGTH), nullable=True)
    review_id: Mapped[str | None] = mapped_column(String(ID_LENGTH), nullable=True)
    submission_attempt_id: Mapped[str | None] = mapped_column(String(ID_LENGTH), nullable=True)
    provider: Mapped[str] = mapped_column(String(PROVIDER_LENGTH), nullable=False)
    broker_order_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    client_order_id: Mapped[str | None] = mapped_column(String(ID_LENGTH), nullable=True)
    client_order_id_identity: Mapped[str] = mapped_column(
        Text(),
        Computed(
            "CASE WHEN client_order_id IS NULL THEN '0:' ELSE '1:' || client_order_id END",
            persisted=True,
        ),
        nullable=False,
    )
    account_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    instrument_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    side: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    purpose: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    order_type: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    time_in_force: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    state: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    requested_quantity: Mapped[Decimal] = canonical_decimal_column("requested_quantity")
    filled_quantity: Mapped[Decimal] = canonical_decimal_column("filled_quantity")
    limit_price: Mapped[Decimal | None] = canonical_decimal_column(
        "limit_price",
        nullable=True,
    )
    stop_price: Mapped[Decimal | None] = canonical_decimal_column("stop_price", nullable=True)
    limit_price_identity: Mapped[str] = mapped_column(
        Text(),
        Computed(
            "CASE WHEN limit_price IS NULL THEN '0:' ELSE '1:' || limit_price END",
            persisted=True,
        ),
        nullable=False,
    )
    stop_price_identity: Mapped[str] = mapped_column(
        Text(),
        Computed(
            "CASE WHEN stop_price IS NULL THEN '0:' ELSE '1:' || stop_price END",
            persisted=True,
        ),
        nullable=False,
    )
    average_fill_price: Mapped[Decimal | None] = canonical_decimal_column(
        "average_fill_price",
        nullable=True,
    )
    created_at: Mapped[datetime] = utc_datetime_column("created_at")
    updated_at: Mapped[datetime] = utc_datetime_column("updated_at")
    data_hash: Mapped[str] = sha256_column("data_hash")


class OrderTransitionRow(Base):
    """Intent-first transition history; broker order linkage is optional until submission."""

    __tablename__ = "order_transitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["order_id", "intent_id"],
            ["orders.id", "orders.intent_id"],
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    intent_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("order_intents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    order_id: Mapped[str | None] = mapped_column(String(ID_LENGTH), nullable=True)
    from_state: Mapped[str | None] = mapped_column(String(STATE_LENGTH), nullable=True)
    event: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    to_state: Mapped[str] = mapped_column(String(STATE_LENGTH), nullable=False)
    actor: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    occurred_at: Mapped[datetime] = utc_datetime_column("occurred_at")
    config_hash: Mapped[str] = sha256_column("config_hash")
    correlation_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    corrects_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("order_transitions.id", ondelete="RESTRICT"),
        nullable=True,
    )


class FillRow(Base):
    """Exact execution with provider-scoped replay and occurrence identity."""

    __tablename__ = "fills"
    __table_args__ = (
        UniqueConstraint("provider", "external_execution_key"),
        UniqueConstraint("id", "account_id", "instrument_id"),
        ForeignKeyConstraint(
            [
                "order_id",
                "provider",
                "broker_order_id",
                "account_id",
                "instrument_id",
                "side",
            ],
            [
                "orders.id",
                "orders.provider",
                "orders.broker_order_id",
                "orders.account_id",
                "orders.instrument_id",
                "orders.side",
            ],
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    provider: Mapped[str] = mapped_column(String(PROVIDER_LENGTH), nullable=False)
    external_execution_key: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    broker_order_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    account_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    instrument_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("instruments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    side: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    quantity: Mapped[Decimal] = canonical_decimal_column("quantity")
    price: Mapped[Decimal] = canonical_decimal_column("price")
    fee: Mapped[Decimal] = canonical_decimal_column("fee")
    occurred_at: Mapped[datetime] = utc_datetime_column("occurred_at")
    occurrence_ordinal: Mapped[int] = exact_nonnegative_integer_column("occurrence_ordinal")
    data_hash: Mapped[str] = sha256_column("data_hash")


__all__ = [
    "BrokerReviewRow",
    "FillRow",
    "OrderIntentRow",
    "OrderRow",
    "OrderTransitionRow",
    "SubmissionAttemptRow",
]
