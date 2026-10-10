"""Owned original-event descriptive accounting, never accepted economic evidence.

Marked daily NAV is not executable liquidation. Fees and assumed friction are
already in original cash flows. Recurring costs accrue separately; sunk expenses
and unknown taxes are not silently subtracted from trading P&L.
"""

from dataclasses import astuple, dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal, localcontext
from itertools import pairwise

from trading_bot.domain import Side, require_bounded_decimal
from trading_bot.market_data.recording import content_hash
from trading_bot.research.metrics import (
    MetricValue,
    PerformanceInput,
    PerformanceMetrics,
    calculate_performance,
)
from trading_bot.simulation.etf_capital_account import (
    CapitalAccountSubmission,
    replay_capital_action_account_prefixes,
)
from trading_bot.simulation.etf_capital_action_events import CapitalDistributionPaid
from trading_bot.simulation.etf_capital_daily_entry import _CONTEXT, _Offline
from trading_bot.simulation.etf_capital_trajectory import (
    CapitalTrajectoryRequest,
    CapitalTrajectoryResult,
    replay_capital_trajectory,
)
from trading_bot.simulation.lifecycle_models import LifecycleFillEvent


def _check(value: bool) -> None:
    if not value:
        raise ValueError("capital_path_economics_invalid")


def _bounded(values: tuple[object, ...]) -> None:
    for value in values:
        if isinstance(value, Decimal):
            require_bounded_decimal(value, "descriptive output")
        elif isinstance(value, tuple):
            _bounded(value)


def _ratio(value: Decimal, denominator: Decimal) -> Decimal:
    with localcontext(_CONTEXT) as context:
        context.prec = 64
        return value / denominator


@dataclass(frozen=True, slots=True)
class CapitalPathEconomicRequest(_Offline):
    trajectory: CapitalTrajectoryRequest
    recurring_usd_per_day: Decimal
    sunk_research_usd: Decimal


@dataclass(frozen=True, slots=True)
class CapitalPathEconomics(_Offline):
    input_hash: str
    trajectory_hash: str
    initial_cash: Decimal
    session_dates: tuple[date, ...]
    cash_change: Decimal
    trading_pnl: Decimal | None
    marked_pnl: Decimal
    recurring_cost: Decimal
    sunk_research_cost: Decimal
    operating_profit: Decimal | None
    fees_paid: Decimal
    distributions_paid: Decimal
    distribution_receivable: Decimal
    residual_quantity: Decimal
    available_cash: Decimal
    unsettled_proceeds: Decimal
    completed_episode_pnl: tuple[Decimal, ...]
    turnover_notional: Decimal
    net_nav: tuple[Decimal, ...]
    prior_nav_returns: tuple[Decimal, ...] | None
    metrics: PerformanceMetrics
    reasons: tuple[str, ...]
    independent_opportunities: None = field(default=None, init=False)
    actual_tax_usd: None = field(default=None, init=False)


def evaluate_capital_path_economics(request: CapitalPathEconomicRequest) -> CapitalPathEconomics:
    """Replay original input; supplied balances/results/support are not inputs."""
    try:
        with localcontext(_CONTEXT):
            _check(type(request) is CapitalPathEconomicRequest)
            _check(request.source_qualified is False and request.cost_qualified is False)
            _check(request.execution_enabled is False and request.economic_admitted is False)
            _check(request.evidence_promotable is False)
            require_bounded_decimal(
                request.recurring_usd_per_day, "daily expense", nonnegative=True
            )
            require_bounded_decimal(request.sunk_research_usd, "sunk expense", nonnegative=True)
            _check(type(request.trajectory) is CapitalTrajectoryRequest)
            trajectory = replay_capital_trajectory(request.trajectory)
            first_date = trajectory.points[0].at.date()
            original_open = next(
                day.opens_at
                for day in request.trajectory.dataset.calendar.sessions
                if day.session_date == first_date
            )
            return _capital_path_economics(
                trajectory,
                initial_cash=request.trajectory.initial_cash,
                initial_at=original_open,
                recurring_usd_per_day=request.recurring_usd_per_day,
                sunk_research_usd=request.sunk_research_usd,
            )
    except (ValueError, TypeError, ArithmeticError, AttributeError, StopIteration, IndexError):
        raise ValueError("capital_path_economics_invalid") from None


def _capital_path_economics(
    trajectory: CapitalTrajectoryResult,
    *,
    initial_cash: Decimal,
    initial_at: datetime,
    recurring_usd_per_day: Decimal,
    sunk_research_usd: Decimal,
) -> CapitalPathEconomics:
    """Private invocation-local report seam, never externally adopted state."""
    with localcontext(_CONTEXT):
        prefixes = replay_capital_action_account_prefixes(
            initial_cash=initial_cash, events=trajectory.events
        )
        _check(prefixes[-1] == trajectory.account)
        episodes: list[Decimal] = []
        episode_origin: Decimal | None = None
        bought = False
        turnover = paid = Decimal(0)
        for index, event in enumerate(trajectory.events):
            before, after = prefixes[index : index + 2]
            if before.economic_hash == after.economic_hash:
                continue
            if isinstance(event, CapitalAccountSubmission) and event.request.order.side is Side.BUY:
                _check(episode_origin is None)
                episode_origin = before.cash
                bought = False
            if isinstance(event, LifecycleFillEvent):
                turnover += event.fill.price * event.fill.quantity
                bought = bought or event.fill.side is Side.BUY
            if isinstance(event, CapitalDistributionPaid):
                paid += event.amount
            if after.complete and episode_origin is not None:
                if bought:
                    episodes.append(after.cash - episode_origin)
                episode_origin = None
                bought = False

        points = trajectory.points
        _check(bool(points) and initial_at < points[0].at)
        dates = tuple(point.at.date() for point in points)
        _check(all(a < b for a, b in pairwise(dates)))
        observations = {row.cursor.occurred_at: row for row in trajectory.observations}
        exposures: list[Decimal] = []
        for point in points:
            original = observations[point.at]
            _check(point.account == prefixes[original.source_count])
            held = point.account.quantity
            _check(not held or original.mark is not None)
            notional = Decimal(0) if not held else held * original.mark  # type: ignore[operator]
            _check(
                point.equity
                == point.account.cash + point.account.distribution_receivable + notional
            )
            exposures.append(Decimal(0) if point.equity == 0 else _ratio(notional, point.equity))

        accruals = tuple(
            Decimal((day - dates[0]).days + 1) * recurring_usd_per_day for day in dates
        )
        net_nav = tuple(p.equity - cost for p, cost in zip(points, accruals, strict=True))
        previous = (initial_cash, *net_nav[:-1])
        returns = (
            None
            if any(nav <= 0 for nav in previous)
            else tuple(
                _ratio(nav - prior, prior) for nav, prior in zip(net_nav, previous, strict=True)
            )
        )
        elapsed = _ratio(Decimal((dates[-1] - dates[0]).days + 1), Decimal(365))
        with localcontext(_CONTEXT) as metric_context:
            metric_context.prec = 64
            metrics = calculate_performance(
                PerformanceInput(
                    (
                        (initial_at, initial_cash),
                        *((p.at, nav) for p, nav in zip(points, net_nav, strict=True)),
                    ),
                    () if returns is None else returns,
                    tuple(episodes),
                    252,
                    elapsed,
                    _ratio(turnover, initial_cash),
                    tuple(exposures),
                    tuple(exposures),
                    _ratio(
                        Decimal(sum(p.account.quantity > 0 for p in points)), Decimal(len(points))
                    ),
                    Decimal(0),
                    Decimal(0),
                    trajectory.account.fees,
                    0,
                )
            )
        if returns is None:
            undefined = MetricValue(None, "undefined_nonpositive_prior_nav")
            metrics = replace(
                metrics, annualized_volatility_pct=undefined, sharpe=undefined, sortino=undefined
            )
        metrics = replace(
            metrics,
            independent_opportunities=MetricValue(None, "independent_support_not_established"),
            spread_cost=MetricValue(None, "unmeasured_component_embedded_in_assumed_prices"),
            slippage_cost=MetricValue(None, "unmeasured_component_embedded_in_assumed_prices"),
            time_in_market_pct=replace(
                metrics.time_in_market_pct, status="daily_close_occupancy_proxy"
            ),
            average_gross_exposure=replace(
                metrics.average_gross_exposure, status="daily_close_equity_exposure_proxy"
            ),
            average_net_exposure=replace(
                metrics.average_net_exposure, status="daily_close_equity_exposure_proxy"
            ),
            expectancy=replace(
                metrics.expectancy,
                status="finalized_trading_usd_before_operating_cost" if episodes else "no_trades",
            ),
        )
        complete = trajectory.account.complete and trajectory.account.quantity == 0
        cash_change = trajectory.account.cash - initial_cash
        reasons = (
            "development_only_unqualified_source_and_costs",
            "marked_nav_not_executable_liquidation",
            "operating_accrual_declared_unverified",
            "independent_support_not_established",
            "tax_treatment_unknown",
            "benchmarks_and_full_family_statistics_unavailable",
        ) + (() if complete else ("account_outcome_incomplete",))
        identity = content_hash(
            (
                "capital-path-descriptive-economics-v1",
                trajectory.input_hash,
                initial_cash,
                initial_at,
                recurring_usd_per_day,
                sunk_research_usd,
                "inclusive_UTC_ACT365_priorNAV_returns_finalized_trading_episodePNL_dailyclose_proxies_no_tax_no_support",
            )
        )
        result = CapitalPathEconomics(
            identity,
            trajectory.input_hash,
            initial_cash,
            dates,
            cash_change,
            cash_change if complete else None,
            points[-1].equity - initial_cash,
            accruals[-1],
            sunk_research_usd,
            cash_change - accruals[-1] if complete else None,
            trajectory.account.fees,
            paid,
            trajectory.account.distribution_receivable,
            trajectory.account.quantity,
            trajectory.account.available_cash,
            trajectory.account.unsettled_proceeds,
            tuple(episodes),
            turnover,
            net_nav,
            returns,
            metrics,
            reasons,
        )
        _bounded(astuple(result))
        return result
