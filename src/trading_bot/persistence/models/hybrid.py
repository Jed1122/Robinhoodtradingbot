"""Experimental hybrid account journal, isolated from production order ownership."""

from sqlalchemy import CheckConstraint, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from trading_bot.persistence.base import Base, sha256_column


class HybridEventRow(Base):
    __tablename__ = "hybrid_events"
    __table_args__ = (
        CheckConstraint("sequence >= 0 AND sequence < 100000", name="sequence_bounded"),
        CheckConstraint(
            "json_valid(state_json) AND length(state_json) <= 1048576", name="state_bounded"
        ),
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = sha256_column("request_hash")
    config_hash: Mapped[str] = sha256_column("config_hash")
    previous_hash: Mapped[str] = sha256_column("previous_hash")
    event_hash: Mapped[str] = sha256_column("event_hash")
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
