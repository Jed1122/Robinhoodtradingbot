"""Account, position, and portfolio ledger rows."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from trading_bot.persistence.base import (
    ID_LENGTH,
    NAME_LENGTH,
    PROVIDER_LENGTH,
    Base,
    canonical_decimal_column,
    exact_boolean_column,
    sha256_column,
    utc_datetime_column,
)


class AccountRow(Base):
    """Current broker-neutral account identity and observed safety state."""

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_account_id"),
        UniqueConstraint("id", "provider"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    provider: Mapped[str] = mapped_column(String(PROVIDER_LENGTH), nullable=False)
    provider_account_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    account_type: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    provider_state: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    equity: Mapped[Decimal] = canonical_decimal_column("equity")
    cash: Mapped[Decimal] = canonical_decimal_column("cash")
    equity_buying_power: Mapped[Decimal | None] = canonical_decimal_column(
        "equity_buying_power",
        nullable=True,
    )
    crypto_buying_power: Mapped[Decimal | None] = canonical_decimal_column(
        "crypto_buying_power",
        nullable=True,
    )
    prediction_buying_power: Mapped[Decimal | None] = canonical_decimal_column(
        "prediction_buying_power",
        nullable=True,
    )
    restricted: Mapped[bool] = exact_boolean_column("restricted")
    observed_at: Mapped[datetime] = utc_datetime_column("observed_at")
    data_hash: Mapped[str] = sha256_column("data_hash")
    config_hash: Mapped[str] = sha256_column("config_hash")
    code_hash: Mapped[str] = sha256_column("code_hash")


class PositionRow(Base):
    """Time-versioned exact position observation."""

    __tablename__ = "positions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["portfolio_snapshot_id", "account_id"],
            ["portfolio_snapshots.id", "portfolio_snapshots.account_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["instrument_id", "asset_class"],
            ["instruments.id", "instruments.asset_class"],
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    instrument_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    portfolio_snapshot_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH),
        nullable=True,
    )
    asset_class: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    quantity: Mapped[Decimal] = canonical_decimal_column("quantity")
    average_price: Mapped[Decimal | None] = canonical_decimal_column(
        "average_price",
        nullable=True,
    )
    market_value: Mapped[Decimal] = canonical_decimal_column("market_value")
    unrealized_pnl: Mapped[Decimal] = canonical_decimal_column("unrealized_pnl")
    observed_at: Mapped[datetime] = utc_datetime_column("observed_at")
    data_hash: Mapped[str] = sha256_column("data_hash")


class PortfolioSnapshotRow(Base):
    """Time-versioned account totals used for risk and reconciliation evidence."""

    __tablename__ = "portfolio_snapshots"
    __table_args__ = (UniqueConstraint("id", "account_id"),)

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    equity: Mapped[Decimal] = canonical_decimal_column("equity")
    cash: Mapped[Decimal] = canonical_decimal_column("cash")
    gross_exposure: Mapped[Decimal] = canonical_decimal_column("gross_exposure")
    net_exposure: Mapped[Decimal] = canonical_decimal_column("net_exposure")
    crypto_exposure: Mapped[Decimal] = canonical_decimal_column("crypto_exposure")
    realized_pnl: Mapped[Decimal] = canonical_decimal_column("realized_pnl")
    unrealized_pnl: Mapped[Decimal] = canonical_decimal_column("unrealized_pnl")
    observed_at: Mapped[datetime] = utc_datetime_column("observed_at")
    data_hash: Mapped[str] = sha256_column("data_hash")


class EquityCurveRow(Base):
    """Exact account equity observation for performance and drawdown reconstruction."""

    __tablename__ = "equity_curve"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    observed_at: Mapped[datetime] = utc_datetime_column("observed_at")
    equity: Mapped[Decimal] = canonical_decimal_column("equity")
    cash: Mapped[Decimal] = canonical_decimal_column("cash")
    gross_exposure: Mapped[Decimal] = canonical_decimal_column("gross_exposure")
    net_exposure: Mapped[Decimal] = canonical_decimal_column("net_exposure")
    data_hash: Mapped[str] = sha256_column("data_hash")


class RealizedPnlRow(Base):
    """Append-oriented exact realized profit-and-loss event."""

    __tablename__ = "realized_pnl"
    __table_args__ = (
        CheckConstraint(
            "fill_id IS NULL OR instrument_id IS NOT NULL",
            name="fill_requires_instrument",
        ),
        ForeignKeyConstraint(
            ["fill_id", "account_id", "instrument_id"],
            ["fills.id", "fills.account_id", "fills.instrument_id"],
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    instrument_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("instruments.id", ondelete="RESTRICT"),
        nullable=True,
    )
    fill_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH),
        nullable=True,
    )
    amount: Mapped[Decimal] = canonical_decimal_column("amount")
    realized_at: Mapped[datetime] = utc_datetime_column("realized_at")
    data_hash: Mapped[str] = sha256_column("data_hash")


class DrawdownEventRow(Base):
    """Exact drawdown observation; policy decisions remain outside persistence."""

    __tablename__ = "drawdown_events"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    started_at: Mapped[datetime] = utc_datetime_column("started_at")
    observed_at: Mapped[datetime] = utc_datetime_column("observed_at")
    peak_equity: Mapped[Decimal] = canonical_decimal_column("peak_equity")
    current_equity: Mapped[Decimal] = canonical_decimal_column("current_equity")
    drawdown_fraction: Mapped[Decimal] = canonical_decimal_column("drawdown_fraction")
    active: Mapped[bool] = exact_boolean_column("active")
    config_hash: Mapped[str] = sha256_column("config_hash")
    data_hash: Mapped[str] = sha256_column("data_hash")


__all__ = [
    "AccountRow",
    "DrawdownEventRow",
    "EquityCurveRow",
    "PortfolioSnapshotRow",
    "PositionRow",
    "RealizedPnlRow",
]
