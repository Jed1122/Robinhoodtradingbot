"""Real SQLite owned execution facts, using only fictional local submissions."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.persistence.test_unit_of_work import (
    HASH_C,
    NOW,
    _make_broker_order,
    _make_intent,
    _make_submission,
    _make_uow,
    _seed_parents,
)
from trading_bot.domain import (
    AccountId,
    DataHash,
    Fill,
    FillId,
    OrderEvent,
    OrderId,
    OrderState,
    SubmissionOutcome,
)
from trading_bot.domain.owned_order_lifecycle import OwnedOrderEvent
from trading_bot.persistence import async_session_factory
from trading_bot.persistence.models import FillRow, OrderRow, OrderTransitionRow


@pytest.fixture
def owned_schema(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")


@pytest.fixture
async def owned_engine(owned_schema: None, sqlite_engine: AsyncEngine) -> AsyncEngine:
    del owned_schema
    await _seed_parents(sqlite_engine)
    intent = _make_intent()
    submission = _make_submission(intent)
    async with _make_uow(sqlite_engine) as uow:
        await uow.orders.add(intent)
        await uow.orders.add_review(submission.review_id, submission.review)
        assert await uow.submission_attempts.reserve(submission, "paper", NOW)
        await uow.orders.add_broker_order(_make_broker_order(intent), submission, "paper")
        await uow.submission_attempts.complete(
            submission.submission_attempt_id,
            SubmissionOutcome.ACCEPTED,
            NOW,
            _make_broker_order(intent),
        )
        await uow.commit()
    return sqlite_engine


def event(*, index: int = 0, quantity: str = "0.25", kind=OrderEvent.PARTIAL_FILL):
    moment = NOW + timedelta(seconds=index + 1)
    order = _make_broker_order(_make_intent())
    fill = None
    if kind in {OrderEvent.PARTIAL_FILL, OrderEvent.FILL}:
        fill = Fill(
            FillId(f"fill-{index}"),
            order.broker_order_id,
            order.account_id,
            order.instrument_id,
            order.side,
            Decimal(quantity),
            Decimal("10"),
            Decimal("0.01"),
            moment,
            DataHash(HASH_C),
        )
    return OwnedOrderEvent(
        id=f"event-{index}",
        order_id=order.id,
        event=kind,
        occurred_at=moment,
        data_hash=DataHash(HASH_C),
        fill=fill,
        external_execution_key=None if fill is None else f"native-{index}",
        occurrence_ordinal=None if fill is None else index,
    )


def owner(uow):
    assert hasattr(uow.orders, "record_event"), "durable owned lifecycle API not implemented"
    assert hasattr(uow.orders, "get_broker_order"), "durable recovery API not implemented"
    return uow.orders


async def counts(engine):
    async with async_session_factory(engine)() as session:
        return (
            await session.scalar(select(func.count()).select_from(FillRow)),
            await session.scalar(select(func.count()).select_from(OrderTransitionRow)),
        )


async def test_partial_full_restart_and_original_response_preserved(owned_engine: AsyncEngine):
    async with _make_uow(owned_engine) as uow:
        assert await owner(uow).record_event(event())
        first = await owner(uow).get_broker_order(OrderId("order-1"))
        assert first.filled_quantity == Decimal("0.25")
        assert first.state is OrderState.PARTIALLY_FILLED
        await uow.commit()
    async with _make_uow(owned_engine) as restarted:
        assert await owner(restarted).record_event(
            event(index=1, quantity="1", kind=OrderEvent.FILL)
        )
        final = await owner(restarted).get_broker_order(OrderId("order-1"))
        assert final.filled_quantity == Decimal("1.25")
        assert final.state is OrderState.FILLED
        assert await restarted.fills.get(FillId("fill-0")) == event().fill
        assert len(await restarted.fills.list_for_account(AccountId("account-1"), NOW)) == 2
        assert await restarted.fills.list_for_account(AccountId("other"), NOW) == ()
        assert (
            len(
                await restarted.fills.list_for_account(
                    AccountId("account-1"), NOW + timedelta(seconds=2)
                )
            )
            == 1
        )
        await restarted.commit()
    assert await counts(owned_engine) == (2, 2)
    async with async_session_factory(owned_engine)() as session:
        original = await session.get(OrderRow, "order-1")
        assert original.filled_quantity == Decimal("0")
        assert original.state == "submitted"
        assert original.data_hash == HASH_C


async def test_exact_terminal_retry_is_idempotent(owned_engine: AsyncEngine):
    full = event(quantity="1.25", kind=OrderEvent.FILL)
    async with _make_uow(owned_engine) as uow:
        assert await owner(uow).record_event(full)
        assert not await owner(uow).record_event(full)
        await uow.commit()
    async with _make_uow(owned_engine) as uow:
        assert not await owner(uow).record_event(full)
        await uow.commit()
    assert await counts(owned_engine) == (1, 1)


@pytest.mark.parametrize(
    "changes",
    [
        {"data_hash": DataHash("b" * 64)},
        {"external_execution_key": "other"},
        {"occurrence_ordinal": 1},
    ],
)
async def test_conflicting_redelivery_rolls_back(owned_engine: AsyncEngine, changes):
    async with _make_uow(owned_engine) as uow:
        assert await owner(uow).record_event(event())
        await uow.commit()
    with pytest.raises(ValueError, match="owned_order_journal_invalid"):
        async with _make_uow(owned_engine) as uow:
            await owner(uow).record_event(replace(event(), **changes))
    assert await counts(owned_engine) == (1, 1)


async def test_failed_transaction_does_not_publish_fill_or_transition(owned_engine: AsyncEngine):
    with pytest.raises(ValueError, match="owned_order_journal_invalid"):
        async with _make_uow(owned_engine) as uow:
            assert await owner(uow).record_event(event())
            await owner(uow).record_event(event(index=1, quantity="2"))
            await uow.commit()
    assert await counts(owned_engine) == (0, 0)
    async with _make_uow(owned_engine) as uow:
        restored = await owner(uow).get_broker_order(OrderId("order-1"))
        assert restored.filled_quantity == Decimal("0")


async def test_cancel_race_and_terminal_preserve_actual_fills(owned_engine: AsyncEngine):
    async with _make_uow(owned_engine) as uow:
        assert await owner(uow).record_event(event(kind=OrderEvent.REQUEST_CANCEL))
        raced = replace(event(index=1), occurrence_ordinal=0)
        assert await owner(uow).record_event(raced)
        assert await owner(uow).record_event(event(index=2, kind=OrderEvent.CANCEL_CONFIRMED))
        current = await owner(uow).get_broker_order(OrderId("order-1"))
        assert current.filled_quantity == Decimal("0.25")
        assert current.state is OrderState.CANCELED
        await uow.commit()
    with pytest.raises(ValueError, match="owned_order_journal_invalid"):
        async with _make_uow(owned_engine) as uow:
            await owner(uow).record_event(replace(event(index=3), occurrence_ordinal=1))
    assert await counts(owned_engine) == (1, 3)


@pytest.mark.parametrize("change", ["missing", "foreign_account", "wrong_ordinal", "key_reuse"])
async def test_unknown_and_conflicting_fill_ownership_denies(owned_engine: AsyncEngine, change):
    bad = event()
    if change == "missing":
        bad = replace(bad, order_id=OrderId("missing"))
    elif change == "foreign_account":
        bad = replace(bad, fill=replace(bad.fill, account_id=AccountId("other")))
    elif change == "wrong_ordinal":
        bad = replace(bad, occurrence_ordinal=1)
    else:
        async with _make_uow(owned_engine) as uow:
            assert await owner(uow).record_event(event())
            await uow.commit()
        bad = replace(event(index=1), external_execution_key="native-0")
    with pytest.raises(ValueError, match="owned_order_journal_invalid"):
        async with _make_uow(owned_engine) as uow:
            await owner(uow).record_event(bad)
    assert await counts(owned_engine) == ((1, 1) if change == "key_reuse" else (0, 0))


async def test_modified_transition_denies_recovery(owned_engine: AsyncEngine):
    async with _make_uow(owned_engine) as uow:
        assert await owner(uow).record_event(event())
        await uow.commit()
    async with async_session_factory(owned_engine).begin() as session:
        await session.execute(text("DROP TRIGGER trg_order_transitions_append_only_update"))
        await session.execute(text("UPDATE order_transitions SET reason_code='other'"))
    with pytest.raises(ValueError, match="owned_order_journal_invalid"):
        async with _make_uow(owned_engine) as uow:
            await owner(uow).get_broker_order(OrderId("order-1"))


async def test_missing_order_and_fill_reads_remain_absent(owned_engine: AsyncEngine):
    async with _make_uow(owned_engine) as uow:
        assert await owner(uow).get_broker_order(OrderId("missing")) is None
        assert await uow.fills.get(FillId("missing")) is None
