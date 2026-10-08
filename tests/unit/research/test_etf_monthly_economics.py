"""Frozen hypothetical costs; never customer calibration."""

import importlib
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from tests.unit.research.test_etf_daily_protocol import daily_bar
from tests.unit.simulation.test_etf_monthly_screen import inputs as synthetic_inputs

D = Decimal


def api():
    return importlib.import_module("trading_bot.research.etf_monthly_economics")


def inputs():
    req = synthetic_inputs()
    study = replace(
        req.protocol.study,
        cost_plan_hash=api().etf_monthly_cost_plan_hash(),
        operating_basis_hash=api().etf_monthly_operating_basis_hash(),
    )
    return replace(req, protocol=replace(req.protocol, study=study))


def test_claimed_cost_and_operating_basis_cannot_differ_from_executed_grid():
    for field in ("cost_plan_hash", "operating_basis_hash"):
        req = inputs()
        altered = replace(req.protocol.study, **{field: "a" * 64})
        with pytest.raises(ValueError):
            api().run_etf_monthly_economics(
                replace(req, protocol=replace(req.protocol, study=altered))
            )


def test_all_24_fixed_cases_with_distinct_price_economic_operating_identities():
    req = inputs()
    out = api().run_etf_monthly_economics(req)
    assert len(out.scores) == 24
    assert tuple(
        (s.initial_cash, s.cost_scenario, s.monthly_data_assumption, s.monthly_compute_assumption)
        for s in out.scores
    ) == tuple(
        (capital, name, data, compute)
        for capital in (D("500"), D("1000"))
        for name in (
            "zero_cost_mathematical_reference",
            "five_bps_uncalibrated",
            "twenty_five_bps_uncalibrated",
        )
        for data, compute in (
            (D("0"), D("0")),
            (D("0"), D("12")),
            (D("99"), D("0")),
            (D("99"), D("12")),
        )
    )
    assert out.price_policy_hash == req.protocol.protocol_hash
    assert out.economic_plan_hash == api().etf_monthly_economic_plan_hash(req.protocol)
    assert out.operating_basis_hash == api().etf_monthly_operating_basis_hash()
    assert out.evaluation_anchor == date(2016, 11, 1)
    assert all(s.screening_verdict == "INSUFFICIENT_EVIDENCE" for s in out.scores)
    assert api().monthly_expansion_disposition(out) == "STOP_CANDIDATE"
    assert out.economic_admitted is out.live_authorized is out.execution_enabled is False
    assert out.native_whole_share_quantity == 0 and out.fractional_route_verified is False
    assert out.measured_cash_yield is out.sunk_research_cost is None


def test_unknown_input_no_points_unknown_not_zero_and_invalid_inputs_deny():
    req = inputs()
    out = api().run_etf_monthly_economics(
        replace(req, protocol=replace(req.protocol, price_basis="unknown"))
    )
    assert all(s.operating_profit_proxy is None and s.evaluation_sessions == 0 for s in out.scores)
    with pytest.raises(ValueError):
        api().run_etf_monthly_economics(None)
    with pytest.raises(ValueError):
        api().etf_monthly_economic_plan_hash(None)


def test_expansion_requires_stress_survival_but_no_caller_can_supply_operating_support():
    out = api().run_etf_monthly_economics(inputs())
    only_five = replace(
        out,
        scores=tuple(
            replace(s, screening_verdict="PROCEED_TO_FURTHER_RESEARCH")
            if s.cost_scenario == "five_bps_uncalibrated"
            else s
            for s in out.scores
        ),
    )
    assert api().monthly_expansion_disposition(only_five) == "STOP_CANDIDATE"
    stress = replace(
        out,
        scores=tuple(
            replace(s, screening_verdict="PROCEED_TO_FURTHER_RESEARCH")
            if s.cost_scenario == "twenty_five_bps_uncalibrated"
            else s
            for s in out.scores
        ),
    )
    assert api().monthly_expansion_disposition(stress) == "BLOCKED_OPERATING_EVIDENCE"
    assert stress.economic_admitted is stress.live_authorized is False


def test_literal_first_evaluated_date_anchors_whole_renewals_not_warmup():
    common = importlib.import_module("trading_bot.research.etf_exploratory_economics")
    assert tuple(
        common._renewals(date(2016, 11, 1), end)
        for end in (date(2016, 11, 1), date(2016, 11, 30), date(2016, 12, 1), date(2017, 1, 1))
    ) == (1, 1, 2, 3)
    nav = (D("550"), D("495"))
    assert common._returns(nav, D("500")) == (D(".10"), D("-.11"))
    assert common._period_returns(nav, D("500")) == (D(".10"), D("-.10"))
    assert common._period_returns((D("0"), D("1")), D("500")) is None


def test_adverse_prices_and_paid_fees_are_embedded_once_in_literal_cash():
    req = inputs()
    rows = tuple(
        daily_bar(r.session_date, D("98")) if r.session_date >= date(2016, 11, 2) else r
        for r in req.bars
    )
    report = api().run_etf_monthly_economics(replace(req, bars=rows))
    stress = report.scores[8:12]
    assert all(s.fees == D(".02") and s.marked_trading_pnl == D("-.7004184") for s in stress)
    assert tuple(s.operating_profit_proxy for s in stress) == (
        D("-.7004184"),
        D("-12.7004184"),
        D("-99.7004184"),
        D("-111.7004184"),
    )
    assert report.terminal_runs[2].account.cash == D("499.2995816")
    assert report.terminal_runs[2].account.trial.consumed_loss == D(".7004184")
    assert all(s.screening_verdict == "REJECT" for s in stress)


def test_operating_disposition_cannot_launder_nested_markers_or_support_claims():
    report = api().run_etf_monthly_economics(inputs())
    object.__setattr__(report.scores[0], "live_authorized", True)
    with pytest.raises(ValueError):
        api().monthly_expansion_disposition(report)
    with pytest.raises(ValueError):
        api().monthly_expansion_disposition(None)
