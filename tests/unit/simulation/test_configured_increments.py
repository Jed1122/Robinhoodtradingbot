"""Explicit equity metadata rounds fills adversely without changing legacy scenarios."""

from dataclasses import fields, replace
from decimal import Decimal as D

import pytest

from tests.unit.risk.test_sizing import instrument
from trading_bot.domain import AssetClass, Side, TimeInForce
from trading_bot.simulation import configured_models
from trading_bot.simulation.configured import simulate_configured_order
from trading_bot.simulation.configured_models import ConfiguredValidationError

from ._configured_fixtures import at, cost_settings, market, request, settings
from ._lifecycle_fixtures import make_request


def equity_request(*, events=None, initial=None, metadata=None, **changes):
    source = make_request() if initial is None else initial
    initial = replace(
        source,
        position=replace(source.position, asset_class=AssetClass.EQUITY),
        order=replace(source.order, time_in_force=TimeInForce.GOOD_FOR_DAY),
    )
    if events is None:
        events = (market(available_quantity=D("0.25")),)
    events = tuple(
        replace(event, clock=replace(event.clock, asset_class=AssetClass.EQUITY))
        for event in events
    )
    base = request(initial=initial, events=events, expires_at=at(10000), **changes)
    if metadata is None:
        metadata = instrument(
            id=initial.order.instrument_id,
            asset_class=AssetClass.EQUITY,
            observed_at=at(0),
            quantity_increment=D("0.1"),
        )
    constructor = getattr(configured_models, "InstrumentConfiguredOrderRequest", None)
    assert constructor is not None, "versioned instrument-aware request is missing"
    return constructor(
        **{field.name: getattr(base, field.name) for field in fields(base)}, instrument=metadata
    )


def test_equity_lot_floor_and_adverse_tick_use_existing_fee_accounting():
    req = equity_request(costs=cost_settings(equity_commission_usd=D("0.10")))
    result = simulate_configured_order(req)
    snapshot = result.lifecycle.snapshot
    assert snapshot.position.quantity == D("0.2")
    assert snapshot.position.average_price == D("99.25")
    assert snapshot.cash == D("980.05")  # 1000 - 0.2 * 99.25 - 0.10
    assert snapshot.fees == D("0.10")
    assert result.events[-2].fill.quantity == D("0.2")
    assert result.assumptions_validated is False
    assert result.evidence_promotable is False


def test_sub_lot_liquidity_is_no_fill_and_charges_no_commission():
    result = simulate_configured_order(
        equity_request(
            events=(market(available_quantity=D("0.09")),),
            costs=cost_settings(equity_commission_usd=D(1)),
        )
    )
    assert result.lifecycle.snapshot.position.quantity == D(0)
    assert result.lifecycle.snapshot.cash == D(1000)
    assert result.lifecycle.snapshot.fees == D(0)
    assert result.decisions[1].reason.value == "no_fill"


def test_partial_outcome_rounds_down_not_up_or_to_nearest():
    partial = settings(
        full_fill_probability_pct=D(0),
        partial_fill_probability_pct=D(100),
        partial_fill_min_pct=D(25),
        partial_fill_max_pct=D(25),
    )
    result = simulate_configured_order(equity_request(events=(market(),), simulation=partial))
    assert result.lifecycle.snapshot.position.quantity == D("0.2")
    assert result.decisions[1].partial_percentage == D(25)


def test_sub_lot_partial_keeps_the_sampled_percentage_in_the_audit():
    partial = settings(
        full_fill_probability_pct=D(0),
        partial_fill_probability_pct=D(100),
        partial_fill_min_pct=D(10),
        partial_fill_max_pct=D(10),
    )
    source = make_request(quantity="0.5")
    result = simulate_configured_order(equity_request(initial=source, simulation=partial))
    assert result.lifecycle.snapshot.position.quantity == D(0)
    assert result.lifecycle.snapshot.fees == D(0)
    assert result.decisions[1].reason.value == "no_fill"
    assert result.decisions[1].selected_outcome.value == "partial"
    assert result.decisions[1].partial_percentage == D(10)


def test_sell_price_rounds_down_and_never_increases_shares():
    source = make_request(side=Side.SELL, position_quantity="1", average_price="99")
    event = market()
    event = replace(event, quote=replace(event.quote, bid=D(101), ask=D(102)))
    result = simulate_configured_order(equity_request(initial=source, events=(event,)))
    assert result.lifecycle.snapshot.position.quantity == D(0)
    assert result.lifecycle.snapshot.cash == D("1100.74")
    assert result.events[-1].fill.price == D("100.74")


@pytest.mark.parametrize("side,bid,ask", [(Side.BUY, "99.75", "100"), (Side.SELL, "100", "100.25")])
def test_cost_adjusted_executable_price_cannot_cross_the_order_limit(side, bid, ask):
    source = make_request(side=side, position_quantity="1", average_price="99")
    event = market()
    event = replace(event, quote=replace(event.quote, bid=D(bid), ask=D(ask)))
    result = simulate_configured_order(equity_request(initial=source, events=(event,)))
    assert result.lifecycle.snapshot.order.filled_quantity == D(0)
    assert result.lifecycle.snapshot.cash == D(1000)
    assert result.decisions[1].reason.value == "limit_price_not_executable"


@pytest.mark.parametrize(
    "change",
    [
        {"id": "different"},
        {"asset_class": AssetClass.CRYPTO},
        {"observed_at": at(1)},
        {"quantity_increment": D("0.3")},
        {"price_increment": D("0.3")},
        {"minimum_quantity": D(2)},
        {"minimum_notional": D(101)},
        {"maximum_quantity": D("0.5")},
    ],
)
def test_metadata_mismatch_or_unrepresentable_initial_order_denies(change):
    metadata = instrument(
        id=make_request().order.instrument_id,
        asset_class=AssetClass.EQUITY,
        observed_at=at(0),
        quantity_increment=D("0.1"),
        **{},
    )
    with pytest.raises(ConfiguredValidationError):
        equity_request(metadata=replace(metadata, **change))


def test_new_metadata_semantics_are_identity_bound_but_legacy_is_unchanged():
    req = equity_request()
    assert req.execution_version == "synthetic-equity-increments-v1"
    altered = replace(req, instrument=replace(req.instrument, quantity_increment=D("0.01")))
    constrained = simulate_configured_order(req)
    finer = simulate_configured_order(altered)
    assert constrained.settings_hash != finer.settings_hash
    legacy = configured_models.ConfiguredOrderRequest(
        **{
            field.name: getattr(req, field.name)
            for field in fields(configured_models.ConfiguredOrderRequest)
        }
    )
    legacy_result = simulate_configured_order(legacy)
    assert legacy_result.lifecycle.snapshot.position.quantity == D("0.25")
    assert legacy_result.lifecycle.snapshot.position.average_price == D("99.2475")
