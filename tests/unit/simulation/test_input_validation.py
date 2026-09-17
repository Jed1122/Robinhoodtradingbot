"""Primary regressions for simulation boundary and arithmetic-result validation."""

import random
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, Overflow, localcontext

import pytest

from trading_bot.clock import DomainValidationError
from trading_bot.domain import Side
from trading_bot.simulation.costs import SimulatedCosts, execution_fee, execution_price
from trading_bot.simulation.events import EventCursor
from trading_bot.simulation.fills import FillModel, FillRequest


def request() -> FillRequest:
    at = datetime(2026, 1, 5, tzinfo=UTC)
    return FillRequest(
        EventCursor(1, at),
        EventCursor(2, at),
        Side.BUY,
        Decimal("10"),
        Decimal("10"),
        Decimal("99"),
        Decimal("100"),
        Decimal("0"),
        Decimal("1"),
        Decimal("0"),
        True,
        SimulatedCosts(Decimal("0.1"), Decimal("0.2"), Decimal("0.01")),
    )


@pytest.mark.parametrize("field", ["quantity", "available_quantity"])
def test_negative_quantity_is_invalid_not_a_no_liquidity_outcome(field: str) -> None:
    with pytest.raises(DomainValidationError):
        replace(request(), **{field: Decimal("-1")})


@pytest.mark.parametrize("field", ["slippage_pct", "fee_pct", "commission"])
def test_negative_cost_is_not_a_rebate(field: str) -> None:
    with pytest.raises(DomainValidationError):
        replace(request().costs, **{field: Decimal("-0.01")})


@pytest.mark.parametrize(
    "field", ["rejection_probability", "fill_probability", "partial_fill_probability"]
)
@pytest.mark.parametrize("value", [Decimal("-0.01"), Decimal("1.01"), Decimal("NaN")])
def test_invalid_probability_is_rejected_at_construction(field: str, value: Decimal) -> None:
    with pytest.raises(DomainValidationError):
        replace(request(), **{field: value})


@pytest.mark.parametrize("slippage", ["100", "101"])
def test_sell_slippage_cannot_create_zero_or_negative_execution_price(slippage: str) -> None:
    costs = SimulatedCosts(Decimal(slippage), Decimal("0"), Decimal("0"))
    with pytest.raises(DomainValidationError):
        execution_price(side=Side.SELL, bid=Decimal("99"), ask=Decimal("100"), costs=costs)


def test_non_enum_side_cannot_silently_execute_as_sell() -> None:
    with pytest.raises(DomainValidationError):
        execution_price(side="buy", bid=Decimal("99"), ask=Decimal("100"), costs=request().costs)  # type: ignore[arg-type]


def test_crossed_book_is_invalid_even_when_market_is_closed() -> None:
    with pytest.raises(DomainValidationError):
        replace(request(), bid=Decimal("101"), market_open=False)


@pytest.mark.parametrize(
    "quantity,price", [(Decimal("0"), Decimal("100")), (Decimal("1"), Decimal("-1"))]
)
def test_direct_fee_call_requires_positive_quantity_and_price(
    quantity: Decimal, price: Decimal
) -> None:
    with pytest.raises(DomainValidationError):
        execution_fee(quantity, price, request().costs)


@pytest.mark.parametrize("trap_overflow", [False, True])
def test_overflowing_fee_result_is_rejected_as_domain_error(trap_overflow: bool) -> None:
    with localcontext() as context:
        context.Emax = 4
        context.traps[Overflow] = trap_overflow
        with pytest.raises(DomainValidationError):
            execution_fee(Decimal("1000"), Decimal("1000"), request().costs)


@pytest.mark.parametrize("trap_overflow", [False, True])
def test_overflowing_price_result_is_rejected_as_domain_error(trap_overflow: bool) -> None:
    costs = SimulatedCosts(Decimal("100000"), Decimal("0"), Decimal("0"))
    with localcontext() as context:
        context.Emax = 4
        context.traps[Overflow] = trap_overflow
        with pytest.raises(DomainValidationError):
            execution_price(side=Side.BUY, bid=Decimal("1000"), ask=Decimal("1000"), costs=costs)


def test_execution_results_still_obey_existing_decimal_representation_bounds() -> None:
    costs = SimulatedCosts(Decimal("0"), Decimal("100"), Decimal("0"))
    with pytest.raises(DomainValidationError):
        execution_fee(Decimal("1e300"), Decimal("1e300"), costs)


def test_price_result_still_obeys_existing_decimal_representation_bounds() -> None:
    costs = SimulatedCosts(Decimal("1e300"), Decimal("0"), Decimal("0"))
    with pytest.raises(DomainValidationError):
        execution_price(side=Side.BUY, bid=Decimal("1e300"), ask=Decimal("1e300"), costs=costs)


def test_valid_seeded_fill_retains_literal_price_quantity_and_fee() -> None:
    plan = FillModel().evaluate(request(), rng=random.Random(87))
    assert plan.reason_code == "filled"
    assert plan.rejected is False
    assert len(plan.fills) == 1
    assert plan.fills[0].quantity == Decimal("10")
    assert plan.fills[0].price == Decimal("100.100")
    assert plan.fills[0].fee == Decimal("2.012000")
