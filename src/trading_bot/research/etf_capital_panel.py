"""Original-source DEVELOPMENT panel; never qualification or promotion authority."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from trading_bot.code_identity import CodeIdentity, CodeIdentityError, resolve_code_identity
from trading_bot.config import LoadedConfig
from trading_bot.config.capital_research import CapitalResearchAppConfig
from trading_bot.config.loader import restore_loaded_config
from trading_bot.domain import Instrument, require_bounded_decimal
from trading_bot.market_data.etf_capital_dataset import CapitalResearchDataset
from trading_bot.market_data.etf_capital_owned import _own_capital_source, _OwnedCapitalSource
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_economic_window import _capital_economic_window
from trading_bot.research.etf_capital_feasibility import _config
from trading_bot.research.etf_capital_matched import _capital_matched_values, _CapitalMatchedTerms
from trading_bot.research.etf_capital_panel_models import (
    _KEYS,
    _ROLES,
    _TAGS,
    CapitalEconomicPanelReport,
    CapitalPanelCriterion,
    CapitalPanelDecision,
    CapitalPanelFamily,
    CapitalPanelFinal,
    CapitalPanelFold,
    CapitalPanelLabel,
    CapitalPanelMathematical,
    CapitalPanelPath,
    CapitalPanelScenario,
    CapitalPanelTraining,
    _check,
    _false_flags,
    _panel_hash,
    _PanelRecord,
    _typed,
)
from trading_bot.research.etf_capital_passive import (
    _LIMITATIONS as _PASSIVE_LIMITATIONS,
)
from trading_bot.research.etf_capital_passive import (
    CapitalPassiveRequest,
    _capital_passive_values,
)
from trading_bot.research.etf_capital_path_economics import _ratio
from trading_bot.research.etf_capital_prepared import (
    _prepare_owned_capital_days,
    _PreparedCapitalInput,
)
from trading_bot.research.etf_capital_selection import (
    CapitalTrainingOutcome,
    CapitalTrainingSelection,
    select_capital_training,
)
from trading_bot.research.etf_capital_signals import (
    CapitalCandidate,
    CapitalWalkForwardFold,
    capital_candidates,
)
from trading_bot.research.etf_resampling import (
    EtfBlockRisk,
    dependent_capital_simultaneous_mean_intervals,
    dependent_mean_risks,
)
from trading_bot.simulation.etf_capital_constrained import (
    CapitalConstrainedDay,
    CapitalConstrainedRequest,
    CapitalConstrainedResult,
    _replay_owned_capital_constrained,
)
from trading_bot.simulation.etf_capital_daily_entry import _CONTEXT, _Offline
from trading_bot.simulation.etf_capital_daily_owner import _Outcome
from trading_bot.simulation.etf_capital_trajectory import CapitalTrajectoryResult

if TYPE_CHECKING:
    from trading_bot.simulation.etf_capital_walk_forward import CapitalWalkForwardRequest


def _record[T: _PanelRecord](cls: type[T], *values: object) -> T:
    return cast(Callable[..., T], cls)(*values, _panel_hash(_TAGS[cls], *values))


@dataclass(frozen=True, slots=True)
class CapitalEconomicPanelRequest(_Offline):
    dataset: CapitalResearchDataset
    instruments: tuple[Instrument, ...]
    episode_fee_bound: Decimal | None
    entry_fee: Decimal
    exit_fee: Decimal
    recurring_usd_per_day: Decimal | None
    sunk_research_usd: Decimal | None
    weekly_review_sessions: tuple[date, ...] = ()
    entry_outcome: _Outcome = "filled"
    entry_fill_fraction: Decimal = Decimal(1)
    exit_outcome: _Outcome = "filled"
    exit_fill_fraction: Decimal = Decimal(1)


def _panel_inputs(
    request: CapitalEconomicPanelRequest, owned: _OwnedCapitalSource
) -> tuple[CapitalResearchAppConfig, LoadedConfig, CapitalWalkForwardRequest]:
    from trading_bot.simulation.etf_capital_walk_forward import (
        CapitalWalkForwardRequest,
        _walk_forward_inputs,
    )

    try:
        _check(type(request) is CapitalEconomicPanelRequest)
        _check(_false_flags(request))
        loaded = restore_loaded_config(owned.dataset.canonical_config, owned.dataset.config_hash)
        cfg = _config(loaded)
        for amount in (request.entry_fee, request.exit_fee):
            require_bounded_decimal(amount, "declared fee", nonnegative=True)
        _check(request.entry_fee < min(cfg.capital_research.capital_tiers))
        for expense in (request.recurring_usd_per_day, request.sunk_research_usd):
            if expense is not None:
                require_bounded_decimal(expense, "declared expense", nonnegative=True)
        walk = CapitalWalkForwardRequest(
            request.dataset,
            cfg.capital_research.capital_tiers[0],
            request.instruments,
            request.episode_fee_bound,
            request.entry_fee,
            request.exit_fee,
            cfg.capital_research.round_trip_friction_pct[0],
            request.weekly_review_sessions,
            request.entry_outcome,
            request.entry_fill_fraction,
            request.exit_outcome,
            request.exit_fill_fraction,
        )
        _walk_forward_inputs(walk, owned)
        return cfg, loaded, walk
    except (ValueError, TypeError, AttributeError, ArithmeticError):
        raise ValueError("capital_economic_panel_invalid") from None


def _paired_column(
    candidate: tuple[Decimal, ...], reference: tuple[Decimal, ...], capital: Decimal
) -> tuple[Decimal, ...]:
    try:
        with localcontext(_CONTEXT):
            _check(type(candidate) is tuple and type(reference) is tuple)
            _check(len(candidate) == len(reference) == 631)
            require_bounded_decimal(capital, "paired capital", positive=True)
            for value in (*candidate, *reference):
                require_bounded_decimal(value, "paired NAV")
            return tuple(
                _ratio((b - a) - (d - c), capital)
                for (a, b), (c, d) in zip(pairwise(candidate), pairwise(reference), strict=True)
            )
    except (ValueError, TypeError, ArithmeticError):
        raise ValueError("capital_economic_panel_invalid") from None


def _build_family(
    kind: Literal["trading", "operating"],
    dates: tuple[date, ...],
    labels: tuple[CapitalPanelLabel, ...],
    columns: tuple[tuple[Decimal, ...], ...],
    *,
    capitals: tuple[Decimal, ...],
    frictions: tuple[Decimal, ...],
    seed: int,
    draws: int,
) -> CapitalPanelFamily:
    try:
        _check(type(kind) is str and kind in ("trading", "operating"))
        _check(type(dates) is tuple and len(dates) == 630)
        _check(all(type(day) is date for day in dates) and all(a < b for a, b in pairwise(dates)))
        _check(type(labels) is tuple and type(columns) is tuple)
        _check(len(capitals) == 6 and len(frictions) == 4)
        _check(len(labels) == len(columns) == 2784)
        expected = tuple(
            CapitalPanelLabel(
                capital,
                cost,
                path,
                cast(Literal["full_spy", "managed_spy", "matched_spy", "cash"], role),
            )
            for capital in capitals
            for cost in frictions
            for path in range(29)
            for role in _ROLES
        )
        for label, want, column in zip(labels, expected, columns, strict=True):
            _typed(label, CapitalPanelLabel)
            _check(label == want)
            _check(type(column) is tuple and len(column) == 630)
            for value in column:
                require_bounded_decimal(value, "paired increment")
        hashes = tuple(
            _panel_hash("column", kind, label, dates, column)
            for label, column in zip(labels, columns, strict=True)
        )
        bands = dependent_capital_simultaneous_mean_intervals(
            columns, seed=seed, block_lengths=(20, 100), draws=draws
        )
        return _record(CapitalPanelFamily, kind, dates, labels, columns, hashes, bands)
    except (ValueError, TypeError, AttributeError, ArithmeticError):
        raise ValueError("capital_economic_panel_invalid") from None


def _retain_final(
    trajectory: CapitalTrajectoryResult | CapitalConstrainedResult,
    *,
    initial_cash: Decimal,
    test_count: int,
) -> CapitalPanelFinal:
    with localcontext(_CONTEXT):
        _check(type(trajectory) in (CapitalTrajectoryResult, CapitalConstrainedResult))
        _check(_false_flags(trajectory))
        _check(type(test_count) is int and 0 < test_count < len(trajectory.points))
        require_bounded_decimal(initial_cash, "capital", positive=True)
        account, cutoff = trajectory.account, trajectory.points[test_count].account
        complete = account.complete and account.quantity == 0
        _check(type(account.marked_equity) is Decimal)
        return _record(
            CapitalPanelFinal,
            trajectory.input_hash,
            account.economic_hash,
            trajectory.risk.result_hash,
            account.complete,
            account.cash,
            account.available_cash,
            account.quantity,
            account.unsettled_proceeds,
            account.distribution_receivable,
            account.fees,
            account.marked_equity,
            account.cash - initial_cash if complete else None,
            account.cash - cutoff.cash,
            account.fees - cutoff.fees,
            (
                "final_original_tail_state_not_test_finality",
                "marked_equity_not_realized_cash",
                *(() if complete else ("final_outcome_incomplete",)),
            ),
        )


def _decide_path(
    capital: Decimal,
    path_index: int,
    scenarios: tuple[CapitalPanelScenario, ...],
    *,
    operating: CapitalPanelFamily | None,
    cash_risks: tuple[tuple[EtfBlockRisk, ...], ...] | None,
    cfg: CapitalResearchAppConfig,
) -> CapitalPanelDecision:
    """Private cross-cost screen of freshly assembled, complete panel facts.

    Conditional resampling never supplies independence or adaptive coverage.
    Full scenario/family admission belongs to the original-source assembler.
    """
    with localcontext(_CONTEXT):
        tiers = cfg.capital_research.capital_tiers
        costs = cfg.capital_research.round_trip_friction_pct
        _check(type(capital) is Decimal and capital in tiers)
        _check(type(path_index) is int and 0 <= path_index < 29)
        _check(type(scenarios) is tuple and len(scenarios) == 4)
        windows = []
        for scenario, cost in zip(scenarios, costs, strict=True):
            _check(type(scenario) is CapitalPanelScenario)
            _check(scenario.capital == capital and scenario.friction_pct == cost)
            _check(len(scenario.paths) > path_index)
            path = scenario.paths[path_index]
            _check(type(path) is CapitalPanelPath and path.path_index == path_index)
            windows.append(path.window)
        research = cfg.research
        thresholds = (
            Decimal(0),
            Decimal(research.minimum_positive_walk_forward_folds),
            research.maximum_stressed_drawdown_pct,
            research.minimum_benchmark_excess_return_pct,
            Decimal(0),
            research.maximum_monte_carlo_loss_probability_pct,
            Decimal(research.minimum_independent_opportunities),
            research.maximum_single_opportunity_profit_contribution_pct,
            Decimal(0),
            cfg.equity_strategies.etf_pilot.confidence_level_pct,
        )
        values: list[Decimal | None] = [None] * 10
        reasons = ["operating_cost_unknown"] * 6 + [
            "dependent_dates_draws_and_episodes_are_not_independent_opportunities",
            "independent_profit_attribution_not_established",
            "positive_marks_are_not_conservative_net_expectancy",
            "conditional_bands_do_not_rerun_adaptive_selection",
        ]
        evidence = tuple(s.input_hash for s in scenarios)
        if operating is None:
            _check(cash_risks is None)
            _check(all(w.net_nav is None and w.marked_operating_profit is None for w in windows))
        else:
            _check(type(operating) is CapitalPanelFamily and operating.kind == "operating")
            _check(len(operating.columns) == len(operating.labels) == 2784)
            if cash_risks is None:
                raise ValueError("capital_economic_panel_invalid")
            _check(type(cash_risks) is tuple and len(cash_risks) == 696)
            _check(tuple(b.block_length for b in operating.bands) == (20, 100))
            _check(all(len(b.intervals) == 2784 for b in operating.bands))
            profits, positives, drawdowns = [], [], []
            excesses: list[Decimal] = []
            lower_bounds: list[Decimal] = []
            probabilities: list[Decimal] = []
            tier = tiers.index(capital)
            for cost_index, window in enumerate(windows):
                _check(window.session_dates == operating.session_dates)
                if (
                    window.net_nav is None
                    or window.marked_operating_profit is None
                    or window.operating_metrics is None
                ):
                    raise ValueError("capital_economic_panel_invalid")
                _check(len(window.net_nav) == 631)
                profits.append(window.marked_operating_profit)
                positives.append(
                    Decimal(
                        sum(
                            window.net_nav[(fold + 1) * 126] > window.net_nav[fold * 126]
                            for fold in range(5)
                        )
                    )
                )
                drawdown = window.operating_metrics.maximum_drawdown_pct.value
                if drawdown is None:
                    raise ValueError("capital_economic_panel_invalid")
                drawdowns.append(abs(Decimal(drawdown)))
                base = ((tier * 4 + cost_index) * 29 + path_index) * 4
                for role_index, role in enumerate(_ROLES):
                    index = base + role_index
                    _check(
                        operating.labels[index]
                        == CapitalPanelLabel(
                            capital,
                            costs[cost_index],
                            path_index,
                            cast(Literal["full_spy", "managed_spy", "matched_spy", "cash"], role),
                        )
                    )
                    excesses.append(sum(operating.columns[index], Decimal(0)) * 100)
                    lower_bounds.extend(b.intervals[index].lower for b in operating.bands)
                risks = cash_risks[base // 4]
                _check(tuple(r.interval.block_length for r in risks) == (20, 100))
                for risk in risks:
                    _check(type(risk) is EtfBlockRisk and 0 <= risk.loss_probability <= 1)
                    probabilities.append(100 * risk.loss_probability)
            values[:6] = [
                min(profits),
                min(positives),
                max(drawdowns),
                min(excesses),
                min(lower_bounds),
                max(probabilities),
            ]
            reasons[:6] = [
                "minimum_observed_marked_operating_profit_across_four_costs",
                "minimum_positive_consecutive_126_date_folds_across_four_costs",
                "worst_original_operating_drawdown_across_four_costs",
                "minimum_fixed_capital_paired_excess_across_all_roles_and_costs",
                "conditional_complete_family_lower_bound_not_adaptive_coverage",
                "conditional_cash_loss_probability_whole_percent_not_population_proof",
            ]
            evidence = (*evidence, operating.input_hash)
        criteria = []
        for index, (key, value, threshold, reason) in enumerate(
            zip(_KEYS, values, thresholds, reasons, strict=True)
        ):
            passed = value is not None and (
                value > threshold
                if index in (0, 4)
                else value <= threshold
                if index in (2, 5)
                else value >= threshold
            )
            status: Literal["passes_declared_screen", "fails_declared_screen", "unknown"] = (
                "unknown"
                if value is None
                else "passes_declared_screen"
                if passed
                else "fails_declared_screen"
            )
            criteria.append(
                _record(CapitalPanelCriterion, key, status, value, threshold, reason, evidence)
            )
        verdict = (
            "REJECT"
            if any(c.status == "fails_declared_screen" for c in criteria)
            else ("INSUFFICIENT_EVIDENCE")
        )
        return _record(CapitalPanelDecision, capital, path_index, tuple(criteria), verdict)


def _retain_training(
    result: CapitalTrajectoryResult,
    candidate: CapitalCandidate,
    outcome: CapitalTrainingOutcome,
) -> CapitalPanelTraining:
    _check(type(result) is CapitalTrajectoryResult)
    _check(_false_flags(result))
    return _record(
        CapitalPanelTraining,
        candidate,
        outcome,
        result.input_hash,
        result.account.economic_hash,
        result.risk.result_hash,
        len(result.points),
        len(result.events),
    )


def _retain_path(
    result: CapitalTrajectoryResult,
    *,
    path_index: int,
    candidate: CapitalCandidate | None,
    owned: _OwnedCapitalSource,
    terms: _CapitalMatchedTerms,
    test_sessions: tuple[date, ...],
    recurring_usd_per_day: Decimal | None,
    sunk_research_usd: Decimal | None,
) -> CapitalPanelPath:
    _check(type(result) is CapitalTrajectoryResult)
    window = _capital_economic_window(
        result,
        initial_cash=terms.initial_cash,
        test_sessions=test_sessions,
        recurring_usd_per_day=recurring_usd_per_day,
        sunk_research_usd=sunk_research_usd,
    )
    final = _retain_final(result, initial_cash=terms.initial_cash, test_count=len(test_sessions))
    matched = _capital_matched_values(owned, terms, result, test_sessions)
    mathematical = _record(
        CapitalPanelMathematical,
        matched.input_hash,
        matched.kernel_result.input_hash,
        terms.initial_cash,
        (terms.initial_cash, *tuple(p.close_midpoint_nav for p in matched.kernel_result.points)),
        matched.raw_quantities,
        matched.mean_exposure,
        matched.close_exposures,
        matched.limitations,
    )
    return _record(
        CapitalPanelPath, path_index, candidate, result.input_hash, window, final, mathematical
    )


@dataclass(frozen=True, slots=True)
class _CapitalPanelRetention:
    """Invocation-private projection context, never a public callback/token."""

    owned: _OwnedCapitalSource
    prepared: _PreparedCapitalInput
    terms: _CapitalMatchedTerms
    test_sessions: tuple[date, ...]
    recurring_usd_per_day: Decimal | None
    sunk_research_usd: Decimal | None

    def training(
        self,
        result: CapitalTrajectoryResult,
        candidate: CapitalCandidate,
        outcome: CapitalTrainingOutcome,
    ) -> CapitalPanelTraining:
        return _retain_training(result, candidate, outcome)

    def fold(
        self,
        fold: CapitalWalkForwardFold,
        cutoff: datetime,
        at: datetime,
        training: tuple[CapitalPanelTraining, ...],
        selection: CapitalTrainingSelection,
    ) -> CapitalPanelFold:
        return _record(CapitalPanelFold, fold, cutoff, at, training, selection)

    def path(
        self, result: CapitalTrajectoryResult, index: int, candidate: CapitalCandidate | None
    ) -> CapitalPanelPath:
        return _retain_path(
            result,
            path_index=index,
            candidate=candidate,
            owned=self.owned,
            terms=self.terms,
            test_sessions=self.test_sessions,
            recurring_usd_per_day=self.recurring_usd_per_day,
            sunk_research_usd=self.sunk_research_usd,
        )


@dataclass(frozen=True, slots=True)
class _CapitalCompactWalkForward:
    folds: tuple[CapitalPanelFold, ...]
    paths: tuple[CapitalPanelPath, ...]
    walker_hash: str


_PROTOCOL = (
    "capital-original-economic-panel-v1",
    1423,
    769,
    (770, 1400),
    (1400, 1423),
    (750, 20, 20, 126, 5),
    "first-source-session-anchored_unused-suffix-reported",
    "train-only-complete-positive-USDPNL-at-.40_grid-order-cash-zero",
    "continuous-account_original-opening-policy-carried_no-terminal-forced-fill",
    "whole-percent-roundtrip-halfside_fees-once",
    _ROLES,
    "capital-friction-selected-then-grid-role_order_2784x630",
    "managed-candidate-and-managed-SPY_same-calendar-UTC-date-elapsed-operating-cost",
    "passive-matched-cash-zero-incremental-expense-assumption",
    "unknown-recurring-whole-operating-family-none_no-cancellation",
    "marked-prior-NAV-returns-distinct-from-paired-USD-increments-over-fixed-capital",
    "sunk-declared-once-not-summed_tax-unknown_development-only",
)
_LIMITATIONS = (
    "development_only_not_qualified_market_source_or_expected_live_performance",
    "source_actions_access_costs_fractional_terms_and_execution_unqualified",
    "2016_2023_adaptive_2024_2025_used_or_uncertain_not_untouched",
    "publication_chronology_waiver_disclosed_not_reinstated_or_validated",
    "future_126_eligible_final_sessions_require_complete_freeze_no_peek_or_auto_extension",
    "conditional_joint_bands_do_not_establish_independence_or_adaptive_selection_coverage",
    "marked_NAV_not_sale_final_fees_settlement_or_window_realized_profit",
    "cash_zero_yield_lower_bound_full_SPY_not_risk_executable_matched_SPY_retrospective",
    "managed_paths_same_declared_recurring_cost_passive_matched_cash_zero_incremental_assumed",
    "sunk_research_cost_is_one_declaration_not_sum_of_nested_repetitions",
    "taxes_unknown_not_assumed_zero",
    "no_economic_admission_promotion_runtime_or_live_authority",
)


def _evaluate_scenario(
    walk: CapitalWalkForwardRequest,
    *,
    owned: _OwnedCapitalSource,
    prepared: _PreparedCapitalInput,
    recurring_usd_per_day: Decimal | None,
    sunk_research_usd: Decimal | None,
) -> CapitalPanelScenario:
    from trading_bot.simulation.etf_capital_walk_forward import (
        _replay_owned_capital_walk_forward,
        _walk_forward_inputs,
    )

    _, _, dates, _, reviews = _walk_forward_inputs(walk, owned)
    tests = dates[770:1400]
    terms = _CapitalMatchedTerms(
        walk.initial_cash, walk.roundtrip_friction_pct, walk.entry_fee, walk.exit_fee
    )
    compact = _replay_owned_capital_walk_forward(
        walk,
        owned=owned,
        prepared=prepared,
        retention=_CapitalPanelRetention(
            owned, prepared, terms, tests, recurring_usd_per_day, sunk_research_usd
        ),
    )
    passive_request = CapitalPassiveRequest(
        owned.dataset,
        walk.initial_cash,
        tests,
        walk.roundtrip_friction_pct,
        walk.entry_fee,
        walk.exit_fee,
    )
    kernel, quantities, baseline = _capital_passive_values(owned, passive_request)
    reference_hash = content_hash(
        (
            "capital-passive-original-reference-v1",
            owned.source_hash,
            owned.dataset.config_hash,
            baseline,
            tests,
            walk.initial_cash,
            walk.roundtrip_friction_pct,
            walk.entry_fee,
            walk.exit_fee,
            kernel.input_hash,
            _PASSIVE_LIMITATIONS,
        )
    )
    full = _record(
        CapitalPanelMathematical,
        reference_hash,
        kernel.input_hash,
        walk.initial_cash,
        (walk.initial_cash, *tuple(p.close_midpoint_nav for p in kernel.points)),
        quantities,
        None,
        None,
        _PASSIVE_LIMITATIONS,
    )
    schedule = tuple(
        CapitalConstrainedDay(
            day,
            index < 1399,
            index < 1400,
            day in reviews,
        )
        for index, day in enumerate(dates[769:1423], start=769)
    )
    managed = _replay_owned_capital_constrained(
        CapitalConstrainedRequest(
            owned.dataset,
            walk.initial_cash,
            schedule,
            walk.instruments,
            walk.episode_fee_bound,
            walk.entry_fee,
            walk.exit_fee,
            walk.roundtrip_friction_pct,
            walk.entry_outcome,
            walk.entry_fill_fraction,
            walk.exit_outcome,
            walk.exit_fill_fraction,
        ),
        owned=owned,
        prepared=prepared,
    )
    managed_window = _capital_economic_window(
        managed,
        initial_cash=walk.initial_cash,
        test_sessions=tests,
        recurring_usd_per_day=recurring_usd_per_day,
        sunk_research_usd=sunk_research_usd,
    )
    managed_final = _retain_final(managed, initial_cash=walk.initial_cash, test_count=630)
    del managed
    return _record(
        CapitalPanelScenario,
        walk.initial_cash,
        walk.roundtrip_friction_pct,
        compact.walker_hash,
        compact.folds,
        compact.paths,
        full,
        managed_window,
        managed_final,
        (walk.initial_cash,) * 631,
    )


def _validate_scenario(
    scenario: CapitalPanelScenario,
    *,
    walk: CapitalWalkForwardRequest,
    owned: _OwnedCapitalSource,
    recurring_usd_per_day: Decimal | None,
    sunk_research_usd: Decimal | None,
) -> None:
    """Admit every retained fact before any whole-panel statistical call."""
    from trading_bot.simulation.etf_capital_walk_forward import _walk_forward_inputs

    _typed(scenario, CapitalPanelScenario)
    terms, _, dates, folds, _ = _walk_forward_inputs(walk, owned)
    sessions = {s.session_date: s for s in owned.dataset.calendar.sessions}
    candidates = capital_candidates()
    _check(scenario.capital == walk.initial_cash)
    _check(scenario.friction_pct == walk.roundtrip_friction_pct)
    _check(len(scenario.folds) == 5 and len(scenario.paths) == 29)
    for actual, expected in zip(scenario.folds, folds, strict=True):
        _check(actual.fold == expected)
        cutoff = sessions[expected.train_sessions[-1]].closes_at + timedelta(seconds=3)
        at = sessions[dates[dates.index(expected.test_sessions[0]) - 1]].closes_at
        _check(actual.training_cutoff == cutoff and actual.selection_at == at)
        _check(len(actual.training) == 28)
        for value, candidate in zip(actual.training, candidates, strict=True):
            value.__post_init__()
            _check(value.candidate == candidate)
        selection = select_capital_training(
            tuple(t.outcome for t in actual.training),
            loaded=terms.loaded,
            capital=walk.initial_cash,
            training_cutoff=cutoff,
            selection_at=at,
        )
        _check(actual.selection == selection)

    def window(value: object) -> None:
        from trading_bot.research.etf_capital_economic_window import CapitalEconomicWindow

        _typed(value, CapitalEconomicWindow)
        current = cast(CapitalEconomicWindow, value)
        _check(current.initial_cash == walk.initial_cash)
        _check(current.baseline_session == dates[769])
        _check(current.session_dates == dates[770:1400])
        _check(current.tail_sessions == dates[1400:1423])
        _check(len(current.marked_nav) == 631 and current.baseline_nav == current.marked_nav[0])
        _check(current.marked_pnl == current.marked_nav[-1] - current.baseline_nav)
        _check(current.sunk_research_cost == sunk_research_usd)
        _check(current.independent_opportunities is current.actual_tax_usd is None)
        if recurring_usd_per_day is None:
            _check(current.net_nav is None and current.recurring_cost is None)
            _check(current.operating_profit is None and current.marked_operating_profit is None)
            _check(current.operating_prior_nav_returns is None)
            _check(current.operating_metrics is None)
        else:
            costs = tuple(
                Decimal((day - dates[769]).days) * recurring_usd_per_day for day in dates[769:1400]
            )
            net = tuple(nav - cost for nav, cost in zip(current.marked_nav, costs, strict=True))
            _check(current.net_nav == net and current.recurring_cost == costs[-1])
            _check(current.marked_operating_profit == current.marked_pnl - costs[-1])
            _check(
                current.operating_profit
                == (None if current.trading_pnl is None else current.trading_pnl - costs[-1])
            )
            _check(current.operating_metrics is not None)

    def mathematical(value: CapitalPanelMathematical, *, matched: bool) -> None:
        _check(len(value.marked_nav) == 631 and len(value.raw_quantities) == 630)
        _check(value.baseline_nav == walk.initial_cash == value.marked_nav[0])
        _check(all(q >= 0 for q in value.raw_quantities))
        if matched:
            _check(value.exposures is not None and len(value.exposures) == 630)
            _check(value.mean_exposure is not None and 0 <= value.mean_exposure <= 1)
        else:
            _check(value.mean_exposure is None and value.exposures is None)

    mathematical(scenario.full_spy, matched=False)
    _check(scenario.cash_nav == (walk.initial_cash,) * 631)
    window(scenario.managed_spy)
    _check(scenario.managed_spy_final.trajectory_hash == scenario.managed_spy.trajectory_hash)
    for index, (path, path_candidate) in enumerate(
        zip(scenario.paths, (None, *candidates), strict=True)
    ):
        _check(path.path_index == index and path.candidate == path_candidate)
        _check(path.trajectory_hash == path.window.trajectory_hash == path.final.trajectory_hash)
        window(path.window)
        mathematical(path.matched_spy, matched=True)


def _implementation() -> CodeIdentity:
    value = resolve_code_identity(Path(__file__).resolve().parents[3], image_digest=None)
    _typed(value, CodeIdentity)
    _check(value.dirty is False and value.git_commit is not None and value.image_digest is None)
    return value


def evaluate_capital_economic_panel(
    request: CapitalEconomicPanelRequest,
) -> CapitalEconomicPanelReport:
    """Own originals and evaluate the complete frozen DEVELOPMENT family.

    No caller winners, scores, balances, observations, cached results or authority
    are accepted. This produces only REJECT or INSUFFICIENT_EVIDENCE.
    """
    try:
        with localcontext(_CONTEXT):
            _check(type(request) is CapitalEconomicPanelRequest)
            _check(_false_flags(request))
            implementation = _implementation()
            owned = _own_capital_source(request.dataset)
            cfg, _, base = _panel_inputs(request, owned)
            request = replace(
                request,
                dataset=owned.dataset,
                instruments=tuple(replace(i) for i in request.instruments),
            )
            base = replace(base, dataset=owned.dataset, instruments=request.instruments)
            source = owned.dataset
            dates = tuple(
                s.session_date
                for s in source.calendar.sessions
                if source.start <= s.session_date < source.end
            )
            used, tests, tail = dates[:1423], dates[770:1400], dates[1400:1423]
            prepared = _prepare_owned_capital_days(owned, sessions=used)
            capitals = cfg.capital_research.capital_tiers
            frictions = cfg.capital_research.round_trip_friction_pct
            scenarios = []
            labels, trading_columns, operating_columns = [], [], []
            for capital in capitals:
                for cost in frictions:
                    walk = replace(base, initial_cash=capital, roundtrip_friction_pct=cost)
                    scenario = _evaluate_scenario(
                        walk,
                        owned=owned,
                        prepared=prepared,
                        recurring_usd_per_day=request.recurring_usd_per_day,
                        sunk_research_usd=request.sunk_research_usd,
                    )
                    _validate_scenario(
                        scenario,
                        walk=walk,
                        owned=owned,
                        recurring_usd_per_day=request.recurring_usd_per_day,
                        sunk_research_usd=request.sunk_research_usd,
                    )
                    scenarios.append(scenario)
                    for path in scenario.paths:
                        trading_refs = (
                            scenario.full_spy.marked_nav,
                            scenario.managed_spy.marked_nav,
                            path.matched_spy.marked_nav,
                            scenario.cash_nav,
                        )
                        for role, reference in zip(_ROLES, trading_refs, strict=True):
                            labels.append(
                                CapitalPanelLabel(
                                    capital,
                                    cost,
                                    path.path_index,
                                    cast(
                                        Literal["full_spy", "managed_spy", "matched_spy", "cash"],
                                        role,
                                    ),
                                )
                            )
                            trading_columns.append(
                                _paired_column(path.window.marked_nav, reference, capital)
                            )
                        if request.recurring_usd_per_day is not None:
                            _check(path.window.net_nav is not None)
                            _check(scenario.managed_spy.net_nav is not None)
                            operating_refs = (
                                scenario.full_spy.marked_nav,
                                scenario.managed_spy.net_nav,
                                path.matched_spy.marked_nav,
                                scenario.cash_nav,
                            )
                            for operating_reference in operating_refs:
                                operating_columns.append(
                                    _paired_column(
                                        cast(tuple[Decimal, ...], path.window.net_nav),
                                        cast(tuple[Decimal, ...], operating_reference),
                                        capital,
                                    )
                                )
            _check(len(scenarios) == 24)
            trading = _build_family(
                "trading",
                tests,
                tuple(labels),
                tuple(trading_columns),
                capitals=capitals,
                frictions=frictions,
                seed=cfg.research.seed,
                draws=cfg.research.monte_carlo_iterations,
            )
            operating = None
            risks = None
            if request.recurring_usd_per_day is not None:
                operating = _build_family(
                    "operating",
                    tests,
                    tuple(labels),
                    tuple(operating_columns),
                    capitals=capitals,
                    frictions=frictions,
                    seed=cfg.research.seed,
                    draws=cfg.research.monte_carlo_iterations,
                )
                risks = tuple(
                    dependent_mean_risks(
                        operating.columns[index],
                        seed=cfg.research.seed,
                        block_lengths=(20, 100),
                        draws=cfg.research.monte_carlo_iterations,
                    )
                    for index in range(3, 2784, 4)
                )
            recorded = tuple(scenarios)
            decisions = tuple(
                _decide_path(
                    capital,
                    index,
                    recorded[tier * 4 : tier * 4 + 4],
                    operating=operating,
                    cash_risks=risks,
                    cfg=cfg,
                )
                for tier, capital in enumerate(capitals)
                for index in range(29)
            )
            report = _record(
                CapitalEconomicPanelReport,
                implementation,
                owned.source_hash,
                str(source.config_hash),
                prepared.input_hash,
                content_hash(source.calendar),
                content_hash(source.actions),
                _panel_hash(
                    "terms",
                    base.instruments,
                    request.episode_fee_bound,
                    request.entry_fee,
                    request.exit_fee,
                    request.weekly_review_sessions,
                    request.entry_outcome,
                    request.entry_fill_fraction,
                    request.exit_outcome,
                    request.exit_fill_fraction,
                ),
                _panel_hash(
                    "cost", frictions, request.recurring_usd_per_day, request.sunk_research_usd
                ),
                _panel_hash("protocol", _PROTOCOL),
                _panel_hash(
                    "selection",
                    "train-only-complete-positive-USDPNL-at-.40_grid-order-cash-zero",
                    tuple(f.selection for s in recorded for f in s.folds),
                ),
                _panel_hash(
                    "statistics",
                    tuple(labels),
                    cfg.research.seed,
                    (20, 100),
                    cfg.research.monte_carlo_iterations,
                    "existing-dependent-mean_and-complete-family-max-error-v1",
                ),
                _panel_hash(
                    "criteria",
                    _KEYS,
                    (">", ">=", "<=", ">=", ">", "<="),
                    tuple(c.threshold for c in decisions[0].criteria),
                    "last-four-always-unknown_no-GO_conditional-not-independent",
                ),
                used,
                dates[1423:],
                dates[769],
                tests,
                tail,
                recorded,
                trading,
                operating,
                risks,
                decisions,
                _LIMITATIONS,
            )
            _check(_implementation() == implementation)
            return report
    except (
        ValueError,
        TypeError,
        AttributeError,
        ArithmeticError,
        KeyError,
        StopIteration,
        IndexError,
        CodeIdentityError,
        OSError,
    ):
        raise ValueError("capital_economic_panel_invalid") from None
