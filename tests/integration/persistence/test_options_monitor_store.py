"""Observation audit survives restart in a temporary real SQLite ledger."""

import json
import sqlite3

import pytest
from alembic import command
from sqlalchemy import select

from tests.integration.persistence.test_migrations import _seed_account
from tests.unit.reconciliation._options_fixtures import ACCOUNT
from tests.unit.reconciliation._options_fixtures import (
    offline_observation_boundary as offline_observation_boundary,
)
from tests.unit.runtime.test_options_monitor import Source, loaded, monitor
from trading_bot.domain import CodeHash
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.persistence.models import ReconciliationEventRow
from trading_bot.persistence.reconciliation import SqlReconciliationStore


@pytest.fixture
def monitor_database(
    alembic_config,
    database_path,
    database_url,
):
    command.upgrade(alembic_config, "head")
    with sqlite3.connect(database_path) as connection:
        _seed_account(connection, account_id=ACCOUNT)
    return database_path, database_url


async def test_monitor_persists_append_only_results_and_restart_never_resumes(monitor_database):
    database_path, database_url = monitor_database
    engine = create_engine(database_url)
    factory = async_session_factory(engine)
    store = SqlReconciliationStore(
        factory, config_hash=loaded().config_hash, code_hash=CodeHash("c" * 64)
    )
    m = monitor(store=store)
    assert (await m.cycle()).reconciliation_clean

    class Disconnected(Source):
        async def read(self, account_id):
            from dataclasses import replace

            return replace(await super().read(account_id), calendars=())

    assert not (await monitor(store=store, source=Disconnected()).cycle()).reconciliation_clean
    await engine.dispose()
    restarted = create_engine(database_url)
    try:
        factory = async_session_factory(restarted)
        async with factory() as session:
            rows = (await session.scalars(select(ReconciliationEventRow))).all()
            assert len(rows) == 2 and sum(row.clean for row in rows) == 1
            bad = next(row for row in rows if not row.clean)
            assert {item["code"] for item in json.loads(bad.differences_json)} == {
                "expiry_calendar_unverified"
            }
        resumed = monitor(
            store=SqlReconciliationStore(
                factory, config_hash=loaded().config_hash, code_hash=CodeHash("c" * 64)
            )
        )
        assert resumed.status().paused and resumed.status().last_observed_at is None
        with sqlite3.connect(database_path) as connection, pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM reconciliation_events")
    finally:
        await restarted.dispose()
