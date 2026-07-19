"""Complete Decimal performance metrics with explicit undefined states."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext


@dataclass(frozen=True, slots=True)
class MetricValue:
    value: Decimal | int | None
    status: str = "defined"


@dataclass(frozen=True, slots=True)
class PerformanceInput:
    equity_curve: tuple[tuple[datetime, Decimal], ...]
    period_returns: tuple[Decimal, ...]
    trade_pnl: tuple[Decimal, ...]
    periods_per_year: int
    elapsed_years: Decimal
    turnover: Decimal
    gross_exposure: tuple[Decimal, ...]
    net_exposure: tuple[Decimal, ...]
    time_in_market_fraction: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    fees: Decimal
    independent_opportunities: int


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    total_return_pct: MetricValue
    cagr_pct: MetricValue
    annualized_volatility_pct: MetricValue
    sharpe: MetricValue
    sortino: MetricValue
    calmar: MetricValue
    maximum_drawdown_pct: MetricValue
    average_drawdown_pct: MetricValue
    maximum_drawdown_duration: MetricValue
    win_rate_pct: MetricValue
    average_win: MetricValue
    average_loss: MetricValue
    payoff_ratio: MetricValue
    profit_factor: MetricValue
    expectancy: MetricValue
    median_trade: MetricValue
    turnover: MetricValue
    average_gross_exposure: MetricValue
    average_net_exposure: MetricValue
    time_in_market_pct: MetricValue
    spread_cost: MetricValue
    slippage_cost: MetricValue
    fees: MetricValue
    independent_opportunities: MetricValue
    longest_losing_streak: MetricValue
    tail_loss: MetricValue


def _undefined(reason: str) -> MetricValue:
    return MetricValue(None, reason)


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    return None if not values else sum(values, Decimal("0")) / Decimal(len(values))


def _sample_std(values: tuple[Decimal, ...]) -> Decimal | None:
    if len(values) < 2:
        return None
    mean = _mean(values)
    if mean is None:
        raise RuntimeError("sample mean is unexpectedly unavailable")
    variance = sum(((value - mean) ** 2 for value in values), Decimal("0")) / Decimal(
        len(values) - 1
    )
    with localcontext() as context:
        context.prec = 64
        return variance.sqrt()


def calculate_performance(source: PerformanceInput) -> PerformanceMetrics:
    equities = tuple(value for _, value in source.equity_curve)
    total_return = (
        None
        if len(equities) < 2 or equities[0] == 0
        else (equities[-1] / equities[0] - Decimal("1")) * Decimal("100")
    )
    cagr = None
    if total_return is not None and source.elapsed_years > 0 and equities[-1] >= 0:
        with localcontext() as context:
            context.prec = 64
            cagr = ((equities[-1] / equities[0]) ** (Decimal("1") / source.elapsed_years) - 1) * 100
    std = _sample_std(source.period_returns)
    annual_root = Decimal(source.periods_per_year).sqrt()
    volatility = None if std is None else std * annual_root * 100
    average_return = _mean(source.period_returns)
    sharpe = (
        None
        if std in {None, Decimal("0")} or average_return is None
        else (average_return / std * annual_root)
    )
    downside = tuple(value for value in source.period_returns if value < 0)
    downside_std = _sample_std(downside)
    sortino = (
        None
        if downside_std in {None, Decimal("0")} or average_return is None
        else (average_return / downside_std * annual_root)
    )
    peak: Decimal | None = None
    drawdowns: list[Decimal] = []
    duration = longest_duration = 0
    for equity in equities:
        peak = equity if peak is None else max(peak, equity)
        drawdown = Decimal("0") if peak == 0 else (equity / peak - 1) * 100
        drawdowns.append(drawdown)
        duration = duration + 1 if drawdown < 0 else 0
        longest_duration = max(longest_duration, duration)
    maximum_drawdown = min(drawdowns, default=Decimal("0"))
    active_drawdowns = tuple(abs(item) for item in drawdowns if item < 0)
    average_drawdown = _mean(active_drawdowns) or Decimal("0")
    calmar = None if cagr is None or maximum_drawdown == 0 else cagr / abs(maximum_drawdown)
    wins = tuple(value for value in source.trade_pnl if value > 0)
    losses = tuple(value for value in source.trade_pnl if value < 0)
    average_win = _mean(wins)
    average_loss = _mean(losses)
    payoff = (
        None
        if average_win is None or average_loss in {None, Decimal("0")}
        else average_win / abs(average_loss)
    )
    gross_profit = sum(wins, Decimal("0"))
    gross_loss = abs(sum(losses, Decimal("0")))
    profit_factor = None if gross_loss == 0 else gross_profit / gross_loss
    expectancy = _mean(source.trade_pnl)
    ordered = sorted(source.trade_pnl)
    median = None
    if ordered:
        middle = len(ordered) // 2
        median = (
            ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
        )
    streak = longest_streak = 0
    for value in source.trade_pnl:
        streak = streak + 1 if value < 0 else 0
        longest_streak = max(longest_streak, streak)
    tail_count = max(1, (len(ordered) + 19) // 20) if ordered else 0
    tail_loss = _mean(tuple(ordered[:tail_count])) if tail_count else None
    trade_count = len(source.trade_pnl)
    return PerformanceMetrics(
        MetricValue(total_return)
        if total_return is not None
        else _undefined("insufficient_equity_curve"),
        MetricValue(cagr) if cagr is not None else _undefined("invalid_elapsed_period"),
        MetricValue(volatility)
        if volatility is not None
        else _undefined("insufficient_return_variation"),
        MetricValue(sharpe) if sharpe is not None else _undefined("undefined_zero_variation"),
        MetricValue(sortino)
        if sortino is not None
        else _undefined("undefined_no_downside_variation"),
        MetricValue(calmar) if calmar is not None else _undefined("undefined_no_drawdown"),
        MetricValue(maximum_drawdown),
        MetricValue(average_drawdown),
        MetricValue(longest_duration),
        MetricValue(Decimal(len(wins)) * 100 / trade_count)
        if trade_count
        else _undefined("no_trades"),
        MetricValue(average_win) if average_win is not None else _undefined("no_wins"),
        MetricValue(average_loss) if average_loss is not None else _undefined("no_losses"),
        MetricValue(payoff) if payoff is not None else _undefined("undefined_payoff"),
        MetricValue(profit_factor)
        if profit_factor is not None
        else _undefined("undefined_no_loss"),
        MetricValue(expectancy) if expectancy is not None else _undefined("no_trades"),
        MetricValue(median) if median is not None else _undefined("no_trades"),
        MetricValue(source.turnover),
        MetricValue(_mean(source.gross_exposure) or Decimal("0")),
        MetricValue(_mean(source.net_exposure) or Decimal("0")),
        MetricValue(source.time_in_market_fraction * 100),
        MetricValue(source.spread_cost),
        MetricValue(source.slippage_cost),
        MetricValue(source.fees),
        MetricValue(source.independent_opportunities),
        MetricValue(longest_streak),
        MetricValue(tail_loss) if tail_loss is not None else _undefined("no_trades"),
    )


__all__ = ["MetricValue", "PerformanceInput", "PerformanceMetrics", "calculate_performance"]
