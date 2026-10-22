"""Append-only stock research admission and cache references; no execution authority."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.clock import require_utc
from trading_bot.config import LoadedConfig
from trading_bot.config.loader import restore_loaded_config
from trading_bot.config.stock_research import StockWorkerAppConfig
from trading_bot.domain import (
    AuditEvent,
    AuditEventId,
    CodeHash,
    ConfigHash,
    CorrelationId,
    DataHash,
)
from trading_bot.logging import contains_registered_secret
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.persistence.audit import _stage_audit_event, serialize_audit_details
from trading_bot.persistence.base import _require_validated_session_factory
from trading_bot.persistence.models import AuditEventRow, ConfigurationVersionRow

type Phase = Literal["discovery", "enrichment"]
type Status = Literal["succeeded", "blocked", "failed", "cancelled"]

_MAX_EVENTS = 100000
_MAX_CONFIGURATIONS = 256
_ZERO = "0" * 64
_SCOPE = "robinhood_stock_research_v1"
_CATEGORY = "stock_research"
_ACTOR = "stock_research_worker"
_HASH_FIELDS = frozenset(
    {
        "claim_id",
        "previous_sha256",
        "config_hash",
        "code_hash",
        "plan_sha256",
        "source_result_sha256",
        "manifest_sha256",
        "report_sha256",
        "capture_plan_sha256",
    }
)
_REASONS = frozenset(
    {
        "complete",
        "capture_partial",
        "runtime_failure",
        "auth_unavailable",
        "cancelled",
        "schema_mismatch",
        "screen_incomplete",
        "source_stale",
        "artifact_unavailable",
        "report_failed",
        "storage_full",
        "control_denied",
    }
)
# Exact whitespace-normalized history guards from immutable migration0002. Merely
# retaining a trigger name (for example with a no-op body) does not satisfy this check.
_AUDIT_GUARDS = {
    "trg_audit_events_append_only_insert": (
        "d03e204cdfa3865101a8902d0f266ad939d886cef757361edc67175dc06e0951"
    ),
    "trg_audit_events_append_only_update": (
        "e4cba9cdf742a96bbb1fa4f4d492041efed4a713554c8d31bb509e7ce97451d7"
    ),
    "trg_audit_events_append_only_delete": (
        "d9e3576974d6172c591f271112390bdcbb6f3bbba5dc296c7ed4bda254f83df3"
    ),
    "trg_audit_events_append_only_rowid": (
        "679614b08cc50371eceae47b9fa64269326a3efd967146e2605100597a89e04d"
    ),
    "trg_configuration_versions_append_only_insert": (
        "797a0e8d5315624d9c517b06b91104bc1e0d194b1978b418046688f26cee67d6"
    ),
    "trg_configuration_versions_append_only_update": (
        "7c102acd77b1bc8173253a54541ee545181d7762dae873287f8d68ee4266f4db"
    ),
    "trg_configuration_versions_append_only_delete": (
        "20880b527dc23bdcf325a3933a2a9fc49a29cc51079cf206b95348f6a32c161a"
    ),
    "trg_configuration_versions_append_only_rowid": (
        "bdbaf3e269299c7a6b02d9a825f747c30678cb0712ff4a47f0e81d76af9c71e8"
    ),
}


class StockResearchJobError(ValueError):
    """Stable local denial; underlying database/provider text is never exposed."""


def _check(valid: bool, reason: str = "stock_job_history_invalid") -> None:
    if not valid:
        raise StockResearchJobError(reason)


def _sha(value: object) -> bool:
    return (
        type(value) is str
        and re.fullmatch("[0-9a-f]{64}", value) is not None
        and not contains_registered_secret(value)
    )


def _integer(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _slot(at: datetime, minutes: int) -> datetime:
    midnight = at.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight + timedelta(minutes=((at.hour * 60 + at.minute) // minutes) * minutes)


def _days(start: datetime, end: datetime) -> tuple[str, ...]:
    result = [start.date().isoformat()]
    if end.date() != start.date():
        result.append(end.date().isoformat())
    return tuple(result)


def _claim_id(slot: datetime) -> str:
    return str(content_hash((_SCOPE, slot)))


@dataclass(frozen=True, slots=True)
class StockResearchClaim:
    claim_id: str
    sequence: int
    previous_sha256: str
    config_hash: str
    code_hash: str
    phase: Phase
    slot_start: datetime
    claimed_at: datetime
    deadline_at: datetime
    scan_minutes: int
    plan_sha256: str
    planned_calls: int
    budget_days: tuple[str, ...]
    source_result_sha256: str | None
    record_sha256: str

    def __post_init__(self) -> None:
        for value in (
            self.claim_id,
            self.previous_sha256,
            self.config_hash,
            self.code_hash,
            self.plan_sha256,
            self.record_sha256,
        ):
            _check(_sha(value))
        _check(_integer(self.sequence, 1, _MAX_EVENTS))
        _check(self.phase in {"discovery", "enrichment"})
        _check(_integer(self.scan_minutes, 15, 60) and _integer(self.planned_calls, 1, 32))
        start, deadline = require_utc(self.claimed_at), require_utc(self.deadline_at)
        _check(require_utc(self.slot_start) == _slot(start, self.scan_minutes))
        _check(self.claim_id == _claim_id(self.slot_start))
        _check(60 <= (deadline - start).total_seconds() <= 450)
        _check(type(self.budget_days) is tuple and self.budget_days == _days(start, deadline))
        _check(self.source_result_sha256 is None or _sha(self.source_result_sha256))
        _check((self.phase == "enrichment") == (self.source_result_sha256 is not None))


@dataclass(frozen=True, slots=True)
class StockResearchResult:
    claim_id: str
    sequence: int
    previous_sha256: str
    config_hash: str
    code_hash: str
    phase: Phase
    recorded_at: datetime
    plan_sha256: str
    capture_plan_sha256: str | None
    attempted_calls: int
    successful_calls: int
    status: Status
    reason: str
    manifest_sha256: str | None
    report_sha256: str | None
    record_sha256: str
    live_enabled: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        for value in (
            self.claim_id,
            self.previous_sha256,
            self.config_hash,
            self.code_hash,
            self.plan_sha256,
            self.record_sha256,
        ):
            _check(_sha(value))
        _check(_integer(self.sequence, 1, _MAX_EVENTS))
        _check(self.phase in {"discovery", "enrichment"})
        require_utc(self.recorded_at)
        _check(_integer(self.attempted_calls, 0, 32))
        _check(_integer(self.successful_calls, 0, self.attempted_calls))
        _check(self.status in {"succeeded", "blocked", "failed", "cancelled"})
        _check(self.reason in _REASONS)
        for optional in (self.capture_plan_sha256, self.manifest_sha256, self.report_sha256):
            _check(optional is None or _sha(optional))
        if self.status == "succeeded":
            _check(self.reason == "complete")
            _check(self.manifest_sha256 is not None and self.report_sha256 is not None)
            _check(self.capture_plan_sha256 == self.plan_sha256)
        else:
            _check(self.reason != "complete" and self.report_sha256 is None)


type _Record = StockResearchClaim | StockResearchResult


def _wire(record: _Record) -> dict[str, Any]:
    payload = asdict(record)
    payload.pop("record_sha256")
    payload.update(
        kind="claim" if type(record) is StockResearchClaim else "result", version=1, scope=_SCOPE
    )
    # This closed codec accepts only already-validated SHA fields. It does not
    # encode free-form text or weaken the shared audit secret sanitizer.
    for key in _HASH_FIELDS:
        value = payload.get(key)
        if value is not None:
            _check(_sha(value))
            payload[key] = ":".join(value[index : index + 4] for index in range(0, 64, 4))
    result: dict[str, Any] = json.loads(canonical_json(payload))
    return result


def _hash_record(record: _Record) -> str:
    return str(content_hash(_wire(record)))


def _event(record: _Record) -> AuditEvent:
    claim = type(record) is StockResearchClaim
    return AuditEvent(
        id=AuditEventId(
            record.claim_id if claim else str(content_hash((_SCOPE, "result", record.claim_id)))
        ),
        occurred_at=record.claimed_at
        if isinstance(record, StockResearchClaim)
        else record.recorded_at,
        category=_CATEGORY,
        actor=_ACTOR,
        reason_code="claim" if claim else "result",
        correlation_id=CorrelationId(record.claim_id),
        config_hash=ConfigHash(record.config_hash),
        code_hash=CodeHash(record.code_hash),
        data_hash=DataHash(record.record_sha256),
        details=(("record", canonical_json(_wire(record))),),
    )


def _parse(row: AuditEventRow) -> _Record:
    _check(row.corrects_id is None and len(row.sanitized_details_json.encode()) <= 8192)
    details = json.loads(row.sanitized_details_json)
    _check(type(details) is list and len(details) == 1)
    _check(type(details[0]) is list and len(details[0]) == 2 and details[0][0] == "record")
    payload = json.loads(details[0][1])
    _check(type(payload) is dict)
    _check(
        payload.pop("scope") == _SCOPE
        and type(payload["version"]) is int
        and payload.pop("version") == 1
    )
    kind = payload.pop("kind")
    for key in _HASH_FIELDS:
        value = payload.get(key)
        if value is not None:
            _check(
                type(value) is str
                and re.fullmatch(r"[0-9a-f]{4}(?::[0-9a-f]{4}){15}", value) is not None
            )
            payload[key] = value.replace(":", "")
    payload["record_sha256"] = row.data_hash
    record: _Record
    if kind == "claim":
        for name in ("slot_start", "claimed_at", "deadline_at"):
            payload[name] = datetime.fromisoformat(payload[name])
        _check(type(payload["budget_days"]) is list)
        payload["budget_days"] = tuple(payload["budget_days"])
        record = StockResearchClaim(**payload)
    else:
        _check(kind == "result" and payload.pop("live_enabled") is False)
        payload["recorded_at"] = datetime.fromisoformat(payload["recorded_at"])
        record = StockResearchResult(**payload)
    _check(_hash_record(record) == record.record_sha256)
    event = _event(record)
    _check(
        (
            row.id,
            row.occurred_at,
            row.category,
            row.actor,
            row.reason_code,
            row.correlation_id,
            row.config_hash,
            row.code_hash,
            row.data_hash,
            row.sanitized_details_json,
        )
        == (
            event.id,
            event.occurred_at,
            event.category,
            event.actor,
            event.reason_code,
            event.correlation_id,
            event.config_hash,
            event.code_hash,
            event.data_hash,
            serialize_audit_details(event),
        )
    )
    return record


@dataclass(frozen=True, slots=True)
class StockResearchJobState:
    claims: tuple[StockResearchClaim, ...]
    results: tuple[StockResearchResult, ...]
    state_hash: str
    last_observed_at: datetime | None
    reserved_today: int
    discovery_head: StockResearchResult | None
    enrichment_head: StockResearchResult | None
    observed_at: datetime

    @property
    def pending_count(self) -> int:
        completed = {record.claim_id for record in self.results}
        return sum(claim.claim_id not in completed for claim in self.claims)


class SqlStockResearchJobs:
    """One fixed provider scope in the canonical ledger, independent of account journals."""

    def __init__(
        self,
        factory: object,
        *,
        loaded: LoadedConfig,
        code_hash: CodeHash,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._factory = _require_validated_session_factory(factory)
        self._engine = self._factory.kw["bind"]
        restored = restore_loaded_config(loaded.canonical_json, loaded.config_hash)
        _check(
            restored == loaded and type(restored.config) is StockWorkerAppConfig,
            "stock_worker_config_required",
        )
        _check(_sha(code_hash), "stock_worker_code_required")
        self._config = StockWorkerAppConfig.model_validate(restored.config.model_dump())
        self._loaded = restored
        self._config_hash, self._code_hash = str(loaded.config_hash), str(code_hash)
        self._clock = clock
        self._last_seen: datetime | None = None

    def _factory_check(self) -> None:
        try:
            checked = _require_validated_session_factory(self._factory)
            _check(checked.kw["bind"] is self._engine, "stock_job_factory_changed")
        except Exception:
            raise StockResearchJobError("stock_job_factory_changed") from None

    def _now(self, previous: datetime | None = None) -> datetime:
        now = require_utc(self._clock())
        _check(self._last_seen is None or now >= self._last_seen, "stock_job_clock_denied")
        _check(previous is None or now >= previous, "stock_job_clock_denied")
        self._last_seen = now
        return now

    async def _read(self, session: AsyncSession) -> tuple[list[_Record], datetime]:
        versions = list(
            (await session.scalars(text("SELECT version_num FROM alembic_version"))).all()
        )
        guards = (
            await session.execute(
                text(
                    "SELECT name, sql FROM sqlite_master "
                    "WHERE type='trigger' AND tbl_name IN "
                    "('audit_events', 'configuration_versions')"
                )
            )
        ).all()
        actual = {
            name: hashlib.sha256(" ".join(sql.split()).encode()).hexdigest() for name, sql in guards
        }
        _check(
            versions == ["0011_hybrid_experimental"] and actual == _AUDIT_GUARDS,
            "stock_job_schema_denied",
        )
        rows = list(
            (
                await session.scalars(
                    select(AuditEventRow)
                    .where(AuditEventRow.category == _CATEGORY)
                    .limit(_MAX_EVENTS + 1)
                )
            ).all()
        )
        _check(len(rows) <= _MAX_EVENTS, "stock_job_history_limit")
        records = sorted((_parse(row) for row in rows), key=lambda item: item.sequence)
        claims: dict[str, StockResearchClaim] = {}
        results: set[str] = set()
        verified_results: dict[str, StockResearchResult] = {}
        previous, previous_time = _ZERO, None
        for index, record in enumerate(records, start=1):
            _check(record.sequence == index and record.previous_sha256 == previous)
            at = record.claimed_at if isinstance(record, StockResearchClaim) else record.recorded_at
            _check(previous_time is None or at >= previous_time)
            if isinstance(record, StockResearchClaim):
                _check(record.claim_id not in claims)
                if claims:
                    last = next(reversed(claims.values()))
                    _check(
                        record.claimed_at >= last.claimed_at + timedelta(minutes=last.scan_minutes)
                    )
                if record.source_result_sha256 is not None:
                    source = verified_results.get(record.source_result_sha256)
                    _check(
                        isinstance(source, StockResearchResult)
                        and source.status == "succeeded"
                        and source.phase == "discovery"
                        and source.config_hash == record.config_hash
                        and source.code_hash == record.code_hash
                    )
                claims[record.claim_id] = record
            else:
                _check(record.claim_id in claims and record.claim_id not in results)
                claim = claims[record.claim_id]
                _check(
                    (record.config_hash, record.code_hash, record.phase, record.plan_sha256)
                    == (claim.config_hash, claim.code_hash, claim.phase, claim.plan_sha256)
                )
                _check(
                    record.recorded_at >= claim.claimed_at
                    and record.attempted_calls <= claim.planned_calls
                )
                _check(
                    record.capture_plan_sha256 is None
                    or record.capture_plan_sha256 == claim.plan_sha256
                )
                if record.status == "succeeded":
                    _check(record.attempted_calls == record.successful_calls == claim.planned_calls)
                results.add(record.claim_id)
                _check(record.record_sha256 not in verified_results)
                verified_results[record.record_sha256] = record
            previous, previous_time = record.record_sha256, at
        return records, self._now(previous_time)

    def _state(self, records: list[_Record], now: datetime) -> StockResearchJobState:
        claims = tuple(item for item in records if isinstance(item, StockResearchClaim))
        results = tuple(item for item in records if isinstance(item, StockResearchResult))
        eligible = [
            item
            for item in results
            if item.status == "succeeded"
            and item.config_hash == self._config_hash
            and item.code_hash == self._code_hash
        ]
        source_sequence = {item.claim_id: item.sequence for item in claims}
        eligible.sort(key=lambda item: source_sequence[item.claim_id])
        return StockResearchJobState(
            claims,
            results,
            records[-1].record_sha256 if records else _ZERO,
            None
            if not records
            else (
                records[-1].claimed_at
                if isinstance(records[-1], StockResearchClaim)
                else records[-1].recorded_at
            ),
            sum(
                item.planned_calls for item in claims if now.date().isoformat() in item.budget_days
            ),
            next((item for item in reversed(eligible) if item.phase == "discovery"), None),
            next((item for item in reversed(eligible) if item.phase == "enrichment"), None),
            now,
        )

    async def snapshot(self) -> StockResearchJobState:
        self._factory_check()
        try:
            async with self._factory() as session:
                await session.execute(text("BEGIN IMMEDIATE"))
                records, now = await self._read(session)
                state = self._state(records, now)
                await session.rollback()
                return state
        except StockResearchJobError:
            raise
        except Exception:
            raise StockResearchJobError("stock_job_history_unavailable") from None

    def _configuration(self, row: ConfigurationVersionRow, now: datetime) -> LoadedConfig:
        _check(
            _sha(row.config_hash)
            and _sha(row.code_hash)
            and row.id == str(content_hash((_SCOPE, "configuration", row.config_hash)))
            and row.source == _SCOPE
            and row.corrects_id is None
            and require_utc(row.created_at) <= now
        )
        canonical = row.canonical_nonsecret_config_json
        _check(type(canonical) is str and 0 < len(canonical) <= 1048576)
        loaded = restore_loaded_config(canonical.encode(), ConfigHash(row.config_hash))
        _check(type(loaded.config) is StockWorkerAppConfig)
        return loaded

    async def _retain_configuration(self, session: AsyncSession, now: datetime) -> None:
        row = await session.scalar(
            select(ConfigurationVersionRow).where(
                ConfigurationVersionRow.config_hash == self._config_hash
            )
        )
        if row is not None:
            _check(self._configuration(row, now) == self._loaded)
            return
        hashes = list(
            (
                await session.scalars(
                    select(ConfigurationVersionRow.config_hash).limit(_MAX_CONFIGURATIONS + 1)
                )
            ).all()
        )
        _check(len(hashes) < _MAX_CONFIGURATIONS, "stock_job_configuration_capacity")
        session.add(
            ConfigurationVersionRow(
                id=str(content_hash((_SCOPE, "configuration", self._config_hash))),
                config_hash=self._config_hash,
                code_hash=self._code_hash,
                created_at=now,
                source=_SCOPE,
                canonical_nonsecret_config_json=self._loaded.canonical_json.decode(),
                corrects_id=None,
            )
        )

    async def configuration_history(self, *, expected_state_hash: str) -> dict[str, LoadedConfig]:
        """Read exact original graphs for a verified chain, without policy substitution.

        The current canonical graph also supports same-configuration legacy ledgers.
        Unknown older graphs cannot be reconstructed or backfilled by this reader.
        """
        self._factory_check()
        try:
            _check(_sha(expected_state_hash), "stock_job_stale_state")
            async with self._factory() as session:
                await session.execute(text("BEGIN IMMEDIATE"))
                records, now = await self._read(session)
                _check(
                    self._state(records, now).state_hash == expected_state_hash,
                    "stock_job_stale_state",
                )
                required = {self._config_hash} | {
                    row.config_hash for row in records if isinstance(row, StockResearchClaim)
                }
                _check(len(required) <= _MAX_CONFIGURATIONS, "stock_job_configuration_capacity")
                rows = list(
                    (
                        await session.scalars(
                            select(ConfigurationVersionRow)
                            .where(ConfigurationVersionRow.config_hash.in_(required))
                            .limit(_MAX_CONFIGURATIONS + 1)
                        )
                    ).all()
                )
                _check(len(rows) <= _MAX_CONFIGURATIONS)
                history = {self._config_hash: self._loaded}
                for row in rows:
                    graph = self._configuration(row, now)
                    history[row.config_hash] = graph
                _check(set(history) == required)
                await session.rollback()
                return history
        except StockResearchJobError:
            raise
        except Exception:
            raise StockResearchJobError("stock_job_configuration_unavailable") from None

    def _require_source(
        self, state: StockResearchJobState, source_sha256: str | None, now: datetime
    ) -> None:
        head = state.discovery_head
        _check(
            head is not None and source_sha256 == head.record_sha256,
            "stock_job_source_required",
        )
        if head is None:
            raise StockResearchJobError("stock_job_source_required")
        source_claim = next(item for item in state.claims if item.claim_id == head.claim_id)
        _check(
            now - source_claim.claimed_at
            <= timedelta(minutes=self._config.stock_research.maximum_source_age_minutes),
            "stock_job_source_stale",
        )

    async def reserve(
        self,
        *,
        phase: Phase,
        plan_sha256: str,
        planned_calls: int,
        expected_state_hash: str,
        source_result_sha256: str | None = None,
    ) -> StockResearchClaim:
        self._factory_check()
        try:
            _check(
                phase in {"discovery", "enrichment"}
                and _sha(plan_sha256)
                and _sha(expected_state_hash),
                "stock_job_plan_invalid",
            )
            _check(
                _integer(planned_calls, 1, self._config.stock_research.max_calls_per_cycle),
                "stock_job_cycle_budget",
            )
            async with self._factory() as session:
                await session.execute(text("BEGIN IMMEDIATE"))
                records, now = await self._read(session)
                state = self._state(records, now)
                _check(state.state_hash == expected_state_hash, "stock_job_stale_state")
                _check(
                    len(records) + state.pending_count + 2 <= _MAX_EVENTS,
                    "stock_job_history_capacity",
                )
                minutes = self._config.stock_research.scan_minutes
                slot = _slot(now, minutes)
                _check(
                    all(item.claim_id != _claim_id(slot) for item in state.claims),
                    "stock_job_slot_claimed",
                )
                if state.claims:
                    last = state.claims[-1]
                    _check(
                        now >= last.claimed_at + timedelta(minutes=max(minutes, last.scan_minutes)),
                        "stock_job_cadence_not_due",
                    )
                if phase == "enrichment":
                    self._require_source(state, source_result_sha256, now)
                else:
                    _check(source_result_sha256 is None, "stock_job_source_invalid")
                deadline = now + timedelta(seconds=self._config.stock_worker.max_run_seconds)
                days = _days(now, deadline)
                for day in days:
                    spent = sum(
                        item.planned_calls for item in state.claims if day in item.budget_days
                    )
                    _check(
                        spent + planned_calls <= self._config.stock_research.max_daily_calls,
                        "stock_job_daily_budget",
                    )
                claim = StockResearchClaim(
                    _claim_id(slot),
                    len(records) + 1,
                    state.state_hash,
                    self._config_hash,
                    self._code_hash,
                    phase,
                    slot,
                    now,
                    deadline,
                    minutes,
                    plan_sha256,
                    planned_calls,
                    days,
                    source_result_sha256,
                    _ZERO,
                )
                claim = replace(claim, record_sha256=_hash_record(claim))
                await self._retain_configuration(session, now)
                _stage_audit_event(session, _event(claim))
                await session.commit()
                return claim
        except StockResearchJobError:
            raise
        except Exception:
            raise StockResearchJobError("stock_job_admission_failed") from None

    async def assert_active(
        self, claim: StockResearchClaim, *, plan_sha256: str, planned_calls: int
    ) -> None:
        """Recheck the exact pending reservation immediately before a data-tool send.

        The runtime also freezes the full plan, makes no retries and enforces its
        monotonic run timeout. This read creates no per-call retry or execution grant.
        """
        self._factory_check()
        try:
            _check(type(claim) is StockResearchClaim)
            claim.__post_init__()
            _check(_hash_record(claim) == claim.record_sha256)
            _check(_sha(plan_sha256) and _integer(planned_calls, 1, 32))
            _check(plan_sha256 == claim.plan_sha256 and planned_calls == claim.planned_calls)
            async with self._factory() as session:
                await session.execute(text("BEGIN IMMEDIATE"))
                records, now = await self._read(session)
                state = self._state(records, now)
                _check(claim in state.claims)
                _check(
                    claim.config_hash == self._config_hash and claim.code_hash == self._code_hash
                )
                _check(all(item.claim_id != claim.claim_id for item in state.results))
                _check(now < claim.deadline_at, "stock_job_deadline_denied")
                _check(now.date().isoformat() in claim.budget_days, "stock_job_budget_day_denied")
                if claim.phase == "enrichment":
                    self._require_source(state, claim.source_result_sha256, now)
                await session.rollback()
        except StockResearchJobError:
            raise
        except Exception:
            raise StockResearchJobError("stock_job_send_denied") from None

    async def finish(
        self,
        claim: StockResearchClaim,
        *,
        status: Status,
        reason: str,
        capture_plan_sha256: str | None,
        attempted_calls: int,
        successful_calls: int,
        manifest_sha256: str | None,
        report_sha256: str | None,
        require_active_before_success: bool = False,
    ) -> StockResearchResult:
        self._factory_check()
        try:
            _check(type(claim) is StockResearchClaim and _hash_record(claim) == claim.record_sha256)
            _check(type(require_active_before_success) is bool)
            async with self._factory() as session:
                await session.execute(text("BEGIN IMMEDIATE"))
                records, now = await self._read(session)
                state = self._state(records, now)
                _check(
                    claim in state.claims
                    and claim.config_hash == self._config_hash
                    and claim.code_hash == self._code_hash
                )
                original = next(
                    (item for item in state.results if item.claim_id == claim.claim_id), None
                )
                _check(_integer(attempted_calls, 0, claim.planned_calls))
                _check(_integer(successful_calls, 0, attempted_calls))
                if capture_plan_sha256 is not None:
                    _check(capture_plan_sha256 == claim.plan_sha256)
                if status == "succeeded":
                    _check(attempted_calls == successful_calls == claim.planned_calls)
                if original is not None:
                    compare = replace(
                        original,
                        capture_plan_sha256=capture_plan_sha256,
                        attempted_calls=attempted_calls,
                        successful_calls=successful_calls,
                        status=status,
                        reason=reason,
                        manifest_sha256=manifest_sha256,
                        report_sha256=report_sha256,
                    )
                    _check(compare == original, "stock_job_result_conflict")
                    await session.rollback()
                    return original
                if status == "succeeded" and require_active_before_success:
                    _check(now < claim.deadline_at, "stock_job_deadline_denied")
                    if claim.phase == "enrichment":
                        self._require_source(state, claim.source_result_sha256, now)
                result = StockResearchResult(
                    claim.claim_id,
                    len(records) + 1,
                    state.state_hash,
                    self._config_hash,
                    self._code_hash,
                    claim.phase,
                    now,
                    claim.plan_sha256,
                    capture_plan_sha256,
                    attempted_calls,
                    successful_calls,
                    status,
                    reason,
                    manifest_sha256,
                    report_sha256,
                    _ZERO,
                )
                result = replace(result, record_sha256=_hash_record(result))
                _stage_audit_event(session, _event(result))
                await session.commit()
                return result
        except StockResearchJobError:
            raise
        except Exception:
            raise StockResearchJobError("stock_job_result_failed") from None
