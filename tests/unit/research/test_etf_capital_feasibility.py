"""Independent cash/risk expectations for the offline capital policy."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from trading_bot.config import load_config
from trading_bot.domain import AssetClass, DataHash, Instrument, InstrumentId
from trading_bot.research.etf_capital_feasibility import (
    capital_budgets,
    capital_feasibility,
    size_capital_entry,
)

CONFIGS = Path(__file__).resolve().parents[3] / "configs"
D = Decimal


def loaded():
    return load_config(
        CONFIGS / "base.yaml",
        CONFIGS / "etf/capital/simulation.yaml",
        CONFIGS / "safety-envelope.yaml",
        {},
        research_policy_path=CONFIGS / "etf/capital/policy.yaml",
    )


def instrument(**changes):
    value = Instrument(
        id=InstrumentId("fixture-SPY"),
        symbol="SPY",
        asset_class=AssetClass.EQUITY,
        provider_status="active",
        tradable=True,
        fractional_eligible=True,
        price_increment=D(".01"),
        quantity_increment=D(".001"),
        minimum_quantity=D(".001"),
        minimum_notional=D("1"),
        maximum_quantity=None,
        correlation_group="fixture-etf",
        observed_at=datetime(2026, 10, 8, tzinfo=UTC),
        data_hash=DataHash("a" * 64),
    )
    return replace(value, **changes)


def size(**changes):
    arguments = dict(
        loaded=loaded(),
        instrument=instrument(),
        equity=D("100"),
        settled_cash=D("100"),
        entry_price=D("10"),
        stop_distance=D(".2"),
        fee_bound=D(".1"),
        position_open=False,
        daily_loss=D("0"),
    )
    arguments.update(changes)
    return size_capital_entry(**arguments)


@pytest.mark.parametrize(
    "equity,position,risk,cash,loss",
    [("100", "20", ".5", "40", "1"), ("1000", "200", "5", "400", "10")],
)
def test_literal_equity_scaled_budgets(equity, position, risk, cash, loss):
    value = capital_budgets(loaded(), D(equity))
    assert value.max_notional == D(position)
    assert value.planned_risk_budget == D(risk)
    assert value.cash_floor == D(cash)
    assert value.daily_loss_budget == D(loss)


def test_fee_reserved_inside_planned_risk_and_cash():
    value = size()
    assert value.allowed is True
    assert value.quantity == D("2")
    assert value.notional == D("20")
    assert value.planned_risk_with_fees == D(".5")
    assert value.cash_reservation == D("20.1")
    assert value.execution_enabled is False
    assert value.evidence_promotable is False


def test_current_equity_not_reference_equity_controls_research():
    value = size(equity=D("1000"), settled_cash=D("1000"))
    assert value.quantity == D("20")
    assert value.notional == D("200")
    assert loaded().config.activity.max_order_notional_usd == D("15")


def test_settled_cash_and_cash_floor_are_independent_caps():
    value = size(settled_cash=D("12"))
    assert value.quantity == D("1.19")
    assert value.cash_reservation == D("12")
    # Fees count toward the cash floor even with all cash settled.
    assert size(fee_bound=D(".5")).allowed is False


@pytest.mark.parametrize(
    "changes",
    [
        {"position_open": True},
        {"daily_loss": D("1")},
        {"fee_bound": D(".51")},
        {"settled_cash": D("0")},
        {"instrument": instrument(minimum_notional=D("21"))},
        {"instrument": instrument(minimum_quantity=D("3"))},
        {"instrument": instrument(tradable=False)},
        {"instrument": instrument(symbol="TSLA")},
    ],
)
def test_denials_have_zero_economic_effect(changes):
    value = size(**changes)
    assert value.allowed is False
    assert value.quantity == value.notional == value.cash_reservation == D("0")
    assert value.planned_risk_with_fees == D("0")
    assert value.denial_code


def test_maximum_quantity_and_whole_share_terms():
    assert size(instrument=instrument(maximum_quantity=D(".5"))).quantity == D(".5")
    whole = instrument(fractional_eligible=False, quantity_increment=D("1"))
    assert size(instrument=whole, entry_price=D("500")).allowed is False


def test_unknown_fee_bound_cannot_admit_entry():
    assert size(fee_bound=None).denial_code == "unknown_fee_bound"


def test_fee_reduction_can_drop_final_size_below_minimum():
    assert size(fee_bound=D(".49")).denial_code == "below_minimum_notional"


def test_inconsistent_whole_share_terms_are_denied():
    assert size(instrument=instrument(fractional_eligible=False)).denial_code == (
        "inconsistent_whole_share_terms"
    )


def test_impossible_cash_state_is_not_silently_clamped():
    with pytest.raises(ValueError):
        size(settled_cash=D("101"))


def test_regular_profile_and_wrong_dependency_do_not_gain_research_admission():
    with pytest.raises(ValueError):
        capital_budgets(object(), D("100"))
    regular = load_config(
        CONFIGS / "base.yaml", CONFIGS / "simulation.yaml", CONFIGS / "safety-envelope.yaml", {}
    )
    with pytest.raises(ValueError):
        capital_budgets(regular, D("100"))


def test_caller_decimal_context_cannot_change_outcome():
    expected = size(entry_price=D("13.37"), stop_distance=D(".333"))
    with localcontext() as context:
        context.prec = 2
        assert size(entry_price=D("13.37"), stop_distance=D(".333")) == expected


def test_mutated_config_graph_cannot_borrow_old_canonical_identity():
    original = loaded()
    changed = replace(
        original,
        config=original.config.model_copy(update={"live_trading_enabled": True}),
    )
    with pytest.raises(ValueError):
        capital_budgets(changed, D("100"))


@pytest.mark.parametrize("changes", [{"equity": 100}, {"position_open": 0}, {"daily_loss": True}])
def test_equality_equivalent_input_types_are_rejected(changes):
    with pytest.raises(ValueError):
        size(**changes)


def test_feasibility_is_six_tier_assumption_report_not_broker_evidence():
    report = capital_feasibility(loaded())
    assert tuple(row.budget.equity for row in report.tiers) == tuple(
        map(D, (100, 250, 500, 1000, 5000, 10000))
    )
    assert report.tiers[0].compute_12_monthly_annual_equity_pct == D("144")
    assert report.tiers[-1].compute_12_monthly_annual_equity_pct == D("1.44")
    assert report.actual_recurring_data_cost is None
    assert report.actual_customer_fee_cost is None
    assert report.actual_tax_cost is None
    assert report.broker_fractional_route_verified is False
    assert report.execution_enabled is report.evidence_promotable is False
    assert report == capital_feasibility(loaded())
