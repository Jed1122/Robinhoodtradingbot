"""Append-only local lifecycle facts linked to immutable order responses."""

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from trading_bot.persistence.base import (
    ID_LENGTH,
    Base,
    exact_nonnegative_integer_column,
    sha256_column,
)


class OwnedOrderEventRow(Base):
    __tablename__ = "owned_order_events"
    __table_args__ = (
        UniqueConstraint("order_id", "sequence"),
        UniqueConstraint("transition_id"),
        UniqueConstraint("fill_id"),
        ForeignKeyConstraint(
            ["order_id", "intent_id"], ["orders.id", "orders.intent_id"], ondelete="RESTRICT"
        ),
        CheckConstraint(
            "typeof(payload_json) = 'text' AND json_valid(payload_json) "
            "AND length(CAST(payload_json AS BLOB)) <= 16384",
            name="payload_bounded",
        ),
        CheckConstraint("sequence < 10000", name="sequence_bounded"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    intent_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    sequence: Mapped[int] = exact_nonnegative_integer_column("sequence")
    payload_json: Mapped[str] = mapped_column(Text(), nullable=False)
    previous_hash: Mapped[str] = sha256_column("previous_hash")
    event_hash: Mapped[str] = sha256_column("event_hash")
    order_hash: Mapped[str] = sha256_column("order_hash")
    transition_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("order_transitions.id", ondelete="RESTRICT"), nullable=False
    )
    fill_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("fills.id", ondelete="RESTRICT"), nullable=True
    )


__all__ = ["OwnedOrderEventRow"]
