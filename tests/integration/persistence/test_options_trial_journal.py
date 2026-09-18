"""Durable synthetic trial history: reservations survive restart and stale writers fail."""

import asyncio
import json
import sqlite3
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event as sqlalchemy_event

from tests.integration.persistence.test_execution_lease import NOW, Clock
from tests.integration.persistence.test_migrations import _seed_account
from trading_bot.domain import AccountId
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.persistence.lease import LeaseRepository, StaleFencingToken
from trading_bot.persistence.models import OptionsTrialEventRow
from trading_bot.persistence.options_trial import (
    OptionsTrialJournal,
    TrialJournalEvent,
    _decode,
    _hash,
    _payload,
    _reconstruct,
)
from trading_bot.risk.options_economics import TrialEpisode

D = Decimal


@pytest.fixture
def journal_url(alembic_config: Config, database_path: Path, database_url: str) -> str:
    command.upgrade(alembic_config, "head")
    with sqlite3.connect(database_path) as connection:
        _seed_account(connection)
    return database_url


def event(name: str = "open", **changes: object) -> TrialJournalEvent:
    return replace(
        TrialJournalEvent(
            name, NOW, "b" * 64, TrialEpisode("episode-1", D("11"), None, False, False, False)
        ),
        **changes,
    )


async def test_trial_loss_survives_restart_and_wins_do_not_replenish(journal_url: str) -> None:
    engine = create_engine(journal_url)
    factory = async_session_factory(engine)
    clock = Clock()
    leases = LeaseRepository(factory, clock)
    lease = await leases.acquire(AccountId("account-1"), owner="paper")
    journal = OptionsTrialJournal(factory, clock)
    await journal.append(lease, event())
    assert (await journal.restore(AccountId("account-1"))).reserved_risk == D("11")
    completed = replace(
        event().episode,
        net_cash_flow=D("-6"),
        flat=True,
        orders_terminal=True,
        settlement_and_fees_final=True,
    )
    await journal.append(lease, event("loss", episode=completed))
    new = replace(event().episode, episode_id="episode-2")
    await journal.append(lease, event("open-win", episode=new))
    await journal.append(
        lease,
        event(
            "win",
            episode=replace(
                new,
                net_cash_flow=D("100"),
                flat=True,
                orders_terminal=True,
                settlement_and_fees_final=True,
            ),
        ),
    )
    await engine.dispose()
    restarted_engine = create_engine(journal_url)
    restored = await OptionsTrialJournal(async_session_factory(restarted_engine), clock).restore(
        AccountId("account-1")
    )
    assert restored.consumed_loss == D("6")
    assert restored.reserved_risk == 0
    assert restored.remaining(D("50")) == D("44")
    await restarted_engine.dispose()


def test_corruption_noncanonical_payload_and_schema_changes_fail_closed() -> None:
    payload = _payload(event())
    for bad in (" " + payload, payload.replace('"synthetic"', '"live"')):
        with pytest.raises(ValueError):
            _decode(bad)
    for field, value in (
        ("event_hash", "a" * 64),
        ("previous_hash", "b" * 64),
        ("sequence", 1),
        ("id", "wrong"),
    ):
        row = OptionsTrialEventRow(
            id="open",
            account_id="account-1",
            sequence=0,
            fencing_token=1,
            payload_json=payload,
            previous_hash="0" * 64,
        )
        row.event_hash = _hash(row)
        setattr(row, field, value)
        if field == "id":
            row.event_hash = _hash(row)
        with pytest.raises(ValueError):
            _reconstruct([row])
    parsed = json.loads(payload)
    parsed["event"]["episode"]["net_cash_flow"] = "NaN"
    with pytest.raises(ValueError):
        _decode(json.dumps(parsed))


def test_event_and_payload_work_bounds_are_enforced() -> None:
    with pytest.raises(ValueError):
        event("x" * 256)
    with pytest.raises(ValueError):
        event(episode={})
    oversized = event(episode=replace(event().episode, episode_id="x" * 16385))
    with pytest.raises(ValueError, match="limit"):
        _payload(oversized)
    for maximum in (True, 0, -1, 100001):
        with pytest.raises(ValueError):
            OptionsTrialJournal(None, Clock(), max_events=maximum)  # type: ignore[arg-type]


async def test_partial_and_pending_cancellation_keep_full_reservation(journal_url: str) -> None:
    engine = create_engine(journal_url)
    factory = async_session_factory(engine)
    clock = Clock()
    lease = await LeaseRepository(factory, clock).acquire(AccountId("account-1"), owner="paper")
    journal = OptionsTrialJournal(factory, clock)
    await journal.append(lease, event())
    for number, snapshot in enumerate(
        (
            replace(event().episode, net_cash_flow=D("-5")),
            replace(event().episode, net_cash_flow=D("-5"), flat=True),
            replace(event().episode, net_cash_flow=D("-5"), flat=True, orders_terminal=True),
        )
    ):
        await journal.append(lease, event(f"step-{number}", episode=snapshot))
        state = await journal.restore(AccountId("account-1"))
        assert state.reserved_risk == D("11")
        assert state.consumed_loss == 0
    await engine.dispose()


async def test_idempotency_stale_writer_and_reservation_reduction_are_denied(
    journal_url: str,
) -> None:
    engine = create_engine(journal_url)
    factory = async_session_factory(engine)
    clock = Clock()
    leases = LeaseRepository(factory, clock)
    lease = await leases.acquire(AccountId("account-1"), owner="paper")
    journal = OptionsTrialJournal(factory, clock)
    receipt = await journal.append(lease, event())
    assert await journal.append(lease, event()) == receipt
    with pytest.raises(ValueError):
        await journal.append(lease, event(episode=replace(event().episode, reserved_risk=D("12"))))
    with pytest.raises(ValueError):
        await journal.append(
            lease, event("reduce", episode=replace(event().episode, reserved_risk=D("1")))
        )
    await leases.release(lease)
    await leases.acquire(AccountId("account-1"), owner="paper")
    with pytest.raises(StaleFencingToken):
        await journal.append(lease, event("stale"))
    assert (await journal.restore(AccountId("account-1"))).reserved_risk == D("11")
    await engine.dispose()


async def test_completed_episode_cannot_be_reopened_or_rewritten(journal_url: str) -> None:
    engine = create_engine(journal_url)
    factory = async_session_factory(engine)
    clock = Clock()
    lease = await LeaseRepository(factory, clock).acquire(AccountId("account-1"), owner="paper")
    journal = OptionsTrialJournal(factory, clock)
    await journal.append(lease, event())
    completed = replace(
        event().episode,
        net_cash_flow=D("-11"),
        flat=True,
        orders_terminal=True,
        settlement_and_fees_final=True,
    )
    await journal.append(lease, event("finish", episode=completed))
    for candidate in (
        event("reopen"),
        event("rewrite", episode=replace(completed, net_cash_flow=D("0"))),
    ):
        with pytest.raises(ValueError):
            await journal.append(lease, candidate)
    await engine.dispose()


def test_empty_additive_history_can_be_rolled_back(
    journal_url: str,
    database_path: Path,
    alembic_config: Config,
) -> None:
    del journal_url
    with sqlite3.connect(database_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(options_trial_events)")}
        assert {
            "id",
            "account_id",
            "sequence",
            "payload_json",
            "previous_hash",
            "event_hash",
        } <= columns
    # Empty additive migration may be rolled back; nonempty history gets a separate
    # integration test once written through the fenced repository.
    command.downgrade(alembic_config, "0005_research_evidence_guards")
    command.upgrade(alembic_config, "head")


async def test_nonempty_history_blocks_sql_mutation_and_lossy_rollback(
    journal_url: str,
    database_path: Path,
    alembic_config: Config,
) -> None:
    engine = create_engine(journal_url)
    factory = async_session_factory(engine)
    clock = Clock()
    lease = await LeaseRepository(factory, clock).acquire(AccountId("account-1"), owner="paper")
    journal = OptionsTrialJournal(factory, clock)
    await journal.append(lease, event())
    with sqlite3.connect(database_path) as connection:
        for statement in (
            "UPDATE options_trial_events SET payload_json = '{}'",
            "DELETE FROM options_trial_events",
            "INSERT OR REPLACE INTO options_trial_events SELECT * FROM options_trial_events",
            "UPDATE options_trial_events SET rowid = 100",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                connection.execute(statement)
    with pytest.raises(RuntimeError, match="nonempty"):
        await asyncio.to_thread(command.downgrade, alembic_config, "0005_research_evidence_guards")
    assert (await journal.restore(AccountId("account-1"))).reserved_risk == D("11")
    await engine.dispose()


async def test_capacity_never_silently_truncates_loss_history(journal_url: str) -> None:
    engine = create_engine(journal_url)
    factory = async_session_factory(engine)
    clock = Clock()
    lease = await LeaseRepository(factory, clock).acquire(AccountId("account-1"), owner="paper")
    journal = OptionsTrialJournal(factory, clock, max_events=2)
    await journal.append(lease, event())
    await journal.append(
        lease, event("grow", episode=replace(event().episode, reserved_risk=D("12")))
    )
    with pytest.raises(ValueError, match="capacity"):
        await journal.append(lease, event("over-capacity"))
    with pytest.raises(ValueError, match="capacity"):
        await OptionsTrialJournal(factory, clock, max_events=1).restore(AccountId("account-1"))
    assert (await journal.restore(AccountId("account-1"))).reserved_risk == D("12")
    await engine.dispose()


async def test_future_out_of_order_and_missing_initial_reservation_are_denied(
    journal_url: str,
) -> None:
    from datetime import timedelta

    engine = create_engine(journal_url)
    factory = async_session_factory(engine)
    clock = Clock()
    lease = await LeaseRepository(factory, clock).acquire(AccountId("account-1"), owner="paper")
    journal = OptionsTrialJournal(factory, clock)
    with pytest.raises(ValueError, match="future"):
        await journal.append(lease, event(occurred_at=NOW + timedelta(seconds=1)))
    with pytest.raises(ValueError, match="start"):
        await journal.append(lease, event(episode=replace(event().episode, reserved_risk=D("0"))))
    await journal.append(lease, event())
    with pytest.raises(ValueError, match="out-of-order"):
        await journal.append(lease, event("earlier", occurred_at=NOW - timedelta(seconds=1)))
    # Historical losses larger than a reservation must remain visible, not be capped.
    completed = replace(
        event().episode,
        net_cash_flow=D("-60"),
        flat=True,
        orders_terminal=True,
        settlement_and_fees_final=True,
    )
    await journal.append(lease, event("loss", episode=completed, config_hash="c" * 64))
    assert (await journal.restore(AccountId("account-1"))).remaining(D("50")) == 0
    await engine.dispose()


@pytest.mark.parametrize("boundary", ["BEGIN IMMEDIATE", "INSERT INTO options_trial_events"])
async def test_lease_expiring_during_database_wait_cannot_append(
    journal_url: str, boundary: str
) -> None:
    from datetime import timedelta

    engine = create_engine(journal_url)
    factory = async_session_factory(engine)
    clock = Clock()
    lease = await LeaseRepository(factory, clock, timedelta(seconds=1)).acquire(
        AccountId("account-1"), owner="paper"
    )
    journal = OptionsTrialJournal(factory, clock)

    def advance_clock(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith(boundary):
            clock.current += timedelta(seconds=2)

    sqlalchemy_event.listen(engine.sync_engine, "before_cursor_execute", advance_clock)
    with pytest.raises(StaleFencingToken):
        await journal.append(lease, event())
    sqlalchemy_event.remove(engine.sync_engine, "before_cursor_execute", advance_clock)
    assert (await journal.restore(AccountId("account-1"))).episodes == ()
    await engine.dispose()
