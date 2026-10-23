"""Rejected physical connections must not outlive their owning event loop."""

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import aiosqlite
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from trading_bot.persistence import PersistenceConfigurationError, base, create_engine


@pytest.fixture
async def driver_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[list[aiosqlite.Connection]]:
    """Observe real driver allocation and clean up even while the regression is RED."""
    connections: list[aiosqlite.Connection] = []
    connect = aiosqlite.connect
    close = aiosqlite.Connection.close

    def capture(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(aiosqlite, "connect", capture)
    try:
        yield connections
    finally:
        for connection in connections:
            await close(connection)
            await asyncio.to_thread(connection._thread.join, 1)
            assert not connection._thread.is_alive(), "test must not leave a driver worker behind"


async def assert_driver_closed(connections: list[aiosqlite.Connection]) -> None:
    assert len(connections) == 1
    connection = connections[0]
    await asyncio.to_thread(connection._thread.join, 1)
    assert (connection._connection is None, connection._thread.is_alive()) == (True, False)


@pytest.mark.asyncio
async def test_wal_rejection_closes_new_driver_and_stops_worker(driver_connections) -> None:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    try:
        with pytest.raises(PersistenceConfigurationError, match="did not enter WAL"):
            async with engine.connect():
                pytest.fail("a database without WAL must never be returned")
    finally:
        await engine.dispose()

    await assert_driver_closed(driver_connections)


@pytest.mark.asyncio
async def test_identity_rejection_closes_new_driver_before_policy(
    tmp_path: Path, driver_connections
) -> None:
    root = tmp_path.resolve()
    root.chmod(0o700)
    path = root / "ledger.sqlite3"
    path.touch(mode=0o600)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    engine = create_engine(f"sqlite+aiosqlite:///{path}", existing_file_descriptor=descriptor)
    try:
        path.chmod(0o640)
        with pytest.raises(PersistenceConfigurationError, match="existing SQLite ledger changed"):
            async with engine.connect():
                pytest.fail("a changed private ledger must never be returned")
        assert path.stat().st_size == 0, "policy must not write WAL to the rejected ledger"
    finally:
        await engine.dispose()
        os.close(descriptor)

    await assert_driver_closed(driver_connections)


@pytest.mark.asyncio
@pytest.mark.parametrize("primary_type", [PersistenceConfigurationError, asyncio.CancelledError])
@pytest.mark.parametrize("cleanup_type", [OSError, asyncio.CancelledError])
async def test_failed_connect_preserves_original_error_when_driver_close_raises(
    monkeypatch: pytest.MonkeyPatch,
    driver_connections,
    primary_type: Callable[[str], BaseException],
    cleanup_type: Callable[[str], BaseException],
) -> None:
    primary = primary_type("original connection rejection")
    cause = ValueError("original policy cause")
    cleanup = cleanup_type("secondary close failure")
    close = aiosqlite.Connection.close

    def reject(_connection: object) -> None:
        raise primary from cause

    async def close_then_raise(connection: aiosqlite.Connection) -> None:
        await close(connection)
        raise cleanup

    monkeypatch.setattr(base, "_apply_sqlite_policy", reject)
    monkeypatch.setattr(aiosqlite.Connection, "close", close_then_raise)
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    try:
        with pytest.raises(type(primary)) as captured:
            async with engine.connect():
                pytest.fail("the original connection rejection must propagate")
        assert captured.value is primary
        assert captured.value.__cause__ is cause
    finally:
        await engine.dispose()

    await assert_driver_closed(driver_connections)


@pytest.mark.asyncio
async def test_successful_policy_and_pooled_checkout_keep_driver_until_disposal(
    tmp_path: Path, driver_connections
) -> None:
    engine: AsyncEngine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'ledger.sqlite3'}")
    try:
        for _ in range(2):
            async with engine.connect() as connection:
                assert await connection.scalar(text("PRAGMA journal_mode")) == "wal"
                assert await connection.scalar(text("PRAGMA foreign_keys")) == 1
                assert await connection.scalar(text("PRAGMA synchronous")) == 2
                assert await connection.scalar(text("PRAGMA recursive_triggers")) == 1
                assert await connection.scalar(text("SELECT 42")) == 42
            assert len(driver_connections) == 1
            assert driver_connections[0]._connection is not None
            assert driver_connections[0]._thread.is_alive()
    finally:
        await engine.dispose()

    await assert_driver_closed(driver_connections)
