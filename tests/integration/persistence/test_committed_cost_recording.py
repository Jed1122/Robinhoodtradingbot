"""Joint economic publication before observation; fictional SQLite facts only."""

import asyncio
import importlib
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.integration.persistence.test_owned_economic_journal import (
    execution_event,
    seed_economics,
)
from tests.integration.persistence.test_owned_order_journal import (
    owned_engine as _owned_engine_fixture,
)
from tests.integration.persistence.test_owned_order_journal import (
    owned_schema as _owned_schema_fixture,
)
from tests.integration.persistence.test_unit_of_work import NOW, _make_uow
from trading_bot.accounting import Execution, FinalFees
from trading_bot.domain import AccountId, FillId, OrderEvent, OrderId, OrderState
from trading_bot.persistence.unit_of_work import SqlAlchemyUnitOfWork

owned_engine = _owned_engine_fixture
owned_schema = _owned_schema_fixture


def api():
    return importlib.import_module("trading_bot.execution.committed_cost_recording")


class Observer:
    def __init__(self, engine, *, fail=False):
        self.engine, self.fail, self.facts = engine, fail, []

    async def observed(self, fact):
        # A separate transaction must see both committed projections already.
        async with _make_uow(self.engine) as read:
            state = await read.economics.get(AccountId("account-1"))
            order = await read.orders.get_broker_order(fact.order_id)
            assert state.position.quantity == order.filled_quantity == Decimal("0.25")
            assert state.book_cash == Decimal("497.49")
        self.facts.append(fact)
        if self.fail:
            raise OSError("synthetic recorder unavailable")


def writer(engine, observer):
    return api().CommittedCostRecording(
        account_id=AccountId("account-1"),
        uow_factory=lambda: _make_uow(engine),
        observer=observer,
    )


async def test_commits_joint_state_before_receipt_and_never_resamples_duplicate(owned_engine):
    await seed_economics(owned_engine)
    observer = Observer(owned_engine)
    service = writer(owned_engine, observer)
    first = await service.publish(execution_event())
    assert first.committed_new and first.receipt_status == "recorded"
    second = await service.publish(execution_event())
    assert not second.committed_new and second.receipt_status == "duplicate_not_resampled"
    assert len(observer.facts) == 1
    assert first.execution_enabled is first.evidence_promotable is False


async def test_restarted_projection_does_not_invent_original_receipt(owned_engine):
    await seed_economics(owned_engine)
    async with _make_uow(owned_engine) as uow:
        await uow.economics.append(execution_event())
        await uow.commit()
    observer = Observer(owned_engine)
    outcome = await writer(owned_engine, observer).publish(execution_event())
    assert outcome.receipt_status == "duplicate_not_resampled"
    assert not observer.facts


async def test_receipt_failure_preserves_joint_commit_and_duplicate_is_not_replayed(owned_engine):
    await seed_economics(owned_engine)
    observer = Observer(owned_engine, fail=True)
    service = writer(owned_engine, observer)
    assert (await service.publish(execution_event())).receipt_status == "receipt_unavailable"
    assert (await service.publish(execution_event())).receipt_status == "duplicate_not_resampled"
    async with _make_uow(owned_engine) as read:
        assert (await read.economics.get(AccountId("account-1"))).book_cash == Decimal("497.49")
    assert len(observer.facts) == 1


@pytest.mark.parametrize("after_commit", [False, True])
async def test_uncertain_commit_latches_without_observer_or_retry(
    owned_engine, monkeypatch, after_commit
):
    await seed_economics(owned_engine)
    observer = Observer(owned_engine)
    service = writer(owned_engine, observer)
    original = SqlAlchemyUnitOfWork.commit

    async def fail(self):
        if after_commit:
            await original(self)
        raise OSError("synthetic uncertain commit")

    with monkeypatch.context() as patch:
        patch.setattr(SqlAlchemyUnitOfWork, "commit", fail)
        with pytest.raises(api().CommittedCostRecordingError):
            await service.publish(execution_event())
    with pytest.raises(api().CommittedCostRecordingError):
        await service.publish(execution_event())
    assert not observer.facts
    async with _make_uow(owned_engine) as read:
        expected = Decimal("497.49") if after_commit else Decimal("500")
        assert (await read.economics.get(AccountId("account-1"))).book_cash == expected


async def test_conflicting_or_wrong_account_fact_never_observed(owned_engine):
    await seed_economics(owned_engine)
    observer = Observer(owned_engine)
    service = writer(owned_engine, observer)
    wrong = replace(execution_event(), account_id=AccountId("other-account"))
    with pytest.raises(api().CommittedCostRecordingError):
        await service.publish(wrong)
    assert not observer.facts


def next_execution():
    first = execution_event()
    at = NOW + timedelta(seconds=4)
    fact = replace(
        first.payload.event,
        id="event-final",
        event=OrderEvent.FILL,
        occurred_at=at,
        fill=replace(
            first.payload.event.fill,
            id=FillId("fill-final"),
            quantity=Decimal("1"),
            occurred_at=at,
        ),
        external_execution_key="native-final",
        occurrence_ordinal=1,
    )
    return replace(first, id="economics-4", occurred_at=at, payload=Execution(fact))


async def assert_completed_finances(engine):
    async with _make_uow(engine) as read:
        state = await read.economics.get(AccountId("account-1"))
        order = await read.orders.get_broker_order(OrderId("order-1"))
        assert state.book_cash == Decimal("487.48")
        assert state.position.quantity == order.filled_quantity == Decimal("1.25")
        assert state.event_count == 5
        assert order.state is OrderState.FILLED


async def test_later_financial_fact_commits_after_receipt_failure(owned_engine):
    await seed_economics(owned_engine)
    observer = Observer(owned_engine, fail=True)
    service = writer(owned_engine, observer)
    assert (await service.publish(execution_event())).receipt_status == "receipt_unavailable"
    next_outcome = await service.publish(next_execution())
    assert next_outcome.committed_new
    assert next_outcome.receipt_status == "receipt_unavailable"
    assert len(observer.facts) == 1
    await assert_completed_finances(owned_engine)


async def test_cancellation_facts_are_committed_without_hiding_partial_fill_or_finality(
    owned_engine,
):
    await seed_economics(owned_engine)
    observer = Observer(owned_engine)
    service = writer(owned_engine, observer)
    assert (await service.publish(execution_event())).receipt_status == "recorded"
    for index, kind in ((4, OrderEvent.REQUEST_CANCEL), (5, OrderEvent.CANCEL_CONFIRMED)):
        first = execution_event()
        at = NOW + timedelta(seconds=index)
        control = replace(
            first.payload.event,
            id=f"control-{index}",
            event=kind,
            occurred_at=at,
            fill=None,
            external_execution_key=None,
            occurrence_ordinal=None,
        )
        supplied = replace(
            first, id=f"economics-{index}", occurred_at=at, payload=Execution(control)
        )
        assert (await service.publish(supplied)).receipt_status == "recorded"
    assert [fact.event for fact in observer.facts] == [
        OrderEvent.PARTIAL_FILL,
        OrderEvent.REQUEST_CANCEL,
        OrderEvent.CANCEL_CONFIRMED,
    ]
    async with _make_uow(owned_engine) as read:
        state = await read.economics.get(AccountId("account-1"))
        order = await read.orders.get_broker_order(OrderId("order-1"))
        assert state.book_cash == Decimal("497.49")
        assert state.position.quantity == order.filled_quantity == Decimal("0.25")
        assert order.state is OrderState.CANCELED
        assert state.event_count == 6
        assert state.orders[0].fees_final is state.orders[0].released is False


async def test_concurrent_identical_delivery_commits_once_and_observes_once(owned_engine):
    await seed_economics(owned_engine)
    observer = Observer(owned_engine)
    service = writer(owned_engine, observer)
    outcomes = await asyncio.gather(*(service.publish(execution_event()) for _ in range(6)))
    assert sum(outcome.committed_new for outcome in outcomes) == 1
    assert [outcome.receipt_status for outcome in outcomes].count("recorded") == 1
    assert [outcome.receipt_status for outcome in outcomes].count("duplicate_not_resampled") == 5
    assert len(observer.facts) == 1
    async with _make_uow(owned_engine) as read:
        state = await read.economics.get(AccountId("account-1"))
        assert state.event_count == 4
        assert state.book_cash == Decimal("497.49")


@pytest.mark.parametrize("after_commit", [False, True])
async def test_cancelled_commit_preserves_actual_state_and_latches(
    owned_engine, monkeypatch, after_commit
):
    await seed_economics(owned_engine)
    observer = Observer(owned_engine)
    service = writer(owned_engine, observer)
    original = SqlAlchemyUnitOfWork.commit

    async def cancelled(self):
        if after_commit:
            await original(self)
        raise asyncio.CancelledError()

    with monkeypatch.context() as patch:
        patch.setattr(SqlAlchemyUnitOfWork, "commit", cancelled)
        with pytest.raises(asyncio.CancelledError):
            await service.publish(execution_event())
    with pytest.raises(api().CommittedCostRecordingError):
        await service.publish(execution_event())
    assert not observer.facts
    async with _make_uow(owned_engine) as read:
        state = await read.economics.get(AccountId("account-1"))
        assert state.book_cash == (Decimal("497.49") if after_commit else Decimal("500"))
        assert state.position.quantity == (Decimal("0.25") if after_commit else Decimal("0"))


class SimulatedProcessFailure(BaseException):
    pass


@pytest.mark.parametrize("failure", [asyncio.CancelledError, SimulatedProcessFailure])
async def test_observer_cancellation_or_crash_cannot_stop_next_financial_fact(
    owned_engine, failure
):
    await seed_economics(owned_engine)

    class InterruptedObserver(Observer):
        async def observed(self, fact):
            await super().observed(fact)
            raise failure()

    observer = InterruptedObserver(owned_engine)
    service = writer(owned_engine, observer)
    with pytest.raises(failure):
        await service.publish(execution_event())
    duplicate = await service.publish(execution_event())
    assert not duplicate.committed_new
    assert duplicate.receipt_status == "duplicate_not_resampled"
    outcome = await service.publish(next_execution())
    assert outcome.committed_new and outcome.receipt_status == "receipt_unavailable"
    assert len(observer.facts) == 1
    await assert_completed_finances(owned_engine)


async def test_process_death_after_commit_does_not_recreate_a_receipt(owned_engine, database_url):
    await seed_economics(owned_engine)
    script = """
import asyncio
import os
import sys
from tests.integration.persistence.test_owned_economic_journal import execution_event
from tests.integration.persistence.test_unit_of_work import _make_uow
from trading_bot.domain import AccountId
from trading_bot.execution.committed_cost_recording import CommittedCostRecording
from trading_bot.persistence import create_engine

class CrashAfterCommit:
    async def observed(self, fact):
        os._exit(73)

async def run():
    engine = create_engine(sys.argv[1])
    writer = CommittedCostRecording(
        account_id=AccountId('account-1'),
        uow_factory=lambda: _make_uow(engine),
        observer=CrashAfterCommit(),
    )
    await writer.publish(execution_event())

asyncio.run(run())
"""
    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-c", script, database_url],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 73, result.stderr
    observer = Observer(owned_engine)
    outcome = await writer(owned_engine, observer).publish(execution_event())
    assert not outcome.committed_new
    assert outcome.receipt_status == "duplicate_not_resampled"
    assert not observer.facts
    async with _make_uow(owned_engine) as read:
        state = await read.economics.get(AccountId("account-1"))
        assert state.book_cash == Decimal("497.49")
        assert state.event_count == 4


async def test_nested_caller_mutation_during_uow_entry_cannot_change_committed_fact(
    owned_engine, monkeypatch
):
    await seed_economics(owned_engine)
    observer = Observer(owned_engine)
    service = writer(owned_engine, observer)
    supplied = execution_event()
    original_enter = SqlAlchemyUnitOfWork.__aenter__

    async def mutating_enter(self):
        entered = await original_enter(self)
        object.__setattr__(supplied.payload.event.fill, "quantity", Decimal("1"))
        return entered

    with monkeypatch.context() as patch:
        patch.setattr(SqlAlchemyUnitOfWork, "__aenter__", mutating_enter)
        outcome = await service.publish(supplied)
    assert outcome.committed_new and outcome.receipt_status == "recorded"
    assert observer.facts[0].fill.quantity == Decimal("0.25")
    async with _make_uow(owned_engine) as read:
        state = await read.economics.get(AccountId("account-1"))
        assert state.book_cash == Decimal("497.49")
        assert state.position.quantity == Decimal("0.25")


class PausedObserver:
    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.facts = []

    async def observed(self, fact):
        self.facts.append(fact)
        if len(self.facts) == 1:
            self.entered.set()
            await self.release.wait()


async def test_queued_publication_freezes_nested_fact_before_waiting_for_lock(owned_engine):
    await seed_economics(owned_engine)
    observer = PausedObserver()
    service = writer(owned_engine, observer)
    first = asyncio.create_task(service.publish(execution_event()))
    await asyncio.wait_for(observer.entered.wait(), timeout=5)
    supplied = next_execution()
    started = asyncio.Event()

    async def queue_fact():
        started.set()
        return await service.publish(supplied)

    second = asyncio.create_task(queue_fact())
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        object.__setattr__(supplied.payload.event.fill, "quantity", Decimal("0.5"))
        observer.release.set()
        outcomes = await asyncio.wait_for(asyncio.gather(first, second), timeout=5)
        assert all(outcome.committed_new for outcome in outcomes)
        assert all(outcome.receipt_status == "recorded" for outcome in outcomes)
        assert [fact.fill.quantity for fact in observer.facts] == [Decimal("0.25"), Decimal("1")]
        await assert_completed_finances(owned_engine)
    finally:
        observer.release.set()
        for task in (first, second):
            if not task.done():
                task.cancel()
        await asyncio.gather(first, second, return_exceptions=True)


async def test_cancelling_lock_waiter_does_not_poison_active_or_later_publication(owned_engine):
    await seed_economics(owned_engine)
    observer = PausedObserver()
    service = writer(owned_engine, observer)
    first = asyncio.create_task(service.publish(execution_event()))
    await asyncio.wait_for(observer.entered.wait(), timeout=5)
    started = asyncio.Event()

    async def queue_duplicate():
        started.set()
        return await service.publish(execution_event())

    waiting = asyncio.create_task(queue_duplicate())
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        observer.release.set()
        assert (await asyncio.wait_for(first, timeout=5)).receipt_status == "recorded"
        assert (await service.publish(next_execution())).receipt_status == "recorded"
        assert len(observer.facts) == 2
        await assert_completed_finances(owned_engine)
    finally:
        observer.release.set()
        for task in (first, waiting):
            if not task.done():
                task.cancel()
        await asyncio.gather(first, waiting, return_exceptions=True)


async def test_nonexecution_fact_is_denied_without_financial_mutation(owned_engine):
    await seed_economics(owned_engine)
    observer = Observer(owned_engine)
    service = writer(owned_engine, observer)
    wrong_kind = replace(execution_event(), payload=FinalFees(OrderId("order-1"), Decimal("0.01")))
    with pytest.raises(api().CommittedCostRecordingError):
        await service.publish(wrong_kind)
    assert not observer.facts
    async with _make_uow(owned_engine) as read:
        state = await read.economics.get(AccountId("account-1"))
        assert state.event_count == 3
        assert state.book_cash == Decimal("500")


@pytest.mark.parametrize("account", [None, "", " ", "x" * 256])
def test_invalid_account_binding_is_rejected_without_constructing_writer(owned_engine, account):
    with pytest.raises(api().CommittedCostRecordingError):
        api().CommittedCostRecording(
            account_id=account,
            uow_factory=lambda: _make_uow(owned_engine),
            observer=Observer(owned_engine),
        )
