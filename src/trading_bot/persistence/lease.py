"""SQLite single-leader execution lease with monotonic fencing tokens."""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trading_bot.clock import Clock, require_utc
from trading_bot.domain import AccountId
from trading_bot.persistence.models import ExecutionLeaseRow


class LeaseUnavailable(RuntimeError):
    pass


class StaleFencingToken(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ExecutionLease:
    account_id: AccountId
    owner: str
    fencing_token: int
    acquired_at: datetime
    expires_at: datetime


class LeaseRepository:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        clock: Clock,
        lifetime: timedelta = timedelta(seconds=30),
    ) -> None:
        self._factory = factory
        self._clock = clock
        self._lifetime = lifetime

    async def acquire(self, account_id: AccountId, *, owner: str) -> ExecutionLease:
        now = require_utc(self._clock.now())
        async with self._factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            row = await session.scalar(
                select(ExecutionLeaseRow).where(ExecutionLeaseRow.account_id == account_id)
            )
            if row is not None and row.expires_at > now:
                await session.rollback()
                raise LeaseUnavailable("execution lease is held")
            token = 1 if row is None else row.fencing_token + 1
            expires = now + self._lifetime
            evidence = self._hash(account_id, owner, token, expires)
            if row is None:
                session.add(
                    ExecutionLeaseRow(
                        id=f"execution-{account_id}",
                        account_id=account_id,
                        owner_id=owner,
                        fencing_token=token,
                        acquired_at=now,
                        heartbeat_at=now,
                        expires_at=expires,
                        evidence_hash=evidence,
                    )
                )
            else:
                row.owner_id = owner
                row.fencing_token = token
                row.acquired_at = now
                row.heartbeat_at = now
                row.expires_at = expires
                row.evidence_hash = evidence
            await session.commit()
        return ExecutionLease(account_id, owner, token, now, expires)

    async def take_over_expired(self, account_id: AccountId, *, owner: str) -> ExecutionLease:
        return await self.acquire(account_id, owner=owner)

    async def renew(self, lease: ExecutionLease) -> ExecutionLease:
        now = require_utc(self._clock.now())
        expires = now + self._lifetime
        statement = (
            update(ExecutionLeaseRow)
            .where(
                ExecutionLeaseRow.account_id == lease.account_id,
                ExecutionLeaseRow.owner_id == lease.owner,
                ExecutionLeaseRow.fencing_token == lease.fencing_token,
                ExecutionLeaseRow.expires_at > now,
            )
            .values(
                heartbeat_at=now,
                expires_at=expires,
                evidence_hash=self._hash(
                    lease.account_id, lease.owner, lease.fencing_token, expires
                ),
            )
        )
        async with self._factory.begin() as session:
            result = cast(CursorResult[Any], await session.execute(statement))
            if result.rowcount != 1:
                raise StaleFencingToken("execution lease fencing token is stale")
        return ExecutionLease(
            lease.account_id, lease.owner, lease.fencing_token, lease.acquired_at, expires
        )

    async def release(self, lease: ExecutionLease) -> None:
        now = require_utc(self._clock.now())
        # Retain the fencing high-water mark. Deleting this row lets a later owner
        # reuse token 1, making an old same-owner lease valid again (the ABA problem).
        statement = (
            update(ExecutionLeaseRow)
            .where(
                ExecutionLeaseRow.account_id == lease.account_id,
                ExecutionLeaseRow.owner_id == lease.owner,
                ExecutionLeaseRow.fencing_token == lease.fencing_token,
                ExecutionLeaseRow.expires_at > now,
            )
            .values(
                heartbeat_at=now,
                expires_at=now,
                evidence_hash=self._hash(lease.account_id, lease.owner, lease.fencing_token, now),
            )
        )
        async with self._factory.begin() as session:
            result = cast(CursorResult[Any], await session.execute(statement))
            if result.rowcount != 1:
                raise StaleFencingToken("execution lease fencing token is stale")

    @staticmethod
    def _hash(account_id: AccountId, owner: str, token: int, expires: datetime) -> str:
        return hashlib.sha256(
            f"{account_id}|{owner}|{token}|{expires.isoformat()}".encode()
        ).hexdigest()


__all__ = ["ExecutionLease", "LeaseRepository", "LeaseUnavailable", "StaleFencingToken"]
