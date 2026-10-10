"""Private original-account test window; never accepted economic evidence.

This is an invocation-owned assembler, not a public saved-result evaluator.
Final settlement in a later exit-only tail cannot finalize the test cutoff.
"""

from dataclasses import astuple, dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from itertools import pairwise

from trading_bot.clock import require_utc
from trading_bot.domain import Side, require_bounded_decimal
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_path_economics import (
    _bounded,
    _capital_close_exposures,
    _ratio,
)
from trading_bot.research.metrics import (
    MetricValue,
    PerformanceInput,
    PerformanceMetrics,
    calculate_performance,
)
from trading_bot.simulation.etf_capital_account import (
    CapitalAccountSubmission,
    CapitalActionAccountReplay,
    replay_capital_action_account_prefixes,
)
from trading_bot.simulation.etf_capital_action_events import CapitalDistributionPaid
from trading_bot.simulation.etf_capital_constrained import (
    CapitalConstrainedPoint,
    CapitalConstrainedResult,
)
from trading_bot.simulation.etf_capital_daily_entry import _CONTEXT, _Offline
from trading_bot.simulation.etf_capital_risk import _capital_risk_source_frontiers
from trading_bot.simulation.etf_capital_trajectory import (
    CapitalTrajectoryPoint,
    CapitalTrajectoryResult,
)
from trading_bot.simulation.lifecycle_models import LifecycleFillEvent


def _check(value: bool) -> None:
    if not value:
        raise ValueError("capital_economic_window_invalid")


def _strict_account(account: CapitalActionAccountReplay) -> None:
    """Validate exact record types before equality with recomputed originals."""
    _check(type(account) is CapitalActionAccountReplay)
    for amount in (
        account.cash,
        account.available_cash,
        account.quantity,
        account.fees,
        account.unsettled_proceeds,
        account.distribution_receivable,
    ):
        require_bounded_decimal(amount, "original account value")
    for optional in (account.average_price, account.mark, account.marked_equity):
        if optional is not None:
            require_bounded_decimal(optional, "optional original account value")
    _check(type(account.complete) is bool and type(account.economic_hash) is str)
    _check(account.execution_enabled is False and account.evidence_promotable is False)
    _check(account.source_qualified is False)


@dataclass(frozen=True, slots=True)
class CapitalEconomicWindow(_Offline):
    input_hash: str
    trajectory_hash: str
    initial_cash: Decimal
    baseline_session: date
    session_dates: tuple[date, ...]
    tail_sessions: tuple[date, ...]
    baseline_nav: Decimal
    marked_nav: tuple[Decimal, ...]
    net_nav: tuple[Decimal, ...] | None
    cash_change: Decimal
    trading_pnl: Decimal | None
    marked_pnl: Decimal
    recurring_cost: Decimal | None
    sunk_research_cost: Decimal | None
    operating_profit: Decimal | None
    marked_operating_profit: Decimal | None
    fees_paid: Decimal
    distributions_paid: Decimal
    distribution_receivable: Decimal
    residual_quantity: Decimal
    available_cash: Decimal
    unsettled_proceeds: Decimal
    completed_episode_pnl: tuple[Decimal, ...]
    turnover_notional: Decimal
    trading_prior_nav_returns: tuple[Decimal, ...] | None
    operating_prior_nav_returns: tuple[Decimal, ...] | None
    trading_metrics: PerformanceMetrics
    operating_metrics: PerformanceMetrics | None
    reasons: tuple[str, ...]
    independent_opportunities: None = field(default=None, init=False)
    actual_tax_usd: None = field(default=None, init=False)


def _window_metrics(
    times: tuple[datetime, ...],
    nav: tuple[Decimal, ...],
    episodes: tuple[Decimal, ...],
    turnover: Decimal,
    exposures: tuple[Decimal, ...],
    occupancy: Decimal,
    fees: Decimal,
) -> tuple[tuple[Decimal, ...] | None, PerformanceMetrics]:
    """Assemble shared metrics; marked daily returns are not execution prices."""
    returns = (
        None
        if any(prior <= 0 for prior in nav[:-1])
        else tuple(_ratio(current - prior, prior) for prior, current in pairwise(nav))
    )
    with localcontext(_CONTEXT) as context:
        context.prec = 64
        metrics = calculate_performance(
            PerformanceInput(
                tuple(zip(times, nav, strict=True)),
                () if returns is None else returns,
                episodes,
                252,
                _ratio(Decimal((times[-1].date() - times[0].date()).days), Decimal(365)),
                turnover,
                exposures,
                exposures,
                occupancy,
                Decimal(0),
                Decimal(0),
                fees,
                0,
            )
        )
    if returns is None:
        undefined = MetricValue(None, "undefined_nonpositive_prior_nav")
        metrics = replace(
            metrics, annualized_volatility_pct=undefined, sharpe=undefined, sortino=undefined
        )
    else:
        metrics = replace(
            metrics,
            sortino=MetricValue(
                None, "unavailable_legacy_negative_return_sample_sd_not_target_downside_deviation"
            ),
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
            status="finalized_episode_trading_usd_not_window_attributed"
            if episodes
            else "no_trades",
        ),
    )
    return returns, metrics


def _capital_economic_window(
    trajectory: CapitalTrajectoryResult | CapitalConstrainedResult,
    *,
    initial_cash: Decimal,
    test_sessions: tuple[date, ...],
    recurring_usd_per_day: Decimal | None,
    sunk_research_usd: Decimal | None,
) -> CapitalEconomicWindow:
    """Use only inside a future original-source-owned comparison invocation."""
    try:
        with localcontext(_CONTEXT):
            _check(
                type(trajectory) is CapitalTrajectoryResult
                or type(trajectory) is CapitalConstrainedResult
            )
            strategy = type(trajectory) is CapitalTrajectoryResult
            point_type = CapitalTrajectoryPoint if strategy else CapitalConstrainedPoint
            _check(trajectory.source_qualified is False and trajectory.cost_qualified is False)
            _check(trajectory.execution_enabled is False and trajectory.economic_admitted is False)
            _check(trajectory.evidence_promotable is False)
            require_bounded_decimal(initial_cash, "initial capital", positive=True)
            for expense in (recurring_usd_per_day, sunk_research_usd):
                if expense is not None:
                    require_bounded_decimal(expense, "expense", nonnegative=True)
            _check(type(test_sessions) is tuple and 0 < len(test_sessions) <= 2047)
            _check(all(type(day) is date for day in test_sessions))
            points = trajectory.points
            _check(type(points) is tuple and 1 < len(points) <= 2048)
            _strict_account(trajectory.account)
            for point in points:
                _check(type(point) is point_type)
                require_utc(point.at)
                _check(point.at.tzinfo is UTC)
                require_bounded_decimal(point.equity, "original point equity", positive=True)
                _strict_account(point.account)
            dates = tuple(point.at.date() for point in points)
            _check(all(a < b for a, b in pairwise(dates)))
            count = len(test_sessions)
            _check(dates[1 : count + 1] == test_sessions)
            prefixes = replay_capital_action_account_prefixes(
                initial_cash=initial_cash, events=trajectory.events
            )
            _capital_risk_source_frontiers(
                events=trajectory.events,
                accounts=prefixes,
                observations=trajectory.observations,
                actions=True,
            )
            _check(prefixes[-1] == trajectory.account)
            exposures = _capital_close_exposures(trajectory, prefixes)
            observations = {row.cursor.occurred_at: row for row in trajectory.observations}
            baseline_count = observations[points[0].at].source_count
            cutoff_count = observations[points[count].at].source_count
            _check(baseline_count <= cutoff_count)
            baseline, cutoff = prefixes[baseline_count], prefixes[cutoff_count]
            episodes: list[Decimal] = []
            episode_origin: Decimal | None = None
            bought = False
            turnover = paid = Decimal(0)
            for index, event in enumerate(trajectory.events[:cutoff_count]):
                before, after = prefixes[index : index + 2]
                if before.economic_hash == after.economic_hash:
                    continue
                if (
                    isinstance(event, CapitalAccountSubmission)
                    and event.request.order.side is Side.BUY
                ):
                    _check(episode_origin is None)
                    episode_origin, bought = before.cash, False
                if isinstance(event, LifecycleFillEvent):
                    bought = bought or event.fill.side is Side.BUY
                    if index >= baseline_count:
                        turnover += event.fill.price * event.fill.quantity
                if isinstance(event, CapitalDistributionPaid) and index >= baseline_count:
                    paid += event.amount
                if after.complete and episode_origin is not None:
                    if bought and index >= baseline_count:
                        episodes.append(after.cash - episode_origin)
                    episode_origin, bought = None, False
            selected = points[: count + 1]
            times = tuple(p.at for p in selected)
            marked = tuple(p.equity for p in selected)
            fees = cutoff.fees - baseline.fees
            _check(fees >= 0)
            exposure = exposures[1 : count + 1]
            occupancy = _ratio(
                Decimal(sum(p.account.quantity > 0 for p in selected[1:])), Decimal(count)
            )
            trade_returns, trade_metrics = _window_metrics(
                times,
                marked,
                tuple(episodes),
                _ratio(turnover, initial_cash),
                exposure,
                occupancy,
                fees,
            )
            costs = (
                None
                if recurring_usd_per_day is None
                else tuple(
                    Decimal((d - dates[0]).days) * recurring_usd_per_day for d in dates[: count + 1]
                )
            )
            net = (
                None
                if costs is None
                else tuple(nav - cost for nav, cost in zip(marked, costs, strict=True))
            )
            operating_returns = operating_metrics = None
            if net is not None:
                operating_returns, operating_metrics = _window_metrics(
                    times,
                    net,
                    tuple(episodes),
                    _ratio(turnover, initial_cash),
                    exposure,
                    occupancy,
                    fees,
                )
            complete = (
                baseline.complete and cutoff.complete and baseline.quantity == cutoff.quantity == 0
            )
            cash_change = cutoff.cash - baseline.cash
            trading_pnl = cash_change if complete else None
            recurring = None if costs is None else costs[-1]
            reasons = (
                (
                    "private_development_window_unqualified_source_and_costs",
                    "marked_nav_not_executable_liquidation",
                    "completed_episode_pnl_not_window_attributed",
                    "independent_support_not_established",
                    "tax_treatment_unknown",
                )
                + (() if complete else ("window_endpoint_outcome_incomplete",))
                + (
                    ("operating_cost_unknown",)
                    if recurring is None
                    else ("declared_unverified_operating_cost",)
                )
            )
            identity = content_hash(
                (
                    "capital-private-economic-window-v1"
                    if strategy
                    else "capital-private-constrained-economic-window-v1",
                    trajectory.input_hash,
                    initial_cash,
                    dates[0],
                    test_sessions,
                    dates[count + 1 :],
                    baseline_count,
                    cutoff_count,
                    tuple(p.economic_hash for p in prefixes),
                    marked,
                    exposure,
                    recurring_usd_per_day,
                    sunk_research_usd,
                    "baseline_excluded_elapsed_UTC_ACT365_cutoff_finality_priorNAV_episode_completion_clock",
                    reasons,
                )
            )
            result = CapitalEconomicWindow(
                identity,
                trajectory.input_hash,
                initial_cash,
                dates[0],
                test_sessions,
                dates[count + 1 :],
                marked[0],
                marked,
                net,
                cash_change,
                trading_pnl,
                marked[-1] - marked[0],
                recurring,
                sunk_research_usd,
                None if trading_pnl is None or recurring is None else trading_pnl - recurring,
                None if net is None else net[-1] - net[0],
                fees,
                paid,
                cutoff.distribution_receivable,
                cutoff.quantity,
                cutoff.available_cash,
                cutoff.unsettled_proceeds,
                tuple(episodes),
                turnover,
                trade_returns,
                operating_returns,
                trade_metrics,
                operating_metrics,
                reasons,
            )
            _bounded(astuple(result))
            return result
    except (ValueError, TypeError, ArithmeticError, AttributeError, KeyError, IndexError):
        raise ValueError("capital_economic_window_invalid") from None
