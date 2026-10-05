"""Retain local owned lifecycle and fill facts without rewriting legacy evidence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_owned_order_lifecycle"
down_revision: str | Sequence[str] | None = "0008_etf_replay_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "owned_order_events",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("order_id", sa.String(255), nullable=False),
        sa.Column("intent_id", sa.String(255), nullable=False),
        sa.Column(
            "transition_id",
            sa.String(255),
            sa.ForeignKey("order_transitions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("fill_id", sa.String(255), sa.ForeignKey("fills.id", ondelete="RESTRICT")),
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
                    f"AND length(CAST({name} AS BLOB)) = 64 AND {name} NOT GLOB '*[^0-9a-f]*'",
                    name=f"{name}_sha256",
                ),
                nullable=False,
            )
            for name in ("previous_hash", "event_hash", "order_hash")
        ],
        sa.ForeignKeyConstraint(
            ["order_id", "intent_id"], ["orders.id", "orders.intent_id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("order_id", "sequence"),
        sa.UniqueConstraint("transition_id"),
        sa.UniqueConstraint("fill_id"),
    )
    op.execute("""CREATE TRIGGER trg_owned_order_insert BEFORE INSERT ON owned_order_events
        WHEN EXISTS (SELECT 1 FROM owned_order_events WHERE id = NEW.id)
          OR EXISTS (SELECT 1 FROM owned_order_events
                     WHERE order_id = NEW.order_id AND sequence = NEW.sequence)
          OR EXISTS (SELECT 1 FROM owned_order_events WHERE transition_id = NEW.transition_id)
          OR (NEW.fill_id IS NOT NULL AND EXISTS
              (SELECT 1 FROM owned_order_events WHERE fill_id = NEW.fill_id))
          OR (NEW.rowid != -1 AND EXISTS
              (SELECT 1 FROM owned_order_events WHERE rowid = NEW.rowid))
        BEGIN SELECT RAISE(ROLLBACK, 'immutable owned order history'); END""")
    op.execute("""CREATE TRIGGER trg_owned_fill_insert BEFORE INSERT ON fills
        WHEN EXISTS (SELECT 1 FROM fills WHERE id = NEW.id)
          OR EXISTS (SELECT 1 FROM fills
              WHERE provider = NEW.provider AND external_execution_key = NEW.external_execution_key)
          OR (NEW.rowid != -1 AND EXISTS (SELECT 1 FROM fills WHERE rowid = NEW.rowid))
        BEGIN SELECT RAISE(ROLLBACK, 'immutable fill history'); END""")
    for table, prefix in (("owned_order_events", "owned_order"), ("fills", "owned_fill")):
        for operation in ("UPDATE", "DELETE"):
            op.execute(f"""CREATE TRIGGER trg_{prefix}_{operation.lower()} BEFORE {operation}
                ON {table} BEGIN SELECT RAISE(ROLLBACK, 'immutable execution history'); END""")
        op.execute(f"""CREATE TRIGGER trg_{prefix}_rowid AFTER INSERT ON {table}
            WHEN NEW.rowid = -1 BEGIN SELECT RAISE(ROLLBACK, 'immutable execution history'); END""")


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT count(*) FROM owned_order_events")).scalar_one():
        raise RuntimeError("cannot downgrade nonempty owned order history")
    for prefix in ("owned_order", "owned_fill"):
        for operation in ("rowid", "delete", "update", "insert"):
            op.execute(f"DROP TRIGGER trg_{prefix}_{operation}")
    op.drop_table("owned_order_events")
