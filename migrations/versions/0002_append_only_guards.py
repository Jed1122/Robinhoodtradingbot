"""Guard critical ledger events against mutation and SQLite replace semantics.

Revision ID: 0002_append_only_guards
Revises: 0001_core_ledger
Create Date: 2026-07-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_append_only_guards"
down_revision: str | Sequence[str] | None = "0001_core_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROTECTED_TABLES = (
    "audit_events",
    "order_transitions",
    "risk_evaluations",
    "configuration_versions",
    "live_authorizations",
    "kill_switch_events",
    "reconciliation_events",
)

UNIQUE_REPLACE_KEYS = {
    "configuration_versions": ("config_hash",),
    "live_authorizations": ("activation_nonce",),
}


def _trigger_name(table_name: str, operation: str) -> str:
    if table_name not in PROTECTED_TABLES or operation not in {
        "insert",
        "update",
        "delete",
        "rowid",
    }:
        raise ValueError("append-only trigger identifier is not in the closed migration set")
    return f"trg_{table_name}_append_only_{operation}"


def _insert_guard_sql(table_name: str) -> str:
    conflicts = [
        f'EXISTS (SELECT 1 FROM "{table_name}" WHERE id = NEW.id)',  # nosec B608
        (  # Static identifiers are validated by _trigger_name.
            f'(NEW.rowid != -1 AND EXISTS (SELECT 1 FROM "{table_name}" WHERE rowid = NEW.rowid))'  # nosec B608
        ),
    ]
    conflicts.extend(
        f'EXISTS (SELECT 1 FROM "{table_name}" WHERE "{column_name}" = NEW."{column_name}")'  # nosec B608
        for column_name in UNIQUE_REPLACE_KEYS.get(table_name, ())
    )
    conflicts.extend(
        (
            "NEW.corrects_id = NEW.id",
            (
                f"(NEW.corrects_id IS NOT NULL AND NOT EXISTS "  # nosec B608
                f'(SELECT 1 FROM "{table_name}" WHERE id = NEW.corrects_id))'
            ),
        )
    )
    predicate = "\n        OR ".join(conflicts)
    return f"""
    CREATE TRIGGER "{_trigger_name(table_name, "insert")}"
    BEFORE INSERT ON "{table_name}"
    WHEN {predicate}
    BEGIN
        SELECT RAISE(ROLLBACK, 'append-only insert rejected');
    END
    """


def _mutation_guard_sql(table_name: str, operation: str) -> str:
    return f"""
    CREATE TRIGGER "{_trigger_name(table_name, operation)}"
    BEFORE {operation.upper()} ON "{table_name}"
    BEGIN
        SELECT RAISE(ROLLBACK, 'append-only {operation} rejected');
    END
    """


def _negative_rowid_guard_sql(table_name: str) -> str:
    return f"""
    CREATE TRIGGER "{_trigger_name(table_name, "rowid")}"
    AFTER INSERT ON "{table_name}"
    WHEN NEW.rowid = -1
    BEGIN
        SELECT RAISE(ROLLBACK, 'append-only rowid rejected');
    END
    """


def upgrade() -> None:
    for table_name in PROTECTED_TABLES:
        op.execute(_insert_guard_sql(table_name))
        op.execute(_mutation_guard_sql(table_name, "update"))
        op.execute(_mutation_guard_sql(table_name, "delete"))
        op.execute(_negative_rowid_guard_sql(table_name))


def downgrade() -> None:
    for table_name in reversed(PROTECTED_TABLES):
        for operation in ("rowid", "delete", "update", "insert"):
            op.execute(f'DROP TRIGGER "{_trigger_name(table_name, operation)}"')
