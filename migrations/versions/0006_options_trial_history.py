"""Add immutable synthetic options trial history without rewriting old evidence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_options_trial_history"
down_revision: str | Sequence[str] | None = "0005_research_evidence_guards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _hash(name: str) -> sa.Column[str]:
    return sa.Column(
        name,
        sa.String(64),
        sa.CheckConstraint(
            f"typeof({name}) = 'text' AND length({name}) = 64 "
            f"AND length(CAST({name} AS BLOB)) = 64 AND {name} NOT GLOB '*[^0-9a-f]*'",
            name=f"{name}_sha256",
        ),
        nullable=False,
    )


def _integer(name: str) -> sa.Column[int]:
    return sa.Column(
        name,
        sa.BLOB(),
        sa.CheckConstraint(
            f"typeof({name}) = 'integer' AND {name} >= 0", name=f"{name}_nonnegative_integer"
        ),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "options_trial_events",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(255),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        _integer("sequence"),
        _integer("fencing_token"),
        sa.Column("payload_json", sa.Text(), nullable=False),
        _hash("previous_hash"),
        _hash("event_hash"),
        sa.UniqueConstraint("account_id", "sequence"),
        sa.UniqueConstraint("event_hash"),
        sa.CheckConstraint(
            "typeof(payload_json) = 'text' AND json_valid(payload_json) "
            "AND length(CAST(payload_json AS BLOB)) <= 16384",
            name="payload_bounded",
        ),
    )
    op.execute("""
        CREATE TRIGGER trg_options_trial_insert BEFORE INSERT ON options_trial_events
        WHEN EXISTS (SELECT 1 FROM options_trial_events WHERE id = NEW.id)
          OR EXISTS (SELECT 1 FROM options_trial_events WHERE event_hash = NEW.event_hash)
          OR EXISTS (SELECT 1 FROM options_trial_events
                     WHERE account_id = NEW.account_id AND sequence = NEW.sequence)
          OR (NEW.rowid != -1 AND EXISTS (
              SELECT 1 FROM options_trial_events WHERE rowid = NEW.rowid))
        BEGIN SELECT RAISE(ROLLBACK, 'immutable options history'); END
    """)
    op.execute("""
        CREATE TRIGGER trg_options_trial_update BEFORE UPDATE ON options_trial_events
        BEGIN SELECT RAISE(ROLLBACK, 'immutable options history'); END
    """)
    op.execute("""
        CREATE TRIGGER trg_options_trial_delete BEFORE DELETE ON options_trial_events
        BEGIN SELECT RAISE(ROLLBACK, 'immutable options history'); END
    """)
    op.execute("""
        CREATE TRIGGER trg_options_trial_rowid AFTER INSERT ON options_trial_events
        WHEN NEW.rowid = -1
        BEGIN SELECT RAISE(ROLLBACK, 'immutable options history'); END
    """)


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT count(*) FROM options_trial_events")).scalar_one():
        raise RuntimeError("cannot downgrade nonempty options trial history")
    for operation in ("rowid", "delete", "update", "insert"):
        op.execute(f"DROP TRIGGER trg_options_trial_{operation}")
    op.drop_table("options_trial_events")
