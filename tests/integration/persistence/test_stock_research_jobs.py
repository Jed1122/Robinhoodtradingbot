"""Fictional research claims reserve quotas without touching a broker or account."""

import asyncio
import hashlib
import importlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.config import load_config
from trading_bot.domain import CodeHash
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.persistence.audit import _stage_audit_event
from trading_bot.persistence.models import AuditEventRow

ROOT = Path(__file__).parents[3]
NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass
class Clock:
    current: datetime = NOW

    def now(self):
        return self.current


def config(stock_policy=None):
    return load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/hybrid/paper.yaml",
        ROOT / "configs/hybrid/safety-envelope.yaml",
        {},
        hybrid_policy_path=ROOT / "configs/hybrid/policy.yaml",
        stock_research_policy_path=stock_policy or ROOT / "configs/hybrid/stock-research.yaml",
        stock_worker_policy_path=ROOT / "configs/hybrid/stock-worker.yaml",
    )


@pytest.fixture
def migrated(alembic_config):
    command.upgrade(alembic_config, "head")


def store(engine, *, clock=None, loaded=None, code="fixture-reviewed-build"):
    module = importlib.import_module("trading_bot.persistence.stock_research_jobs")
    return module.SqlStockResearchJobs(
        async_session_factory(engine),
        loaded=loaded or config(),
        code_hash=CodeHash(digest(code)),
        clock=(clock or Clock()).now,
    )


async def reserve(owner, *, calls=17, phase="discovery", source=None, basis=None):
    state = await owner.snapshot()
    return await owner.reserve(
        phase=phase,
        plan_sha256=digest("fictional-plan"),
        planned_calls=calls,
        expected_state_hash=basis or state.state_hash,
        source_result_sha256=source,
    )


async def finish(owner, claim, *, status="succeeded", attempted=None, successful=None):
    return await owner.finish(
        claim,
        status=status,
        reason="complete" if status == "succeeded" else "capture_partial",
        capture_plan_sha256=claim.plan_sha256,
        attempted_calls=claim.planned_calls if attempted is None else attempted,
        successful_calls=claim.planned_calls if successful is None else successful,
        manifest_sha256=digest("fictional-manifest"),
        report_sha256=digest("fictional-report") if status == "succeeded" else None,
    )


@pytest.mark.asyncio
async def test_claim_result_restart_preserves_budget_and_verified_head(sqlite_engine, migrated):
    owner = store(sqlite_engine)
    claim = await reserve(owner)
    pending = await store(sqlite_engine).snapshot()
    assert pending.reserved_today == 17 and pending.pending_count == 1
    assert pending.discovery_head is None
    result = await finish(owner, claim)
    restored = await store(sqlite_engine).snapshot()
    assert restored.reserved_today == 17 and restored.pending_count == 0
    assert restored.discovery_head == result
    assert result.claim_id == claim.claim_id
    assert restored.state_hash == result.record_sha256
    assert not result.live_enabled


@pytest.mark.asyncio
async def test_same_slot_phase_plan_and_code_changes_cannot_replay(sqlite_engine, migrated):
    module = importlib.import_module("trading_bot.persistence.stock_research_jobs")
    claim = await reserve(store(sqlite_engine))
    for phase in ("discovery", "enrichment"):
        with pytest.raises(module.StockResearchJobError):
            await reserve(store(sqlite_engine, code="new-build"), phase=phase)
    assert (await store(sqlite_engine).snapshot()).claims == (claim,)


@pytest.mark.asyncio
async def test_competition_and_stale_state_allow_one_claim(sqlite_engine, migrated):
    module = importlib.import_module("trading_bot.persistence.stock_research_jobs")
    a, b = store(sqlite_engine), store(sqlite_engine)
    basis = (await a.snapshot()).state_hash
    results = await asyncio.gather(
        reserve(a, basis=basis), reserve(b, basis=basis), return_exceptions=True
    )
    assert sum(not isinstance(item, BaseException) for item in results) == 1
    assert sum(isinstance(item, module.StockResearchJobError) for item in results) == 1
    assert (await a.snapshot()).reserved_today == 17


@pytest.mark.asyncio
async def test_failure_keeps_old_cache_and_full_charge(sqlite_engine, migrated):
    clock = Clock()
    owner = store(sqlite_engine, clock=clock)
    first = await reserve(owner)
    good = await finish(owner, first)
    clock.current += timedelta(hours=1)
    failed = await reserve(owner)
    await finish(owner, failed, status="blocked", attempted=2, successful=1)
    state = await owner.snapshot()
    assert state.reserved_today == 34 and state.discovery_head == good


@pytest.mark.asyncio
async def test_budget_survives_config_and_code_change_and_midnight(
    sqlite_engine, migrated, tmp_path
):
    module = importlib.import_module("trading_bot.persistence.stock_research_jobs")
    clock = Clock(NOW.replace(hour=23, minute=59))
    owner = store(sqlite_engine, clock=clock)
    claim = await reserve(owner)
    assert len(claim.budget_days) == 2
    policy = tmp_path / "lower-budget.yaml"
    policy.write_text("max_daily_calls: 32\n")
    changed = store(sqlite_engine, clock=clock, loaded=config(policy), code="changed-build")
    clock.current += timedelta(hours=2)
    assert (await changed.snapshot()).reserved_today == 17
    with pytest.raises(module.StockResearchJobError, match="daily_budget"):
        await reserve(changed)


@pytest.mark.asyncio
async def test_backward_clock_and_cadence_change_do_not_create_admission(sqlite_engine, migrated):
    module = importlib.import_module("trading_bot.persistence.stock_research_jobs")
    clock = Clock()
    owner = store(sqlite_engine, clock=clock)
    await reserve(owner)
    clock.current -= timedelta(seconds=1)
    with pytest.raises(module.StockResearchJobError, match="clock"):
        await owner.snapshot()
    clock.current = NOW + timedelta(minutes=20)
    with pytest.raises(module.StockResearchJobError):
        await reserve(store(sqlite_engine, clock=clock))


@pytest.mark.asyncio
@pytest.mark.parametrize("calls", [True, 0, 33])
async def test_invalid_cycle_counts_never_append(sqlite_engine, migrated, calls):
    module = importlib.import_module("trading_bot.persistence.stock_research_jobs")
    owner = store(sqlite_engine)
    with pytest.raises(module.StockResearchJobError):
        await reserve(owner, calls=calls)
    assert (await owner.snapshot()).claims == ()


@pytest.mark.asyncio
async def test_enrichment_requires_current_fresh_discovery_head(sqlite_engine, migrated):
    module = importlib.import_module("trading_bot.persistence.stock_research_jobs")
    clock = Clock()
    owner = store(sqlite_engine, clock=clock)
    with pytest.raises(module.StockResearchJobError):
        await reserve(owner, phase="enrichment", calls=25)
    discovery = await reserve(owner)
    result = await finish(owner, discovery)
    clock.current += timedelta(hours=1)
    enriched = await reserve(owner, phase="enrichment", calls=25, source=result.record_sha256)
    assert enriched.source_result_sha256 == result.record_sha256
    assert (await owner.snapshot()).reserved_today == 42


@pytest.mark.asyncio
@pytest.mark.parametrize("ack_lost", [False, True])
async def test_commit_failure_never_returns_a_usable_claim(
    sqlite_engine, migrated, monkeypatch, ack_lost
):
    module = importlib.import_module("trading_bot.persistence.stock_research_jobs")
    owner = store(sqlite_engine)
    original = AsyncSession.commit

    async def fail(self):
        if ack_lost:
            await original(self)
        raise RuntimeError("fictional-provider-secret")

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", fail)
        with pytest.raises(module.StockResearchJobError) as error:
            await reserve(owner)
        assert "fictional" not in str(error.value)
    fresh = store(sqlite_engine)
    state = await fresh.snapshot()
    assert state.reserved_today == (17 if ack_lost else 0)
    if ack_lost:
        with pytest.raises(module.StockResearchJobError):
            await reserve(fresh)


@pytest.mark.asyncio
async def test_trigger_tamper_and_factory_rebind_fail_closed(sqlite_engine, migrated, tmp_path):
    module = importlib.import_module("trading_bot.persistence.stock_research_jobs")
    owner = store(sqlite_engine)
    factory = owner._factory
    other = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'other.db'}")
    factory.configure(bind=other)
    try:
        with pytest.raises(module.StockResearchJobError):
            await owner.snapshot()
    finally:
        await other.dispose()
    async with async_session_factory(sqlite_engine).begin() as session:
        await session.execute(text('DROP TRIGGER "trg_audit_events_append_only_update"'))
    with pytest.raises(module.StockResearchJobError, match="schema"):
        await store(sqlite_engine).snapshot()


@pytest.mark.asyncio
async def test_raw_hashes_do_not_bypass_existing_secret_sanitizer(sqlite_engine, migrated):
    owner = store(sqlite_engine)
    await finish(owner, await reserve(owner))
    async with async_session_factory(sqlite_engine)() as session:
        rows = list((await session.scalars(select(AuditEventRow))).all())
    assert len(rows) == 2
    assert all(digest("fictional-plan") not in row.sanitized_details_json for row in rows)


@pytest.mark.asyncio
async def test_daily_512_boundary_retains_all_abandoned_reservations(
    sqlite_engine, migrated, tmp_path
):
    module = importlib.import_module("trading_bot.persistence.stock_research_jobs")
    policy = tmp_path / "frequent.yaml"
    policy.write_text("scan_minutes: 15\n")
    clock = Clock(NOW.replace(hour=0))
    owner = store(sqlite_engine, clock=clock, loaded=config(policy))
    for _ in range(30):
        await reserve(owner)
        clock.current += timedelta(minutes=15)
    assert (await owner.snapshot()).reserved_today == 510
    with pytest.raises(module.StockResearchJobError, match="daily_budget"):
        await reserve(owner)
    assert (await owner.snapshot()).pending_count == 30


@pytest.mark.asyncio
async def test_result_is_idempotent_and_conflicting_metadata_cannot_replace_cache(
    sqlite_engine, migrated
):
    module = importlib.import_module("trading_bot.persistence.stock_research_jobs")
    owner = store(sqlite_engine)
    claim = await reserve(owner)
    original = await finish(owner, claim)
    assert await finish(owner, claim) == original
    with pytest.raises(module.StockResearchJobError):
        await finish(owner, claim, attempted=16, successful=16)
    state = await owner.snapshot()
    assert state.results == (original,)


@pytest.mark.asyncio
async def test_named_noop_guard_is_not_append_only_evidence(sqlite_engine, migrated):
    module = importlib.import_module("trading_bot.persistence.stock_research_jobs")
    async with async_session_factory(sqlite_engine).begin() as session:
        await session.execute(text('DROP TRIGGER "trg_audit_events_append_only_update"'))
        await session.execute(
            text(
                'CREATE TRIGGER "trg_audit_events_append_only_update" '
                'BEFORE UPDATE ON "audit_events" BEGIN SELECT 1; END'
            )
        )
    with pytest.raises(module.StockResearchJobError, match="schema"):
        await store(sqlite_engine).snapshot()


@pytest.mark.asyncio
@pytest.mark.parametrize("ack_lost", [False, True])
async def test_cancelled_commit_retains_unknown_outcome_without_replay(
    sqlite_engine, migrated, monkeypatch, ack_lost
):
    module = importlib.import_module("trading_bot.persistence.stock_research_jobs")
    owner = store(sqlite_engine)
    original = AsyncSession.commit

    async def cancel(self):
        if ack_lost:
            await original(self)
        raise asyncio.CancelledError

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", cancel)
        with pytest.raises(asyncio.CancelledError):
            await reserve(owner)
    fresh = store(sqlite_engine)
    assert (await fresh.snapshot()).reserved_today == (17 if ack_lost else 0)
    if ack_lost:
        with pytest.raises(module.StockResearchJobError):
            await reserve(fresh)


@pytest.mark.asyncio
async def test_send_guard_requires_pending_exact_plan_and_unexpired_budget_window(
    sqlite_engine, migrated
):
    module = importlib.import_module("trading_bot.persistence.stock_research_jobs")
    clock = Clock()
    owner = store(sqlite_engine, clock=clock)
    claim = await reserve(owner)
    await owner.assert_active(
        claim, plan_sha256=claim.plan_sha256, planned_calls=claim.planned_calls
    )
    with pytest.raises(module.StockResearchJobError):
        await owner.assert_active(claim, plan_sha256=digest("different"), planned_calls=17)
    clock.current = claim.deadline_at
    with pytest.raises(module.StockResearchJobError, match="deadline"):
        await owner.assert_active(claim, plan_sha256=claim.plan_sha256, planned_calls=17)


@pytest.mark.asyncio
async def test_terminal_claim_cannot_authorize_an_additional_call(sqlite_engine, migrated):
    module = importlib.import_module("trading_bot.persistence.stock_research_jobs")
    owner = store(sqlite_engine)
    claim = await reserve(owner)
    await finish(owner, claim)
    with pytest.raises(module.StockResearchJobError):
        await owner.assert_active(claim, plan_sha256=claim.plan_sha256, planned_calls=17)


@pytest.mark.asyncio
async def test_admission_reserves_terminal_capacity_and_full_result_retry_is_idempotent(
    sqlite_engine, migrated, monkeypatch
):
    module = importlib.import_module("trading_bot.persistence.stock_research_jobs")
    monkeypatch.setattr(module, "_MAX_EVENTS", 2)
    clock = Clock()
    owner = store(sqlite_engine, clock=clock)
    claim = await reserve(owner)
    clock.current += timedelta(hours=1)
    with pytest.raises(module.StockResearchJobError, match="capacity"):
        await reserve(owner)
    result = await finish(owner, claim)
    assert await finish(owner, claim) == result


@pytest.mark.asyncio
async def test_pending_claims_keep_space_for_all_future_terminal_records(
    sqlite_engine, migrated, monkeypatch
):
    module = importlib.import_module("trading_bot.persistence.stock_research_jobs")
    monkeypatch.setattr(module, "_MAX_EVENTS", 6)
    clock = Clock()
    owner = store(sqlite_engine, clock=clock)
    claims = []
    for _ in range(3):
        claims.append(await reserve(owner))
        clock.current += timedelta(hours=1)
    with pytest.raises(module.StockResearchJobError, match="capacity"):
        await reserve(owner)
    for claim in claims:
        await finish(owner, claim, status="blocked", attempted=0, successful=0)
    state = await owner.snapshot()
    assert state.pending_count == 0 and len(state.results) == 3


@pytest.mark.asyncio
async def test_late_completion_cannot_replace_newer_source_cache(sqlite_engine, migrated):
    clock = Clock()
    owner = store(sqlite_engine, clock=clock)
    older = await reserve(owner)
    clock.current += timedelta(hours=1)
    newer = await reserve(owner)
    current = await finish(owner, newer)
    clock.current += timedelta(hours=1)
    await finish(owner, older)
    assert (await owner.snapshot()).discovery_head == current


@pytest.mark.asyncio
async def test_replay_rejects_canonically_hashed_failed_result_with_wrong_capture_plan(
    sqlite_engine, migrated
):
    module = importlib.import_module("trading_bot.persistence.stock_research_jobs")
    owner = store(sqlite_engine)
    claim = await reserve(owner)
    forged = module.StockResearchResult(
        claim.claim_id,
        2,
        claim.record_sha256,
        claim.config_hash,
        claim.code_hash,
        claim.phase,
        NOW,
        claim.plan_sha256,
        digest("wrong-capture-plan"),
        1,
        0,
        "blocked",
        "capture_partial",
        digest("fictional-manifest"),
        None,
        "0" * 64,
    )
    forged = replace(forged, record_sha256=module._hash_record(forged))
    async with async_session_factory(sqlite_engine).begin() as session:
        _stage_audit_event(session, module._event(forged))
    with pytest.raises(module.StockResearchJobError):
        await store(sqlite_engine).snapshot()


@pytest.mark.asyncio
async def test_enrichment_send_guard_rechecks_source_age_within_run(sqlite_engine, migrated):
    module = importlib.import_module("trading_bot.persistence.stock_research_jobs")
    clock = Clock()
    owner = store(sqlite_engine, clock=clock)
    source = await finish(owner, await reserve(owner))
    clock.current += timedelta(minutes=119)
    claim = await reserve(owner, phase="enrichment", calls=25, source=source.record_sha256)
    clock.current += timedelta(minutes=2)
    assert clock.current < claim.deadline_at
    with pytest.raises(module.StockResearchJobError, match="source_stale"):
        await owner.assert_active(claim, plan_sha256=claim.plan_sha256, planned_calls=25)


@pytest.mark.asyncio
async def test_hash_codec_does_not_hide_a_registered_secret(sqlite_engine, migrated, monkeypatch):
    module = importlib.import_module("trading_bot.persistence.stock_research_jobs")
    owner = store(sqlite_engine)
    monkeypatch.setattr(
        module, "contains_registered_secret", lambda value: value == digest("fictional-plan")
    )
    with pytest.raises(module.StockResearchJobError):
        await reserve(owner)
    assert (await owner.snapshot()).claims == ()
