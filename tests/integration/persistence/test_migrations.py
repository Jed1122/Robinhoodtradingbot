"""Integration contract for the initial durable ledger migration."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, cast

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Inspector
from sqlalchemy.schema import SchemaItem

from trading_bot.persistence import Base
from trading_bot.persistence import models as persistence_models

REQUIRED_TABLES = {
    "accounts",
    "instruments",
    "market_snapshots",
    "bars",
    "data_quality_events",
    "features",
    "signals",
    "strategy_decisions",
    "risk_evaluations",
    "research_acceptance_evidence",
    "order_intents",
    "broker_reviews",
    "submission_attempts",
    "orders",
    "order_transitions",
    "fills",
    "positions",
    "portfolio_snapshots",
    "equity_curve",
    "realized_pnl",
    "drawdown_events",
    "alerts",
    "reconciliation_events",
    "promotion_evidence",
    "promotion_observations",
    "configuration_versions",
    "live_authorizations",
    "live_leases",
    "used_nonces",
    "kill_switch_events",
    "heartbeats",
    "execution_leases",
    "audit_events",
}

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
UTC_TEXT = "2026-07-13T12:00:00.000000Z"
PROMOTION_EXPIRES_TEXT = "2026-07-13T12:05:00.000000Z"


@contextmanager
def _inspect_database(database_path: Path) -> Iterator[Inspector]:
    engine = sa.create_engine(f"sqlite:///{database_path}")
    try:
        yield sa.inspect(engine)
    finally:
        engine.dispose()


def _unique_column_sets(inspector: Inspector, table_name: str) -> set[tuple[str, ...]]:
    primary_key = tuple(inspector.get_pk_constraint(table_name)["constrained_columns"])
    unique_sets = {primary_key} if primary_key else set()
    unique_sets.update(
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(table_name)
    )
    unique_sets.update(
        tuple(cast(list[str], index["column_names"]))
        for index in inspector.get_indexes(table_name)
        if index["unique"]
    )
    return unique_sets


def _foreign_key_targets(inspector: Inspector, table_name: str) -> set[tuple[str, str]]:
    return {
        (local_column, str(foreign_key["referred_table"]))
        for foreign_key in inspector.get_foreign_keys(table_name)
        for local_column in foreign_key["constrained_columns"]
    }


def _connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _seed_account(
    connection: sqlite3.Connection,
    *,
    account_id: str = "account-1",
    provider: str = "provider",
    equity: object = "1000",
    equity_buying_power: str | None = "1000",
    crypto_buying_power: str | None = "1000",
    prediction_buying_power: str | None = None,
    observed_at: str = UTC_TEXT,
) -> None:
    connection.execute(
        """
        INSERT INTO accounts (
            id, provider, provider_account_id, account_type, provider_state,
            equity, cash, equity_buying_power, crypto_buying_power,
            prediction_buying_power, restricted,
            observed_at, data_hash, config_hash, code_hash
        ) VALUES (?, ?, ?, 'cash', 'active', ?, '1000', ?, ?, ?, 0, ?, ?, ?, ?)
        """,
        (
            account_id,
            provider,
            f"external-{account_id}",
            equity,
            equity_buying_power,
            crypto_buying_power,
            prediction_buying_power,
            observed_at,
            HASH_A,
            HASH_B,
            HASH_C,
        ),
    )


def _seed_instrument(
    connection: sqlite3.Connection,
    *,
    instrument_id: str = "instrument-1",
    provider: str = "provider",
) -> None:
    connection.execute(
        """
        INSERT INTO instruments (
            id, provider, provider_instrument_id, symbol, asset_class,
            provider_status, tradable, fractional_eligible, price_increment,
            quantity_increment, minimum_quantity, minimum_notional,
            maximum_quantity, correlation_group, observed_at, data_hash
        ) VALUES (?, ?, ?, 'ABC', 'equity', 'active', 1, 1, '0.01',
                  '0.0001', '0.0001', '1', NULL, 'equity:ABC', ?, ?)
        """,
        (instrument_id, provider, f"external-{instrument_id}", UTC_TEXT, HASH_A),
    )


def _seed_intent(
    connection: sqlite3.Connection,
    intent_id: str,
    *,
    asset_class: str = "equity",
    limit_price: str | None = "10",
    stop_price: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO order_intents (
            id, account_id, instrument_id, strategy_decision_id, asset_class,
            side, purpose, order_type, time_in_force, quantity, limit_price,
            stop_price, created_at, expires_at, strategy_version, config_hash,
            code_hash, data_hash, exit_policy_version
        ) VALUES (?, 'account-1', 'instrument-1', NULL, ?, 'buy', 'entry',
                  'limit', 'day', '1', ?, ?, ?,
                  '2026-07-13T12:05:00.000000Z', 'strategy-v1', ?, ?, ?, 'exit-v1')
        """,
        (
            intent_id,
            asset_class,
            limit_price,
            stop_price,
            UTC_TEXT,
            HASH_A,
            HASH_B,
            HASH_C,
        ),
    )


def _seed_review(
    connection: sqlite3.Connection,
    review_id: str,
    intent_id: str,
    *,
    client_order_id: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO broker_reviews (
            id, intent_id, source, reviewed_at, expires_at, estimated_notional,
            estimated_fees, client_order_id, outbound_payload_sha256,
            normalized_intent_hash, sanitized_response_hash, broker_review_id
        ) VALUES (?, ?, 'provider-review', ?, '2026-07-13T12:04:00.000000Z',
                  '10', '0', ?, ?, ?, ?, NULL)
        """,
        (review_id, intent_id, UTC_TEXT, client_order_id, HASH_A, HASH_B, HASH_C),
    )


def _seed_submission(
    connection: sqlite3.Connection,
    submission_id: str,
    intent_id: str,
    review_id: str,
    *,
    provider: str = "provider",
    account_id: str = "account-1",
    instrument_id: str = "instrument-1",
    provider_client_reference: str | None = None,
    deduplication_key: str = HASH_A,
    execution_mode: str = "paper",
    live_lease_id: str | None = None,
    live_lease_evidence_hash: str | None = None,
    fencing_token: int | None = None,
    completed_at: str | None = None,
    outcome_class: str = "pending",
    sanitized_response_hash: str | None = None,
) -> None:
    effective_fencing_token = (
        (1 if execution_mode in {"micro_live", "normal_live"} else 0)
        if fencing_token is None
        else fencing_token
    )
    connection.execute(
        """
        INSERT INTO submission_attempts (
            id, intent_id, review_id, account_id, instrument_id,
            deduplication_key, provider,
            provider_client_reference, fencing_token, attempt_started_at,
            execution_mode, live_lease_id, live_lease_evidence_hash,
            completed_at, outcome_class, sanitized_response_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            submission_id,
            intent_id,
            review_id,
            account_id,
            instrument_id,
            deduplication_key,
            provider,
            provider_client_reference,
            effective_fencing_token,
            UTC_TEXT,
            execution_mode,
            live_lease_id,
            live_lease_evidence_hash,
            completed_at,
            outcome_class,
            sanitized_response_hash,
        ),
    )


def _seed_order(
    connection: sqlite3.Connection,
    order_id: str,
    broker_order_id: str,
    submission_id: str | None,
    *,
    intent_id: str | None = "intent-1",
    review_id: str | None = "review-1",
    provider: str = "provider",
    account_id: str = "account-1",
    instrument_id: str = "instrument-1",
    side: str = "buy",
    purpose: str = "entry",
    order_type: str = "limit",
    time_in_force: str = "day",
    requested_quantity: str = "1",
    limit_price: str | None = "10",
    stop_price: str | None = None,
    client_order_id: str | None = None,
    state: str = "submitted",
) -> None:
    connection.execute(
        """
        INSERT INTO orders (
            id, intent_id, review_id, submission_attempt_id, provider,
            broker_order_id, client_order_id, account_id, instrument_id, side,
            purpose, order_type, time_in_force, state, requested_quantity,
            filled_quantity, limit_price, stop_price, average_fill_price,
            created_at, updated_at, data_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?,
                  ?, ?, '0', ?, ?, NULL, ?, ?, ?)
        """,
        (
            order_id,
            intent_id,
            review_id,
            submission_id,
            provider,
            broker_order_id,
            client_order_id,
            account_id,
            instrument_id,
            side,
            purpose,
            order_type,
            time_in_force,
            state,
            requested_quantity,
            limit_price,
            stop_price,
            UTC_TEXT,
            UTC_TEXT,
            HASH_A,
        ),
    )


def _seed_fill(
    connection: sqlite3.Connection,
    *,
    fill_id: str = "fill-1",
    account_id: str = "account-1",
    instrument_id: str = "instrument-1",
) -> None:
    connection.execute(
        """
        INSERT INTO fills (
            id, order_id, provider, external_execution_key, broker_order_id,
            account_id, instrument_id, side, quantity, price, fee, occurred_at,
            occurrence_ordinal, data_hash
        ) VALUES (?, 'order-1', 'provider', ?, 'broker-order-1', ?, ?, 'buy',
                  '1', '10', '0', ?, 0, ?)
        """,
        (fill_id, f"execution-{fill_id}", account_id, instrument_id, UTC_TEXT, HASH_A),
    )


def _seed_portfolio_snapshot(
    connection: sqlite3.Connection,
    *,
    snapshot_id: str = "snapshot-1",
    account_id: str = "account-1",
) -> None:
    connection.execute(
        """
        INSERT INTO portfolio_snapshots (
            id, account_id, equity, cash, gross_exposure, net_exposure,
            crypto_exposure, realized_pnl, unrealized_pnl, observed_at, data_hash
        ) VALUES (?, ?, '1000', '900', '100', '100', '0', '0', '0', ?, ?)
        """,
        (snapshot_id, account_id, UTC_TEXT, HASH_A),
    )


def _seed_position(
    connection: sqlite3.Connection,
    *,
    position_id: str = "position-1",
    account_id: str = "account-1",
    instrument_id: str = "instrument-1",
    portfolio_snapshot_id: str | None = "snapshot-1",
    asset_class: str = "equity",
) -> None:
    connection.execute(
        """
        INSERT INTO positions (
            id, account_id, instrument_id, portfolio_snapshot_id, asset_class,
            quantity, average_price, market_value, unrealized_pnl, observed_at,
            data_hash
        ) VALUES (?, ?, ?, ?, ?, '1', '10', '10', '0', ?, ?)
        """,
        (
            position_id,
            account_id,
            instrument_id,
            portfolio_snapshot_id,
            asset_class,
            UTC_TEXT,
            HASH_A,
        ),
    )


def _seed_realized_pnl(
    connection: sqlite3.Connection,
    *,
    pnl_id: str = "pnl-1",
    account_id: str = "account-1",
    instrument_id: str | None = "instrument-1",
    fill_id: str | None = "fill-1",
) -> None:
    connection.execute(
        """
        INSERT INTO realized_pnl (
            id, account_id, instrument_id, fill_id, amount, realized_at, data_hash
        ) VALUES (?, ?, ?, ?, '1', ?, ?)
        """,
        (pnl_id, account_id, instrument_id, fill_id, UTC_TEXT, HASH_A),
    )


def _seed_promotion_and_authorization(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO promotion_evidence (
            id, stage, eligible, evidence_hash, reason_codes_json,
            evaluated_at, expires_at
        ) VALUES ('promotion-1', 'micro_live', 1, ?, '[]', ?, ?)
        """,
        (HASH_A, UTC_TEXT, PROMOTION_EXPIRES_TEXT),
    )
    connection.execute(
        """
        INSERT INTO promotion_evidence (
            id, stage, eligible, evidence_hash, reason_codes_json,
            evaluated_at, expires_at
        ) VALUES ('promotion-2', 'normal_live', 1, ?, '[]', ?, ?)
        """,
        (HASH_B, UTC_TEXT, PROMOTION_EXPIRES_TEXT),
    )
    connection.execute(
        """
        INSERT INTO promotion_evidence (
            id, stage, eligible, evidence_hash, reason_codes_json,
            evaluated_at, expires_at
        ) VALUES ('promotion-3', 'micro_live', 0, ?, '["ineligible"]', ?, ?)
        """,
        (HASH_C, UTC_TEXT, PROMOTION_EXPIRES_TEXT),
    )
    connection.execute(
        """
        INSERT INTO live_authorizations (
            id, account_id, stage, activation_nonce, artifact_hash, preflight_hash,
            acknowledgement_hash, config_hash, code_hash, strategy_eligibility_hash,
            promotion_evidence_hash, promotion_eligible, authorized_risk_equity,
            issued_at, expires_at,
            consumed_at, status, evidence_hash, corrects_id
        ) VALUES ('authorization-1', 'account-1', 'micro_live', 'nonce-right', ?, ?, ?, ?, ?, ?,
                  ?, 1, '100', ?, ?, NULL, 'issued', ?, NULL)
        """,
        (HASH_A, HASH_A, HASH_A, HASH_A, HASH_A, HASH_A, HASH_A, UTC_TEXT, UTC_TEXT, HASH_A),
    )


def _seed_live_lease(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO live_leases (
            id, authorization_id, account_id, stage, issued_at, expires_at,
            revoked_at, revocation_reason, authorized_risk_equity, config_hash,
            code_hash, strategy_eligibility_hash, promotion_evidence_hash,
            evidence_hash
        ) VALUES ('live-lease-1', 'authorization-1', 'account-1', 'micro_live', ?, ?,
                  NULL, NULL, '100', ?, ?, ?, ?, ?)
        """,
        (UTC_TEXT, UTC_TEXT, HASH_A, HASH_A, HASH_A, HASH_A, HASH_B),
    )


def _seed_audit_correction(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO audit_events (
            id, occurred_at, category, actor, reason_code, correlation_id,
            config_hash, code_hash, data_hash, sanitized_details_json, corrects_id
        ) VALUES ('audit-1', ?, 'persistence', 'test', 'seed', 'correlation-1',
                  ?, ?, NULL, '{}', NULL)
        """,
        (UTC_TEXT, HASH_A, HASH_B),
    )
    connection.execute(
        """
        INSERT INTO audit_events (
            id, occurred_at, category, actor, reason_code, correlation_id,
            config_hash, code_hash, data_hash, sanitized_details_json, corrects_id
        ) VALUES ('audit-2', ?, 'persistence', 'test', 'correction',
                  'correlation-1', ?, ?, NULL, '{}', 'audit-1')
        """,
        (UTC_TEXT, HASH_A, HASH_B),
    )


def test_upgrade_head_creates_required_tables(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with _inspect_database(database_path) as inspector:
        table_names = set(inspector.get_table_names())
        assert table_names >= REQUIRED_TABLES
        assert "alembic_version" in table_names


def test_upgrade_records_core_revision(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(sqlite3.connect(database_path)) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert revision == ("0004_promotion_observations",)


def test_models_register_exactly_the_required_tables() -> None:
    assert persistence_models is not None
    assert set(Base.metadata.tables) == REQUIRED_TABLES


def test_default_alembic_paths_are_anchored_to_the_configuration_directory() -> None:
    config = Config(str(Path(__file__).parents[3] / "alembic.ini"))
    script_location = config.get_main_option("script_location")
    prepend_sys_path = config.get_main_option("prepend_sys_path")
    database_url = config.get_main_option("sqlalchemy.url")

    assert script_location is not None and Path(script_location).is_absolute()
    assert prepend_sys_path is not None and Path(prepend_sys_path).is_absolute()
    assert database_url is not None and str(Path(__file__).parents[3]) in database_url


def test_migration_and_metadata_do_not_drift(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")
    engine = sa.create_engine(f"sqlite:///{database_path}")
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()


def test_every_ledger_table_has_a_primary_key(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")
    with _inspect_database(database_path) as inspector:
        for table_name in REQUIRED_TABLES:
            assert inspector.get_pk_constraint(table_name)["constrained_columns"], table_name


def test_required_idempotency_constraints_exist(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")
    expected = {
        "accounts": ("provider", "provider_account_id"),
        "order_intents": ("id",),
        "submission_attempts": ("intent_id",),
        "orders": ("provider", "broker_order_id"),
        "orders_submission": ("submission_attempt_id",),
        "fills": ("provider", "external_execution_key"),
        "used_nonces": ("nonce",),
        "promotion_evidence": ("evidence_hash",),
        "audit_events": ("id",),
    }

    with _inspect_database(database_path) as inspector:
        for table_name, column_names in expected.items():
            inspected_table = "orders" if table_name == "orders_submission" else table_name
            assert column_names in _unique_column_sets(inspector, inspected_table), table_name


def test_schema_persists_required_domain_contract_fields(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")
    expected = {
        "accounts": {
            "provider_state",
            "equity_buying_power",
            "crypto_buying_power",
            "prediction_buying_power",
        },
        "instruments": {"minimum_notional"},
        "broker_reviews": {
            "estimated_notional",
            "estimated_fees",
            "client_order_id",
            "outbound_payload_sha256",
        },
        "orders": {"created_at", "data_hash"},
        "positions": {"portfolio_snapshot_id"},
        "portfolio_snapshots": {"realized_pnl", "unrealized_pnl"},
    }

    with _inspect_database(database_path) as inspector:
        for table_name, required_columns in expected.items():
            columns = {column["name"] for column in inspector.get_columns(table_name)}
            assert columns >= required_columns, table_name
        broker_review_columns = {
            column["name"] for column in inspector.get_columns("broker_reviews")
        }
        assert "request_hash" not in broker_review_columns
        account_columns = {column["name"]: column for column in inspector.get_columns("accounts")}
        for column_name in (
            "equity_buying_power",
            "crypto_buying_power",
            "prediction_buying_power",
        ):
            assert account_columns[column_name]["nullable"] is True


def test_submission_attempt_schema_captures_the_crash_boundary(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")
    with _inspect_database(database_path) as inspector:
        columns = {
            column["name"]: column for column in inspector.get_columns("submission_attempts")
        }
    required_columns = {
        "intent_id",
        "review_id",
        "account_id",
        "instrument_id",
        "deduplication_key",
        "provider_client_reference",
        "fencing_token",
        "attempt_started_at",
        "execution_mode",
        "live_lease_id",
        "live_lease_evidence_hash",
        "outcome_class",
        "sanitized_response_hash",
    }

    assert required_columns <= columns.keys()
    assert columns["provider_client_reference"]["nullable"] is True
    assert "BLOB" in str(columns["fencing_token"]["type"]).upper()
    assert columns["fencing_token"]["nullable"] is False


def test_trading_values_never_use_sqlite_float_affinity(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")
    with _inspect_database(database_path) as inspector:
        for table_name in REQUIRED_TABLES:
            for column in inspector.get_columns(table_name):
                storage_type = str(column["type"]).upper()
                assert all(token not in storage_type for token in ("REAL", "FLOAT", "DOUBLE")), (
                    table_name,
                    column["name"],
                    storage_type,
                )


def test_schema_contains_the_normalized_economic_effect_chain(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")
    expected_targets = {
        "risk_evaluations": {("intent_id", "order_intents")},
        "broker_reviews": {("intent_id", "order_intents")},
        "submission_attempts": {
            ("intent_id", "order_intents"),
            ("review_id", "broker_reviews"),
        },
        "orders": {
            ("account_id", "accounts"),
            ("instrument_id", "instruments"),
        },
        "order_transitions": {("intent_id", "order_intents")},
        "fills": {("order_id", "orders")},
        "positions": {
            ("account_id", "accounts"),
            ("instrument_id", "instruments"),
            ("portfolio_snapshot_id", "portfolio_snapshots"),
        },
    }

    with _inspect_database(database_path) as inspector:
        for table_name, targets in expected_targets.items():
            assert _foreign_key_targets(inspector, table_name) >= targets, table_name

        assert ("intent_id",) not in _unique_column_sets(inspector, "risk_evaluations")
        order_columns = {column["name"]: column for column in inspector.get_columns("orders")}
        assert order_columns["intent_id"]["nullable"] is True


def test_live_lease_is_bound_to_promotion_evidence_by_hash(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")
    with _inspect_database(database_path) as inspector:
        matching = [
            foreign_key
            for foreign_key in inspector.get_foreign_keys("live_leases")
            if foreign_key["constrained_columns"] == ["promotion_evidence_hash"]
        ]

    assert len(matching) == 1
    assert matching[0]["referred_table"] == "promotion_evidence"
    assert matching[0]["referred_columns"] == ["evidence_hash"]
    assert str(matching[0].get("options", {}).get("ondelete")).upper() == "RESTRICT"


def test_safety_scalar_columns_use_exact_types_in_orm_metadata() -> None:
    from trading_bot.persistence import (
        CanonicalDecimal,
        ExactBoolean,
        ExactNonNegativeInteger,
        SHA256Digest,
        UTCDateTime,
    )

    for table in Base.metadata.tables.values():
        for column in table.columns:
            if column.name.endswith(("_hash", "_sha256")) or column.name in {
                "deduplication_key",
            }:
                assert isinstance(column.type, SHA256Digest), f"{table.name}.{column.name}"
            if isinstance(column.type, sa.Boolean):
                raise AssertionError(f"{table.name}.{column.name} uses coercive Boolean")
            if isinstance(column.type, CanonicalDecimal):
                assert any(
                    str(constraint.name).endswith(f"{column.name}_canonical_decimal")
                    for constraint in column.constraints
                ), f"{table.name}.{column.name}"
            if isinstance(column.type, UTCDateTime):
                assert any(
                    str(constraint.name).endswith(f"{column.name}_canonical_utc")
                    for constraint in column.constraints
                ), f"{table.name}.{column.name}"
            if column.name in {
                "check_count",
                "drift_count",
                "fencing_token",
                "occurrence_ordinal",
            }:
                assert isinstance(column.type, ExactNonNegativeInteger), (
                    table.name,
                    column.name,
                )
            if column.name in {
                "active",
                "allowed",
                "clean",
                "clean_shutdown",
                "eligible",
                "fractional_eligible",
                "freshness_verified",
                "healthy",
                "interpolated",
                "promotion_eligible",
                "restricted",
                "tradable",
            }:
                assert isinstance(column.type, ExactBoolean), (table.name, column.name)


@pytest.mark.parametrize(
    ("eligible", "evidence_hash"),
    [
        (2, HASH_A),
        ("1", HASH_A),
        (1.0, HASH_A),
        (1, "A" * 64),
        (1, "x" * 1_000),
        (1, f"{HASH_A}\x00junk"),
    ],
)
def test_database_rejects_noncanonical_boolean_and_hash_values(
    alembic_config: Config,
    database_path: Path,
    eligible: object,
    evidence_hash: str,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO promotion_evidence (
                id, stage, eligible, evidence_hash, reason_codes_json,
                evaluated_at, expires_at
            ) VALUES ('promotion-1', 'paper', ?, ?, '[]', ?, ?)
            """,
            (eligible, evidence_hash, UTC_TEXT, PROMOTION_EXPIRES_TEXT),
        )


@pytest.mark.parametrize("invalid_integer", ["abc", "7", 7.0])
def test_database_rejects_noncanonical_nonnegative_integer_values(
    alembic_config: Config,
    database_path: Path,
    invalid_integer: object,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO execution_leases (
                    id, account_id, owner_id, fencing_token, acquired_at,
                    heartbeat_at, expires_at, evidence_hash
                ) VALUES ('lease-1', 'account-1', 'owner-1', ?, ?, ?, ?, ?)
                """,
                (invalid_integer, UTC_TEXT, UTC_TEXT, UTC_TEXT, HASH_A),
            )


@pytest.mark.parametrize(
    "invalid_decimal",
    [
        "",
        "00",
        "NaN",
        "01.0",
        "1E+3",
        "-0",
        ".5",
        "0.",
        "+1",
        " 1",
        "1.0",
        "1" * 513,
        "1\x00junk",
        1,
        1.5,
        True,
    ],
)
def test_database_rejects_noncanonical_decimal_text(
    alembic_config: Config,
    database_path: Path,
    invalid_decimal: object,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection, pytest.raises(sqlite3.IntegrityError):
        _seed_account(connection, equity=invalid_decimal)


@pytest.mark.parametrize(
    "invalid_timestamp",
    [
        "not-utc",
        "2026-07-13T12:00:00+00:00",
        "2026-07-13T12:00:00.000000+00:00",
        "2026-02-30T12:00:00.000000Z",
        "0000-01-01T00:00:00.000000Z",
        "2026-13-01T00:00:00.000000Z",
        "2026-01-01T24:00:00.000000Z",
        "2026-07-13T25:00:00.000000Z",
        "2026-07-13T12:60:00.000000Z",
        "2026-07-13T12:00:60.000000Z",
        f"{UTC_TEXT}\x00junk",
    ],
)
def test_database_rejects_noncanonical_or_invalid_utc_text(
    alembic_config: Config,
    database_path: Path,
    invalid_timestamp: str,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection, pytest.raises(sqlite3.IntegrityError):
        _seed_account(connection, observed_at=invalid_timestamp)


@pytest.mark.parametrize("canonical_decimal", ["0", "0.05", "-12.5", "1000.0001"])
def test_database_accepts_canonical_decimal_text(
    alembic_config: Config,
    database_path: Path,
    canonical_decimal: str,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection, equity=canonical_decimal)
        stored = connection.execute("SELECT equity FROM accounts").fetchone()

    assert stored == (canonical_decimal,)


@pytest.mark.parametrize(
    "canonical_timestamp",
    ["2024-02-29T23:59:59.999999Z", "0001-01-01T00:00:00.000001Z"],
)
def test_database_accepts_canonical_utc_text(
    alembic_config: Config,
    database_path: Path,
    canonical_timestamp: str,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection, observed_at=canonical_timestamp)
        stored = connection.execute("SELECT observed_at FROM accounts").fetchone()

    assert stored == (canonical_timestamp,)


def test_account_buying_power_supports_asset_specific_snapshots(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(
            connection,
            equity_buying_power=None,
            crypto_buying_power="1000.25",
            prediction_buying_power=None,
        )
        buying_power = connection.execute(
            """
            SELECT equity_buying_power, crypto_buying_power, prediction_buying_power
            FROM accounts WHERE id = 'account-1'
            """
        ).fetchone()

    assert buying_power == (None, "1000.25", None)


def test_account_provider_identity_is_unique_in_database(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO accounts (
                    id, provider, provider_account_id, account_type, provider_state,
                    equity, cash, equity_buying_power, crypto_buying_power, restricted,
                    observed_at, data_hash, config_hash, code_hash
                ) VALUES ('account-2', 'provider', 'external-account-1', 'cash',
                          'active', '1000', '1000', '1000', '1000', 0, ?, ?, ?, ?)
                """,
                (UTC_TEXT, HASH_A, HASH_B, HASH_C),
            )


def test_order_intent_asset_class_must_match_its_instrument(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        with pytest.raises(sqlite3.IntegrityError):
            _seed_intent(connection, "intent-1", asset_class="crypto")


def test_position_asset_class_must_match_its_instrument(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        with pytest.raises(sqlite3.IntegrityError):
            _seed_position(
                connection,
                portfolio_snapshot_id=None,
                asset_class="crypto",
            )


def test_submission_review_must_belong_to_the_same_intent(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_intent(connection, "intent-1")
        _seed_intent(connection, "intent-2")
        _seed_review(connection, "review-1", "intent-1")
        _seed_review(connection, "review-2", "intent-2")
        with pytest.raises(sqlite3.IntegrityError):
            _seed_submission(connection, "submission-1", "intent-1", "review-2")


@pytest.mark.parametrize(
    ("review_client_order_id", "provider_client_reference"),
    [
        ("client-order-1", None),
        ("client-order-1", "wrong-client-order"),
        (None, ""),
    ],
)
def test_submission_client_reference_must_match_its_review_null_safely(
    alembic_config: Config,
    database_path: Path,
    review_client_order_id: str | None,
    provider_client_reference: str | None,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_intent(connection, "intent-1")
        _seed_review(
            connection,
            "review-1",
            "intent-1",
            client_order_id=review_client_order_id,
        )

        with pytest.raises(sqlite3.IntegrityError):
            _seed_submission(
                connection,
                "submission-1",
                "intent-1",
                "review-1",
                provider_client_reference=provider_client_reference,
            )


@pytest.mark.parametrize(
    ("provider", "account_id", "instrument_id"),
    [
        ("wrong-provider", "account-1", "instrument-1"),
        ("provider", "account-2", "instrument-1"),
        ("provider", "account-1", "instrument-2"),
    ],
)
def test_submission_scope_must_match_its_intent_account_instrument_and_provider(
    alembic_config: Config,
    database_path: Path,
    provider: str,
    account_id: str,
    instrument_id: str,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_account(connection, account_id="account-2")
        _seed_instrument(connection)
        _seed_instrument(connection, instrument_id="instrument-2")
        _seed_intent(connection, "intent-1")
        _seed_review(connection, "review-1", "intent-1")
        with pytest.raises(sqlite3.IntegrityError):
            _seed_submission(
                connection,
                "submission-1",
                "intent-1",
                "review-1",
                provider=provider,
                account_id=account_id,
                instrument_id=instrument_id,
            )


@pytest.mark.parametrize(
    ("execution_mode", "live_lease_id", "live_lease_evidence_hash"),
    [
        ("micro_live", None, None),
        ("micro_live", "live-lease-1", HASH_A),
        ("normal_live", "live-lease-1", HASH_B),
        ("paper", "live-lease-1", HASH_B),
        ("unknown", None, None),
    ],
)
def test_submission_attempt_requires_mode_appropriate_live_lease_provenance(
    alembic_config: Config,
    database_path: Path,
    execution_mode: str,
    live_lease_id: str | None,
    live_lease_evidence_hash: str | None,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_intent(connection, "intent-1")
        _seed_review(connection, "review-1", "intent-1")
        _seed_promotion_and_authorization(connection)
        _seed_live_lease(connection)
        with pytest.raises(sqlite3.IntegrityError):
            _seed_submission(
                connection,
                "submission-1",
                "intent-1",
                "review-1",
                execution_mode=execution_mode,
                live_lease_id=live_lease_id,
                live_lease_evidence_hash=live_lease_evidence_hash,
            )


def test_live_submission_attempt_persists_matching_lease_provenance(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_intent(connection, "intent-1")
        _seed_review(connection, "review-1", "intent-1")
        _seed_promotion_and_authorization(connection)
        _seed_live_lease(connection)
        _seed_submission(
            connection,
            "submission-1",
            "intent-1",
            "review-1",
            execution_mode="micro_live",
            live_lease_id="live-lease-1",
            live_lease_evidence_hash=HASH_B,
        )
        provenance = connection.execute(
            """
            SELECT execution_mode, live_lease_id, live_lease_evidence_hash
            FROM submission_attempts
            """
        ).fetchone()

    assert provenance == ("micro_live", "live-lease-1", HASH_B)


@pytest.mark.parametrize("execution_mode", ["backtest", "simulation", "paper", "shadow"])
def test_submission_accepts_nonlive_mode_without_lease_provenance(
    alembic_config: Config,
    database_path: Path,
    execution_mode: str,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_intent(connection, "intent-1")
        _seed_review(connection, "review-1", "intent-1")
        _seed_submission(
            connection,
            "submission-1",
            "intent-1",
            "review-1",
            execution_mode=execution_mode,
        )

        stored = connection.execute(
            "SELECT execution_mode, live_lease_id FROM submission_attempts"
        ).fetchone()

    assert stored == (execution_mode, None)


def test_submission_attempt_contract_is_pending_then_exactly_once_terminal(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_intent(connection, "intent-1")
        _seed_review(connection, "review-1", "intent-1")
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError, match="submission attempt contract"):
            _seed_submission(
                connection,
                "invalid-submission",
                "intent-1",
                "review-1",
                fencing_token=1,
            )

        _seed_submission(connection, "submission-1", "intent-1", "review-1")
        _seed_order(
            connection,
            "order-1",
            "broker-order-1",
            "submission-1",
        )
        connection.execute(
            """
            UPDATE submission_attempts
            SET outcome_class = 'accepted', completed_at = ?, sanitized_response_hash = ?
            WHERE id = 'submission-1'
            """,
            (UTC_TEXT, HASH_B),
        )
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError, match="submission attempt contract"):
            connection.execute(
                "UPDATE submission_attempts SET outcome_class = 'rejected' "
                "WHERE id = 'submission-1'"
            )

        stored = connection.execute(
            "SELECT outcome_class, completed_at, sanitized_response_hash "
            "FROM submission_attempts WHERE id = 'submission-1'"
        ).fetchone()

    assert stored == ("accepted", UTC_TEXT, HASH_B)


@pytest.mark.parametrize("outcome_class", ["accepted", "rejected", "ambiguous", "unknown"])
def test_submission_attempt_insert_rejects_every_non_pending_outcome(
    alembic_config: Config,
    database_path: Path,
    outcome_class: str,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_intent(connection, "intent-1")
        _seed_review(connection, "review-1", "intent-1")
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError, match="submission attempt contract"):
            _seed_submission(
                connection,
                "submission-1",
                "intent-1",
                "review-1",
                completed_at=UTC_TEXT,
                outcome_class=outcome_class,
                sanitized_response_hash=HASH_B,
            )


@pytest.mark.parametrize(
    ("outcome_class", "order_state", "response_hash"),
    [
        ("accepted", "submitted", HASH_B),
        ("rejected", "rejected", HASH_B),
        ("ambiguous", None, None),
        ("ambiguous", None, HASH_B),
    ],
)
def test_submission_attempt_allows_only_well_formed_terminal_updates(
    alembic_config: Config,
    database_path: Path,
    outcome_class: str,
    order_state: str | None,
    response_hash: str | None,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_intent(connection, "intent-1")
        _seed_review(connection, "review-1", "intent-1")
        _seed_submission(connection, "submission-1", "intent-1", "review-1")
        if order_state is not None:
            _seed_order(
                connection,
                "order-1",
                "broker-order-1",
                "submission-1",
                state=order_state,
            )
        connection.execute(
            """
            UPDATE submission_attempts
            SET outcome_class = ?, completed_at = ?, sanitized_response_hash = ?
            WHERE id = 'submission-1'
            """,
            (outcome_class, UTC_TEXT, response_hash),
        )
        connection.commit()

        stored = connection.execute(
            "SELECT outcome_class, completed_at, sanitized_response_hash "
            "FROM submission_attempts WHERE id = 'submission-1'"
        ).fetchone()

    assert stored == (outcome_class, UTC_TEXT, response_hash)


@pytest.mark.parametrize(
    ("outcome_class", "order_state", "completed_at", "response_hash"),
    [
        ("accepted", None, UTC_TEXT, HASH_B),
        ("rejected", None, UTC_TEXT, HASH_B),
        ("accepted", "rejected", UTC_TEXT, HASH_B),
        ("rejected", "submitted", UTC_TEXT, HASH_B),
        ("accepted", "submitted", UTC_TEXT, None),
        ("rejected", "rejected", UTC_TEXT, None),
        ("accepted", "submitted", "2026-07-13T11:59:59.000000Z", HASH_B),
    ],
)
def test_submission_attempt_rejects_malformed_terminal_updates(
    alembic_config: Config,
    database_path: Path,
    outcome_class: str,
    order_state: str | None,
    completed_at: str,
    response_hash: str | None,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_intent(connection, "intent-1")
        _seed_review(connection, "review-1", "intent-1")
        _seed_submission(connection, "submission-1", "intent-1", "review-1")
        if order_state is not None:
            _seed_order(
                connection,
                "order-1",
                "broker-order-1",
                "submission-1",
                state=order_state,
            )
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError, match="submission attempt contract"):
            connection.execute(
                """
                UPDATE submission_attempts
                SET outcome_class = ?, completed_at = ?, sanitized_response_hash = ?
                WHERE id = 'submission-1'
                """,
                (outcome_class, completed_at, response_hash),
            )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE submission_attempts SET provider = 'other' WHERE id = 'submission-1'",
        "UPDATE submission_attempts SET outcome_class = 'pending' WHERE id = 'submission-1'",
    ],
)
def test_submission_attempt_rejects_immutable_or_noop_updates(
    alembic_config: Config,
    database_path: Path,
    statement: str,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_intent(connection, "intent-1")
        _seed_review(connection, "review-1", "intent-1")
        _seed_submission(connection, "submission-1", "intent-1", "review-1")
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError, match="submission attempt contract"):
            connection.execute(statement)


def test_live_submission_attempt_rejects_zero_fencing_token(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_intent(connection, "intent-1")
        _seed_review(connection, "review-1", "intent-1")
        _seed_promotion_and_authorization(connection)
        _seed_live_lease(connection)
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError, match="submission attempt contract"):
            _seed_submission(
                connection,
                "submission-1",
                "intent-1",
                "review-1",
                execution_mode="micro_live",
                live_lease_id="live-lease-1",
                live_lease_evidence_hash=HASH_B,
                fencing_token=0,
            )


def test_live_submission_lease_must_match_the_submission_account(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_account(connection, account_id="account-2")
        _seed_instrument(connection)
        _seed_intent(connection, "intent-1")
        _seed_review(connection, "review-1", "intent-1")
        _seed_promotion_and_authorization(connection)
        connection.execute(
            """
            INSERT INTO live_authorizations (
                id, account_id, stage, activation_nonce, artifact_hash, preflight_hash,
                acknowledgement_hash, config_hash, code_hash, strategy_eligibility_hash,
                promotion_evidence_hash, promotion_eligible, authorized_risk_equity,
                issued_at, expires_at, consumed_at, status, evidence_hash, corrects_id
            ) VALUES ('authorization-2', 'account-2', 'micro_live', 'nonce-2', ?, ?, ?, ?, ?, ?,
                      ?, 1, '100', ?, ?, NULL, 'issued', ?, NULL)
            """,
            (
                HASH_A,
                HASH_A,
                HASH_A,
                HASH_A,
                HASH_A,
                HASH_A,
                HASH_A,
                UTC_TEXT,
                UTC_TEXT,
                HASH_A,
            ),
        )
        connection.execute(
            """
            INSERT INTO live_leases (
                id, authorization_id, account_id, stage, issued_at, expires_at,
                revoked_at, revocation_reason, authorized_risk_equity, config_hash,
                code_hash, strategy_eligibility_hash, promotion_evidence_hash,
                evidence_hash
            ) VALUES ('live-lease-2', 'authorization-2', 'account-2', 'micro_live', ?, ?,
                      NULL, NULL, '100', ?, ?, ?, ?, ?)
            """,
            (UTC_TEXT, UTC_TEXT, HASH_A, HASH_A, HASH_A, HASH_A, HASH_B),
        )
        with pytest.raises(sqlite3.IntegrityError):
            _seed_submission(
                connection,
                "submission-1",
                "intent-1",
                "review-1",
                execution_mode="micro_live",
                live_lease_id="live-lease-2",
                live_lease_evidence_hash=HASH_B,
            )


def test_one_submission_attempt_cannot_create_two_orders(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_intent(connection, "intent-1")
        _seed_review(connection, "review-1", "intent-1")
        _seed_submission(connection, "submission-1", "intent-1", "review-1")
        _seed_order(connection, "order-1", "broker-order-1", "submission-1")
        with pytest.raises(sqlite3.IntegrityError):
            _seed_order(connection, "order-2", "broker-order-2", "submission-1")


def test_live_lease_rejects_missing_promotion_evidence_hash(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        connection.execute(
            """
            INSERT INTO promotion_evidence (
                id, stage, eligible, evidence_hash, reason_codes_json,
                evaluated_at, expires_at
            ) VALUES ('promotion-1', 'micro_live', 1, ?, '[]', ?, ?)
            """,
            (HASH_A, UTC_TEXT, PROMOTION_EXPIRES_TEXT),
        )
        connection.execute(
            """
            INSERT INTO live_authorizations (
                id, account_id, stage, activation_nonce, artifact_hash, preflight_hash,
                acknowledgement_hash, config_hash, code_hash, strategy_eligibility_hash,
                promotion_evidence_hash, promotion_eligible, authorized_risk_equity,
                issued_at, expires_at,
                consumed_at, status, evidence_hash, corrects_id
            ) VALUES ('authorization-1', 'account-1', 'micro_live', 'nonce-1', ?, ?, ?, ?, ?, ?,
                      ?, 1, '1000', ?, ?, NULL, 'issued', ?, NULL)
            """,
            (HASH_A, HASH_A, HASH_A, HASH_A, HASH_A, HASH_A, HASH_A, UTC_TEXT, UTC_TEXT, HASH_A),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO live_leases (
                    id, authorization_id, account_id, stage, issued_at, expires_at,
                    revoked_at, revocation_reason, authorized_risk_equity, config_hash,
                    code_hash, strategy_eligibility_hash, promotion_evidence_hash,
                    evidence_hash
                ) VALUES ('live-lease-1', 'authorization-1', 'account-1', 'micro_live', ?, ?,
                          NULL, NULL, '1000', ?, ?, ?, ?, ?)
                """,
                (UTC_TEXT, UTC_TEXT, HASH_A, HASH_A, HASH_A, HASH_B, HASH_A),
            )


def test_live_authorization_rejects_a_nonlive_stage(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        connection.execute(
            """
            INSERT INTO promotion_evidence (
                id, stage, eligible, evidence_hash, reason_codes_json,
                evaluated_at, expires_at
            ) VALUES ('promotion-paper', 'paper', 1, ?, '[]', ?, ?)
            """,
            (HASH_A, UTC_TEXT, PROMOTION_EXPIRES_TEXT),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO live_authorizations (
                    id, account_id, stage, activation_nonce, artifact_hash, preflight_hash,
                    acknowledgement_hash, config_hash, code_hash, strategy_eligibility_hash,
                    promotion_evidence_hash, promotion_eligible, authorized_risk_equity,
                    issued_at, expires_at, consumed_at, status, evidence_hash, corrects_id
                ) VALUES ('authorization-paper', 'account-1', 'paper', 'nonce-paper',
                          ?, ?, ?, ?, ?, ?, ?, 1, '100', ?, ?, NULL, 'issued', ?, NULL)
                """,
                (
                    HASH_A,
                    HASH_A,
                    HASH_A,
                    HASH_A,
                    HASH_A,
                    HASH_A,
                    HASH_A,
                    UTC_TEXT,
                    UTC_TEXT,
                    HASH_A,
                ),
            )


@pytest.mark.parametrize(
    (
        "account_id",
        "stage",
        "authorized_risk_equity",
        "config_hash",
        "code_hash",
        "strategy_eligibility_hash",
        "promotion_evidence_hash",
    ),
    [
        ("account-2", "micro_live", "100", HASH_A, HASH_A, HASH_A, HASH_A),
        ("account-1", "normal_live", "100", HASH_A, HASH_A, HASH_A, HASH_A),
        ("account-1", "micro_live", "999", HASH_A, HASH_A, HASH_A, HASH_A),
        ("account-1", "micro_live", "100", HASH_B, HASH_A, HASH_A, HASH_A),
        ("account-1", "micro_live", "100", HASH_A, HASH_B, HASH_A, HASH_A),
        ("account-1", "micro_live", "100", HASH_A, HASH_A, HASH_B, HASH_A),
        ("account-1", "micro_live", "100", HASH_A, HASH_A, HASH_A, HASH_B),
    ],
)
def test_live_lease_identity_must_match_its_authorization(
    alembic_config: Config,
    database_path: Path,
    account_id: str,
    stage: str,
    authorized_risk_equity: str,
    config_hash: str,
    code_hash: str,
    strategy_eligibility_hash: str,
    promotion_evidence_hash: str,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_account(connection, account_id="account-2")
        _seed_promotion_and_authorization(connection)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO live_leases (
                    id, authorization_id, account_id, stage, issued_at, expires_at,
                    revoked_at, revocation_reason, authorized_risk_equity, config_hash,
                    code_hash, strategy_eligibility_hash, promotion_evidence_hash,
                    evidence_hash
                ) VALUES ('live-lease-1', 'authorization-1', ?, ?, ?, ?,
                          NULL, NULL, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_id,
                    stage,
                    UTC_TEXT,
                    UTC_TEXT,
                    authorized_risk_equity,
                    config_hash,
                    code_hash,
                    strategy_eligibility_hash,
                    promotion_evidence_hash,
                    HASH_B,
                ),
            )


@pytest.mark.parametrize(
    ("nonce", "artifact_hash"),
    [("nonce-wrong", HASH_A), ("nonce-right", HASH_B)],
)
def test_used_nonce_identity_must_match_its_authorization(
    alembic_config: Config,
    database_path: Path,
    nonce: str,
    artifact_hash: str,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_promotion_and_authorization(connection)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO used_nonces (nonce, authorization_id, artifact_hash, used_at)
                VALUES (?, 'authorization-1', ?, ?)
                """,
                (nonce, artifact_hash, UTC_TEXT),
            )


def test_consistent_authorization_lease_and_nonce_chain_is_accepted(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_promotion_and_authorization(connection)
        _seed_live_lease(connection)
        connection.execute(
            """
            INSERT INTO used_nonces (nonce, authorization_id, artifact_hash, used_at)
            VALUES ('nonce-right', 'authorization-1', ?, ?)
            """,
            (HASH_A, UTC_TEXT),
        )
        lease_count = connection.execute("SELECT count(*) FROM live_leases").fetchone()
        nonce_count = connection.execute("SELECT count(*) FROM used_nonces").fetchone()

    assert lease_count == (1,)
    assert nonce_count == (1,)


@pytest.mark.parametrize(
    ("stage", "promotion_evidence_hash", "promotion_eligible"),
    [
        ("normal_live", HASH_A, 1),
        ("micro_live", HASH_C, 1),
        ("micro_live", HASH_C, 0),
    ],
)
def test_live_authorization_requires_eligible_same_stage_promotion_evidence(
    alembic_config: Config,
    database_path: Path,
    stage: str,
    promotion_evidence_hash: str,
    promotion_eligible: int,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_promotion_and_authorization(connection)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO live_authorizations (
                    id, account_id, stage, activation_nonce, artifact_hash, preflight_hash,
                    acknowledgement_hash, config_hash, code_hash, strategy_eligibility_hash,
                    promotion_evidence_hash, promotion_eligible, authorized_risk_equity,
                    issued_at, expires_at, consumed_at, status, evidence_hash, corrects_id
                ) VALUES ('authorization-2', 'account-1', ?, 'nonce-2', ?, ?, ?, ?, ?, ?,
                          ?, ?, '100', ?, ?, NULL, 'issued', ?, NULL)
                """,
                (
                    stage,
                    HASH_A,
                    HASH_A,
                    HASH_A,
                    HASH_A,
                    HASH_A,
                    HASH_A,
                    promotion_evidence_hash,
                    promotion_eligible,
                    UTC_TEXT,
                    UTC_TEXT,
                    HASH_A,
                ),
            )


@pytest.mark.parametrize(
    ("provider", "account_id", "instrument_id"),
    [
        ("other-provider", "account-1", "instrument-1"),
        ("provider", "account-2", "instrument-1"),
        ("provider", "account-1", "instrument-2"),
    ],
)
def test_order_scope_must_match_its_intent_and_submission(
    alembic_config: Config,
    database_path: Path,
    provider: str,
    account_id: str,
    instrument_id: str,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_account(connection, account_id="account-2")
        _seed_instrument(connection)
        _seed_instrument(connection, instrument_id="instrument-2")
        _seed_intent(connection, "intent-1")
        _seed_review(connection, "review-1", "intent-1")
        _seed_submission(connection, "submission-1", "intent-1", "review-1")
        with pytest.raises(sqlite3.IntegrityError):
            _seed_order(
                connection,
                "order-1",
                "broker-order-1",
                "submission-1",
                provider=provider,
                account_id=account_id,
                instrument_id=instrument_id,
            )


@pytest.mark.parametrize(
    (
        "side",
        "purpose",
        "order_type",
        "time_in_force",
        "requested_quantity",
        "limit_price",
        "stop_price",
        "client_order_id",
    ),
    [
        ("sell", "entry", "limit", "day", "1", "10", None, None),
        ("buy", "protective_exit", "limit", "day", "1", "10", None, None),
        ("buy", "entry", "market", "day", "1", "10", None, None),
        ("buy", "entry", "limit", "gtc", "1", "10", None, None),
        ("buy", "entry", "limit", "day", "2", "10", None, None),
        ("buy", "entry", "limit", "day", "1", None, None, None),
        ("buy", "entry", "limit", "day", "1", "11", None, None),
        ("buy", "entry", "limit", "day", "1", "10", "9", None),
        ("buy", "entry", "limit", "day", "1", "10", None, "wrong-client-id"),
    ],
)
def test_order_payload_must_match_its_intent_and_review(
    alembic_config: Config,
    database_path: Path,
    side: str,
    purpose: str,
    order_type: str,
    time_in_force: str,
    requested_quantity: str,
    limit_price: str | None,
    stop_price: str | None,
    client_order_id: str | None,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_intent(connection, "intent-1")
        _seed_review(connection, "review-1", "intent-1")
        _seed_submission(connection, "submission-1", "intent-1", "review-1")
        with pytest.raises(sqlite3.IntegrityError):
            _seed_order(
                connection,
                "order-1",
                "broker-order-1",
                "submission-1",
                side=side,
                purpose=purpose,
                order_type=order_type,
                time_in_force=time_in_force,
                requested_quantity=requested_quantity,
                limit_price=limit_price,
                stop_price=stop_price,
                client_order_id=client_order_id,
            )


@pytest.mark.parametrize("payload_field", ["stop_price", "client_order_id"])
def test_order_payload_null_cannot_bypass_nonnull_intent_or_review_identity(
    alembic_config: Config,
    database_path: Path,
    payload_field: str,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_intent(
            connection,
            "intent-1",
            stop_price="9" if payload_field == "stop_price" else None,
        )
        client_order_id = "client-order-1" if payload_field == "client_order_id" else None
        _seed_review(
            connection,
            "review-1",
            "intent-1",
            client_order_id=client_order_id,
        )
        _seed_submission(
            connection,
            "submission-1",
            "intent-1",
            "review-1",
            provider_client_reference=client_order_id,
        )
        with pytest.raises(sqlite3.IntegrityError):
            _seed_order(
                connection,
                "order-1",
                "broker-order-1",
                "submission-1",
                stop_price=None,
                client_order_id=None,
            )


def test_order_accepts_matching_nonnull_stop_and_client_identity(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_intent(connection, "intent-1", stop_price="9")
        _seed_review(
            connection,
            "review-1",
            "intent-1",
            client_order_id="client-order-1",
        )
        _seed_submission(
            connection,
            "submission-1",
            "intent-1",
            "review-1",
            provider_client_reference="client-order-1",
        )
        _seed_order(
            connection,
            "order-1",
            "broker-order-1",
            "submission-1",
            stop_price="9",
            client_order_id="client-order-1",
        )

        stored = connection.execute("SELECT stop_price, client_order_id FROM orders").fetchone()

    assert stored == ("9", "client-order-1")


def test_local_order_requires_the_complete_submission_chain(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_intent(connection, "intent-1")
        _seed_review(connection, "review-1", "intent-1")
        with pytest.raises(sqlite3.IntegrityError):
            _seed_order(connection, "order-1", "broker-order-1", None)


def test_reconciled_external_order_allows_no_local_submission_chain(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_order(
            connection,
            "external-order-1",
            "broker-order-1",
            None,
            intent_id=None,
            review_id=None,
        )
        stored = connection.execute(
            "SELECT intent_id, review_id, submission_attempt_id FROM orders"
        ).fetchone()

    assert stored == (None, None, None)


@pytest.mark.parametrize(
    ("provider", "account_id", "instrument_id"),
    [
        ("wrong-provider", "account-1", "instrument-1"),
        ("provider", "account-other", "instrument-1"),
        ("provider", "account-1", "instrument-other"),
    ],
)
def test_reconciled_external_order_provider_must_match_account_and_instrument(
    alembic_config: Config,
    database_path: Path,
    provider: str,
    account_id: str,
    instrument_id: str,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_account(connection, account_id="account-other", provider="other-provider")
        _seed_instrument(connection)
        _seed_instrument(connection, instrument_id="instrument-other", provider="other-provider")

        with pytest.raises(sqlite3.IntegrityError):
            _seed_order(
                connection,
                "external-order-1",
                "broker-order-1",
                None,
                intent_id=None,
                review_id=None,
                provider=provider,
                account_id=account_id,
                instrument_id=instrument_id,
            )


def test_transition_intent_must_match_its_order(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_intent(connection, "intent-1")
        _seed_intent(connection, "intent-2")
        _seed_review(connection, "review-1", "intent-1")
        _seed_submission(connection, "submission-1", "intent-1", "review-1")
        _seed_order(connection, "order-1", "broker-order-1", "submission-1")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO order_transitions (
                    id, intent_id, order_id, from_state, event, to_state, actor,
                    reason_code, occurred_at, config_hash, correlation_id, corrects_id
                ) VALUES ('transition-1', 'intent-2', 'order-1', NULL, 'accepted',
                          'submitted', 'broker', 'accepted', ?, ?, 'correlation-1', NULL)
                """,
                (UTC_TEXT, HASH_A),
            )


@pytest.mark.parametrize(
    ("provider", "broker_order_id", "account_id", "instrument_id", "side"),
    [
        ("other-provider", "broker-order-1", "account-1", "instrument-1", "buy"),
        ("provider", "other-broker-order", "account-1", "instrument-1", "buy"),
        ("provider", "broker-order-1", "account-2", "instrument-1", "buy"),
        ("provider", "broker-order-1", "account-1", "instrument-2", "buy"),
        ("provider", "broker-order-1", "account-1", "instrument-1", "sell"),
    ],
)
def test_fill_scope_must_match_its_order(
    alembic_config: Config,
    database_path: Path,
    provider: str,
    broker_order_id: str,
    account_id: str,
    instrument_id: str,
    side: str,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_account(connection, account_id="account-2")
        _seed_instrument(connection)
        _seed_instrument(connection, instrument_id="instrument-2")
        _seed_intent(connection, "intent-1")
        _seed_review(connection, "review-1", "intent-1")
        _seed_submission(connection, "submission-1", "intent-1", "review-1")
        _seed_order(connection, "order-1", "broker-order-1", "submission-1")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO fills (
                    id, order_id, provider, external_execution_key, broker_order_id,
                    account_id, instrument_id, side, quantity, price, fee, occurred_at,
                    occurrence_ordinal, data_hash
                ) VALUES ('fill-1', 'order-1', ?, 'execution-1',
                          ?, ?, ?, ?,
                          '1', '10', '0', ?, 0, ?)
                """,
                (
                    provider,
                    broker_order_id,
                    account_id,
                    instrument_id,
                    side,
                    UTC_TEXT,
                    HASH_A,
                ),
            )


def test_consistent_order_transition_and_fill_chain_is_accepted(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_intent(connection, "intent-1")
        _seed_review(connection, "review-1", "intent-1")
        _seed_submission(connection, "submission-1", "intent-1", "review-1")
        _seed_order(connection, "order-1", "broker-order-1", "submission-1")
        connection.execute(
            """
            INSERT INTO order_transitions (
                id, intent_id, order_id, from_state, event, to_state, actor,
                reason_code, occurred_at, config_hash, correlation_id, corrects_id
            ) VALUES ('transition-1', 'intent-1', 'order-1', NULL, 'accepted',
                      'submitted', 'broker', 'accepted', ?, ?, 'correlation-1', NULL)
            """,
            (UTC_TEXT, HASH_A),
        )
        connection.execute(
            """
            INSERT INTO fills (
                id, order_id, provider, external_execution_key, broker_order_id,
                account_id, instrument_id, side, quantity, price, fee, occurred_at,
                occurrence_ordinal, data_hash
            ) VALUES ('fill-1', 'order-1', 'provider', 'execution-1',
                      'broker-order-1', 'account-1', 'instrument-1', 'buy',
                      '1', '10', '0', ?, 0, ?)
            """,
            (UTC_TEXT, HASH_A),
        )
        transition_count = connection.execute("SELECT count(*) FROM order_transitions").fetchone()
        fill_count = connection.execute("SELECT count(*) FROM fills").fetchone()

    assert transition_count == (1,)
    assert fill_count == (1,)


@pytest.mark.parametrize(
    ("account_id", "instrument_id"),
    [
        ("account-2", "instrument-1"),
        ("account-1", "instrument-2"),
    ],
)
def test_realized_pnl_scope_must_match_its_fill(
    alembic_config: Config,
    database_path: Path,
    account_id: str,
    instrument_id: str,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_account(connection, account_id="account-2")
        _seed_instrument(connection)
        _seed_instrument(connection, instrument_id="instrument-2")
        _seed_intent(connection, "intent-1")
        _seed_review(connection, "review-1", "intent-1")
        _seed_submission(connection, "submission-1", "intent-1", "review-1")
        _seed_order(connection, "order-1", "broker-order-1", "submission-1")
        _seed_fill(connection)

        with pytest.raises(sqlite3.IntegrityError):
            _seed_realized_pnl(
                connection,
                account_id=account_id,
                instrument_id=instrument_id,
            )


def test_realized_pnl_accepts_matching_fill_and_fill_free_aggregate_events(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_intent(connection, "intent-1")
        _seed_review(connection, "review-1", "intent-1")
        _seed_submission(connection, "submission-1", "intent-1", "review-1")
        _seed_order(connection, "order-1", "broker-order-1", "submission-1")
        _seed_fill(connection)
        _seed_realized_pnl(connection)
        _seed_realized_pnl(
            connection,
            pnl_id="pnl-aggregate",
            instrument_id=None,
            fill_id=None,
        )

        rows = connection.execute("SELECT id, fill_id FROM realized_pnl ORDER BY id").fetchall()

    assert rows == [("pnl-1", "fill-1"), ("pnl-aggregate", None)]


def test_realized_pnl_fill_requires_an_instrument_identity(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_intent(connection, "intent-1")
        _seed_review(connection, "review-1", "intent-1")
        _seed_submission(connection, "submission-1", "intent-1", "review-1")
        _seed_order(connection, "order-1", "broker-order-1", "submission-1")
        _seed_fill(connection)

        with pytest.raises(sqlite3.IntegrityError):
            _seed_realized_pnl(connection, instrument_id=None)


def test_position_snapshot_membership_must_match_the_position_account(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_account(connection, account_id="account-2")
        _seed_instrument(connection)
        _seed_portfolio_snapshot(connection)

        with pytest.raises(sqlite3.IntegrityError):
            _seed_position(connection, account_id="account-2")


def test_position_accepts_matching_or_absent_snapshot_membership(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_portfolio_snapshot(connection)
        _seed_position(connection)
        _seed_position(
            connection,
            position_id="position-unlinked",
            portfolio_snapshot_id=None,
        )

        rows = connection.execute(
            "SELECT id, portfolio_snapshot_id FROM positions ORDER BY id"
        ).fetchall()

    assert rows == [("position-1", "snapshot-1"), ("position-unlinked", None)]


def test_historical_foreign_keys_do_not_cascade_delete(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")
    with _inspect_database(database_path) as inspector:
        for table_name in REQUIRED_TABLES:
            for foreign_key in inspector.get_foreign_keys(table_name):
                ondelete = foreign_key.get("options", {}).get("ondelete")
                assert ondelete is None or str(ondelete).upper() == "RESTRICT", table_name


def test_downgrade_cleanup_covers_every_self_referencing_correction_table(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")
    with _inspect_database(database_path) as inspector:
        self_referencing_tables = {
            table_name
            for table_name in REQUIRED_TABLES
            for foreign_key in inspector.get_foreign_keys(table_name)
            if foreign_key["referred_table"] == table_name
            and foreign_key["constrained_columns"] == ["corrects_id"]
        }

    revision = ScriptDirectory.from_config(alembic_config).get_revision("0001_core_ledger")
    assert revision is not None
    cleanup_tables = cast(tuple[str, ...], revision.module.CORRECTION_TABLES)
    assert set(cleanup_tables) == self_referencing_tables


def test_submission_attempts_store_no_raw_provider_response(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")
    with _inspect_database(database_path) as inspector:
        columns = {column["name"] for column in inspector.get_columns("submission_attempts")}
    forbidden = {
        "authorization_header",
        "private_key",
        "raw_payload",
        "raw_response",
        "response_body",
        "secret",
    }

    assert columns.isdisjoint(forbidden)
    assert "sanitized_response_hash" in columns


def test_upgrade_head_is_idempotent(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")
    with _inspect_database(database_path) as inspector:
        first_inventory = set(inspector.get_table_names())
    command.upgrade(alembic_config, "head")
    with _inspect_database(database_path) as inspector:
        second_inventory = set(inspector.get_table_names())

    assert second_inventory == first_inventory


def test_failed_upgrade_rolls_back_all_schema_changes_and_can_retry(
    alembic_config: Config,
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_create_table = Operations.create_table
    create_count = 0

    def fail_on_third_table(
        operations: Operations,
        table_name: str,
        *columns: SchemaItem,
        if_not_exists: bool | None = None,
        **kwargs: Any,
    ) -> sa.Table:
        nonlocal create_count
        create_count += 1
        if create_count == 3:
            raise RuntimeError("injected upgrade failure")
        return original_create_table(
            operations,
            table_name,
            *columns,
            if_not_exists=if_not_exists,
            **kwargs,
        )

    with monkeypatch.context() as scoped_patch:
        scoped_patch.setattr(Operations, "create_table", fail_on_third_table)
        with pytest.raises(RuntimeError, match="injected upgrade failure"):
            command.upgrade(alembic_config, "head")

    with _inspect_database(database_path) as inspector:
        table_names = set(inspector.get_table_names())
        assert REQUIRED_TABLES.isdisjoint(table_names)
        if "alembic_version" in table_names:
            with closing(sqlite3.connect(database_path)) as connection:
                assert (
                    connection.execute("SELECT version_num FROM alembic_version").fetchone() is None
                )

    command.upgrade(alembic_config, "head")
    with _inspect_database(database_path) as inspector:
        assert set(inspector.get_table_names()) >= REQUIRED_TABLES


def test_failed_downgrade_restores_all_schema_changes_and_can_retry(
    alembic_config: Config,
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command.upgrade(alembic_config, "head")
    with closing(_connect(database_path)) as connection:
        _seed_audit_correction(connection)
        connection.commit()
    original_drop_table = Operations.drop_table
    drop_count = 0

    def fail_on_third_table(
        operations: Operations,
        table_name: str,
        *,
        schema: str | None = None,
        if_exists: bool | None = None,
        **kwargs: Any,
    ) -> None:
        nonlocal drop_count
        drop_count += 1
        if drop_count == 3:
            raise RuntimeError("injected downgrade failure")
        original_drop_table(
            operations,
            table_name,
            schema=schema,
            if_exists=if_exists,
            **kwargs,
        )

    with monkeypatch.context() as scoped_patch:
        scoped_patch.setattr(Operations, "drop_table", fail_on_third_table)
        with pytest.raises(RuntimeError, match="injected downgrade failure"):
            command.downgrade(alembic_config, "base")

    with _inspect_database(database_path) as inspector:
        assert set(inspector.get_table_names()) >= REQUIRED_TABLES
    with closing(sqlite3.connect(database_path)) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        correction = connection.execute(
            "SELECT corrects_id FROM audit_events WHERE id = 'audit-2'"
        ).fetchone()
    assert revision == ("0004_promotion_observations",)
    assert correction == ("audit-1",)

    command.downgrade(alembic_config, "base")
    with _inspect_database(database_path) as inspector:
        assert REQUIRED_TABLES.isdisjoint(inspector.get_table_names())


def test_downgrade_handles_populated_foreign_key_graph(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")
    with closing(_connect(database_path)) as connection:
        _seed_account(connection)
        _seed_instrument(connection)
        _seed_promotion_and_authorization(connection)
        _seed_live_lease(connection)
        _seed_intent(connection, "intent-1")
        _seed_review(connection, "review-1", "intent-1")
        _seed_submission(
            connection,
            "submission-1",
            "intent-1",
            "review-1",
            execution_mode="micro_live",
            live_lease_id="live-lease-1",
            live_lease_evidence_hash=HASH_B,
        )
        _seed_order(connection, "order-1", "broker-order-1", "submission-1")
        _seed_fill(connection)
        _seed_realized_pnl(connection)
        _seed_portfolio_snapshot(connection)
        _seed_position(connection)
        _seed_audit_correction(connection)
        connection.commit()

    command.downgrade(alembic_config, "base")
    with _inspect_database(database_path) as inspector:
        assert REQUIRED_TABLES.isdisjoint(inspector.get_table_names())


def test_downgrade_and_reupgrade_round_trip(
    alembic_config: Config,
    database_path: Path,
) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")
    with _inspect_database(database_path) as inspector:
        assert REQUIRED_TABLES.isdisjoint(inspector.get_table_names())

    command.upgrade(alembic_config, "head")
    with _inspect_database(database_path) as inspector:
        assert set(inspector.get_table_names()) >= REQUIRED_TABLES
