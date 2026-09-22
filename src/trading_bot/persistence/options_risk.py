"""Fenced immutable synthetic risk history, with no order/authorization capabilities."""

from dataclasses import dataclass, fields

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trading_bot.clock import Clock, require_utc
from trading_bot.config import LoadedConfig
from trading_bot.domain import AccountId
from trading_bot.domain.decimal_utils import DomainValidationError, _require_sha256_hex
from trading_bot.market_data.bundle_codec import _boolean, _decimal, _json, _mapping, _string, _time
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.persistence.lease import ExecutionLease, StaleFencingToken
from trading_bot.persistence.models import ExecutionLeaseRow, OptionsRiskEventRow
from trading_bot.risk.options_loss_history import (
    OptionsLossPoint,
    OptionsLossReport,
    evaluate_options_loss_history,
)

_GENESIS = "0" * 64
_LIMITS = BundleLimits(16384, 16384, 16384, 100, 8)


def encode_point(point: OptionsLossPoint) -> str:
    if type(point) is not OptionsLossPoint:
        raise DomainValidationError("validated risk point required")
    payload = canonical_json(
        {
            "schema": "options-risk-point-v1",
            "source_kind": "synthetic",
            "point": point,
        }
    )
    if len(payload.encode()) > 16384:
        raise DomainValidationError("risk point exceeds encoding bound")
    return payload


def decode_point(payload: str) -> OptionsLossPoint:
    root = _mapping(
        _json(payload.encode(), max_bytes=16384, limits=_LIMITS), {"schema", "source_kind", "point"}
    )
    if root["schema"] != "options-risk-point-v1" or root["source_kind"] != "synthetic":
        raise DomainValidationError("unsupported risk point evidence")
    p = _mapping(root["point"], {f.name for f in fields(OptionsLossPoint)})
    point = OptionsLossPoint(
        _string(p["event_id"]),
        AccountId(_string(p["account_id"])),
        _string(p["config_hash"]),
        _time(p["observed_at"]),
        _string(p["session_id"]),
        _time(p["session_open"]),
        _time(p["session_close"]),
        None if p["previous_session_close"] is None else _time(p["previous_session_close"]),
        _decimal(p["liquidation_equity"]),
        _decimal(p["cumulative_external_flows"]),
        _string(p["source_hash"]),
        _boolean(p["complete"]),
    )
    if encode_point(point) != payload:
        raise DomainValidationError("noncanonical risk point")
    return point


def _hash(row: OptionsRiskEventRow) -> str:
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


def _points(rows: list[OptionsRiskEventRow], account_id: AccountId) -> tuple[OptionsLossPoint, ...]:
    head, token = _GENESIS, 0
    result = []
    for sequence, row in enumerate(rows):
        if (
            row.sequence != sequence
            or row.previous_hash != head
            or row.event_hash != _hash(row)
            or row.fencing_token < token
            or row.account_id != account_id
        ):
            raise DomainValidationError("risk journal integrity failure")
        point = decode_point(row.payload_json)
        if row.id != point.event_id or point.account_id != account_id:
            raise DomainValidationError("risk journal identity failure")
        result.append(point)
        head, token = row.event_hash, row.fencing_token
    return tuple(result)


@dataclass(frozen=True, slots=True)
class RiskJournalSnapshot:
    points: tuple[OptionsLossPoint, ...]
    report: OptionsLossReport | None
    head_hash: str


class OptionsRiskJournal:
    """Bounded full reconstruction, never a rolling window that forgets a breach."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        clock: Clock,
        loaded: LoadedConfig,
        *,
        max_events: int = 5000,
    ) -> None:
        if type(max_events) is not int or not 1 <= max_events <= 100000:
            raise DomainValidationError("invalid risk journal bound")
        if type(loaded) is not LoadedConfig:
            raise DomainValidationError("canonical configuration required")
        self._factory, self._clock, self._loaded = factory, clock, loaded
        self._maximum = min(max_events, loaded.config.options.replay_max_records)

    async def _rows(
        self, session: AsyncSession, account_id: AccountId
    ) -> list[OptionsRiskEventRow]:
        rows = list(
            (
                await session.scalars(
                    select(OptionsRiskEventRow)
                    .where(OptionsRiskEventRow.account_id == account_id)
                    .order_by(OptionsRiskEventRow.sequence)
                    .limit(self._maximum + 1)
                )
            ).all()
        )
        if len(rows) > self._maximum:
            raise DomainValidationError("risk journal exceeds reconstruction bound")
        return rows

    async def snapshot(self, account_id: AccountId) -> RiskJournalSnapshot:
        async with self._factory() as session:
            rows = await self._rows(session, account_id)
            points = _points(rows, account_id)
            report = (
                evaluate_options_loss_history(
                    self._loaded, points, as_of=require_utc(self._clock.now())
                )
                if points
                else None
            )
            return RiskJournalSnapshot(points, report, rows[-1].event_hash if rows else _GENESIS)

    def _check_leader(self, leader: ExecutionLeaseRow | None) -> None:
        now = require_utc(self._clock.now())
        if (
            leader is None
            or now >= leader.expires_at
            or now < max(leader.acquired_at, leader.heartbeat_at)
        ):
            raise StaleFencingToken("risk writer lease expired, changed or clock regressed")

    async def append(
        self, lease: ExecutionLease, point: OptionsLossPoint, *, expected_head: str
    ) -> str:
        if type(lease) is not ExecutionLease or type(point) is not OptionsLossPoint:
            raise DomainValidationError("validated risk writer and observation required")
        if lease.account_id != point.account_id:
            raise DomainValidationError("risk writer account mismatch")
        _require_sha256_hex(expected_head, "expected risk head")
        payload = encode_point(point)
        async with self._factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            leader = await session.scalar(
                select(ExecutionLeaseRow).where(
                    ExecutionLeaseRow.account_id == lease.account_id,
                    ExecutionLeaseRow.owner_id == lease.owner,
                    ExecutionLeaseRow.fencing_token == lease.fencing_token,
                )
            )
            self._check_leader(leader)
            rows = await self._rows(session, lease.account_id)
            points = _points(rows, lease.account_id)
            head = rows[-1].event_hash if rows else _GENESIS
            duplicate = await session.get(OptionsRiskEventRow, point.event_id)
            if duplicate is not None:
                if (
                    duplicate.account_id != point.account_id
                    or duplicate.payload_json != payload
                    or head not in (expected_head, duplicate.event_hash)
                ):
                    raise DomainValidationError("conflicting or superseded risk event")
                evaluate_options_loss_history(self._loaded, points, as_of=self._clock.now())
                self._check_leader(leader)
                return duplicate.event_hash
            if head != expected_head or len(rows) >= self._maximum:
                raise DomainValidationError("risk head changed or journal full")
            evaluate_options_loss_history(self._loaded, (*points, point), as_of=self._clock.now())
            row = OptionsRiskEventRow(
                id=point.event_id,
                account_id=point.account_id,
                sequence=len(rows),
                fencing_token=lease.fencing_token,
                payload_json=payload,
                previous_hash=head,
            )
            row.event_hash = _hash(row)
            session.add(row)
            await session.flush()
            self._check_leader(leader)
            await session.commit()
            return row.event_hash
