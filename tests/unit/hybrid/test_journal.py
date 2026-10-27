import asyncio
from pathlib import Path
from typing import Literal

import pytest
from pydantic import Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from trading_bot.hybrid.models import Account
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.persistence.hybrid_journal import HybridJournal
from trading_bot.persistence.migrations import migrate_sqlite_ledger
from trading_bot.persistence.models.hybrid import HybridEventRow

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
async def journal(tmp_path):
    ledger = tmp_path / "hybrid.db"
    # Alembic is synchronous and owns its own event loop.
    url = await asyncio.to_thread(
        migrate_sqlite_ledger,
        ledger,
        alembic_ini=ROOT / "alembic.ini",
        migrations_dir=ROOT / "migrations",
    )
    engine = create_engine(url)
    factory = async_session_factory(engine)
    yield HybridJournal(factory, "a" * 64), factory
    await engine.dispose()


async def test_restart_idempotency_and_conflicting_request(journal):
    owner, factory = journal
    state = await owner.change("genesis", "initialize", {}, lambda _: Account())
    assert state.cash == 1000
    state = await owner.change(
        "pause", "control", {"action": "pause"}, lambda a: a.model_copy(update={"paused": True})
    )
    restarted = HybridJournal(factory, "a" * 64)
    assert await restarted.read() == state
    assert (
        await restarted.change(
            "pause",
            "control",
            {"action": "pause"},
            lambda _: (_ for _ in ()).throw(AssertionError()),
        )
        == state
    )
    with pytest.raises(ValueError, match="conflict"):
        await restarted.change("pause", "control", {"action": "kill"}, lambda a: a)


async def test_transaction_failure_rolls_back_and_history_immutable(journal):
    owner, factory = journal
    await owner.change("g", "initialize", {}, lambda _: Account())

    def broken(a):
        raise ValueError("injected")

    with pytest.raises(ValueError):
        await owner.change("bad", "control", {}, broken)
    assert (await owner.read()).cash == 1000
    async with factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(text("DELETE FROM hybrid_events"))
    assert (await owner.read()).cash == 1000


async def test_configuration_identity_cannot_adopt_another_account(journal):
    owner, factory = journal
    await owner.change("g", "initialize", {}, lambda _: Account())
    with pytest.raises(ValueError):
        await HybridJournal(factory, "b" * 64).read()


async def test_batched_quotes_survive_journal_restart_and_duplicate_replay(journal):
    from datetime import UTC, datetime

    from trading_bot.config.hybrid import HybridSettings
    from trading_bot.hybrid.scenario import Scenario, replay

    owner, factory = journal
    await owner.change("genesis", "initialize", {}, lambda _: Account())
    now = datetime(2026, 10, 21, 14, tzinfo=UTC)
    scenario = Scenario.model_validate(
        {
            "steps": [
                {
                    "kind": "quote",
                    "at": now,
                    "quote": {
                        "symbol": symbol,
                        "bid": "100",
                        "ask": "100",
                        "as_of": now,
                    },
                }
                for symbol in ("AAA", "BBB")
            ]
        }
    )
    first = await replay(scenario, HybridSettings(), await owner.read(), owner=owner)
    restarted = HybridJournal(factory, "a" * 64)
    second = await replay(scenario, HybridSettings(), await restarted.read(), owner=restarted)
    assert first == second
    assert len(second.marks) == 2


class RequiredSimulationAccount(Account):
    profile: Literal["fixture-simulation-v1"]
    simulation_account_id: str = Field(min_length=1)


class RequiredSimulationJournal(HybridJournal):
    def _decode_account(self, raw: str) -> Account:
        return RequiredSimulationAccount.model_validate_json(raw)


async def test_default_decoder_keeps_original_account_wire_bytes(journal):
    owner, factory = journal
    expected = Account().model_dump_json()
    await owner.change("genesis", "initialize", {}, lambda _: Account())
    async with factory() as session:
        stored = await session.get(HybridEventRow, 0)
        assert stored is not None and stored.state_json == expected
    observed = await HybridJournal(factory, "a" * 64).read()
    assert type(observed) is Account and observed.model_dump_json() == expected


async def test_optin_decoder_preserves_required_metadata_and_revalidates_every_transition(journal):
    _, factory = journal
    owner = RequiredSimulationJournal(factory, "a" * 64)
    state = await owner.change(
        "genesis",
        "initialize",
        {},
        lambda _: RequiredSimulationAccount(
            profile="fixture-simulation-v1", simulation_account_id="fixture-account"
        ),
    )
    assert type(state) is RequiredSimulationAccount
    restarted = RequiredSimulationJournal(factory, "a" * 64)
    assert await restarted.read() == state
    changed = await restarted.change(
        "pause", "control", {"action": "pause"}, lambda a: a.model_copy(update={"paused": True})
    )
    assert type(changed) is RequiredSimulationAccount
    assert (
        changed.profile == "fixture-simulation-v1"
        and changed.simulation_account_id == "fixture-account"
    )
    with pytest.raises(ValueError):
        await restarted.change(
            "invalid", "control", {}, lambda a: a.model_copy(update={"profile": "foreign-profile"})
        )
    assert await restarted.read() == changed
    with pytest.raises(ValueError):
        await HybridJournal(factory, "a" * 64).read()


async def test_optin_decoder_cannot_adopt_old_account_with_missing_required_metadata(journal):
    legacy, factory = journal
    original = await legacy.change("genesis", "initialize", {}, lambda _: Account())
    selected = RequiredSimulationJournal(factory, "a" * 64)
    with pytest.raises(ValueError):
        await selected.read()
    with pytest.raises(ValueError):
        await selected.change("foreign", "control", {}, lambda a: a)
    assert await legacy.read() == original
