"""Real fictional SQLite joint-state tests; zero broker/provider calls."""

import asyncio
import hashlib
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
    _make_submission,
    _make_uow,
)
from trading_bot.accounting import (
    Bind,
    Complete,
    EconomicError,
    EconomicEvent,
    Execution,
    FinalFees,
    Funding,
    Opening,
    Release,
    Reserve,
    Settlement,
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


@pytest.mark.parametrize("prior_joint", [False, True])
@pytest.mark.parametrize("write_path", ["owned", "transition", "null_transition"])
async def test_bound_legacy_write_cannot_commit_even_after_joint_append(
    owned_engine, prior_joint, write_path
):
    from trading_bot.domain import (
        CorrelationId,
        OrderEvent,
        OrderState,
        OrderTransitionId,
    )
    from trading_bot.persistence.base import PersistenceDataError

    await seed_economics(owned_engine)
    async with _make_uow(owned_engine) as uow:
        if prior_joint:
            await owner(uow).append(execution_event())
        with pytest.raises(PersistenceDataError, match="joint economic publication"):
            if write_path == "owned":
                fact = execution_event().payload.event
                if prior_joint:
                    fact = replace(
                        owned_fact(index=4, kind=OrderEvent.REQUEST_CANCEL),
                        occurred_at=NOW + timedelta(seconds=4),
                    )
                await uow.orders.record_event(fact)
            else:
                i, b = _make_intent(), _make_broker_order(_make_intent())
                await uow.orders.add_transition(
                    OrderTransitionId("unpaired-transition"),
                    i.id,
                    None if write_path == "null_transition" else b.id,
                    OrderState.PARTIALLY_FILLED if prior_joint else OrderState.SUBMITTED,
                    OrderEvent.REQUEST_CANCEL,
                    OrderState.CANCEL_PENDING,
                    "fixture",
                    "unpaired",
                    NOW + timedelta(seconds=4),
                    CorrelationId("fixture-correl"),
                )
        with pytest.raises(UnitOfWorkStateError):
            await uow.commit()
    async with _make_uow(owned_engine) as restarted:
        s = await owner(restarted).get(AccountId("account-1"))
        assert s.book_cash == Decimal("500") and s.position.quantity == 0
        assert not s.obligations and s.event_count == 3


async def test_hostile_removed_counterpart_is_not_adopted_on_read_or_retry(
    owned_engine, database_path
):
    await seed_economics(owned_engine)
    async with _make_uow(owned_engine) as uow:
        await owner(uow).append(execution_event())
        await uow.commit()
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("DROP TRIGGER trg_owned_economic_delete")
        connection.execute("DELETE FROM owned_economic_events WHERE sequence=3")
        connection.commit()
    async with _make_uow(owned_engine) as restarted:
        with pytest.raises(EconomicError):
            await owner(restarted).get(AccountId("account-1"))
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


@pytest.mark.skipif(sys.platform == "win32", reason="real SIGKILL control requires POSIX")
@pytest.mark.parametrize("phase", ["owned", "economic", "committed"])
async def test_real_sigkill_recovers_only_complete_joint_state(owned_engine, database_url, phase):
    import signal

    await seed_economics(owned_engine)
    child = await asyncio.to_thread(
        subprocess.run,
        [
            sys.executable,
            "-m",
            "tests.integration.persistence._owned_economic_crash_worker",
            database_url,
            phase,
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert child.returncode == -signal.SIGKILL, child.stderr.decode()
    independent = create_engine(database_url)
    try:
        async with _make_uow(independent) as uow:
            s = await owner(uow).get(AccountId("account-1"))
            committed = phase == "committed"
            assert s.book_cash == Decimal("497.49" if committed else "500")
            assert s.settled_cash == Decimal("500")
            assert s.position.quantity == Decimal("0.25" if committed else "0")
            assert s.trial.reserved_risk == Decimal("13.225")
            assert await owner(uow).append(execution_event()) is (not committed)
            await uow.commit()
        async with _make_uow(independent) as uow:
            s = await owner(uow).get(AccountId("account-1"))
            assert s.book_cash == Decimal("497.49") and len(s.obligations) == 1
    finally:
        await independent.dispose()


async def test_final_fees_and_signed_settlement_survive_independent_restart(
    owned_engine, database_url
):
    from trading_bot.domain import OrderEvent, OrderId

    await seed_economics(owned_engine)
    async with _make_uow(owned_engine) as uow:
        await owner(uow).append(execution_event())
        for index, kind in [(4, OrderEvent.REQUEST_CANCEL), (5, OrderEvent.CANCEL_CONFIRMED)]:
            at = NOW + timedelta(seconds=index)
            control = replace(owned_fact(index=index, kind=kind), occurred_at=at)
            await owner(uow).append(e(Execution(control), index))
        await owner(uow).append(e(FinalFees(OrderId("order-1"), Decimal("0.04")), 6))
        await uow.commit()
    independent = create_engine(database_url)
    try:
        async with _make_uow(independent) as uow:
            s = await owner(uow).get(AccountId("account-1"))
            assert s.book_cash == Decimal("497.46")
            assert s.settled_cash == Decimal("500")
            assert not s.orders[0].released and len(s.obligations) == 2
            assert sorted(o.amount for o in s.obligations) == [Decimal("-2.51"), Decimal("-0.03")]
            for index, obligation in enumerate(s.obligations, 7):
                await owner(uow).append(e(Settlement(obligation.id, obligation.amount), index))
            await owner(uow).append(e(Release(OrderId("order-1")), 9))
            await uow.commit()
        async with _make_uow(independent) as uow:
            s = await owner(uow).get(AccountId("account-1"))
            assert s.available_cash == s.book_cash == s.settled_cash == Decimal("497.46")
            assert s.position.quantity == Decimal("0.25") and not s.obligations
            assert s.orders[0].released and s.trial.reserved_risk == Decimal("13.225")
    finally:
        await independent.dispose()


async def test_exact_economic_capacity_retains_complete_history_then_denies(owned_engine):
    from sqlalchemy import insert

    from trading_bot.accounting import encode_economic_event
    from trading_bot.persistence.models import OwnedEconomicEventRow
    from trading_bot.persistence.owned_economic_journal import _hash

    rows = []
    head = "0" * 64
    for index in range(10_000):
        event = setup_events()[0] if index == 0 else e(Funding(Decimal("0")), index)
        row = OwnedEconomicEventRow(
            id=event.id,
            account_id=event.account_id,
            sequence=index,
            payload_json=encode_economic_event(event),
            config_hash=event.config_hash,
            code_hash="b" * 64,
            previous_hash=head,
            event_hash="0" * 64,
        )
        head = row.event_hash = _hash(row)
        rows.append({column.name: getattr(row, column.name) for column in row.__table__.columns})
    async with async_session_factory(owned_engine)() as session:
        await session.execute(insert(OwnedEconomicEventRow), rows)
        await session.commit()
    async with _make_uow(owned_engine) as uow:
        s = await owner(uow).get(AccountId("account-1"))
        assert s.event_count == 10_000 and s.book_cash == Decimal("500")
        assert not await owner(uow).append(e(Funding(Decimal("0")), 9999))
        with pytest.raises(EconomicError):
            await owner(uow).append(e(Funding(Decimal("1")), 10_000))
        with pytest.raises(UnitOfWorkStateError):
            await uow.commit()
    async with _make_uow(owned_engine) as restarted:
        assert (await owner(restarted).get(AccountId("account-1"))).event_count == 10_000


async def seed_additional_order(engine, intent, index):
    from trading_bot.domain import (
        BrokerOrderId,
        OrderId,
        ReviewId,
        SubmissionAttemptId,
        SubmissionOutcome,
    )

    submission = _make_submission(intent)
    submission = replace(
        submission,
        review_id=ReviewId(f"review-{index}"),
        submission_attempt_id=SubmissionAttemptId(f"attempt-{index}"),
        deduplication_key=hashlib.sha256(str(intent.id).encode()).hexdigest(),
        review=replace(
            submission.review,
            estimated_notional=intent.quantity * intent.limit_price,
            broker_review_id=f"paper-review-{index}",
        ),
    )
    order = replace(
        _make_broker_order(intent),
        id=OrderId(f"order-{index}"),
        broker_order_id=BrokerOrderId(f"broker-order-{index}"),
    )
    async with _make_uow(engine) as uow:
        await uow.orders.add(intent)
        await uow.orders.add_review(submission.review_id, submission.review)
        assert await uow.submission_attempts.reserve(submission, "paper", NOW)
        await uow.orders.add_broker_order(order, submission, "paper")
        await uow.submission_attempts.complete(
            submission.submission_attempt_id, SubmissionOutcome.ACCEPTED, NOW, order
        )
        await uow.commit()
    return order


async def finish_fictional_order(uow, order, start, price):
    from trading_bot.domain import Fill, FillId, OrderEvent, Side
    from trading_bot.domain.owned_order_lifecycle import OwnedOrderEvent

    at = NOW + timedelta(seconds=start)
    fill = Fill(
        FillId(f"fill-complete-{start}"),
        order.broker_order_id,
        order.account_id,
        order.instrument_id,
        order.side,
        order.requested_quantity,
        Decimal(price),
        Decimal("0.01"),
        at,
        DataHash(HASH_C),
    )
    fact = OwnedOrderEvent(
        f"owned-complete-{start}",
        order.id,
        OrderEvent.FILL,
        at,
        DataHash(HASH_C),
        fill,
        f"native-complete-{start}",
        0,
    )
    for event in (
        e(Execution(fact), start),
        e(FinalFees(order.id, Decimal("0.01")), start + 1),
        e(
            Settlement(
                fill.id,
                (-1 if order.side is Side.BUY else 1) * fill.quantity * fill.price - fill.fee,
            ),
            start + 2,
        ),
        e(Release(order.id), start + 3),
    ):
        await owner(uow).append(event)


async def test_completed_loss_then_profit_and_funding_do_not_replenish_after_restart(
    owned_engine, database_url
):
    from trading_bot.domain import OrderPurpose, Side

    await seed_economics(owned_engine)
    sell = replace(
        _make_intent(intent_id="intent-2"),
        side=Side.SELL,
        purpose=OrderPurpose.STRATEGY_EXIT,
        limit_price=Decimal("9"),
    )
    exit_order = await seed_additional_order(owned_engine, sell, 2)
    buy = _make_intent(intent_id="intent-3")
    buy_order = await seed_additional_order(owned_engine, buy, 3)
    profit_sell = replace(
        _make_intent(intent_id="intent-4"),
        side=Side.SELL,
        purpose=OrderPurpose.STRATEGY_EXIT,
        limit_price=Decimal("11"),
    )
    profit_order = await seed_additional_order(owned_engine, profit_sell, 4)
    async with _make_uow(owned_engine) as uow:
        await finish_fictional_order(uow, _make_broker_order(_make_intent()), 3, "10")
        for event in (
            e(Reserve(sell, "episode-1", Decimal("0.1"), Decimal("13.225")), 7),
            e(Bind(exit_order), 8),
        ):
            await owner(uow).append(event)
        await finish_fictional_order(uow, exit_order, 9, "9")
        await owner(uow).append(e(Complete("episode-1"), 13))
        await uow.commit()
    async with _make_uow(owned_engine) as uow:
        for event in (
            e(Reserve(buy, "episode-2", Decimal("0.1"), Decimal("13.225")), 14),
            e(Bind(buy_order), 15),
        ):
            await owner(uow).append(event)
        await finish_fictional_order(uow, buy_order, 16, "10")
        for event in (
            e(Reserve(profit_sell, "episode-2", Decimal("0.1"), Decimal("13.225")), 20),
            e(Bind(profit_order), 21),
        ):
            await owner(uow).append(event)
        await finish_fictional_order(uow, profit_order, 22, "11")
        await owner(uow).append(e(Complete("episode-2"), 26))
        await owner(uow).append(e(Funding(Decimal("100")), 27))
        await uow.commit()
    independent = create_engine(database_url)
    try:
        async with _make_uow(independent) as restarted:
            s = await owner(restarted).get(AccountId("account-1"))
            assert s.available_cash == s.settled_cash == s.book_cash == Decimal("599.96")
            assert s.position.quantity == 0 and s.trial.reserved_risk == 0
            assert s.trial.consumed_loss == Decimal("1.27")
            assert s.trial.remaining(Decimal("50")) == Decimal("48.73")
            assert not s.source_qualified and not s.cost_qualified
            assert not s.execution_enabled and not s.evidence_promotable
    finally:
        await independent.dispose()


@pytest.mark.parametrize(
    "field,value", [("strategy_version", "changed"), ("data_hash", DataHash("d" * 64))]
)
async def test_valid_same_id_intent_substitution_is_denied(owned_engine, field, value):
    opening, reservation, _ = setup_events()
    bad = replace(
        reservation,
        payload=replace(
            reservation.payload, intent=replace(reservation.payload.intent, **{field: value})
        ),
    )
    async with _make_uow(owned_engine) as uow:
        await owner(uow).append(opening)
        with pytest.raises(EconomicError):
            await owner(uow).append(bad)
        with pytest.raises(UnitOfWorkStateError):
            await uow.commit()
    async with _make_uow(owned_engine) as uow:
        assert await owner(uow).get(AccountId("account-1")) is None


@pytest.mark.parametrize("changed", ["broker_id", "client_id", "advanced"])
async def test_unowned_or_already_advanced_binding_does_not_adopt(owned_engine, changed):
    from trading_bot.domain import BrokerOrderId

    opening, reservation, binding = setup_events()
    if changed == "advanced":
        async with _make_uow(owned_engine) as uow:
            await uow.orders.record_event(execution_event().payload.event)
            await uow.commit()
        bad = binding
    else:
        updates = (
            {"broker_order_id": BrokerOrderId("foreign-broker")}
            if changed == "broker_id"
            else {"client_order_id": "foreign-client"}
        )
        bad = replace(binding, payload=Bind(replace(binding.payload.order, **updates)))
    async with _make_uow(owned_engine) as uow:
        for event in (opening, reservation):
            await owner(uow).append(event)
        with pytest.raises(EconomicError):
            await owner(uow).append(bad)
        with pytest.raises(UnitOfWorkStateError):
            await uow.commit()


async def test_same_owned_fact_with_different_economic_envelope_cannot_debit_twice(owned_engine):
    await seed_economics(owned_engine)
    async with _make_uow(owned_engine) as uow:
        await owner(uow).append(execution_event())
        await uow.commit()
    async with _make_uow(owned_engine) as uow:
        with pytest.raises(EconomicError):
            await owner(uow).append(replace(execution_event(), id="another-economic-envelope"))
    async with _make_uow(owned_engine) as uow:
        assert (await owner(uow).get(AccountId("account-1"))).book_cash == Decimal("497.49")


async def test_invalid_append_type_denies_and_latches_transaction(owned_engine):
    async with _make_uow(owned_engine) as uow:
        with pytest.raises(EconomicError):
            await owner(uow).append(object())
        with pytest.raises(UnitOfWorkStateError):
            await uow.commit()


async def test_cancelled_recovery_cannot_be_caught_then_committed(owned_engine, monkeypatch):
    from trading_bot.persistence.owned_economic_journal import SqlEconomicRepository

    async def cancelled(self, account):
        raise asyncio.CancelledError()

    monkeypatch.setattr(SqlEconomicRepository, "_recover", cancelled)
    async with _make_uow(owned_engine) as uow:
        with pytest.raises(asyncio.CancelledError):
            await owner(uow).get(AccountId("account-1"))
        with pytest.raises(UnitOfWorkStateError):
            await uow.commit()


async def test_execution_writer_false_is_not_adopted_as_economic_effect(owned_engine, monkeypatch):
    import trading_bot.persistence.owned_economic_journal as module

    await seed_economics(owned_engine)

    async def already_present(*args):
        return False

    with monkeypatch.context() as patch:
        patch.setattr(module, "record_owned_event", already_present)
        async with _make_uow(owned_engine) as uow:
            with pytest.raises(EconomicError):
                await owner(uow).append(execution_event())
            with pytest.raises(UnitOfWorkStateError):
                await uow.commit()
    async with _make_uow(owned_engine) as uow:
        assert (await owner(uow).get(AccountId("account-1"))).book_cash == Decimal("500")


async def test_changed_original_acceptance_hash_denies_economic_recovery(
    owned_engine, database_path
):
    await seed_economics(owned_engine)
    with closing(sqlite3.connect(database_path)) as connection:
        # Fixture-only hostile database owner: normal update is already denied.
        connection.execute("DROP TRIGGER trg_submission_attempts_contract_update")
        connection.execute(
            "UPDATE submission_attempts SET sanitized_response_hash=? WHERE id='attempt-1'",
            ("d" * 64,),
        )
        connection.commit()
    async with _make_uow(owned_engine) as uow:
        with pytest.raises(EconomicError):
            await owner(uow).get(AccountId("account-1"))
        with pytest.raises(UnitOfWorkStateError):
            await uow.commit()


async def test_zero_fee_adjustment_cannot_steal_another_orders_fill_reference(owned_engine):
    from trading_bot.accounting.owned_economic_codec import fee_obligation_id
    from trading_bot.domain import Fill, FillId, OrderEvent, OrderPurpose, Side
    from trading_bot.domain.owned_order_lifecycle import OwnedOrderEvent
    from trading_bot.persistence.models import OwnedEconomicEventRow

    await seed_economics(owned_engine)
    sell = replace(
        _make_intent(intent_id="intent-2"),
        side=Side.SELL,
        purpose=OrderPurpose.STRATEGY_EXIT,
        limit_price=Decimal("11"),
    )
    exit_order = await seed_additional_order(owned_engine, sell, 2)
    no_adjustment = e(FinalFees(exit_order.id, Decimal("0.01")), 8)
    entry = replace(
        owned_fact(quantity="1.25", kind=OrderEvent.FILL), occurred_at=NOW + timedelta(seconds=3)
    )
    entry = replace(
        entry,
        fill=replace(
            entry.fill, id=FillId(fee_obligation_id(no_adjustment)), occurred_at=entry.occurred_at
        ),
    )
    at = NOW + timedelta(seconds=6)
    exit_fill = Fill(
        FillId("exit-fill"),
        exit_order.broker_order_id,
        sell.account_id,
        sell.instrument_id,
        Side.SELL,
        sell.quantity,
        Decimal("11"),
        Decimal("0.01"),
        at,
        DataHash(HASH_C),
    )
    exit_fact = OwnedOrderEvent(
        "exit-owned",
        exit_order.id,
        OrderEvent.FILL,
        at,
        DataHash(HASH_C),
        exit_fill,
        "native-exit",
        0,
    )
    for_events = (
        e(Execution(entry), 3),
        e(Reserve(sell, "episode-1", Decimal("0.1"), Decimal("13.225")), 4),
        e(Bind(exit_order), 5),
        e(Execution(exit_fact), 6),
        e(FinalFees(entry.order_id, Decimal("0.01")), 7),
        no_adjustment,
        e(Settlement(entry.fill.id, Decimal("-12.51")), 9),
        e(Settlement(exit_fill.id, Decimal("13.74")), 10),
        e(Release(entry.order_id), 11),
        e(Release(exit_order.id), 12),
        e(Complete("episode-1"), 13),
    )
    async with _make_uow(owned_engine) as uow:
        for event in for_events:
            await owner(uow).append(event)
        await uow.commit()
    async with async_session_factory(owned_engine)() as session:
        row = await session.get(OwnedEconomicEventRow, "economics-9")
        assert row.order_id == "order-1" and row.intent_id == "intent-1"
    async with _make_uow(owned_engine) as uow:
        s = await owner(uow).get(AccountId("account-1"))
        assert s.book_cash == s.available_cash == s.settled_cash == Decimal("501.23")
        assert not s.obligations and s.trial.consumed_loss == 0


async def test_registered_account_is_denied_before_economic_read(owned_engine, monkeypatch):
    import trading_bot.logging as logging_module
    from trading_bot.logging import SecretRegistry

    monkeypatch.setattr(logging_module, "_REGISTRY_STATE", logging_module._RegistryState())
    SecretRegistry().register("fictional-sensitive-account")
    async with _make_uow(owned_engine) as uow:
        with pytest.raises(EconomicError):
            await owner(uow).get(AccountId("fictional-sensitive-account"))
        with pytest.raises(UnitOfWorkStateError):
            await uow.commit()


async def test_missing_original_order_denies_joint_recovery(owned_engine, database_path):
    await seed_economics(owned_engine)
    # Hostile temporary database owner; no production connection or schema.
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("DELETE FROM orders WHERE id='order-1'")
        connection.commit()
    async with _make_uow(owned_engine) as uow:
        with pytest.raises(EconomicError):
            await owner(uow).get(AccountId("account-1"))
        with pytest.raises(UnitOfWorkStateError):
            await uow.commit()
