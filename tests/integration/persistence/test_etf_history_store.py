"""Atomic fixture-account replay; no production state or broker transports."""

import importlib
import sqlite3
from dataclasses import replace
from datetime import timedelta

import pytest
from alembic import command
from sqlalchemy import event as sql_event
from sqlalchemy import select

from tests.integration.persistence.test_execution_lease import Clock
from tests.integration.persistence.test_migrations import _seed_account
from tests.unit.simulation.test_etf_account import NOW, D, episode_events, request
from trading_bot.domain import AccountId
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.persistence.lease import LeaseRepository
from trading_bot.persistence.models import EtfReplayEventRow
from trading_bot.simulation.etf_account import replay_etf_account


def store_type():
    try:
        return importlib.import_module("trading_bot.persistence.etf_history_store").EtfHistoryStore
    except ModuleNotFoundError:
        pytest.fail("Transactional ETF account replay store is missing")


@pytest.fixture
def etf_url(alembic_config, database_path, database_url):
    command.upgrade(alembic_config, "head")
    with sqlite3.connect(database_path) as connection:
        _seed_account(connection, account_id="etf-offline")
    return database_url


async def test_reopened_store_reconstructs_partial_cash_and_trial_reservation(etf_url):
    engine = create_engine(etf_url)
    factory = async_session_factory(engine)
    clock = Clock()
    lease = await LeaseRepository(factory, clock).acquire(AccountId("etf-offline"), owner="fixture")
    store = store_type()(factory, clock)
    original = request(episode_events())
    await store.append_event(original, lease, expected_cursor=0, event=original.events[0])
    prefix = await store.append_event(original, lease, expected_cursor=1, event=original.events[1])
    assert prefix.state.cash == D("489.99") and prefix.state.trial.reserved_risk == D("10.02")
    assert prefix.cursor == 2 and prefix.state.paused
    await engine.dispose()
    restarted = create_engine(etf_url)
    restored = await store_type()(async_session_factory(restarted), clock).restore(original)
    assert restored == prefix
    await restarted.dispose()


async def test_reopened_store_preserves_ambiguous_pending_submission(etf_url):
    from tests.unit.simulation.test_etf_pending import pending, status
    from trading_bot.domain import OrderEvent, OrderState
    from trading_bot.simulation.etf_account import admit_etf_pending_intent

    engine = create_engine(etf_url)
    factory = async_session_factory(engine)
    clock = Clock()
    lease = await LeaseRepository(factory, clock).acquire(AccountId("etf-offline"), owner="fixture")
    original = request((pending(), status(OrderEvent.BROKER_AMBIGUOUS)))
    store = store_type()(factory, clock)
    for cursor, item in enumerate(original.events):
        checkpoint = await store.append_event(original, lease, expected_cursor=cursor, event=item)
    await engine.dispose()
    restarted = create_engine(etf_url)
    restored = await store_type()(async_session_factory(restarted), clock).restore(original)
    assert restored == checkpoint and restored.state.paused
    assert restored.state.orders[0].order.state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION
    assert restored.state.reserved_cash == restored.state.trial.reserved_risk == D("10.02")
    assert restored.state.cash == D("500") and restored.state.shares == 0
    assert not admit_etf_pending_intent(original, original.events[0]).allowed
    await restarted.dispose()


async def test_complete_replay_is_atomic_idempotent_and_identity_bound(etf_url):
    engine = create_engine(etf_url)
    factory = async_session_factory(engine)
    clock = Clock()
    lease = await LeaseRepository(factory, clock).acquire(AccountId("etf-offline"), owner="fixture")
    store = store_type()(factory, clock)
    original = request(episode_events())
    for cursor, item in enumerate(original.events):
        checkpoint = await store.append_event(original, lease, expected_cursor=cursor, event=item)
    assert checkpoint.state == replay_etf_account(original)
    assert (
        await store.append_event(original, lease, expected_cursor=7, event=original.events[7])
        == checkpoint
    )
    wrong = replace(
        original,
        events=(*original.events[:-1], replace(original.events[-1], fill_ids=("missing",))),
    )
    with pytest.raises(ValueError, match="etf_store_invalid"):
        await store.restore(wrong)
    with pytest.raises(ValueError, match="etf_store_invalid"):
        await store.append_event(original, lease, expected_cursor=0, event=original.events[1])
    await engine.dispose()


async def test_commit_failure_preserves_previous_account_cursor(etf_url):
    engine = create_engine(etf_url)
    factory = async_session_factory(engine)
    clock = Clock()
    lease = await LeaseRepository(factory, clock).acquire(AccountId("etf-offline"), owner="fixture")
    store = store_type()(factory, clock)
    original = request(episode_events())
    before = await store.append_event(original, lease, expected_cursor=0, event=original.events[0])

    def fail_commit(connection):
        raise RuntimeError("synthetic disk failure")

    sql_event.listen(engine.sync_engine, "commit", fail_commit)
    try:
        with pytest.raises(ValueError, match="etf_store_invalid"):
            await store.append_event(original, lease, expected_cursor=1, event=original.events[1])
    finally:
        sql_event.remove(engine.sync_engine, "commit", fail_commit)
    assert await store.restore(original) == before
    await engine.dispose()


async def test_expired_or_replaced_writer_cannot_advance_replay(etf_url):
    engine = create_engine(etf_url)
    factory = async_session_factory(engine)
    clock = Clock()
    leases = LeaseRepository(factory, clock)
    old = await leases.acquire(AccountId("etf-offline"), owner="old")
    store = store_type()(factory, clock)
    original = request(episode_events())
    before = await store.append_event(original, old, expected_cursor=0, event=original.events[0])
    clock.current += timedelta(seconds=31)
    fresh = await leases.acquire(AccountId("etf-offline"), owner="new")
    with pytest.raises(ValueError, match="etf_store_invalid"):
        await store.append_event(original, old, expected_cursor=1, event=original.events[1])
    assert await store.restore(original) == before
    after = await store.append_event(original, fresh, expected_cursor=1, event=original.events[1])
    assert after.state.cash == D("489.99") and after.fencing_token > before.fencing_token
    await engine.dispose()


async def test_future_event_is_denied_without_losing_prior_cursor(etf_url):
    engine = create_engine(etf_url)
    factory = async_session_factory(engine)
    clock = Clock(current=NOW + timedelta(microseconds=500000))
    lease = await LeaseRepository(factory, clock).acquire(AccountId("etf-offline"), owner="clock")
    store = store_type()(factory, clock)
    original = request(episode_events())
    before = await store.append_event(original, lease, expected_cursor=0, event=original.events[0])
    with pytest.raises(ValueError, match="etf_store_invalid"):
        await store.append_event(original, lease, expected_cursor=1, event=original.events[1])
    assert await store.restore(original) == before
    clock.current = NOW + timedelta(seconds=1)
    after = await store.append_event(original, lease, expected_cursor=1, event=original.events[1])
    assert after.cursor == 2 and after.state.cash == D("489.99")
    await engine.dispose()


async def test_subsecond_event_at_clock_is_not_mistaken_for_future(etf_url):
    engine = create_engine(etf_url)
    factory = async_session_factory(engine)
    clock = Clock(current=NOW + timedelta(microseconds=500000))
    lease = await LeaseRepository(factory, clock).acquire(AccountId("etf-offline"), owner="clock")
    store = store_type()(factory, clock)
    original = request(episode_events())
    first = original.events[0]
    changed = replace(first.intent, created_at=clock.current)
    event = replace(first, intent=changed, at_ns=first.at_ns + 500000000)
    source = request((event,))
    result = await store.append_event(source, lease, expected_cursor=0, event=event)
    assert result.cursor == 1 and result.state.last_at_ns == event.at_ns
    await engine.dispose()


@pytest.mark.parametrize("cursor", [-1, True, 99])
async def test_invalid_cursor_preserves_empty_ledger(etf_url, cursor):
    engine = create_engine(etf_url)
    factory = async_session_factory(engine)
    clock = Clock()
    lease = await LeaseRepository(factory, clock).acquire(AccountId("etf-offline"), owner="fixture")
    store = store_type()(factory, clock)
    original = request(episode_events())
    with pytest.raises(ValueError, match="etf_store_invalid"):
        await store.append_event(original, lease, expected_cursor=cursor, event=original.events[0])
    assert (await store.restore(original)).cursor == 0
    await engine.dispose()


async def test_corrupt_terminal_state_hash_cannot_reconstruct_even_with_valid_row_hash(etf_url):
    engine = create_engine(etf_url)
    factory = async_session_factory(engine)
    clock = Clock()
    lease = await LeaseRepository(factory, clock).acquire(AccountId("etf-offline"), owner="fixture")
    store = store_type()(factory, clock)
    original = request(episode_events())
    await store.append_event(original, lease, expected_cursor=0, event=original.events[0])
    async with factory() as session:
        row = await session.scalar(select(EtfReplayEventRow))
        session.expunge(row)
    module = importlib.import_module("trading_bot.persistence.etf_history_store")
    row.state_hash = "f" * 64
    row.event_hash = module._hash(row)
    with pytest.raises(ValueError, match="etf_store_invalid"):
        module._restore(original, [row])
    with pytest.raises(ValueError, match="etf_store_invalid"):
        module._restore(replace(original, events=()), [row])
    with pytest.raises(ValueError, match="etf_store_invalid"):
        await store.restore({})
    await engine.dispose()


async def test_corrupt_intermediate_state_is_not_hidden_by_a_valid_terminal_state(etf_url):
    engine = create_engine(etf_url)
    factory = async_session_factory(engine)
    clock = Clock()
    lease = await LeaseRepository(factory, clock).acquire(AccountId("etf-offline"), owner="fixture")
    store = store_type()(factory, clock)
    original = request(episode_events())
    for cursor in range(2):
        await store.append_event(
            original, lease, expected_cursor=cursor, event=original.events[cursor]
        )
    async with factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(EtfReplayEventRow).order_by(EtfReplayEventRow.sequence)
                )
            ).all()
        )
        session.expunge_all()
    module = importlib.import_module("trading_bot.persistence.etf_history_store")
    rows[0].state_hash = "f" * 64
    rows[0].event_hash = module._hash(rows[0])
    rows[1].previous_hash = rows[0].event_hash
    rows[1].event_hash = module._hash(rows[1])
    with pytest.raises(ValueError, match="etf_store_invalid"):
        module._restore(original, rows)
    await engine.dispose()


def test_journal_payload_size_is_bounded():
    module = importlib.import_module("trading_bot.persistence.etf_history_store")
    item = episode_events()[0]
    oversized = replace(item, intent=replace(item.intent, strategy_version="x" * 20000))
    with pytest.raises(ValueError, match="etf_store_invalid"):
        module._payload(oversized)
