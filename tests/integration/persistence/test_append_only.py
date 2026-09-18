"""Integration contract for database-enforced append-only critical events."""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from trading_bot.persistence import async_session_factory
from trading_bot.persistence.models import AuditEventRow

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
UTC_TEXT = "2026-07-14T12:00:00.000000Z"

PROTECTED_TABLES = (
    "audit_events",
    "order_transitions",
    "risk_evaluations",
    "configuration_versions",
    "live_authorizations",
    "kill_switch_events",
    "reconciliation_events",
)
PROMOTION_TRIGGER_COUNT = 10
RESEARCH_TRIGGER_COUNT = 5
OPTIONS_TRIAL_TRIGGER_COUNT = 4

ROW_IDS = {table_name: f"{table_name}-1" for table_name in PROTECTED_TABLES}


def _connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _seed_protected_rows(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO accounts (
            id, provider, provider_account_id, account_type, provider_state,
            equity, cash, equity_buying_power, crypto_buying_power,
            prediction_buying_power, restricted, observed_at, data_hash,
            config_hash, code_hash
        ) VALUES ('account-1', 'paper', 'paper-account-1', 'cash', 'active',
                  '1000', '1000', '1000', NULL, NULL, 0, ?, ?, ?, ?)
        """,
        (UTC_TEXT, HASH_A, HASH_B, HASH_C),
    )
    connection.execute(
        """
        INSERT INTO instruments (
            id, provider, provider_instrument_id, symbol, asset_class,
            provider_status, tradable, fractional_eligible, price_increment,
            quantity_increment, minimum_quantity, minimum_notional,
            maximum_quantity, correlation_group, observed_at, data_hash
        ) VALUES ('instrument-1', 'paper', 'paper-instrument-1', 'TEST', 'equity',
                  'active', 1, 1, '0.01', '0.01', '0.01', '1', NULL,
                  'equity:TEST', ?, ?)
        """,
        (UTC_TEXT, HASH_A),
    )
    connection.execute(
        """
        INSERT INTO order_intents (
            id, account_id, instrument_id, strategy_decision_id, asset_class,
            side, purpose, order_type, time_in_force, quantity, limit_price,
            stop_price, created_at, expires_at, strategy_version, config_hash,
            code_hash, data_hash, exit_policy_version
        ) VALUES ('intent-1', 'account-1', 'instrument-1', NULL, 'equity',
                  'buy', 'entry', 'limit', 'good_for_day', '1', '10', NULL, ?,
                  '2026-07-14T12:05:00.000000Z', 'strategy-v1', ?, ?, ?, 'exit-v1')
        """,
        (UTC_TEXT, HASH_A, HASH_B, HASH_C),
    )
    connection.execute(
        """
        INSERT INTO promotion_evidence (
            id, stage, eligible, evidence_hash, reason_codes_json,
            evaluated_at, expires_at
        ) VALUES ('promotion-1', 'micro_live', 1, ?, '[]', ?,
                  '2026-07-14T12:05:00.000000Z')
        """,
        (HASH_B, UTC_TEXT),
    )
    connection.execute(
        """
        INSERT INTO audit_events (
            id, occurred_at, category, actor, reason_code, correlation_id,
            config_hash, code_hash, data_hash, sanitized_details_json, corrects_id
        ) VALUES (?, ?, 'persistence', 'test', 'seed', 'correlation-1',
                  ?, ?, ?, '[]', NULL)
        """,
        (ROW_IDS["audit_events"], UTC_TEXT, HASH_A, HASH_B, HASH_C),
    )
    connection.execute(
        """
        INSERT INTO order_transitions (
            id, intent_id, order_id, from_state, event, to_state, actor,
            reason_code, occurred_at, config_hash, correlation_id, corrects_id
        ) VALUES (?, 'intent-1', NULL, NULL, 'risk_allow', 'risk_approved',
                  'test', 'seed', ?, ?, 'correlation-1', NULL)
        """,
        (ROW_IDS["order_transitions"], UTC_TEXT, HASH_A),
    )
    connection.execute(
        """
        INSERT INTO risk_evaluations (
            id, intent_id, phase, allowed, check_count, checks_json,
            evaluated_at, config_hash, corrects_id
        ) VALUES (?, 'intent-1', 'preliminary', 1, 1, '[]', ?, ?, NULL)
        """,
        (ROW_IDS["risk_evaluations"], UTC_TEXT, HASH_A),
    )
    connection.execute(
        """
        INSERT INTO configuration_versions (
            id, config_hash, code_hash, created_at, source,
            canonical_nonsecret_config_json, corrects_id
        ) VALUES (?, ?, ?, ?, 'test', '{}', NULL)
        """,
        (ROW_IDS["configuration_versions"], HASH_A, HASH_B, UTC_TEXT),
    )
    connection.execute(
        """
        INSERT INTO live_authorizations (
            id, account_id, stage, activation_nonce, artifact_hash,
            preflight_hash, acknowledgement_hash, config_hash, code_hash,
            strategy_eligibility_hash, promotion_evidence_hash,
            promotion_eligible, authorized_risk_equity, issued_at, expires_at,
            consumed_at, status, evidence_hash, corrects_id
        ) VALUES (?, 'account-1', 'micro_live', 'nonce-1', ?, ?, ?, ?, ?, ?, ?,
                  1, '100', ?, '2026-07-14T12:05:00.000000Z', NULL,
                  'issued', ?, NULL)
        """,
        (
            ROW_IDS["live_authorizations"],
            HASH_A,
            HASH_A,
            HASH_A,
            HASH_A,
            HASH_A,
            HASH_A,
            HASH_B,
            UTC_TEXT,
            HASH_C,
        ),
    )
    connection.execute(
        """
        INSERT INTO kill_switch_events (
            id, action, occurred_at, actor, reason, acknowledgement_hash,
            evidence_hash, correlation_id, config_hash, code_hash, corrects_id
        ) VALUES (?, 'activate', ?, 'test', 'seed', NULL, ?, 'correlation-1',
                  ?, ?, NULL)
        """,
        (ROW_IDS["kill_switch_events"], UTC_TEXT, HASH_C, HASH_A, HASH_B),
    )
    connection.execute(
        """
        INSERT INTO reconciliation_events (
            id, reconciliation_id, account_id, clean, drift_count,
            differences_json, observed_at, evidence_hash, config_hash,
            code_hash, corrects_id
        ) VALUES (?, 'reconciliation-1', 'account-1', 1, 0, '[]', ?, ?, ?, ?, NULL)
        """,
        (ROW_IDS["reconciliation_events"], UTC_TEXT, HASH_C, HASH_A, HASH_B),
    )
    connection.commit()


def _ordinary_columns(connection: sqlite3.Connection, table_name: str) -> tuple[str, ...]:
    return tuple(
        str(row[1])
        for row in connection.execute(f'PRAGMA table_xinfo("{table_name}")')
        if row[6] == 0
    )


def _copy_row_sql(
    connection: sqlite3.Connection,
    table_name: str,
    *,
    prefix: str,
    replacements: dict[str, str] | None = None,
) -> tuple[str, tuple[str, ...]]:
    replacements = {} if replacements is None else replacements
    columns = _ordinary_columns(connection, table_name)
    projections: list[str] = []
    parameters: list[str] = []
    for column in columns:
        replacement = replacements.get(column)
        if replacement is None:
            projections.append(f'"{column}"')
        else:
            projections.append("?")
            parameters.append(replacement)
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    sql = (
        f'{prefix} INTO "{table_name}" ({quoted_columns}) '
        f'SELECT {", ".join(projections)} FROM "{table_name}" WHERE id = ?'
    )
    return sql, (*parameters, ROW_IDS[table_name])


@pytest.fixture
def migrated_database(alembic_config: Config, database_path: Path) -> Path:
    command.upgrade(alembic_config, "head")
    with closing(_connect(database_path)) as connection:
        _seed_protected_rows(connection)
    return database_path


def test_exact_append_only_trigger_inventory(
    migrated_database: Path,
) -> None:
    expected = {
        f"trg_{table_name}_append_only_{operation}"
        for table_name in PROTECTED_TABLES
        for operation in ("insert", "update", "delete", "rowid")
    }
    with closing(_connect(migrated_database)) as connection:
        actual = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'trigger' AND name LIKE 'trg_%_append_only_%'"
            )
        }
    assert actual == expected


def test_trigger_sql_rejects_identifiers_outside_the_closed_migration_set(
    alembic_config: Config,
) -> None:
    revision = ScriptDirectory.from_config(alembic_config).get_revision("0002_append_only_guards")
    assert revision is not None
    with pytest.raises(ValueError, match="closed migration set"):
        revision.module._insert_guard_sql('audit_events"; DROP TABLE audit_events; --')


@pytest.mark.parametrize("table_name", PROTECTED_TABLES)
def test_protected_rows_reject_update_and_delete(
    migrated_database: Path,
    table_name: str,
) -> None:
    with closing(_connect(migrated_database)) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                f'UPDATE "{table_name}" SET id = id WHERE id = ?',
                (ROW_IDS[table_name],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(f'DELETE FROM "{table_name}" WHERE id = ?', (ROW_IDS[table_name],))
        assert connection.execute(
            f'SELECT count(*) FROM "{table_name}" WHERE id = ?',
            (ROW_IDS[table_name],),
        ).fetchone() == (1,)


@pytest.mark.parametrize("table_name", PROTECTED_TABLES)
@pytest.mark.parametrize("prefix", ["INSERT OR REPLACE", "REPLACE"])
def test_insert_or_replace_cannot_bypass_append_only_guards(
    migrated_database: Path,
    table_name: str,
    prefix: str,
) -> None:
    with closing(_connect(migrated_database)) as connection:
        sql, parameters = _copy_row_sql(
            connection,
            table_name,
            prefix=prefix,
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(sql, parameters)
        assert connection.execute(
            f'SELECT count(*) FROM "{table_name}" WHERE id = ?',
            (ROW_IDS[table_name],),
        ).fetchone() == (1,)


def test_on_conflict_update_cannot_bypass_append_only_guards(
    migrated_database: Path,
) -> None:
    with closing(_connect(migrated_database)) as connection:
        sql, parameters = _copy_row_sql(
            connection,
            "audit_events",
            prefix="INSERT",
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                f"{sql} ON CONFLICT(id) DO UPDATE SET reason_code = 'changed'",
                parameters,
            )
        assert connection.execute(
            "SELECT reason_code FROM audit_events WHERE id = ?",
            (ROW_IDS["audit_events"],),
        ).fetchone() == ("seed",)


@pytest.mark.parametrize(
    ("table_name", "replacements"),
    [
        (
            "configuration_versions",
            {
                "id": "configuration-unique-conflict",
                "corrects_id": ROW_IDS["configuration_versions"],
            },
        ),
        (
            "live_authorizations",
            {
                "id": "authorization-unique-conflict",
                "corrects_id": ROW_IDS["live_authorizations"],
            },
        ),
    ],
)
def test_replace_cannot_delete_a_row_through_a_secondary_unique_key(
    migrated_database: Path,
    table_name: str,
    replacements: dict[str, str],
) -> None:
    with closing(_connect(migrated_database)) as connection:
        sql, parameters = _copy_row_sql(
            connection,
            table_name,
            prefix="REPLACE",
            replacements=replacements,
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(sql, parameters)
        assert connection.execute(
            f'SELECT count(*) FROM "{table_name}" WHERE id = ?',
            (ROW_IDS[table_name],),
        ).fetchone() == (1,)


def test_explicit_negative_rowid_cannot_replace_history_with_recursive_triggers_off(
    migrated_database: Path,
) -> None:
    with closing(_connect(migrated_database)) as connection:
        connection.execute("PRAGMA recursive_triggers=OFF")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                """
                INSERT INTO audit_events (
                    rowid, id, occurred_at, category, actor, reason_code,
                    correlation_id, config_hash, code_hash, data_hash,
                    sanitized_details_json, corrects_id
                ) VALUES (-1, 'negative-rowid', ?, 'test', 'test', 'negative-rowid',
                          'correlation-negative', ?, ?, ?, '[]', NULL)
                """,
                (UTC_TEXT, HASH_A, HASH_B, HASH_C),
            )
        assert connection.execute(
            "SELECT count(*) FROM audit_events WHERE id = ?",
            (ROW_IDS["audit_events"],),
        ).fetchone() == (1,)


@pytest.mark.parametrize("table_name", PROTECTED_TABLES)
def test_corrections_append_without_mutating_original(
    migrated_database: Path,
    table_name: str,
) -> None:
    correction_id = f"{table_name}-2"
    replacements = {"id": correction_id, "corrects_id": ROW_IDS[table_name]}
    if table_name == "configuration_versions":
        replacements["config_hash"] = HASH_D
    if table_name == "live_authorizations":
        replacements["activation_nonce"] = "nonce-2"

    with closing(_connect(migrated_database)) as connection:
        sql, parameters = _copy_row_sql(
            connection,
            table_name,
            prefix="INSERT",
            replacements=replacements,
        )
        connection.execute(sql, parameters)
        connection.commit()
        rows = connection.execute(
            f'SELECT id, corrects_id FROM "{table_name}" ORDER BY id'
        ).fetchall()
    assert rows == [(ROW_IDS[table_name], None), (correction_id, ROW_IDS[table_name])]


@pytest.mark.parametrize("table_name", PROTECTED_TABLES)
@pytest.mark.parametrize("target", ["self", "missing"])
def test_correction_target_must_be_a_distinct_existing_row(
    migrated_database: Path,
    table_name: str,
    target: str,
) -> None:
    correction_id = f"{table_name}-2"
    corrects_id = correction_id if target == "self" else "missing-row"
    replacements = {"id": correction_id, "corrects_id": corrects_id}
    if table_name == "configuration_versions":
        replacements["config_hash"] = HASH_D
    if table_name == "live_authorizations":
        replacements["activation_nonce"] = "nonce-2"

    with closing(_connect(migrated_database)) as connection:
        sql, parameters = _copy_row_sql(
            connection,
            table_name,
            prefix="INSERT",
            replacements=replacements,
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(sql, parameters)


def test_append_only_rejection_rolls_back_the_whole_transaction(
    migrated_database: Path,
) -> None:
    with closing(_connect(migrated_database)) as connection:
        connection.execute("BEGIN")
        connection.execute(
            """
            INSERT INTO audit_events (
                id, occurred_at, category, actor, reason_code, correlation_id,
                config_hash, code_hash, data_hash, sanitized_details_json, corrects_id
            ) VALUES ('audit-events-staged', ?, 'test', 'test', 'staged',
                      'correlation-staged', ?, ?, ?, '[]', NULL)
            """,
            (UTC_TEXT, HASH_A, HASH_B, HASH_C),
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE audit_events SET reason_code = 'changed' WHERE id = ?",
                (ROW_IDS["audit_events"],),
            )
        assert connection.execute(
            "SELECT count(*) FROM audit_events WHERE id = 'audit-events-staged'"
        ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_orm_update_is_rejected_by_database_trigger(
    migrated_database: Path,
    sqlite_engine: AsyncEngine,
) -> None:
    del migrated_database
    factory = async_session_factory(sqlite_engine)
    with pytest.raises(IntegrityError, match="append-only"):
        async with factory.begin() as session:
            await session.execute(
                update(AuditEventRow)
                .where(AuditEventRow.id == ROW_IDS["audit_events"])
                .values(reason_code="changed")
            )


def test_downgrade_and_reupgrade_remove_and_restore_guards(
    alembic_config: Config,
    migrated_database: Path,
) -> None:
    command.downgrade(alembic_config, "0001_core_ledger")
    with closing(_connect(migrated_database)) as connection:
        trigger_count = connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type = 'trigger'"
        ).fetchone()
        audit_count = connection.execute("SELECT count(*) FROM audit_events").fetchone()
    assert trigger_count == (0,)
    assert audit_count == (1,)

    command.upgrade(alembic_config, "head")
    with closing(_connect(migrated_database)) as connection:
        trigger_count = connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type = 'trigger'"
        ).fetchone()
    assert trigger_count == (
        len(PROTECTED_TABLES) * 4
        + 2
        + PROMOTION_TRIGGER_COUNT
        + RESEARCH_TRIGGER_COUNT
        + OPTIONS_TRIAL_TRIGGER_COUNT,
    )


def test_failed_trigger_upgrade_is_atomic_and_retryable(
    alembic_config: Config,
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command.upgrade(alembic_config, "0001_core_ledger")
    original_execute = Operations.execute
    create_count = 0

    def fail_during_trigger_creation(
        operations: Operations,
        sqltext: Any,
        *,
        execution_options: dict[str, Any] | None = None,
    ) -> None:
        nonlocal create_count
        if type(sqltext) is str and "CREATE TRIGGER" in sqltext:
            create_count += 1
            if create_count == 5:
                raise RuntimeError("injected trigger upgrade failure")
        original_execute(operations, sqltext, execution_options=execution_options)

    with monkeypatch.context() as scoped_patch:
        scoped_patch.setattr(Operations, "execute", fail_during_trigger_creation)
        with pytest.raises(RuntimeError, match="injected trigger upgrade failure"):
            command.upgrade(alembic_config, "head")

    with closing(_connect(database_path)) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        trigger_count = connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type = 'trigger'"
        ).fetchone()
    assert revision == ("0001_core_ledger",)
    assert trigger_count == (0,)

    command.upgrade(alembic_config, "head")
    with closing(_connect(database_path)) as connection:
        trigger_count = connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type = 'trigger'"
        ).fetchone()
    assert trigger_count == (
        len(PROTECTED_TABLES) * 4
        + 2
        + PROMOTION_TRIGGER_COUNT
        + RESEARCH_TRIGGER_COUNT
        + OPTIONS_TRIAL_TRIGGER_COUNT,
    )


def test_failed_trigger_downgrade_is_atomic_and_retryable(
    alembic_config: Config,
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command.upgrade(alembic_config, "head")
    original_execute = Operations.execute
    drop_count = 0

    def fail_during_trigger_removal(
        operations: Operations,
        sqltext: Any,
        *,
        execution_options: dict[str, Any] | None = None,
    ) -> None:
        nonlocal drop_count
        if type(sqltext) is str and "DROP TRIGGER" in sqltext:
            drop_count += 1
            if drop_count == 5:
                raise RuntimeError("injected trigger downgrade failure")
        original_execute(operations, sqltext, execution_options=execution_options)

    with monkeypatch.context() as scoped_patch:
        scoped_patch.setattr(Operations, "execute", fail_during_trigger_removal)
        with pytest.raises(RuntimeError, match="injected trigger downgrade failure"):
            command.downgrade(alembic_config, "0001_core_ledger")

    with closing(_connect(database_path)) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        trigger_count = connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type = 'trigger'"
        ).fetchone()
    assert revision == ("0006_options_trial_history",)
    assert trigger_count == (
        len(PROTECTED_TABLES) * 4
        + 2
        + PROMOTION_TRIGGER_COUNT
        + RESEARCH_TRIGGER_COUNT
        + OPTIONS_TRIAL_TRIGGER_COUNT,
    )

    command.downgrade(alembic_config, "0001_core_ledger")
    with closing(_connect(database_path)) as connection:
        trigger_count = connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type = 'trigger'"
        ).fetchone()
    assert trigger_count == (0,)
