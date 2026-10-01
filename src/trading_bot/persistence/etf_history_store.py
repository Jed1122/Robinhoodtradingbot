"""Atomic, fenced fixture-account history and paused restart reconstruction.

The complete immutable request must remain available on restore. This research
store never loads broker state, creates accounts, grants execution or infers facts.
Every committed event binds its exact source bytes and the resulting account state.
"""

from dataclasses import dataclass, replace
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trading_bot.clock import Clock, require_utc
from trading_bot.market_data.etf_source import _ns
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.persistence.base import _require_validated_session_factory
from trading_bot.persistence.lease import ExecutionLease
from trading_bot.persistence.models import EtfReplayEventRow, ExecutionLeaseRow
from trading_bot.simulation.etf_account import (
    EtfAccountEvent,
    EtfAccountRequest,
    EtfAccountResult,
    replay_etf_account,
)

_GENESIS = "0" * 64


class EtfStoreError(ValueError):
    def __init__(self) -> None:
        super().__init__("etf_store_invalid")


@dataclass(frozen=True, slots=True)
class EtfAccountCheckpoint:
    cursor: int
    fencing_token: int
    input_hash: str
    head_hash: str
    state: EtfAccountResult


def _payload(event: EtfAccountEvent) -> str:
    payload = canonical_json({"schema": "etf-replay-journal-v1", "event": event})
    if len(payload.encode()) > 16384:
        raise EtfStoreError()
    return payload


def _hash(row: EtfReplayEventRow) -> str:
    return content_hash(
        {
            name: getattr(row, name)
            for name in (
                "id",
                "account_id",
                "run_id",
                "input_hash",
                "source_event_id",
                "sequence",
                "fencing_token",
                "payload_json",
                "state_hash",
                "previous_hash",
            )
        }
    )


def _restore(request: EtfAccountRequest, rows: list[EtfReplayEventRow]) -> EtfAccountCheckpoint:
    input_hash = content_hash(request)
    previous = _GENESIS
    if len(rows) > len(request.events):
        raise EtfStoreError()
    for sequence, row in enumerate(rows):
        source = request.events[sequence]
        if (
            row.account_id != "etf-offline"
            or row.run_id != request.run_id
            or row.input_hash != input_hash
            or row.sequence != sequence
            or row.source_event_id != source.event_id
            or row.payload_json != _payload(source)
            or row.previous_hash != previous
            or row.event_hash != _hash(row)
            or row.id != content_hash((request.run_id, source.event_id))
        ):
            raise EtfStoreError()
        prefix = replay_etf_account(replace(request, events=request.events[: sequence + 1]))
        if prefix.state_hash != row.state_hash:
            raise EtfStoreError()
        previous = row.event_hash
    state = replay_etf_account(replace(request, events=request.events[: len(rows)]))
    return EtfAccountCheckpoint(
        len(rows), rows[-1].fencing_token if rows else 0, input_hash, previous, state
    )


class EtfHistoryStore:
    def __init__(self, factory: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self._factory = _require_validated_session_factory(factory)
        self._clock = clock

    async def _rows(
        self, session: AsyncSession, request: EtfAccountRequest
    ) -> list[EtfReplayEventRow]:
        return list(
            (
                await session.scalars(
                    select(EtfReplayEventRow)
                    .where(EtfReplayEventRow.run_id == request.run_id)
                    .order_by(EtfReplayEventRow.sequence)
                    .limit(10001)
                )
            ).all()
        )

    async def restore(self, request: EtfAccountRequest) -> EtfAccountCheckpoint:
        try:
            if type(request) is not EtfAccountRequest:
                raise EtfStoreError()
            replace(request)
            async with _require_validated_session_factory(self._factory)() as session:
                return _restore(request, await self._rows(session, request))
        except Exception:
            raise EtfStoreError() from None

    def _leader(
        self, row: ExecutionLeaseRow | None, lease: ExecutionLease, not_before: datetime
    ) -> datetime:
        now = require_utc(self._clock.now())
        if (
            row is None
            or lease.account_id != "etf-offline"
            or row.owner_id != lease.owner
            or row.fencing_token != lease.fencing_token
            or row.account_id != lease.account_id
            or now >= row.expires_at
            or now < max(not_before, row.acquired_at, row.heartbeat_at)
        ):
            raise EtfStoreError()
        return now

    async def append_event(
        self,
        request: EtfAccountRequest,
        lease: ExecutionLease,
        *,
        expected_cursor: int,
        event: EtfAccountEvent,
    ) -> EtfAccountCheckpoint:
        try:
            if (
                type(request) is not EtfAccountRequest
                or type(lease) is not ExecutionLease
                or type(expected_cursor) is not int
                or expected_cursor < 0
                or type(event) is not EtfAccountEvent
            ):
                raise EtfStoreError()
            replace(request)
            if expected_cursor >= len(request.events) or request.events[expected_cursor] != event:
                raise EtfStoreError()
            now = require_utc(self._clock.now())
            async with _require_validated_session_factory(self._factory)() as session:
                await session.execute(text("BEGIN IMMEDIATE"))
                leader = await session.scalar(
                    select(ExecutionLeaseRow).where(
                        ExecutionLeaseRow.account_id == lease.account_id
                    )
                )
                now = self._leader(leader, lease, now)
                rows = await self._rows(session, request)
                checkpoint = _restore(request, rows)
                if expected_cursor == checkpoint.cursor - 1:
                    self._leader(leader, lease, now)
                    return checkpoint
                if expected_cursor != checkpoint.cursor or event.at_ns > _ns(now):
                    raise EtfStoreError()
                state = replay_etf_account(
                    replace(request, events=request.events[: expected_cursor + 1])
                )
                row = EtfReplayEventRow(
                    id=content_hash((request.run_id, event.event_id)),
                    account_id=lease.account_id,
                    run_id=request.run_id,
                    input_hash=checkpoint.input_hash,
                    source_event_id=event.event_id,
                    sequence=checkpoint.cursor,
                    fencing_token=lease.fencing_token,
                    payload_json=_payload(event),
                    state_hash=state.state_hash,
                    previous_hash=checkpoint.head_hash,
                )
                row.event_hash = _hash(row)
                session.add(row)
                await session.flush()
                self._leader(leader, lease, now)
                try:
                    await session.commit()
                except Exception:
                    # A failure before DBAPI commit can leave SQLite's explicit
                    # transaction open after SQLAlchemy marks its transaction
                    # inactive. Discard that connection rather than returning it
                    # to the pool; closing rolls back any uncommitted write.
                    await session.invalidate()
                    raise
                return EtfAccountCheckpoint(
                    checkpoint.cursor + 1,
                    lease.fencing_token,
                    checkpoint.input_hash,
                    row.event_hash,
                    state,
                )
        except Exception:
            raise EtfStoreError() from None
