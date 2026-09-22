"""Append-only synthetic loss observations; no migration of production state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_options_risk_history"
down_revision: str | Sequence[str] | None = "0006_options_trial_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "options_risk_events",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(255),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *[
            sa.Column(
                name,
                sa.BLOB(),
                sa.CheckConstraint(
                    f"typeof({name}) = 'integer' AND {name} >= 0",
                    name=f"{name}_nonnegative_integer",
                ),
                nullable=False,
            )
            for name in ("sequence", "fencing_token")
        ],
        sa.Column("payload_json", sa.Text(), nullable=False),
        *[
            sa.Column(
                name,
                sa.String(64),
                sa.CheckConstraint(
                    f"typeof({name}) = 'text' AND length({name}) = 64 "
                    f"AND length(CAST({name} AS BLOB)) = 64 AND {name} NOT GLOB '*[^0-9a-f]*'",
                    name=f"{name}_sha256",
                ),
                nullable=False,
            )
            for name in ("previous_hash", "event_hash")
        ],
        sa.UniqueConstraint("account_id", "sequence"),
        sa.UniqueConstraint("event_hash"),
        sa.CheckConstraint(
            "typeof(payload_json) = 'text' AND json_valid(payload_json) "
            "AND length(CAST(payload_json AS BLOB)) <= 16384",
            name="payload_bounded",
        ),
    )
    op.execute("""
        CREATE TRIGGER trg_options_risk_insert BEFORE INSERT ON options_risk_events
        WHEN EXISTS (SELECT 1 FROM options_risk_events WHERE id = NEW.id)
          OR EXISTS (SELECT 1 FROM options_risk_events WHERE event_hash = NEW.event_hash)
          OR EXISTS (SELECT 1 FROM options_risk_events
                     WHERE account_id = NEW.account_id AND sequence = NEW.sequence)
          OR (NEW.rowid != -1 AND EXISTS (
              SELECT 1 FROM options_risk_events WHERE rowid = NEW.rowid))
        BEGIN SELECT RAISE(ROLLBACK, 'immutable options risk history'); END
    """)
    for operation in ("UPDATE", "DELETE"):
        op.execute(f"""
            CREATE TRIGGER trg_options_risk_{operation.lower()} BEFORE {operation}
            ON options_risk_events
            BEGIN SELECT RAISE(ROLLBACK, 'immutable options risk history'); END
        """)
    op.execute("""
        CREATE TRIGGER trg_options_risk_rowid AFTER INSERT ON options_risk_events
        WHEN NEW.rowid = -1
        BEGIN SELECT RAISE(ROLLBACK, 'immutable options risk history'); END
    """)


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT count(*) FROM options_risk_events")).scalar_one():
        raise RuntimeError("cannot downgrade nonempty options risk history")
    for operation in ("rowid", "delete", "update", "insert"):
        op.execute(f"DROP TRIGGER trg_options_risk_{operation}")
    op.drop_table("options_risk_events")
