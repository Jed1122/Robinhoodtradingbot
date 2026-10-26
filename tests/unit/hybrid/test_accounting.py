from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from trading_bot.hybrid.accounting import buy_lot, dispose, exit_quantity, wash_sale_conflicts
from trading_bot.hybrid.models import Lot

NOW = datetime(2026, 10, 21, 14, tzinfo=UTC)


def test_retention_proceeds_are_not_capital_gain():
    lot = buy_lot("a", "SPY", "tactical", D(10), D(100), NOW)
    quantity = exit_quantity("principal", D(10), D(120), D(1000), D(120))
    assert quantity == D("1.666666")
    sale = dispose((lot,), quantity, D(120), NOW, tax_rate=D(".30"))
    assert abs(sale.proceeds - D(200)) < D(".0001")
    assert abs(sale.gain - D(100) / 3) < D(".0001")
    assert abs(sale.lots[0].basis - D(2500) / 3) < D(".0001")
    assert sale.tax_reserve == sale.gain * D(".30")


def test_multiple_lots_fifo_and_specific_disposal():
    first = buy_lot("a", "SPY", "tactical", D(1), D(100), NOW)
    second = buy_lot("b", "SPY", "tactical", D(2), D(120), NOW)
    fifo = dispose((first, second), D(2), D(130), NOW)
    assert fifo.gain == D(40)
    specific = dispose((first, second), D(1), D(130), NOW, selected_lots=("b",))
    assert specific.gain == D(10)
    assert specific.tax_reserve is None


def test_exits_and_invalid_disposal():
    assert exit_quantity("partial_first", D(10), D(113), D(1000), D(113)) == D("2.500000")
    assert exit_quantity("principal", D(10), D(114), D(1000), D(114)) == 0
    assert exit_quantity("trend", D(10), D(115), D(1000), D(125), trailing_pct=D(5)) == 10
    with pytest.raises(ValueError):
        dispose((), D(1), D(100), NOW)


def test_invalid_quantities_nonfinite_and_duplicate_lots():
    with pytest.raises(ValueError):
        buy_lot("a", "SPY", "tactical", D("NaN"), D(100), NOW)
    lot = buy_lot("a", "SPY", "tactical", D(1), D(100), NOW)
    with pytest.raises(ValueError):
        dispose((lot, lot), D(1), D(120), NOW)
    with pytest.raises(ValueError):
        Lot(id="x", symbol="SPY", sleeve="tactical", quantity="-1", basis="100", acquired_at=NOW)


def test_wash_sale_past_and_future_window():
    lot = buy_lot("a", "SPY", "tactical", D(1), D(100), NOW)
    assert wash_sale_conflicts("SPY", NOW, (lot,)) == ("a",)


@pytest.mark.parametrize(
    ("sold_at", "acquired_at", "expected"),
    [
        ("2026-09-01T14:30:00+00:00", "2026-10-01T20:00:00+00:00", True),
        ("2026-10-01T20:00:00+00:00", "2026-09-01T14:30:00+00:00", True),
        ("2026-09-01T20:00:00+00:00", "2026-10-02T14:30:00+00:00", False),
        ("2026-10-02T14:30:00+00:00", "2026-09-01T20:00:00+00:00", False),
    ],
)
def test_wash_sale_uses_inclusive_calendar_dates_not_720_hours(sold_at, acquired_at, expected):
    lot = buy_lot(
        "stock-lot", "AAPL", "tactical", D(1), D(100), datetime.fromisoformat(acquired_at)
    )
    assert wash_sale_conflicts("AAPL", datetime.fromisoformat(sold_at), (lot,)) == (
        ("stock-lot",) if expected else ()
    )


def test_completed_threshold_not_repeated_and_whole_share_rounding():
    assert exit_quantity("partial_first", D(10), D(120), D(1000), D(120), completed=True) == 0
    assert exit_quantity("principal", D(10), D(120), D(1000), D(120), fractional=False) == 1
