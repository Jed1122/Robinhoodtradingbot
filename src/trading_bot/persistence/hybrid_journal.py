"""Transactional hash-chained experimental account snapshots on the canonical ledger."""

import hashlib
import json
import re
from collections.abc import Callable

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trading_bot.hybrid.models import Account
from trading_bot.persistence.base import _require_validated_session_factory
from trading_bot.persistence.models.hybrid import HybridEventRow


def _hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


class HybridJournal:
    """One isolated experimental account per ledger; no production identity adoption."""

    def __init__(self, factory: async_sessionmaker[AsyncSession], config_hash: str) -> None:
        _require_validated_session_factory(factory)
        if re.fullmatch(r"[0-9a-f]{64}", config_hash) is None:
            raise ValueError("invalid configuration identity")
        self.factory, self.config_hash = factory, config_hash

    async def _read(self, session: AsyncSession) -> tuple[Account | None, list[HybridEventRow]]:
        rows = list(
            (await session.scalars(select(HybridEventRow).order_by(HybridEventRow.sequence))).all()
        )
        previous = "0" * 64
        state = None
        for sequence, row in enumerate(rows):
            digest = _hash(
                [
                    sequence,
                    row.event_id,
                    row.kind,
                    row.request_hash,
                    row.config_hash,
                    previous,
                    row.state_json,
                ]
            )
            if (
                row.sequence != sequence
                or row.previous_hash != previous
                or row.config_hash != self.config_hash
                or row.event_hash != digest
            ):
                raise ValueError("hybrid history identity or chain invalid")
            state = Account.model_validate_json(row.state_json)
            previous = digest
        return state, rows

    async def read(self) -> Account:
        async with self.factory() as session:
            state, _ = await self._read(session)
            if state is None:
                raise ValueError("experimental account not initialized")
            return state

    async def change(
        self,
        event_id: str,
        kind: str,
        request: dict[str, object],
        transition: Callable[[Account], Account],
    ) -> Account:
        if re.fullmatch(r"[A-Za-z0-9:_.-]{1,128}", event_id) is None or kind not in {
            "initialize",
            "control",
            "order",
            "fill",
            "cancel",
            "settle",
            "job",
            "mark",
            "research",
        }:
            raise ValueError("invalid event identity or kind")
        request_hash = _hash([kind, request])
        async with self.factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                state, rows = await self._read(session)
                existing = next((row for row in rows if row.event_id == event_id), None)
                if existing:
                    if existing.request_hash != request_hash or state is None:
                        raise ValueError("conflicting request identity")
                    await session.rollback()
                    return state
                if state is None and kind != "initialize":
                    raise ValueError("account must be initialized explicitly")
                if state is not None and kind == "initialize":
                    raise ValueError("account already initialized")
                updated = transition(state or Account())
                updated = Account.model_validate_json(updated.model_dump_json())
                state_json = updated.model_dump_json()
                if len(state_json.encode()) > 1048576 or len(rows) >= 100000:
                    raise ValueError("experimental journal bounds reached")
                previous = rows[-1].event_hash if rows else "0" * 64
                digest = _hash(
                    [
                        len(rows),
                        event_id,
                        kind,
                        request_hash,
                        self.config_hash,
                        previous,
                        state_json,
                    ]
                )
                session.add(
                    HybridEventRow(
                        sequence=len(rows),
                        event_id=event_id,
                        kind=kind,
                        request_hash=request_hash,
                        config_hash=self.config_hash,
                        previous_hash=previous,
                        event_hash=digest,
                        state_json=state_json,
                    )
                )
                await session.commit()
                return updated
            except BaseException:
                await session.rollback()
                raise
