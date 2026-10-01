"""Add immutable research replay history; no production migration is executed."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_etf_replay_history"
down_revision: str | Sequence[str] | None = "0007_options_risk_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "etf_replay_events",
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
                sa.String(64),
                sa.CheckConstraint(
                    f"typeof({name}) = 'text' AND length({name}) = 64 "
                    f"AND length(CAST({name} AS BLOB)) = 64 AND {name} NOT GLOB '*[^0-9a-f]*'",
                    name=f"{name}_sha256",
                ),
                nullable=False,
            )
            for name in (
                "run_id",
                "input_hash",
                "source_event_id",
                "state_hash",
                "previous_hash",
                "event_hash",
            )
        ],
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
        sa.UniqueConstraint("run_id", "sequence"),
        sa.UniqueConstraint("run_id", "source_event_id"),
        sa.CheckConstraint(
            "typeof(payload_json) = 'text' AND json_valid(payload_json) "
            "AND length(CAST(payload_json AS BLOB)) <= 16384",
            name="payload_bounded",
        ),
    )
    op.execute("""CREATE TRIGGER trg_etf_replay_insert BEFORE INSERT ON etf_replay_events
        WHEN EXISTS (SELECT 1 FROM etf_replay_events WHERE id = NEW.id)
          OR EXISTS (SELECT 1 FROM etf_replay_events
                     WHERE run_id = NEW.run_id AND sequence = NEW.sequence)
          OR EXISTS (SELECT 1 FROM etf_replay_events
                     WHERE run_id = NEW.run_id AND source_event_id = NEW.source_event_id)
          OR (NEW.rowid != -1 AND EXISTS (SELECT 1 FROM etf_replay_events WHERE rowid = NEW.rowid))
        BEGIN SELECT RAISE(ROLLBACK, 'immutable ETF replay history'); END""")
    for operation in ("UPDATE", "DELETE"):
        op.execute(f"""CREATE TRIGGER trg_etf_replay_{operation.lower()} BEFORE {operation}
            ON etf_replay_events
            BEGIN SELECT RAISE(ROLLBACK, 'immutable ETF replay history'); END""")
    op.execute("""CREATE TRIGGER trg_etf_replay_rowid AFTER INSERT ON etf_replay_events
        WHEN NEW.rowid = -1 BEGIN SELECT RAISE(ROLLBACK, 'immutable ETF replay history'); END""")


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT count(*) FROM etf_replay_events")).scalar_one():
        raise RuntimeError("cannot downgrade nonempty ETF replay history")
    for operation in ("rowid", "delete", "update", "insert"):
        op.execute(f"DROP TRIGGER trg_etf_replay_{operation}")
    op.drop_table("etf_replay_events")
