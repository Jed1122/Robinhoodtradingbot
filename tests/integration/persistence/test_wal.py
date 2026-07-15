"""Integration tests for the fail-closed SQLite connection policy."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from trading_bot.persistence import (
    CanonicalDecimal,
    ExactBoolean,
    ExactNonNegativeInteger,
    PersistenceConfigurationError,
    PersistenceDataError,
    SHA256Digest,
    UTCDateTime,
    async_session_factory,
    create_engine,
)


class DecimalSubclass(Decimal):
    pass


class DatetimeSubclass(datetime):
    pass


async def _read_pragmas(engine: AsyncEngine) -> tuple[str, int, int]:
    async with engine.connect() as connection:
        journal = await connection.scalar(text("PRAGMA journal_mode"))
        foreign_keys = await connection.scalar(text("PRAGMA foreign_keys"))
        synchronous = await connection.scalar(text("PRAGMA synchronous"))
    return str(journal).lower(), int(foreign_keys), int(synchronous)


@pytest.mark.asyncio
async def test_sqlite_uses_wal_foreign_keys_and_full_sync(sqlite_engine: AsyncEngine) -> None:
    assert await _read_pragmas(sqlite_engine) == ("wal", 1, 2)


@pytest.mark.asyncio
async def test_foreign_keys_are_enforced_not_merely_reported(
    sqlite_engine: AsyncEngine,
) -> None:
    async with sqlite_engine.begin() as connection:
        await connection.execute(text("CREATE TABLE parent (id INTEGER PRIMARY KEY)"))
        await connection.execute(
            text(
                "CREATE TABLE child ("
                "id INTEGER PRIMARY KEY, "
                "parent_id INTEGER NOT NULL REFERENCES parent(id)"
                ")"
            )
        )

    with pytest.raises(IntegrityError):
        async with sqlite_engine.begin() as connection:
            await connection.execute(text("INSERT INTO child (id, parent_id) VALUES (1, 999)"))


@pytest.mark.asyncio
async def test_connection_policy_is_applied_to_a_new_physical_connection(
    sqlite_engine: AsyncEngine,
) -> None:
    await sqlite_engine.dispose()
    assert await _read_pragmas(sqlite_engine) == ("wal", 1, 2)


@pytest.mark.asyncio
async def test_connection_policy_repairs_tampered_pooled_connections(
    sqlite_engine: AsyncEngine,
) -> None:
    async with sqlite_engine.connect() as connection:
        await connection.exec_driver_sql("PRAGMA journal_mode=DELETE")
        await connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        await connection.exec_driver_sql("PRAGMA synchronous=OFF")

    assert await _read_pragmas(sqlite_engine) == ("wal", 1, 2)
    await sqlite_engine.dispose()
    assert await _read_pragmas(sqlite_engine) == ("wal", 1, 2)


@pytest.mark.asyncio
async def test_async_session_factory_binds_safe_sessions_to_engine(
    sqlite_engine: AsyncEngine,
) -> None:
    factory = async_session_factory(sqlite_engine)

    async with factory() as session:
        assert session.bind is sqlite_engine
        assert session.sync_session.autoflush is False
        assert session.sync_session.expire_on_commit is False


@pytest.mark.asyncio
async def test_engine_creation_does_not_create_application_schema(
    sqlite_engine: AsyncEngine,
) -> None:
    async with sqlite_engine.connect() as connection:
        rows = await connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))

    assert rows.scalars().all() == []


@pytest.mark.asyncio
async def test_connection_fails_when_wal_cannot_be_established() -> None:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    try:
        with pytest.raises(PersistenceConfigurationError, match="WAL"):
            async with engine.connect():
                pass
    finally:
        await engine.dispose()


def test_unknown_database_dialect_is_normalized_to_configuration_error() -> None:
    with pytest.raises(PersistenceConfigurationError, match="database_url"):
        create_engine("not-a-dialect://ledger")


@pytest.mark.asyncio
async def test_session_factory_rejects_an_engine_without_the_persistence_safety_policy(
    database_url: str,
) -> None:
    unvalidated_engine = create_async_engine(database_url)
    try:
        with pytest.raises(PersistenceConfigurationError, match="validated"):
            async_session_factory(unvalidated_engine)
    finally:
        await unvalidated_engine.dispose()


@pytest.mark.asyncio
async def test_exact_decimal_and_utc_types_round_trip_without_float_or_timezone_loss(
    sqlite_engine: AsyncEngine,
) -> None:
    metadata = sa.MetaData()
    probe = sa.Table(
        "exact_value_probe",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("amount", CanonicalDecimal(), nullable=False),
        sa.Column("observed_at", UTCDateTime(), nullable=False),
    )
    amount = Decimal("12345678901234567890.12345678901234567890")
    observed_at = datetime(2026, 7, 13, 23, 59, 58, 123456, tzinfo=UTC)

    async with sqlite_engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(
            probe.insert().values(id=1, amount=amount, observed_at=observed_at)
        )
        row = (await connection.execute(sa.select(probe))).one()

    assert row.amount == amount
    assert row.observed_at == observed_at
    assert row.observed_at.tzinfo is UTC


@pytest.mark.asyncio
async def test_exact_boolean_and_integer_round_trip_with_integer_storage_class(
    sqlite_engine: AsyncEngine,
) -> None:
    metadata = sa.MetaData()
    probe = sa.Table(
        "exact_integer_probe",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("flag", ExactBoolean(), nullable=False),
        sa.Column("count", ExactNonNegativeInteger(), nullable=False),
    )

    async with sqlite_engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(probe.insert().values(id=1, flag=True, count=7))
        row = (await connection.execute(sa.select(probe))).one()
        raw_row = (
            await connection.exec_driver_sql(
                "SELECT typeof(flag), flag, typeof(count), count FROM exact_integer_probe"
            )
        ).one()

    assert type(row.flag) is bool
    assert row.flag is True
    assert type(row.count) is int
    assert row.count == 7
    assert raw_row == ("integer", 1, "integer", 7)


@pytest.mark.asyncio
async def test_exact_decimal_canonicalizes_zero_without_rendering_its_exponent(
    sqlite_engine: AsyncEngine,
) -> None:
    metadata = sa.MetaData()
    probe = sa.Table(
        "zero_decimal_probe",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("amount", CanonicalDecimal(), nullable=False),
    )

    async with sqlite_engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(probe.insert().values(id=1, amount=Decimal("0E-1000000")))
        stored = await connection.exec_driver_sql(
            "SELECT amount FROM zero_decimal_probe WHERE id = 1"
        )

    assert stored.scalar_one() == "0"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_amount",
    [
        1.5,
        "1.5",
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("1E+1000000"),
        DecimalSubclass("1.5"),
    ],
)
async def test_exact_decimal_type_rejects_non_decimal_or_nonfinite_values(
    sqlite_engine: AsyncEngine,
    invalid_amount: object,
) -> None:
    metadata = sa.MetaData()
    probe = sa.Table(
        "invalid_decimal_probe",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("amount", CanonicalDecimal(), nullable=False),
    )
    async with sqlite_engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        with pytest.raises(StatementError):
            await connection.execute(probe.insert().values(id=1, amount=invalid_amount))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_timestamp",
    [
        datetime(2026, 7, 13, 23, 59, 58),
        datetime(2026, 7, 13, 19, 59, 58, tzinfo=timezone(-timedelta(hours=4))),
        DatetimeSubclass(2026, 7, 13, 23, 59, 58, tzinfo=UTC),
    ],
)
async def test_utc_datetime_type_rejects_naive_or_non_utc_values(
    sqlite_engine: AsyncEngine,
    invalid_timestamp: datetime,
) -> None:
    metadata = sa.MetaData()
    probe = sa.Table(
        "invalid_timestamp_probe",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("observed_at", UTCDateTime(), nullable=False),
    )
    async with sqlite_engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        with pytest.raises(StatementError):
            await connection.execute(probe.insert().values(id=1, observed_at=invalid_timestamp))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("type_", "invalid_value"),
    [
        (ExactBoolean(), 1),
        (ExactBoolean(), 1.0),
        (ExactBoolean(), Decimal("1")),
        (ExactNonNegativeInteger(), True),
        (ExactNonNegativeInteger(), "1"),
        (ExactNonNegativeInteger(), -1),
        (SHA256Digest(), "not-a-hash"),
        (SHA256Digest(), "A" * 64),
    ],
)
async def test_exact_safety_scalar_types_reject_invalid_bind_values(
    sqlite_engine: AsyncEngine,
    type_: sa.types.TypeEngine[object],
    invalid_value: object,
) -> None:
    metadata = sa.MetaData()
    probe = sa.Table(
        "invalid_safety_scalar_probe",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("value", type_, nullable=False),
    )
    async with sqlite_engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        with pytest.raises(StatementError):
            await connection.execute(probe.insert().values(id=1, value=invalid_value))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("table_name", "type_", "raw_value"),
    [
        ("corrupt_boolean_probe", ExactBoolean(), 2),
        ("corrupt_integer_probe", ExactNonNegativeInteger(), "abc"),
        ("corrupt_hash_probe", SHA256Digest(), "x" * 1000),
        ("corrupt_decimal_probe", CanonicalDecimal(), "1.0"),
        ("corrupt_timestamp_probe", UTCDateTime(), "2026-07-13T23:59:58+00:00"),
    ],
)
async def test_exact_safety_scalar_types_reject_corrupt_stored_values(
    sqlite_engine: AsyncEngine,
    table_name: str,
    type_: sa.types.TypeEngine[object],
    raw_value: object,
) -> None:
    metadata = sa.MetaData()
    probe = sa.Table(
        table_name,
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("value", type_, nullable=False),
    )
    async with sqlite_engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.exec_driver_sql(
            f"INSERT INTO {table_name} (id, value) VALUES (?, ?)",
            (1, raw_value),
        )
        with pytest.raises(PersistenceDataError):
            result = await connection.execute(sa.select(probe.c.value))
            result.scalar_one()
