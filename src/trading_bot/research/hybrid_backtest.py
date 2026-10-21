"""Small illustrative close-decision/next-open comparison with explicit assumptions."""

from datetime import datetime
from decimal import Decimal

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
