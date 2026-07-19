from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from tests.unit.research.test_metrics import source
from trading_bot.research.metrics import calculate_performance


@given(
    st.lists(
        st.decimals(
            min_value="-0.5", max_value="0.5", allow_nan=False, allow_infinity=False, places=4
        ),
        min_size=2,
        max_size=50,
    )
)
def test_drawdown_and_win_rate_bounds(returns: list[Decimal]) -> None:
    metrics = calculate_performance(source(tuple(returns)))
    assert metrics.maximum_drawdown_pct.value is not None
    assert metrics.maximum_drawdown_pct.value <= 0
    assert metrics.win_rate_pct.value is not None
    assert Decimal("0") <= metrics.win_rate_pct.value <= Decimal("100")
