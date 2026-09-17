from dataclasses import replace
from decimal import Decimal

import pytest

from tests.integration.simulation.test_decision_cycle import request
from tests.unit.market_data._bundle_fixtures import END, ID, LIMITS, START, fixture_package
from tests.unit.research.test_validation import report
from trading_bot.app import DecisionCycleService
from trading_bot.domain import BarInterval, DataHash
from trading_bot.market_data.bundle_codec import decode_envelope
from trading_bot.market_data.bundle_models import BundleError, SnapshotSettings
from trading_bot.market_data.bundle_verify import verify_bundle
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.market_data.snapshot_loader import BundleSnapshotLoader
from trading_bot.portfolio import TargetPortfolio
from trading_bot.research.report import render_json
from trading_bot.strategies import FeaturePipeline, FeatureSnapshot


class BundleFeatures:
    def __init__(self):
        self.pipeline = FeaturePipeline(short_window=2, long_window=3)
        self.calls = 0

    def compute(self, market, *, as_of):
        self.calls += 1
        vectors = tuple(self.pipeline.compute(history, as_of=as_of) for history in market.histories)
        return FeatureSnapshot(as_of, vectors, content_hash({"as_of": as_of, "vectors": vectors}))


class NoExecution:
    async def execute(self, intent):
        raise AssertionError("synthetic data integration must not create an execution intent")


class NoPlanner:
    def plan(self, target, context):
        return ()


class EmptyPortfolio:
    def construct(
        self, decisions, snapshot, *, as_of, config_hash, exposure_multiplier, exit_policy
    ):
        assert decisions == ()
        return TargetPortfolio(as_of, (), snapshot.cash, config_hash, DataHash("d" * 64))


class MemoryJournal:
    def __init__(self):
        self.payloads = []

    async def finalize(self, payload):
        self.payloads.append(payload)
        return ("synthetic-bundle-cycle",)


def cycle(*, package=None, minimum_bars=2):
    original = request()
    portfolio = replace(original.portfolio, observed_at=END)
    cycle_request = replace(
        original,
        universe=(ID,),
        as_of=END,
        portfolio=portfolio,
        intent_context=replace(original.intent_context, portfolio=portfolio),
    )
    loader = BundleSnapshotLoader(
        verify_bundle(fixture_package() if package is None else package, limits=LIMITS),
        settings=SnapshotSettings(BarInterval.ONE_DAY, START, minimum_bars),
    )
    journal, features = MemoryJournal(), BundleFeatures()
    service = DecisionCycleService(
        snapshot_loader=loader,
        features=features,
        strategies=(),
        portfolio=EmptyPortfolio(),
        intent_planner=NoPlanner(),
        execution=NoExecution(),
        journal=journal,
    )
    return service, cycle_request, journal, features


@pytest.mark.asyncio
async def test_real_loader_and_features_feed_existing_cycle_without_execution():
    service, cycle_request, journal, features = cycle()
    result = await service.run_cycle(cycle_request)
    again = await service.run_cycle(cycle_request)
    assert len(result.market.histories) == 1
    assert tuple(bar.close for bar in result.market.histories[0].bars) == (Decimal("10"),) * 2
    assert dict(result.features.vectors[0].values)["spread_pct"] is None
    assert dict(result.features.vectors[0].values)["latest_close"] == Decimal("10")
    assert result.decisions == result.intents == result.order_outcomes == ()
    assert result.audit_event_ids == ("synthetic-bundle-cycle",)
    assert journal.payloads[0]["market_hash"] == result.market.data_hash
    assert features.calls == 2
    assert result.result_hash == again.result_hash


def test_tampered_bundle_is_rejected_before_cycle_construction():
    package = replace(fixture_package(), envelope_bytes=b"{}")
    with pytest.raises(BundleError):
        cycle(package=package)


@pytest.mark.asyncio
async def test_query_denial_precedes_features_and_journal():
    service, cycle_request, journal, features = cycle(minimum_bars=3)
    with pytest.raises(BundleError, match=r"^snapshot_history_insufficient$"):
        await service.run_cycle(cycle_request)
    assert features.calls == 0
    assert journal.payloads == []


def test_existing_report_identity_is_unchanged():
    value = report()  # Construction only: never accept or persist this compatibility fixture.
    assert value.report_hash == "2a63011d5965cdd6826116f3ca2ee1532d2c98058c480b3c45256d0dd3d54781"
    assert value.run.data_manifest.manifest_hash == (
        "08ecc519c3085798817cf57cb60f0bd7e1c1df8bdbcade4ae512d5d3cd5c451d"
    )
    assert content_hash(render_json(value)) == (
        "6e71bb1d6d1fb30977851d5f78cbae488767e44c09f26620069075598ef3d6ba"
    )
    with pytest.raises(BundleError, match=r"^bundle_schema_invalid$"):
        decode_envelope(canonical_json(value.run.data_manifest).encode(), limits=LIMITS)
