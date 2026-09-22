import random
from decimal import Decimal

from tests.unit.simulation.test_fills import request
from trading_bot.simulation import FillModel


def test_partial_fill_is_seed_reproducible() -> None:
    result = FillModel().evaluate(request(1, 2), rng=random.Random(20260710))
    assert result.fills[0].quantity == Decimal("5")
