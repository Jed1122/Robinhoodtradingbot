"""Synthetic value fixtures only; no account, source transport, or runtime state."""

from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

from tests.unit.market_data._bundle_fixtures import END, ID, LIMITS, START, fixture_package
from tests.unit.risk.test_sizing import instrument
from trading_bot.config import load_config
from trading_bot.domain import AssetClass, DataHash, MarketClock, Quote, TimestampSource
from trading_bot.market_data.bundle_models import SnapshotSettings
from trading_bot.market_data.bundle_verify import verify_bundle
from trading_bot.simulation.configured_models import SyntheticBarWindow, SyntheticMarketEvent
from trading_bot.simulation.equity_replay_models import (
    EquityStrategyReplayRequest,
    ReplayCandidate,
    ReplayDecision,
    ReplaySession,
)
from trading_bot.simulation.events import EventCursor

ROOT = Path(__file__).parents[3]
NOW = END
LATER = NOW + timedelta(seconds=1)
STOP = NOW + timedelta(hours=1)


def loaded(mode="simulation"):
    return load_config(
        ROOT / "configs/base.yaml",
        ROOT / f"configs/{mode}.yaml",
        ROOT / "configs/safety-envelope.yaml",
        {},
    )


def market(event_id="quote-1", sequence=2, at=LATER):
    return SyntheticMarketEvent(
        event_id,
        EventCursor(sequence, at),
        SyntheticBarWindow(at, at + timedelta(seconds=1)),
        Quote(
            ID,
            at,
            D(10),
            D("10.01"),
            None,
            "synthetic-configured-order-v1",
            DataHash("d" * 64),
            True,
            TimestampSource.SIMULATED,
        ),
        MarketClock(AssetClass.EQUITY, "synthetic", at, True, False, False, False, None, STOP),
        D(10),
    )


def request(**changes):
    configuration = loaded()
    values = dict(
        namespace="synthetic:equity-fixture",
        loaded=configuration,
        seed=7,
        candidate=ReplayCandidate("equity_momentum", 20, 100, None, D("0.5")),
        bundle=verify_bundle(fixture_package(), limits=LIMITS),
        snapshot_settings=SnapshotSettings(
            configuration.config.equity_strategies.bar_interval,
            START,
            configuration.config.research.minimum_history_bars,
        ),
        instruments=(
            instrument(id=ID, symbol="SYNTH", asset_class=AssetClass.EQUITY, observed_at=NOW),
        ),
        sessions=(ReplaySession(ID, SyntheticBarWindow(NOW, STOP), (LATER,)),),
        decisions=(ReplayDecision("decision-1", EventCursor(1, NOW)),),
        markets=(market(),),
        starts_at=NOW,
        end_at=STOP,
        initial_cash=D(100),
    )
    values.update(changes)
    return EquityStrategyReplayRequest(**values)
