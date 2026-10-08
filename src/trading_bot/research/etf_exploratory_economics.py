"""Shared policy-neutral, assumption-only arithmetic; never economic admission."""

from collections import Counter
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, localcontext
from typing import Literal

from trading_bot.config import LoadedConfig
from trading_bot.config.loader import restore_loaded_config
from trading_bot.domain import Side
from trading_bot.domain.decimal_utils import require_bounded_decimal
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_benchmark import (
    EtfBenchmarkBar,
    EtfBenchmarkDistribution,
    EtfBenchmarkRequest,
    _ratio,
    run_etf_benchmark,
)
from trading_bot.research.etf_daily_protocol import (
    EtfDailyBar,
    _check,
    _DailyRecord,
)
from trading_bot.research.etf_monthly_protocol import _markers, _MonthlyRecord
from trading_bot.research.etf_paired_economics import EtfMatchedReturns, analyze_etf_matched_returns
from trading_bot.research.etf_resampling import EtfBlockRisk
from trading_bot.research.metrics import (
    MetricValue,
    PerformanceInput,
    PerformanceMetrics,
    calculate_performance,
)
from trading_bot.simulation.etf_account import EtfAccountEvent, EtfAccountResult
from trading_bot.simulation.etf_exploratory_lifecycle import EtfDailyAttempt, EtfDailyPoint
from trading_bot.simulation.lifecycle_accounting import _context

ZERO = Decimal("0")
_COSTS = (
    ("zero_cost_mathematical_reference", ZERO, ZERO, ZERO),
    ("five_bps_uncalibrated", Decimal("5"), Decimal(".01"), Decimal(".10")),
    ("twenty_five_bps_uncalibrated", Decimal("25"), Decimal(".01"), Decimal(".10")),
)
_BUDGETS = (
    ("zero_data_zero_compute_unverified", ZERO, ZERO),
    ("zero_data_twelve_compute_unverified", ZERO, Decimal("12")),
    ("current_paid_zero_compute", Decimal("99"), ZERO),
    ("current_paid_twelve_compute", Decimal("99"), Decimal("12")),
)


@dataclass(frozen=True, slots=True)
class EtfExploratoryTrace(_MonthlyRecord):
    loaded: LoadedConfig
    initial_cash: Decimal
    risk_equity_reference: Decimal
    seed: int
    per_side_cost_bps: Decimal
    side_fee: Decimal
    bars: tuple[EtfDailyBar, ...]
    distributions: tuple[EtfBenchmarkDistribution, ...]
    points: tuple[EtfDailyPoint, ...]
    account: EtfAccountResult
    events: tuple[EtfAccountEvent, ...]
    attempts: tuple[EtfDailyAttempt, ...]
    scheduled_entries: int
    incomplete_reasons: tuple[str, ...]
    run_hash: str

    def __post_init__(self) -> None:
        _markers(self)
        _check(type(self.loaded) is LoadedConfig)
        restored = restore_loaded_config(self.loaded.canonical_json, self.loaded.config_hash)
        _check(restored == self.loaded)
        for amount in (self.initial_cash, self.risk_equity_reference):
            require_bounded_decimal(amount, "research capital", positive=True)
        _check(type(self.points) is tuple and len(self.points) <= 10000)
        _check(type(self.bars) is tuple and len(self.bars) <= 10000)
        days = tuple(p.session_date for p in self.points)
        _check(days == tuple(sorted(set(days))))
        _check(set(days) <= {r.session_date for r in self.bars})
        _check(
            self.account.execution_enabled is False and self.account.evidence_promotable is False
        )


@dataclass(frozen=True, slots=True)
class EtfExploratoryUncertainty:
    seed: int
    paired_input_hash: str
    paired_report_hash: str
    vs_constrained: tuple[EtfBlockRisk, ...]
    vs_cash: tuple[EtfBlockRisk, ...]
    constrained_lower_bound: Decimal
    cash_lower_bound: Decimal


@dataclass(frozen=True, slots=True)
class EtfExploratorySizing(_DailyRecord):
    scheduled_entries: int
    attempted_entries: int
    admitted_entries: int
    denied_entries: int
    denial_counts: tuple[tuple[str, int], ...]
    minimum_quantity: Decimal | None
    maximum_quantity: Decimal | None
    minimum_notional: Decimal | None
    maximum_notional: Decimal | None


@dataclass(frozen=True, slots=True)
class EtfExploratoryScore(_DailyRecord):
    initial_cash: Decimal
    cost_scenario: str
    operating_scenario: str
    monthly_data_assumption: Decimal
    monthly_compute_assumption: Decimal
    run_hash: str
    account_hash: str
    evaluation_start: date | None
    evaluation_end: date | None
    evaluation_sessions: int
    completed_episodes: int
    independent_opportunities: None
    fees: Decimal
    realized_trading_pnl: Decimal | None
    marked_trading_pnl: Decimal | None
    operating_cost: Decimal | None
    operating_profit_proxy: Decimal | None
    reference_notional: Decimal | None
    candidate_mean_exposure: Decimal | None
    reference_mean_exposure: Decimal | None
    constrained_benchmark_pnl: Decimal | None
    cash_benchmark_pnl: Decimal | None
    risk_reference_drawdown_pct: Decimal | None
    performance: PerformanceMetrics | None
    uncertainty: EtfExploratoryUncertainty | None
    screening_verdict: Literal["REJECT", "PROCEED_TO_FURTHER_RESEARCH", "INSUFFICIENT_EVIDENCE"]
    incomplete_reasons: tuple[str, ...]
    entry_sizing: EtfExploratorySizing


def _sizing(out: EtfExploratoryTrace) -> EtfExploratorySizing:
    attempts = tuple(a for a in out.attempts if a.side is Side.BUY)
    denied = tuple(a for a in attempts if not a.admitted)
    fills = tuple(e.fill for e in out.events if e.fill is not None and e.fill.side is Side.BUY)
    quantities = tuple(fill.quantity for fill in fills)
    notionals = tuple(fill.quantity * fill.price for fill in fills)
    return EtfExploratorySizing(
        out.scheduled_entries,
        len(attempts),
        sum(a.admitted for a in attempts),
        len(denied),
        tuple(sorted(Counter(a.reason for a in denied).items())),
        min(quantities) if quantities else None,
        max(quantities) if quantities else None,
        min(notionals) if notionals else None,
        max(notionals) if notionals else None,
    )


def _renewals(first: date, last: date) -> int:
    # The fixed anchor is the 26th, so every hypothetical monthly anniversary
    # exists; this does not silently substitute calendar-month or daily billing.
    return max(
        1,
        (last.year - first.year) * 12
        + last.month
        - first.month
        + (1 if last.day >= first.day else 0),
    )


def _returns(nav: tuple[Decimal, ...], origin: Decimal) -> tuple[Decimal, ...]:
    """Fixed-capital P&L fractions for paired uncertainty, not performance."""
    previous = origin
    changes = []
    for value in nav:
        changes.append(_ratio(value - previous, origin))
        previous = value
    return tuple(changes)


def _period_returns(nav: tuple[Decimal, ...], origin: Decimal) -> tuple[Decimal, ...] | None:
    """Conventional returns; never invent a denominator after nonpositive NAV."""
    previous = origin
    changes = []
    for value in nav:
        if previous <= 0:
            return None
        changes.append(_ratio(value - previous, previous))
        previous = value
    return tuple(changes)


def _performance(out: EtfExploratoryTrace) -> PerformanceMetrics:
    origin = out.initial_cash
    points = out.points
    bars = {row.session_date: row for row in out.bars}
    nav = tuple(point.liquidation_proxy for point in points)
    period_returns = _period_returns(nav, origin)
    elapsed = _ratio(
        Decimal((points[-1].session_date - points[0].session_date).days + 1), Decimal("365.25")
    )
    trades = tuple(
        episode.net_cash_flow
        for episode in out.account.trial.episodes
        if episode.complete and episode.net_cash_flow is not None
    )
    turnover = sum(
        (event.fill.quantity * event.fill.price for event in out.events if event.fill is not None),
        ZERO,
    )
    exposures = tuple(point.marked_nav - point.cash - point.receivable for point in points)
    with localcontext(_context(exact=False)) as context:
        context.prec = 64
        metrics = calculate_performance(
            PerformanceInput(
                (
                    (bars[points[0].session_date].raw.starts_at, origin),
                    *((bars[p.session_date].raw.ends_at, p.liquidation_proxy) for p in points),
                ),
                period_returns if period_returns is not None else (),
                trades,
                252,
                elapsed,
                _ratio(turnover, origin),
                exposures,
                exposures,
                _ratio(Decimal(sum(point.shares > 0 for point in points)), Decimal(len(points))),
                ZERO,
                ZERO,
                out.account.fees,
                0,
            )
        )
    if period_returns is None:
        undefined = MetricValue(None, "undefined_nonpositive_prior_nav")
        metrics = replace(
            metrics,
            annualized_volatility_pct=undefined,
            sharpe=undefined,
            sortino=undefined,
        )
    return replace(
        metrics,
        spread_cost=MetricValue(None, "unmeasured_component_embedded_in_assumed_prices"),
        slippage_cost=MetricValue(None, "unmeasured_component_embedded_in_assumed_prices"),
        independent_opportunities=MetricValue(None, "not_established"),
        time_in_market_pct=replace(
            metrics.time_in_market_pct, status="daily_close_occupancy_proxy"
        ),
    )


def score_etf_exploratory_trace(
    out: EtfExploratoryTrace,
    *,
    cost_name: str,
    budget_name: str,
    data_monthly: Decimal,
    compute_monthly: Decimal,
) -> EtfExploratoryScore:
    _check(type(out) is EtfExploratoryTrace)
    out.__post_init__()
    for amount in (data_monthly, compute_monthly):
        require_bounded_decimal(amount, "operating assumption", nonnegative=True)
    budget = (budget_name, data_monthly, compute_monthly)
    episodes = sum(episode.complete for episode in out.account.trial.episodes)
    if not out.points:
        return EtfExploratoryScore(
            out.initial_cash,
            cost_name,
            budget_name,
            data_monthly,
            compute_monthly,
            out.run_hash,
            out.account.state_hash,
            None,
            None,
            0,
            episodes,
            None,
            out.account.fees,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "INSUFFICIENT_EVIDENCE",
            out.incomplete_reasons,
            _sizing(out),
        )
    cfg = out.loaded.config
    bars = {row.session_date: row for row in out.bars}
    points = out.points
    origin = out.initial_cash
    mean_exposure = _ratio(
        sum((p.marked_nav - p.cash - p.receivable for p in points), ZERO), Decimal(len(points))
    )
    first_open = bars[points[0].session_date].raw.open * (1 + out.per_side_cost_bps / 10000)
    unit_exposure = _ratio(
        sum((bars[p.session_date].raw.close for p in points), ZERO),
        Decimal(len(points)) * first_open,
    )
    reference_notional = min(
        cfg.activity.max_order_notional_usd,
        out.risk_equity_reference * cfg.position_risk.max_position_notional_pct / 100,
        _ratio(mean_exposure, unit_exposure),
    )
    reference = run_etf_benchmark(
        EtfBenchmarkRequest(
            tuple(
                EtfBenchmarkBar(
                    p.session_date,
                    bars[p.session_date].raw.open,
                    bars[p.session_date].raw.close,
                    p.source_hash,
                )
                for p in points
            ),
            out.distributions,
            origin,
            reference_notional,
            out.per_side_cost_bps,
            out.side_fee,
            out.side_fee,
        )
    )
    reference_mean = _ratio(
        sum(
            (p.close_midpoint_nav - p.cash - p.dividend_receivable for p in reference.points), ZERO
        ),
        Decimal(len(points)),
    )
    monthly = data_monthly + compute_monthly
    costs = tuple(
        Decimal(_renewals(points[0].session_date, p.session_date)) * monthly for p in points
    )
    candidate_nav = tuple(p.liquidation_proxy for p in points)
    trading_pnl = candidate_nav[-1] - origin
    operating_profit = trading_pnl - costs[-1]
    risk_peak = origin
    risk_drawdown = ZERO
    for value in candidate_nav:
        risk_peak = max(risk_peak, value)
        risk_drawdown = max(risk_drawdown, (risk_peak - value) / out.risk_equity_reference * 100)
    uncertainty = None
    if len(points) >= 100:
        candidate_returns = _returns(
            tuple(value - cost for value, cost in zip(candidate_nav, costs, strict=True)), origin
        )
        reference_returns = _returns(tuple(p.liquidation_proxy for p in reference.points), origin)
        matched = EtfMatchedReturns(
            tuple(p.session_date for p in points),
            candidate_returns,
            reference_returns,
            (ZERO,) * len(points),
            content_hash((out.run_hash, reference.result_hash, budget)),
        )
        paired = analyze_etf_matched_returns(matched, seed=out.seed)
        uncertainty = EtfExploratoryUncertainty(
            paired.seed,
            matched.input_hash,
            paired.report_hash,
            paired.candidate_vs_constrained,
            paired.candidate_vs_cash,
            paired.constrained_lower_bound,
            paired.cash_lower_bound,
        )
    verdict: Literal["REJECT", "PROCEED_TO_FURTHER_RESEARCH", "INSUFFICIENT_EVIDENCE"]
    if out.incomplete_reasons:
        verdict = "INSUFFICIENT_EVIDENCE"
    elif operating_profit <= 0 or risk_drawdown > cfg.research.maximum_stressed_drawdown_pct:
        verdict = "REJECT"
    elif (
        episodes < cfg.research.minimum_independent_opportunities
        or uncertainty is None
        or uncertainty.constrained_lower_bound <= 0
        or uncertainty.cash_lower_bound <= 0
    ):
        verdict = "INSUFFICIENT_EVIDENCE"
    else:
        # This is only a reason to research independent opportunities, costs,
        # and eligible sources further. It is never economic acceptance.
        verdict = "PROCEED_TO_FURTHER_RESEARCH"
    realized = out.account.cash - origin if out.account.complete else None
    return EtfExploratoryScore(
        origin,
        cost_name,
        budget_name,
        data_monthly,
        compute_monthly,
        out.run_hash,
        out.account.state_hash,
        points[0].session_date,
        points[-1].session_date,
        len(points),
        episodes,
        None,
        out.account.fees,
        realized,
        trading_pnl,
        costs[-1],
        operating_profit,
        reference_notional,
        mean_exposure,
        reference_mean,
        reference.points[-1].liquidation_proxy - origin,
        ZERO,
        risk_drawdown,
        _performance(out),
        uncertainty,
        verdict,
        out.incomplete_reasons,
        _sizing(out),
    )
