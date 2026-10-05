"""Real fictional SQLite joint-state tests; zero broker/provider calls."""

import asyncio
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.persistence.test_owned_order_journal import (
    event as owned_fact,
)
from tests.integration.persistence.test_owned_order_journal import (
    owned_engine as _owned_engine_fixture,
)
from tests.integration.persistence.test_owned_order_journal import (
    owned_schema as _owned_schema_fixture,
)
from tests.integration.persistence.test_unit_of_work import (
    HASH_A,
    HASH_C,
    NOW,
    _make_broker_order,
    _make_intent,
    _make_uow,
)
from trading_bot.accounting import (
    Bind,
    EconomicError,
    EconomicEvent,
    Execution,
    Opening,
    Reserve,
)
from trading_bot.domain import AccountId, ConfigHash, DataHash
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.persistence.models import FillRow, OwnedOrderEventRow
from trading_bot.persistence.unit_of_work import UnitOfWorkStateError

owned_engine = _owned_engine_fixture
owned_schema = _owned_schema_fixture


def e(payload, index):
    return EconomicEvent(
        f"economics-{index}",
        AccountId("account-1"),
        NOW + timedelta(seconds=index),
        DataHash(HASH_C),
        ConfigHash(HASH_A),
        payload,
    )


def setup_events():
    i = _make_intent()
    return (
        e(Opening(i.instrument_id, Decimal("500")), 0),
        e(Reserve(i, "episode-1", Decimal("0.10"), Decimal("13.225")), 1),
        e(Bind(_make_broker_order(i)), 2),
    )


def execution_event():
    fact = owned_fact()
    at = NOW + timedelta(seconds=3)
    fact = replace(fact, occurred_at=at, fill=replace(fact.fill, occurred_at=at))
    return e(Execution(fact), 3)


def owner(uow):
    assert hasattr(uow, "economics"), "joint economic repository not implemented"
    return uow.economics


async def seed_economics(engine):
    async with _make_uow(engine) as uow:
        for event in setup_events():
            assert await owner(uow).append(event)
        await uow.commit()


async def test_joint_fill_commit_restart_preserves_original_and_signed_cash(
    owned_engine, database_url
):
    await seed_economics(owned_engine)
    async with _make_uow(owned_engine) as uow:
        assert await owner(uow).append(execution_event())
        s = await owner(uow).get(AccountId("account-1"))
        assert s.settled_cash == Decimal("500")
        assert s.book_cash == Decimal("497.49")
        assert s.position.quantity == Decimal("0.25")
        assert s.orders[0].cash_hold == Decimal("10.59")
        assert s.trial.reserved_risk == Decimal("13.225")
        await uow.commit()
    independent = create_engine(database_url)
    try:
        async with _make_uow(independent) as restarted:
            assert not await owner(restarted).append(execution_event())
            assert (await owner(restarted).get(AccountId("account-1"))).book_cash == Decimal(
                "497.49"
            )
            await restarted.commit()
        async with async_session_factory(independent)() as session:
            assert await session.scalar(select(func.count()).select_from(FillRow)) == 1
            assert await session.scalar(select(func.count()).select_from(OwnedOrderEventRow)) == 1
    finally:
        await independent.dispose()


async def test_exit_without_commit_rolls_back_both_effects(owned_engine):
    await seed_economics(owned_engine)
    async with _make_uow(owned_engine) as uow:
        assert await owner(uow).append(execution_event())
    async with _make_uow(owned_engine) as restarted:
        s = await owner(restarted).get(AccountId("account-1"))
        assert s.book_cash == Decimal("500") and s.position.quantity == 0
        assert (
            await restarted.orders.get_broker_order(execution_event().payload.event.order_id)
        ).filled_quantity == 0


async def test_caught_invalid_append_cannot_commit_prior_execution_staging(owned_engine):
    await seed_economics(owned_engine)
    async with _make_uow(owned_engine) as uow:
        assert await owner(uow).append(execution_event())
        with pytest.raises(EconomicError):
            await owner(uow).append(replace(execution_event(), source_hash=DataHash("b" * 64)))
        with pytest.raises(UnitOfWorkStateError):
            await uow.commit()
    async with _make_uow(owned_engine) as restarted:
        assert (await owner(restarted).get(AccountId("account-1"))).book_cash == Decimal("500")


async def test_unpaired_owned_fact_is_not_adopted_on_read_or_retry(owned_engine):
    await seed_economics(owned_engine)
    async with _make_uow(owned_engine) as unpaired:
        await unpaired.orders.record_event(execution_event().payload.event)
        await unpaired.commit()
    async with _make_uow(owned_engine) as restarted:
        with pytest.raises(EconomicError):
            await owner(restarted).get(AccountId("account-1"))
        with pytest.raises(UnitOfWorkStateError):
            await restarted.commit()
    async with _make_uow(owned_engine) as restarted:
        with pytest.raises(EconomicError):
            await owner(restarted).append(execution_event())


async def test_missing_history_is_missing_not_zero_or_adopted_cash(owned_engine):
    async with _make_uow(owned_engine) as uow:
        assert await owner(uow).get(AccountId("account-1")) is None


async def test_wrong_configuration_fails_before_any_economic_history(owned_engine):
    async with _make_uow(owned_engine) as uow:
        wrong = replace(setup_events()[0], config_hash=ConfigHash("b" * 64))
        with pytest.raises(EconomicError):
            await owner(uow).append(wrong)
        with pytest.raises(UnitOfWorkStateError):
            await uow.commit()
    async with _make_uow(owned_engine) as restarted:
        assert await owner(restarted).get(AccountId("account-1")) is None


@pytest.mark.parametrize(
    "point", ["FillRow", "OrderTransitionRow", "OwnedOrderEventRow", "OwnedEconomicEventRow"]
)
async def test_any_staging_failure_then_caught_error_cannot_commit_half(
    owned_engine, monkeypatch, point
):
    await seed_economics(owned_engine)
    original = AsyncSession.flush

    async def fail_after_flush(self, objects=None):
        await original(self, objects)
        if objects and any(type(row).__name__ == point for row in objects):
            raise RuntimeError("fixture-only staged failure")

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "flush", fail_after_flush)
        async with _make_uow(owned_engine) as uow:
            with pytest.raises(EconomicError):
                await owner(uow).append(execution_event())
            with pytest.raises(UnitOfWorkStateError):
                await uow.commit()
    async with _make_uow(owned_engine) as restarted:
        s = await owner(restarted).get(AccountId("account-1"))
        assert s.book_cash == Decimal("500") and s.position.quantity == 0
        assert (
            await restarted.orders.get_broker_order(execution_event().payload.event.order_id)
        ).filled_quantity == 0


async def test_cancelled_append_latches_transaction_before_rollback(owned_engine, monkeypatch):
    await seed_economics(owned_engine)
    original = AsyncSession.flush

    async def cancelled(self, objects=None):
        await original(self, objects)
        if objects and any(type(row).__name__ == "OwnedOrderEventRow" for row in objects):
            raise asyncio.CancelledError()

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "flush", cancelled)
        async with _make_uow(owned_engine) as uow:
            with pytest.raises(asyncio.CancelledError):
                await owner(uow).append(execution_event())
            with pytest.raises(UnitOfWorkStateError):
                await uow.commit()
    async with _make_uow(owned_engine) as restarted:
        assert (await owner(restarted).get(AccountId("account-1"))).book_cash == Decimal("500")


@pytest.mark.parametrize("mutation", ["UPDATE", "DELETE", "REPLACE", "ROWID"])
async def test_append_only_journal_denies_sql_mutation(owned_engine, database_path, mutation):
    await seed_economics(owned_engine)
    with closing(sqlite3.connect(database_path)) as connection:
        if mutation == "UPDATE":
            sql = "UPDATE owned_economic_events SET payload_json='{}' WHERE sequence=0"
        elif mutation == "DELETE":
            sql = "DELETE FROM owned_economic_events WHERE sequence=0"
        else:
            row = connection.execute(
                "SELECT * FROM owned_economic_events WHERE sequence=0"
            ).fetchone()
            columns = [r[1] for r in connection.execute("PRAGMA table_info(owned_economic_events)")]
            if mutation == "ROWID":
                columns.insert(0, "rowid")
                row = (-1, *row)
            sql = (
                f"INSERT OR REPLACE INTO owned_economic_events ({','.join(columns)}) "
                f"VALUES ({','.join('?' for _ in columns)})"
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable economic history"):
            connection.execute(sql, row if mutation in {"REPLACE", "ROWID"} else ())
    async with _make_uow(owned_engine) as restarted:
        assert (await owner(restarted).get(AccountId("account-1"))).available_cash == Decimal(
            "486.775"
        )


@pytest.mark.parametrize(
    "field,value",
    [("event_hash", "d" * 64), ("owned_event_id", None), ("intent_id", None), ("order_id", None)],
)
async def test_corrupt_joint_link_denies_even_with_rehashed_row(
    owned_engine, database_path, field, value
):
    from trading_bot.persistence.models import OwnedEconomicEventRow
    from trading_bot.persistence.owned_economic_journal import _hash

    await seed_economics(owned_engine)
    async with _make_uow(owned_engine) as uow:
        await owner(uow).append(execution_event())
        await uow.commit()
    async with async_session_factory(owned_engine)() as session:
        row = await session.get(OwnedEconomicEventRow, "economics-3")
        setattr(row, field, value)
        digest = value if field == "event_hash" else _hash(row)
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("DROP TRIGGER trg_owned_economic_update")
        connection.execute(
            f"UPDATE owned_economic_events SET {field}=?, event_hash=? WHERE id='economics-3'",
            (value, digest),
        )
        connection.commit()
    async with _make_uow(owned_engine) as restarted:
        with pytest.raises(EconomicError):
            await owner(restarted).get(AccountId("account-1"))
        with pytest.raises(UnitOfWorkStateError):
            await restarted.commit()


async def test_concurrent_identical_fill_applies_money_at_most_once(owned_engine):
    await seed_economics(owned_engine)

    async def append_once():
        try:
            async with _make_uow(owned_engine) as uow:
                applied = await owner(uow).append(execution_event())
                await uow.commit()
                return applied
        except EconomicError:
            return None

    results = await asyncio.gather(append_once(), append_once())
    assert sum(r is True for r in results) == 1
    async with _make_uow(owned_engine) as restarted:
        assert (await owner(restarted).get(AccountId("account-1"))).book_cash == Decimal("497.49")


@pytest.mark.parametrize(
    "module", ["trading_bot.persistence.unit_of_work", "trading_bot.accounting"]
)
def test_fresh_process_import_keeps_bootstrap_cycle_broken(module):
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"], capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr.decode()


async def test_nonempty_economic_history_refuses_downgrade(owned_engine, alembic_config):
    from alembic import command

    await seed_economics(owned_engine)
    await owned_engine.dispose()
    with pytest.raises(RuntimeError, match="cannot downgrade nonempty economic history"):
        await asyncio.to_thread(command.downgrade, alembic_config, "0009_owned_order_lifecycle")


async def test_registered_secret_is_denied_before_encoder(owned_engine, monkeypatch):
    import trading_bot.logging as logging_module
    import trading_bot.persistence.owned_economic_journal as module
    from trading_bot.logging import SecretRegistry

    monkeypatch.setattr(logging_module, "_REGISTRY_STATE", logging_module._RegistryState())
    SecretRegistry().register("b" * 64)
    original = module.encode_economic_event

    def encoder(event):
        assert event.source_hash != "b" * 64, "secret reached encoder"
        return original(event)

    monkeypatch.setattr(module, "encode_economic_event", encoder)
    async with _make_uow(owned_engine) as uow:
        with pytest.raises(EconomicError):
            await owner(uow).append(replace(setup_events()[0], source_hash=DataHash("b" * 64)))
        with pytest.raises(UnitOfWorkStateError):
            await uow.commit()
