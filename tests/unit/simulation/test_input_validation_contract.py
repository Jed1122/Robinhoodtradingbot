"""Input-boundary contract for the synthetic fill and cost primitives."""

import random
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from trading_bot.clock import DomainValidationError
from trading_bot.domain import Side
from trading_bot.simulation import EventCursor, FillModel, FillPlan, FillRequest, PlannedFill
from trading_bot.simulation.costs import SimulatedCosts, execution_fee, execution_price

NOW = datetime(2026, 9, 16, 14, 30, tzinfo=UTC)
ZERO_COSTS = SimulatedCosts(Decimal("0"), Decimal("0"), Decimal("0"))
SMALL_COSTS = SimulatedCosts(Decimal("0.1"), Decimal("0.2"), Decimal("0.01"))


class DerivedDecimal(Decimal):
    pass


class DerivedCursor(EventCursor):
    pass


class DerivedCosts(SimulatedCosts):
    pass


def valid_request(**changes: Any) -> FillRequest:
    values: dict[str, Any] = {
        "submitted": EventCursor(10, NOW),
        "market": EventCursor(11, NOW),
        "side": Side.BUY,
        "quantity": Decimal("10"),
        "available_quantity": Decimal("10"),
        "bid": Decimal("99"),
        "ask": Decimal("100"),
        "rejection_probability": Decimal("0"),
        "fill_probability": Decimal("1"),
        "partial_fill_probability": Decimal("0"),
        "market_open": True,
        "costs": SMALL_COSTS,
    }
    values.update(changes)
    return FillRequest(**values)


INVALID_DECIMALS: tuple[object, ...] = (
    "1",
    1,
    1.0,
    True,
    Decimal("NaN"),
    Decimal("Infinity"),
    Decimal("1e513"),
    Decimal("1e-513"),
    DerivedDecimal("1"),
)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        *(
            pytest.param(field, value, id=f"{field}-{index}")
            for field in (
                "quantity",
                "available_quantity",
                "bid",
                "ask",
                "rejection_probability",
                "fill_probability",
                "partial_fill_probability",
            )
            for index, value in enumerate(INVALID_DECIMALS)
        ),
        pytest.param("quantity", Decimal("0"), id="quantity-zero"),
        pytest.param("quantity", Decimal("-0.1"), id="quantity-negative"),
        pytest.param("available_quantity", Decimal("-0.1"), id="availability-negative"),
        pytest.param("bid", Decimal("0"), id="bid-zero"),
        pytest.param("bid", Decimal("-1"), id="bid-negative"),
        pytest.param("ask", Decimal("0"), id="ask-zero"),
        pytest.param("ask", Decimal("-1"), id="ask-negative"),
        pytest.param("rejection_probability", Decimal("-0.1"), id="rejection-below-zero"),
        pytest.param("rejection_probability", Decimal("1.1"), id="rejection-above-one"),
        pytest.param("fill_probability", Decimal("-0.1"), id="fill-below-zero"),
        pytest.param("fill_probability", Decimal("1.1"), id="fill-above-one"),
        pytest.param("partial_fill_probability", Decimal("-0.1"), id="partial-below-zero"),
        pytest.param("partial_fill_probability", Decimal("1.1"), id="partial-above-one"),
    ],
)
def test_fill_request_rejects_invalid_decimal_fields_at_construction(
    field: str, value: object
) -> None:
    with pytest.raises(DomainValidationError):
        valid_request(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("side", "buy"),
        ("side", 1),
        ("market_open", 1),
        ("market_open", "true"),
        ("submitted", (10, NOW)),
        ("market", (11, NOW)),
        ("submitted", DerivedCursor(10, NOW)),
        ("market", DerivedCursor(11, NOW)),
        ("costs", (Decimal("0"), Decimal("0"), Decimal("0"))),
        ("costs", DerivedCosts(Decimal("0"), Decimal("0"), Decimal("0"))),
    ],
)
def test_fill_request_rejects_noncanonical_field_types(field: str, value: object) -> None:
    with pytest.raises(DomainValidationError):
        valid_request(**{field: value})


def test_fill_request_rejects_crossed_quotes() -> None:
    with pytest.raises(DomainValidationError):
        valid_request(bid=Decimal("101"), ask=Decimal("100"))


@pytest.mark.parametrize("amount", INVALID_DECIMALS)
@pytest.mark.parametrize("field", ["slippage_pct", "fee_pct", "commission"])
def test_costs_reject_non_decimal_nonfinite_or_unbounded_amounts(
    field: str, amount: object
) -> None:
    values: dict[str, object] = {
        "slippage_pct": Decimal("0"),
        "fee_pct": Decimal("0"),
        "commission": Decimal("0"),
    }
    values[field] = amount

    with pytest.raises(DomainValidationError):
        SimulatedCosts(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["slippage_pct", "fee_pct", "commission"])
def test_costs_reject_negative_amounts(field: str) -> None:
    with pytest.raises(DomainValidationError):
        replace(ZERO_COSTS, **{field: Decimal("-0.01")})


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(
            lambda: execution_price(
                side="buy", bid=Decimal("99"), ask=Decimal("100"), costs=ZERO_COSTS
            ),
            id="price-side",
        ),
        pytest.param(
            lambda: execution_price(side=Side.BUY, bid="99", ask=Decimal("100"), costs=ZERO_COSTS),
            id="price-bid-type",
        ),
        pytest.param(
            lambda: execution_price(
                side=Side.BUY, bid=Decimal("99"), ask=Decimal("NaN"), costs=ZERO_COSTS
            ),
            id="price-ask-nonfinite",
        ),
        pytest.param(
            lambda: execution_price(
                side=Side.BUY, bid=Decimal("101"), ask=Decimal("100"), costs=ZERO_COSTS
            ),
            id="price-crossed",
        ),
        pytest.param(
            lambda: execution_price(
                side=Side.BUY, bid=Decimal("99"), ask=Decimal("100"), costs="none"
            ),
            id="price-costs",
        ),
        pytest.param(
            lambda: execution_fee(Decimal("0"), Decimal("100"), ZERO_COSTS),
            id="fee-zero-quantity",
        ),
        pytest.param(
            lambda: execution_fee(Decimal("1"), Decimal("0"), ZERO_COSTS),
            id="fee-zero-price",
        ),
        pytest.param(
            lambda: execution_fee("1", Decimal("100"), ZERO_COSTS),
            id="fee-quantity-type",
        ),
        pytest.param(
            lambda: execution_fee(Decimal("1"), Decimal("Infinity"), ZERO_COSTS),
            id="fee-price-nonfinite",
        ),
        pytest.param(
            lambda: execution_fee(Decimal("1"), Decimal("100"), "none"),
            id="fee-costs",
        ),
        pytest.param(
            lambda: execution_price(
                side=Side.BUY,
                bid=Decimal("99"),
                ask=Decimal("100"),
                costs=DerivedCosts(Decimal("0"), Decimal("0"), Decimal("0")),
            ),
            id="price-costs-subclass",
        ),
        pytest.param(
            lambda: execution_fee(
                Decimal("1"),
                Decimal("100"),
                DerivedCosts(Decimal("0"), Decimal("0"), Decimal("0")),
            ),
            id="fee-costs-subclass",
        ),
    ],
)
def test_cost_helpers_reject_invalid_direct_inputs(call: Callable[[], object]) -> None:
    with pytest.raises(DomainValidationError):
        call()


@pytest.mark.parametrize("slippage", [Decimal("100"), Decimal("101")])
def test_sell_price_must_remain_positive(slippage: Decimal) -> None:
    costs = SimulatedCosts(slippage, Decimal("0"), Decimal("0"))

    with pytest.raises(DomainValidationError):
        execution_price(side=Side.SELL, bid=Decimal("100"), ask=Decimal("100"), costs=costs)


def test_valid_boundaries_preserve_zero_liquidity_outcome() -> None:
    request = valid_request(
        available_quantity=Decimal("0"),
        bid=Decimal("100"),
        ask=Decimal("100"),
        rejection_probability=Decimal("0"),
        fill_probability=Decimal("1"),
        partial_fill_probability=Decimal("1"),
        costs=ZERO_COSTS,
    )

    assert FillModel().evaluate(request, rng=random.Random(735)) == FillPlan(
        (), False, "no_liquidity"
    )


def test_valid_probability_endpoints_and_zero_costs_preserve_exact_arithmetic() -> None:
    request = valid_request(
        bid=Decimal("100"),
        ask=Decimal("100"),
        rejection_probability=Decimal("0"),
        fill_probability=Decimal("1"),
        partial_fill_probability=Decimal("0"),
        costs=ZERO_COSTS,
    )

    assert FillModel().evaluate(request, rng=random.Random(736)) == FillPlan(
        (PlannedFill(Decimal("10"), Decimal("100"), Decimal("0")),),
        False,
        "filled",
    )


@pytest.mark.parametrize("market_sequence", [10, 9])
def test_same_or_earlier_sequence_keeps_existing_result(market_sequence: int) -> None:
    request = valid_request(market=EventCursor(market_sequence, NOW))

    assert FillModel().evaluate(request, rng=random.Random(737)) == FillPlan(
        (), False, "same_event_fill_forbidden"
    )


def test_cursor_timestamp_order_does_not_add_a_fill_policy() -> None:
    later = datetime(2026, 9, 16, 14, 31, tzinfo=UTC)
    request = valid_request(
        submitted=EventCursor(10, later),
        market=EventCursor(11, NOW),
        costs=ZERO_COSTS,
    )

    assert FillModel().evaluate(request, rng=random.Random(738)).reason_code == "filled"
