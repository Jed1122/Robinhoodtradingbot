"""Private synthetic daily history and explicit execution slots, no real market data."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from functools import lru_cache

from tests.unit.simulation._equity_portfolio_fixtures import scenario
from tests.unit.simulation._equity_replay_fixtures import NOW, STOP, market
from trading_bot.config import AppConfig, LoadedConfig
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.domain import InstrumentId
from trading_bot.market_data.bundle_models import (
    BundleLimits,
    InstrumentMapping,
    SnapshotSettings,
    SourceCapture,
)
from trading_bot.market_data.bundle_normalize import assemble_bundle
from trading_bot.market_data.bundle_verify import verify_bundle
from trading_bot.market_data.recording import canonical_json
from trading_bot.simulation.configured_models import SyntheticBarWindow
from trading_bot.simulation.equity_replay_models import (
    ReplayCandidate,
    ReplayDecision,
    ReplaySession,
)
from trading_bot.simulation.events import EventCursor


def simulation_settings(request, **changes):
    values = request.loaded.config.model_dump()
    values["simulation"].update(changes)
    config = AppConfig.model_validate(values)
    canonical, digest = hash_loaded_config(config, request.loaded.safety_envelope)
    return replace(
        request, loaded=LoadedConfig(config, request.loaded.safety_envelope, canonical, digest)
    )


def cancel_race_scenario():
    base = replay_scenario(commission="0")
    events = []
    for i in range(8):
        at = NOW + timedelta(seconds=i)
        template = base.markets[min(i, 4)]
        price = D(10) if i < 3 else D(8)
        events.append(
            replace(
                template,
                event_id=f"market-{i}",
                cursor=EventCursor(100 + i, at),
                window=SyntheticBarWindow(at, at + timedelta(seconds=1)),
                quote=replace(template.quote, observed_at=at, bid=price, ask=price),
                clock=replace(template.clock, observed_at=at),
                available_quantity={2: D("0.1"), 3: D("0.05"), 4: D("0.05")}.get(i, D(10)),
            )
        )
    return simulation_settings(
        replace(
            base,
            markets=tuple(events),
            end_at=events[-1].cursor.occurred_at,
            decisions=(
                base.decisions[0],
                ReplayDecision("cancel", EventCursor(2, NOW + timedelta(seconds=3))),
                ReplayDecision("exit", EventCursor(3, NOW + timedelta(seconds=5))),
            ),
        ),
        latency_milliseconds=1500,
        cancel_race_probability_pct=D(100),
    )


@lru_cache(maxsize=8)
def replay_scenario(
    *, strategy="equity_momentum", commission="0.1", symbols=("SYNTH",), tight_ranges=False
):
    base = scenario(commission=commission)
    count = base.loaded.config.research.minimum_history_bars
    start = NOW - timedelta(days=count)
    symbol = InstrumentId("SYNTH")
    slots = tuple(
        {"starts_at": start + timedelta(days=i), "ends_at": start + timedelta(days=i + 1)}
        for i in range(count)
    )
    rows = [
        {
            "kind": "baseline",
            "available_at": start,
            "price_basis": None,
            "value": {
                "instrument_id": symbol,
                "coverage_start": start,
                "effective_at": start,
                "announced_at": start,
                "included": True,
            },
        }
    ]
    for i, slot in enumerate(slots):
        close = D(8) + D(max(0, i - count + 21)) / D(10)
        rows.append(
            {
                "kind": "bar",
                "available_at": slot["ends_at"],
                "price_basis": "unadjusted",
                "value": {
                    "instrument_id": symbol,
                    "interval": "one_day",
                    **slot,
                    "open": close,
                    "high": close + (D("0.01") if tight_ranges else D("0.5")),
                    "low": close - (D("0.01") if tight_ranges else D("0.5")),
                    "close": close,
                    "volume": D(100),
                    "source": "replay-fixture",
                    "interpolated": False,
                },
            }
        )
    for kind in ("bar", "membership", "corporate_action"):
        rows.append(
            {
                "kind": "coverage",
                "available_at": start,
                "price_basis": None,
                "value": {
                    "instrument_id": symbol,
                    "record_kind": kind,
                    "interval": "one_day" if kind == "bar" else None,
                    "starts_at": start,
                    "ends_at": STOP,
                    "state": "complete",
                    "expected_slots": slots if kind == "bar" else (),
                },
            }
        )
    sources = []
    for name in symbols:
        renamed = [
            {
                **row,
                "value": {
                    **row["value"],
                    "instrument_id": name,
                    **({"source": name.lower()} if row["kind"] == "bar" else {}),
                },
            }
            for row in rows
        ]
        body = canonical_json({"schema": "synthetic-market-v1", "records": renamed}).encode()
        sources.append(
            SourceCapture(
                name.lower(),
                "synthetic",
                (InstrumentId(name),),
                ("bar", "baseline", "coverage"),
                start,
                STOP,
                STOP,
                None,
                (),
                body,
            )
        )
    limits = BundleLimits(4194304, 2097152, 8388608, 5000, 16)
    bundle = verify_bundle(
        assemble_bundle(
            sources=tuple(sources),
            instruments=tuple(InstrumentMapping(InstrumentId(name), name) for name in symbols),
            limits=limits,
        ),
        limits=limits,
    )
    times = tuple(NOW + timedelta(seconds=i) for i in range(8))
    events = []
    for i, at in enumerate(times[:5]):
        for name in symbols:
            event = market(f"{name}-market-{i}", 100 + len(events), at)
            events.append(
                replace(
                    event,
                    quote=replace(
                        event.quote,
                        instrument_id=InstrumentId(name),
                        bid=D(10) if i < 2 else D(8),
                        ask=D(10) if i < 2 else D(8),
                    ),
                )
            )
    return replace(
        base,
        instruments=tuple(i for i in base.instruments if i.id in symbols),
        bundle=bundle,
        snapshot_settings=SnapshotSettings(base.snapshot_settings.interval, start, count),
        sessions=tuple(
            ReplaySession(InstrumentId(name), SyntheticBarWindow(NOW, STOP), times)
            for name in symbols
        ),
        markets=tuple(events),
        end_at=times[4],
        decisions=(
            ReplayDecision("entry", EventCursor(1, NOW)),
            ReplayDecision("exit", EventCursor(2, times[2])),
        ),
        candidate=ReplayCandidate(
            strategy, 20, 100, 1 if strategy == "equity_relative_strength" else None, D("0.5")
        ),
    )
