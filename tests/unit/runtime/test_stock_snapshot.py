"""Coherent fictional stock snapshots and killed isolated restoration; no provider access."""

import hashlib
import importlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from trading_bot.brokers.robinhood_mcp_transport import McpToolResult
from trading_bot.brokers.stock_research_mcp import StockResearchTransport
from trading_bot.config import load_config
from trading_bot.domain import CodeHash
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.persistence.stock_research_jobs import SqlStockResearchJobs
from trading_bot.research.stock_screen import TURNOVER_COLUMN
from trading_bot.runtime.stock_archive_lease import StockArchiveLease
from trading_bot.runtime.stock_capture import _publish, capture_stock_observations
from trading_bot.runtime.stock_research_controls import StockResearchControls
from trading_bot.runtime.stock_research_worker import (
    _plan_hash,
    _requests,
    _screen_body,
    _verified_capture,
)

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)
CODE = CodeHash("b" * 64)


def module():
    try:
        return importlib.import_module("trading_bot.runtime.stock_snapshot")
    except ModuleNotFoundError:
        pytest.fail("Coherent stock snapshot implementation is missing")


@pytest.fixture
def sample(tmp_path):
    root = tmp_path.resolve()
    state = root / "state"
    state.mkdir(mode=0o700)
    database = state / "ledger.sqlite3"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    command.upgrade(config, "head")
    database.chmod(0o600)
    policy = root / "fictional-stock-policy.yaml"
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
    for name in ("archive", "controls", "exports"):
        (root / name).mkdir(mode=0o700)
    controls = StockResearchControls(root / "controls", clock=lambda: NOW)
    controls.initialize()
    return {
        "loaded": loaded,
        "code_hash": CODE,
        "database": database,
        "archive_dir": root / "archive",
        "control_dir": root / "controls",
        "export_dir": root / "exports",
        "destination": root / "snapshot",
        "now": NOW,
    }


async def reserve(sample, *, at=NOW):
    engine = create_engine(f"sqlite+aiosqlite:///{sample['database']}")
    try:
        jobs = SqlStockResearchJobs(
            async_session_factory(engine), loaded=sample["loaded"], code_hash=CODE, clock=lambda: at
        )
        state = await jobs.snapshot()
        return await jobs.reserve(
            phase="discovery",
            plan_sha256="c" * 64,
            planned_calls=17,
            expected_state_hash=state.state_hash,
        )
    finally:
        await engine.dispose()


async def discovery(sample, *, at=NOW, candidate=False, partial=False):
    from trading_bot.runtime.stock_capture import _json

    class EmptyResearch:
        async def call_tool(self, name, arguments):
            if partial and name == "preview_scan":
                raise RuntimeError("fictional research failure")
            rows = (
                []
                if not candidate
                else [
                    {
                        "ticker": "ALFA",
                        "instrument_id": "fictional-ALFA",
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
                ]
            )
            value = (
                {"filter_specs": []}
                if name == "get_scanner_filter_specs"
                else {
                    "result": {
                        "total_items": len(rows),
                        "filters_applied": arguments["filters"],
                        "results": rows,
                    }
                }
            )
            return McpToolResult((), False, {"data": value})

    async def no_wait(seconds):
        return None

    engine = create_engine(f"sqlite+aiosqlite:///{sample['database']}")
    try:
        jobs = SqlStockResearchJobs(
            async_session_factory(engine), loaded=sample["loaded"], code_hash=CODE, clock=lambda: at
        )
        policy = sample["loaded"].config
        plan = _requests("discovery", policy, at, ())
        state = await jobs.snapshot()
        claim = await jobs.reserve(
            phase="discovery",
            plan_sha256=_plan_hash(plan),
            planned_calls=len(plan),
            expected_state_hash=state.state_hash,
        )
        capture = await capture_stock_observations(
            transport=StockResearchTransport(EmptyResearch()),
            requests=plan,
            output_dir=sample["archive_dir"],
            transport_authenticated=True,
            clock=lambda: at,
            sleep=no_wait,
        )
        if partial:
            return await jobs.finish(
                claim,
                status="blocked",
                reason="capture_partial",
                capture_plan_sha256=claim.plan_sha256,
                attempted_calls=capture["attempted_calls"],
                successful_calls=capture["successful_calls"],
                manifest_sha256=capture["manifest_sha256"],
                report_sha256=None,
            )
        with StockArchiveLease(sample["archive_dir"]) as lease:
            _, rows = _verified_capture(
                archive=lease,
                root=sample["archive_dir"],
                claim=claim,
                plan=plan,
                manifest_sha256=capture["manifest_sha256"],
                now=at,
            )
            report = _screen_body(
                claim=claim,
                observations=rows,
                manifest_sha256=capture["manifest_sha256"],
                policy=policy,
                at=at,
            )
            assert report["screen"]["coverage_complete"] is True
            _, digest = _publish(lease.directory_fd, _json(report), ".stock-screen.json")
        return await jobs.finish(
            claim,
            status="succeeded",
            reason="complete",
            capture_plan_sha256=claim.plan_sha256,
            attempted_calls=len(plan),
            successful_calls=len(plan),
            manifest_sha256=capture["manifest_sha256"],
            report_sha256=digest,
        )
    finally:
        await engine.dispose()


async def enrichment(sample, source, *, at):
    from trading_bot.runtime.stock_capture import _json
    from trading_bot.runtime.stock_dossier_report import compile_stock_dossier_report

    class Research:
        async def call_tool(self, name, arguments):
            data = {
                "get_equity_fundamentals": {
                    "results": [{"symbol": "ALFA", "market_cap": "5000000000"}]
                },
                "get_financials": {"results": [None]},
                "get_equity_quotes": {"results": []},
                "get_equity_historicals": {
                    "results": [
                        {
                            "symbol": "ALFA",
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
                },
                "get_earnings_results": {"results": []},
                "get_sec_filing_index": {"symbol": "ALFA", "filings": [], "next": ""},
            }[name]
            return McpToolResult((), False, {"data": data})

    async def no_wait(seconds):
        return None

    engine = create_engine(f"sqlite+aiosqlite:///{sample['database']}")
    try:
        jobs = SqlStockResearchJobs(
            async_session_factory(engine), loaded=sample["loaded"], code_hash=CODE, clock=lambda: at
        )
        plan = _requests("enrichment", sample["loaded"].config, at, ("ALFA",))
        state = await jobs.snapshot()
        claim = await jobs.reserve(
            phase="enrichment",
            plan_sha256=_plan_hash(plan),
            planned_calls=len(plan),
            expected_state_hash=state.state_hash,
            source_result_sha256=source.record_sha256,
        )
        capture = await capture_stock_observations(
            transport=StockResearchTransport(Research()),
            requests=plan,
            output_dir=sample["archive_dir"],
            transport_authenticated=True,
            clock=lambda: at,
            sleep=no_wait,
        )
        with StockArchiveLease(sample["archive_dir"]) as lease:
            _, rows = _verified_capture(
                archive=lease,
                root=sample["archive_dir"],
                claim=claim,
                plan=plan,
                manifest_sha256=capture["manifest_sha256"],
                now=at,
            )
            report = compile_stock_dossier_report(observations=rows, as_of=at)
            report["source_manifest_sha256"] = capture["manifest_sha256"]
            assert report["normalization_denials"] == []
            _, digest = _publish(lease.directory_fd, _json(report), ".stock-dossiers.json")
        return await jobs.finish(
            claim,
            status="succeeded",
            reason="complete",
            capture_plan_sha256=claim.plan_sha256,
            attempted_calls=len(plan),
            successful_calls=len(plan),
            manifest_sha256=capture["manifest_sha256"],
            report_sha256=digest,
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_round_trip_replays_real_migrations_and_keeps_pending_daily_charges(sample):
    pending = await reserve(sample)
    original_control = (sample["control_dir"] / "stock-control.json").read_bytes()
    result = await module().create_stock_snapshot(**sample)
    assert (result.claim_count, result.result_count, result.pending_count) == (1, 0, 1)
    assert result.budget_by_day == (("2026-10-22", 17),)
    assert result.state_sha256 == pending.record_sha256
    root = sample["destination"]
    assert (root / "canonical-config.json").read_bytes() == sample["loaded"].canonical_json
    assert (root / "saved-control.json").read_bytes() == original_control
    assert (sample["control_dir"] / "stock-control.json").read_bytes() == original_control
    verified = await module().verify_stock_snapshot(root)
    assert verified == result
    assert len(result.manifest_sha256) == 64
    assert not (root / "controls").exists()
    assert not any("oauth" in str(path.relative_to(root)) for path in root.rglob("*"))


@pytest.mark.asyncio
async def test_snapshot_rejects_missing_historical_report_even_when_newest_head_is_valid(sample):
    old = await discovery(sample)
    await discovery(sample, at=NOW + timedelta(hours=1))
    (sample["archive_dir"] / (old.report_sha256 + ".stock-screen.json")).unlink()
    sample["now"] = NOW + timedelta(hours=1)
    with pytest.raises(ValueError, match="stock_snapshot_unavailable"):
        await module().create_stock_snapshot(**sample)


@pytest.mark.asyncio
async def test_snapshot_preserves_committed_reports_and_original_observation_times(sample):
    result = await discovery(sample)
    source = sample["archive_dir"] / (result.report_sha256 + ".stock-screen.json")
    raw = source.read_bytes()
    made = await module().create_stock_snapshot(**sample)
    assert made.result_count == 1 and made.pending_count == 0
    assert (sample["destination"] / "archive" / source.name).read_bytes() == raw
    assert json.loads(raw)["as_of"] == NOW.isoformat()


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", ["archive_dir", "control_dir", "export_dir"])
async def test_busy_application_mutex_never_acknowledges_a_snapshot(sample, tree):
    owner = (
        StockResearchControls(sample[tree], clock=lambda: NOW) if tree == "control_dir" else None
    )
    lease = owner._locked() if owner else StockArchiveLease(sample[tree])
    with lease, pytest.raises(ValueError, match="stock_snapshot_unavailable"):
        await module().create_stock_snapshot(**sample)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["symlink", "hardlink", "public", "unknown", "bad_hash"])
async def test_snapshot_denies_unsafe_archive_without_changing_the_source(sample, kind):
    path = sample["archive_dir"] / ("a" * 64 + ".stock-observation.json")
    path.write_bytes(b"{}")
    path.chmod(0o600)
    if kind == "symlink":
        other = sample["archive_dir"].parent / "outside"
        path.rename(other)
        path.symlink_to(other)
    elif kind == "hardlink":
        os.link(path, sample["archive_dir"].parent / "outside")
    elif kind == "public":
        path.chmod(0o644)
    elif kind == "unknown":
        path.rename(sample["archive_dir"] / "unrelated")
    with pytest.raises(ValueError, match="stock_snapshot_unavailable"):
        await module().create_stock_snapshot(**sample)
    assert any(sample["archive_dir"].iterdir())


@pytest.mark.asyncio
async def test_existing_destination_and_oversized_ledger_are_never_replaced(sample, monkeypatch):
    sample["destination"].mkdir(mode=0o700)
    marker = sample["destination"] / "unrelated"
    marker.write_bytes(b"preserved")
    with pytest.raises(ValueError):
        await module().create_stock_snapshot(**sample)
    assert marker.read_bytes() == b"preserved"
    sample["destination"] = sample["destination"].with_name("second")
    monkeypatch.setattr(module(), "_MAX_LEDGER_BYTES", 1)
    with pytest.raises(ValueError):
        await module().create_stock_snapshot(**sample)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["unknown", "config", "ledger", "manifest", "symlink"])
async def test_offline_verifier_denies_tampering_and_open_inventory(sample, kind):
    await module().create_stock_snapshot(**sample)
    root = sample["destination"]
    if kind == "unknown":
        (root / "unrelated").touch(mode=0o600)
    elif kind == "symlink":
        path = root / "saved-control.json"
        path.unlink()
        path.symlink_to(sample["control_dir"] / "stock-control.json")
    else:
        path = (
            root
            / {
                "config": "canonical-config.json",
                "ledger": "state/ledger.sqlite3",
                "manifest": "manifest.json",
            }[kind]
        )
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="stock_snapshot_unavailable"):
        await module().verify_stock_snapshot(root)


@pytest.mark.asyncio
async def test_copied_ledger_must_retain_actual_audit_trigger_bodies(sample):
    with closing(sqlite3.connect(sample["database"])) as db, db:
        db.execute("DROP TRIGGER trg_audit_events_append_only_update")
        db.execute(
            'CREATE TRIGGER trg_audit_events_append_only_update BEFORE UPDATE ON "audit_events" '
            "BEGIN SELECT 1; END"
        )
    with pytest.raises(ValueError, match="stock_snapshot_unavailable"):
        await module().create_stock_snapshot(**sample)


@pytest.mark.asyncio
async def test_restore_kills_original_identity_and_retains_forensic_saved_grant(sample):
    owner = StockResearchControls(sample["control_dir"], clock=lambda: NOW)
    saved = owner.read()
    saved = owner.change(
        "resume",
        expected_sha256=saved.sha256,
        config_hash=str(sample["loaded"].config_hash),
        code_hash=CODE,
    )
    await module().create_stock_snapshot(**sample)
    destination = sample["destination"].with_name("restored")
    result = module().restore_snapshot_controls(
        sample["destination"], destination=destination, now=NOW
    )
    restored = StockResearchControls(destination / "controls", clock=lambda: NOW).read()
    assert result.offline_only is True
    assert restored.record.status == "killed"
    assert restored.record.control_id == saved.record.control_id
    assert restored.record.generation == saved.record.generation + 1
    assert restored.record.previous_sha256 == saved.sha256
    assert (destination / "saved-control.json").read_bytes() == (
        sample["destination"] / "saved-control.json"
    ).read_bytes()


@pytest.mark.asyncio
async def test_later_kill_wins_and_foreign_high_water_is_rejected(sample):
    owner = StockResearchControls(sample["control_dir"], clock=lambda: NOW)
    saved = owner.read()
    await module().create_stock_snapshot(**sample)
    killed = owner.change("kill", expected_sha256=saved.sha256)
    destination = sample["destination"].with_name("restored")
    result = module().restore_snapshot_controls(
        sample["destination"], destination=destination, now=NOW, high_water=killed
    )
    assert result.offline_only is False
    assert StockResearchControls(destination / "controls", clock=lambda: NOW).read() == killed
    other = sample["destination"].with_name("other-control")
    other.mkdir(mode=0o700)
    foreign = StockResearchControls(other, clock=lambda: NOW).initialize()
    with pytest.raises(ValueError, match="stock_snapshot_unavailable"):
        module().restore_snapshot_controls(
            sample["destination"],
            destination=destination.with_name("foreign"),
            now=NOW,
            high_water=foreign,
        )


@pytest.mark.asyncio
async def test_manifest_cannot_adopt_a_replaced_empty_publication_file(sample, monkeypatch):
    implementation = module()
    original = implementation._replay

    async def replace(*args):
        result = await original(*args)
        manifest = sample["destination"] / "manifest.json"
        if manifest.exists():
            manifest.unlink()
        manifest.touch(mode=0o600)
        return result

    monkeypatch.setattr(implementation, "_replay", replace)
    with pytest.raises(ValueError, match="stock_snapshot_unavailable"):
        await implementation.create_stock_snapshot(**sample)


@pytest.mark.asyncio
async def test_database_inventory_denies_unsafe_wal_or_unrelated_state(sample):
    path = sample["database"].parent / "ledger.sqlite3-wal"
    other = sample["database"].parent.parent / "unrelated"
    other.write_bytes(b"private unrelated data")
    other.chmod(0o600)
    path.symlink_to(other)
    with pytest.raises(ValueError, match="stock_snapshot_unavailable"):
        await module().create_stock_snapshot(**sample)
    assert other.read_bytes() == b"private unrelated data"


@pytest.mark.asyncio
async def test_rehashed_manifest_cannot_substitute_booleans_for_integer_application_counts(sample):
    await reserve(sample)
    await module().create_stock_snapshot(**sample)
    path = sample["destination"] / "manifest.json"
    row = json.loads(path.read_bytes())
    row["application"]["claim_count"] = True
    path.write_bytes(json.dumps(row, sort_keys=True, separators=(",", ":")).encode())
    with pytest.raises(ValueError, match="stock_snapshot_unavailable"):
        await module().verify_stock_snapshot(sample["destination"])


@pytest.mark.asyncio
async def test_ledger_hashing_is_streamed_instead_of_buffering_the_database(sample, monkeypatch):
    implementation = module()
    original = implementation._read_bytes

    def bounded(directory, name, limit, window):
        assert name != "ledger.sqlite3" or limit <= 1048576, (
            "Database bytes must be hashed in bounded chunks"
        )
        return original(directory, name, limit, window)

    monkeypatch.setattr(implementation, "_read_bytes", bounded)
    await implementation.create_stock_snapshot(**sample)
    await implementation.verify_stock_snapshot(sample["destination"])


@pytest.mark.asyncio
async def test_source_replacement_during_copy_denies_result(sample, monkeypatch):
    data = b"forensic crash prefix"
    path = sample["archive_dir"] / (".pending-" + "c" * 32)
    path.write_bytes(data)
    path.chmod(0o600)
    implementation = module()
    original = implementation._copy_file

    def replace(source, target, name, expected, limit, window):
        original(source, target, name, expected, limit, window)
        if name == path.name:
            path.unlink()
            path.write_bytes(data)
            path.chmod(0o600)

    monkeypatch.setattr(implementation, "_copy_file", replace)
    with pytest.raises(ValueError, match="stock_snapshot_unavailable"):
        await implementation.create_stock_snapshot(**sample)


@pytest.mark.asyncio
async def test_killed_snapshot_is_preserved_and_older_high_water_is_denied(sample):
    owner = StockResearchControls(sample["control_dir"], clock=lambda: NOW)
    earlier = owner.read()
    killed = owner.change("kill", expected_sha256=earlier.sha256)
    await module().create_stock_snapshot(**sample)
    target = sample["destination"].with_name("killed-copy")
    module().restore_snapshot_controls(sample["destination"], destination=target, now=NOW)
    assert StockResearchControls(target / "controls", clock=lambda: NOW).read() == killed
    with pytest.raises(ValueError, match="stock_snapshot_unavailable"):
        module().restore_snapshot_controls(
            sample["destination"],
            destination=target.with_name("rollback-copy"),
            now=NOW,
            high_water=earlier,
        )


@pytest.mark.asyncio
async def test_source_failures_and_expired_helper_window_never_publish_a_manifest(
    sample, monkeypatch
):
    implementation = module()
    monkeypatch.setattr(implementation.time, "monotonic", lambda: 1.0)
    original = implementation._copy_file

    def expired(*args):
        original(*args)
        monkeypatch.setattr(implementation.time, "monotonic", lambda: 301.0)

    monkeypatch.setattr(implementation, "_copy_file", expired)
    with pytest.raises(ValueError, match="stock_snapshot_unavailable"):
        await implementation.create_stock_snapshot(**sample)
    manifest = sample["destination"] / "manifest.json"
    assert not manifest.exists() or manifest.read_bytes() == b""


@pytest.mark.asyncio
async def test_quiesced_wal_backup_does_not_create_live_sqlite_sidecars(sample):
    before = {path.name: path.read_bytes() for path in sample["database"].parent.iterdir()}
    await module().create_stock_snapshot(**sample)
    after = {path.name: path.read_bytes() for path in sample["database"].parent.iterdir()}
    assert before == after
    assert {path.name for path in (sample["destination"] / "state").iterdir()} == {"ledger.sqlite3"}


@pytest.mark.asyncio
async def test_nonempty_enrichment_replays_its_exact_original_discovery_shortlist(sample):
    source = await discovery(sample, candidate=True)
    result = await enrichment(sample, source, at=NOW + timedelta(hours=1))
    sample["now"] += timedelta(hours=1)
    made = await module().create_stock_snapshot(**sample)
    assert (made.claim_count, made.result_count, made.pending_count) == (2, 2, 0)
    copied = sample["destination"] / "archive" / (result.report_sha256 + ".stock-dossiers.json")
    assert json.loads(copied.read_bytes())["dossiers"][0]["symbol"] == "ALFA"
    assert await module().verify_stock_snapshot(sample["destination"]) == made


@pytest.mark.asyncio
async def test_older_export_reconstructs_at_saved_generation_without_renewing_source_times(sample):
    from trading_bot.runtime.stock_dashboard_export import export_stock_dashboard

    await discovery(sample, candidate=True)
    engine = create_engine(f"sqlite+aiosqlite:///{sample['database']}")
    try:
        await export_stock_dashboard(
            loaded=sample["loaded"],
            code_hash=CODE,
            factory=async_session_factory(engine),
            archive_dir=sample["archive_dir"],
            export_dir=sample["export_dir"],
            clock=lambda: NOW,
        )
    finally:
        await engine.dispose()
    original = (sample["export_dir"] / "stock-research.json").read_bytes()
    await reserve(sample, at=NOW + timedelta(hours=1))
    sample["now"] += timedelta(hours=1)
    made = await module().create_stock_snapshot(**sample)
    copied = sample["destination"] / "exports" / "stock-research.json"
    assert copied.read_bytes() == original and made.pending_count == 1
    assert json.loads(copied.read_bytes())["generated_at"] == "2026-10-22T12:00:00Z"
    assert await module().verify_stock_snapshot(sample["destination"]) == made


@pytest.mark.asyncio
async def test_rehashed_ledger_with_foreign_key_corruption_is_rejected_on_restore(sample):
    await module().create_stock_snapshot(**sample)
    root = sample["destination"]
    ledger = root / "state" / "ledger.sqlite3"
    with closing(sqlite3.connect(ledger)) as connection, connection:
        connection.executescript(
            "CREATE TABLE parent_restore_test(id INTEGER PRIMARY KEY);"
            "CREATE TABLE child_restore_test(id INTEGER REFERENCES parent_restore_test(id));"
            "INSERT INTO child_restore_test VALUES (42);"
        )
    path = root / "manifest.json"
    row = json.loads(path.read_bytes())
    row["files"]["state/ledger.sqlite3"] = {
        "sha256": hashlib.sha256(ledger.read_bytes()).hexdigest(),
        "size": ledger.stat().st_size,
    }
    path.write_bytes(json.dumps(row, sort_keys=True, separators=(",", ":")).encode())
    with pytest.raises(ValueError, match="stock_snapshot_unavailable"):
        await module().verify_stock_snapshot(root)


@pytest.mark.asyncio
async def test_committed_wal_reservation_is_copied_without_transplanting_shared_memory(sample):
    engine = create_engine(f"sqlite+aiosqlite:///{sample['database']}")
    try:
        jobs = SqlStockResearchJobs(
            async_session_factory(engine),
            loaded=sample["loaded"],
            code_hash=CODE,
            clock=lambda: NOW,
        )
        before = await jobs.snapshot()
        claim = await jobs.reserve(
            phase="discovery",
            plan_sha256="c" * 64,
            planned_calls=17,
            expected_state_hash=before.state_hash,
        )
        assert sample["database"].with_name("ledger.sqlite3-wal").stat().st_size > 0
        assert sample["database"].with_name("ledger.sqlite3-shm").exists()
        made = await module().create_stock_snapshot(**sample)
        assert made.state_sha256 == claim.record_sha256 and made.pending_count == 1
        assert made.budget_by_day == (("2026-10-22", 17),)
        assert await module().verify_stock_snapshot(sample["destination"]) == made
        assert {path.name for path in (sample["destination"] / "state").iterdir()} == {
            "ledger.sqlite3"
        }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_failed_authentication_result_retains_the_entire_daily_reservation(sample):
    claim = await reserve(sample)
    engine = create_engine(f"sqlite+aiosqlite:///{sample['database']}")
    try:
        jobs = SqlStockResearchJobs(
            async_session_factory(engine),
            loaded=sample["loaded"],
            code_hash=CODE,
            clock=lambda: NOW,
        )
        result = await jobs.finish(
            claim,
            status="blocked",
            reason="auth_unavailable",
            capture_plan_sha256=None,
            attempted_calls=0,
            successful_calls=0,
            manifest_sha256=None,
            report_sha256=None,
        )
    finally:
        await engine.dispose()
    made = await module().create_stock_snapshot(**sample)
    assert (made.claim_count, made.result_count, made.pending_count) == (1, 1, 0)
    assert made.state_sha256 == result.record_sha256
    assert made.budget_by_day == (("2026-10-22", 17),)


@pytest.mark.asyncio
async def test_partial_capture_is_replayed_without_promoting_or_refunding_its_reservation(sample):
    result = await discovery(sample, partial=True)
    made = await module().create_stock_snapshot(**sample)
    assert made.result_count == 1 and made.pending_count == 0
    assert made.budget_by_day == (("2026-10-22", 2),)
    assert result.successful_calls == 1 and result.report_sha256 is None
    assert await module().verify_stock_snapshot(sample["destination"]) == made
