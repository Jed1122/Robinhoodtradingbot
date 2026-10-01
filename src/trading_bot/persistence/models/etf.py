"""Immutable research-only ETF account replay journal."""

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from trading_bot.persistence.base import (
    ID_LENGTH,
    Base,
    exact_nonnegative_integer_column,
    sha256_column,
)


class EtfReplayEventRow(Base):
    __tablename__ = "etf_replay_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence"),
        UniqueConstraint("run_id", "source_event_id"),
        CheckConstraint(
            "typeof(payload_json) = 'text' AND json_valid(payload_json) "
            "AND length(CAST(payload_json AS BLOB)) <= 16384",
            name="payload_bounded",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    run_id: Mapped[str] = sha256_column("run_id")
    input_hash: Mapped[str] = sha256_column("input_hash")
    source_event_id: Mapped[str] = sha256_column("source_event_id")
    sequence: Mapped[int] = exact_nonnegative_integer_column("sequence")
    fencing_token: Mapped[int] = exact_nonnegative_integer_column("fencing_token")
    payload_json: Mapped[str] = mapped_column(Text(), nullable=False)
    state_hash: Mapped[str] = sha256_column("state_hash")
    previous_hash: Mapped[str] = sha256_column("previous_hash")
    event_hash: Mapped[str] = sha256_column("event_hash")
