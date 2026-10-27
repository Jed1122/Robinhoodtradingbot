"""Current-provider snapshots use retained fictional intent, including unattempted names."""

import json
import sqlite3
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import pytest

from tests.integration.persistence.test_stock_current_worker_cycle import current_worker
from trading_bot.runtime import stock_snapshot as snapshot


@pytest.fixture
def current_snapshot_worker(tmp_path, sqlite_engine, alembic_config, monkeypatch):
    return current_worker.__wrapped__(tmp_path, sqlite_engine, alembic_config, monkeypatch)


async def setup(context, tmp_path, *, partial=False):
    module, archive, clock, scenario, cycle, owner, loaded = context
    assert (await cycle())["status"] == "succeeded"
    clock.current += timedelta(hours=1)
    if partial:
        scenario.fail = "get_scanner_filter_specs"
    watch = module.StockResearchWatch(
        held_symbols=("HELD",),
        watch_symbols=(),
        as_of=clock.current,
        expires_at=clock.current + timedelta(hours=1),
        source_sha256="a" * 64,
    )
    result = await cycle(watch=watch)
    assert result["status"] == ("blocked" if partial else "succeeded")
    source = Path(owner._factory.kw["bind"].url.database)
    state = tmp_path / "snapshot-source-state"
    state.mkdir(mode=0o700)
    database = state / "ledger.sqlite3"
    with (
        closing(sqlite3.connect(f"file:{source}?mode=ro", uri=True)) as original,
        closing(sqlite3.connect(database)) as copied,
    ):
        original.backup(copied)
    database.chmod(0o600)
    exports = tmp_path / "exports"
    exports.mkdir(mode=0o700)
    return dict(
        loaded=loaded,
        code_hash=context[5]._code_hash,
        database=database,
        archive_dir=archive,
        control_dir=tmp_path / "controls",
        export_dir=exports,
        destination=tmp_path / "snapshot",
        now=clock.current,
    ), result


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", ["full_replay_v1", "recovery_integrity_v1"])
@pytest.mark.parametrize("partial", [False, True])
async def test_current_held_capture_replays_same_plan_and_charges_even_before_preview(
    current_snapshot_worker, tmp_path, policy, partial
):
    kwargs, result = await setup(current_snapshot_worker, tmp_path, partial=partial)
    manifest = json.loads(
        (kwargs["archive_dir"] / (result["manifest_sha256"] + ".stock-capture.json")).read_bytes()
    )
    assert manifest["schema_version"] == 2
    assert manifest["request_plan"][2]["arguments"]["symbols"] == ["HELD"]
    if partial:
        assert manifest["successful_calls"] == 0 and manifest["attempted_calls"] == 1
    made = await snapshot.create_stock_snapshot(**kwargs, validation_policy=policy)
    checked = await snapshot.verify_stock_snapshot(kwargs["destination"], validation_policy=policy)
    assert made == checked and made.claim_count == made.result_count == 2
    assert made.pending_count == 0 and made.budget_by_day == (("2026-10-21", 11),)


@pytest.mark.asyncio
async def test_rebound_retained_plan_cannot_escape_claim_commitment(
    current_snapshot_worker, tmp_path, monkeypatch
):
    kwargs, result = await setup(current_snapshot_worker, tmp_path, partial=True)
    original = snapshot._read
    manifest_name = result["manifest_sha256"] + ".stock-capture.json"

    def rebound(directory, name, suffix):
        value = original(directory, name, suffix)
        if name == manifest_name:
            value["request_plan"][2]["arguments"]["symbols"] = ["OTHER"]
        return value

    monkeypatch.setattr(snapshot, "_read", rebound)
    with pytest.raises(ValueError, match="stock_snapshot_unavailable"):
        await snapshot.create_stock_snapshot(**kwargs)
