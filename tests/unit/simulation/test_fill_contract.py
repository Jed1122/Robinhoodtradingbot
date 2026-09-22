"""Characterization tests for the standalone seeded fill primitive."""

import random
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from trading_bot.domain import Side
from trading_bot.simulation import EventCursor, FillModel, FillPlan, FillRequest, PlannedFill
from trading_bot.simulation.costs import SimulatedCosts

OCCURRED_AT = datetime(2026, 8, 1, 14, 30, tzinfo=UTC)
COSTS = SimulatedCosts(
    slippage_pct=Decimal("0.1"),
    fee_pct=Decimal("0.2"),
    commission=Decimal("0.01"),
)


def make_request(
    *,
    submitted_sequence: int = 10,
    market_sequence: int = 11,
    side: Side = Side.BUY,
    quantity: str = "10",
    available_quantity: str = "10",
    rejection_probability: str = "0",
    fill_probability: str = "1",
    partial_fill_probability: str = "0",
    market_open: bool = True,
) -> FillRequest:
    """Build a fresh request exclusively from deterministic synthetic values."""
    return FillRequest(
        submitted=EventCursor(submitted_sequence, OCCURRED_AT),
        market=EventCursor(market_sequence, OCCURRED_AT),
        side=side,
        quantity=Decimal(quantity),
        available_quantity=Decimal(available_quantity),
        bid=Decimal("99"),
        ask=Decimal("100"),
        rejection_probability=Decimal(rejection_probability),
        fill_probability=Decimal(fill_probability),
        partial_fill_probability=Decimal(partial_fill_probability),
        market_open=market_open,
        costs=COSTS,
    )


@pytest.mark.parametrize("market_sequence", [10, 9])
def test_same_or_earlier_market_event_is_denied(market_sequence: int) -> None:
    plan = FillModel().evaluate(
        make_request(submitted_sequence=10, market_sequence=market_sequence),
        rng=random.Random(101),
    )

    assert plan == FillPlan((), False, "same_event_fill_forbidden")


def test_closed_market_precedes_forced_rejection_and_fill() -> None:
    plan = FillModel().evaluate(
        make_request(
            market_open=False,
            rejection_probability="1",
            fill_probability="1",
            partial_fill_probability="1",
        ),
        rng=random.Random(102),
    )

    assert plan == FillPlan((), False, "market_closed")


def test_forced_rejection_precedes_forced_fill() -> None:
    plan = FillModel().evaluate(
        make_request(rejection_probability="1", fill_probability="1"),
        rng=random.Random(103),
    )

    assert plan == FillPlan((), True, "simulated_rejection")


def test_forced_no_fill_is_not_a_rejection() -> None:
    plan = FillModel().evaluate(
        make_request(rejection_probability="0", fill_probability="0"),
        rng=random.Random(104),
    )

    assert plan == FillPlan((), False, "no_fill")


def test_zero_liquidity_is_reported_after_forced_fill_selection() -> None:
    plan = FillModel().evaluate(
        make_request(
            available_quantity="0",
            rejection_probability="0",
            fill_probability="1",
        ),
        rng=random.Random(105),
    )

    assert plan == FillPlan((), False, "no_liquidity")


@pytest.mark.parametrize("partial_fill_probability", ["0", "1"])
def test_buy_is_liquidity_capped_with_literal_price_and_fee_accounting(
    partial_fill_probability: str,
) -> None:
    plan = FillModel().evaluate(
        make_request(
            side=Side.BUY,
            available_quantity="4",
            partial_fill_probability=partial_fill_probability,
        ),
        rng=random.Random(106),
    )

    # BUY price: 100 * (1 + 0.1 / 100) = 100.100.
    # Fee: 4 * 100.100 * (0.2 / 100) + 0.01 = 0.810800.
    assert plan == FillPlan(
        (PlannedFill(Decimal("4"), Decimal("100.100"), Decimal("0.810800")),),
        False,
        "partial_fill",
    )


def test_forced_stochastic_partial_branch_has_literal_buy_accounting() -> None:
    plan = FillModel().evaluate(
        make_request(partial_fill_probability="1"),
        rng=random.Random(107),
    )

    # Half of 10 is 5; fee is 5 * 100.100 * 0.002 + 0.01 = 1.011000.
    assert plan == FillPlan(
        (PlannedFill(Decimal("5"), Decimal("100.100"), Decimal("1.011000")),),
        False,
        "partial_fill",
    )


def test_sell_full_fill_has_literal_price_and_fee_accounting() -> None:
    plan = FillModel().evaluate(
        make_request(side=Side.SELL, partial_fill_probability="0"),
        rng=random.Random(108),
    )

    # SELL price: 99 * (1 - 0.1 / 100) = 98.901.
    # Fee: 10 * 98.901 * (0.2 / 100) + 0.01 = 1.988020.
    assert plan == FillPlan(
        (PlannedFill(Decimal("10"), Decimal("98.901"), Decimal("1.988020")),),
        False,
        "filled",
    )


def test_equivalent_seeded_inputs_repeat_independently_of_global_random_state() -> None:
    model = FillModel()
    full = FillPlan(
        (PlannedFill(Decimal("10"), Decimal("100.100"), Decimal("2.012000")),),
        False,
        "filled",
    )
    partial = FillPlan(
        (PlannedFill(Decimal("5"), Decimal("100.100"), Decimal("1.011000")),),
        False,
        "partial_fill",
    )
    # Independently derived from the third 53-bit draw per evaluation at a 0.5 cutoff:
    # seed 20260801: .542, .953, .712, .441, .711, .239, .539, .985.
    expected = (full, full, full, partial, full, partial, full, full)

    global_state = random.getstate()
    try:
        random.seed(111_111)
        first_rng = random.Random(20260801)
        first = tuple(
            model.evaluate(make_request(partial_fill_probability="0.5"), rng=first_rng)
            for _ in range(8)
        )

        random.seed(999_999)
        for _ in range(25):
            random.random()
        second_rng = random.Random(20260801)
        second = tuple(
            model.evaluate(make_request(partial_fill_probability="0.5"), rng=second_rng)
            for _ in range(8)
        )
    finally:
        random.setstate(global_state)

    assert first == expected
    assert second == expected

    # Distinct-seed control: .211, .295, .190, .044, .782, .972, .630, .915.
    different_rng = random.Random(20260802)
    different = tuple(
        model.evaluate(make_request(partial_fill_probability="0.5"), rng=different_rng)
        for _ in range(8)
    )
    assert different == (partial, partial, partial, partial, full, full, full, full)
