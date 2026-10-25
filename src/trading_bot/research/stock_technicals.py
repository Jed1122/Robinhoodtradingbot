"""Unqualified descriptive features of retained completed raw daily observations; no forecasts."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from itertools import pairwise
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import require_bounded_decimal
from trading_bot.market_data.recording import content_hash
from trading_bot.market_data.stock_facts import StockDailyBar, StockObservationReceipt
from trading_bot.market_data.stock_history_projection import (
    StockHistoryProjectionBatch,
    StockHistorySymbolOutcome,
)

_CONTEXT = Context(
    prec=50,
    rounding=ROUND_HALF_EVEN,
    Emin=-999999,
    Emax=999999,
    capitals=1,
    clamp=0,
    flags=[],
    traps=[InvalidOperation, DivisionByZero, Overflow],
)
_NAMES = (
    "price_return_20",
    "price_return_60",
    "price_return_120",
    "sma_50",
    "sma_200",
    "realized_volatility_20",
    "average_volume_20",
    "average_volume_30",
    "average_dollar_volume_20",
    "average_dollar_volume_30",
    "series_max_drawdown",
)
_LIMITATIONS = (
    "descriptive_observed_price_features_not_forecasts",
    "raw_corporate_actions_unknown_not_total_returns",
    "calendar_session_coverage_unverified",
    "windows_count_retained_observations_not_certified_exchange_sessions",
    "raw_basis_and_completion_are_unqualified_caller_declarations",
    "dollar_volume_is_mean_raw_close_times_volume_not_actual_trade_turnover",
    "quote_currency_unverified",
    "no_benchmark_relative_strength_without_benchmark_input",
)


def _check(valid: bool) -> None:
    if not valid:
        raise ValueError("stock_technicals_invalid")


@dataclass(frozen=True, slots=True)
class StockTechnicalMetrics:
    price_return_20: Decimal | None = None
    price_return_60: Decimal | None = None
    price_return_120: Decimal | None = None
    sma_50: Decimal | None = None
    sma_200: Decimal | None = None
    realized_volatility_20: Decimal | None = None
    average_volume_20: Decimal | None = None
    average_volume_30: Decimal | None = None
    average_dollar_volume_20: Decimal | None = None
    average_dollar_volume_30: Decimal | None = None
    series_max_drawdown: Decimal | None = None


@dataclass(frozen=True, slots=True)
class StockTechnicalMetricGap:
    metric: str
    reason: Literal["insufficient_observations", "ineligible_history", "arithmetic_invalid"]


@dataclass(frozen=True, slots=True)
class StockTechnicalFeatures:
    symbol: str
    as_of: datetime
    receipt: StockObservationReceipt
    projection_batch_hash: str
    outcome: StockHistorySymbolOutcome
    normalized_observation_hash: str | None
    total_bar_count: int | None
    source_bar_slot_count: int | None
    omitted_interpolated_count: int | None
    supported_bar_count: int | None
    calculation_status: Literal["calculated", "ineligible", "unavailable", "quarantined"]
    metrics: StockTechnicalMetrics
    missing_metrics: tuple[StockTechnicalMetricGap, ...]
    reason_codes: tuple[str, ...]
    window_basis: Literal["retained_completed_daily_observations"] = field(
        default="retained_completed_daily_observations", init=False
    )
    volatility_annualization_sessions: Literal[252] = field(default=252, init=False)
    volatility_method: Literal["sample_stddev_of_20_simple_returns_times_sqrt252"] = field(
        default="sample_stddev_of_20_simple_returns_times_sqrt252", init=False
    )
    arithmetic_precision: Literal[50] = field(default=50, init=False)
    quote_currency: None = field(default=None, init=False)
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)

    @property
    def feature_hash(self) -> str:
        return str(content_hash(("stock-technicals-v1", self)))


def _supported(
    bar: StockDailyBar, receipt: StockObservationReceipt, cutoff: datetime | None
) -> bool:
    try:
        for name, value in (
            ("open", bar.open),
            ("high", bar.high),
            ("low", bar.low),
            ("close", bar.close),
        ):
            require_bounded_decimal(value, name, positive=True)
        require_bounded_decimal(bar.volume, "volume", nonnegative=True)
        starts = require_utc(bar.begins_at)
        return (
            bar.low <= bar.open <= bar.high
            and bar.low <= bar.close <= bar.high
            and starts <= receipt.received_at
            and bar.price_basis == "raw"
            and bar.raw_basis_caller_declared is True
            and bar.interpolated is False
            and bar.session == "reg"
            and cutoff is not None
            and require_utc(cutoff) <= receipt.received_at
            and starts < cutoff
            and bar.completed_by == cutoff
            and bar.completion_status == "caller_declared_complete"
        )
    except (ValueError, DecimalException):
        return False


def _return(bars: tuple[StockDailyBar, ...], lag: int) -> Decimal:
    return bars[-1].close / bars[-lag - 1].close - 1


def _mean(
    bars: tuple[StockDailyBar, ...], count: int, kind: Literal["close", "volume", "dollar"]
) -> Decimal:
    values = (
        row.close if kind == "close" else row.volume if kind == "volume" else row.close * row.volume
        for row in bars[-count:]
    )
    return sum(values, Decimal(0)) / Decimal(count)


def _volatility(bars: tuple[StockDailyBar, ...]) -> Decimal:
    returns = tuple(
        bars[index].close / bars[index - 1].close - 1 for index in range(len(bars) - 20, len(bars))
    )
    mean = sum(returns, Decimal(0)) / Decimal(20)
    sample_variance = sum(((value - mean) ** 2 for value in returns), Decimal(0)) / Decimal(19)
    return (sample_variance * Decimal(252)).sqrt()


def _drawdown(bars: tuple[StockDailyBar, ...]) -> Decimal:
    peak, maximum = bars[0].close, Decimal(0)
    for row in bars[1:]:
        peak = max(peak, row.close)
        maximum = max(maximum, 1 - row.close / peak)
    return maximum


def _calculate(
    bars: tuple[StockDailyBar, ...],
) -> tuple[StockTechnicalMetrics, tuple[StockTechnicalMetricGap, ...]]:
    calculations: tuple[tuple[str, int, Callable[[], Decimal]], ...] = (
        ("price_return_20", 21, lambda: _return(bars, 20)),
        ("price_return_60", 61, lambda: _return(bars, 60)),
        ("price_return_120", 121, lambda: _return(bars, 120)),
        ("sma_50", 50, lambda: _mean(bars, 50, "close")),
        ("sma_200", 200, lambda: _mean(bars, 200, "close")),
        ("realized_volatility_20", 21, lambda: _volatility(bars)),
        ("average_volume_20", 20, lambda: _mean(bars, 20, "volume")),
        ("average_volume_30", 30, lambda: _mean(bars, 30, "volume")),
        ("average_dollar_volume_20", 20, lambda: _mean(bars, 20, "dollar")),
        ("average_dollar_volume_30", 30, lambda: _mean(bars, 30, "dollar")),
        ("series_max_drawdown", 2, lambda: _drawdown(bars)),
    )
    values: dict[str, Decimal | None] = {}
    gaps = []
    for name, minimum, calculation in calculations:
        values[name] = None
        if len(bars) < minimum:
            gaps.append(StockTechnicalMetricGap(name, "insufficient_observations"))
            continue
        try:
            with localcontext(_CONTEXT):
                values[name] = require_bounded_decimal(calculation(), name)
        except (ValueError, DecimalException):
            gaps.append(StockTechnicalMetricGap(name, "arithmetic_invalid"))
    return StockTechnicalMetrics(**values), tuple(gaps)


def compute_stock_technicals(
    *, as_of: datetime, history: tuple[StockHistoryProjectionBatch, ...]
) -> tuple[StockTechnicalFeatures, ...]:
    """Describe complete raw series without prefix selection, gap repair or ranking."""
    try:
        as_of = require_utc(as_of)
    except ValueError:
        raise ValueError("stock_technicals_invalid") from None
    _check(type(history) is tuple and len(history) <= 256)
    _check(all(isinstance(batch, StockHistoryProjectionBatch) for batch in history))
    seen: set[str] = set()
    result = []
    record_count = 0
    for batch in history:
        _check(batch.receipt.tool == "get_equity_historicals")
        if require_utc(batch.receipt.received_at) > as_of:
            continue
        _check(type(batch.outcomes) is tuple and type(batch.requested_symbols) is tuple)
        _check(tuple(outcome.symbol for outcome in batch.outcomes) == batch.requested_symbols)
        batch_hash: str | None = None
        for outcome in batch.outcomes:
            _check(outcome.symbol not in seen)
            seen.add(outcome.symbol)
            _check(len(seen) <= 1000)
            context, normalized = outcome.context, outcome.normalized
            _check(context.original_source_sha256 == batch.receipt.observation_sha256)
            _check(context.original_requested_symbols == batch.requested_symbols)
            _check(
                (context.original_result_index is None)
                != (context.original_not_found_index is None)
            )
            metrics = StockTechnicalMetrics()
            missing = tuple(StockTechnicalMetricGap(name, "ineligible_history") for name in _NAMES)
            count: int | None = None
            slot_count: int | None = None
            omitted: int | None = None
            supported: int | None = None
            normalized_hash: str | None = None
            status: Literal["calculated", "ineligible", "unavailable", "quarantined"]
            if normalized is None:
                _check(outcome.status == "quarantined")
                status, reasons = "quarantined", ("source_history_quarantined",)
            else:
                _check(normalized.receipt.tool == "get_equity_historicals")
                _check(normalized.receipt.received_at == batch.receipt.received_at)
                _check(normalized.receipt.observation_sha256 == context.projected_payload_sha256)
                _check(normalized.requested_symbols == (outcome.symbol,))
                _check(normalized.request_adjustment_type == batch.request_adjustment_type)
                _check(normalized.completed_before == batch.completed_before)
                bars = normalized.records
                _check(type(bars) is tuple and all(isinstance(row, StockDailyBar) for row in bars))
                _check(
                    all(
                        row.symbol == outcome.symbol and row.receipt == normalized.receipt
                        for row in bars
                    )
                )
                _check(outcome.status == ("normalized" if bars else "unavailable"))
                count, omitted = len(bars), normalized.omitted_interpolated_count
                slot_count = count + omitted + normalized.null_row_count
                record_count += slot_count
                _check(record_count <= 100000)
                supported = sum(
                    _supported(row, batch.receipt, batch.completed_before) for row in bars
                )
                normalized_hash = normalized.observation_hash
                ordered = all(left.begins_at < right.begins_at for left, right in pairwise(bars))
                if not bars:
                    status, reasons = "unavailable", ("source_history_unavailable",)
                elif supported != count or not ordered or normalized.null_row_count:
                    status, reasons = (
                        "ineligible",
                        ("history_not_raw_completed_regular_noninterpolated",),
                    )
                else:
                    status, reasons = "calculated", ("unqualified_descriptive_features",)
                    metrics, missing = _calculate(bars)
            if batch_hash is None:
                batch_hash = batch.observation_hash
            result.append(
                StockTechnicalFeatures(
                    outcome.symbol,
                    as_of,
                    batch.receipt,
                    batch_hash,
                    outcome,
                    normalized_hash,
                    count,
                    slot_count,
                    omitted,
                    supported,
                    status,
                    metrics,
                    missing,
                    reasons,
                )
            )
    return tuple(sorted(result, key=lambda item: item.symbol))
