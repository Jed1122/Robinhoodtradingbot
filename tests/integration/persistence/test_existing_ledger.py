"""Actual SQLite opening must preserve the research CLI's existing-file boundary."""

import os
import sqlite3

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from trading_bot.persistence import PersistenceConfigurationError, create_engine


def private_ledger(root, name="ledger.sqlite3"):
    root = root.resolve()
    root.chmod(0o700)
    path = root / name
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sentinel (value TEXT)")
    path.chmod(0o600)
    return path


@pytest.mark.asyncio
async def test_existing_engine_opens_exact_escaped_path_without_changing_policy(tmp_path):
    path = private_ledger(tmp_path, "ledger with spaces%25.sqlite3")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    engine = create_engine(f"sqlite+aiosqlite:///{path}", existing_file_descriptor=descriptor)
    try:
        assert engine.pool._pre_ping is False
        async with engine.connect() as connection:
            assert await connection.scalar(text("PRAGMA journal_mode")) == "wal"
            assert await connection.scalar(text("PRAGMA synchronous")) == 2
            assert await connection.scalar(text("PRAGMA foreign_keys")) == 1
            assert await connection.scalar(text("PRAGMA recursive_triggers")) == 1
            assert await connection.scalar(text("SELECT count(*) FROM sentinel")) == 0
        # A pooled checkout remains usable while the same private file is held.
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM sentinel")) == 0
        assert path.stat().st_ino == os.fstat(descriptor).st_ino
        assert path.stat().st_mode & 0o777 == 0o600
    finally:
        await engine.dispose()
        os.close(descriptor)


@pytest.mark.asyncio
@pytest.mark.parametrize("pooled", [False, True])
@pytest.mark.parametrize("change", ["disappear", "replace", "symlink", "mode", "parent"])
async def test_existing_engine_rechecks_before_connect_or_checkout_policy(
    tmp_path, monkeypatch, pooled, change
):
    from trading_bot.persistence import base

    path = private_ledger(tmp_path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    engine = create_engine(f"sqlite+aiosqlite:///{path}", existing_file_descriptor=descriptor)
    try:
        if pooled:
            async with engine.connect():
                pass
        policy_calls = []
        original = base._apply_sqlite_policy

        def policy(connection):
            policy_calls.append(True)
            return original(connection)

        monkeypatch.setattr(base, "_apply_sqlite_policy", policy)
        if change in {"disappear", "replace", "symlink"}:
            path.rename(path.with_name("retained.sqlite3"))
        if change == "replace":
            with sqlite3.connect(path) as connection:
                connection.execute("CREATE TABLE unrelated (value TEXT)")
            path.chmod(0o600)
        elif change == "symlink":
            path.symlink_to(path.with_name("retained.sqlite3"))
        elif change == "mode":
            path.chmod(0o640)
        elif change == "parent":
            path.parent.chmod(0o750)

        with pytest.raises((OperationalError, PersistenceConfigurationError)):
            async with engine.connect():
                pytest.fail("changed ledger must not be returned")
        assert policy_calls == []
        if change == "disappear":
            assert not path.exists()
        if change == "replace":
            with sqlite3.connect(path) as connection:
                assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)
    finally:
        await engine.dispose()
        os.close(descriptor)


def test_existing_engine_cannot_override_readwrite_only_uri(tmp_path):
    path = private_ledger(tmp_path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with pytest.raises(PersistenceConfigurationError):
            create_engine(
                f"sqlite+aiosqlite:///{path}?mode=rwc", existing_file_descriptor=descriptor
            )
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("descriptor", [True, -1, "0"])
def test_existing_engine_rejects_invalid_descriptor_without_opening(tmp_path, descriptor):
    path = private_ledger(tmp_path)
    with pytest.raises(PersistenceConfigurationError):
        create_engine(f"sqlite+aiosqlite:///{path}", existing_file_descriptor=descriptor)
