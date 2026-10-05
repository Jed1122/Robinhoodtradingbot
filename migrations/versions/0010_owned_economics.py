"""Retain independent local economic facts without adopting legacy observations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_owned_economics"
down_revision: str | Sequence[str] | None = "0009_owned_order_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "owned_economic_events",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(255),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("sequence", sa.BLOB(), nullable=False),
        sa.CheckConstraint(
            "typeof(sequence) = 'integer' AND sequence >= 0", name="sequence_nonnegative_integer"
        ),
        sa.CheckConstraint("sequence < 10000", name="sequence_bounded"),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "typeof(payload_json) = 'text' AND json_valid(payload_json) "
            "AND length(CAST(payload_json AS BLOB)) <= 16384",
            name="payload_bounded",
        ),
        *[
            sa.Column(
                name,
                sa.String(64),
                sa.CheckConstraint(
                    f"typeof({name}) = 'text' AND length({name}) = 64 "
                    f"AND length(CAST({name} AS BLOB)) = 64 "
                    f"AND {name} NOT GLOB '*[^0-9a-f]*'",
                    name=f"{name}_sha256",
                ),
                nullable=False,
            )
            for name in ("config_hash", "code_hash", "previous_hash", "event_hash")
        ],
        sa.Column(
            "intent_id", sa.String(255), sa.ForeignKey("order_intents.id", ondelete="RESTRICT")
        ),
        sa.Column("order_id", sa.String(255), sa.ForeignKey("orders.id", ondelete="RESTRICT")),
        sa.Column(
            "owned_event_id",
            sa.String(255),
            sa.ForeignKey("owned_order_events.id", ondelete="RESTRICT"),
        ),
        sa.UniqueConstraint("account_id", "sequence"),
        sa.UniqueConstraint("owned_event_id"),
    )
    op.execute("""CREATE TRIGGER trg_owned_economic_insert BEFORE INSERT ON owned_economic_events
        WHEN EXISTS (SELECT 1 FROM owned_economic_events WHERE id = NEW.id)
          OR EXISTS (SELECT 1 FROM owned_economic_events
                     WHERE account_id = NEW.account_id AND sequence = NEW.sequence)
          OR (NEW.owned_event_id IS NOT NULL AND EXISTS
              (SELECT 1 FROM owned_economic_events WHERE owned_event_id = NEW.owned_event_id))
          OR (NEW.rowid != -1 AND EXISTS
              (SELECT 1 FROM owned_economic_events WHERE rowid = NEW.rowid))
        BEGIN SELECT RAISE(ROLLBACK, 'immutable economic history'); END""")
    for operation in ("UPDATE", "DELETE"):
        op.execute(f"""CREATE TRIGGER trg_owned_economic_{operation.lower()} BEFORE {operation}
            ON owned_economic_events
            BEGIN SELECT RAISE(ROLLBACK, 'immutable economic history'); END""")
    op.execute("""CREATE TRIGGER trg_owned_economic_rowid AFTER INSERT ON owned_economic_events
        WHEN NEW.rowid = -1 BEGIN SELECT RAISE(ROLLBACK, 'immutable economic history'); END""")


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT count(*) FROM owned_economic_events")).scalar_one():
        raise RuntimeError("cannot downgrade nonempty economic history")
    for suffix in ("rowid", "delete", "update", "insert"):
        op.execute(f"DROP TRIGGER trg_owned_economic_{suffix}")
    op.drop_table("owned_economic_events")
