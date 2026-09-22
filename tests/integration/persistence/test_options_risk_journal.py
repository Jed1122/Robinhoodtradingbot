"""Real temporary SQLite databases; no broker, credentials or production migration."""

import asyncio
import importlib
import json
import socket
import sqlite3
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import event as sqlalchemy_event

from tests.integration.persistence.test_migrations import _seed_account
from tests.unit.risk.test_options_loss_history import ACCOUNT, OPEN, config, point
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.persistence.lease import LeaseRepository, StaleFencingToken


class Clock:
    value = OPEN

    def now(self):
        return self.value


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("offline journal cannot use a network")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)


def api():
    try:
        return importlib.import_module("trading_bot.persistence.options_risk")
    except ModuleNotFoundError:
        pytest.fail("durable options risk journal not implemented")


@pytest.fixture
def journal_url(alembic_config, database_path, database_url):
    command.upgrade(alembic_config, "head")
    with sqlite3.connect(database_path) as connection:
        _seed_account(connection, account_id=ACCOUNT)
    return database_url


async def setup(url, maximum=5000):
    module = api()
    engine = create_engine(url)
    factory = async_session_factory(engine)
    clock = Clock()
    leases = LeaseRepository(factory, clock)
    lease = await leases.acquire(ACCOUNT, owner="synthetic-risk")
    return (
        engine,
        factory,
        clock,
        leases,
        lease,
        module.OptionsRiskJournal(factory, clock, config(), max_events=maximum),
    )


async def test_restart_preserves_latches_and_exact_cash_flow_history(journal_url):
    engine, _factory, clock, _leases, lease, journal = await setup(journal_url)
    empty = await journal.snapshot(ACCOUNT)
    assert empty.points == () and empty.report is None and empty.head_hash == "0" * 64
    head = await journal.append(lease, point(), expected_head=empty.head_hash)
    clock.value += timedelta(seconds=1)
    loss = point("loss", "89", at=clock.value)
    head = await journal.append(lease, loss, expected_head=head)
    clock.value += timedelta(seconds=1)
    deposit = point("deposit", "1089", flow="1000", at=clock.value)
    head = await journal.append(lease, deposit, expected_head=head)
    before = await journal.snapshot(ACCOUNT)
    await engine.dispose()
    restarted = create_engine(journal_url)
    restored = (
        await api()
        .OptionsRiskJournal(async_session_factory(restarted), clock, config())
        .snapshot(ACCOUNT)
    )
    assert restored == before
    assert restored.head_hash == head
    assert restored.points == (point(), loss, deposit)
    assert restored.report.flow_adjusted_equity == Decimal("89")
    assert restored.report.weekly_halt and restored.report.drawdown_halt
    assert restored.report.paused and not restored.report.production_eligible
    await restarted.dispose()


async def test_idempotency_cas_and_conflicting_identity(journal_url):
    engine, _factory, clock, _leases, lease, journal = await setup(journal_url)
    receipt = await journal.append(lease, point(), expected_head="0" * 64)
    assert await journal.append(lease, point(), expected_head="0" * 64) == receipt
    with pytest.raises(ValueError):
        await journal.append(lease, point(value="99"), expected_head=receipt)
    clock.value += timedelta(seconds=1)
    with pytest.raises(ValueError):
        await journal.append(lease, point("stale", at=clock.value), expected_head="0" * 64)
    await journal.append(lease, point("new", at=clock.value), expected_head=receipt)
    with pytest.raises(ValueError):
        await journal.append(lease, point(), expected_head="0" * 64)
    assert len((await journal.snapshot(ACCOUNT)).points) == 2
    await engine.dispose()


async def test_stale_leader_clock_regression_and_future_point_are_denied(journal_url):
    engine, _factory, clock, leases, lease, journal = await setup(journal_url)
    with pytest.raises(ValueError):
        await journal.append(
            lease, point("future", at=OPEN + timedelta(seconds=1)), expected_head="0" * 64
        )
    clock.value -= timedelta(seconds=1)
    with pytest.raises((ValueError, StaleFencingToken)):
        await journal.append(lease, point(), expected_head="0" * 64)
    clock.value = OPEN
    await leases.release(lease)
    current = await leases.acquire(ACCOUNT, owner=lease.owner)
    with pytest.raises(StaleFencingToken):
        await journal.append(lease, point(), expected_head="0" * 64)
    await journal.append(current, point(), expected_head="0" * 64)
    await engine.dispose()


@pytest.mark.parametrize("sql_fragment", ["BEGIN IMMEDIATE", "INSERT INTO options_risk_events"])
async def test_expiry_after_wait_or_before_commit_rolls_back(journal_url, sql_fragment):
    engine, _factory, clock, _leases, lease, journal = await setup(journal_url)

    def expire(connection, cursor, statement, parameters, context, executemany):
        if sql_fragment in statement:
            clock.value = lease.expires_at

    sqlalchemy_event.listen(engine.sync_engine, "after_cursor_execute", expire)
    with pytest.raises(StaleFencingToken):
        await journal.append(lease, point(), expected_head="0" * 64)
    sqlalchemy_event.remove(engine.sync_engine, "after_cursor_execute", expire)
    assert (await journal.snapshot(ACCOUNT)).points == ()
    await engine.dispose()


async def test_capacity_denies_without_erasing_history(journal_url):
    engine, factory, clock, _leases, lease, journal = await setup(journal_url, maximum=1)
    head = await journal.append(lease, point(), expected_head="0" * 64)
    clock.value += timedelta(seconds=1)
    with pytest.raises(ValueError):
        await journal.append(lease, point("too-many", at=clock.value), expected_head=head)
    assert len((await journal.snapshot(ACCOUNT)).points) == 1
    bigger = api().OptionsRiskJournal(factory, clock, config(), max_events=2)
    await bigger.append(lease, point("two", at=clock.value), expected_head=head)
    with pytest.raises(ValueError):
        await journal.snapshot(ACCOUNT)
    await engine.dispose()


async def test_invalid_inputs_do_not_write(journal_url):
    engine, factory, clock, _leases, lease, journal = await setup(journal_url)
    for maximum in (0, True, 100001):
        with pytest.raises(ValueError):
            api().OptionsRiskJournal(factory, clock, config(), max_events=maximum)
    for bad_lease, bad_point, bad_head in (
        (object(), point(), "0" * 64),
        (lease, object(), "0" * 64),
        (lease, point(), "bad"),
        (replace(lease, account_id="synthetic:other"), point(), "0" * 64),
    ):
        with pytest.raises(ValueError):
            await journal.append(bad_lease, bad_point, expected_head=bad_head)
    assert (await journal.snapshot(ACCOUNT)).points == ()
    await engine.dispose()


async def test_sql_mutation_and_destructive_downgrade_are_blocked(
    journal_url, database_path, alembic_config
):
    engine, _factory, _clock, _leases, lease, journal = await setup(journal_url)
    await journal.append(lease, point(), expected_head="0" * 64)
    await engine.dispose()
    for sql in (
        "DELETE FROM options_risk_events",
        "UPDATE options_risk_events SET payload_json='{}'",
        "INSERT OR REPLACE INTO options_risk_events SELECT * FROM options_risk_events",
        "INSERT OR REPLACE INTO options_risk_events "
        "(rowid,id,account_id,sequence,fencing_token,payload_json,previous_hash,event_hash) "
        "SELECT rowid,'replacement',account_id,sequence+1,fencing_token,payload_json,"
        "previous_hash,event_hash FROM options_risk_events",
    ):
        with sqlite3.connect(database_path) as connection, pytest.raises(sqlite3.IntegrityError):
            connection.execute(sql)
    with pytest.raises(RuntimeError, match="nonempty"):
        await asyncio.to_thread(command.downgrade, alembic_config, "0006_options_trial_history")


def test_closed_codec_and_hash_chain_reject_tampering():
    module = api()
    payload = module.encode_point(point())
    assert module.decode_point(payload) == point()
    for bad in (
        " " + payload,
        payload.replace('"synthetic"', '"historical"'),
        payload.replace('"options-risk-point-v1"', '"other"'),
    ):
        with pytest.raises(ValueError):
            module.decode_point(bad)
    decoded = json.loads(payload)
    decoded["point"]["unknown"] = True
    with pytest.raises(ValueError):
        module.decode_point(json.dumps(decoded))
    for field, value in (
        ("sequence", 1),
        ("previous_hash", "a" * 64),
        ("event_hash", "b" * 64),
        ("id", "other"),
        ("account_id", "synthetic:other"),
    ):
        row = module.OptionsRiskEventRow(
            id="initial",
            account_id=ACCOUNT,
            sequence=0,
            fencing_token=1,
            payload_json=payload,
            previous_hash="0" * 64,
        )
        row.event_hash = module._hash(row)
        setattr(row, field, value)
        if field in ("id", "account_id"):
            row.event_hash = module._hash(row)
        with pytest.raises(ValueError):
            module._points([row], ACCOUNT)


async def test_simultaneous_appends_have_one_winner(journal_url):
    engine, _factory, clock, _leases, lease, journal = await setup(journal_url)
    head = await journal.append(lease, point(), expected_head="0" * 64)
    clock.value += timedelta(seconds=1)
    results = await asyncio.gather(
        *[
            journal.append(lease, point(name, at=clock.value), expected_head=head)
            for name in ("left", "right")
        ],
        return_exceptions=True,
    )
    assert sum(isinstance(result, str) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1
    assert len((await journal.snapshot(ACCOUNT)).points) == 2
    await engine.dispose()


async def test_new_config_cannot_reinterpret_existing_history(journal_url):
    engine, factory, clock, _leases, lease, journal = await setup(journal_url)
    await journal.append(lease, point(), expected_head="0" * 64)
    changed = replace(config(), config_hash="e" * 64)
    with pytest.raises(ValueError):
        await api().OptionsRiskJournal(factory, clock, changed).snapshot(ACCOUNT)
    await engine.dispose()


def test_codec_bound_identity_and_prior_close(monkeypatch):
    from tests.unit.risk.test_options_loss_history import CLOSE, next_session

    module = api()
    monday = next_session(point("close", at=CLOSE), "100")
    assert module.decode_point(module.encode_point(monday)) == monday
    with pytest.raises(ValueError):
        module.encode_point(object())
    with pytest.raises(ValueError):
        module.OptionsRiskJournal(None, Clock(), object())
    with pytest.raises(ValueError):
        module.decode_point("x" * 16385)
    monkeypatch.setattr(module, "canonical_json", lambda _: "x" * 16385)
    with pytest.raises(ValueError):
        module.encode_point(point())


def test_lower_fencing_token_is_detected_even_with_recomputed_hash():
    module = api()
    rows = []
    head = "0" * 64
    for number, token in enumerate((2, 1)):
        p = point(str(number), at=OPEN + timedelta(seconds=number))
        row = module.OptionsRiskEventRow(
            id=p.event_id,
            account_id=ACCOUNT,
            sequence=number,
            fencing_token=token,
            payload_json=module.encode_point(p),
            previous_hash=head,
        )
        row.event_hash = head = module._hash(row)
        rows.append(row)
    with pytest.raises(ValueError):
        module._points(rows, ACCOUNT)


async def test_old_duplicate_with_current_head_cannot_return_stale_receipt(journal_url):
    engine, _factory, clock, _leases, lease, journal = await setup(journal_url)
    head_a = await journal.append(lease, point(), expected_head="0" * 64)
    clock.value += timedelta(seconds=1)
    head_b = await journal.append(lease, point("B", at=clock.value), expected_head=head_a)
    with pytest.raises(ValueError, match=r"conflicting|superseded"):
        await journal.append(lease, point(), expected_head=head_b)
    assert (await journal.snapshot(ACCOUNT)).head_hash == head_b
    await engine.dispose()


async def test_precommit_clock_regression_rolls_back_even_inside_lease(journal_url):
    engine, _factory, clock, _leases, lease, journal = await setup(journal_url)
    head = await journal.append(lease, point(), expected_head="0" * 64)
    clock.value = OPEN + timedelta(seconds=10)
    later = point("later", at=clock.value)

    def regress(connection, cursor, statement, parameters, context, executemany):
        if "INSERT INTO options_risk_events" in statement:
            clock.value = OPEN + timedelta(seconds=5)

    sqlalchemy_event.listen(engine.sync_engine, "after_cursor_execute", regress)
    with pytest.raises(StaleFencingToken):
        await journal.append(lease, later, expected_head=head)
    sqlalchemy_event.remove(engine.sync_engine, "after_cursor_execute", regress)
    restored = await journal.snapshot(ACCOUNT)
    assert restored.points == (point(),) and restored.head_hash == head
    await engine.dispose()
