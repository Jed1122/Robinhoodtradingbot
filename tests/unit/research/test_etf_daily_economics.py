"""Frozen hypothetical costs do not establish customer calibration or admission."""

import importlib
from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from tests.unit.research.test_etf_daily_protocol import daily_bar
from tests.unit.simulation.test_etf_daily_screen import request

D = Decimal
CAPITAL = D("500")


def api():
    return importlib.import_module("trading_bot.research.etf_daily_economics")


def gap_request():
    req = request()
    rows = list(req.bars)
    rows[102] = daily_bar(rows[102].session_date, D("98"))
    return replace(req, bars=tuple(rows))


def score(
    report, *, capital=CAPITAL, cost="five_bps_uncalibrated", budget="current_paid_zero_compute"
):
    return next(
        row
        for row in report.scores
        if row.initial_cash == capital
        and row.cost_scenario == cost
        and row.operating_scenario == budget
    )


def test_frozen_cost_matrix_and_capital_dont_expand_sizing():
    req = gap_request()
    report = api().run_etf_daily_economics(req)
    assert len(report.scores) == 24
    first = score(report)
    second = score(report, capital=D("1000"))
    assert first.marked_trading_pnl == second.marked_trading_pnl == D("-.480206740")
    assert first.realized_trading_pnl == D("-.480206740")
    assert first.fees == D(".02") and first.completed_episodes == 1
    assert first.operating_cost == D("99")
    assert first.operating_profit_proxy == D("-99.480206740")
    assert first.screening_verdict == "REJECT"
    assert first.independent_opportunities is None and first.uncertainty is None
    assert report.economic_admitted is False and report.execution_enabled is False
    assert first.cost_qualified is False and first.evidence_promotable is False
    assert report.measured_cash_yield is None and report.assumed_cash_yield == 0
    assert report.sunk_research_cost is None and report.sunk_cost_included is False
    assert len(report.protocol_hash) == len(report.result_hash) == 64


def test_fee_embedded_in_pnl_is_not_subtracted_again():
    report = api().run_etf_daily_economics(gap_request())
    s = score(report, budget="zero_data_zero_compute_unverified")
    assert s.operating_cost == 0
    assert s.operating_profit_proxy == s.marked_trading_pnl
    assert s.fees == D(".02")
    assert abs(s.candidate_mean_exposure - s.reference_mean_exposure) < D("1e-24")
    assert s.reference_notional <= D("15")
    assert s.cash_benchmark_pnl == 0


def test_open_outcome_never_reports_realized_pnl_or_forces_a_sale():
    report = api().run_etf_daily_economics(request())
    s = score(report)
    assert s.realized_trading_pnl is None
    assert s.completed_episodes == 0
    assert "open_account_obligations" in s.incomplete_reasons
    assert s.screening_verdict == "INSUFFICIENT_EVIDENCE"


def test_unknown_basis_is_missing_not_a_zero_return():
    req = request()
    report = api().run_etf_daily_economics(
        replace(req, protocol=replace(req.protocol, price_basis="unknown"))
    )
    assert all(
        s.marked_trading_pnl is None
        and s.operating_profit_proxy is None
        and s.screening_verdict == "INSUFFICIENT_EVIDENCE"
        for s in report.scores
    )


def test_monthly_budget_is_an_explicit_renewal_model_not_daily_prorated_billing():
    from datetime import date

    assert api()._renewals(date(2016, 5, 26), date(2016, 6, 1)) == 1
    assert api()._renewals(date(2016, 5, 26), date(2016, 6, 26)) == 2
    assert api()._renewals(date(2016, 5, 26), date(2017, 5, 25)) == 12


def test_protocol_bound_before_outcomes_and_fixed_context():
    req = gap_request()
    before = api().etf_daily_economic_plan_hash(req.protocol)
    report = api().run_etf_daily_economics(req)
    assert report.protocol_hash == before
    with localcontext() as context:
        context.prec = 5
        assert api().run_etf_daily_economics(req) == report
    assert api().etf_daily_economic_plan_hash(replace(req.protocol, source_hash="1" * 64)) != before
    object.__setattr__(req, "economic_admitted", True)
    with pytest.raises(ValueError, match="etf_daily_invalid"):
        api().run_etf_daily_economics(req)
