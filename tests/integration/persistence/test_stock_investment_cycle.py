"""Current stock research through durable planning with real local source owners."""

import importlib
from datetime import timedelta

import pytest

from tests.integration.persistence.test_stock_current_worker_cycle import (
    current_worker as current_worker,
)
from tests.integration.persistence.test_stock_research_worker import CODE
from trading_bot.brokers.robinhood_mcp_transport import McpToolResult
from trading_bot.runtime.stock_research_controls import StockResearchControls


def api():
    try:
        return importlib.import_module("trading_bot.runtime.stock_investment_cycle")
    except ModuleNotFoundError:
        pytest.fail("verified current stock planning cycle missing")


async def acquire(data):
    _, _, clock, scenario, cycle, _, _ = data
    original = scenario.call_tool

    async def positive(tool, arguments):
        result = await original(tool, arguments)
        if tool == "preview_scan":
            for row in result.structured_content["data"]["result"]["results"]:
                row["columns"].update(
                    {"Assets/equity": "2", "Provider close 20": "90", "Provider SMA 50": "95"}
                )
        if tool == "get_financials":
            result = McpToolResult(
                (),
                False,
                {
                    "data": {
                        "results": [
                            {
                                "symbol": "ALFA",
                                "period": arguments["period"],
                                "financials": [
                                    {
                                        "fiscal_year": 2026,
                                        "fiscal_quarter": 3
                                        if arguments["period"] == "quarterly"
                                        else None,
                                        "period_end_date": "2026-09-30",
                                        "net_income": "100",
                                        "revenue": "1000",
                                    }
                                ],
                            }
                        ]
                    }
                },
            )
        return result

    scenario.call_tool = positive
    assert (await cycle())["status"] == "succeeded"
    clock.current += timedelta(hours=1)
    assert (await cycle())["status"] == "succeeded"


async def run(data, output, **changes):
    _, root, clock, _, _, owner, loaded = data
    values = dict(
        loaded=loaded,
        acquisition_code_hash=CODE,
        analysis_code_hash="7" * 64,
        factory=owner._factory,
        archive_dir=root,
        output_dir=output,
        controls=StockResearchControls(root.parent / "controls", clock=clock.now),
        clock=clock.now,
    )
    values.update(changes)
    return await api().run_current_stock_planning_cycle(**values)


@pytest.mark.asyncio
async def test_source_to_rankings_to_private_report_uses_no_more_provider_or_account_calls(
    current_worker, tmp_path
):
    await acquire(current_worker)
    _, root, _, scenario, _, owner, _ = current_worker
    output = tmp_path / "plans"
    output.mkdir(mode=0o700)
    calls, events = list(scenario.calls), list(scenario.events)
    state = await owner.snapshot()
    result = await run(current_worker, output)
    assert result["status"] == "current_stock_plan_published"
    assert result["long_term_candidates"] == result["tactical_candidates"] == 1
    assert result["proposed_entries"] == 0 and result["live_enabled"] is False
    assert "account_context_missing" in result["needs"]
    assert (output / result["artifact_file"]).is_file()
    assert scenario.calls == calls and scenario.events == events
    assert (await owner.snapshot()).state_hash == state.state_hash
    assert await run(current_worker, output) == result
    assert len(list(output.glob("*.stock-investment.json"))) == 1
    assert not list(root.glob("*.stock-investment.json"))


@pytest.mark.asyncio
async def test_manual_kill_blocks_the_planning_cycle_without_mutating_sources(
    current_worker, tmp_path
):
    await acquire(current_worker)
    _, root, clock, scenario, _, owner, _ = current_worker
    control = StockResearchControls(root.parent / "controls", clock=clock.now)
    before = control.read()
    control.change("kill", expected_sha256=before.sha256)
    output = tmp_path / "plans"
    output.mkdir(mode=0o700)
    calls = list(scenario.calls)
    state = await owner.snapshot()
    assert await run(current_worker, output) == {
        "status": "blocked",
        "reason": "research_control_denied",
        "live_enabled": False,
    }
    assert scenario.calls == calls and not list(output.iterdir())
    assert (await owner.snapshot()).state_hash == state.state_hash


@pytest.mark.asyncio
async def test_expired_current_data_is_reported_without_any_eligible_candidate_or_new_calls(
    current_worker, tmp_path
):
    await acquire(current_worker)
    _, _, clock, scenario, _, _, _ = current_worker
    clock.current += timedelta(hours=3)
    output = tmp_path / "plans"
    output.mkdir(mode=0o700)
    calls = list(scenario.calls)
    result = await run(current_worker, output)
    assert result["status"] == "current_stock_plan_published"
    assert result["long_term_candidates"] == result["tactical_candidates"] == 0
    assert "discovery_stale" in result["needs"]
    assert scenario.calls == calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ("planning_deadline", "decision_expiry", "control_expiry", "portfolio_expiry")
)
async def test_evidence_expiring_during_analysis_is_not_published_as_current(
    current_worker, tmp_path, monkeypatch, case
):
    await acquire(current_worker)
    _, _, clock, scenario, _, _, _ = current_worker
    module = api()
    extra = {}
    elapsed = timedelta(seconds=301)
    if case == "portfolio_expiry":
        elapsed = timedelta(seconds=31)
    if case == "decision_expiry":
        clock.current += timedelta(minutes=119)
        elapsed = timedelta(seconds=61)
    elif case == "control_expiry":
        from trading_bot.runtime.stock_investment_plan import StockPlanningControls

        extra["planning_controls"] = StockPlanningControls(
            research_enabled=True,
            kill_switch_active=False,
            tactical_entries_suspended=False,
            as_of=clock.current,
            expires_at=clock.current + timedelta(seconds=30),
            source_hash="8" * 64,
        )
        elapsed = timedelta(seconds=31)
    original = module.compile_current_stock_plan

    def slow_compile(*args, **kwargs):
        result = original(*args, **kwargs)
        if case == "portfolio_expiry":
            from dataclasses import replace

            result = replace(
                result,
                portfolio_proposals=replace(
                    result.portfolio_proposals, expires_at=clock.current + timedelta(seconds=30)
                ),
            )
        clock.current += elapsed
        return result

    monkeypatch.setattr(module, "compile_current_stock_plan", slow_compile)
    output = tmp_path / "plans"
    output.mkdir(mode=0o700)
    calls = list(scenario.calls)
    assert await run(current_worker, output, **extra) == {
        "status": "blocked",
        "reason": "current_stock_planning_unavailable",
        "live_enabled": False,
    }
    assert not list(output.iterdir()) and scenario.calls == calls


@pytest.mark.asyncio
async def test_optional_watch_requires_explicit_current_account_and_preserves_source_clocks(
    current_worker, tmp_path
):
    from tests.unit.portfolio.test_stock_allocation import NOW, context
    from trading_bot.runtime.stock_research_watch import read_stock_research_watch

    clock = current_worker[2]
    clock.current = NOW - timedelta(hours=1)
    await acquire(current_worker)
    output, target = tmp_path / "plans", tmp_path / "watch"
    output.mkdir(mode=0o700)
    target.mkdir(mode=0o700)
    account = context()
    result = await run(
        current_worker,
        output,
        allocation_context=account,
        watch_output_dir=target,
        watch_symbols=("BETA",),
    )
    assert result["status"] == "current_stock_plan_published"
    assert result["watch_status"] == "published"
    restored = read_stock_research_watch(root=target, clock=clock.now)
    assert restored.held_symbols == () and restored.watch_symbols == ("BETA",)
    assert restored.as_of == account.as_of and restored.expires_at == account.expires_at
    assert restored.source_sha256 == account.evidence_hash


@pytest.mark.asyncio
async def test_optional_watch_cannot_invent_an_empty_account(current_worker, tmp_path):
    await acquire(current_worker)
    output, target = tmp_path / "plans", tmp_path / "watch"
    output.mkdir(mode=0o700)
    target.mkdir(mode=0o700)
    result = await run(current_worker, output, watch_output_dir=target)
    assert result == {
        "status": "blocked",
        "reason": "current_stock_planning_unavailable",
        "live_enabled": False,
    }
    assert not list(target.iterdir()) and not list(output.iterdir())


@pytest.mark.asyncio
async def test_expiry_during_file_publication_never_returns_a_success_receipt(
    current_worker, tmp_path, monkeypatch
):
    await acquire(current_worker)
    _, root, clock, scenario, _, _, _ = current_worker
    reports = importlib.import_module("trading_bot.runtime.stock_investment_reports")
    original = reports.publish_current_stock_plan

    def slow_publication(*args, **kwargs):
        artifact = original(*args, **kwargs)
        clock.current += timedelta(minutes=6)
        return artifact

    monkeypatch.setattr(reports, "publish_current_stock_plan", slow_publication)
    output = tmp_path / "plans"
    output.mkdir(mode=0o700)
    calls = list(scenario.calls)
    result = await run(current_worker, output)
    assert result == {
        "status": "blocked",
        "reason": "current_stock_planning_unavailable",
        "live_enabled": False,
    }
    # The immutable, dated research artifact is retained after an ambiguous
    # completion; it is not a successful/current cycle receipt or an order.
    assert len(list(output.glob("*.stock-investment.json"))) == 1
    assert "artifact_file" not in result and scenario.calls == calls
    assert not list(root.glob("*.stock-investment.json"))


@pytest.mark.asyncio
async def test_optional_decision_export_matches_the_verified_full_report(current_worker, tmp_path):
    await acquire(current_worker)
    output, export = tmp_path / "plans", tmp_path / "decisions"
    output.mkdir(mode=0o700)
    export.mkdir(mode=0o700)
    result = await run(current_worker, output, decision_export_dir=export)
    assert result["status"] == "current_stock_plan_published"
    assert result["decision_export_status"] == "published"
    import json

    projection = json.loads((export / "stock-decisions.json").read_text())
    assert projection["report_body_sha256"] == result["artifact_sha256"]
    assert projection["report_evidence_hash"] == result["report_evidence_hash"]
    assert projection["execution_authorized"] is projection["live_authorized"] is False


@pytest.mark.asyncio
async def test_decision_projection_cannot_overwrite_the_acquisition_archive(
    current_worker, tmp_path
):
    await acquire(current_worker)
    _, archive, _, scenario, _, _, _ = current_worker
    output = tmp_path / "plans"
    output.mkdir(mode=0o700)
    calls = list(scenario.calls)
    result = await run(current_worker, output, decision_export_dir=archive)
    assert result == {
        "status": "blocked",
        "reason": "current_stock_planning_unavailable",
        "live_enabled": False,
    }
    assert not list(output.iterdir()) and scenario.calls == calls
    assert not (archive / "stock-decisions.json").exists()
