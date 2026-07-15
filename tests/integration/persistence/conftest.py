"""File-backed SQLite fixtures for persistence integration tests."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine

from trading_bot.persistence import create_engine

ROOT = Path(__file__).parents[3]


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "ledger.sqlite3"


@pytest.fixture
def database_url(database_path: Path) -> str:
    return f"sqlite+aiosqlite:///{database_path}"


@pytest.fixture
def alembic_config(database_url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture
async def sqlite_engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database_url)
    try:
        yield engine
    finally:
        await engine.dispose()
