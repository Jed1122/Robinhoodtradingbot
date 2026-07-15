"""Alembic environment for the async, fail-closed durable ledger."""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.engine import Connection

from trading_bot.persistence import Base, create_engine

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    database_url = config.get_main_option("sqlalchemy.url")
    if database_url is None or not database_url.strip():
        raise RuntimeError("Alembic requires a nonempty sqlalchemy.url")
    return database_url


def run_migrations_offline() -> None:
    """Render migration SQL without constructing an application engine."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        transactional_ddl=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    connection.exec_driver_sql("BEGIN IMMEDIATE")
    try:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            transactional_ddl=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


async def _run_async_migrations() -> None:
    engine = create_engine(_database_url())
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    """Run migrations through the same validated engine policy as the application."""
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
