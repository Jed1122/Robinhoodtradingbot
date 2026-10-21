"""Pure current-stock fact normalization; no I/O, ranking or trading authority."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, DecimalException
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.recording import content_hash

_FUND_METRICS = (
    "open",
    "high",
    "low",
    "volume",
    "overnight_volume",
    "average_volume",
    "average_volume_2_weeks",
    "average_volume_30_days",
    "high_52_weeks",
    "low_52_weeks",
    "float",
    "market_cap",
    "pb_ratio",
    "pe_ratio",
    "shares_outstanding",
    "dividend_yield",
    "dividend_per_share",
    "thirty_day_sec_yield",
)
_FIN_METRICS = ("revenue", "gross_profit", "net_income", "net_margin")
_PRICE_METRICS = frozenset({"open", "high", "low", "high_52_weeks", "low_52_weeks"})
_NONNEGATIVE_METRICS = frozenset(
    {
        "volume",
        "overnight_volume",
        "average_volume",
        "average_volume_2_weeks",
        "average_volume_30_days",
        "float",
        "shares_outstanding",
        "market_cap",
    }
)
_FUND_DATES = (
    "market_date",
    "high_52_weeks_date",
    "low_52_weeks_date",
    "payable_date",
    "ex_dividend_date",
    "record_date",
)
_FUND_TEXT = (
    "bounds",
    "description",
    "ceo",
    "headquarters_city",
    "headquarters_state",
    "sector",
    "industry",
    "distribution_frequency",
    "financial_status_indicator",
    "financial_status_description",
)
_LIMITATIONS = (
    "source_receipt_hash_is_caller_declared_not_authenticated",
    "current_receipt_not_historical_point_in_time_availability",
    "missing_metrics_are_not_zero",
    "source_coverage_corporate_actions_and_units_unqualified",
    "no_average_dollar_volume_inferred_from_share_volume",
    "bar_omissions_do_not_certify_contiguous_or_calendar_coverage",
)
_Tool = Literal["get_equity_fundamentals", "get_financials", "get_equity_historicals"]


def _check(valid: bool) -> None:
    if not valid:
        raise ValueError("stock_facts_invalid")


def _utc(value: datetime) -> datetime:
    try:
        return require_utc(value)
    except ValueError:
        raise ValueError("stock_facts_invalid") from None


def _mapping(value: object, allowed: set[str]) -> dict[str, object]:
    _check(isinstance(value, Mapping))
    if not isinstance(value, Mapping):
        raise ValueError("stock_facts_invalid")
    _check(all(type(key) is str and key in allowed for key in value))
    return dict(value)


def _array(value: object, maximum: int) -> list[object]:
    if value is None:
        return []
    _check(type(value) is list and len(value) <= maximum)
    if not isinstance(value, list):
        raise ValueError("stock_facts_invalid")
    return list(value)


def _symbol(value: object) -> str:
    _check(
        type(value) is str and re.fullmatch(r"[A-Z0-9][A-Z0-9.$+^=/@_-]{0,31}", value) is not None
    )
    return str(value)


def _date(value: object) -> date:
    _check(type(value) is str and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is not None)
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValueError("stock_facts_invalid") from None


def _timestamp(value: object) -> datetime:
    _check(type(value) is str and len(value) <= 64 and "T" in value)
    try:
        return _utc(datetime.fromisoformat(str(value)))
    except ValueError:
        raise ValueError("stock_facts_invalid") from None


def _decimal(value: object, name: str) -> Decimal:
    _check(type(value) is str and 0 < len(value) <= 512 and value == value.strip())
    _check(
        re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", str(value))
        is not None
    )
    try:
        return require_bounded_decimal(
            Decimal(str(value)),
            name,
            positive=name in _PRICE_METRICS or name.endswith("_price"),
            nonnegative=name in _NONNEGATIVE_METRICS,
        )
    except (ValueError, DecimalException):
        raise ValueError("stock_facts_invalid") from None


@dataclass(frozen=True, slots=True)
class StockObservationReceipt:
    tool: _Tool
    received_at: datetime
    observation_sha256: str
    hash_is_caller_declared: Literal[True] = field(default=True, init=False)

    def __post_init__(self) -> None:
        _check(self.tool in ("get_equity_fundamentals", "get_financials", "get_equity_historicals"))
        _utc(self.received_at)
        try:
            _require_sha256_hex(self.observation_sha256, "stock observation")
        except ValueError:
            raise ValueError("stock_facts_invalid") from None


@dataclass(frozen=True, slots=True)
class StockDecimalMetric:
    name: str
    value: Decimal


@dataclass(frozen=True, slots=True)
class StockFundamentals:
    symbol: str
    receipt: StockObservationReceipt
    market_date: date | None
    bounds: str | None
    metrics: tuple[StockDecimalMetric, ...]
    missing_metrics: tuple[str, ...]
    sector: str | None
    industry: str | None

    @property
    def available_at(self) -> datetime:
        return self.receipt.received_at


@dataclass(frozen=True, slots=True)
class StockFinancialPeriod:
    symbol: str
    receipt: StockObservationReceipt
    period: Literal["annual", "quarterly"]
    fiscal_year: int
    fiscal_quarter: int | None
    period_end: date
    metrics: tuple[StockDecimalMetric, ...]
    missing_metrics: tuple[str, ...]
    period_start: None = field(default=None, init=False)
    currency: None = field(default=None, init=False)

    @property
    def available_at(self) -> datetime:
        return self.receipt.received_at


@dataclass(frozen=True, slots=True)
class StockDailyBar:
    symbol: str
    receipt: StockObservationReceipt
    begins_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    interpolated: bool | None
    session: str | None
    price_basis: Literal["raw", "unknown"]
    raw_basis_caller_declared: bool
    completion_status: Literal["unknown", "caller_declared_complete"]
    completed_by: datetime | None
    completed_at: None = field(default=None, init=False)

    @property
    def left_edge_date(self) -> date:
        """UTC date of the source's left edge, not a certified exchange session."""
        return self.begins_at.date()

    @property
    def available_at(self) -> datetime:
        return self.receipt.received_at


@dataclass(frozen=True, slots=True)
class StockInterpolatedBarOmission:
    symbol: str
    begins_at: datetime
    reason: Literal["source_declared_interpolated"] = field(
        default="source_declared_interpolated", init=False
    )


@dataclass(frozen=True, slots=True)
class StockFactCollection[T: (StockFundamentals, StockFinancialPeriod, StockDailyBar)]:
    receipt: StockObservationReceipt
    records: tuple[T, ...]
    reported_symbols: tuple[str, ...]
    not_found: tuple[str, ...]
    unavailable_symbols: tuple[str, ...]
    results_missing: bool
    null_row_count: int
    scope_verified: bool
    requested_symbols: tuple[str, ...] | None
    request_adjustment_type: Literal["none"] | None = None
    completed_before: datetime | None = None
    omitted_interpolated_count: int = 0
    omitted_interpolated_bars: tuple[StockInterpolatedBarOmission, ...] = ()
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)

    @property
    def observation_hash(self) -> str:
        return str(content_hash(("stock-facts-normalized-v2", self)))


def _envelope(
    payload: Mapping[str, object], maximum: int, *, not_found: bool = True
) -> tuple[list[object], tuple[str, ...], bool]:
    root = _mapping(payload, {"data", "guide"})
    if "guide" in root:
        _check(type(root["guide"]) is str and len(str(root["guide"])) <= 65536)
    data = _mapping(root.get("data"), {"results", "not_found"} if not_found else {"results"})
    _check("results" in data)
    rows = _array(data["results"], maximum)
    absent = tuple(_symbol(item) for item in _array(data.get("not_found"), maximum))
    _check(len(set(absent)) == len(absent))
    return rows, absent, data["results"] is None


def _requested(requested: tuple[str, ...] | None, maximum: int) -> tuple[str, ...] | None:
    if requested is None:
        return None
    _check(type(requested) is tuple and 1 <= len(requested) <= maximum)
    symbols = tuple(_symbol(item) for item in requested)
    _check(len(set(symbols)) == len(symbols))
    return symbols


def _scope(
    reported: list[str],
    absent: tuple[str, ...],
    requested: tuple[str, ...] | None,
    maximum: int,
    nulls: int,
    *,
    positional_unavailable: tuple[str, ...] = (),
) -> bool:
    known = (*reported, *absent, *positional_unavailable)
    _check(len(set(known)) == len(known) and len(known) <= maximum)
    symbols = _requested(requested, maximum)
    if symbols is None:
        return False
    _check(set(symbols) == set(known))
    return nulls == 0


def _metrics(
    row: Mapping[str, object], names: tuple[str, ...]
) -> tuple[tuple[StockDecimalMetric, ...], tuple[str, ...]]:
    values, missing = [], []
    for name in names:
        if row.get(name) is None:
            missing.append(name)
        else:
            values.append(StockDecimalMetric(name, _decimal(row[name], name)))
    return tuple(values), tuple(missing)


def normalize_fundamentals(
    payload: Mapping[str, object],
    *,
    received_at: datetime,
    observation_sha256: str,
    requested_symbols: tuple[str, ...] | None = None,
) -> StockFactCollection[StockFundamentals]:
    receipt = StockObservationReceipt(
        "get_equity_fundamentals", _utc(received_at), observation_sha256
    )
    rows, absent, missing = _envelope(payload, 10)
    records: list[StockFundamentals] = []
    reported: list[str] = []
    nulls = 0
    allowed = set(
        _FUND_METRICS + _FUND_DATES + _FUND_TEXT + ("symbol", "num_employees", "year_founded")
    )
    for item in rows:
        if item is None:
            nulls += 1
            continue
        row = _mapping(item, allowed)
        symbol = _symbol(row.get("symbol"))
        reported.append(symbol)
        for name in _FUND_TEXT:
            _check(
                row.get(name) is None or (type(row[name]) is str and len(str(row[name])) <= 32768)
            )
        for name in ("num_employees", "year_founded"):
            _check(row.get(name) is None or type(row[name]) is int)
        dates = {name: None if row.get(name) is None else _date(row[name]) for name in _FUND_DATES}
        for name in ("market_date", "high_52_weeks_date", "low_52_weeks_date"):
            observed_date = dates[name]
            _check(observed_date is None or observed_date <= receipt.received_at.date())
        bounds = row.get("bounds")
        _check(bounds is None or bounds in ("regular", "trading", "extended", "24_5"))
        metrics, unknown = _metrics(row, _FUND_METRICS)
        by_name = {metric.name: metric.value for metric in metrics}
        for low_name, high_name in (
            ("low", "high"),
            ("low", "open"),
            ("open", "high"),
            ("low_52_weeks", "high_52_weeks"),
        ):
            if low_name in by_name and high_name in by_name:
                _check(by_name[low_name] <= by_name[high_name])
        records.append(
            StockFundamentals(
                symbol,
                receipt,
                dates["market_date"],
                None if bounds is None else str(bounds),
                metrics,
                unknown,
                None if row.get("sector") is None else str(row["sector"]),
                None if row.get("industry") is None else str(row["industry"]),
            )
        )
    verified = _scope(reported, absent, requested_symbols, 10, nulls)
    return StockFactCollection(
        receipt,
        tuple(records),
        tuple(reported),
        absent,
        (),
        missing,
        nulls,
        verified,
        requested_symbols,
    )


def normalize_financials(
    payload: Mapping[str, object],
    *,
    received_at: datetime,
    observation_sha256: str,
    requested_symbols: tuple[str, ...] | None = None,
) -> StockFactCollection[StockFinancialPeriod]:
    receipt = StockObservationReceipt("get_financials", _utc(received_at), observation_sha256)
    rows, absent, missing = _envelope(payload, 20, not_found=False)
    requested = _requested(requested_symbols, 20)
    _check(requested is None or len(rows) == len(requested))
    records: list[StockFinancialPeriod] = []
    reported, unavailable = [], []
    positional_unavailable = []
    nulls = 0
    for index, item in enumerate(rows):
        if item is None:
            nulls += 1
            if requested is not None:
                unavailable.append(requested[index])
                positional_unavailable.append(requested[index])
            continue
        row = _mapping(item, {"symbol", "period", "financials"})
        symbol = _symbol(row.get("symbol"))
        _check(requested is None or symbol == requested[index])
        reported.append(symbol)
        period = row.get("period")
        _check(period in ("annual", "quarterly"))
        period_kind: Literal["annual", "quarterly"] = (
            "annual" if period == "annual" else "quarterly"
        )
        periods = _array(row.get("financials"), 40)
        previous: date | None = None
        seen: set[tuple[int, int | None]] = set()
        count = 0
        for item_period in periods:
            if item_period is None:
                nulls += 1
                continue
            fact = _mapping(
                item_period,
                {*_FIN_METRICS, "fiscal_year", "fiscal_quarter", "period_end_date"},
            )
            year, quarter = fact.get("fiscal_year"), fact.get("fiscal_quarter")
            _check(type(year) is int and 1 <= year <= 9999)
            _check(quarter is None or (type(quarter) is int and 1 <= quarter <= 4))
            _check(period_kind != "annual" or quarter is None)
            if not isinstance(year, int) or (quarter is not None and not isinstance(quarter, int)):
                raise ValueError("stock_facts_invalid")
            end = _date(fact.get("period_end_date"))
            _check(end <= receipt.received_at.date() and (previous is None or end < previous))
            _check((period_kind == "quarterly" and quarter is None) or (year, quarter) not in seen)
            previous = end
            seen.add((year, quarter))
            metrics, unknown = _metrics(fact, _FIN_METRICS)
            records.append(
                StockFinancialPeriod(
                    symbol, receipt, period_kind, year, quarter, end, metrics, unknown
                )
            )
            count += 1
        if count == 0:
            unavailable.append(symbol)
    verified = _scope(
        reported,
        absent,
        requested,
        20,
        nulls,
        positional_unavailable=tuple(positional_unavailable),
    )
    return StockFactCollection(
        receipt,
        tuple(records),
        tuple(reported),
        absent,
        tuple(unavailable),
        missing,
        nulls,
        verified,
        requested_symbols,
    )


def normalize_daily_bars(
    payload: Mapping[str, object],
    *,
    received_at: datetime,
    observation_sha256: str,
    requested_symbols: tuple[str, ...] | None = None,
    request_adjustment_type: Literal["none"] | None = None,
    completed_before: datetime | None = None,
) -> StockFactCollection[StockDailyBar]:
    receipt = StockObservationReceipt(
        "get_equity_historicals", _utc(received_at), observation_sha256
    )
    _check(
        request_adjustment_type is None
        or (type(request_adjustment_type) is str and request_adjustment_type == "none")
    )
    cutoff = None if completed_before is None else _utc(completed_before)
    _check(cutoff is None or cutoff <= receipt.received_at)
    rows, absent, missing = _envelope(payload, 10)
    records: list[StockDailyBar] = []
    omissions: list[StockInterpolatedBarOmission] = []
    reported, unavailable = [], []
    nulls = 0
    for item in rows:
        _check(item is not None)
        row = _mapping(item, {"symbol", "interval", "bounds", "bars"})
        symbol = _symbol(row.get("symbol"))
        reported.append(symbol)
        _check(row.get("interval") == "day" and row.get("bounds") == "regular")
        previous: datetime | None = None
        count = 0
        for item_bar in _array(row.get("bars"), 10000):
            if item_bar is None:
                nulls += 1
                continue
            bar = _mapping(
                item_bar,
                {
                    "begins_at",
                    "open_price",
                    "close_price",
                    "high_price",
                    "low_price",
                    "volume",
                    "interpolated",
                    "session",
                },
            )
            starts = _timestamp(bar.get("begins_at"))
            _check(starts <= receipt.received_at and (previous is None or starts > previous))
            previous = starts
            interpolated, session = bar.get("interpolated"), bar.get("session")
            _check("interpolated" not in bar or type(interpolated) is bool)
            _check("session" not in bar or type(session) is str)
            _check(session is None or session == "reg")
            opened, high, low, close = (
                _decimal(bar.get(name), name)
                for name in ("open_price", "high_price", "low_price", "close_price")
            )
            _check(low <= opened <= high and low <= close <= high)
            volume = bar.get("volume")
            _check(type(volume) is int and 0 <= volume <= 2**63 - 1)
            if not isinstance(volume, int):
                raise ValueError("stock_facts_invalid")
            _check(len(records) + len(omissions) < 30000)
            if interpolated is True:
                omissions.append(StockInterpolatedBarOmission(symbol, starts))
                continue
            complete = cutoff is not None and starts < cutoff
            records.append(
                StockDailyBar(
                    symbol,
                    receipt,
                    starts,
                    opened,
                    high,
                    low,
                    close,
                    Decimal(volume),
                    None if interpolated is None else bool(interpolated),
                    None if session is None else str(session),
                    "raw" if request_adjustment_type == "none" else "unknown",
                    request_adjustment_type == "none",
                    "caller_declared_complete" if complete else "unknown",
                    cutoff if complete else None,
                )
            )
            count += 1
        if count == 0:
            unavailable.append(symbol)
    verified = _scope(reported, absent, requested_symbols, 10, nulls)
    return StockFactCollection(
        receipt,
        tuple(records),
        tuple(reported),
        absent,
        tuple(unavailable),
        missing,
        nulls,
        verified,
        requested_symbols,
        request_adjustment_type,
        cutoff,
        omitted_interpolated_count=len(omissions),
        omitted_interpolated_bars=tuple(omissions),
    )
