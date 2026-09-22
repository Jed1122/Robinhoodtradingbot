"""A saved synthetic script resumes from durable reservations, never live orders."""

import socket
import sqlite3
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from tests.integration.persistence.test_execution_lease import Clock
from tests.integration.persistence.test_migrations import _seed_account
from tests.integration.simulation.test_options_replay import request
from trading_bot.domain import AccountId
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.persistence.lease import LeaseRepository, StaleFencingToken
from trading_bot.persistence.options_trial import OptionsTrialJournal, TrialJournalEvent
from trading_bot.risk.options_economics import TrialEpisode
from trading_bot.runtime.options_recorded_session import RecordedOptionsSession
from trading_bot.simulation.options_replay import replay_options

D = Decimal
ACCOUNT = AccountId("account-1")


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("network forbidden in recorded options session tests")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


@pytest.fixture
def session_url(alembic_config: Config, database_path: Path, database_url: str) -> str:
    command.upgrade(alembic_config, "head")
    with sqlite3.connect(database_path) as connection:
        _seed_account(connection)
    return database_url


@pytest.mark.parametrize("scenario", ["completed", "loss", "unsettled", "cancel_race", "unknown"])
async def test_each_event_survives_restart_without_duplicate_fills(session_url: str, scenario: str):
    r = request(scenario)
    clock = Clock(r.as_of + timedelta(seconds=10))
    engine = create_engine(session_url)
    factory = async_session_factory(engine)
    leases = LeaseRepository(factory, clock)
    lease = await leases.acquire(ACCOUNT, owner="offline")
    journal = OptionsTrialJournal(factory, clock)
    service = RecordedOptionsSession(journal)
    assert await service.restore(ACCOUNT, r) is None
    initial = await service.start(lease, r)
    assert initial.event_count == 0 and initial.paused
    assert initial.result.cash == D(2500)
    assert (await journal.restore(ACCOUNT)).reserved_risk == D(11)
    assert await service.start(lease, r) == initial
    for count in range(len(r.events)):
        await leases.release(lease)
        await engine.dispose()
        engine = create_engine(session_url)
        factory = async_session_factory(engine)
        leases = LeaseRepository(factory, clock)
        lease = await leases.acquire(ACCOUNT, owner="restarted-offline")
        journal = OptionsTrialJournal(factory, clock)
        service = RecordedOptionsSession(journal)
        restored = await service.restore(ACCOUNT, r)
        assert restored is not None and restored.paused
        assert restored.event_count == count
        with pytest.raises(ValueError, match="paused"):
            await service.advance(lease, r, expected_event_count=count)
        progressed = await service.advance(
            lease, r, expected_event_count=count, resume_recorded_replay=True
        )
        assert progressed.result == replay_options(r, event_count=count + 1)
        assert not progressed.result.production_eligible
    assert (await journal.restore(ACCOUNT)) == replay_options(r).trial
    await engine.dispose()


async def test_mismatched_script_stale_step_and_stale_lease_cannot_advance(session_url: str):
    r = request()
    clock = Clock(r.as_of + timedelta(seconds=10))
    engine = create_engine(session_url)
    factory = async_session_factory(engine)
    leases = LeaseRepository(factory, clock)
    lease = await leases.acquire(ACCOUNT, owner="offline")
    journal = OptionsTrialJournal(factory, clock)
    service = RecordedOptionsSession(journal)
    await service.start(lease, r)
    with pytest.raises(ValueError):
        await service.start(lease, replace(r, close_limit=D("0.16")))
    await service.advance(lease, r, expected_event_count=0, resume_recorded_replay=True)
    with pytest.raises(ValueError, match="count"):
        await service.advance(lease, r, expected_event_count=0, resume_recorded_replay=True)
    await leases.release(lease)
    await leases.acquire(ACCOUNT, owner="next")
    with pytest.raises(StaleFencingToken):
        await service.advance(lease, r, expected_event_count=1, resume_recorded_replay=True)
    assert (await service.restore(ACCOUNT, r)).event_count == 1
    await engine.dispose()


async def test_denied_entry_does_not_create_a_reservation_or_session(session_url: str):
    r = request(capital="100")
    clock = Clock(r.as_of)
    engine = create_engine(session_url)
    factory = async_session_factory(engine)
    lease = await LeaseRepository(factory, clock).acquire(ACCOUNT, owner="offline")
    journal = OptionsTrialJournal(factory, clock)
    service = RecordedOptionsSession(journal)
    with pytest.raises(ValueError, match="denied"):
        await service.start(lease, r)
    assert (await journal.restore(ACCOUNT)).episodes == ()
    assert await service.restore(ACCOUNT, r) is None
    await engine.dispose()


async def test_completed_script_cannot_start_another_episode_on_same_account(session_url: str):
    r = request("rejected")
    clock = Clock(r.as_of + timedelta(seconds=10))
    engine = create_engine(session_url)
    factory = async_session_factory(engine)
    lease = await LeaseRepository(factory, clock).acquire(ACCOUNT, owner="offline")
    journal = OptionsTrialJournal(factory, clock)
    service = RecordedOptionsSession(journal)
    await service.start(lease, r)
    final = await service.advance(lease, r, expected_event_count=0, resume_recorded_replay=True)
    with pytest.raises(ValueError, match="count"):
        await service.advance(lease, r, expected_event_count=1, resume_recorded_replay=True)
    with pytest.raises(ValueError, match="one recorded script"):
        await service.start(lease, replace(r, trial=final.result.trial))
    await engine.dispose()


@pytest.mark.parametrize("mutation", ["identity", "extra", "other_episode"])
async def test_semantically_inconsistent_journal_stops_reconstruction(
    session_url: str, mutation: str
):
    r = request()
    clock = Clock(r.as_of + timedelta(seconds=10))
    engine = create_engine(session_url)
    factory = async_session_factory(engine)
    lease = await LeaseRepository(factory, clock).acquire(ACCOUNT, owner="offline")
    journal = OptionsTrialJournal(factory, clock)
    service = RecordedOptionsSession(journal)
    await service.start(lease, r)
    initial = (await journal.events(ACCOUNT))[0]
    if mutation == "identity":
        await journal.append(lease, replace(initial, event_id="unrelated-id"))
    elif mutation == "extra":
        for count in range(len(r.events) + 1):
            await journal.append(lease, replace(initial, event_id=f"extra-{count}"))
    else:
        await journal.append(
            lease,
            TrialJournalEvent(
                "other",
                r.as_of,
                r.loaded.config_hash,
                TrialEpisode("other-episode", D(1), None, False, False, False),
            ),
        )
    with pytest.raises(ValueError):
        await service.restore(ACCOUNT, r)
    await engine.dispose()


async def test_invalid_resume_and_counts_never_start_implicit_work(session_url: str):
    with pytest.raises(ValueError):
        RecordedOptionsSession(object())
    r = request()
    clock = Clock(r.as_of + timedelta(seconds=10))
    engine = create_engine(session_url)
    factory = async_session_factory(engine)
    lease = await LeaseRepository(factory, clock).acquire(ACCOUNT, owner="offline")
    service = RecordedOptionsSession(OptionsTrialJournal(factory, clock))
    with pytest.raises(ValueError, match="count"):
        await service.advance(lease, r, expected_event_count=0, resume_recorded_replay=True)
    await service.start(lease, r)
    for count in (True, -1, 1, "0"):
        with pytest.raises(ValueError, match="count"):
            await service.advance(lease, r, expected_event_count=count, resume_recorded_replay=True)
    for resume in (False, 1, "true", None):
        with pytest.raises(ValueError, match="paused"):
            await service.advance(lease, r, expected_event_count=0, resume_recorded_replay=resume)
    await engine.dispose()


async def test_failed_checkpoint_write_retains_reservation_and_prior_cash(
    session_url: str,
    database_path: Path,
):
    r = request()
    clock = Clock(r.as_of + timedelta(seconds=10))
    engine = create_engine(session_url)
    factory = async_session_factory(engine)
    lease = await LeaseRepository(factory, clock).acquire(ACCOUNT, owner="offline")
    journal = OptionsTrialJournal(factory, clock)
    service = RecordedOptionsSession(journal)
    initial = await service.start(lease, r)
    with sqlite3.connect(database_path) as connection:
        connection.execute("""
            CREATE TRIGGER synthetic_write_failure BEFORE INSERT ON options_trial_events
            BEGIN SELECT RAISE(ABORT, 'synthetic database write failure'); END
        """)
    with pytest.raises(IntegrityError):
        await service.advance(lease, r, expected_event_count=0, resume_recorded_replay=True)
    assert await service.restore(ACCOUNT, r) == initial
    assert (await journal.restore(ACCOUNT)).reserved_risk == D(11)
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TRIGGER synthetic_write_failure")
    advanced = await service.advance(lease, r, expected_event_count=0, resume_recorded_replay=True)
    assert advanced.event_count == 1 and advanced.result.cash == D(2500)
    await engine.dispose()


async def test_completion_before_end_of_script_stays_terminal(session_url: str):
    r = request("rejected")
    r = replace(r, events=(*r.events, request().events[1]))
    clock = Clock(r.as_of + timedelta(seconds=10))
    engine = create_engine(session_url)
    factory = async_session_factory(engine)
    lease = await LeaseRepository(factory, clock).acquire(ACCOUNT, owner="offline")
    service = RecordedOptionsSession(OptionsTrialJournal(factory, clock))
    await service.start(lease, r)
    await service.advance(lease, r, expected_event_count=0, resume_recorded_replay=True)
    with pytest.raises(ValueError, match="completed"):
        await service.advance(lease, r, expected_event_count=1, resume_recorded_replay=True)
    await engine.dispose()


async def test_state_preserving_intervening_writer_denies_next_checkpoint(
    session_url: str,
    monkeypatch: pytest.MonkeyPatch,
):
    r = request()
    clock = Clock(r.as_of + timedelta(seconds=10))
    engine = create_engine(session_url)
    factory = async_session_factory(engine)
    lease = await LeaseRepository(factory, clock).acquire(ACCOUNT, owner="offline")
    journal = OptionsTrialJournal(factory, clock)
    service = RecordedOptionsSession(journal)
    await service.start(lease, r)
    await service.advance(lease, r, expected_event_count=0, resume_recorded_replay=True)
    before = await journal.restore(ACCOUNT)
    last = (await journal.events(ACCOUNT))[-1]
    original = journal.append

    async def interposed(writer, checkpoint, **kwargs):
        await original(writer, replace(last, event_id="state-preserving-intervening-writer"))
        return await original(writer, checkpoint, **kwargs)

    monkeypatch.setattr(journal, "append", interposed)
    with pytest.raises(ValueError, match="changed"):
        await service.advance(lease, r, expected_event_count=1, resume_recorded_replay=True)
    assert (await journal.restore(ACCOUNT)) == before
    assert len(await journal.events(ACCOUNT)) == 3  # No fourth record/entry fill committed.
    await engine.dispose()


async def test_identical_scripts_in_distinct_accounts_have_distinct_checkpoint_identity(
    session_url: str,
    database_path: Path,
):
    with sqlite3.connect(database_path) as connection:
        _seed_account(connection, account_id="account-2")
    r = request()
    clock = Clock(r.as_of + timedelta(seconds=10))
    engine = create_engine(session_url)
    factory = async_session_factory(engine)
    leases = LeaseRepository(factory, clock)
    journal = OptionsTrialJournal(factory, clock)
    service = RecordedOptionsSession(journal)
    first = await leases.acquire(ACCOUNT, owner="offline")
    second = await leases.acquire(AccountId("account-2"), owner="offline")
    one = await service.start(first, r)
    two = await service.start(second, r)
    assert one.result == two.result
    assert one.journal_head != two.journal_head
    assert (await journal.events(ACCOUNT))[0].event_id != (
        await journal.events(AccountId("account-2"))
    )[0].event_id
    await service.advance(first, r, expected_event_count=0, resume_recorded_replay=True)
    assert (await service.restore(AccountId("account-2"), r)).event_count == 0
    await engine.dispose()
