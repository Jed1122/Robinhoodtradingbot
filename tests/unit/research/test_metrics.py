from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_bot.research.metrics import PerformanceInput, calculate_performance


def source(returns: tuple[Decimal, ...]) -> PerformanceInput:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    curve = tuple(
        (now + timedelta(days=index), Decimal("100") + index) for index in range(len(returns) + 1)
    )
    return PerformanceInput(
        curve,
        returns,
        (Decimal("2"), Decimal("-1"), Decimal("3")),
        252,
        Decimal("1"),
        Decimal("2"),
        (Decimal("50"),),
        (Decimal("50"),),
        Decimal("0.5"),
        Decimal("1"),
        Decimal("2"),
        Decimal("3"),
        3,
    )


def test_zero_downside_returns_none_sortino() -> None:
    metrics = calculate_performance(source((Decimal("0.01"), Decimal("0.02"))))
    assert metrics.sortino.value is None
    assert metrics.sortino.status == "undefined_no_downside_variation"


def test_trade_and_cost_metrics_are_complete() -> None:
    metrics = calculate_performance(source((Decimal("0.01"), Decimal("-0.02"), Decimal("0.03"))))
    assert metrics.expectancy.value == Decimal("4") / Decimal("3")
    assert metrics.spread_cost.value == Decimal("1")
    assert metrics.longest_losing_streak.value == 1
