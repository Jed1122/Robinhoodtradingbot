"""Async engine policy and exact SQLite persistence primitives."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast
from weakref import WeakSet

from sqlalchemy import CheckConstraint, MetaData, String, Text, event
from sqlalchemy.engine import Dialect, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, MappedColumn, mapped_column
from sqlalchemy.types import TypeDecorator, UserDefinedType

from trading_bot.clock import InvalidTimestamp, require_utc

ID_LENGTH = 255
HASH_LENGTH = 64
DECIMAL_TEXT_MAX_LENGTH = 512
NAME_LENGTH = 128
PROVIDER_LENGTH = 64
STATE_LENGTH = 64

_VALIDATED_ENGINES: WeakSet[AsyncEngine] = WeakSet()
_VALIDATED_SESSION_FACTORIES: WeakSet[async_sessionmaker[AsyncSession]] = WeakSet()

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class PersistenceConfigurationError(RuntimeError):
    """Raised when the durable database cannot meet the configured safety policy."""


class PersistenceDataError(ValueError):
    """Raised when persisted data is not in its canonical exact representation."""


class Base(DeclarativeBase):
    """Declarative base shared by the complete durable ledger."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _canonical_decimal_text(value: Decimal) -> str:
    if type(value) is not Decimal or not value.is_finite():
        raise PersistenceDataError("trading values must be finite exact Decimal instances")
    if value == 0:
        return "0"
    if (
        len(value.as_tuple().digits) > DECIMAL_TEXT_MAX_LENGTH
        or abs(value.adjusted()) > DECIMAL_TEXT_MAX_LENGTH
    ):
        raise PersistenceDataError("trading value exceeds canonical Decimal storage bounds")
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if len(rendered) > DECIMAL_TEXT_MAX_LENGTH:
        raise PersistenceDataError("trading value exceeds canonical Decimal storage bounds")
    return rendered


class _SQLiteTextStorage(UserDefinedType[str]):
    """Declare no SQLite affinity while leaving DBAPI text values untouched."""

    cache_ok = True

    def get_col_spec(self, **kwargs: Any) -> str:
        del kwargs
        return "BLOB"


class CanonicalDecimal(TypeDecorator[Decimal]):
    """Store exact trading values as canonical text, never SQLite REAL."""

    impl = _SQLiteTextStorage
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> str | None:
        del dialect
        if value is None:
            return None
        return _canonical_decimal_text(value)

    def process_result_value(self, value: object, dialect: Dialect) -> Decimal | None:
        del dialect
        if value is None:
            return None
        if type(value) is not str:
            raise PersistenceDataError("stored trading values must use canonical text")
        try:
            parsed = Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise PersistenceDataError("stored trading value is not a Decimal") from exc
        if _canonical_decimal_text(parsed) != value:
            raise PersistenceDataError("stored trading value is not canonical")
        return parsed


def _canonical_utc_text(value: datetime) -> str:
    try:
        canonical = require_utc(value)
    except InvalidTimestamp as exc:
        raise PersistenceDataError("timestamps must be exact UTC datetimes") from exc
    return canonical.isoformat(timespec="microseconds").replace("+00:00", "Z")


class UTCDateTime(TypeDecorator[datetime]):
    """Store timestamps as canonical UTC text to preserve timezone semantics in SQLite."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> str | None:
        del dialect
        if value is None:
            return None
        return _canonical_utc_text(value)

    def process_result_value(self, value: object, dialect: Dialect) -> datetime | None:
        del dialect
        if value is None:
            return None
        if type(value) is not str or not value.endswith("Z"):
            raise PersistenceDataError("stored timestamps must use canonical UTC text")
        try:
            parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
        except ValueError as exc:
            raise PersistenceDataError("stored timestamp is not valid ISO-8601 UTC") from exc
        if _canonical_utc_text(parsed) != value:
            raise PersistenceDataError("stored timestamp is not canonical")
        return parsed


def _validate_sha256_digest(value: object, *, stored: bool) -> str:
    if (
        type(value) is not str
        or len(value) != HASH_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        source = "stored" if stored else "bound"
        raise PersistenceDataError(f"{source} digest must be lowercase SHA-256 hex")
    return value


class SHA256Digest(TypeDecorator[str]):
    """Store only exact lowercase 64-character SHA-256 hex digests."""

    impl = String(HASH_LENGTH)
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        del dialect
        if value is None:
            return None
        return _validate_sha256_digest(value, stored=False)

    def process_result_value(self, value: object, dialect: Dialect) -> str | None:
        del dialect
        if value is None:
            return None
        return _validate_sha256_digest(value, stored=True)


class _SQLiteIntegerStorage(UserDefinedType[int]):
    """Declare no SQLite affinity while leaving DBAPI integer values untouched."""

    cache_ok = True

    def get_col_spec(self, **kwargs: Any) -> str:
        del kwargs
        return "BLOB"


class ExactBoolean(TypeDecorator[bool]):
    """Store exact Python booleans as constrained SQLite integers without coercion."""

    # BLOB affinity leaves the bound storage class untouched, allowing the
    # database CHECK to distinguish integer 1 from text "1" and REAL 1.0.
    impl = _SQLiteIntegerStorage
    cache_ok = True

    def process_bind_param(self, value: bool | None, dialect: Dialect) -> int | None:
        del dialect
        if value is None:
            return None
        if type(value) is not bool:
            raise PersistenceDataError("bound boolean must be an exact bool")
        return int(value)

    def process_result_value(self, value: object, dialect: Dialect) -> bool | None:
        del dialect
        if value is None:
            return None
        if type(value) is not int or value not in (0, 1):
            raise PersistenceDataError("stored boolean must be the integer 0 or 1")
        return bool(value)


class ExactNonNegativeInteger(TypeDecorator[int]):
    """Store exact nonnegative Python integers without SQLite affinity coercion."""

    # BLOB is intentionally used as SQLite's no-coercion affinity. Values are
    # still stored with SQLite's INTEGER storage class and checked below.
    impl = _SQLiteIntegerStorage
    cache_ok = True

    def process_bind_param(self, value: int | None, dialect: Dialect) -> int | None:
        del dialect
        if value is None:
            return None
        if type(value) is not int or value < 0:
            raise PersistenceDataError("bound integer must be an exact nonnegative int")
        return value

    def process_result_value(self, value: object, dialect: Dialect) -> int | None:
        del dialect
        if value is None:
            return None
        if type(value) is not int or value < 0:
            raise PersistenceDataError("stored integer must be an exact nonnegative int")
        return value


def _nullable_check(column_name: str, required_expression: str, *, nullable: bool) -> str:
    if nullable:
        return f"{column_name} IS NULL OR ({required_expression})"
    return required_expression


def _canonical_decimal_check_expression(column_name: str) -> str:
    unsigned = f"ltrim({column_name}, '-')"
    dot = f"instr({unsigned}, '.')"
    integer_part = f"substr({unsigned}, 1, {dot} - 1)"
    fractional_part = f"substr({unsigned}, {dot} + 1)"
    return (
        f"typeof({column_name}) = 'text' AND length({column_name}) > 0 "
        f"AND length({column_name}) <= {DECIMAL_TEXT_MAX_LENGTH} "
        f"AND length(CAST({column_name} AS BLOB)) = length({column_name}) "
        f"AND {column_name} NOT GLOB '*[^0-9.-]*' "
        f"AND length({column_name}) - length(replace({column_name}, '-', '')) <= 1 "
        f"AND (instr({column_name}, '-') = 0 OR instr({column_name}, '-') = 1) "
        f"AND length({column_name}) - length(replace({column_name}, '.', '')) <= 1 "
        f"AND ({column_name} = '0' OR ({unsigned} <> '0' AND ("
        f"({dot} = 0 AND {unsigned} GLOB '[1-9]*' "
        f"AND {unsigned} NOT GLOB '*[^0-9]*') OR ("
        f"{dot} > 1 AND {dot} < length({unsigned}) "
        f"AND ({integer_part} = '0' OR ({integer_part} GLOB '[1-9]*' "
        f"AND {integer_part} NOT GLOB '*[^0-9]*')) "
        f"AND {fractional_part} NOT GLOB '*[^0-9]*' "
        f"AND substr({unsigned}, -1, 1) GLOB '[1-9]'))))"
    )


def _canonical_utc_check_expression(column_name: str) -> str:
    pattern = (
        "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T"
        "[0-9][0-9]:[0-9][0-9]:[0-9][0-9]."
        "[0-9][0-9][0-9][0-9][0-9][0-9]Z"
    )
    normalized = f"strftime('%Y-%m-%dT%H:%M:%S', {column_name})"
    return (
        f"typeof({column_name}) = 'text' AND length({column_name}) = 27 "
        f"AND length(CAST({column_name} AS BLOB)) = 27 "
        f"AND {column_name} GLOB '{pattern}' "
        f"AND substr({column_name}, 1, 4) <> '0000' "
        f"AND substr({column_name}, 12, 2) BETWEEN '00' AND '23' "
        f"AND {normalized} IS NOT NULL "
        f"AND {normalized} = substr({column_name}, 1, 19)"
    )


def canonical_decimal_column(
    column_name: str,
    *,
    nullable: bool = False,
) -> MappedColumn[Decimal]:
    """Build an exact Decimal column with canonical SQLite text enforcement."""
    return mapped_column(
        CanonicalDecimal(),
        CheckConstraint(
            _nullable_check(
                column_name,
                _canonical_decimal_check_expression(column_name),
                nullable=nullable,
            ),
            name=f"{column_name}_canonical_decimal",
        ),
        nullable=nullable,
    )


def utc_datetime_column(
    column_name: str,
    *,
    nullable: bool = False,
) -> MappedColumn[datetime]:
    """Build an exact UTC timestamp column with canonical SQLite text enforcement."""
    return mapped_column(
        UTCDateTime(),
        CheckConstraint(
            _nullable_check(
                column_name,
                _canonical_utc_check_expression(column_name),
                nullable=nullable,
            ),
            name=f"{column_name}_canonical_utc",
        ),
        nullable=nullable,
    )


def sha256_column(column_name: str, *, nullable: bool = False) -> MappedColumn[str]:
    """Build an ORM digest column with both bind-time and database constraints."""
    expression = (
        f"typeof({column_name}) = 'text' AND length({column_name}) = {HASH_LENGTH} "
        f"AND length(CAST({column_name} AS BLOB)) = {HASH_LENGTH} "
        f"AND {column_name} NOT GLOB '*[^0-9a-f]*'"
    )
    return mapped_column(
        SHA256Digest(),
        CheckConstraint(
            _nullable_check(column_name, expression, nullable=nullable),
            name=f"{column_name}_sha256",
        ),
        nullable=nullable,
    )


def exact_boolean_column(column_name: str, *, nullable: bool = False) -> MappedColumn[bool]:
    """Build an ORM boolean column that rejects every representation except 0 or 1."""
    expression = f"typeof({column_name}) = 'integer' AND {column_name} IN (0, 1)"
    return mapped_column(
        ExactBoolean(),
        CheckConstraint(
            _nullable_check(column_name, expression, nullable=nullable),
            name=f"{column_name}_exact_boolean",
        ),
        nullable=nullable,
    )


def exact_nonnegative_integer_column(
    column_name: str,
    *,
    nullable: bool = False,
) -> MappedColumn[int]:
    """Build an ORM integer column that rejects text, booleans, floats, and negatives."""
    expression = f"typeof({column_name}) = 'integer' AND {column_name} >= 0"
    return mapped_column(
        ExactNonNegativeInteger(),
        CheckConstraint(
            _nullable_check(column_name, expression, nullable=nullable),
            name=f"{column_name}_nonnegative_integer",
        ),
        nullable=nullable,
    )


def _apply_sqlite_policy(dbapi_connection: object) -> None:
    cursor: Any | None = None
    operation_error: Exception | None = None
    journal_row: object | None = None
    foreign_keys_row: object | None = None
    synchronous_row: object | None = None
    recursive_triggers_row: object | None = None
    try:
        cursor = cast(Any, dbapi_connection).cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA recursive_triggers=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        journal_row = cursor.fetchone()
        cursor.execute("PRAGMA synchronous=FULL")
        cursor.execute("PRAGMA foreign_keys")
        foreign_keys_row = cursor.fetchone()
        cursor.execute("PRAGMA synchronous")
        synchronous_row = cursor.fetchone()
        cursor.execute("PRAGMA recursive_triggers")
        recursive_triggers_row = cursor.fetchone()
    except Exception as exc:
        operation_error = exc

    close_error: Exception | None = None
    if cursor is not None:
        try:
            cursor.close()
        except Exception as exc:
            close_error = exc

    if operation_error is not None:
        raise PersistenceConfigurationError(
            "SQLite connection safety policy could not be applied"
        ) from operation_error
    if close_error is not None:
        raise PersistenceConfigurationError(
            "SQLite connection safety policy cursor could not be closed"
        ) from close_error

    journal_mode = "" if journal_row is None else str(cast(Any, journal_row)[0]).lower()
    foreign_keys = None if foreign_keys_row is None else cast(Any, foreign_keys_row)[0]
    synchronous = None if synchronous_row is None else cast(Any, synchronous_row)[0]
    recursive_triggers = (
        None if recursive_triggers_row is None else cast(Any, recursive_triggers_row)[0]
    )
    if journal_mode != "wal":
        raise PersistenceConfigurationError("SQLite connection did not enter WAL mode")
    if foreign_keys != 1:
        raise PersistenceConfigurationError("SQLite foreign-key enforcement is disabled")
    if synchronous != 2:
        raise PersistenceConfigurationError("SQLite synchronous mode is not FULL")
    if recursive_triggers != 1:
        raise PersistenceConfigurationError("SQLite recursive-trigger enforcement is disabled")


def create_engine(database_url: str) -> AsyncEngine:
    """Create an async engine whose SQLite connections fail closed without WAL safety."""
    if type(database_url) is not str or not database_url.strip():
        raise PersistenceConfigurationError("database_url must be a nonempty exact string")
    try:
        url = make_url(database_url)
    except (SQLAlchemyError, TypeError, ValueError) as exc:
        raise PersistenceConfigurationError("database_url is invalid") from exc
    if url.drivername != "sqlite+aiosqlite":
        raise PersistenceConfigurationError("database_url must use sqlite+aiosqlite")

    try:
        engine = create_async_engine(
            database_url,
            pool_pre_ping=True,
            hide_parameters=True,
        )
    except (ImportError, SQLAlchemyError, TypeError, ValueError) as exc:
        raise PersistenceConfigurationError("database_url cannot create an async engine") from exc

    @event.listens_for(engine.sync_engine, "connect")
    def configure_connection(dbapi_connection: object, connection_record: object) -> None:
        del connection_record
        _apply_sqlite_policy(dbapi_connection)

    @event.listens_for(engine.sync_engine, "checkout")
    def validate_checkout(
        dbapi_connection: object,
        connection_record: object,
        connection_proxy: object,
    ) -> None:
        del connection_record, connection_proxy
        _apply_sqlite_policy(dbapi_connection)

    _VALIDATED_ENGINES.add(engine)
    return engine


def async_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create safe async sessions bound to one validated engine."""
    if not isinstance(engine, AsyncEngine) or engine not in _VALIDATED_ENGINES:
        raise PersistenceConfigurationError("engine must be a validated persistence AsyncEngine")
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )
    _VALIDATED_SESSION_FACTORIES.add(factory)
    return factory


def _require_validated_session_factory(
    factory: object,
) -> async_sessionmaker[AsyncSession]:
    """Reject unbranded or rebound factories at each transaction boundary."""
    if not isinstance(factory, async_sessionmaker) or factory not in _VALIDATED_SESSION_FACTORIES:
        raise PersistenceConfigurationError(
            "session factory must come from the validated persistence factory"
        )
    bind = factory.kw.get("bind")
    if not isinstance(bind, AsyncEngine) or bind not in _VALIDATED_ENGINES:
        raise PersistenceConfigurationError("session factory is not bound to a validated engine")
    if (
        set(factory.kw) != {"bind", "autoflush", "expire_on_commit"}
        or factory.class_ is not AsyncSession
        or factory.kw.get("autoflush") is not False
        or factory.kw.get("expire_on_commit") is not False
        or bind.sync_engine.hide_parameters is not True
    ):
        raise PersistenceConfigurationError("session factory safety options were modified")
    return factory
