"""Complete evaluation cannot turn six descriptive simulations into authority."""

import importlib
from dataclasses import replace
from decimal import Decimal

import pytest

from tests.unit.research.test_etf_full_statistics import package
from tests.unit.simulation.test_etf_history import bar, study
from trading_bot.research.etf_full_economics import evaluate_etf_economics
from trading_bot.simulation.etf_native_fixtures import synthetic_etf_history_request
from trading_bot.simulation.etf_native_history import run_etf_history
from trading_bot.simulation.etf_native_models import SCENARIOS


def test_full_evaluator_entrypoint_exists():
    module = importlib.import_module("trading_bot.research.etf_full_economics")
    assert callable(module.evaluate_etf_economics)


def test_actual_six_run_kernel_evaluation_preserves_loss_and_denies_promotion():
    frozen = study()
    requests = tuple(
        synthetic_etf_history_request(frozen, cash, scenario)
        for cash in frozen.capital_tiers
        for scenario in SCENARIOS
    )
    results = tuple(run_etf_history(request) for request in requests)
    report = evaluate_etf_economics(frozen, results, requests[0].costs)
    assert len(report.assessments) == 6
    assert all(not row.assessment.eligible for row in report.assessments)
    assert all(
        row.candidate.trading_pnl == Decimal("-.36446985") for row in report.statistics.scenarios
    )
    assert all(
        row.candidate.consumed_trial_loss == Decimal(".36446985")
        for row in report.statistics.scenarios
    )
    assert report.verdict == "ECONOMIC_NO_GO" and not report.evidence_promotable
    assert "unstable_parameters" in report.reasons
    assert "paired_uncertainty_unavailable" in report.reasons
    assert report == evaluate_etf_economics(frozen, tuple(reversed(results)), requests[0].costs)


def test_canonical_probe_preimages_are_valid_but_do_not_grant_acceptance():
    from trading_bot.research.report import report_integrity_reason_codes

    frozen, results, costs = package()
    report = evaluate_etf_economics(frozen, results, costs)
    assert all(not report_integrity_reason_codes(row.canonical_probe) for row in report.assessments)
    assert all(row.independent_opportunities == 1 for row in report.assessments)
    assert all(
        "research_assumptions_unvalidated" in row.assessment.reason_codes
        for row in report.assessments
    )


def test_purged_five_folds_keep_holding_settlement_embargo_without_forced_sales():
    frozen, results, costs = package(days=tuple(range(250)))
    warmup = tuple(bar(i, Decimal("100")).payload for i in range(750))
    results = tuple(replace(result, bars=warmup) for result in results)
    report = evaluate_etf_economics(frozen, results, costs)
    assert len(report.folds) == 30
    assert all(fold.test_observations == 50 for fold in report.folds)
    assert all(fold.purged_observations > 0 for fold in report.folds)
    assert sum(row.independent_opportunities for row in report.assessments) == 6
    assert "independent_opportunities_insufficient" in report.reasons
    assert all(not row.assessment.eligible for row in report.assessments)


def test_changed_bar_preimages_are_not_silently_mixed_between_scenarios():
    frozen, results, costs = package()
    changed = replace(results[0], bars=(bar(0, Decimal("100")).payload,))
    with pytest.raises(ValueError):
        evaluate_etf_economics(frozen, (changed, *results[1:]), costs)


def test_dividend_paid_before_sale_cannot_shorten_episode_settlement_label():
    from trading_bot.research.etf_full_economics import _episodes

    _, results, _ = package()
    source = results[0]
    settlement = max(
        event.at_ns for event in source.candidate.account_events if event.kind == "settlement"
    )
    assert _episodes(source)[0][1] == settlement
