"""Create the complete normalized durable trading ledger.

Revision ID: 0001_core_ledger
Revises:
Create Date: 2026-07-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_core_ledger"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ID_LENGTH = 255
HASH_LENGTH = 64
DECIMAL_TEXT_MAX_LENGTH = 512
NAME_LENGTH = 128
PROVIDER_LENGTH = 64
STATE_LENGTH = 64

CORRECTION_TABLES = (
    "audit_events",
    "kill_switch_events",
    "live_authorizations",
    "configuration_versions",
    "reconciliation_events",
    "order_transitions",
    "risk_evaluations",
)


def _identifier(name: str, *, nullable: bool = False) -> sa.Column[str]:
    return sa.Column(name, sa.String(length=ID_LENGTH), nullable=nullable)


def _hash(name: str, *, nullable: bool = False) -> sa.Column[str]:
    expression = (
        f"typeof({name}) = 'text' AND length({name}) = {HASH_LENGTH} "
        f"AND length(CAST({name} AS BLOB)) = {HASH_LENGTH} "
        f"AND {name} NOT GLOB '*[^0-9a-f]*'"
    )
    return sa.Column(
        name,
        sa.String(length=HASH_LENGTH),
        sa.CheckConstraint(
            _nullable_check(name, expression, nullable=nullable),
            name=f"{name}_sha256",
        ),
        nullable=nullable,
    )


def _name(name: str, *, nullable: bool = False) -> sa.Column[str]:
    return sa.Column(name, sa.String(length=NAME_LENGTH), nullable=nullable)


def _provider(name: str = "provider", *, nullable: bool = False) -> sa.Column[str]:
    return sa.Column(name, sa.String(length=PROVIDER_LENGTH), nullable=nullable)


def _state(name: str, *, nullable: bool = False) -> sa.Column[str]:
    return sa.Column(name, sa.String(length=STATE_LENGTH), nullable=nullable)


def _canonical_decimal_check_expression(name: str) -> str:
    unsigned = f"ltrim({name}, '-')"
    dot = f"instr({unsigned}, '.')"
    integer_part = f"substr({unsigned}, 1, {dot} - 1)"
    fractional_part = f"substr({unsigned}, {dot} + 1)"
    return (
        f"typeof({name}) = 'text' AND length({name}) > 0 "
        f"AND length({name}) <= {DECIMAL_TEXT_MAX_LENGTH} "
        f"AND length(CAST({name} AS BLOB)) = length({name}) "
        f"AND {name} NOT GLOB '*[^0-9.-]*' "
        f"AND length({name}) - length(replace({name}, '-', '')) <= 1 "
        f"AND (instr({name}, '-') = 0 OR instr({name}, '-') = 1) "
        f"AND length({name}) - length(replace({name}, '.', '')) <= 1 "
        f"AND ({name} = '0' OR ({unsigned} <> '0' AND ("
        f"({dot} = 0 AND {unsigned} GLOB '[1-9]*' "
        f"AND {unsigned} NOT GLOB '*[^0-9]*') OR ("
        f"{dot} > 1 AND {dot} < length({unsigned}) "
        f"AND ({integer_part} = '0' OR ({integer_part} GLOB '[1-9]*' "
        f"AND {integer_part} NOT GLOB '*[^0-9]*')) "
        f"AND {fractional_part} NOT GLOB '*[^0-9]*' "
        f"AND substr({unsigned}, -1, 1) GLOB '[1-9]'))))"
    )


def _canonical_utc_check_expression(name: str) -> str:
    pattern = (
        "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T"
        "[0-9][0-9]:[0-9][0-9]:[0-9][0-9]."
        "[0-9][0-9][0-9][0-9][0-9][0-9]Z"
    )
    normalized = f"strftime('%Y-%m-%dT%H:%M:%S', {name})"
    return (
        f"typeof({name}) = 'text' AND length({name}) = 27 "
        f"AND length(CAST({name} AS BLOB)) = 27 "
        f"AND {name} GLOB '{pattern}' "
        f"AND substr({name}, 1, 4) <> '0000' "
        f"AND substr({name}, 12, 2) BETWEEN '00' AND '23' "
        f"AND {normalized} IS NOT NULL "
        f"AND {normalized} = substr({name}, 1, 19)"
    )


def _decimal(name: str, *, nullable: bool = False) -> sa.Column[str]:
    return sa.Column(
        name,
        sa.BLOB(),
        sa.CheckConstraint(
            _nullable_check(
                name,
                _canonical_decimal_check_expression(name),
                nullable=nullable,
            ),
            name=f"{name}_canonical_decimal",
        ),
        nullable=nullable,
    )


def _utc(name: str, *, nullable: bool = False) -> sa.Column[str]:
    return sa.Column(
        name,
        sa.Text(),
        sa.CheckConstraint(
            _nullable_check(name, _canonical_utc_check_expression(name), nullable=nullable),
            name=f"{name}_canonical_utc",
        ),
        nullable=nullable,
    )


def _text(name: str, *, nullable: bool = False) -> sa.Column[str]:
    return sa.Column(name, sa.Text(), nullable=nullable)


def _nullable_identity(name: str, source_column: str) -> sa.Column[str]:
    return sa.Column(
        name,
        sa.Text(),
        sa.Computed(
            f"CASE WHEN {source_column} IS NULL THEN '0:' ELSE '1:' || {source_column} END",
            persisted=True,
        ),
        nullable=False,
    )


def _integer(name: str, *, nullable: bool = False) -> sa.Column[int]:
    expression = f"typeof({name}) = 'integer' AND {name} >= 0"
    return sa.Column(
        name,
        sa.BLOB(),
        sa.CheckConstraint(
            _nullable_check(name, expression, nullable=nullable),
            name=f"{name}_nonnegative_integer",
        ),
        nullable=nullable,
    )


def _boolean(name: str, *, nullable: bool = False) -> sa.Column[int]:
    expression = f"typeof({name}) = 'integer' AND {name} IN (0, 1)"
    return sa.Column(
        name,
        sa.BLOB(),
        sa.CheckConstraint(
            _nullable_check(name, expression, nullable=nullable),
            name=f"{name}_exact_boolean",
        ),
        nullable=nullable,
    )


def _nullable_check(name: str, required_expression: str, *, nullable: bool) -> str:
    if nullable:
        return f"{name} IS NULL OR ({required_expression})"
    return required_expression


def _primary_key(table_name: str, column_name: str = "id") -> sa.PrimaryKeyConstraint:
    return sa.PrimaryKeyConstraint(column_name, name=op.f(f"pk_{table_name}"))


def _foreign_key(
    table_name: str,
    column_name: str,
    referred_table: str,
    referred_column: str = "id",
) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column_name],
        [f"{referred_table}.{referred_column}"],
        name=op.f(f"fk_{table_name}_{column_name}_{referred_table}"),
        ondelete="RESTRICT",
    )


def _composite_foreign_key(
    table_name: str,
    column_names: tuple[str, ...],
    referred_table: str,
    referred_columns: tuple[str, ...],
) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        list(column_names),
        [f"{referred_table}.{column_name}" for column_name in referred_columns],
        name=op.f(f"fk_{table_name}_{column_names[0]}_{referred_table}"),
        ondelete="RESTRICT",
    )


def _unique(table_name: str, *column_names: str) -> sa.UniqueConstraint:
    return sa.UniqueConstraint(
        *column_names,
        name=op.f(f"uq_{table_name}_{'_'.join(column_names)}"),
    )


def upgrade() -> None:
    op.create_table(
        "accounts",
        _identifier("id"),
        _provider(),
        _identifier("provider_account_id"),
        _name("account_type"),
        _name("provider_state"),
        _decimal("equity"),
        _decimal("cash"),
        _decimal("equity_buying_power", nullable=True),
        _decimal("crypto_buying_power", nullable=True),
        _decimal("prediction_buying_power", nullable=True),
        _boolean("restricted"),
        _utc("observed_at"),
        _hash("data_hash"),
        _hash("config_hash"),
        _hash("code_hash"),
        _primary_key("accounts"),
        _unique("accounts", "provider", "provider_account_id"),
        _unique("accounts", "id", "provider"),
    )
    op.create_table(
        "instruments",
        _identifier("id"),
        _provider(),
        _identifier("provider_instrument_id"),
        _name("symbol"),
        _name("asset_class"),
        _name("provider_status"),
        _boolean("tradable"),
        _boolean("fractional_eligible"),
        _decimal("price_increment"),
        _decimal("quantity_increment"),
        _decimal("minimum_quantity"),
        _decimal("minimum_notional"),
        _decimal("maximum_quantity", nullable=True),
        _name("correlation_group"),
        _utc("observed_at"),
        _hash("data_hash"),
        _primary_key("instruments"),
        _unique("instruments", "provider", "provider_instrument_id"),
        _unique("instruments", "id", "provider"),
        _unique("instruments", "id", "asset_class"),
    )
    op.create_table(
        "market_snapshots",
        _identifier("id"),
        _identifier("instrument_id"),
        _decimal("bid", nullable=True),
        _decimal("ask", nullable=True),
        _decimal("last", nullable=True),
        _utc("observed_at"),
        _name("source"),
        _name("timestamp_source"),
        _boolean("freshness_verified"),
        _hash("data_hash"),
        _primary_key("market_snapshots"),
        _foreign_key("market_snapshots", "instrument_id", "instruments"),
    )
    op.create_table(
        "bars",
        _identifier("id"),
        _identifier("instrument_id"),
        _name("interval"),
        _utc("starts_at"),
        _utc("ends_at"),
        _decimal("open"),
        _decimal("high"),
        _decimal("low"),
        _decimal("close"),
        _decimal("volume"),
        _name("source"),
        _boolean("interpolated"),
        _hash("data_hash"),
        _primary_key("bars"),
        _foreign_key("bars", "instrument_id", "instruments"),
        _unique("bars", "instrument_id", "interval", "starts_at", "source"),
    )
    op.create_table(
        "data_quality_events",
        _identifier("id"),
        _identifier("instrument_id", nullable=True),
        _utc("occurred_at"),
        _name("code"),
        _name("severity"),
        _text("reason"),
        _text("sanitized_details_json"),
        _hash("data_hash", nullable=True),
        _hash("config_hash"),
        _primary_key("data_quality_events"),
        _foreign_key("data_quality_events", "instrument_id", "instruments"),
    )
    op.create_table(
        "features",
        _identifier("id"),
        _identifier("instrument_id"),
        _name("feature_name"),
        _name("feature_version"),
        _utc("observed_at"),
        _text("values_json"),
        _hash("data_hash"),
        _hash("config_hash"),
        _hash("code_hash"),
        _primary_key("features"),
        _foreign_key("features", "instrument_id", "instruments"),
    )
    op.create_table(
        "signals",
        _identifier("id"),
        _identifier("instrument_id"),
        _name("strategy_version"),
        _name("signal_name"),
        _utc("observed_at"),
        _decimal("value", nullable=True),
        _text("output_json"),
        _hash("data_hash"),
        _hash("config_hash"),
        _hash("code_hash"),
        _primary_key("signals"),
        _foreign_key("signals", "instrument_id", "instruments"),
    )
    op.create_table(
        "strategy_decisions",
        _identifier("id"),
        _identifier("account_id", nullable=True),
        _identifier("instrument_id"),
        _identifier("signal_id", nullable=True),
        _name("strategy_version"),
        _name("decision"),
        _name("reason_code"),
        _utc("decided_at"),
        _text("inputs_json"),
        _text("output_json"),
        _name("risk_result", nullable=True),
        _text("rejection_reason", nullable=True),
        _name("broker_action", nullable=True),
        _decimal("final_position_effect", nullable=True),
        _hash("config_hash"),
        _hash("code_hash"),
        _hash("data_hash"),
        _primary_key("strategy_decisions"),
        _foreign_key("strategy_decisions", "account_id", "accounts"),
        _foreign_key("strategy_decisions", "instrument_id", "instruments"),
        _foreign_key("strategy_decisions", "signal_id", "signals"),
    )
    op.create_table(
        "order_intents",
        _identifier("id"),
        _identifier("account_id"),
        _identifier("instrument_id"),
        _identifier("strategy_decision_id", nullable=True),
        _name("asset_class"),
        _name("side"),
        _name("purpose"),
        _name("order_type"),
        _name("time_in_force"),
        _decimal("quantity"),
        _decimal("limit_price", nullable=True),
        _decimal("stop_price", nullable=True),
        _nullable_identity("limit_price_identity", "limit_price"),
        _nullable_identity("stop_price_identity", "stop_price"),
        _utc("created_at"),
        _utc("expires_at"),
        _name("strategy_version"),
        _hash("config_hash"),
        _hash("code_hash"),
        _hash("data_hash"),
        _name("exit_policy_version", nullable=True),
        _primary_key("order_intents"),
        _foreign_key("order_intents", "account_id", "accounts"),
        _composite_foreign_key(
            "order_intents",
            ("instrument_id", "asset_class"),
            "instruments",
            ("id", "asset_class"),
        ),
        _foreign_key("order_intents", "strategy_decision_id", "strategy_decisions"),
        _unique("order_intents", "id", "account_id", "instrument_id"),
        _unique(
            "order_intents",
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
    )
    op.create_table(
        "risk_evaluations",
        _identifier("id"),
        _identifier("intent_id"),
        _name("phase"),
        _boolean("allowed"),
        _integer("check_count"),
        _text("checks_json"),
        _utc("evaluated_at"),
        _hash("config_hash"),
        _identifier("corrects_id", nullable=True),
        _primary_key("risk_evaluations"),
        _foreign_key("risk_evaluations", "intent_id", "order_intents"),
        _foreign_key("risk_evaluations", "corrects_id", "risk_evaluations"),
        sa.CheckConstraint(
            "check_count > 0",
            name=op.f("ck_risk_evaluations_check_count_positive"),
        ),
    )
    op.create_table(
        "research_acceptance_evidence",
        _identifier("id"),
        _name("strategy_version"),
        _boolean("eligible"),
        _hash("config_hash"),
        _hash("code_hash"),
        _hash("research_manifest_hash"),
        _hash("report_hash"),
        _hash("evidence_hash"),
        _text("reason_codes_json"),
        _utc("observed_at"),
        _primary_key("research_acceptance_evidence"),
    )
    op.create_table(
        "promotion_evidence",
        _identifier("id"),
        _name("stage"),
        _boolean("eligible"),
        _hash("evidence_hash"),
        _text("reason_codes_json"),
        _utc("evaluated_at"),
        _utc("expires_at"),
        _primary_key("promotion_evidence"),
        _unique("promotion_evidence", "evidence_hash"),
        _unique("promotion_evidence", "evidence_hash", "stage", "eligible"),
    )
    op.create_table(
        "broker_reviews",
        _identifier("id"),
        _identifier("intent_id"),
        _name("source"),
        _utc("reviewed_at"),
        _utc("expires_at"),
        _decimal("estimated_notional"),
        _decimal("estimated_fees"),
        _identifier("client_order_id", nullable=True),
        _nullable_identity("client_order_id_identity", "client_order_id"),
        _hash("outbound_payload_sha256"),
        _hash("normalized_intent_hash"),
        _hash("sanitized_response_hash"),
        _identifier("broker_review_id", nullable=True),
        _primary_key("broker_reviews"),
        _foreign_key("broker_reviews", "intent_id", "order_intents"),
        _unique("broker_reviews", "id", "intent_id"),
        _unique("broker_reviews", "id", "intent_id", "client_order_id_identity"),
    )
    op.create_table(
        "submission_attempts",
        _identifier("id"),
        _identifier("intent_id"),
        _identifier("review_id"),
        _identifier("account_id"),
        _identifier("instrument_id"),
        _hash("deduplication_key"),
        _provider(),
        _identifier("provider_client_reference", nullable=True),
        _nullable_identity(
            "provider_client_reference_identity",
            "provider_client_reference",
        ),
        _integer("fencing_token"),
        _utc("attempt_started_at"),
        _state("execution_mode"),
        _identifier("live_lease_id", nullable=True),
        _hash("live_lease_evidence_hash", nullable=True),
        _utc("completed_at", nullable=True),
        _state("outcome_class"),
        _hash("sanitized_response_hash", nullable=True),
        _primary_key("submission_attempts"),
        _composite_foreign_key(
            "submission_attempts",
            ("review_id", "intent_id", "provider_client_reference_identity"),
            "broker_reviews",
            ("id", "intent_id", "client_order_id_identity"),
        ),
        _composite_foreign_key(
            "submission_attempts",
            ("intent_id", "account_id", "instrument_id"),
            "order_intents",
            ("id", "account_id", "instrument_id"),
        ),
        _composite_foreign_key(
            "submission_attempts",
            ("account_id", "provider"),
            "accounts",
            ("id", "provider"),
        ),
        _composite_foreign_key(
            "submission_attempts",
            ("instrument_id", "provider"),
            "instruments",
            ("id", "provider"),
        ),
        _composite_foreign_key(
            "submission_attempts",
            (
                "live_lease_id",
                "live_lease_evidence_hash",
                "account_id",
                "execution_mode",
            ),
            "live_leases",
            ("id", "evidence_hash", "account_id", "stage"),
        ),
        _unique("submission_attempts", "intent_id"),
        _unique("submission_attempts", "deduplication_key"),
        _unique("submission_attempts", "provider", "provider_client_reference"),
        _unique(
            "submission_attempts",
            "id",
            "intent_id",
            "review_id",
            "account_id",
            "instrument_id",
            "provider",
            "provider_client_reference_identity",
        ),
        sa.CheckConstraint(
            "(execution_mode IN ('micro_live', 'normal_live') "
            "AND live_lease_id IS NOT NULL AND live_lease_evidence_hash IS NOT NULL) OR "
            "(execution_mode IN ('backtest', 'simulation', 'paper', 'shadow') "
            "AND live_lease_id IS NULL AND live_lease_evidence_hash IS NULL)",
            name=op.f("ck_submission_attempts_execution_mode_live_lease_provenance"),
        ),
    )
    op.create_table(
        "orders",
        _identifier("id"),
        _identifier("intent_id", nullable=True),
        _identifier("review_id", nullable=True),
        _identifier("submission_attempt_id", nullable=True),
        _provider(),
        _identifier("broker_order_id"),
        _identifier("client_order_id", nullable=True),
        _nullable_identity("client_order_id_identity", "client_order_id"),
        _identifier("account_id"),
        _identifier("instrument_id"),
        _name("side"),
        _name("purpose"),
        _name("order_type"),
        _name("time_in_force"),
        _state("state"),
        _decimal("requested_quantity"),
        _decimal("filled_quantity"),
        _decimal("limit_price", nullable=True),
        _decimal("stop_price", nullable=True),
        _nullable_identity("limit_price_identity", "limit_price"),
        _nullable_identity("stop_price_identity", "stop_price"),
        _decimal("average_fill_price", nullable=True),
        _utc("created_at"),
        _utc("updated_at"),
        _hash("data_hash"),
        _primary_key("orders"),
        _composite_foreign_key(
            "orders",
            ("review_id", "intent_id", "client_order_id_identity"),
            "broker_reviews",
            ("id", "intent_id", "client_order_id_identity"),
        ),
        _composite_foreign_key(
            "orders",
            (
                "submission_attempt_id",
                "intent_id",
                "review_id",
                "account_id",
                "instrument_id",
                "provider",
                "client_order_id_identity",
            ),
            "submission_attempts",
            (
                "id",
                "intent_id",
                "review_id",
                "account_id",
                "instrument_id",
                "provider",
                "provider_client_reference_identity",
            ),
        ),
        _composite_foreign_key(
            "orders",
            (
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
            ),
            "order_intents",
            (
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
        ),
        _composite_foreign_key(
            "orders",
            ("account_id", "provider"),
            "accounts",
            ("id", "provider"),
        ),
        _composite_foreign_key(
            "orders",
            ("instrument_id", "provider"),
            "instruments",
            ("id", "provider"),
        ),
        _unique("orders", "provider", "broker_order_id"),
        _unique("orders", "submission_attempt_id"),
        _unique("orders", "id", "intent_id"),
        _unique(
            "orders",
            "id",
            "provider",
            "broker_order_id",
            "account_id",
            "instrument_id",
            "side",
        ),
        sa.CheckConstraint(
            "(intent_id IS NULL AND review_id IS NULL AND submission_attempt_id IS NULL) OR "
            "(intent_id IS NOT NULL AND review_id IS NOT NULL "
            "AND submission_attempt_id IS NOT NULL)",
            name=op.f("ck_orders_local_submission_chain_all_or_none"),
        ),
    )
    op.create_table(
        "order_transitions",
        _identifier("id"),
        _identifier("intent_id"),
        _identifier("order_id", nullable=True),
        _state("from_state", nullable=True),
        _state("event"),
        _state("to_state"),
        _name("actor"),
        _name("reason_code"),
        _utc("occurred_at"),
        _hash("config_hash"),
        _identifier("correlation_id"),
        _identifier("corrects_id", nullable=True),
        _primary_key("order_transitions"),
        _foreign_key("order_transitions", "intent_id", "order_intents"),
        _composite_foreign_key(
            "order_transitions",
            ("order_id", "intent_id"),
            "orders",
            ("id", "intent_id"),
        ),
        _foreign_key("order_transitions", "corrects_id", "order_transitions"),
    )
    op.create_table(
        "fills",
        _identifier("id"),
        _identifier("order_id"),
        _provider(),
        _identifier("external_execution_key"),
        _identifier("broker_order_id"),
        _identifier("account_id"),
        _identifier("instrument_id"),
        _name("side"),
        _decimal("quantity"),
        _decimal("price"),
        _decimal("fee"),
        _utc("occurred_at"),
        _integer("occurrence_ordinal"),
        _hash("data_hash"),
        _primary_key("fills"),
        _composite_foreign_key(
            "fills",
            (
                "order_id",
                "provider",
                "broker_order_id",
                "account_id",
                "instrument_id",
                "side",
            ),
            "orders",
            ("id", "provider", "broker_order_id", "account_id", "instrument_id", "side"),
        ),
        _foreign_key("fills", "account_id", "accounts"),
        _foreign_key("fills", "instrument_id", "instruments"),
        _unique("fills", "provider", "external_execution_key"),
        _unique("fills", "id", "account_id", "instrument_id"),
    )
    op.create_table(
        "portfolio_snapshots",
        _identifier("id"),
        _identifier("account_id"),
        _decimal("equity"),
        _decimal("cash"),
        _decimal("gross_exposure"),
        _decimal("net_exposure"),
        _decimal("crypto_exposure"),
        _decimal("realized_pnl"),
        _decimal("unrealized_pnl"),
        _utc("observed_at"),
        _hash("data_hash"),
        _primary_key("portfolio_snapshots"),
        _foreign_key("portfolio_snapshots", "account_id", "accounts"),
        _unique("portfolio_snapshots", "id", "account_id"),
    )
    op.create_table(
        "positions",
        _identifier("id"),
        _identifier("account_id"),
        _identifier("instrument_id"),
        _identifier("portfolio_snapshot_id", nullable=True),
        _name("asset_class"),
        _decimal("quantity"),
        _decimal("average_price", nullable=True),
        _decimal("market_value"),
        _decimal("unrealized_pnl"),
        _utc("observed_at"),
        _hash("data_hash"),
        _primary_key("positions"),
        _foreign_key("positions", "account_id", "accounts"),
        _composite_foreign_key(
            "positions",
            ("instrument_id", "asset_class"),
            "instruments",
            ("id", "asset_class"),
        ),
        _composite_foreign_key(
            "positions",
            ("portfolio_snapshot_id", "account_id"),
            "portfolio_snapshots",
            ("id", "account_id"),
        ),
    )
    op.create_table(
        "equity_curve",
        _identifier("id"),
        _identifier("account_id"),
        _utc("observed_at"),
        _decimal("equity"),
        _decimal("cash"),
        _decimal("gross_exposure"),
        _decimal("net_exposure"),
        _hash("data_hash"),
        _primary_key("equity_curve"),
        _foreign_key("equity_curve", "account_id", "accounts"),
    )
    op.create_table(
        "realized_pnl",
        _identifier("id"),
        _identifier("account_id"),
        _identifier("instrument_id", nullable=True),
        _identifier("fill_id", nullable=True),
        _decimal("amount"),
        _utc("realized_at"),
        _hash("data_hash"),
        _primary_key("realized_pnl"),
        _foreign_key("realized_pnl", "account_id", "accounts"),
        _foreign_key("realized_pnl", "instrument_id", "instruments"),
        _composite_foreign_key(
            "realized_pnl",
            ("fill_id", "account_id", "instrument_id"),
            "fills",
            ("id", "account_id", "instrument_id"),
        ),
        sa.CheckConstraint(
            "fill_id IS NULL OR instrument_id IS NOT NULL",
            name=op.f("ck_realized_pnl_fill_requires_instrument"),
        ),
    )
    op.create_table(
        "drawdown_events",
        _identifier("id"),
        _identifier("account_id"),
        _utc("started_at"),
        _utc("observed_at"),
        _decimal("peak_equity"),
        _decimal("current_equity"),
        _decimal("drawdown_fraction"),
        _boolean("active"),
        _hash("config_hash"),
        _hash("data_hash"),
        _primary_key("drawdown_events"),
        _foreign_key("drawdown_events", "account_id", "accounts"),
    )
    op.create_table(
        "alerts",
        _identifier("id"),
        _identifier("account_id", nullable=True),
        _hash("deduplication_key"),
        _name("severity"),
        _state("status"),
        _name("code"),
        _text("reason"),
        _utc("raised_at"),
        _utc("cleared_at", nullable=True),
        _hash("evidence_hash"),
        _identifier("correlation_id"),
        _hash("config_hash"),
        _primary_key("alerts"),
        _foreign_key("alerts", "account_id", "accounts"),
    )
    op.create_table(
        "reconciliation_events",
        _identifier("id"),
        _identifier("reconciliation_id"),
        _identifier("account_id"),
        _boolean("clean"),
        _integer("drift_count"),
        _text("differences_json"),
        _utc("observed_at"),
        _hash("evidence_hash"),
        _hash("config_hash"),
        _hash("code_hash"),
        _identifier("corrects_id", nullable=True),
        _primary_key("reconciliation_events"),
        _foreign_key("reconciliation_events", "account_id", "accounts"),
        _foreign_key("reconciliation_events", "corrects_id", "reconciliation_events"),
    )
    op.create_table(
        "configuration_versions",
        _identifier("id"),
        _hash("config_hash"),
        _hash("code_hash"),
        _utc("created_at"),
        _name("source"),
        _text("canonical_nonsecret_config_json"),
        _identifier("corrects_id", nullable=True),
        _primary_key("configuration_versions"),
        _foreign_key("configuration_versions", "corrects_id", "configuration_versions"),
        _unique("configuration_versions", "config_hash"),
    )
    op.create_table(
        "live_authorizations",
        _identifier("id"),
        _identifier("account_id"),
        _state("stage"),
        _identifier("activation_nonce"),
        _hash("artifact_hash"),
        _hash("preflight_hash"),
        _hash("acknowledgement_hash"),
        _hash("config_hash"),
        _hash("code_hash"),
        _hash("strategy_eligibility_hash"),
        _hash("promotion_evidence_hash"),
        _boolean("promotion_eligible"),
        _decimal("authorized_risk_equity"),
        _utc("issued_at"),
        _utc("expires_at"),
        _utc("consumed_at", nullable=True),
        _state("status"),
        _hash("evidence_hash"),
        _identifier("corrects_id", nullable=True),
        _primary_key("live_authorizations"),
        _foreign_key("live_authorizations", "account_id", "accounts"),
        _composite_foreign_key(
            "live_authorizations",
            ("promotion_evidence_hash", "stage", "promotion_eligible"),
            "promotion_evidence",
            ("evidence_hash", "stage", "eligible"),
        ),
        _foreign_key("live_authorizations", "corrects_id", "live_authorizations"),
        _unique("live_authorizations", "activation_nonce"),
        _unique("live_authorizations", "id", "activation_nonce", "artifact_hash"),
        _unique(
            "live_authorizations",
            "id",
            "account_id",
            "stage",
            "authorized_risk_equity",
            "config_hash",
            "code_hash",
            "strategy_eligibility_hash",
            "promotion_evidence_hash",
        ),
        sa.CheckConstraint(
            "promotion_eligible = 1",
            name=op.f("ck_live_authorizations_promotion_must_be_eligible"),
        ),
        sa.CheckConstraint(
            "stage IN ('micro_live', 'normal_live')",
            name=op.f("ck_live_authorizations_stage_live_only"),
        ),
    )
    op.create_table(
        "live_leases",
        _identifier("id"),
        _identifier("authorization_id"),
        _identifier("account_id"),
        _state("stage"),
        _utc("issued_at"),
        _utc("expires_at"),
        _utc("revoked_at", nullable=True),
        _text("revocation_reason", nullable=True),
        _decimal("authorized_risk_equity"),
        _hash("config_hash"),
        _hash("code_hash"),
        _hash("strategy_eligibility_hash"),
        _hash("promotion_evidence_hash"),
        _hash("evidence_hash"),
        _primary_key("live_leases"),
        _foreign_key("live_leases", "account_id", "accounts"),
        _foreign_key(
            "live_leases",
            "promotion_evidence_hash",
            "promotion_evidence",
            "evidence_hash",
        ),
        _composite_foreign_key(
            "live_leases",
            (
                "authorization_id",
                "account_id",
                "stage",
                "authorized_risk_equity",
                "config_hash",
                "code_hash",
                "strategy_eligibility_hash",
                "promotion_evidence_hash",
            ),
            "live_authorizations",
            (
                "id",
                "account_id",
                "stage",
                "authorized_risk_equity",
                "config_hash",
                "code_hash",
                "strategy_eligibility_hash",
                "promotion_evidence_hash",
            ),
        ),
        _unique("live_leases", "authorization_id"),
        _unique("live_leases", "id", "evidence_hash", "account_id", "stage"),
        sa.CheckConstraint(
            "stage IN ('micro_live', 'normal_live')",
            name=op.f("ck_live_leases_stage_live_only"),
        ),
    )
    op.create_table(
        "used_nonces",
        _identifier("nonce"),
        _identifier("authorization_id"),
        _hash("artifact_hash"),
        _utc("used_at"),
        _primary_key("used_nonces", "nonce"),
        _composite_foreign_key(
            "used_nonces",
            ("authorization_id", "nonce", "artifact_hash"),
            "live_authorizations",
            ("id", "activation_nonce", "artifact_hash"),
        ),
    )
    op.create_table(
        "kill_switch_events",
        _identifier("id"),
        _state("action"),
        _utc("occurred_at"),
        _name("actor"),
        _text("reason"),
        _hash("acknowledgement_hash", nullable=True),
        _hash("evidence_hash"),
        _identifier("correlation_id"),
        _hash("config_hash"),
        _hash("code_hash"),
        _identifier("corrects_id", nullable=True),
        _primary_key("kill_switch_events"),
        _foreign_key("kill_switch_events", "corrects_id", "kill_switch_events"),
    )
    op.create_table(
        "heartbeats",
        _identifier("id"),
        _identifier("instance_id"),
        _identifier("process_id"),
        _identifier("account_id", nullable=True),
        _state("execution_mode"),
        _state("runtime_state"),
        _boolean("healthy"),
        _utc("observed_at"),
        _boolean("clean_shutdown"),
        _hash("config_hash"),
        _hash("code_hash"),
        _hash("evidence_hash"),
        _primary_key("heartbeats"),
        _foreign_key("heartbeats", "account_id", "accounts"),
    )
    op.create_table(
        "execution_leases",
        _identifier("id"),
        _identifier("account_id"),
        _identifier("owner_id"),
        _integer("fencing_token"),
        _utc("acquired_at"),
        _utc("heartbeat_at"),
        _utc("expires_at"),
        _hash("evidence_hash"),
        _primary_key("execution_leases"),
        _foreign_key("execution_leases", "account_id", "accounts"),
        _unique("execution_leases", "account_id"),
    )
    op.create_table(
        "audit_events",
        _identifier("id"),
        _utc("occurred_at"),
        _name("category"),
        _name("actor"),
        _name("reason_code"),
        _identifier("correlation_id"),
        _hash("config_hash"),
        _hash("code_hash"),
        _hash("data_hash", nullable=True),
        _text("sanitized_details_json"),
        _identifier("corrects_id", nullable=True),
        _primary_key("audit_events"),
        _foreign_key("audit_events", "corrects_id", "audit_events"),
    )


def downgrade() -> None:
    for table_name in CORRECTION_TABLES:
        correction_table = sa.table(table_name, sa.column("corrects_id"))
        op.execute(correction_table.update().values(corrects_id=None))

    for table_name in (
        "audit_events",
        "execution_leases",
        "heartbeats",
        "kill_switch_events",
        "used_nonces",
        "alerts",
        "drawdown_events",
        "realized_pnl",
        "equity_curve",
        "positions",
        "portfolio_snapshots",
        "fills",
        "order_transitions",
        "orders",
        "submission_attempts",
        "live_leases",
        "live_authorizations",
        "configuration_versions",
        "reconciliation_events",
        "broker_reviews",
        "promotion_evidence",
        "research_acceptance_evidence",
        "risk_evaluations",
        "order_intents",
        "strategy_decisions",
        "signals",
        "features",
        "data_quality_events",
        "bars",
        "market_snapshots",
        "instruments",
        "accounts",
    ):
        op.drop_table(table_name)
