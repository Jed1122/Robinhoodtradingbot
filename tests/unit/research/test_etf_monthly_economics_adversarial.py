"""Fabricated score projections isolate verdict math, not accepted evidence."""

import importlib
from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from tests.unit.research.test_etf_daily_economics_adversarial import projected, rising_nav
from tests.unit.simulation.test_etf_daily_screen import request
from trading_bot.research.etf_benchmark import _money_context
from trading_bot.simulation.etf_daily_screen import run_etf_daily_screen

D = Decimal


@pytest.fixture(scope="module")
def baseline():
    return run_etf_daily_screen(request(200))


def score(result):
    common = importlib.import_module("trading_bot.research.etf_exploratory_economics")
    _trace = importlib.import_module("trading_bot.research.etf_daily_economics")._trace
    with localcontext(_money_context()):
        return common.score_etf_exploratory_trace(
            _trace(result),
            cost_name="synthetic",
            budget_name="synthetic",
            data_monthly=D("0"),
            compute_monthly=D("0"),
        )


@pytest.mark.parametrize(
    "episodes,expected", [(29, "INSUFFICIENT_EVIDENCE"), (30, "PROCEED_TO_FURTHER_RESEARCH")]
)
def test_literal_episode_proxy_boundary_with_real_paired_math(baseline, episodes, expected):
    out = score(projected(baseline, rising_nav(), completed=episodes))
    assert out.operating_profit_proxy == D("50") and out.screening_verdict == expected
    assert out.independent_opportunities is None and out.economic_admitted is False


def test_incomplete_precedence_zero_profit_and_prior_nav_undefined(baseline):
    negative = projected(baseline, (D("490"),) * 100)
    assert (
        score(replace(negative, incomplete_reasons=("pending",))).screening_verdict
        == "INSUFFICIENT_EVIDENCE"
    )
    assert score(projected(baseline, (D("500"),) * 100)).screening_verdict == "REJECT"
    invalid_nav = score(projected(baseline, (D("0"), D("1"))))
    assert invalid_nav.performance.sharpe.value is None
    assert invalid_nav.performance.sharpe.status == "undefined_nonpositive_prior_nav"
