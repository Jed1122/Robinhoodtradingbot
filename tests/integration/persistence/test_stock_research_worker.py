"""One-shot worker against a migrated fictional database and fake official session."""

import asyncio
import importlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.brokers.robinhood_mcp_transport import McpToolResult
from trading_bot.brokers.stock_research_mcp import PROFILE_SHA256
from trading_bot.config import load_config
from trading_bot.domain import CodeHash
from trading_bot.persistence import async_session_factory
from trading_bot.persistence.stock_research_jobs import SqlStockResearchJobs
from trading_bot.research.stock_screen import TURNOVER_COLUMN
from trading_bot.runtime.stock_research_controls import StockResearchControls

ROOT = Path(__file__).parents[3]
NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)
CODE = CodeHash("b" * 64)


@dataclass
class Clock:
    current: datetime = NOW

    def now(self):
        return self.current


class Scenario:
    def __init__(self):
        self.events = []
        self.calls = []
        self.symbol = "ALFA"
        self.fail = None
        self.schema = PROFILE_SHA256
        self.truncated = False
        self.entered = asyncio.Event()
        self.waiting = asyncio.Event()
        self.on_sleep = None

    def connection(self, **kwargs):
        self.events.append("constructed")
        if self.fail == "auth":
            raise RuntimeError("private-auth-detail")
        scenario = self

        class Connection:
            stock_research_session = scenario

            async def __aenter__(self):
                scenario.events.append("opened")
                return self

            async def __aexit__(self, *args):
                scenario.events.append("closed")
                if scenario.fail == "close":
                    raise RuntimeError("private-close-detail")

        return Connection()

    async def validate_tools(self):
        self.events.append("schemas")
        return self.schema

    async def call_tool(self, tool, arguments):
        self.calls.append((tool, arguments))
        if self.fail == "hang":
            self.entered.set()
            await self.waiting.wait()
        if self.fail == tool:
            raise RuntimeError("private-provider-detail")
        symbol = self.symbol
        if tool == "get_scanner_filter_specs":
            data = {"filter_specs": []}
        elif tool == "preview_scan":
            data = {
                "result": {
                    "total_items": 400 if self.truncated else 1,
                    "filters_applied": arguments["filters"],
                    "results": [
                        {
                            "ticker": symbol,
                            "instrument_id": "fictional-" + symbol,
                            "instrument_type": "EQUITY",
                            "columns": {
                                "Asset type": "STOCK",
                                "Last": "100",
                                "Market cap": "5000000000",
                                TURNOVER_COLUMN.format(sessions=30): "30000000",
                                "Sector": "Technology",
                                "Return on equity": "0.2",
                                "Net profit margin": "0.1",
                                "Annual EPS growth": "0.1",
                                "Quarterly revenue growth": "0.1",
                                "P/E": "20",
                                "FCF/share": "2",
                            },
                        }
                    ],
                }
            }
        elif tool == "get_equity_fundamentals":
            data = {"results": [{"symbol": symbol, "market_cap": "5000000000"}]}
        elif tool == "get_financials":
            data = {"results": [None]}
        elif tool == "get_equity_quotes":
            data = {"results": []}
        elif tool == "get_equity_historicals":
            data = {
                "results": [
                    {
                        "symbol": symbol,
                        "interval": "day",
                        "bounds": "regular",
                        "bars": [
                            {
                                "begins_at": "2026-10-19T04:00:00Z",
                                "open_price": "20",
                                "high_price": "22",
                                "low_price": "19",
                                "close_price": "21",
                                "volume": 1000,
                                "session": "reg",
                                "interpolated": False,
                            }
                        ],
                    }
                ]
            }
        elif tool == "get_earnings_results":
            data = {"results": []}
        elif tool == "get_sec_filing_index":
            data = {"symbol": symbol, "filings": [], "next": ""}
        else:
            raise AssertionError("unexpected research tool")
        return McpToolResult((), False, {"data": data})


@pytest.fixture
def worker(tmp_path, sqlite_engine, alembic_config, monkeypatch):
    command.upgrade(alembic_config, "head")
    module = importlib.import_module("trading_bot.runtime.stock_research_worker")
    policy = tmp_path / "stock.yaml"
    policy.write_text("market_cap_boundaries_usd: [2000000000]\nshortlist_count: 1\n")
    loaded = load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/hybrid/paper.yaml",
        ROOT / "configs/hybrid/safety-envelope.yaml",
        {},
        hybrid_policy_path=ROOT / "configs/hybrid/policy.yaml",
        stock_research_policy_path=policy,
        stock_worker_policy_path=ROOT / "configs/hybrid/stock-worker.yaml",
    )
    root = tmp_path.resolve() / "archive"
    root.mkdir(mode=0o700)
    clock, scenario = Clock(), Scenario()
    control_root = tmp_path.resolve() / "controls"
    control_root.mkdir(mode=0o700)
    controls = StockResearchControls(control_root, clock=clock.now)
    paused = controls.initialize()
    controls.change(
        "resume",
        expected_sha256=paused.sha256,
        config_hash=str(loaded.config_hash),
        code_hash=str(CODE),
    )
    scenario.controls = controls
    monkeypatch.setattr(module, "RobinhoodMcpSdkConnection", scenario.connection)
    factory = async_session_factory(sqlite_engine)

    async def pause(seconds):
        if scenario.on_sleep is not None:
            scenario.on_sleep()

    async def cycle(**kwargs):
        authority = kwargs.pop("controls", controls)
        return await module.run_stock_research_cycle(
            loaded=loaded,
            code_hash=CODE,
            factory=factory,
            oauth_store=tmp_path.resolve() / "unused-fixture-oauth",
            output_dir=root,
            clock=clock.now,
            sleep=pause,
            controls=authority,
            **kwargs,
        )

    owner = SqlStockResearchJobs(factory, loaded=loaded, code_hash=CODE, clock=clock.now)
    return module, root, clock, scenario, cycle, owner, loaded


@pytest.mark.asyncio
async def test_acquisition_requires_explicit_active_collector_authority(worker):
    _, _, _, scenario, cycle, owner, _ = worker
    result = await cycle(controls=None)
    assert result == {"status": "blocked", "reason": "control_denied", "live_enabled": False}
    assert scenario.events == [] and scenario.calls == []
    assert (await owner.snapshot()).claims == ()


def suspend(scenario, action="pause"):
    current = scenario.controls.read()
    return scenario.controls.change(action, expected_sha256=current.sha256)


@pytest.mark.asyncio
async def test_paused_and_killed_collector_never_reserves_or_constructs_sdk(worker):
    _, _, _, scenario, cycle, owner, _ = worker
    suspend(scenario)
    assert (await cycle())["reason"] == "control_denied"
    suspend(scenario, "kill")
    assert (await cycle())["reason"] == "control_denied"
    assert scenario.events == [] and scenario.calls == []
    assert (await owner.snapshot()).claims == ()


@pytest.mark.asyncio
async def test_pause_before_reservation_preserves_zero_charge(worker, monkeypatch):
    module, _, _, scenario, cycle, owner, _ = worker
    original = module._cached

    def pause_first(**kwargs):
        suspend(scenario)
        return original(**kwargs)

    monkeypatch.setattr(module, "_cached", pause_first)
    assert (await cycle())["reason"] == "control_denied"
    assert scenario.events == [] and (await owner.snapshot()).claims == ()


@pytest.mark.asyncio
async def test_pause_after_reservation_prevents_credential_construction(worker, monkeypatch):
    module, _, _, scenario, cycle, owner, _ = worker
    original = module.SqlStockResearchJobs.assert_active

    async def pause_first(self, *args, **kwargs):
        await original(self, *args, **kwargs)
        suspend(scenario)

    monkeypatch.setattr(module.SqlStockResearchJobs, "assert_active", pause_first)
    assert (await cycle())["reason"] == "control_denied"
    assert scenario.events == [] and scenario.calls == []
    state = await owner.snapshot()
    assert state.reserved_today == 2 and state.discovery_head is None
    assert state.results[-1].reason == "control_denied"


@pytest.mark.asyncio
async def test_pause_after_before_call_hook_cannot_race_actual_provider_dispatch(
    worker, monkeypatch
):
    module, _, _, scenario, cycle, owner, _ = worker
    original = module.capture_stock_observations

    async def race(**kwargs):
        before = kwargs["before_call"]

        async def pause_after_hook(index, request):
            await before(index, request)
            suspend(scenario)

        kwargs["before_call"] = pause_after_hook
        return await original(**kwargs)

    monkeypatch.setattr(module, "capture_stock_observations", race)
    assert (await cycle())["reason"] == "control_denied"
    assert scenario.calls == [] and scenario.events[-1] == "closed"
    state = await owner.snapshot()
    assert state.reserved_today == 2 and state.discovery_head is None


@pytest.mark.asyncio
async def test_pause_and_resume_between_calls_fences_the_existing_cycle(worker):
    _, _, _, scenario, cycle, owner, loaded = worker

    def pause_resume():
        state = suspend(scenario)
        scenario.controls.change(
            "resume",
            expected_sha256=state.sha256,
            config_hash=str(loaded.config_hash),
            code_hash=str(CODE),
        )

    scenario.on_sleep = pause_resume
    result = await cycle()
    assert result["reason"] == "control_denied"
    assert len(scenario.calls) == 1 and scenario.events[-1] == "closed"
    assert (await owner.snapshot()).discovery_head is None
    assert scenario.controls.read().record.status == "running"


@pytest.mark.asyncio
async def test_inflight_operation_cannot_be_reported_paused_and_cancellation_releases_permit(
    worker,
):
    _, _, _, scenario, cycle, owner, _ = worker
    scenario.fail = "hang"
    running = asyncio.create_task(cycle())
    await asyncio.wait_for(scenario.entered.wait(), timeout=5)
    with pytest.raises(ValueError, match="stock_control_busy"):
        suspend(scenario)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert suspend(scenario).record.status == "paused"
    assert scenario.events[-1] == "closed"
    state = await owner.snapshot()
    assert state.reserved_today == 2 and state.pending_count == 1
    assert (await cycle())["reason"] == "control_denied"


@pytest.mark.asyncio
async def test_discovery_enrichment_and_fresh_cache_use_real_ledger(worker):
    _, root, clock, scenario, cycle, owner, _ = worker
    discovered = await cycle()
    assert discovered["status"] == "succeeded" and discovered["phase"] == "discovery"
    assert discovered["planned_calls"] == 2
    state = await owner.snapshot()
    assert state.discovery_head is not None and state.reserved_today == 2
    clock.current += timedelta(hours=1)
    enriched = await cycle()
    assert enriched["status"] == "succeeded" and enriched["phase"] == "enrichment"
    assert enriched["planned_calls"] == 7
    assert (await owner.snapshot()).enrichment_head is not None
    for _ in range(2):
        clock.current += timedelta(hours=1)
        assert (await cycle())["phase"] == "discovery"
    assert len(scenario.calls) == 13
    assert (await owner.snapshot()).reserved_today == 13
    assert list(root.glob("*.stock-screen.json")) and list(root.glob("*.stock-dossiers.json"))
    assert all(event in {"constructed", "opened", "schemas", "closed"} for event in scenario.events)
    assert discovered["live_enabled"] is enriched["live_enabled"] is False


@pytest.mark.asyncio
async def test_same_slot_restart_never_constructs_another_connection(worker):
    _, _, _, scenario, cycle, owner, _ = worker
    await cycle()
    count = len(scenario.events)
    result = await cycle()
    assert result["status"] == "blocked"
    assert len(scenario.events) == count
    assert len((await owner.snapshot()).claims) == 1


@pytest.mark.asyncio
async def test_storage_full_blocks_before_claim_or_connection(worker):
    _, root, _, scenario, cycle, owner, loaded = worker
    path = root / ("a" * 64 + ".stock-observation.json")
    descriptor = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
    os.ftruncate(descriptor, loaded.config.stock_worker.max_archive_bytes)
    os.close(descriptor)
    assert (await cycle())["status"] == "blocked"
    assert scenario.events == [] and (await owner.snapshot()).claims == ()
    assert path.exists()


@pytest.mark.asyncio
async def test_partial_capture_charges_full_plan_and_cannot_replace_cache(worker):
    _, _, _, scenario, cycle, owner, _ = worker
    scenario.fail = "preview_scan"
    result = await cycle()
    assert result["status"] == "blocked" and result["reason"] == "capture_partial"
    state = await owner.snapshot()
    assert state.reserved_today == 2 and state.discovery_head is None
    assert state.results[0].attempted_calls == 2 and state.results[0].successful_calls == 1
    assert len(scenario.calls) == 2 and scenario.events[-1] == "closed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,reason", [("auth", "auth_unavailable"), ("schema", "schema_mismatch")]
)
async def test_auth_or_schema_failure_never_falls_back_to_data_tools(worker, failure, reason):
    _, _, _, scenario, cycle, owner, _ = worker
    if failure == "schema":
        scenario.schema = "c" * 64
    else:
        scenario.fail = failure
    result = await cycle()
    assert result["status"] == "blocked" and result["reason"] == reason
    assert scenario.calls == [] and (await owner.snapshot()).reserved_today == 2
    assert "private-" not in str(result)


@pytest.mark.asyncio
async def test_close_failure_retains_capture_but_publishes_no_cache_head(worker):
    _, _, _, scenario, cycle, owner, _ = worker
    scenario.fail = "close"
    result = await cycle()
    assert result["status"] == "blocked"
    state = await owner.snapshot()
    assert state.discovery_head is None and state.reserved_today == 2
    assert "private-close-detail" not in str(result)


@pytest.mark.asyncio
async def test_tampered_discovery_head_denies_before_new_claim_or_connection(worker):
    _, root, clock, scenario, cycle, owner, _ = worker
    await cycle()
    head = (await owner.snapshot()).discovery_head
    path = root / (head.report_sha256 + ".stock-screen.json")
    path.write_bytes(path.read_bytes() + b" ")
    clock.current += timedelta(hours=1)
    events = len(scenario.events)
    result = await cycle()
    assert result["status"] == "blocked" and result["reason"] == "artifact_unavailable"
    assert len(scenario.events) == events and len((await owner.snapshot()).claims) == 1


@pytest.mark.asyncio
async def test_cancellation_retains_reservation_and_lock_until_connection_cleanup(worker):
    _, root, _, scenario, cycle, owner, _ = worker
    from trading_bot.runtime.stock_archive_lease import StockArchiveLease

    scenario.fail = "hang"
    task = asyncio.create_task(cycle())
    await scenario.entered.wait()
    with pytest.raises(ValueError), StockArchiveLease(root):
        pass
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert scenario.events[-1] == "closed"
    state = await owner.snapshot()
    assert state.reserved_today == 2 and state.pending_count == 1 and state.discovery_head is None
    with StockArchiveLease(root):
        pass
    count = len(scenario.events)
    assert (await cycle())["status"] == "blocked"
    assert len(scenario.events) == count


@pytest.mark.asyncio
async def test_changed_shortlist_triggers_enrichment_without_waiting_for_refresh(worker):
    _, _, clock, scenario, cycle, _, _ = worker
    await cycle()
    clock.current += timedelta(hours=1)
    await cycle()
    scenario.symbol = "BETA"
    clock.current += timedelta(hours=1)
    assert (await cycle())["phase"] == "discovery"
    clock.current += timedelta(hours=1)
    assert (await cycle())["phase"] == "enrichment"


@pytest.mark.asyncio
async def test_expiry_after_reservation_blocks_before_sdk_construction(worker, monkeypatch):
    module, _, clock, scenario, cycle, owner, _ = worker
    reserve = module.SqlStockResearchJobs.reserve

    async def late(self, **kwargs):
        claim = await reserve(self, **kwargs)
        clock.current = claim.deadline_at + timedelta(seconds=1)
        return claim

    monkeypatch.setattr(module.SqlStockResearchJobs, "reserve", late)
    assert (await cycle())["status"] == "blocked"
    assert scenario.events == []
    assert (await owner.snapshot()).discovery_head is None


@pytest.mark.asyncio
async def test_expiry_during_screen_compilation_cannot_promote_cache(worker, monkeypatch):
    module, _, clock, _, cycle, owner, _ = worker
    compile_screen = module._screen_body

    def late(**kwargs):
        report = compile_screen(**kwargs)
        clock.current = kwargs["claim"].deadline_at + timedelta(seconds=1)
        return report

    monkeypatch.setattr(module, "_screen_body", late)
    assert (await cycle())["status"] == "blocked"
    assert (await owner.snapshot()).discovery_head is None


@pytest.mark.asyncio
async def test_expiry_inside_terminal_transaction_cannot_promote_cache(worker, monkeypatch):
    module, _, clock, _, cycle, owner, _ = worker
    finish = module.SqlStockResearchJobs.finish

    async def late(self, claim, **kwargs):
        if kwargs["status"] == "succeeded":
            clock.current = claim.deadline_at + timedelta(seconds=1)
        return await finish(self, claim, **kwargs)

    monkeypatch.setattr(module.SqlStockResearchJobs, "finish", late)
    assert (await cycle())["status"] == "blocked"
    state = await owner.snapshot()
    assert state.discovery_head is None and state.pending_count == 1


@pytest.mark.asyncio
async def test_midnight_plan_change_cannot_publish_unreplayable_cache(worker, monkeypatch):
    module, _, clock, scenario, cycle, owner, _ = worker
    clock.current = NOW.replace(hour=22, minute=59, second=59)
    assert (await cycle())["status"] == "succeeded"
    clock.current += timedelta(hours=1)
    reserve = module.SqlStockResearchJobs.reserve

    async def crossed(self, **kwargs):
        if kwargs["phase"] == "enrichment":
            clock.current += timedelta(seconds=2)
        return await reserve(self, **kwargs)

    monkeypatch.setattr(module.SqlStockResearchJobs, "reserve", crossed)
    count = len(scenario.events)
    assert (await cycle())["status"] == "blocked"
    assert len(scenario.events) == count
    assert (await owner.snapshot()).enrichment_head is None
    clock.current += timedelta(hours=1)
    result = await cycle()
    assert result["status"] == "succeeded" and result["phase"] == "discovery"


@pytest.mark.asyncio
@pytest.mark.parametrize("after_commit", [False, True])
async def test_claim_commit_failure_never_constructs_sdk_or_retries(
    worker, monkeypatch, after_commit
):
    _, _, _, scenario, cycle, owner, _ = worker
    commit = AsyncSession.commit

    async def failed(self):
        if after_commit:
            await commit(self)
        raise RuntimeError("private-commit-detail")

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", failed)
        result = await cycle()
    assert result["status"] == "blocked" and scenario.events == []
    state = await owner.snapshot()
    assert len(state.claims) == int(after_commit)
    assert state.reserved_today == (2 if after_commit else 0)
    if after_commit:
        assert (await cycle())["status"] == "blocked"
        assert scenario.events == []


@pytest.mark.asyncio
async def test_unknown_terminal_commit_is_not_retried_and_recovers_from_ledger(worker, monkeypatch):
    _, _, clock, scenario, cycle, owner, _ = worker
    commit = AsyncSession.commit
    committed = []

    async def failed_ack(self):
        await commit(self)
        committed.append(True)
        if len(committed) == 2:
            raise RuntimeError("private-terminal-ack-detail")

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", failed_ack)
        assert (await cycle())["status"] == "blocked"
    state = await owner.snapshot()
    assert len(state.results) == 1 and state.discovery_head is not None
    assert len(scenario.calls) == 2
    assert (await cycle())["status"] == "blocked"
    assert len(scenario.calls) == 2
    clock.current += timedelta(hours=1)
    assert (await cycle())["phase"] == "enrichment"


@pytest.mark.asyncio
async def test_unverifiable_capture_return_cannot_become_cache_evidence(worker, monkeypatch):
    module, _, _, scenario, cycle, owner, _ = worker

    async def forged(**kwargs):
        return {"manifest_file": "c" * 64 + ".stock-capture.json", "manifest_sha256": "c" * 64}

    monkeypatch.setattr(module, "capture_stock_observations", forged)
    assert (await cycle())["reason"] == "artifact_unavailable"
    state = await owner.snapshot()
    assert state.pending_count == 1 and state.discovery_head is None and state.reserved_today == 2
    assert scenario.calls == []


@pytest.mark.asyncio
async def test_whole_run_monotonic_expiry_precedes_sdk_construction(worker, monkeypatch):
    module, _, _, scenario, cycle, owner, _ = worker
    reserve = module.SqlStockResearchJobs.reserve
    monotonic = [100.0]

    async def late(self, **kwargs):
        claim = await reserve(self, **kwargs)
        monotonic[0] += 451
        return claim

    monkeypatch.setattr(module.SqlStockResearchJobs, "reserve", late)
    assert (await cycle(monotonic=lambda: monotonic[0]))["status"] == "blocked"
    assert scenario.events == [] and (await owner.snapshot()).discovery_head is None


@pytest.mark.asyncio
async def test_enrichment_refreshes_after_canonical_six_hour_interval(worker):
    _, _, clock, _, cycle, _, _ = worker
    await cycle()
    clock.current += timedelta(hours=1)
    assert (await cycle())["phase"] == "enrichment"
    for _ in range(5):
        clock.current += timedelta(hours=1)
        assert (await cycle())["phase"] == "discovery"
    clock.current += timedelta(hours=1)
    assert (await cycle())["phase"] == "enrichment"


@pytest.mark.asyncio
async def test_truncated_current_screen_publishes_no_ranked_cache_head(worker):
    _, _, _, scenario, cycle, owner, _ = worker
    scenario.truncated = True
    result = await cycle()
    assert result["status"] == "blocked" and result["reason"] == "screen_incomplete"
    state = await owner.snapshot()
    assert state.discovery_head is None and state.pending_count == 0 and state.reserved_today == 2


@pytest.mark.asyncio
async def test_verified_stock_export_reconstructs_heads_without_new_calls_or_ledger_events(worker):
    from trading_bot.research.stock_dashboard import present_stock_dashboard
    from trading_bot.runtime.stock_dashboard_export import (
        StockDashboardReader,
        export_stock_dashboard,
    )

    _, root, clock, scenario, cycle, owner, loaded = worker
    assert (await cycle())["status"] == "succeeded"
    destination = root.parent / "dashboard-export"
    destination.mkdir(mode=0o700)
    before = await owner.snapshot()
    publication = await export_stock_dashboard(
        loaded=loaded,
        code_hash=CODE,
        factory=owner._factory,
        archive_dir=root,
        export_dir=destination,
        clock=clock.now,
    )
    projection = StockDashboardReader(root=destination, loaded=loaded)()
    view = present_stock_dashboard(projection, now=clock.now(), maximum_age_seconds=7200)
    assert publication["status"] == "published"
    assert projection.state_sha256 == before.state_hash
    assert view["opportunities"][0]["symbol"] == "ALFA"
    assert view["opportunities"][0]["dossier_as_of"] is None
    assert view["stock_worker"]["reserved_today"] == 2
    assert len(scenario.calls) == 2
    assert (await owner.snapshot()).state_hash == before.state_hash
    body = (destination / "stock-research.json").read_text()
    assert all(
        text not in body
        for text in ("fictional-ALFA", "filters_applied", "instrument_id", "payload")
    )
    clock.current += timedelta(hours=1)
    assert (await cycle())["phase"] == "enrichment"
    await export_stock_dashboard(
        loaded=loaded,
        code_hash=CODE,
        factory=owner._factory,
        archive_dir=root,
        export_dir=destination,
        clock=clock.now,
    )
    projection = StockDashboardReader(root=destination, loaded=loaded)()
    view = present_stock_dashboard(projection, now=clock.now(), maximum_age_seconds=7200)
    assert view["opportunities"][0]["dossier_as_of"] == clock.now().isoformat()
    assert "financials_absent" in view["opportunities"][0]["gaps"]
    assert projection.worker.reserved_today == 9
    assert len(scenario.calls) == 9


@pytest.mark.asyncio
async def test_blocked_capture_export_keeps_prior_evidence_with_original_times(worker):
    from trading_bot.research.stock_dashboard import present_stock_dashboard
    from trading_bot.runtime.stock_dashboard_export import (
        StockDashboardReader,
        export_stock_dashboard,
    )

    _, root, clock, scenario, cycle, owner, loaded = worker
    await cycle()
    first = clock.now()
    clock.current += timedelta(hours=1)
    scenario.fail = "auth"
    assert (await cycle())["reason"] == "auth_unavailable"
    destination = root.parent / "dashboard-export"
    destination.mkdir(mode=0o700)
    await export_stock_dashboard(
        loaded=loaded,
        code_hash=CODE,
        factory=owner._factory,
        archive_dir=root,
        export_dir=destination,
        clock=clock.now,
    )
    view = present_stock_dashboard(
        StockDashboardReader(root=destination, loaded=loaded)(),
        now=clock.now(),
        maximum_age_seconds=7200,
    )
    assert view["stock_worker"]["status"] == "blocked"
    assert view["stock_worker"]["reason"] == "auth_unavailable"
    assert view["stock_worker"]["reserved_today"] == 9
    assert view["opportunities"][0]["available_at"] == first.isoformat()
    assert len(scenario.calls) == 2


@pytest.mark.asyncio
async def test_export_rejects_tampered_cache_without_fabricating_an_empty_success(worker):
    from trading_bot.runtime.stock_dashboard_export import (
        StockDashboardExportError,
        export_stock_dashboard,
    )

    _, root, clock, scenario, cycle, owner, loaded = worker
    await cycle()
    destination = root.parent / "dashboard-export"
    destination.mkdir(mode=0o700)
    state = await owner.snapshot()
    file = root / (state.discovery_head.report_sha256 + ".stock-screen.json")
    file.write_bytes(file.read_bytes() + b" ")
    with pytest.raises(StockDashboardExportError):
        await export_stock_dashboard(
            loaded=loaded,
            code_hash=CODE,
            factory=owner._factory,
            archive_dir=root,
            export_dir=destination,
            clock=clock.now,
        )
    assert not (destination / "stock-research.json").exists()
    assert len(scenario.calls) == 2
    assert (await owner.snapshot()).state_hash == state.state_hash


@pytest.mark.asyncio
async def test_export_directory_must_be_separate_from_raw_archive(worker):
    from trading_bot.runtime.stock_dashboard_export import (
        StockDashboardExportError,
        export_stock_dashboard,
    )

    _, root, clock, scenario, cycle, owner, loaded = worker
    await cycle()
    with pytest.raises(StockDashboardExportError):
        await export_stock_dashboard(
            loaded=loaded,
            code_hash=CODE,
            factory=owner._factory,
            archive_dir=root,
            export_dir=root,
            clock=clock.now,
        )
    assert not (root / "stock-research.json").exists()
    assert len(scenario.calls) == 2


@pytest.mark.asyncio
async def test_export_budget_stays_bound_to_snapshot_utc_day_across_midnight(worker, monkeypatch):
    from trading_bot.research.stock_dashboard import present_stock_dashboard
    from trading_bot.runtime.stock_dashboard_export import (
        StockDashboardReader,
        export_stock_dashboard,
    )

    module, root, clock, _, cycle, owner, loaded = worker
    clock.current = NOW.replace(hour=23)
    await cycle()
    clock.current = NOW.replace(hour=23, minute=59, second=59)
    snapshot_time = clock.now()
    snapshot = module.SqlStockResearchJobs.snapshot

    async def crossing(self):
        state = await snapshot(self)
        clock.current += timedelta(seconds=1)
        return state

    destination = root.parent / "dashboard-export"
    destination.mkdir(mode=0o700)
    monkeypatch.setattr(module.SqlStockResearchJobs, "snapshot", crossing)
    await export_stock_dashboard(
        loaded=loaded,
        code_hash=CODE,
        factory=owner._factory,
        archive_dir=root,
        export_dir=destination,
        clock=clock.now,
    )
    projection = StockDashboardReader(root=destination, loaded=loaded)()
    assert projection.generated_at == snapshot_time
    assert projection.worker.reserved_today == 2
    view = present_stock_dashboard(projection, now=clock.now(), maximum_age_seconds=7200)
    assert view["stock_worker"]["reason"] == "budget_day_changed"
    assert view["stock_worker"]["reserved_today"] is None
