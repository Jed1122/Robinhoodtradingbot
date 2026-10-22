"""Isolated experimental hybrid account state; never production order authority."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_hybrid_experimental"
down_revision: str | Sequence[str] | None = "0010_owned_economics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hybrid_events",
        sa.Column("sequence", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("event_id", sa.String(128), nullable=False, unique=True),
        sa.Column("kind", sa.String(64), nullable=False),
        *[
            sa.Column(name, sa.String(64), nullable=False)
            for name in ("request_hash", "config_hash", "previous_hash", "event_hash")
        ],
        sa.Column("state_json", sa.Text, nullable=False),
        sa.CheckConstraint("sequence >= 0 AND sequence < 100000", name="sequence_bounded"),
        sa.CheckConstraint(
            "json_valid(state_json) AND length(state_json) <= 1048576", name="state_bounded"
        ),
    )
    for operation in ("UPDATE", "DELETE"):
        op.execute(f"""CREATE TRIGGER trg_hybrid_{operation.lower()} BEFORE {operation}
            ON hybrid_events BEGIN SELECT RAISE(ROLLBACK, 'immutable hybrid history'); END""")
    op.execute("""CREATE TRIGGER trg_hybrid_replace BEFORE INSERT ON hybrid_events
        WHEN EXISTS (SELECT 1 FROM hybrid_events
                     WHERE sequence = NEW.sequence OR event_id = NEW.event_id)
        BEGIN SELECT RAISE(ROLLBACK, 'immutable hybrid history'); END""")


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT count(*) FROM hybrid_events")).scalar_one():
        raise RuntimeError("cannot downgrade nonempty hybrid history")
    for suffix in ("update", "delete", "replace"):
        op.execute(f"DROP TRIGGER trg_hybrid_{suffix}")
    op.drop_table("hybrid_events")
