"""Fenced, append-only synthetic trial journal with restart reconstruction.

This stores simulation evidence, not broker-confirmed settlement or live authority.
Only a future separately verified reconciler may establish real completion facts.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trading_bot.clock import Clock, require_utc
from trading_bot.domain import AccountId
from trading_bot.domain.decimal_utils import (
    DomainValidationError,
    _require_nonempty,
    _require_sha256_hex,
)
from trading_bot.market_data.bundle_codec import _boolean, _decimal, _json, _mapping, _string, _time
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.persistence.lease import ExecutionLease, StaleFencingToken
from trading_bot.persistence.models import ExecutionLeaseRow, OptionsTrialEventRow
from trading_bot.risk.options_economics import TrialEpisode, TrialLossState

_GENESIS = "0" * 64
_LIMITS = BundleLimits(16384, 16384, 16384, 100, 8)


@dataclass(frozen=True, slots=True)
class TrialJournalEvent:
    event_id: str
    occurred_at: datetime
    config_hash: str
    episode: TrialEpisode

    def __post_init__(self) -> None:
        _require_nonempty(self.event_id, "event ID")
        if len(self.event_id) > 255:
            raise DomainValidationError("event ID too long")
        require_utc(self.occurred_at)
        _require_sha256_hex(self.config_hash, "config hash")
        if type(self.episode) is not TrialEpisode:
            raise DomainValidationError("exact trial episode required")


@dataclass(frozen=True, slots=True)
class TrialJournalSnapshot:
    events: tuple[TrialJournalEvent, ...]
    state: TrialLossState
    head_hash: str


def _payload(event: TrialJournalEvent) -> str:
    result = canonical_json(
        {"schema": "options-trial-event-v1", "source_kind": "synthetic", "event": event}
    )
    if len(result.encode()) > 16384:
        raise DomainValidationError("trial event exceeds journal limit")
    return result


def _decode(payload: str) -> TrialJournalEvent:
    root = _mapping(
        _json(payload.encode(), max_bytes=16384, limits=_LIMITS), {"schema", "source_kind", "event"}
    )
    if root["schema"] != "options-trial-event-v1" or root["source_kind"] != "synthetic":
        raise DomainValidationError("unsupported trial journal evidence")
    event = _mapping(root["event"], {"event_id", "occurred_at", "config_hash", "episode"})
    episode = _mapping(
        event["episode"],
        {
            "episode_id",
            "reserved_risk",
            "net_cash_flow",
            "flat",
            "orders_terminal",
            "settlement_and_fees_final",
        },
    )
    result = TrialJournalEvent(
        _string(event["event_id"]),
        _time(event["occurred_at"]),
        _string(event["config_hash"]),
        TrialEpisode(
            _string(episode["episode_id"]),
            _decimal(episode["reserved_risk"]),
            None if episode["net_cash_flow"] is None else _decimal(episode["net_cash_flow"]),
            _boolean(episode["flat"]),
            _boolean(episode["orders_terminal"]),
            _boolean(episode["settlement_and_fees_final"]),
        ),
    )
    if _payload(result) != payload:
        raise DomainValidationError("noncanonical trial journal payload")
    return result


def _transition(episodes: dict[str, TrialEpisode], current: TrialEpisode) -> None:
    previous = episodes.get(current.episode_id)
    if previous is None:
        if current.complete or current.reserved_risk <= 0 or current.net_cash_flow is not None:
            raise DomainValidationError("trial episode must start with an unconsumed reservation")
    elif previous.complete or current.reserved_risk < previous.reserved_risk:
        raise DomainValidationError("trial history cannot reopen or reduce a reservation")
    episodes[current.episode_id] = current


def _hash(row: OptionsTrialEventRow) -> str:
    return str(
        content_hash(
            {
                "account_id": row.account_id,
                "sequence": row.sequence,
                "fencing_token": row.fencing_token,
                "payload_json": row.payload_json,
                "previous_hash": row.previous_hash,
            }
        )
    )


def _reconstruct(rows: list[OptionsTrialEventRow]) -> TrialLossState:
    previous_hash = _GENESIS
    episodes: dict[str, TrialEpisode] = {}
    previous_at: datetime | None = None
    for sequence, row in enumerate(rows):
        if (
            row.sequence != sequence
            or row.previous_hash != previous_hash
            or row.event_hash != _hash(row)
        ):
            raise DomainValidationError("options trial journal integrity failure")
        event = _decode(row.payload_json)
        if row.id != event.event_id or (
            previous_at is not None and event.occurred_at < previous_at
        ):
            raise DomainValidationError("options trial journal ordering failure")
        _transition(episodes, event.episode)
        previous_hash, previous_at = row.event_hash, event.occurred_at
    return TrialLossState(tuple(episodes.values()))


class OptionsTrialJournal:
    """One transaction checks the existing lease, history and append-only event.

    The bounded read intentionally fails closed at capacity; no rolling window can erase
    earlier losses. It must be replaced with verified streaming before larger histories.
    """

    def __init__(
        self, factory: async_sessionmaker[AsyncSession], clock: Clock, *, max_events: int = 5000
    ) -> None:
        if type(max_events) is not int or not 1 <= max_events <= 100000:
            raise DomainValidationError("invalid trial journal work bound")
        self._factory, self._clock, self._max_events = factory, clock, max_events

    async def _rows(self, session: AsyncSession, account_id: str) -> list[OptionsTrialEventRow]:
        rows = list(
            (
                await session.scalars(
                    select(OptionsTrialEventRow)
                    .where(OptionsTrialEventRow.account_id == account_id)
                    .order_by(OptionsTrialEventRow.sequence)
                    .limit(self._max_events + 1)
                )
            ).all()
        )
        if len(rows) > self._max_events:
            raise DomainValidationError("trial history exceeds bounded reconstruction capacity")
        return rows

    async def restore(self, account_id: AccountId) -> TrialLossState:
        return (await self.snapshot(account_id)).state

    async def events(self, account_id: AccountId) -> tuple[TrialJournalEvent, ...]:
        return (await self.snapshot(account_id)).events

    async def snapshot(self, account_id: AccountId) -> TrialJournalSnapshot:
        """Read one bounded, integrity-checked snapshot for deterministic reconstruction."""
        async with self._factory() as session:
            rows = await self._rows(session, account_id)
            state = _reconstruct(rows)
            return TrialJournalSnapshot(
                tuple(_decode(row.payload_json) for row in rows),
                state,
                rows[-1].event_hash if rows else _GENESIS,
            )

    async def append(
        self,
        lease: ExecutionLease,
        event: TrialJournalEvent,
        *,
        expected_state: TrialLossState | None = None,
        expected_head: str | None = None,
    ) -> str:
        if type(event) is not TrialJournalEvent or type(lease) is not ExecutionLease:
            raise DomainValidationError("invalid trial journal append")
        if expected_state is not None and type(expected_state) is not TrialLossState:
            raise DomainValidationError("invalid expected trial state")
        if expected_head is not None:
            _require_sha256_hex(expected_head, "expected trial head")
        now = require_utc(self._clock.now())
        if event.occurred_at > now:
            raise DomainValidationError("future trial event")
        payload = _payload(event)
        async with self._factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            leader = await session.scalar(
                select(ExecutionLeaseRow).where(
                    ExecutionLeaseRow.account_id == lease.account_id,
                    ExecutionLeaseRow.owner_id == lease.owner,
                    ExecutionLeaseRow.fencing_token == lease.fencing_token,
                )
            )
            # BEGIN IMMEDIATE and the query can wait. Compare after those awaits,
            # never authorize using a clock sample taken before obtaining the lock.
            if leader is None or leader.expires_at <= require_utc(self._clock.now()):
                raise StaleFencingToken("trial journal writer is not the current lease owner")
            rows = await self._rows(session, lease.account_id)
            state = _reconstruct(rows)
            current_head = rows[-1].event_hash if rows else _GENESIS
            duplicate = await session.get(OptionsTrialEventRow, event.event_id)
            if duplicate is not None:
                if duplicate.account_id != lease.account_id or duplicate.payload_json != payload:
                    raise DomainValidationError("conflicting trial event identity")
                if expected_head is not None and current_head not in (
                    expected_head,
                    duplicate.event_hash,
                ):
                    raise DomainValidationError("trial history changed after duplicate event")
                return duplicate.event_hash
            if expected_head is not None and current_head != expected_head:
                raise DomainValidationError("trial history changed before append")
            if expected_state is not None and state != expected_state:
                raise DomainValidationError("trial state changed before append")
            if len(rows) == self._max_events:
                raise DomainValidationError("trial journal append capacity reached")
            if rows and event.occurred_at < _decode(rows[-1].payload_json).occurred_at:
                raise DomainValidationError("out-of-order trial event")
            _transition({episode.episode_id: episode for episode in state.episodes}, event.episode)
            row = OptionsTrialEventRow(
                id=event.event_id,
                account_id=lease.account_id,
                sequence=len(rows),
                fencing_token=lease.fencing_token,
                payload_json=payload,
                previous_hash=rows[-1].event_hash if rows else _GENESIS,
            )
            row.event_hash = _hash(row)
            session.add(row)
            await session.flush()
            # A slow write is still uncommitted. Expiry here rolls the event back.
            if leader.expires_at <= require_utc(self._clock.now()):
                raise StaleFencingToken("trial journal lease expired during append")
            await session.commit()
            return row.event_hash
