import random
from dataclasses import replace
from decimal import Decimal as D
from decimal import Inexact, localcontext

import pytest

from trading_bot.domain import AssetClass, DataHash, Side
from trading_bot.simulation.configured_codec import keyed_rng
from trading_bot.simulation.configured_fills import (
    SimulatedOutcome,
    chance,
    costs_for,
    partial_percentage,
    plan_fill,
    select_outcome,
)
from trading_bot.simulation.configured_models import ConfiguredValidationError
from trading_bot.simulation.costs import execution_fee, execution_price

from ._configured_fixtures import cost_settings, market, request, settings
from ._lifecycle_fixtures import make_request


class FixedDraw(random.Random):
    def __init__(self, bits=0, grid=0):
        super().__init__(0)
        self.bits = bits
        self.grid = grid

    def getrandbits(self, k):
        assert k == 53
        return self.bits

    def randrange(self, stop):
        assert stop == 10001
        return self.grid


@pytest.mark.parametrize(
    "pct,bits,want",
    [(0, 0, False), (100, 2**53 - 1, True), (50, 2**52 - 1, True), (50, 2**52, False)],
)
def test_chance_half_open_boundaries(pct, bits, want):
    assert chance(D(pct), FixedDraw(bits)) is want


@pytest.mark.parametrize(
    "bits,want",
    [
        (0, "no_fill"),
        (2**52 - 1, "no_fill"),
        (2**52, "full"),
        (3 * 2**51 - 1, "full"),
        (3 * 2**51, "partial"),
        (2**53 - 1, "partial"),
    ],
)
def test_outcomes_normalize_after_submission_rejection(bits, want):
    config = settings(
        rejection_probability_pct=D(20),
        no_fill_probability_pct=D(40),
        full_fill_probability_pct=D(20),
        partial_fill_probability_pct=D(20),
    )
    assert select_outcome(config, FixedDraw(bits)).value == want


def test_rejection_only_configuration_cannot_select_a_later_fill():
    with pytest.raises(ConfiguredValidationError):
        select_outcome(
            settings(rejection_probability_pct=D(100), full_fill_probability_pct=D(0)), FixedDraw()
        )


@pytest.mark.parametrize("grid,want", [(0, "10"), (5000, "30"), (10000, "50")])
def test_partial_range_includes_configured_endpoints(grid, want):
    assert partial_percentage(settings(), FixedDraw(grid=grid)) == D(want)


def test_fixed_partial_endpoint_is_constant():
    config = settings(partial_fill_min_pct=D(17), partial_fill_max_pct=D(17))
    assert partial_percentage(config, FixedDraw(grid=9876)) == D(17)


def test_crypto_costs_charge_fee_on_slipped_price():
    costs = costs_for(AssetClass.CRYPTO, cost_settings())
    price = execution_price(side=Side.BUY, bid=D(98), ask=D(99), costs=costs)
    assert price == D("99.2475")
    assert execution_fee(D(1), price, costs) == D("0.4962375")


def test_equity_uses_commission_not_crypto_or_spread_fee():
    costs = costs_for(AssetClass.EQUITY, cost_settings(equity_commission_usd=D(2)))
    assert execution_fee(D(1), D(99), costs) == D(2)


def test_plan_caps_liquidity_and_uses_current_remaining():
    base, digest = DataHash("a" * 64), DataHash("b" * 64)
    event = market(available_quantity=D("0.2"))
    full = plan_fill(request(), event, D("0.8"), base, digest)
    assert full.outcome is SimulatedOutcome.FULL
    assert full.fill.quantity == D("0.2")
    partial = settings(
        full_fill_probability_pct=D(0),
        partial_fill_probability_pct=D(100),
        partial_fill_min_pct=D(25),
        partial_fill_max_pct=D(25),
    )
    result = plan_fill(request(simulation=partial), market(), D("0.8"), base, digest)
    assert result.fill.quantity == D("0.2")
    assert result.percentage == D(25)


def test_nofill_has_no_charge_or_partial_draw():
    config = settings(full_fill_probability_pct=D(0), no_fill_probability_pct=D(100))
    result = plan_fill(
        request(simulation=config), market(), D(1), DataHash("a" * 64), DataHash("b" * 64)
    )
    assert result.fill is None
    assert result.percentage is None
    assert result.outcome is SimulatedOutcome.NO_FILL


def test_seeded_streams_repeat_without_mutating_global_random():
    before = random.getstate()
    base, event = DataHash("a" * 64), DataHash("b" * 64)
    first = keyed_rng(base, event, "outcome").getrandbits(53)
    # Independently computed SHA-256 + stdlib Random reference for the versioned format.
    assert first == 4682424882139304
    assert keyed_rng(base, event, "outcome").getrandbits(53) == first
    assert keyed_rng(base, event, "partial_size").getrandbits(53) != first
    assert random.getstate() == before


def test_fill_computation_ignores_and_preserves_ambient_context():
    args = request(), market(), D(1), DataHash("a" * 64), DataHash("b" * 64)
    expected = plan_fill(*args)
    with localcontext() as context:
        context.prec = 3
        context.traps[Inexact] = True
        assert plan_fill(*args) == expected
        assert context.prec == 3 and context.traps[Inexact]


def test_inexact_costs_are_not_rounded_into_a_fill():
    event = market()
    event = replace(event, quote=replace(event.quote, bid=D("98.1234567890123456789012345678")))
    initial = make_request(side=Side.SELL, position_quantity="1", average_price="99")
    with pytest.raises(ConfiguredValidationError, match="arithmetic"):
        plan_fill(request(initial=initial), event, D(1), DataHash("a" * 64), DataHash("b" * 64))
