from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from trading_bot.domain import DomainValidationError, require_bounded_decimal


@given(st.sampled_from(("NaN", "Infinity", "-Infinity")))
def test_nonfinite_market_values_are_always_rejected(raw: str) -> None:
    with pytest.raises(DomainValidationError):
        require_bounded_decimal(Decimal(raw), "market_value")
