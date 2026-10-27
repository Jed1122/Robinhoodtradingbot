"""Verified fictional collection through current-policy atomic simulation ownership."""

from datetime import timedelta

import pytest

from tests.integration.execution.test_current_stock_simulation import (
    NOW,
    SIMULATION_ID,
    api,
    current_case,
)
from tests.integration.persistence.test_stock_current_worker_cycle import (
    current_worker as current_worker,
)
from tests.integration.persistence.test_stock_investment_cycle import acquire
from tests.integration.persistence.test_stock_research_worker import CODE


@pytest.mark.asyncio
async def test_manifest_verified_research_to_approved_risk_reservation(current_worker):
    from trading_bot.runtime.stock_investment_inputs import load_current_stock_research_inputs
    from trading_bot.runtime.stock_investment_reports import publish_current_stock_plan

    _, archive, clock, scenario, _, source_owner, loaded = current_worker
    clock.current = NOW - timedelta(hours=1)
    await acquire(current_worker)
    source = await load_current_stock_research_inputs(
        loaded=loaded,
        acquisition_code_hash=CODE,
        factory=source_owner._factory,
        archive_dir=archive,
        clock=clock.now,
    )
    assert source.status == "available" and source.as_of == NOW
    context, grant, selection, paper = current_case(source_inputs=source)
    assert context.plan.source_config_hash == str(loaded.config_hash)
    assert context.plan.rankings.long_term
    assert context.plan.performance_evidence == "unproven_not_a_gate"
    report_root = archive.parent / "current-execution-reports"
    report_root.mkdir(mode=0o700)
    artifact = publish_current_stock_plan(context.plan, output_dir=report_root, archive_dir=archive)
    assert artifact.body_sha256 == context.source_report_body_sha256
    assert (report_root / artifact.file).is_file()
    # The actual source adapter/archive is used above. Planning and simulation
    # must not reopen a provider or mutate collection claims afterwards.
    calls, events = list(scenario.calls), list(scenario.events)
    before_source = await source_owner.snapshot()
    owner = api().StockSimulationJournal(
        source_owner._factory,
        context.execution_config_hash,
        simulation_account_id=SIMULATION_ID,
        policy=context.execution_policy,
        clock=clock,
    )
    await owner.initialize(paper, event_id="archive-to-simulation-genesis")
    receipt = await owner.reserve(context, grant=grant, selection=selection)
    assert receipt.prepared.source_config_hash == str(loaded.config_hash)
    assert receipt.prepared.plan_hash == context.plan.evidence_hash
    assert receipt.prepared.source_report_body_sha256 == context.source_report_body_sha256
    assert (await owner.read_state()).reserved_cash > 0
    assert scenario.calls == calls and scenario.events == events
    assert (await source_owner.snapshot()).state_hash == before_source.state_hash
