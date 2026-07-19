import random

from tests.unit.simulation.test_fills import request
from trading_bot.simulation import FillModel


def test_replay_fill_requires_later_event() -> None:
    assert FillModel().evaluate(request(4, 4), rng=random.Random(1)).fills == ()
