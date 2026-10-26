"""Dimensionless split-price descriptions of separately admitted daily evidence."""

from dataclasses import dataclass, field
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
from typing import Literal

from trading_bot.domain.decimal_utils import require_bounded_decimal
from trading_bot.market_data.recording import content_hash
from trading_bot.market_data.stock_daily_series import (
    StockDailySeries,
    StockDailySeriesError,
    validate_stock_daily_series,
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
    "close_to_sma_50",
    "close_to_sma_200",
    "realized_volatility_20",
    "series_max_drawdown",
)
_LIMITATIONS = (
    "descriptive_split_only_price_changes_not_total_returns_or_forecasts",
    "calendar_source_currency_and_vintage_limits_retained_in_input_evidence",
    "252_session_volatility_annualization_is_a_convention_not_observed_year_length",
    "no_volume_currency_liquidity_ranking_or_investment_metrics",
)


@dataclass(frozen=True, slots=True)
class StockDailyPriceMetrics:
    price_return_20: Decimal | None = None
    price_return_60: Decimal | None = None
    price_return_120: Decimal | None = None
    close_to_sma_50: Decimal | None = None
    close_to_sma_200: Decimal | None = None
    realized_volatility_20: Decimal | None = None
    series_max_drawdown: Decimal | None = None


@dataclass(frozen=True, slots=True)
class StockDailyPriceFeatures:
    symbol: str | None
    source_evidence_hash: str | None
    status: Literal["calculated", "ineligible"]
    metrics: StockDailyPriceMetrics | None
    missing_metrics: tuple[str, ...]
    reason_codes: tuple[str, ...]
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
    def evidence_hash(self) -> str:
        return str(content_hash(("stock-daily-price-features-v1", self)))


def calculate_stock_daily_price_features(value: StockDailySeries | None) -> StockDailyPriceFeatures:
    """Revalidate original inputs; calculate only dimensionless, fixed-context metrics."""
    try:
        if value is None:
            raise StockDailySeriesError()
        admitted = validate_stock_daily_series(value)
        provenance = admitted.evidence_hash
    except StockDailySeriesError:
        return StockDailyPriceFeatures(
            None, None, "ineligible", None, _NAMES, ("invalid_or_absent_series",)
        )
    source = admitted.series
    symbol = None if source is None else source.request.symbol
    if admitted.status != "descriptive_admissible" or source is None:
        return StockDailyPriceFeatures(
            symbol, provenance, "ineligible", None, _NAMES, admitted.reason_codes
        )
    prices = tuple(row.close_price for row in source.bars)
    values: dict[str, Decimal] = {}
    try:
        with localcontext(_CONTEXT):
            for lag in (20, 60, 120):
                if len(prices) > lag:
                    values[f"price_return_{lag}"] = prices[-1] / prices[-lag - 1] - 1
            for window in (50, 200):
                if len(prices) >= window:
                    mean = sum(prices[-window:], Decimal(0)) / Decimal(window)
                    values[f"close_to_sma_{window}"] = prices[-1] / mean - 1
            if len(prices) >= 21:
                returns = tuple(
                    prices[i] / prices[i - 1] - 1 for i in range(len(prices) - 20, len(prices))
                )
                mean = sum(returns, Decimal(0)) / Decimal(20)
                variance = sum(((r - mean) ** 2 for r in returns), Decimal(0)) / Decimal(19)
                values["realized_volatility_20"] = (variance * Decimal(252)).sqrt()
            peak, drawdown = prices[0], Decimal(0)
            for price in prices[1:]:
                peak = max(peak, price)
                drawdown = max(drawdown, 1 - price / peak)
            values["series_max_drawdown"] = drawdown
            for name, number in values.items():
                require_bounded_decimal(number, name)
    except (ValueError, DecimalException):
        return StockDailyPriceFeatures(
            symbol, provenance, "ineligible", None, _NAMES, ("arithmetic_invalid",)
        )
    return StockDailyPriceFeatures(
        symbol,
        provenance,
        "calculated",
        StockDailyPriceMetrics(**values),
        tuple(name for name in _NAMES if name not in values),
        (),
    )
