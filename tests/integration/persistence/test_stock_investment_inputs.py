"""Current research inputs from real fictional archive/ledger; no SDK or account calls."""

import importlib
import json
from datetime import timedelta
from decimal import localcontext

import pytest

from tests.integration.persistence.test_stock_current_worker_cycle import (
    current_worker as current_worker,
)
from tests.integration.persistence.test_stock_research_worker import CODE
from tests.integration.persistence.test_stock_research_worker import worker as worker


def api():
    try:
        return importlib.import_module("trading_bot.runtime.stock_investment_inputs")
    except ModuleNotFoundError:
        pytest.fail("current investment input loader is missing")


async def load(data, **kwargs):
    _, root, clock, _, _, owner, loaded = data
    return await api().load_current_stock_research_inputs(
        loaded=loaded,
        acquisition_code_hash=CODE,
        factory=owner._factory,
        archive_dir=root,
        clock=clock.now,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_empty_current_research_is_explicit_without_connecting_or_charging(worker):
    _, _, _, scenario, _, owner, _ = worker
    before = await owner.snapshot()
    result = await load(worker)
    assert result.status == "needs_research"
    assert result.needs == ("discovery_missing", "enrichment_missing")
    assert result.discovery_json is result.enrichment_json is None
    assert result.scanner_rows == ()
    assert scenario.calls == scenario.events == []
    assert (await owner.snapshot()).state_hash == before.state_hash
    assert not result.investment_eligible and not result.execution_authorized


@pytest.mark.asyncio
async def test_rehashes_complete_heads_and_preserves_identity_values_and_old_flags(worker):
    _, _, clock, scenario, cycle, owner, _ = worker
    assert (await cycle())["phase"] == "discovery"
    first = await load(worker)
    assert first.status == "needs_research" and first.needs == (
        "enrichment_missing",
        "discovery_dossier_missing:ALFA",
    )
    (row,) = first.scanner_rows
    assert row.symbol == "ALFA" and row.instrument_id == "fictional-ALFA"
    assert json.loads(row.native_row_json)["columns"]["Last"] == "100"
    clock.current += timedelta(hours=1)
    assert (await cycle())["phase"] == "enrichment"
    before = await owner.snapshot()
    calls, events = list(scenario.calls), list(scenario.events)
    result = await load(worker)
    assert result.status == "available" and result.needs == ()
    assert result.source_config_hash == str(before.claims[-1].config_hash)
    assert result.acquisition_code_hashes == (str(CODE),)
    assert result.source_state_hash == before.state_hash
    assert result.as_of == clock.now() and len(result.evidence_hash) == 64
    assert result.discovery_manifest_hash == before.discovery_head.manifest_sha256
    assert result.enrichment_manifest_hash == before.enrichment_head.manifest_sha256
    discovery, enrichment = json.loads(result.discovery_json), json.loads(result.enrichment_json)
    assert discovery["investment_eligible"] is enrichment["investment_eligible"] is False
    assert enrichment["dossiers"][0]["fundamentals"]["receipt"]["received_at"]
    assert result.native_http_wire_receipt is result.execution_authorized is False
    assert scenario.calls == calls and scenario.events == events
    assert (await owner.snapshot()).state_hash == before.state_hash


@pytest.mark.asyncio
async def test_latest_head_expiry_never_becomes_fresh_from_read_time(worker):
    _, _, clock, scenario, cycle, _, _ = worker
    await cycle()
    clock.current += timedelta(hours=1)
    await cycle()
    clock.current += timedelta(hours=3)
    calls = list(scenario.calls)
    result = await load(worker)
    assert result.status == "needs_research"
    assert result.needs == ("discovery_stale", "enrichment_stale")
    assert json.loads(result.discovery_json)["as_of"] != result.as_of.isoformat()
    assert scenario.calls == calls


@pytest.mark.asyncio
async def test_held_stock_outside_enrichment_is_a_visible_gap(worker):
    _, _, clock, _, cycle, _, _ = worker
    await cycle()
    clock.current += timedelta(hours=1)
    await cycle()
    result = await load(worker, held_symbols=("BETA", "ALFA"))
    assert result.status == "needs_research"
    assert result.needs == ("held_evidence_missing:BETA", "held_scanner_identity_missing:BETA")
    assert result.held_symbols == ("ALFA", "BETA")


@pytest.mark.asyncio
@pytest.mark.parametrize("artifact", ("observation", "report"))
async def test_changed_committed_source_fails_without_empty_success_or_new_calls(worker, artifact):
    _, root, _, scenario, cycle, _, _ = worker
    await cycle()
    file = next(
        root.glob(
            "*.stock-observation.json" if artifact == "observation" else "*.stock-screen.json"
        )
    )
    file.write_bytes(file.read_bytes() + b" ")
    calls = list(scenario.calls)
    with pytest.raises(ValueError, match="current_stock_research_unavailable"):
        await load(worker)
    assert scenario.calls == calls


@pytest.mark.asyncio
async def test_clock_rollback_during_source_reconstruction_is_denied(worker):
    _, root, clock, _, cycle, owner, loaded = worker
    await cycle()
    now = clock.now()
    times = iter((now, now - timedelta(seconds=1)))
    with pytest.raises(ValueError, match="current_stock_research_unavailable"):
        await api().load_current_stock_research_inputs(
            loaded=loaded,
            acquisition_code_hash=CODE,
            factory=owner._factory,
            archive_dir=root,
            clock=lambda: next(times),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("symbols", (["ALFA"], ("ALFA", "ALFA"), ("bad symbol",)))
async def test_invalid_watch_input_denies_before_any_source_or_connection(worker, symbols):
    _, _, _, scenario, _, _, _ = worker
    with pytest.raises(ValueError, match="current_stock_research_unavailable"):
        await load(worker, held_symbols=symbols)
    assert scenario.calls == scenario.events == []


@pytest.mark.asyncio
async def test_retained_reciprocal_metrics_recompute_under_the_original_screen_context(worker):
    _, _, _, scenario, cycle, _, _ = worker
    original = scenario.call_tool

    async def recurring_factor(tool, arguments):
        result = await original(tool, arguments)
        if tool == "preview_scan":
            result.structured_content["data"]["result"]["results"][0]["columns"]["P/E"] = "3"
        return result

    scenario.call_tool = recurring_factor
    await cycle()
    expected = await load(worker)
    with localcontext() as context:
        context.prec = 2
        actual = await load(worker)
    assert actual.discovery_json == expected.discovery_json
    assert actual.evidence_hash == expected.evidence_hash


@pytest.mark.asyncio
async def test_new_discovery_without_matching_dossiers_requests_research(worker):
    _, _, clock, scenario, cycle, _, _ = worker
    await cycle()
    clock.current += timedelta(hours=1)
    await cycle()
    scenario.symbol = "BETA"
    clock.current += timedelta(hours=1)
    await cycle()
    calls = list(scenario.calls)
    result = await load(worker)
    assert result.status == "needs_research"
    assert "discovery_dossier_missing:BETA" in result.needs
    assert scenario.calls == calls


@pytest.mark.asyncio
async def test_held_dossier_without_current_scanner_identity_is_a_visible_gap(worker):
    _, _, clock, scenario, cycle, _, _ = worker
    await cycle()
    clock.current += timedelta(hours=1)
    await cycle()
    scenario.symbol = "BETA"
    clock.current += timedelta(hours=1)
    await cycle()
    result = await load(worker, held_symbols=("ALFA",))
    assert result.status == "needs_research"
    assert "held_scanner_identity_missing:ALFA" in result.needs
    assert "held_evidence_missing:ALFA" not in result.needs


@pytest.mark.asyncio
async def test_unchanged_cohort_can_reuse_fresh_earlier_enrichment(worker):
    _, _, clock, _, cycle, owner, _ = worker
    await cycle()
    clock.current += timedelta(hours=1)
    await cycle()
    previous = (await owner.snapshot()).enrichment_head
    clock.current += timedelta(hours=1)
    assert (await cycle())["phase"] == "discovery"
    result = await load(worker)
    assert result.status == "available" and result.needs == ()
    assert result.enrichment_report_hash == previous.report_sha256


def scanner_observation(*, at, digest="a", symbol="ALFA", instrument="fictional-ALFA", last="100"):
    return {
        "tool": "preview_scan",
        "received_at": at.isoformat(),
        "observation_sha256": digest * 64,
        "payload": {
            "data": {
                "result": {
                    "results": [
                        {"ticker": symbol, "instrument_id": instrument, "columns": {"Last": last}}
                    ]
                }
            }
        },
    }


def scanner_rows(observations, now, wanted=("ALFA",)):
    helper = getattr(api(), "_current_scanner_rows", None)
    assert callable(helper), "verified scanner source merger is missing"
    return helper(tuple(observations), wanted=set(wanted), cutoff=now)


def test_scanner_rows_take_newest_receipt_without_preferring_economic_values():
    from tests.integration.persistence.test_stock_research_worker import NOW

    old = scanner_observation(at=NOW, last="100")
    latest = scanner_observation(at=NOW + timedelta(minutes=1), digest="b", last="2")
    first = scanner_rows((old, latest), NOW + timedelta(minutes=2))
    assert first == scanner_rows((latest, old), NOW + timedelta(minutes=2))
    assert first[0].observation_hash == "b" * 64
    assert json.loads(first[0].native_row_json)["columns"]["Last"] == "2"
    assert first[0].received_at == NOW + timedelta(minutes=1) and first[0].record_index == 0


@pytest.mark.parametrize("changed", ("instrument", "same_clock_row", "symbol"))
def test_scanner_identity_and_same_clock_conflicts_reject(changed):
    from tests.integration.persistence.test_stock_research_worker import NOW

    old = scanner_observation(at=NOW)
    options = dict(at=NOW + timedelta(minutes=1), digest="b")
    if changed == "instrument":
        options["instrument"] = "contradictory-id"
    elif changed == "same_clock_row":
        options.update(at=NOW, last="101")
    else:
        options["symbol"] = "BETA"
    with pytest.raises(ValueError):
        scanner_rows(
            (old, scanner_observation(**options)), NOW + timedelta(minutes=2), ("ALFA", "BETA")
        )


def test_identical_same_clock_rows_choose_stable_original_reference():
    from tests.integration.persistence.test_stock_research_worker import NOW

    a, b = scanner_observation(at=NOW), scanner_observation(at=NOW, digest="b")
    selected = scanner_rows((b, a), NOW)
    assert selected == scanner_rows((a, b), NOW)
    assert selected[0].observation_hash == "a" * 64


def test_older_same_clock_conflict_is_not_hidden_by_a_newer_row():
    from tests.integration.persistence.test_stock_research_worker import NOW

    old = scanner_observation(at=NOW)
    latest = scanner_observation(at=NOW + timedelta(minutes=1), digest="b", last="2")
    conflict = scanner_observation(at=NOW, digest="c", last="101")
    with pytest.raises(ValueError):
        scanner_rows((old, latest, conflict), NOW + timedelta(minutes=2))


def test_future_scanner_receipt_cannot_become_current_identity():
    from tests.integration.persistence.test_stock_research_worker import NOW

    with pytest.raises(ValueError):
        scanner_rows((scanner_observation(at=NOW + timedelta(seconds=1)),), NOW)


@pytest.mark.asyncio
@pytest.mark.parametrize("held", (False, True))
async def test_current_profile_reopens_original_targeted_scanner_rows(
    current_worker, held, monkeypatch
):
    from trading_bot.runtime.stock_archive import read_stock_observations

    module, root, clock, scenario, cycle, owner, _ = current_worker
    await cycle()
    clock.current += timedelta(hours=1)
    original = scenario.call_tool

    async def changed_target(tool, arguments):
        result = await original(tool, arguments)
        if tool == "preview_scan":
            result.structured_content["data"]["result"]["results"][0]["columns"]["Last"] = "99"
        return result

    monkeypatch.setattr(scenario, "call_tool", changed_target)
    options = {}
    symbol = "ALFA"
    if held:
        symbol = "HELD"
        options["watch"] = module.StockResearchWatch(
            held_symbols=(symbol,),
            watch_symbols=(),
            as_of=clock.current,
            expires_at=clock.current + timedelta(hours=1),
            source_sha256="a" * 64,
        )
    assert (await cycle(**options))["phase"] == "enrichment"
    before = await owner.snapshot()
    calls, events = list(scenario.calls), list(scenario.events)
    result = await load(current_worker, held_symbols=(symbol,) if held else ())
    assert (await owner.snapshot()).state_hash == before.state_hash
    assert scenario.calls == calls and scenario.events == events
    selected = next(row for row in result.scanner_rows if row.symbol == symbol)
    observations = read_stock_observations(
        root, before.enrichment_head.manifest_sha256 + ".stock-capture.json"
    )
    source = next(row for row in observations if row["tool"] == "preview_scan")
    assert selected.observation_hash == source["observation_sha256"]
    assert selected.record_index == 0 and selected.received_at.isoformat() == source["received_at"]
    assert json.loads(selected.native_row_json)["columns"]["Last"] == "99"
    assert selected.received_at == clock.current
    assert "held_scanner_identity_missing:" + symbol not in result.needs
    assert "held_evidence_missing:" + symbol not in result.needs
    if held:
        assert result.status == "needs_research" and result.needs == (
            "discovery_dossier_missing:ALFA",
        )
    else:
        assert result.status == "available" and result.needs == ()
    assert (
        result.native_http_wire_receipt
        is result.investment_eligible
        is result.execution_authorized
        is result.live_authorized
        is False
    )
