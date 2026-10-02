"""Complete frozen ETF evaluation with independent, permanently locked verdicts.

The canonical assessment is a threshold probe, not a selected candidate. All
preimages, diagnostic failures, unmeasured stability and unqualified assumptions
remain visible. No bootstrap draw, daily row or zero-fill order is a trade.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from typing import Literal

from trading_bot.domain import DataHash, Side
from trading_bot.market_data.etf_source import _ceil_time, _ns
from trading_bot.market_data.recording import ResearchDataManifest, content_hash
from trading_bot.research.etf_costs import EtfCostEvidence
from trading_bot.research.etf_full_statistics import EtfFullStatisticsReport, describe_etf_economics
from trading_bot.research.etf_study import EtfStudy
from trading_bot.research.report import (
    ResearchAttempt,
    ResearchDatasetSnapshot,
    ResearchReport,
    ResearchRunRecord,
    build_research_report,
    candidate_promotion_identity,
)
from trading_bot.research.validation import (
    LabeledObservation,
    ResearchAcceptancePolicy,
    ResearchAssessment,
    assess_research,
    purged_splits,
)
from trading_bot.simulation.etf_history import _policy
from trading_bot.simulation.etf_native_models import EtfHistoryResult, check
from trading_bot.simulation.lifecycle_accounting import _context


@dataclass(frozen=True, slots=True)
class EtfPurgedFold:
    initial_cash: Decimal
    fill_scenario: str
    first_test_at: datetime
    last_test_at: datetime
    training_observations: int
    purged_observations: int
    test_observations: int
    overlap_and_embargo_sessions: int
    completed_opportunities: int
    total_return_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class EtfThresholdAssessment:
    initial_cash: Decimal
    fill_scenario: str
    canonical_probe: ResearchReport
    assessment: ResearchAssessment
    independent_opportunities: int
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EtfEconomicReport:
    statistics: EtfFullStatisticsReport
    folds: tuple[EtfPurgedFold, ...]
    assessments: tuple[EtfThresholdAssessment, ...]
    reasons: tuple[str, ...]
    verdict: Literal["ECONOMIC_NO_GO"] = field(default="ECONOMIC_NO_GO", init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)

    @property
    def report_hash(self) -> str:
        return content_hash(("etf-complete-economic-report-v1", self))


def _episodes(result: EtfHistoryResult) -> tuple[tuple[int, int], ...]:
    """Only completed, actually filled episodes; full obligations bound labels."""
    spans = []
    facts = result.candidate.account_events
    for episode in result.candidate.account.trial.episodes:
        if not episode.complete:
            continue
        orders = {
            str(o.intent.id)
            for o in result.candidate.account.orders
            if o.episode_id == episode.episode_id
        }
        fills = tuple(
            e for e in facts if e.fill is not None and str(e.fill.broker_order_id) in orders
        )
        if not any(e.fill is not None and e.fill.side is Side.BUY for e in fills):
            continue
        ids = {e.fill.id for e in fills if e.fill is not None}
        start = min(e.at_ns for e in fills)
        end = max(e.at_ns for e in fills)
        # Settlement and later dividend obligations may outlive closing fills.
        end = max((e.at_ns for e in facts if ids.intersection(e.fill_ids)), default=end)
        ex = {e.action_id for e in facts if e.kind == "dividend_ex" and start <= e.at_ns <= end}
        end = max(
            (e.at_ns for e in facts if e.kind == "dividend_pay" and e.action_id in ex), default=end
        )
        spans.append((start, end))
    return tuple(sorted(spans))


def _folds(
    study: EtfStudy, result: EtfHistoryResult, net_nav: tuple[Decimal | None, ...]
) -> tuple[EtfPurgedFold, ...]:
    cfg = _policy(study).config
    settings = cfg.research
    rows = result.candidate.daily
    if len(rows) < settings.walk_forward_folds * settings.minimum_test_bars_per_fold:
        return ()
    warmup = tuple(b for b in result.bars if _ns(b.ends_at) < rows[0].at_ns)
    if len(warmup) < settings.minimum_history_bars:
        return ()
    times = tuple(b.ends_at for b in warmup) + tuple(_ceil_time(row.at_ns) for row in rows)
    check(times == tuple(sorted(set(times))))
    # Conservative full permitted lifecycle horizon: holding plus up to ten
    # settlement sessions (the schedule's maximum), then configured embargo.
    horizon = cfg.equity_strategies.maximum_holding_bars + 10 + settings.embargo_bars
    spans = _episodes(result)
    observations = []
    for index, at in enumerate(times):
        endpoint = times[index + horizon] if index + horizon < len(times) else study.holdout_start
        endpoint = max(
            (endpoint, *(_ceil_time(end) for start, end in spans if start <= _ns(at) <= end))
        )
        observations.append(LabeledObservation(at, endpoint, Decimal(0)))
    folds = []
    for number in range(settings.walk_forward_folds):
        left = len(rows) * number // settings.walk_forward_folds
        right = len(rows) * (number + 1) // settings.walk_forward_folds
        train_size = len(warmup) + left
        test_size = right - left
        split = purged_splits(
            tuple(observations[: len(warmup) + right]),
            train_size=train_size,
            test_size=test_size,
            embargo=timedelta(0),
        )[0]
        initial = result.initial_cash if left == 0 else net_nav[left - 1]
        final = net_nav[right - 1]
        with localcontext(_context(exact=False)):
            change = (
                (final / initial - 1) * 100
                if final is not None and initial is not None and initial > 0
                else None
            )
        start_ns, end_ns = rows[left].at_ns, rows[right - 1].at_ns
        count = sum(start_ns <= start <= end <= end_ns for start, end in spans)
        folds.append(
            EtfPurgedFold(
                result.initial_cash,
                result.fill_scenario,
                split.test[0].observed_at,
                split.test[-1].observed_at,
                len(split.train),
                train_size - len(split.train),
                test_size,
                horizon,
                count,
                change,
            )
        )
    return tuple(folds)


def evaluate_etf_economics(
    study: EtfStudy, results: tuple[EtfHistoryResult, ...], costs: EtfCostEvidence
) -> EtfEconomicReport:
    """Evaluate all six runs without unlocking an evidence or trading capability."""
    statistics = describe_etf_economics(study, results, costs)
    cfg = _policy(study).config.research
    policy = ResearchAcceptancePolicy(
        cfg.minimum_independent_opportunities,
        cfg.maximum_stressed_drawdown_pct,
        cfg.minimum_positive_walk_forward_folds,
        cfg.maximum_single_opportunity_profit_contribution_pct,
        cfg.maximum_monte_carlo_loss_probability_pct,
        cfg.minimum_benchmark_excess_return_pct,
    )
    ordered = sorted(results, key=lambda r: (r.initial_cash, r.fill_scenario))
    bars = ordered[0].bars
    check(all(r.bars == bars for r in ordered))
    check(
        all(
            _ns(study.requested_start)
            <= _ns(b.starts_at)
            < _ns(b.ends_at)
            < _ns(study.holdout_start)
            for b in bars
        )
    )
    for bar in bars:
        replace(bar)
    parameters = (("short_window", "20"), ("long_window", "100"), ("rebalance_sessions", "5"))
    parameter_hash = content_hash(parameters)
    strategy = candidate_promotion_identity(study.policy_id, "1", parameter_hash)
    all_folds: list[EtfPurgedFold] = []
    assessments = []
    reasons = set(statistics.reasons) | {
        "canonical_threshold_probe_not_candidate_selection",
        "parameter_stability_unmeasured",
        "multiple_testing_unresolved",
        "holdout_not_evaluated",
        "source_not_qualified",
        "operating_cost_itemization_unverified",
    }
    raw_hashes = (DataHash(statistics.dataset_hash), DataHash(ordered[0].source_prefix_hash))
    snapshot = ResearchDatasetSnapshot(
        study.holdout_start,
        study.requested_start,
        study.holdout_start,
        (("SPY", bars),),
        raw_hashes,
        DataHash(statistics.dataset_hash),
        ("source_not_qualified",),
    )
    manifest = ResearchDataManifest.create(
        raw_hashes=raw_hashes,
        cleaned_hashes=snapshot.cleaned_hashes,
        corporate_action_coverage="unverified",
        point_in_time_universe=False,
        known_gaps=("source_not_qualified",),
    )
    for result in ordered:
        summary = next(
            s
            for s in statistics.scenarios
            if (s.initial_cash, s.fill_scenario) == (result.initial_cash, result.fill_scenario)
        )
        folds = _folds(study, result, summary.candidate.net_nav)
        all_folds.extend(folds)
        spans = _episodes(result)
        independent = 0
        last = -1
        for first, end in spans:
            if first > last:
                independent += 1
                last = end
        diagnostics = set(summary.reasons) | set(result.reasons)
        if len(folds) != cfg.walk_forward_folds:
            diagnostics.add("purged_validation_coverage_insufficient")
        if independent < cfg.minimum_independent_opportunities:
            diagnostics.add("independent_opportunities_insufficient")
        if study.holdout_previously_examined:
            diagnostics.add("holdout_previously_examined")
        for paired in (summary.paired_zero, summary.paired_cash):
            if paired is None:
                diagnostics.add("paired_uncertainty_unavailable")
            # The paired helper owns fixed dependent-block calculations; its
            # explicit reasons include supported nonpositive excess endpoints.
            else:
                if paired.constrained_lower_bound <= 0:
                    diagnostics.add("constrained_excess_interval_not_positive")
                if paired.cash_lower_bound <= 0:
                    diagnostics.add("cash_excess_interval_not_positive")
        stressed = next(
            s
            for s in statistics.scenarios
            if s.initial_cash == result.initial_cash and s.fill_scenario == "conservative"
        )
        metrics = summary.candidate.metrics
        stressed_metrics = stressed.candidate.metrics
        if metrics is not None:
            metrics = replace(
                metrics,
                independent_opportunities=replace(
                    metrics.independent_opportunities, value=independent
                ),
            )
        if stressed_metrics is not None:
            stressed_metrics = replace(
                stressed_metrics,
                independent_opportunities=replace(
                    stressed_metrics.independent_opportunities, value=independent
                ),
            )
        benchmark = summary.constrained_benchmark.metrics
        benchmark_return = None if benchmark is None else benchmark.total_return_pct.value
        loss = max(
            (risk.loss_probability * 100 for risk in summary.net_expectancy_risks), default=None
        )
        attempt = ResearchAttempt(
            "etf-fixed-momentum",
            parameter_hash,
            "accepted",
            tuple(sorted(diagnostics)),
            metrics,
            study.policy_id,
            "1",
            parameters,
            stressed_metrics,
            tuple(f.total_return_pct for f in folds if f.total_return_pct is not None),
            benchmark_return if isinstance(benchmark_return, Decimal) else None,
            loss,
            summary.maximum_single_opportunity_profit_contribution_pct,
            (),
        )
        run = ResearchRunRecord(
            content_hash(("etf-threshold-probe-v1", result.result_hash)),
            strategy,
            study.code_hash,
            study.config_hash,
            manifest.manifest_hash,
            (
                ("cost_hash", costs.cost_hash),
                ("spread_slippage", "embedded_in_fills_not_debited_again"),
            ),
            (("fixed", (parameter_hash,)),),
            tuple(sorted(reasons)),
            False,
            ("SPY",),
            "SPY",
            statistics.dataset_hash,
            ("canonical_threshold_probe_not_candidate_selection",),
            manifest,
            snapshot,
            study.policy_id,
            "1",
            parameter_hash,
        )
        probe = build_research_report(run, attempts=(attempt,))
        assessment = assess_research(probe, policy)
        check(not assessment.eligible and not assessment.promotable)
        diagnostics.update(assessment.reason_codes)
        reasons.update(diagnostics)
        assessments.append(
            EtfThresholdAssessment(
                result.initial_cash,
                result.fill_scenario,
                probe,
                assessment,
                independent,
                tuple(sorted(diagnostics)),
            )
        )
    return EtfEconomicReport(
        statistics, tuple(all_folds), tuple(assessments), tuple(sorted(reasons))
    )
