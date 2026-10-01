"""After-cost arithmetic independent of simulated fills and acceptance claims."""

import importlib
from dataclasses import replace
from decimal import Decimal

import pytest

from tests.unit.simulation.test_etf_account import episode_events, request
from trading_bot.simulation.etf_account import replay_etf_account

D = Decimal


def api():
    try:
        return importlib.import_module("trading_bot.research.etf_economics")
    except ModuleNotFoundError:
        pytest.fail("ETF after-cost report is missing")


def test_operating_cost_does_not_get_deducted_from_trading_pnl_or_spread_twice():
    result = replay_etf_account(request(episode_events()))
    report = api().evaluate_etf_account_economics(result, operating_cost=D(".25"))
    assert report.trading_pnl == D(".10")
    assert report.operating_profit == D("-.15")
    assert report.fees_paid == D(".02")
    assert report.cash_baseline_pnl == 0
    assert report.verdict == "ECONOMIC_NO_GO"
    assert not report.evidence_promotable and not report.execution_enabled
    assert "synthetic_account_facts" in report.reasons


def test_open_position_reports_unresolved_value_not_realized_strategy_profit():
    result = replay_etf_account(request(episode_events()[:2]))
    report = api().evaluate_etf_account_economics(result, operating_cost=D(".25"))
    assert report.trading_pnl is None and report.operating_profit is None
    assert report.residual_shares == D(".1")
    assert report.cash_change == D("-10.01")
    assert "account_outcome_incomplete" in report.reasons


@pytest.mark.parametrize("cost", [D("-1"), D("NaN"), True, 1, "0"])
def test_unbounded_or_inexact_operating_cost_is_rejected(cost):
    result = replay_etf_account(request(episode_events()))
    with pytest.raises(ValueError, match="etf_economic_invalid"):
        api().evaluate_etf_account_economics(result, operating_cost=cost)


def test_report_identity_binds_account_outcome_and_cost_allocation():
    result = replay_etf_account(request(episode_events()))
    first = api().evaluate_etf_account_economics(result, operating_cost=D(".25"))
    other = api().evaluate_etf_account_economics(result, operating_cost=D(".26"))
    assert first.report_hash != other.report_hash
    with pytest.raises(ValueError, match="etf_economic_invalid"):
        api().evaluate_etf_account_economics(
            replace(result, cash=D("999")), operating_cost=D(".25")
        )


def test_impossible_cash_domain_cannot_pass_a_conservation_identity():
    result = replay_etf_account(request(episode_events()))
    impossible = replace(
        result, initial_cash=D("-1000"), cash=D("-999.9"), settled_cash=D("-999.9")
    )
    with pytest.raises(ValueError, match="etf_economic_invalid"):
        api().evaluate_etf_account_economics(impossible, operating_cost=D(".25"))
