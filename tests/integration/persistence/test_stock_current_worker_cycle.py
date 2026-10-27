"""Two fictional current-profile cycles through the real quota/archive/cache owner."""

from datetime import timedelta

import pytest

from tests.integration.persistence import test_stock_research_worker as legacy
from tests.unit.research.test_stock_current_screen import ADDED, PROFILE


@pytest.fixture
def current_worker(tmp_path, sqlite_engine, alembic_config, monkeypatch):
    path = tmp_path / "current-worker.yaml"
    path.write_text(f"policy_id: {PROFILE}\nenrichment_refresh_minutes: 60\n")
    original_load = legacy.load_config

    def load(*args, **kwargs):
        kwargs["stock_worker_policy_path"] = path
        return original_load(*args, **kwargs)

    monkeypatch.setattr(legacy, "load_config", load)
    context = legacy.worker.__wrapped__(tmp_path, sqlite_engine, alembic_config, monkeypatch)
    scenario = context[3]
    scenario.missing_target = False
    original_call = scenario.call_tool

    async def current_call(tool, arguments):
        if tool == "preview_scan":
            named = next(
                (item for item in arguments["filters"] if item.get("expression") == "symbol"), None
            )
            if named is not None:
                scenario.symbol = named["values"][0]
        result = await original_call(tool, arguments)
        if tool == "preview_scan":
            for row in result.structured_content["data"]["result"]["results"]:
                row["columns"].update({title: "20" for title in ADDED})
                row["columns"].update({"Quotation currency": "USD", "Reporting currency": "USD"})
            if scenario.missing_target and named is not None:
                result.structured_content["data"]["result"].update(
                    {"results": [], "total_items": 0}
                )
        return result

    monkeypatch.setattr(scenario, "call_tool", current_call)
    return context


@pytest.mark.asyncio
async def test_held_symbol_outside_ranked_universe_gets_budgeted_targeted_refresh(current_worker):
    module, root, clock, scenario, cycle, owner, loaded = current_worker
    first = await cycle()
    assert first["status"] == "succeeded" and first["phase"] == "discovery"
    clock.current += timedelta(hours=1)
    watch = module.StockResearchWatch(
        held_symbols=("HELD",),
        watch_symbols=(),
        as_of=clock.current,
        expires_at=clock.current + timedelta(hours=2),
        source_sha256="a" * 64,
    )
    second = await cycle(watch=watch)
    assert second["status"] == "succeeded" and second["phase"] == "enrichment"
    assert second["planned_calls"] == 9  # 7 for one company + vocabulary + named preview.
    named = [
        args
        for tool, args in scenario.calls
        if tool == "preview_scan" and any(f.get("expression") == "symbol" for f in args["filters"])
    ]
    assert len(named) == 1 and named[0]["filters"][1]["values"] == ["HELD"]
    assert all("FILTER_TYPE_LAST" not in str(f) for f in named[0]["filters"])
    state = await owner.snapshot()
    with module.StockArchiveLease(root) as archive:
        discovery, enrichment = module._cached(
            state=state, archive=archive, root=root, policy=loaded.config, now=clock.current
        )
    assert discovery["worker_profile_id"] == PROFILE
    assert [item["symbol"] for item in enrichment["dossiers"]] == ["HELD"]
    assert state.reserved_today == 11  # two discovery + nine whole enrichment calls.
    assert discovery["live_enabled"] is enrichment["live_enabled"] is False


@pytest.mark.asyncio
async def test_omitted_held_row_preserves_capture_but_never_promotes_success(current_worker):
    module, root, clock, scenario, cycle, owner, loaded = current_worker
    assert (await cycle())["status"] == "succeeded"
    clock.current += timedelta(hours=1)
    scenario.missing_target = True
    watch = module.StockResearchWatch(
        held_symbols=("HELD",),
        watch_symbols=(),
        as_of=clock.current,
        expires_at=clock.current + timedelta(hours=1),
        source_sha256="a" * 64,
    )
    result = await cycle(watch=watch)
    assert result["status"] == "blocked" and result["reason"] == "report_failed"
    assert result["manifest_sha256"] is not None and result["report_sha256"] is None
    state = await owner.snapshot()
    assert state.enrichment_head is None and state.reserved_today == 11
    with module.StockArchiveLease(root) as archive:
        discovery, enrichment = module._cached(
            state=state, archive=archive, root=root, policy=loaded.config, now=clock.current
        )
    assert discovery is not None and enrichment is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,reason",
    [
        ("capacity", "watch_coverage_capacity_exceeded"),
        ("stale", "watch_unavailable"),
    ],
)
async def test_fixed_preclaim_watch_denial_is_explicit_without_calls_or_reservation(
    current_worker, case, reason
):
    module, _, clock, scenario, cycle, owner, _ = current_worker
    watch = module.StockResearchWatch(
        held_symbols=("HELD", "OTHER") if case == "capacity" else ("HELD",),
        watch_symbols=(),
        as_of=clock.current - timedelta(hours=3) if case == "stale" else clock.current,
        expires_at=clock.current + timedelta(hours=1),
        source_sha256="a" * 64,
    )
    assert await cycle(watch=watch) == {
        "status": "blocked",
        "reason": reason,
        "live_enabled": False,
    }
    assert scenario.calls == scenario.events == []
    assert (await owner.snapshot()).claims == ()


@pytest.fixture
def legacy_worker(tmp_path, sqlite_engine, alembic_config, monkeypatch):
    return legacy.worker.__wrapped__(tmp_path, sqlite_engine, alembic_config, monkeypatch)


@pytest.mark.asyncio
async def test_watch_cannot_silently_activate_profile_on_legacy_worker(legacy_worker):
    module, _, clock, scenario, cycle, owner, _ = legacy_worker
    watch = module.StockResearchWatch(
        held_symbols=("HELD",),
        watch_symbols=(),
        as_of=clock.current,
        expires_at=clock.current + timedelta(hours=1),
        source_sha256="a" * 64,
    )
    assert await cycle(watch=watch) == {
        "status": "blocked",
        "reason": "watch_profile_required",
        "live_enabled": False,
    }
    assert scenario.calls == scenario.events == []
    assert (await owner.snapshot()).claims == ()


@pytest.mark.asyncio
async def test_other_worker_errors_remain_sanitized(current_worker, monkeypatch):
    module, _, _, scenario, cycle, owner, _ = current_worker

    def deny(**kwargs):
        raise module.StockWorkerError("private-provider-detail")

    monkeypatch.setattr(module, "_select", deny)
    assert await cycle() == {
        "status": "blocked",
        "reason": "artifact_unavailable",
        "live_enabled": False,
    }
    assert scenario.calls == scenario.events == []
    assert (await owner.snapshot()).claims == ()
