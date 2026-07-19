from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from tests.unit.research.test_prediction import estimate, snapshot
from trading_bot.domain import PredictionCosts
from trading_bot.research.prediction import evaluate_prediction_contract


@given(st.decimals(min_value=0, max_value="0.1", allow_nan=False, allow_infinity=False, places=4))
def test_costs_never_increase_edge(cost: Decimal) -> None:
    gross = evaluate_prediction_contract(
        snapshot(),
        estimate(),
        PredictionCosts(Decimal("0"), Decimal("0"), Decimal("0")),
        Decimal("0"),
    )
    net = evaluate_prediction_contract(
        snapshot(), estimate(), PredictionCosts(cost, cost, cost), Decimal("0")
    )
    assert net.edge <= gross.edge
