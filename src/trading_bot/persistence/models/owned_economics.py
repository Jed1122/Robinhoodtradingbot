"""Additive append-only local economic history and exact execution counterparts."""

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from trading_bot.persistence.base import Base, exact_nonnegative_integer_column, sha256_column


class OwnedEconomicEventRow(Base):
    __tablename__ = "owned_economic_events"
    __table_args__ = (
        UniqueConstraint("account_id", "sequence"),
        UniqueConstraint("owned_event_id"),
        CheckConstraint("sequence < 10000", name="sequence_bounded"),
        CheckConstraint(
            "typeof(payload_json) = 'text' AND json_valid(payload_json) "
            "AND length(CAST(payload_json AS BLOB)) <= 16384",
            name="payload_bounded",
        ),
    )
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    sequence: Mapped[int] = exact_nonnegative_integer_column("sequence")
    payload_json: Mapped[str] = mapped_column(Text(), nullable=False)
    config_hash: Mapped[str] = sha256_column("config_hash")
    code_hash: Mapped[str] = sha256_column("code_hash")
    previous_hash: Mapped[str] = sha256_column("previous_hash")
    event_hash: Mapped[str] = sha256_column("event_hash")
    intent_id: Mapped[str | None] = mapped_column(
        String(255), ForeignKey("order_intents.id", ondelete="RESTRICT")
    )
    order_id: Mapped[str | None] = mapped_column(
        String(255), ForeignKey("orders.id", ondelete="RESTRICT")
    )
    owned_event_id: Mapped[str | None] = mapped_column(
        String(255), ForeignKey("owned_order_events.id", ondelete="RESTRICT")
    )
