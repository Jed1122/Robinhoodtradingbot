"""Additive immutable options trial history; no production execution owner yet."""

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from trading_bot.persistence.base import (
    ID_LENGTH,
    Base,
    exact_nonnegative_integer_column,
    sha256_column,
)


class OptionsTrialEventRow(Base):
    __tablename__ = "options_trial_events"
    __table_args__ = (
        UniqueConstraint("account_id", "sequence"),
        UniqueConstraint("event_hash"),
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
    sequence: Mapped[int] = exact_nonnegative_integer_column("sequence")
    fencing_token: Mapped[int] = exact_nonnegative_integer_column("fencing_token")
    payload_json: Mapped[str] = mapped_column(Text(), nullable=False)
    previous_hash: Mapped[str] = sha256_column("previous_hash")
    event_hash: Mapped[str] = sha256_column("event_hash")
