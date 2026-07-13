from decimal import Decimal
from fractions import Fraction

from hypothesis import example, given
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
@example(
    value=Decimal("94.399546168204972043160180766242117432437259853236437490600682304435"),
    increment=Decimal(
        "9.439954616820497204316018076624211743243725985323643749060068230443513380126E-7"
    ),
)
def test_quantize_down_is_bounded(value: Decimal, increment: Decimal) -> None:
    result = quantize_down(value, increment)
    exact_remainder = Fraction(value) - Fraction(result)

    assert result <= value
    assert exact_remainder < Fraction(increment)
