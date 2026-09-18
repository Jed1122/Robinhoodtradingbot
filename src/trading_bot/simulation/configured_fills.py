"""Configured synthetic outcomes; legacy FillModel semantics stay untouched."""

import random
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction

from trading_bot.config.models import CostSettings, SimulationSettings
from trading_bot.domain import AssetClass, DataHash, Side
from trading_bot.domain.decimal_utils import quantize_down, require_bounded_decimal
from trading_bot.simulation.configured_codec import keyed_rng
from trading_bot.simulation.configured_models import (
    ConfiguredErrorReason,
    ConfiguredOrderRequest,
    InstrumentConfiguredOrderRequest,
    SyntheticMarketEvent,
    checked,
    deny,
)
from trading_bot.simulation.costs import SimulatedCosts, execution_fee, execution_price
from trading_bot.simulation.fills import PlannedFill


class SimulatedOutcome(StrEnum):
    NO_FILL = "no_fill"
    FULL = "full"
    PARTIAL = "partial"


@dataclass(frozen=True, slots=True)
class ConfiguredFillPlan:
    outcome: SimulatedOutcome
    percentage: Decimal | None
    fill: PlannedFill | None


def chance(percent: Decimal, rng: random.Random) -> bool:
    return Fraction(rng.getrandbits(53), 2**53) < Fraction(percent) / 100


def select_outcome(settings: SimulationSettings, rng: random.Random) -> SimulatedOutcome:
    with checked(ConfiguredErrorReason.ARITHMETIC):
        accepted = Fraction(100) - Fraction(settings.rejection_probability_pct)
        if accepted <= 0:
            deny(ConfiguredErrorReason.UNSUPPORTED)
        draw = Fraction(rng.getrandbits(53), 2**53)
        no_fill = Fraction(settings.no_fill_probability_pct) / accepted
        full = Fraction(settings.full_fill_probability_pct) / accepted
        if draw < no_fill:
            return SimulatedOutcome.NO_FILL
        if draw < no_fill + full:
            return SimulatedOutcome.FULL
        return SimulatedOutcome.PARTIAL


def partial_percentage(settings: SimulationSettings, rng: random.Random) -> Decimal:
    with checked(ConfiguredErrorReason.ARITHMETIC):
        return settings.partial_fill_min_pct + (
            (settings.partial_fill_max_pct - settings.partial_fill_min_pct)
            * Decimal(rng.randrange(10001))
            / Decimal(10000)
        )


def costs_for(asset_class: AssetClass, settings: CostSettings) -> SimulatedCosts:
    if asset_class is AssetClass.EQUITY:
        return SimulatedCosts(
            settings.assumed_slippage_pct, Decimal(0), settings.equity_commission_usd
        )
    if asset_class is AssetClass.CRYPTO:
        return SimulatedCosts(settings.assumed_slippage_pct, settings.crypto_fee_pct, Decimal(0))
    deny(ConfiguredErrorReason.UNSUPPORTED)


def plan_fill(
    request: ConfiguredOrderRequest,
    event: SyntheticMarketEvent,
    remaining: Decimal,
    base_hash: DataHash,
    event_hash: DataHash,
) -> ConfiguredFillPlan:
    """Called only after scheduler guards; no accounting or risk approval occurs here."""
    with checked(ConfiguredErrorReason.ARITHMETIC):
        outcome = select_outcome(request.simulation, keyed_rng(base_hash, event_hash, "outcome"))
        if outcome is SimulatedOutcome.NO_FILL:
            return ConfiguredFillPlan(outcome, None, None)
        percentage = None
        target = remaining
        if outcome is SimulatedOutcome.PARTIAL:
            percentage = partial_percentage(
                request.simulation, keyed_rng(base_hash, event_hash, "partial_size")
            )
            target = remaining * percentage / Decimal(100)
        quantity = min(target, event.available_quantity)
        if type(request) is InstrumentConfiguredOrderRequest:
            quantity = quantize_down(quantity, request.instrument.quantity_increment)
            if quantity == 0:
                return ConfiguredFillPlan(outcome, percentage, None)
        costs = costs_for(request.initial.position.asset_class, request.costs)
        price = price_for_request(request, event)
        return ConfiguredFillPlan(
            outcome, percentage, PlannedFill(quantity, price, execution_fee(quantity, price, costs))
        )


def price_for_request(request: ConfiguredOrderRequest, event: SyntheticMarketEvent) -> Decimal:
    """Share adverse tick rounding between the execution guard and fill calculation."""
    with checked(ConfiguredErrorReason.ARITHMETIC):
        side = request.initial.order.side
        price = execution_price(
            side=side,
            bid=event.quote.bid,
            ask=event.quote.ask,
            costs=costs_for(request.initial.position.asset_class, request.costs),
        )
        if type(request) is InstrumentConfiguredOrderRequest:
            tick = request.instrument.price_increment
            rounded = quantize_down(price, tick)
            if side is Side.BUY and rounded < price:
                rounded += tick
            price = require_bounded_decimal(rounded, "rounded_price", positive=True)
        return price
