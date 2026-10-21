"""Small illustrative close-decision/next-open comparison with explicit assumptions."""

from datetime import datetime
from decimal import Decimal
from itertools import pairwise

from trading_bot.research.hybrid_sources import utc
from trading_bot.research.hybrid_strategies import PriceBar, validate_bars


def compare_returns(
    bars: tuple[PriceBar, ...],
    signals: tuple[int, ...],
    benchmark: tuple[PriceBar, ...],
    *,
    cost_bps: Decimal,
    signal_available_at: tuple[datetime, ...] | None = None,
) -> dict[str, object]:
    """Signals are exogenous hypotheses: never infer point-in-time validity for them.

    Fractional 0/100% long allocation, immediate full fills at next open, no leverage.
    Last signal is unexecuted. Cost is applied on entry and exit; terminal liquidation
    occurs at last close. Price bases and corporate actions must be qualified upstream.
    """
    if not cost_bps.is_finite() or not Decimal(0) <= cost_bps < Decimal(10000):
        raise ValueError("finite nonnegative costs below 10000bps required")
    if signal_available_at is not None:
        if len(signal_available_at) != len(bars):
            raise ValueError("signal availability length mismatch")
        if any(
            utc(available) > bar.completed_at
            for available, bar in zip(signal_available_at, bars, strict=True)
        ):
            raise ValueError("lookahead signal availability")
    validate_bars(bars)
    validate_bars(benchmark)
    if len(signals) != len(bars) or any(type(s) is not int or s not in (0, 1) for s in signals):
        raise ValueError("binary signal for every completed bar required")
    if len(bars) < 3 or len(benchmark) != len(bars):
        return {"status": "insufficient_evidence", "reason": "matched history required"}
    timestamps: tuple[datetime, ...] = tuple(b.completed_at for b in bars)
    if timestamps != tuple(b.completed_at for b in benchmark):
        return {"status": "insufficient_evidence", "reason": "benchmark intervals differ"}
    cost = cost_bps / Decimal(10000)

    def equity(path: tuple[PriceBar, ...], targets: tuple[int, ...]) -> Decimal:
        wealth = Decimal(1)
        held = 0
        previous_close = path[0].close
        for i in range(1, len(path)):
            bar = path[i]
            if held:
                wealth *= bar.open / previous_close
            target = targets[i - 1]
            if held != target:
                wealth *= 1 - cost
            held = target
            if held:
                wealth *= bar.close / bar.open
            previous_close = bar.close
        if held:
            wealth *= 1 - cost
        return wealth - 1

    return {
        "status": "illustrative_only",
        "strategy_return": float(equity(bars, signals)),
        "benchmark_return": float(equity(benchmark, (1,) * len(benchmark))),
        "cost_bps": str(cost_bps),
        "execution_delay_bars": 1,
        "limitations": [
            "exogenous signals unverified",
            "unqualified fill assumptions",
            "no statistical or promotion evidence",
            "corporate actions unverified",
        ],
    }


# Frozen before observing a path; these are experimental policies, not runtime config.
EXIT_MODELS = (
    "principal_retention",
    "partial_exit",
    "trend_trailing",
    "buy_hold",
    "fixed_target",
    "fixed_holding",
)


def compare_exit_models(
    bars: tuple[PriceBar, ...],
    *,
    starting_capital: Decimal = Decimal(1000),
    slippage_bps: Decimal | None = None,
    fee_per_order: Decimal | None = None,
    operating_cost_per_bar: Decimal | None = None,
    tax_rate: Decimal | None = None,
) -> dict[str, object]:
    """One fully funded, fractional-share episode; no reinvestment or borrowing.

    Prices observed at a close can schedule only next-open sales. Initial signal is
    first close, initial purchase second open. Terminal liquidation at the last close
    is a predeclared horizon convention. No intrabar stop prices are assumed.
    """
    validate_bars(bars)
    if not starting_capital.is_finite() or starting_capital <= 0:
        raise ValueError("positive finite starting capital required")
    if (
        slippage_bps is None
        or fee_per_order is None
        or operating_cost_per_bar is None
        or len(bars) < 3
    ):
        return {
            "status": "insufficient_evidence",
            "qualified": False,
            "models": [],
            "reason": "explicit costs and at least three completed bars required",
        }
    for value in (slippage_bps, fee_per_order, operating_cost_per_bar):
        if not value.is_finite() or value < 0:
            raise ValueError("finite nonnegative cost required")
    if slippage_bps >= 10000:
        raise ValueError("slippage must be below 10000 bps")
    if tax_rate is not None and (not tax_rate.is_finite() or not 0 <= tax_rate < 1):
        raise ValueError("tax rate must be explicit fraction in [0,1)")
    models = [
        _exit_episode(
            bars,
            model,
            starting_capital,
            slippage_bps / Decimal(10000),
            fee_per_order,
            operating_cost_per_bar,
            tax_rate,
        )
        for model in EXIT_MODELS
    ]
    return {
        "status": "illustrative_only",
        "qualified": False,
        "models": models,
        "assumptions": {
            "initial_capital": str(starting_capital),
            "slippage_bps": str(slippage_bps),
            "fee_per_order": str(fee_per_order),
            "operating_cost_per_bar": str(operating_cost_per_bar),
            "tax_rate": None if tax_rate is None else str(tax_rate),
            "capital_contributions": "0",
            "reinvestment": False,
            "operating_budget": "reserved upfront for declared horizon",
            "tax_model": "positive realized gain per sale; no loss offsets or tax deferral",
            "annualization": "252 observed bars; CAGR uses elapsed calendar time",
        },
        "limitations": [
            "unqualified synthetic or caller-supplied prices",
            "fractional full fills assumed",
            "no stop price guarantee",
            "one episode does not establish out-of-sample validity or profitability",
        ],
    }


def _exit_episode(
    bars: tuple[PriceBar, ...],
    model: str,
    capital: Decimal,
    slip: Decimal,
    fee: Decimal,
    operating: Decimal,
    tax_rate: Decimal | None,
) -> dict[str, object]:
    reserve = operating * (len(bars) - 1)
    invest = capital - reserve - fee
    if invest <= 0:
        return {
            "model": model,
            "status": "insufficient_capital",
            "qualified": False,
            "reason": "cannot fund purchase and declared operating reserve",
        }
    entry = bars[1].open * (1 + slip)
    shares = invest / entry
    original_shares = shares
    basis_per_share = (invest + fee) / shares
    cash = reserve
    peak = entry
    pending = Decimal(0)
    retained = False
    rungs: set[int] = set()
    fees = fee
    slips = shares * (entry - bars[1].open)
    paid_tax = Decimal(0)
    operations = Decimal(0)
    turnover = invest
    realized: list[Decimal] = []
    trades: list[dict[str, object]] = [
        {"side": "buy", "bar_index": 1, "quantity": str(shares), "price": str(entry)}
    ]
    curve = [capital]
    exposure = []
    holding_bars = 0

    def sell(quantity: Decimal, price: Decimal, index: int) -> bool:
        nonlocal cash, shares, fees, slips, paid_tax, turnover
        quantity = min(quantity, shares)
        execution = price * (1 - slip)
        proceeds = quantity * execution
        gain = proceeds - fee - quantity * basis_per_share
        tax = max(Decimal(0), gain) * (tax_rate if tax_rate is not None else Decimal(0))
        if cash + proceeds < fee + tax:
            return False
        cash += proceeds - fee - tax
        shares -= quantity
        fees += fee
        slips += quantity * (price - execution)
        paid_tax += tax
        turnover += proceeds
        realized.append(gain)
        trades.append(
            {"side": "sell", "bar_index": index, "quantity": str(quantity), "price": str(execution)}
        )
        return True

    for i in range(1, len(bars)):
        bar = bars[i]
        if pending and not sell(pending, bar.open, i):
            return {
                "model": model,
                "status": "insufficient_capital",
                "qualified": False,
                "reason": "sale cannot fund declared costs without borrowing",
            }
        pending = Decimal(0)
        if shares:
            holding_bars += 1
        cash -= operating
        operations += operating
        equity = cash + shares * bar.close
        exposure.append(float(shares * bar.close / equity) if equity > 0 else 0.0)
        if i == len(bars) - 1 and shares and not sell(shares, bar.close, i):
            return {
                "model": model,
                "status": "insufficient_capital",
                "qualified": False,
                "reason": "terminal sale cannot fund declared costs",
            }
        curve.append(cash + shares * bar.close)
        if not shares or i == len(bars) - 1:
            continue
        prior_peak = peak
        peak = max(peak, bar.close)
        change = bar.close / entry - 1
        if model == "principal_retention" and not retained and change >= Decimal(".15"):
            pending = max(Decimal(0), shares * bar.close - capital) / bar.close
            retained = pending > 0
        elif model == "partial_exit":
            for rung, threshold in enumerate((Decimal(".125"), Decimal(".20"))):
                if rung not in rungs and change >= threshold:
                    pending += original_shares * Decimal(".25")
                    rungs.add(rung)
        elif (
            (model == "trend_trailing" and bar.close <= prior_peak * Decimal(".95"))
            or (model == "fixed_target" and change >= Decimal(".15"))
            or (model == "fixed_holding" and i >= 20)
        ):
            pending = shares
    final = curve[-1]
    return {
        "model": model,
        "status": "illustrative_only",
        "qualified": False,
        "initial_capital": str(capital),
        "pre_tax_return": float((final + paid_tax) / capital - 1),
        "after_tax_return": None if tax_rate is None else float(final / capital - 1),
        "gross_return": float((final + fees + slips + operations + paid_tax) / capital - 1),
        "fees": str(fees),
        "slippage": str(slips),
        "operating_costs": str(operations),
        "tax_paid": None if tax_rate is None else str(paid_tax),
        "turnover": float(turnover / capital),
        "holding_bars": holding_bars,
        "average_exposure": sum(exposure) / len(exposure),
        "trades": trades,
        "tax_status": "unknown" if tax_rate is None else "declared_assumption",
        "metrics_tax_basis": "pre_tax" if tax_rate is None else "after_tax",
        **_path_metrics(curve, bars, realized),
    }


def _path_metrics(
    curve: list[Decimal], bars: tuple[PriceBar, ...], realized: list[Decimal]
) -> dict[str, object]:
    import math
    import statistics

    returns = [float(b / a - 1) for a, b in pairwise(curve) if a > 0]
    peak = curve[0]
    drawdown = Decimal(0)
    for value in curve:
        peak = max(peak, value)
        drawdown = max(drawdown, 1 - value / peak)
    years = (bars[-1].completed_at - bars[0].completed_at).total_seconds() / (365.25 * 86400)
    cagr: float | None = None
    if years > 0 and curve[-1] > 0:
        exponent = math.log(float(curve[-1] / curve[0])) / years
        if exponent < 700:
            cagr = math.expm1(exponent)
    vol = statistics.stdev(returns) if len(returns) >= 2 else None
    average = statistics.mean(returns) if returns else None
    downside = math.sqrt(sum(min(0, r) ** 2 for r in returns) / len(returns)) if returns else 0
    # One episode is not enough for a meaningful trade-distribution claim.
    return {
        "cagr": cagr,
        "max_drawdown": float(drawdown),
        "volatility": None if vol is None else vol * math.sqrt(252),
        "sharpe": None if not vol or average is None else average / vol * math.sqrt(252),
        "sortino": None if not downside or average is None else average / downside * math.sqrt(252),
        "calmar": None if not drawdown or cagr is None else cagr / float(drawdown),
        "win_rate": None,
        "profit_factor": None,
        "metric_basis": "net marked equity; zero risk-free assumption",
        "episode_count": 1,
        "realized_exit_count": len(realized),
    }
