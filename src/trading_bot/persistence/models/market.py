"""Market identity, observations, quality, feature, and signal ledger rows."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
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


class InstrumentRow(Base):
    """Broker-neutral instrument identity plus the latest validated metadata."""

    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint("provider", "provider_instrument_id"),
        UniqueConstraint("id", "provider"),
        UniqueConstraint("id", "asset_class"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    provider: Mapped[str] = mapped_column(String(PROVIDER_LENGTH), nullable=False)
    provider_instrument_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False)
    symbol: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    provider_status: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    tradable: Mapped[bool] = exact_boolean_column("tradable")
    fractional_eligible: Mapped[bool] = exact_boolean_column("fractional_eligible")
    price_increment: Mapped[Decimal] = canonical_decimal_column("price_increment")
    quantity_increment: Mapped[Decimal] = canonical_decimal_column("quantity_increment")
    minimum_quantity: Mapped[Decimal] = canonical_decimal_column("minimum_quantity")
    minimum_notional: Mapped[Decimal] = canonical_decimal_column("minimum_notional")
    maximum_quantity: Mapped[Decimal | None] = canonical_decimal_column(
        "maximum_quantity",
        nullable=True,
    )
    correlation_group: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    observed_at: Mapped[datetime] = utc_datetime_column("observed_at")
    data_hash: Mapped[str] = sha256_column("data_hash")


class MarketSnapshotRow(Base):
    """Time-versioned executable quote evidence without provider payloads."""

    __tablename__ = "market_snapshots"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    instrument_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("instruments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    bid: Mapped[Decimal | None] = canonical_decimal_column("bid", nullable=True)
    ask: Mapped[Decimal | None] = canonical_decimal_column("ask", nullable=True)
    last: Mapped[Decimal | None] = canonical_decimal_column("last", nullable=True)
    observed_at: Mapped[datetime] = utc_datetime_column("observed_at")
    source: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    timestamp_source: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    freshness_verified: Mapped[bool] = exact_boolean_column("freshness_verified")
    data_hash: Mapped[str] = sha256_column("data_hash")


class BarRow(Base):
    """Exact historical OHLCV bar with explicit provenance."""

    __tablename__ = "bars"
    __table_args__ = (UniqueConstraint("instrument_id", "interval", "starts_at", "source"),)

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    instrument_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("instruments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    interval: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    starts_at: Mapped[datetime] = utc_datetime_column("starts_at")
    ends_at: Mapped[datetime] = utc_datetime_column("ends_at")
    open: Mapped[Decimal] = canonical_decimal_column("open")
    high: Mapped[Decimal] = canonical_decimal_column("high")
    low: Mapped[Decimal] = canonical_decimal_column("low")
    close: Mapped[Decimal] = canonical_decimal_column("close")
    volume: Mapped[Decimal] = canonical_decimal_column("volume")
    source: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    interpolated: Mapped[bool] = exact_boolean_column("interpolated")
    data_hash: Mapped[str] = sha256_column("data_hash")


class DataQualityEventRow(Base):
    """Rejected or quarantined market-data evidence with sanitized details."""

    __tablename__ = "data_quality_events"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    instrument_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("instruments.id", ondelete="RESTRICT"),
        nullable=True,
    )
    occurred_at: Mapped[datetime] = utc_datetime_column("occurred_at")
    code: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    severity: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    sanitized_details_json: Mapped[str] = mapped_column(Text(), nullable=False)
    data_hash: Mapped[str | None] = sha256_column("data_hash", nullable=True)
    config_hash: Mapped[str] = sha256_column("config_hash")


class FeatureRow(Base):
    """Content-addressed feature output represented as canonical sanitized JSON."""

    __tablename__ = "features"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    instrument_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("instruments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    feature_name: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    observed_at: Mapped[datetime] = utc_datetime_column("observed_at")
    values_json: Mapped[str] = mapped_column(Text(), nullable=False)
    data_hash: Mapped[str] = sha256_column("data_hash")
    config_hash: Mapped[str] = sha256_column("config_hash")
    code_hash: Mapped[str] = sha256_column("code_hash")


class SignalRow(Base):
    """Content-addressed broker-neutral strategy signal."""

    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    instrument_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey("instruments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    strategy_version: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    signal_name: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    observed_at: Mapped[datetime] = utc_datetime_column("observed_at")
    value: Mapped[Decimal | None] = canonical_decimal_column("value", nullable=True)
    output_json: Mapped[str] = mapped_column(Text(), nullable=False)
    data_hash: Mapped[str] = sha256_column("data_hash")
    config_hash: Mapped[str] = sha256_column("config_hash")
    code_hash: Mapped[str] = sha256_column("code_hash")


__all__ = [
    "BarRow",
    "DataQualityEventRow",
    "FeatureRow",
    "InstrumentRow",
    "MarketSnapshotRow",
    "SignalRow",
]
