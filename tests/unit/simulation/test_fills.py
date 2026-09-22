import random
from datetime import UTC, datetime
from decimal import Decimal

from trading_bot.domain import Side
from trading_bot.simulation import EventCursor, FillModel, FillRequest
from trading_bot.simulation.costs import SimulatedCosts

NOW = datetime(2026, 7, 17, tzinfo=UTC)


def request(submitted: int, market: int) -> FillRequest:
    return FillRequest(
        EventCursor(submitted, NOW),
        EventCursor(market, NOW),
        Side.BUY,
        Decimal("10"),
        Decimal("10"),
        Decimal("99"),
        Decimal("100"),
        Decimal("0"),
        Decimal("1"),
        Decimal("1"),
        True,
        SimulatedCosts(Decimal("0.1"), Decimal("0.2"), Decimal("0.01")),
    )


def test_order_cannot_fill_on_submission_cursor() -> None:
    assert FillModel().evaluate(request(10, 10), rng=random.Random(7)).fills == ()


def test_seeded_partial_fill_is_reproducible() -> None:
    first = FillModel().evaluate(request(10, 11), rng=random.Random(20260710))
    second = FillModel().evaluate(request(10, 11), rng=random.Random(20260710))
    assert first == second
    assert first.fills[0].quantity == Decimal("5")
