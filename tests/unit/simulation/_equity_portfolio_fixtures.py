"""Two-symbol synthetic fixtures with literal quotes and declared future slots."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

from tests.unit.market_data._bundle_fixtures import END, LIMITS, START, fixture_rows
from tests.unit.simulation._equity_replay_fixtures import NOW, STOP, loaded, market, request
from trading_bot.config import AppConfig, LoadedConfig
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.domain import (
    AssetClass,
    ConfigHash,
    DataHash,
    InstrumentId,
    OrderIntent,
    OrderIntentId,
    OrderPurpose,
    OrderType,
    Side,
    TimeInForce,
)
from trading_bot.market_data.bundle_models import InstrumentMapping, SourceCapture
from trading_bot.market_data.bundle_normalize import assemble_bundle
from trading_bot.market_data.bundle_verify import verify_bundle
from trading_bot.market_data.recording import canonical_json
from trading_bot.simulation.configured_models import (
    InstrumentConfiguredOrderRequest,
    SyntheticBarWindow,
)
from trading_bot.simulation.equity_replay_models import ReplaySession


def scenario(*, commission="0", deliveries=True):
    base = loaded()
    values = base.config.model_dump()
    values["costs"].update(equity_commission_usd=D(commission), assumed_slippage_pct=D(0))
    values["simulation"].update(
        rejection_probability_pct=D(0),
        no_fill_probability_pct=D(0),
        full_fill_probability_pct=D(100),
        partial_fill_probability_pct=D(0),
        latency_milliseconds=0,
    )
    config = AppConfig.model_validate(values)
    canonical, digest = hash_loaded_config(config, base.safety_envelope)
    configuration = LoadedConfig(config, base.safety_envelope, canonical, digest)
    instruments = tuple(
        replace(request().instruments[0], id=InstrumentId(name), symbol=name)
        for name in ("SYNTH", "SECOND")
    )
    sources = []
    for instrument in instruments:
        rows = fixture_rows()
        for row in rows:
            row["value"]["instrument_id"] = instrument.id
            if row["kind"] == "bar":
                row["value"]["source"] = instrument.id.lower()
        body = canonical_json({"schema": "synthetic-market-v1", "records": rows}).encode()
        sources.append(
            SourceCapture(
                instrument.id.lower(),
                "synthetic",
                (instrument.id,),
                ("bar", "baseline", "coverage"),
                START,
                END,
                END,
                None,
                (),
                body,
            )
        )
    bundle = verify_bundle(
        assemble_bundle(
            sources=tuple(sources),
            instruments=tuple(InstrumentMapping(i.id, i.symbol) for i in instruments),
            limits=LIMITS,
        ),
        limits=LIMITS,
    )
    times = tuple(NOW + timedelta(seconds=i) for i in (1, 2, 3, 4))
    events = []
    for at in times:
        for instrument in instruments:
            event = market(f"quote-{len(events)}", len(events) + 2, at)
            events.append(
                replace(
                    event,
                    quote=replace(event.quote, instrument_id=instrument.id, ask=D(10)),
                    available_quantity=D(2),
                )
            )
    return request(
        loaded=configuration,
        instruments=instruments,
        bundle=bundle,
        sessions=tuple(
            ReplaySession(i.id, SyntheticBarWindow(NOW, STOP), times) for i in instruments
        ),
        markets=tuple(events) if deliveries else (),
    )


def intent(
    req, *, identifier="buy-1", instrument="SYNTH", quantity="6", side=Side.BUY, at=NOW, **changes
):
    value = OrderIntent(
        OrderIntentId(identifier),
        req.account_id,
        InstrumentId(instrument),
        AssetClass.EQUITY,
        side,
        OrderPurpose.ENTRY if side is Side.BUY else OrderPurpose.STRATEGY_EXIT,
        OrderType.LIMIT,
        TimeInForce.GOOD_FOR_DAY,
        D(quantity),
        D(10),
        None,
        at,
        STOP,
        "synthetic-policy-v1",
        ConfigHash(req.loaded.config_hash),
        DataHash("d" * 64),
        "synthetic-exit-v1" if side is Side.BUY else None,
    )
    return replace(value, **changes)


def configured(book, req, order_id, *, events=None):
    initial = book.initial_order(order_id)
    at = initial.submitted.occurred_at
    return InstrumentConfiguredOrderRequest(
        initial=initial,
        simulation=req.loaded.config.simulation,
        costs=req.loaded.config.costs,
        seed=req.seed,
        submission_window=SyntheticBarWindow(at, at + timedelta(microseconds=1)),
        events=tuple(
            e
            for e in req.markets
            if e.quote.instrument_id == initial.order.instrument_id and e.cursor.occurred_at > at
        )
        if events is None
        else events,
        end_at=req.end_at,
        expires_at=STOP,
        instrument=next(i for i in req.instruments if i.id == initial.order.instrument_id),
    )
