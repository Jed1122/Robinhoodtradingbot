"""Make research acceptance evidence unique and append-only.

Revision ID: 0005_research_evidence_guards
Revises: 0004_promotion_observations
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_research_evidence_guards"
down_revision: str | Sequence[str] | None = "0004_promotion_observations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "research_acceptance_evidence"
_CONSTRAINT = "uq_research_acceptance_evidence_evidence_hash"


def _trigger(operation: str) -> str:
    if operation not in {"insert", "update", "delete", "rowid", "valid"}:
        raise ValueError("research evidence operation is unknown")
    return f"trg_{_TABLE}_immutable_{operation}"


def _invalid_existing_count() -> int:
    connection = op.get_bind()
    result = connection.execute(
        sa.text(
            f"""
            SELECT count(*)
            FROM "{_TABLE}" AS candidate
            WHERE CASE
                WHEN json_valid(candidate.reason_codes_json) = 0 THEN 1
                WHEN json_type(candidate.reason_codes_json) != 'array' THEN 1
                WHEN candidate.eligible = 1
                     AND candidate.reason_codes_json != '[]' THEN 1
                ELSE 0
            END
               OR EXISTS (
                   SELECT 1
                   FROM "{_TABLE}" AS duplicate
                   WHERE duplicate.evidence_hash = candidate.evidence_hash
                     AND duplicate.id != candidate.id
               )
            """
        )
    ).scalar_one()
    if type(result) is not int or result < 0:
        raise RuntimeError("research evidence preflight returned an invalid count")
    return result


def upgrade() -> None:
    if _invalid_existing_count():
        raise RuntimeError("existing research evidence is incompatible with immutable guards")
    with op.batch_alter_table(_TABLE) as batch:
        batch.create_unique_constraint(_CONSTRAINT, ["evidence_hash"])
    op.execute(
        f"""
        CREATE TRIGGER "{_trigger("insert")}"
        BEFORE INSERT ON "{_TABLE}"
        WHEN EXISTS (SELECT 1 FROM "{_TABLE}" WHERE id = NEW.id)
          OR EXISTS (
              SELECT 1 FROM "{_TABLE}" WHERE evidence_hash = NEW.evidence_hash
          )
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
            CREATE TRIGGER "{_trigger(operation)}"
            BEFORE {operation.upper()} ON "{_TABLE}"
            BEGIN
                SELECT RAISE(ROLLBACK, 'append-only {operation} rejected');
            END
            """
        )
    op.execute(
        f"""
        CREATE TRIGGER "{_trigger("rowid")}"
        AFTER INSERT ON "{_TABLE}"
        WHEN NEW.rowid = -1
        BEGIN
            SELECT RAISE(ROLLBACK, 'append-only rowid rejected');
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER "{_trigger("valid")}"
        BEFORE INSERT ON "{_TABLE}"
        WHEN CASE
            WHEN json_valid(NEW.reason_codes_json) = 0 THEN 1
            WHEN json_type(NEW.reason_codes_json) != 'array' THEN 1
            WHEN NEW.eligible AND NEW.reason_codes_json != '[]' THEN 1
            ELSE 0
        END
        BEGIN
            SELECT RAISE(ROLLBACK, 'research evidence rejected');
        END
        """
    )


def downgrade() -> None:
    for operation in ("valid", "rowid", "delete", "update", "insert"):
        op.execute(f'DROP TRIGGER "{_trigger(operation)}"')
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_constraint(_CONSTRAINT, type_="unique")
