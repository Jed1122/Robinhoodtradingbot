from decimal import Decimal

from hypothesis import given
from hypothesis.strategies import decimals

from trading_bot.domain import quantize_down


@given(
    value=decimals(
        min_value="0",
        max_value="100000",
        allow_nan=False,
        allow_infinity=False,
    ),
    increment=decimals(
        min_value="0.00000001",
        max_value="100",
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_quantize_down_is_bounded(value: Decimal, increment: Decimal) -> None:
    result = quantize_down(value, increment)

    assert result <= value
    assert value - result < increment
