"""Real SQLite owned execution facts, using only fictional local submissions."""

import hashlib
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, insert, select, text
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
from trading_bot.domain.owned_order_lifecycle import (
    OwnedOrderEvent,
    advance_owned_order,
    encode_owned_event,
)
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.persistence.evidence import canonical_broker_order_response_sha256
from trading_bot.persistence.models import FillRow, OrderRow, OrderTransitionRow, OwnedOrderEventRow


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


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE broker_reviews SET normalized_intent_hash='" + "d" * 64 + "'",
        "UPDATE broker_reviews SET sanitized_response_hash='" + "d" * 64 + "'",
        "UPDATE broker_reviews SET outbound_payload_sha256='" + "d" * 64 + "'",
        "UPDATE broker_reviews SET estimated_fees='-1'",
        "UPDATE broker_reviews SET expires_at=reviewed_at",
        "UPDATE order_intents SET expires_at=created_at",
    ],
)
async def test_modified_review_and_intent_bindings_deny_recovery(owned_engine, statement):
    async with _make_uow(owned_engine) as uow:
        assert await owner(uow).record_event(event())
        await uow.commit()
    # Corrupt fictional persisted evidence; no provider or customer data is used.
    async with async_session_factory(owned_engine).begin() as session:
        await session.execute(text(statement))
    with pytest.raises(ValueError, match="owned_order_journal_invalid"):
        async with _make_uow(owned_engine) as uow:
            await owner(uow).get_broker_order(OrderId("order-1"))
    with pytest.raises(ValueError, match="owned_order_journal_invalid"):
        async with _make_uow(owned_engine) as uow:
            await owner(uow).record_event(event(index=1, quantity="1", kind=OrderEvent.FILL))
    assert await counts(owned_engine) == (1, 1)


async def test_missing_order_and_fill_reads_remain_absent(owned_engine: AsyncEngine):
    async with _make_uow(owned_engine) as uow:
        assert await owner(uow).get_broker_order(OrderId("missing")) is None
        assert await uow.fills.get(FillId("missing")) is None


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE fills SET fee='0.02'",
        "DELETE FROM fills",
        "UPDATE owned_order_events SET event_hash='" + "b" * 64 + "'",
        "DELETE FROM owned_order_events",
        "INSERT OR REPLACE INTO fills SELECT * FROM fills",
        "INSERT OR REPLACE INTO owned_order_events SELECT * FROM owned_order_events",
        "UPDATE fills SET rowid=-1",
        "UPDATE owned_order_events SET rowid=-1",
    ],
)
async def test_database_mutations_cannot_erase_execution_history(
    owned_engine, database_path, statement
):
    async with _make_uow(owned_engine) as uow:
        assert await owner(uow).record_event(event())
        await uow.commit()
    with closing(sqlite3.connect(database_path)) as raw:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            raw.execute(statement)
        raw.rollback()
    assert await counts(owned_engine) == (1, 1)
    async with _make_uow(owned_engine) as uow:
        assert (await owner(uow).get_broker_order(OrderId("order-1"))).filled_quantity == Decimal(
            "0.25"
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE owned_order_events SET previous_hash='" + "b" * 64 + "'",
        "UPDATE owned_order_events SET order_hash='" + "b" * 64 + "'",
        "UPDATE owned_order_events SET event_hash='" + "b" * 64 + "'",
        "UPDATE owned_order_events SET sequence=1",
        "UPDATE fills SET fee='0.02'",
        "UPDATE order_transitions SET config_hash='" + "b" * 64 + "'",
        "DELETE FROM owned_order_events",
        "DELETE FROM fills",
        "DELETE FROM order_transitions",
    ],
)
async def test_corrupt_or_missing_links_deny_reconstruction(owned_engine, database_path, mutation):
    async with _make_uow(owned_engine) as uow:
        assert await owner(uow).record_event(event())
        await uow.commit()
    # Explicit hostile database-owner fixture, not a claimed production protection.
    with closing(sqlite3.connect(database_path)) as raw:
        triggers = raw.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
        for (name,) in triggers:
            raw.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
        raw.execute(mutation)
        raw.commit()
    with pytest.raises(ValueError, match="owned_order_journal_invalid"):
        async with _make_uow(owned_engine) as uow:
            await owner(uow).get_broker_order(OrderId("order-1"))


async def test_control_event_cannot_retain_a_fill_link(owned_engine, database_path):
    async with _make_uow(owned_engine) as uow:
        assert await owner(uow).record_event(event())
        await uow.commit()
    payload = encode_owned_event(event(kind=OrderEvent.REQUEST_CANCEL))
    with closing(sqlite3.connect(database_path)) as raw:
        raw.execute("DROP TRIGGER trg_owned_order_update")
        raw.execute("UPDATE owned_order_events SET payload_json=?", (payload,))
        raw.commit()
    with pytest.raises(ValueError, match="owned_order_journal_invalid"):
        async with _make_uow(owned_engine) as uow:
            await owner(uow).get_broker_order(OrderId("order-1"))


async def test_independent_engine_restart_retains_pending_cancel(owned_engine, database_url):
    async with _make_uow(owned_engine) as uow:
        assert await owner(uow).record_event(event(kind=OrderEvent.REQUEST_CANCEL))
        assert await owner(uow).record_event(replace(event(index=1), occurrence_ordinal=0))
        await uow.commit()
    fresh = create_engine(database_url)
    try:
        async with _make_uow(fresh) as recovered:
            actual = await owner(recovered).get_broker_order(OrderId("order-1"))
            assert actual.state is OrderState.CANCEL_PENDING
            assert actual.filled_quantity == Decimal("0.25")
            assert not await owner(recovered).record_event(event(kind=OrderEvent.REQUEST_CANCEL))
            await recovered.commit()
    finally:
        await fresh.dispose()
    assert await counts(owned_engine) == (1, 2)


async def test_journal_publication_failure_rolls_back_prior_fill_flush(owned_engine):
    async with async_session_factory(owned_engine).begin() as session:
        await session.execute(
            text("""CREATE TRIGGER fixture_fail_journal BEFORE INSERT
            ON owned_order_events BEGIN SELECT RAISE(ABORT, 'fixture database failure'); END""")
        )
    with pytest.raises(ValueError, match="owned_order_journal_invalid"):
        async with _make_uow(owned_engine) as uow:
            await owner(uow).record_event(event())
            await uow.commit()
    assert await counts(owned_engine) == (0, 0)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE orders SET intent_id=NULL, review_id=NULL, submission_attempt_id=NULL",
        "UPDATE orders SET state='partially_filled', filled_quantity='0.25'",
    ],
)
async def test_unowned_or_incomplete_initial_response_cannot_be_adopted(owned_engine, statement):
    async with async_session_factory(owned_engine).begin() as session:
        await session.execute(text(statement))
    with pytest.raises(ValueError, match="owned_order_journal_invalid"):
        async with _make_uow(owned_engine) as uow:
            await owner(uow).get_broker_order(OrderId("order-1"))


async def test_unjournaled_local_transition_is_not_silently_ignored(owned_engine):
    async with _make_uow(owned_engine) as uow:
        await uow.orders.add_transition(
            "foreign-transition",
            _make_intent().id,
            OrderId("order-1"),
            OrderState.SUBMITTED,
            OrderEvent.REQUEST_CANCEL,
            OrderState.CANCEL_PENDING,
            "fixture",
            "fixture",
            NOW,
            "correlation-1",
        )
        await uow.commit()
    with pytest.raises(ValueError, match="owned_order_journal_invalid"):
        async with _make_uow(owned_engine) as uow:
            await owner(uow).get_broker_order(OrderId("order-1"))


async def test_initial_submission_transition_can_coexist_with_owned_history(owned_engine):
    async with _make_uow(owned_engine) as uow:
        await uow.orders.add_transition(
            "transition-accepted-" + hashlib.sha256(b"intent-1|transition-accepted").hexdigest(),
            _make_intent().id,
            OrderId("order-1"),
            OrderState.SUBMISSION_PENDING,
            OrderEvent.BROKER_ACCEPTED,
            OrderState.SUBMITTED,
            "execution-service",
            "broker_accepted",
            NOW,
            "execution-" + hashlib.sha256(b"intent-1|execution").hexdigest(),
        )
        assert await owner(uow).record_event(event())
        await uow.commit()
    assert await counts(owned_engine) == (1, 2)


@pytest.mark.parametrize("invalid", ["duplicate", "future", "id", "actor", "reason", "correlation"])
async def test_unrelated_acceptance_transition_denies_recovery_and_fill(owned_engine, invalid):
    expected_id = (
        "transition-accepted-" + hashlib.sha256(b"intent-1|transition-accepted").hexdigest()
    )
    expected_correlation = "execution-" + hashlib.sha256(b"intent-1|execution").hexdigest()
    async with _make_uow(owned_engine) as uow:
        for index in range(2 if invalid == "duplicate" else 1):
            await uow.orders.add_transition(
                "unrelated" if invalid == "id" or index else expected_id,
                _make_intent().id,
                OrderId("order-1"),
                OrderState.SUBMISSION_PENDING,
                OrderEvent.BROKER_ACCEPTED,
                OrderState.SUBMITTED,
                "foreign-owner" if invalid == "actor" else "execution-service",
                "foreign-reason" if invalid == "reason" else "broker_accepted",
                NOW + timedelta(days=5) if invalid == "future" else NOW,
                "foreign-correlation" if invalid == "correlation" else expected_correlation,
            )
        await uow.commit()
    with pytest.raises(ValueError, match="owned_order_journal_invalid"):
        async with _make_uow(owned_engine) as uow:
            await owner(uow).get_broker_order(OrderId("order-1"))
    with pytest.raises(ValueError, match="owned_order_journal_invalid"):
        async with _make_uow(owned_engine) as uow:
            await owner(uow).record_event(event())
    assert await counts(owned_engine) == (0, 2 if invalid == "duplicate" else 1)


@pytest.mark.parametrize("method", ["order", "fill", "list"])
async def test_read_identifiers_and_times_are_strict(owned_engine, method):
    with pytest.raises(ValueError, match="owned_order_journal_invalid"):
        async with _make_uow(owned_engine) as uow:
            if method == "order":
                await owner(uow).get_broker_order(OrderId(""))
            elif method == "fill":
                await uow.fills.get(FillId(""))
            else:
                await uow.fills.list_for_account(AccountId("account-1"), NOW.replace(tzinfo=None))


async def test_concurrent_append_cannot_publish_two_effects(owned_engine):
    first = _make_uow(owned_engine)
    second = _make_uow(owned_engine)
    async with first, second:
        assert (await owner(second).get_broker_order(OrderId("order-1"))).filled_quantity == 0
        assert await owner(first).record_event(event())
        await first.commit()
        try:
            result = await owner(second).record_event(event())
        except ValueError as error:
            assert str(error) == "owned_order_journal_invalid"
        else:
            assert result is False
            await second.commit()
    assert await counts(owned_engine) == (1, 1)


async def _seed_controls(engine, count):
    """Bound fixture uses complete real encodings, not owner insertion shortcuts."""
    actual = _make_broker_order(_make_intent())

    def digest(parts):
        return hashlib.sha256(
            json.dumps(parts, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode(
                "ascii"
            )
        ).hexdigest()

    head = digest(
        ["owned-equity-lifecycle-v1", "paper", canonical_broker_order_response_sha256(actual)]
    )
    journals, transitions = [], []
    for index in range(count):
        kind = OrderEvent.RECONCILIATION_DRIFT if index % 2 == 0 else OrderEvent.RECONCILE_SUBMITTED
        next_event = event(index=index, kind=kind)
        projected = advance_owned_order(actual, next_event)
        payload = encode_owned_event(next_event)
        transition_id = digest(["owned-equity-lifecycle-v1", "transition", next_event.id])
        order_hash = canonical_broker_order_response_sha256(projected)
        new_head = digest(["owned-equity-lifecycle-v1", index, head, payload, order_hash])
        transitions.append(
            dict(
                id=transition_id,
                intent_id="intent-1",
                order_id="order-1",
                from_state=actual.state.value,
                event=kind.value,
                to_state=projected.state.value,
                actor="owned_execution",
                reason_code="owned_lifecycle_fact",
                occurred_at=next_event.occurred_at,
                config_hash=_make_intent().config_hash,
                correlation_id=next_event.id,
                corrects_id=None,
            )
        )
        journals.append(
            dict(
                id=next_event.id,
                order_id="order-1",
                intent_id="intent-1",
                sequence=index,
                payload_json=payload,
                previous_hash=head,
                event_hash=new_head,
                order_hash=order_hash,
                transition_id=transition_id,
                fill_id=None,
            )
        )
        actual, head = projected, new_head
    async with async_session_factory(engine).begin() as session:
        await session.execute(insert(OrderTransitionRow), transitions)
        await session.execute(insert(OwnedOrderEventRow), journals)


async def test_exact_lifetime_bound_retains_terminal_retry_but_denies_new_fact(owned_engine):
    await _seed_controls(owned_engine, 10000)
    async with _make_uow(owned_engine) as uow:
        assert not await owner(uow).record_event(
            event(index=9999, kind=OrderEvent.RECONCILE_SUBMITTED)
        )
        assert (await owner(uow).get_broker_order(OrderId("order-1"))).state is OrderState.SUBMITTED
    with pytest.raises(ValueError, match="owned_order_journal_invalid"):
        async with _make_uow(owned_engine) as uow:
            await owner(uow).record_event(event(index=10000, kind=OrderEvent.RECONCILIATION_DRIFT))
    assert await counts(owned_engine) == (0, 10000)


async def test_downgrade_refuses_nonempty_owned_history(owned_engine, alembic_config):
    import asyncio

    async with _make_uow(owned_engine) as uow:
        assert await owner(uow).record_event(event())
        await uow.commit()
    with pytest.raises(RuntimeError, match="cannot downgrade nonempty"):
        await asyncio.to_thread(command.downgrade, alembic_config, "0008_etf_replay_history")
    assert await counts(owned_engine) == (1, 1)


@pytest.mark.skipif(sys.platform == "win32", reason="real SIGKILL control requires POSIX")
@pytest.mark.parametrize(
    "phase,expected", [("fill", (0, 0)), ("transition", (0, 0)), ("committed", (1, 1))]
)
async def test_real_process_kill_never_publishes_a_partial_effect(
    owned_engine, database_url, phase, expected
):
    import asyncio
    import signal

    child = await asyncio.to_thread(
        subprocess.run,
        [
            sys.executable,
            "-m",
            "tests.integration.persistence._owned_order_crash_worker",
            database_url,
            phase,
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert child.returncode == -signal.SIGKILL, child.stderr.decode()
    assert await counts(owned_engine) == expected
    async with _make_uow(owned_engine) as uow:
        current = await owner(uow).get_broker_order(OrderId("order-1"))
        assert current.filled_quantity == (
            Decimal("0.25") if phase == "committed" else Decimal("0")
        )
        assert await owner(uow).record_event(event()) is (phase != "committed")
        await uow.commit()
    assert await counts(owned_engine) == (1, 1)
