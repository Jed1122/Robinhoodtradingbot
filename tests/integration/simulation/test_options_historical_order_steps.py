"""Hand accounting of pure order steps, not a completed historical episode runner."""

from decimal import Decimal

from tests.unit.market_data.test_databento_batch import no_network  # noqa: F401
from tests.unit.research.test_options_study_registration import config
from tests.unit.simulation.test_options_historical_execution import arrangement, scenario
from trading_bot.risk.options_economics import (
    OptionsCapitalState,
    TrialEpisode,
    TrialLossState,
    long_option_feasibility,
)


def test_hand_accounted_round_trip_keeps_unsettled_trial_reservation(tmp_path, monkeypatch):
    s = scenario()
    loaded = config()
    empty_trial = TrialLossState(())
    admissible = {}
    for capital in (Decimal("100"), Decimal("10000")):
        admissible[capital] = long_option_feasibility(
            loaded,
            OptionsCapitalState(capital, capital, capital, Decimal(0), Decimal(0), 0, 0),
            premium=Decimal("0.25"),
            multiplier=Decimal("100"),
            fee_reserve_per_unit=s.fee_bound_per_unit,
            trial=empty_trial,
        )
    assert admissible[Decimal("100")].per_trade_budget == Decimal("0.50")
    assert admissible[Decimal("100")].admissible_units == 0
    assert admissible[Decimal("10000")].admissible_units == 0
    assert admissible[Decimal("10000")].reason_codes == ("legacy_order_notional",)
    # Pure hypothetical unit accounting below, not a full-policy admissible trade.
    opening = tmp_path / "entry"
    opening.mkdir()
    execution, proposed, events = arrangement(opening, monkeypatch)
    ack = execution.advance_order(proposed.order, events[0], scenario=s, seed=7)
    buy = execution.advance_order(ack.order, events[1], scenario=s, seed=7)
    closing = tmp_path / "close"
    closing.mkdir()
    execution, proposed, events = arrangement(closing, monkeypatch, closing=True)
    ack = execution.advance_order(proposed.order, events[0], scenario=s, seed=7)
    sell = execution.advance_order(ack.order, events[1], scenario=s, seed=7)
    # Independent expected dollars, not another aggregation helper.
    assert buy.cash_flow == Decimal("-25.50")
    assert sell.cash_flow == Decimal("19.50")
    assert buy.cash_flow + sell.cash_flow == Decimal("-6.00")
    assert buy.fee + sell.fee == Decimal("1.00")
    assert not buy.settlement_complete and not sell.settlement_complete
    trial = TrialLossState(
        (
            TrialEpisode(
                "synthetic:episode",
                Decimal("26.00"),
                Decimal("-6.00"),
                True,
                True,
                False,
            ),
        )
    )
    assert trial.reserved_risk == Decimal("26.00")
    assert trial.consumed_loss == 0  # pending settlement is not a completed loss episode
    assert trial.remaining(Decimal("50")) == Decimal("24.00")
