from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

from trading_bot.config.models import CostSettings, SimulationSettings
from trading_bot.domain import AssetClass, DataHash, MarketClock, Quote, TimestampSource
from trading_bot.simulation.configured_models import (
    ConfiguredOrderRequest,
    SyntheticBarWindow,
    SyntheticCancelRequest,
    SyntheticMarketEvent,
)
from trading_bot.simulation.events import EventCursor

from ._lifecycle_fixtures import INSTRUMENT, ORIGIN, make_request


def settings(**changes):
    values = dict(
        rejection_probability_pct=D(0),
        no_fill_probability_pct=D(0),
        full_fill_probability_pct=D(100),
        partial_fill_probability_pct=D(0),
        partial_fill_min_pct=D(10),
        partial_fill_max_pct=D(50),
        latency_milliseconds=500,
        cancel_race_probability_pct=D(0),
        same_bar_fills_allowed=False,
        market_session_rules_enforced=True,
        assumptions_validated=False,
        evidence_promotable=False,
    )
    values.update(changes)
    return SimulationSettings.model_validate(values)


def cost_settings(**changes):
    values = dict(
        assumed_equity_spread_pct=D("0.35"),
        assumed_crypto_spread_pct=D("0.60"),
        assumed_prediction_spread_pct=D(1),
        assumed_slippage_pct=D("0.25"),
        max_slippage_pct=D("0.50"),
        equity_commission_usd=D(0),
        crypto_fee_pct=D("0.50"),
        prediction_fee_pct=D(1),
        stressed_cost_multiplier=D(2),
        stressed_fill_probability_pct=D(25),
    )
    values.update(changes)
    return CostSettings.model_validate(values)


def at(milliseconds):
    return ORIGIN + timedelta(milliseconds=milliseconds)


def window(start=0, end=1000):
    return SyntheticBarWindow(at(start), at(end))


def market(event_id="quote", sequence=1, milliseconds=1000, **changes):
    timestamp = at(milliseconds)
    source = next(iter(TimestampSource))
    event = SyntheticMarketEvent(
        event_id,
        EventCursor(sequence, timestamp),
        window(milliseconds // 1000 * 1000, (milliseconds // 1000 + 1) * 1000),
        Quote(
            INSTRUMENT,
            timestamp,
            D(98),
            D(99),
            None,
            "synthetic-configured-order-v1",
            DataHash("d" * 64),
            True,
            source,
        ),
        MarketClock(
            AssetClass.CRYPTO, "synthetic-venue", timestamp, True, False, False, False, None, None
        ),
        D(1),
    )
    return replace(event, **changes)


def cancel(event_id="cancel", sequence=1, milliseconds=1000):
    return SyntheticCancelRequest(event_id, EventCursor(sequence, at(milliseconds)))


def request(events=(), **changes):
    values = dict(
        initial=make_request(),
        simulation=settings(),
        costs=cost_settings(),
        seed=7,
        submission_window=window(),
        events=events,
        end_at=at(10000),
    )
    values.update(changes)
    return ConfiguredOrderRequest(**values)
