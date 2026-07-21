"""Add append-only identity-bound promotion cycle observations.

Revision ID: 0004_promotion_observations
Revises: 0003_submission_attempt_guards
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_promotion_observations"
down_revision: str | Sequence[str] | None = "0003_submission_attempt_guards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "promotion_observations"
_EVIDENCE_TABLE = "promotion_evidence"
_HASH_LENGTH = 64
_ID_LENGTH = 255
_NAME_LENGTH = 128


def _hash(name: str) -> sa.Column[str]:
    return sa.Column(
        name,
        sa.String(length=_HASH_LENGTH),
        sa.CheckConstraint(
            f"typeof({name}) = 'text' AND length({name}) = {_HASH_LENGTH} "
            f"AND length(CAST({name} AS BLOB)) = {_HASH_LENGTH} "
            f"AND {name} NOT GLOB '*[^0-9a-f]*'",
            name=op.f(f"ck_{_TABLE}_{name}_sha256"),
        ),
        nullable=False,
    )


def _boolean(name: str) -> sa.Column[int]:
    return sa.Column(
        name,
        sa.BLOB(),
        sa.CheckConstraint(
            f"typeof({name}) = 'integer' AND {name} IN (0, 1)",
            name=op.f(f"ck_{_TABLE}_{name}_exact_boolean"),
        ),
        nullable=False,
    )


def _utc(name: str) -> sa.Column[str]:
    pattern = (
        "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T"
        "[0-9][0-9]:[0-9][0-9]:[0-9][0-9]."
        "[0-9][0-9][0-9][0-9][0-9][0-9]Z"
    )
    normalized = f"strftime('%Y-%m-%dT%H:%M:%S', {name})"
    expression = (
        f"typeof({name}) = 'text' AND length({name}) = 27 "
        f"AND length(CAST({name} AS BLOB)) = 27 "
        f"AND {name} GLOB '{pattern}' "
        f"AND substr({name}, 1, 4) <> '0000' "
        f"AND substr({name}, 12, 2) BETWEEN '00' AND '23' "
        f"AND {normalized} IS NOT NULL "
        f"AND {normalized} = substr({name}, 1, 19)"
    )
    return sa.Column(
        name,
        sa.Text(),
        sa.CheckConstraint(expression, name=op.f(f"ck_{_TABLE}_{name}_canonical_utc")),
        nullable=False,
    )


def _append_only_trigger(table_name: str, operation: str) -> str:
    if table_name not in {_TABLE, _EVIDENCE_TABLE}:
        raise ValueError("append-only promotion table is unknown")
    if operation not in {"insert", "update", "delete", "rowid"}:
        raise ValueError("append-only promotion operation is unknown")
    return f"trg_{table_name}_immutable_{operation}"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(length=_ID_LENGTH), nullable=False),
        sa.Column("stage", sa.String(length=_NAME_LENGTH), nullable=False),
        _hash("cycle_id"),
        _hash("account_fingerprint"),
        _hash("provider_evidence_hash"),
        sa.Column("strategy_version", sa.String(length=_NAME_LENGTH), nullable=False),
        _hash("strategy_eligibility_hash"),
        _hash("config_hash"),
        _hash("code_hash"),
        _hash("data_hash"),
        _utc("started_at"),
        _utc("completed_at"),
        _boolean("identity_verified"),
        _boolean("provider_evidence_verified"),
        _boolean("strategy_eligible"),
        _boolean("authenticated_reads"),
        _boolean("data_validated"),
        _boolean("outcomes_complete"),
        _boolean("reconciliation_clean"),
        _boolean("fixture_data"),
        _boolean("runtime_scope_valid"),
        _boolean("order_state_known"),
        _boolean("eligible"),
        sa.Column("reason_codes_json", sa.Text(), nullable=False),
        _hash("evidence_hash"),
        sa.CheckConstraint(
            "stage IN ('paper', 'shadow', 'micro_live', 'normal_live')",
            name=op.f(f"ck_{_TABLE}_stage_known"),
        ),
        sa.CheckConstraint(
            "completed_at >= started_at",
            name=op.f(f"ck_{_TABLE}_completion_ordered"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TABLE}")),
        sa.UniqueConstraint(
            "evidence_hash",
            name=op.f(f"uq_{_TABLE}_evidence_hash"),
        ),
        sa.UniqueConstraint(
            "stage",
            "cycle_id",
            name=op.f(f"uq_{_TABLE}_stage_cycle_id"),
        ),
    )

    op.execute(
        f"""
        CREATE TRIGGER "{_append_only_trigger(_TABLE, 'insert')}"
        BEFORE INSERT ON "{_TABLE}"
        WHEN EXISTS (SELECT 1 FROM "{_TABLE}" WHERE id = NEW.id)
          OR EXISTS (
              SELECT 1 FROM "{_TABLE}"
              WHERE stage = NEW.stage AND cycle_id = NEW.cycle_id
          )
          OR EXISTS (SELECT 1 FROM "{_TABLE}" WHERE evidence_hash = NEW.evidence_hash)
          OR (
              NEW.rowid != -1
              AND EXISTS (SELECT 1 FROM "{_TABLE}" WHERE rowid = NEW.rowid)
          )
        BEGIN
            SELECT RAISE(ROLLBACK, 'append-only insert rejected');
        END
        """
    )
    for operation in ("update", "delete"):
        op.execute(
            f"""
            CREATE TRIGGER "{_append_only_trigger(_TABLE, operation)}"
            BEFORE {operation.upper()} ON "{_TABLE}"
            BEGIN
                SELECT RAISE(ROLLBACK, 'append-only {operation} rejected');
            END
            """
        )
    op.execute(
        f"""
        CREATE TRIGGER "{_append_only_trigger(_TABLE, 'rowid')}"
        AFTER INSERT ON "{_TABLE}"
        WHEN NEW.rowid = -1
        BEGIN
            SELECT RAISE(ROLLBACK, 'append-only rowid rejected');
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER "trg_{_TABLE}_eligibility_insert"
        BEFORE INSERT ON "{_TABLE}"
        WHEN json_valid(NEW.reason_codes_json) = 0
          OR json_type(NEW.reason_codes_json) != 'array'
          OR NEW.eligible != (
              NEW.identity_verified
              AND NEW.provider_evidence_verified
              AND NEW.strategy_eligible
              AND (
                  NEW.stage = 'paper'
                  OR NEW.authenticated_reads
              )
              AND NEW.data_validated
              AND NEW.outcomes_complete
              AND NEW.reconciliation_clean
              AND NOT NEW.fixture_data
              AND NEW.runtime_scope_valid
              AND NEW.order_state_known
          )
          OR (NEW.eligible AND NEW.reason_codes_json != '[]')
          OR (NOT NEW.eligible AND NEW.reason_codes_json = '[]')
        BEGIN
            SELECT RAISE(ROLLBACK, 'promotion observation eligibility rejected');
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER "{_append_only_trigger(_EVIDENCE_TABLE, 'insert')}"
        BEFORE INSERT ON "{_EVIDENCE_TABLE}"
        WHEN EXISTS (
              SELECT 1 FROM "{_EVIDENCE_TABLE}" WHERE id = NEW.id
          )
          OR EXISTS (
              SELECT 1 FROM "{_EVIDENCE_TABLE}"
              WHERE evidence_hash = NEW.evidence_hash
          )
          OR (
              NEW.rowid != -1
              AND EXISTS (
                  SELECT 1 FROM "{_EVIDENCE_TABLE}" WHERE rowid = NEW.rowid
              )
          )
        BEGIN
            SELECT RAISE(ROLLBACK, 'append-only insert rejected');
        END
        """
    )
    for operation in ("update", "delete"):
        op.execute(
            f"""
            CREATE TRIGGER "{_append_only_trigger(_EVIDENCE_TABLE, operation)}"
            BEFORE {operation.upper()} ON "{_EVIDENCE_TABLE}"
            BEGIN
                SELECT RAISE(ROLLBACK, 'append-only {operation} rejected');
            END
            """
        )
    op.execute(
        f"""
        CREATE TRIGGER "{_append_only_trigger(_EVIDENCE_TABLE, 'rowid')}"
        AFTER INSERT ON "{_EVIDENCE_TABLE}"
        WHEN NEW.rowid = -1
        BEGIN
            SELECT RAISE(ROLLBACK, 'append-only rowid rejected');
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER "trg_{_EVIDENCE_TABLE}_valid_insert"
        BEFORE INSERT ON "{_EVIDENCE_TABLE}"
        WHEN NEW.stage NOT IN ('paper', 'shadow', 'micro_live', 'normal_live')
          OR typeof(NEW.eligible) != 'integer'
          OR NEW.eligible NOT IN (0, 1)
          OR json_valid(NEW.reason_codes_json) = 0
          OR json_type(NEW.reason_codes_json) != 'array'
          OR (NEW.eligible AND NEW.reason_codes_json != '[]')
          OR (NOT NEW.eligible AND NEW.reason_codes_json = '[]')
          OR NEW.expires_at <= NEW.evaluated_at
        BEGIN
            SELECT RAISE(ROLLBACK, 'promotion evidence rejected');
        END
        """
    )


def downgrade() -> None:
    op.execute(f'DROP TRIGGER "trg_{_EVIDENCE_TABLE}_valid_insert"')
    for operation in ("rowid", "delete", "update", "insert"):
        op.execute(
            f'DROP TRIGGER "{_append_only_trigger(_EVIDENCE_TABLE, operation)}"'
        )
    op.execute(f'DROP TRIGGER "trg_{_TABLE}_eligibility_insert"')
    for operation in ("rowid", "delete", "update", "insert"):
        op.execute(f'DROP TRIGGER "{_append_only_trigger(_TABLE, operation)}"')
    op.drop_table(_TABLE)
