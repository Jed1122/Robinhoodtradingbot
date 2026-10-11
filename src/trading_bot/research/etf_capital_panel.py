"""Original-source DEVELOPMENT panel; never qualification or promotion authority."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, localcontext
from itertools import pairwise
from typing import TYPE_CHECKING, Literal, cast

from trading_bot.config import LoadedConfig
from trading_bot.config.capital_research import CapitalResearchAppConfig
from trading_bot.config.loader import restore_loaded_config
from trading_bot.domain import Instrument, require_bounded_decimal
from trading_bot.market_data.etf_capital_dataset import CapitalResearchDataset
from trading_bot.market_data.etf_capital_owned import _OwnedCapitalSource
from trading_bot.research.etf_capital_economic_window import _capital_economic_window
from trading_bot.research.etf_capital_feasibility import _config
from trading_bot.research.etf_capital_matched import _capital_matched_values, _CapitalMatchedTerms
from trading_bot.research.etf_capital_panel_models import (
    _FLAGS,
    _KEYS,
    _ROLES,
    _TAGS,
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
    _panel_hash,
    _PanelRecord,
    _typed,
)
from trading_bot.research.etf_capital_path_economics import _ratio
from trading_bot.research.etf_capital_prepared import _PreparedCapitalInput
from trading_bot.research.etf_capital_selection import (
    CapitalTrainingOutcome,
    CapitalTrainingSelection,
)
from trading_bot.research.etf_capital_signals import CapitalCandidate, CapitalWalkForwardFold
from trading_bot.research.etf_resampling import (
    EtfBlockRisk,
    dependent_capital_simultaneous_mean_intervals,
)
from trading_bot.simulation.etf_capital_constrained import CapitalConstrainedResult
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
        _check(all(getattr(request, flag) is False for flag in _FLAGS))
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
        _check(all(getattr(trajectory, flag) is False for flag in _FLAGS))
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
    _check(all(getattr(result, flag) is False for flag in _FLAGS))
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
