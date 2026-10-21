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
    monkeypatch.setattr(module, "RobinhoodMcpSdkConnection", scenario.connection)
    factory = async_session_factory(sqlite_engine)

    async def pause(seconds):
        pass

    async def cycle(**kwargs):
        return await module.run_stock_research_cycle(
            loaded=loaded,
            code_hash=CODE,
            factory=factory,
            oauth_store=tmp_path.resolve() / "unused-fixture-oauth",
            output_dir=root,
            clock=clock.now,
            sleep=pause,
            **kwargs,
        )

    owner = SqlStockResearchJobs(factory, loaded=loaded, code_hash=CODE, clock=clock.now)
    return module, root, clock, scenario, cycle, owner, loaded


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
