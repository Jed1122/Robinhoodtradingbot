"""Deterministic, next-bar equity candidate comparison with explicit rejection evidence."""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from trading_bot.config import AppConfig, LoadedConfig
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.domain import Bar, ConfigHash, DataHash, InstrumentId
from trading_bot.market_data import ResearchDataManifest, content_hash
from trading_bot.research.metrics import (
    MetricValue,
    PerformanceInput,
    PerformanceMetrics,
    calculate_performance,
)
from trading_bot.research.report import (
    ResearchAttempt,
    ResearchDatasetSnapshot,
    ResearchReport,
    ResearchRunRecord,
    build_research_report,
)
from trading_bot.strategies import (
    FeaturePipeline,
    FeatureSnapshot,
    HistoricalSlice,
    Strategy,
    StrategyAction,
    StrategyContext,
)
from trading_bot.strategies.momentum import MomentumStrategy
from trading_bot.strategies.relative_strength import RelativeStrengthStrategy

_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")
_DAYS_PER_YEAR = Decimal("365.2425")
_PERIODS_PER_YEAR = 252


EquityResearchDataset = ResearchDatasetSnapshot


@dataclass(frozen=True, slots=True)
class EquityComparisonRequest:
    loaded: LoadedConfig
    code_hash: str
    code_clean: bool
    run_id: str
    dataset: EquityResearchDataset

    def __post_init__(self) -> None:
        canonical, config_hash = hash_loaded_config(
            self.loaded.config,
            self.loaded.safety_envelope,
        )
        if (
            canonical != self.loaded.canonical_json
            or config_hash != self.loaded.config_hash
        ):
            raise ValueError("loaded research configuration identity is invalid")

    @property
    def config(self) -> AppConfig:
        return self.loaded.config

    @property
    def config_hash(self) -> str:
        return str(self.loaded.config_hash)


@dataclass(frozen=True, slots=True)
class _Candidate:
    strategy_id: str
    family: str
    version: str
    parameter_hash: str
    parameters: tuple[tuple[str, str], ...]
    lookback: int
    short_window: int
    top_n: int | None
    grid_position: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _SimulationResult:
    metrics: PerformanceMetrics
    fold_total_returns_pct: tuple[Decimal, ...]
    opportunity_pnl: tuple[Decimal, ...]


@dataclass(frozen=True, slots=True)
class _AttemptDraft:
    candidate: _Candidate
    baseline: _SimulationResult
    stressed: _SimulationResult
    benchmark_total_return_pct: Decimal
    monte_carlo_loss_probability_pct: Decimal
    maximum_single_opportunity_profit_contribution_pct: Decimal
    parameter_neighbor_stressed_total_returns_pct: tuple[Decimal | None, ...]
    reason_codes: tuple[str, ...]


def _candidate_grid(config: AppConfig) -> tuple[_Candidate, ...]:
    settings = config.equity_strategies
    requested = set(settings.research_candidate_strategy_ids)
    candidates: list[_Candidate] = []
    if "equity_momentum" in requested:
        for short_index, short in enumerate(settings.short_windows):
            for long_index, long in enumerate(settings.long_windows):
                strategy = MomentumStrategy(short_window=short, long_window=long)
                candidates.append(
                    _Candidate(
                        strategy_id=strategy.descriptor.strategy_id,
                        family=strategy.descriptor.family,
                        version=strategy.descriptor.version,
                        parameter_hash=str(strategy.descriptor.parameter_hash),
                        parameters=(
                            ("long_window", str(long)),
                            ("short_window", str(short)),
                        ),
                        lookback=long,
                        short_window=short,
                        top_n=None,
                        grid_position=(short_index, long_index),
                    )
                )
    if "equity_relative_strength" in requested:
        short = min(settings.short_windows)
        for lookback_index, lookback in enumerate(settings.long_windows):
            for top_index, top_n in enumerate(settings.research_relative_strength_top_n):
                relative_strength = RelativeStrengthStrategy(
                    lookback_window=lookback,
                    top_n=top_n,
                )
                candidates.append(
                    _Candidate(
                        strategy_id=relative_strength.descriptor.strategy_id,
                        family=relative_strength.descriptor.family,
                        version=relative_strength.descriptor.version,
                        parameter_hash=str(
                            relative_strength.descriptor.parameter_hash
                        ),
                        parameters=(
                            ("lookback_window", str(lookback)),
                            ("top_n", str(top_n)),
                        ),
                        lookback=lookback,
                        short_window=short,
                        top_n=top_n,
                        grid_position=(lookback_index, top_index),
                    )
                )
    return tuple(candidates)


def _validate_dataset(
    request: EquityComparisonRequest,
) -> tuple[dict[str, tuple[Bar, ...]], tuple[str, ...]]:
    config = request.config
    expected = config.equity_strategies.research_universe_symbols
    observed = dict(request.dataset.bars_by_symbol)
    reasons = set(request.dataset.collection_reason_codes)
    if tuple(observed) != expected:
        reasons.add("configured_universe_data_incomplete")
    if set(observed) != set(expected):
        return observed, tuple(sorted(reasons))

    reference_times: tuple[datetime, ...] | None = None
    for symbol in expected:
        bars = observed[symbol]
        if len(bars) < config.research.minimum_history_bars:
            reasons.add("insufficient_history")
        times = tuple(bar.starts_at for bar in bars)
        if times != tuple(sorted(set(times))):
            reasons.add("unordered_or_duplicate_bars")
        if reference_times is None:
            reference_times = times
        elif times != reference_times:
            reasons.add("cross_symbol_history_unaligned")
        for bar in bars:
            if (
                str(bar.instrument_id) != symbol
                or bar.interval is not config.equity_strategies.bar_interval
                or bar.ends_at > request.dataset.as_of
                or bar.volume <= 0
            ):
                reasons.add("invalid_research_bar")
            if bar.interpolated:
                reasons.add("interpolation_status_unverified_or_interpolated")
    return observed, tuple(sorted(reasons))


def _manifest(
    request: EquityComparisonRequest,
    reasons: tuple[str, ...],
) -> ResearchDataManifest:
    cleaned = request.dataset.cleaned_hashes
    return ResearchDataManifest.create(
        raw_hashes=request.dataset.raw_hashes,
        cleaned_hashes=cleaned,
        corporate_action_coverage=(
            "provider-requested split adjustment only; dividends, distributions, "
            "and point-in-time corporate-action provenance unverified"
        ),
        point_in_time_universe=False,
        survivorship_limitations=(
            "The operator-approved fixed ETF candidate list was selected with present-day "
            "knowledge and is not a point-in-time constituent history.",
        ),
        licensing_limitations=(
            "Authenticated Robinhood Trading MCP data is retained only in private evidence "
            "storage; downstream redistribution rights were not established.",
        ),
        known_gaps=tuple(sorted(set(reasons))),
    )


def _fold_ranges(config: AppConfig, count: int) -> tuple[tuple[int, int], ...]:
    start = max(config.equity_strategies.long_windows) + config.research.embargo_bars
    available = count - start
    folds = config.research.walk_forward_folds
    if available < folds * config.research.minimum_test_bars_per_fold:
        return ()
    base = available // folds
    remainder = available % folds
    result: list[tuple[int, int]] = []
    cursor = start
    for index in range(folds):
        size = base + (1 if index < remainder else 0)
        result.append((cursor, cursor + size))
        cursor += size
    return tuple(result)


def _selected_symbols(
    candidate: _Candidate,
    *,
    signal_index: int,
    symbols: tuple[str, ...],
    bars_by_symbol: dict[str, tuple[Bar, ...]],
    config_hash: str,
) -> tuple[str, ...]:
    vectors = []
    for symbol in symbols:
        history = bars_by_symbol[symbol][signal_index - candidate.lookback + 1 : signal_index + 1]
        if len(history) != candidate.lookback:
            return ()
        pipeline = FeaturePipeline(
            short_window=candidate.short_window,
            long_window=candidate.lookback,
        )
        history_hash = content_hash(
            {
                "candidate": candidate.parameter_hash,
                "row_hashes": tuple(bar.data_hash for bar in history),
                "symbol": symbol,
            }
        )
        vectors.append(
            pipeline.compute(
                HistoricalSlice(
                    InstrumentId(symbol),
                    history,
                    None,
                    DataHash(str(history_hash)),
                ),
                as_of=history[-1].ends_at,
            )
        )
    observed_at = bars_by_symbol[symbols[0]][signal_index].ends_at
    snapshot = FeatureSnapshot(
        observed_at,
        tuple(vectors),
        content_hash(tuple(vectors)),
    )
    context = StrategyContext(
        observed_at,
        snapshot,
        ConfigHash(config_hash),
        tuple(InstrumentId(symbol) for symbol in symbols),
    )
    if candidate.strategy_id == "equity_momentum":
        strategy: Strategy = MomentumStrategy(
            short_window=candidate.short_window,
            long_window=candidate.lookback,
            version=candidate.version,
        )
    else:
        if candidate.top_n is None:
            raise RuntimeError("relative-strength candidate is missing top-N")
        strategy = RelativeStrengthStrategy(
            lookback_window=candidate.lookback,
            top_n=candidate.top_n,
            version=candidate.version,
        )
    return tuple(
        str(decision.instrument_id)
        for decision in strategy.decide(context)
        if decision.action is StrategyAction.ENTER_LONG
    )


def _benchmark_selector(symbol: str) -> Callable[[int], tuple[str, ...]]:
    def select(_: int) -> tuple[str, ...]:
        return (symbol,)

    return select


def _simulate(
    *,
    config: AppConfig,
    bars_by_symbol: dict[str, tuple[Bar, ...]],
    fold_ranges: tuple[tuple[int, int], ...],
    select: Callable[[int], tuple[str, ...]],
    cost_multiplier: Decimal,
) -> _SimulationResult:
    symbols = config.equity_strategies.research_universe_symbols
    gross_fraction = config.portfolio.max_total_gross_exposure_pct / _HUNDRED
    spread_rate = (
        config.costs.assumed_equity_spread_pct / Decimal("2") * cost_multiplier / _HUNDRED
    )
    slippage_rate = config.costs.assumed_slippage_pct * cost_multiplier / _HUNDRED
    commission = config.costs.equity_commission_usd * cost_multiplier
    starting_capital = config.portfolio.expected_starting_equity_usd
    capital = starting_capital
    equity_curve: list[tuple[datetime, Decimal]] = []
    period_returns: list[Decimal] = []
    opportunity_pnl: list[Decimal] = []
    fold_returns: list[Decimal] = []
    gross_exposure: list[Decimal] = []
    net_exposure: list[Decimal] = []
    turnover_notional = _ZERO
    spread_cost = _ZERO
    slippage_cost = _ZERO
    fees = _ZERO
    periods_in_market = 0
    previous_equity = capital
    equity_curve.append(
        (
            bars_by_symbol[symbols[0]][fold_ranges[0][0]].starts_at,
            capital,
        )
    )

    for fold_start, fold_end in fold_ranges:
        fold_initial = capital
        cash = capital
        holdings = {symbol: _ZERO for symbol in symbols}
        opportunity_start = capital
        for index in range(fold_start, fold_end):
            opens = {symbol: bars_by_symbol[symbol][index].open for symbol in symbols}
            closes = {symbol: bars_by_symbol[symbol][index].close for symbol in symbols}
            equity_at_open = cash + sum(
                (holdings[symbol] * opens[symbol] for symbol in symbols),
                _ZERO,
            )
            if (index - fold_start) % config.equity_strategies.research_rebalance_bars == 0:
                if index != fold_start:
                    opportunity_pnl.append(equity_at_open - opportunity_start)
                    opportunity_start = equity_at_open
                selected = select(index - 1)
                selected_set = set(selected)
                target_each = (
                    equity_at_open * gross_fraction / Decimal(len(selected))
                    if selected
                    else _ZERO
                )
                for symbol in symbols:
                    target_shares = (
                        target_each / opens[symbol] if symbol in selected_set else _ZERO
                    )
                    delta = target_shares - holdings[symbol]
                    if delta == 0:
                        continue
                    notional = abs(delta) * opens[symbol]
                    current_spread_cost = notional * spread_rate
                    current_slippage_cost = notional * slippage_rate
                    cash -= delta * opens[symbol]
                    cash -= current_spread_cost + current_slippage_cost + commission
                    holdings[symbol] = target_shares
                    turnover_notional += notional
                    spread_cost += current_spread_cost
                    slippage_cost += current_slippage_cost
                    fees += commission

            exposure = sum(
                (holdings[symbol] * closes[symbol] for symbol in symbols),
                _ZERO,
            )
            equity = cash + exposure
            if index == fold_end - 1:
                liquidation_notional = exposure
                liquidation_spread = liquidation_notional * spread_rate
                liquidation_slippage = liquidation_notional * slippage_rate
                liquidation_fees = commission * sum(
                    1 for quantity in holdings.values() if quantity != 0
                )
                cash += liquidation_notional
                cash -= liquidation_spread + liquidation_slippage + liquidation_fees
                turnover_notional += liquidation_notional
                spread_cost += liquidation_spread
                slippage_cost += liquidation_slippage
                fees += liquidation_fees
                holdings = {symbol: _ZERO for symbol in symbols}
                equity = cash
                opportunity_pnl.append(equity - opportunity_start)
            if previous_equity <= 0:
                raise ValueError("research portfolio equity became nonpositive")
            period_returns.append(equity / previous_equity - _ONE)
            equity_curve.append((bars_by_symbol[symbols[0]][index].ends_at, equity))
            gross_exposure.append(exposure)
            net_exposure.append(exposure)
            if exposure > 0:
                periods_in_market += 1
            previous_equity = equity
            capital = equity
        fold_returns.append((capital / fold_initial - _ONE) * _HUNDRED)

    first_at = equity_curve[0][0]
    last_at = equity_curve[-1][0]
    elapsed_days = Decimal((last_at - first_at).total_seconds()) / Decimal("86400")
    source = PerformanceInput(
        equity_curve=tuple(equity_curve),
        period_returns=tuple(period_returns),
        trade_pnl=tuple(opportunity_pnl),
        periods_per_year=_PERIODS_PER_YEAR,
        elapsed_years=max(elapsed_days / _DAYS_PER_YEAR, Decimal("0.000001")),
        turnover=turnover_notional / starting_capital * _HUNDRED,
        gross_exposure=tuple(gross_exposure),
        net_exposure=tuple(net_exposure),
        time_in_market_fraction=Decimal(periods_in_market) / Decimal(len(equity_curve)),
        spread_cost=spread_cost,
        slippage_cost=slippage_cost,
        fees=fees,
        independent_opportunities=len(opportunity_pnl),
    )
    return _SimulationResult(
        calculate_performance(source),
        tuple(fold_returns),
        tuple(opportunity_pnl),
    )


def _monte_carlo_loss_probability(
    trades: tuple[Decimal, ...],
    *,
    samples: int,
    seed: int,
) -> Decimal:
    if not trades:
        return _HUNDRED
    rng = random.Random(seed)  # nosec B311 - deterministic research sampling
    losses = 0
    for _ in range(samples):
        total = sum(
            (trades[rng.randrange(len(trades))] for _ in trades),
            _ZERO,
        )
        losses += total <= 0
    return Decimal(losses) * _HUNDRED / Decimal(samples)


def _metric_decimal(metric: MetricValue) -> Decimal | None:
    value = metric.value
    return value if isinstance(value, Decimal) else None


def _draft_attempts(
    request: EquityComparisonRequest,
    bars_by_symbol: dict[str, tuple[Bar, ...]],
    folds: tuple[tuple[int, int], ...],
) -> tuple[_AttemptDraft, ...]:
    config = request.config
    benchmark = _simulate(
        config=config,
        bars_by_symbol=bars_by_symbol,
        fold_ranges=folds,
        select=_benchmark_selector(config.equity_strategies.research_benchmark_symbol),
        cost_multiplier=config.costs.stressed_cost_multiplier,
    )
    benchmark_return = _metric_decimal(benchmark.metrics.total_return_pct) or _ZERO
    result: list[_AttemptDraft] = []
    for candidate_index, candidate in enumerate(_candidate_grid(config)):
        def selector(index: int, current: _Candidate = candidate) -> tuple[str, ...]:
            return _selected_symbols(
                current,
                signal_index=index,
                symbols=config.equity_strategies.research_universe_symbols,
                bars_by_symbol=bars_by_symbol,
                config_hash=request.config_hash,
            )
        baseline = _simulate(
            config=config,
            bars_by_symbol=bars_by_symbol,
            fold_ranges=folds,
            select=selector,
            cost_multiplier=_ONE,
        )
        stressed = _simulate(
            config=config,
            bars_by_symbol=bars_by_symbol,
            fold_ranges=folds,
            select=selector,
            cost_multiplier=config.costs.stressed_cost_multiplier,
        )
        reasons: set[str] = {"edge_persistence_rationale"}
        expectancy = _metric_decimal(stressed.metrics.expectancy)
        if expectancy is None or expectancy <= 0:
            reasons.add("nonpositive_after_cost_oos_expectancy")
        drawdown = _metric_decimal(stressed.metrics.maximum_drawdown_pct)
        if (
            drawdown is None
            or abs(drawdown) > config.research.maximum_stressed_drawdown_pct
        ):
            reasons.add("stressed_drawdown_breach")
        opportunities = stressed.metrics.independent_opportunities.value
        if (
            not isinstance(opportunities, int)
            or opportunities < config.research.minimum_independent_opportunities
        ):
            reasons.add("insufficient_independent_opportunities")
        if (
            sum(value > 0 for value in stressed.fold_total_returns_pct)
            < config.research.minimum_positive_walk_forward_folds
        ):
            reasons.add("insufficient_positive_walk_forward_folds")
        positive = tuple(value for value in stressed.opportunity_pnl if value > 0)
        contribution = (
            _HUNDRED
            if not positive
            else max(positive) * _HUNDRED / sum(positive, _ZERO)
        )
        if (
            contribution
            > config.research.maximum_single_opportunity_profit_contribution_pct
        ):
            reasons.add("one_trade_dependence")
        total_return = (
            _metric_decimal(stressed.metrics.total_return_pct) or -_HUNDRED
        )
        if (
            total_return - benchmark_return
            < config.research.minimum_benchmark_excess_return_pct
        ):
            reasons.add("benchmark_not_beaten")
        monte_carlo = _monte_carlo_loss_probability(
            stressed.opportunity_pnl,
            samples=config.research.monte_carlo_iterations,
            seed=config.research.seed + candidate_index,
        )
        if monte_carlo > config.research.maximum_monte_carlo_loss_probability_pct:
            reasons.add("monte_carlo_loss_probability_breach")
        result.append(
            _AttemptDraft(
                candidate,
                baseline,
                stressed,
                benchmark_return,
                monte_carlo,
                contribution,
                (),
                tuple(sorted(reasons)),
            )
        )
    return tuple(result)


def _apply_parameter_stability(
    drafts: tuple[_AttemptDraft, ...],
) -> tuple[_AttemptDraft, ...]:
    updated: list[_AttemptDraft] = []
    for draft in drafts:
        neighbors = tuple(
            other
            for other in drafts
            if other.candidate.family == draft.candidate.family
            and sum(
                left != right
                for left, right in zip(
                    other.candidate.grid_position,
                    draft.candidate.grid_position,
                    strict=True,
                )
            )
            == 1
        )
        neighbor_returns = tuple(
            _metric_decimal(item.stressed.metrics.total_return_pct)
            for item in neighbors
        )
        reasons = set(draft.reason_codes)
        stable = bool(neighbor_returns) and all(
            value is not None and value > 0 for value in neighbor_returns
        )
        if not stable:
            reasons.add("unstable_parameters")
        updated.append(
            replace(
                draft,
                parameter_neighbor_stressed_total_returns_pct=neighbor_returns,
                reason_codes=tuple(sorted(reasons)),
            )
        )
    return tuple(updated)


def _empty_attempts(config: AppConfig, reason: str) -> tuple[ResearchAttempt, ...]:
    return tuple(
        ResearchAttempt(
            family=candidate.family,
            parameter_hash=candidate.parameter_hash,
            status="rejected",
            reason_codes=(reason,),
            metrics=None,
            strategy_id=candidate.strategy_id,
            strategy_version=candidate.version,
            parameters=candidate.parameters,
        )
        for candidate in _candidate_grid(config)
    )


def run_equity_candidate_comparison(
    request: EquityComparisonRequest,
) -> ResearchReport:
    """Compare all configured candidates without manufacturing promotion eligibility."""

    observed, dataset_reasons = _validate_dataset(request)
    manifest = _manifest(request, dataset_reasons)
    config = request.config
    run_reasons = {
        "candidate_parameter_identity_not_promotion_bound",
        "corporate_action_coverage_incomplete",
        "exit_policy_not_integrated",
        "multiple_testing_unresolved",
        "paper_config_binding_unavailable",
        "pbo_unavailable",
        "point_in_time_universe_unavailable",
        "raw_response_preimage_unavailable",
        "simulated_fill_assumptions_unvalidated",
    }
    run_reasons.update(dataset_reasons)
    if not config.research.assumptions_validated:
        run_reasons.add("research_assumptions_unvalidated")
    if not config.research.evidence_promotable:
        run_reasons.add("research_promotion_disabled")
    if not request.code_clean:
        run_reasons.add("code_identity_unverified")

    folds: tuple[tuple[int, int], ...] = ()
    if set(observed) == set(config.equity_strategies.research_universe_symbols):
        folds = _fold_ranges(config, min(len(value) for value in observed.values()))
    if not folds:
        run_reasons.add("walk_forward_sample_incomplete")
        attempts = _empty_attempts(config, "walk_forward_sample_incomplete")
    elif {
        "configured_universe_data_incomplete",
        "cross_symbol_history_unaligned",
        "invalid_research_bar",
        "unordered_or_duplicate_bars",
    } & set(dataset_reasons):
        attempts = _empty_attempts(config, "research_dataset_invalid")
    else:
        drafts = _apply_parameter_stability(_draft_attempts(request, observed, folds))
        attempts = tuple(
            ResearchAttempt(
                family=draft.candidate.family,
                parameter_hash=draft.candidate.parameter_hash,
                status=(
                    "accepted"
                    if draft.reason_codes == ("edge_persistence_rationale",)
                    else "rejected"
                ),
                reason_codes=draft.reason_codes,
                metrics=draft.baseline.metrics,
                strategy_id=draft.candidate.strategy_id,
                strategy_version=draft.candidate.version,
                parameters=draft.candidate.parameters,
                stressed_metrics=draft.stressed.metrics,
                fold_total_returns_pct=draft.stressed.fold_total_returns_pct,
                benchmark_total_return_pct=draft.benchmark_total_return_pct,
                monte_carlo_loss_probability_pct=(
                    draft.monte_carlo_loss_probability_pct
                ),
                maximum_single_opportunity_profit_contribution_pct=(
                    draft.maximum_single_opportunity_profit_contribution_pct
                ),
                parameter_neighbor_stressed_total_returns_pct=(
                    draft.parameter_neighbor_stressed_total_returns_pct
                ),
            )
            for draft in drafts
        )

    comparison_identity = content_hash(
        {
            "candidate_parameters": tuple(
                (attempt.strategy_id, attempt.parameter_hash) for attempt in attempts
            ),
            "universe": config.equity_strategies.research_universe_symbols,
            "version": "equity-candidate-comparison-v1",
        }
    )
    run = ResearchRunRecord(
        run_id=request.run_id,
        strategy_version=f"equity-candidate-comparison-v1-{comparison_identity[:16]}",
        code_hash=request.code_hash,
        config_hash=request.config_hash,
        data_manifest_hash=str(manifest.manifest_hash),
        cost_assumptions=(
            (
                "one_way_spread_pct",
                str(config.costs.assumed_equity_spread_pct / Decimal("2")),
            ),
            ("one_way_slippage_pct", str(config.costs.assumed_slippage_pct)),
            ("commission_usd_per_order", str(config.costs.equity_commission_usd)),
            ("stressed_cost_multiplier", str(config.costs.stressed_cost_multiplier)),
        ),
        parameter_grid=(
            ("short_window", tuple(str(value) for value in config.equity_strategies.short_windows)),
            ("long_window", tuple(str(value) for value in config.equity_strategies.long_windows)),
            (
                "relative_strength_top_n",
                tuple(
                    str(value)
                    for value in config.equity_strategies.research_relative_strength_top_n
                ),
            ),
        ),
        data_limitations=(
            manifest.corporate_action_coverage,
            *manifest.survivorship_limitations,
            *manifest.licensing_limitations,
            (
                "The exploratory accounting loop assumes complete next-open target fills; "
                "configured rejection, no-fill, partial-fill, latency, and cancel-race "
                "assumptions are not integrated."
            ),
            (
                "Configured stop-loss, reward-to-risk, maximum-holding, and regime-exit "
                "policies are not integrated into this candidate comparison."
            ),
            *(
                f"Known gap or rejection: {reason}"
                for reason in manifest.known_gaps
            ),
        ),
        code_clean=request.code_clean,
        universe_symbols=config.equity_strategies.research_universe_symbols,
        benchmark_symbol=config.equity_strategies.research_benchmark_symbol,
        provider_evidence_hash=request.dataset.provider_evidence_hash,
        run_reason_codes=tuple(sorted(run_reasons)),
        data_manifest=manifest,
        dataset_snapshot=request.dataset,
    )
    return build_research_report(run, attempts=attempts)


__all__ = [
    "EquityComparisonRequest",
    "EquityResearchDataset",
    "run_equity_candidate_comparison",
]
