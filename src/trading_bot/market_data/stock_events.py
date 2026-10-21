"""Pure receipt-bound earnings and filing-index facts; no I/O or trading authority."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, DecimalException
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.recording import content_hash

_LIMITATIONS = (
    "source_receipt_hash_is_caller_declared_not_authenticated",
    "available_at_is_receipt_not_historical_publication",
    "exact_publication_time_unknown",
    "null_metrics_are_not_zero",
    "estimates_are_source_estimates_not_actuals",
    "source_and_strategy_unqualified",
)


def _check(valid: bool) -> None:
    if not valid:
        raise ValueError("stock_events_invalid")


def _mapping(value: object, allowed: set[str], required: set[str]) -> dict[str, object]:
    _check(isinstance(value, Mapping))
    if not isinstance(value, Mapping):
        raise ValueError("stock_events_invalid")
    _check(all(type(key) is str and key in allowed for key in value))
    _check(required.issubset(value))
    return dict(value)


def _symbol(value: object) -> str:
    _check(type(value) is str and re.fullmatch(r"[A-Z][A-Z0-9.\-/]{0,14}", value) is not None)
    return str(value)


def _text(value: object, maximum: int, *, empty: bool = False) -> str:
    _check(type(value) is str and (empty or bool(value)) and len(str(value)) <= maximum)
    _check(not any(ord(character) < 32 or ord(character) == 127 for character in str(value)))
    return str(value)


def _date(value: object) -> date:
    _check(type(value) is str and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is not None)
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValueError("stock_events_invalid") from None


def _eps(value: object) -> Decimal | None:
    if value is None:
        return None
    _check(type(value) is str and 0 < len(str(value)) <= 512)
    _check(
        re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", str(value))
        is not None
    )
    try:
        return require_bounded_decimal(Decimal(str(value)), "earnings EPS")
    except (ValueError, DecimalException):
        raise ValueError("stock_events_invalid") from None


def _rows(value: object, maximum: int) -> list[object]:
    if value is None:
        return []
    _check(type(value) is list and len(value) <= maximum)
    if not isinstance(value, list):
        raise ValueError("stock_events_invalid")
    return list(value)


def _data(
    payload: Mapping[str, object], allowed: set[str], required: set[str]
) -> dict[str, object]:
    root = _mapping(payload, {"data", "guide"}, {"data"})
    if "guide" in root:
        _check(type(root["guide"]) is str and len(str(root["guide"])) <= 65536)
    return _mapping(root["data"], allowed, required)


@dataclass(frozen=True, slots=True)
class _Unqualified:
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_enabled: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class StockEventReceipt:
    tool: Literal["get_earnings_results", "get_sec_filing_index"]
    received_at: datetime
    observation_sha256: str
    hash_is_caller_declared: Literal[True] = field(default=True, init=False)

    def __post_init__(self) -> None:
        try:
            _check(self.tool in ("get_earnings_results", "get_sec_filing_index"))
            _check(isinstance(self.received_at, datetime))
            require_utc(self.received_at)
            _require_sha256_hex(self.observation_sha256, "stock observation")
        except (TypeError, ValueError):
            raise ValueError("stock_events_invalid") from None


@dataclass(frozen=True, slots=True)
class StockEarningsEvent(_Unqualified):
    symbol: str
    receipt: StockEventReceipt
    fiscal_year: int
    fiscal_quarter: int
    eps_actual: Decimal | None
    eps_estimate: Decimal | None
    report_date: date | None
    report_timing: Literal["am", "pm"] | None
    report_verified: bool | None
    report_scheduled: bool
    publication_at: None = field(default=None, init=False)

    @property
    def available_at(self) -> datetime:
        return self.receipt.received_at

    @property
    def reported(self) -> bool:
        return self.eps_actual is not None


@dataclass(frozen=True, slots=True)
class StockFiling(_Unqualified):
    symbol: str
    receipt: StockEventReceipt
    filing_id: str
    date_filed: date
    form_type: str
    description: str
    source_url: None = field(default=None, init=False)
    publication_at: None = field(default=None, init=False)

    @property
    def available_at(self) -> datetime:
        return self.receipt.received_at


@dataclass(frozen=True, slots=True)
class _Collection[T: (StockEarningsEvent, StockFiling)](_Unqualified):
    receipt: StockEventReceipt
    requested_symbol: str
    records: tuple[T, ...]
    null_row_count: int
    response_results_missing: bool
    scope_verified: bool
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)

    @property
    def available_at(self) -> datetime:
        return self.receipt.received_at

    @property
    def observation_hash(self) -> str:
        return str(content_hash(("stock-events-normalized-v1", self)))


@dataclass(frozen=True, slots=True)
class StockEarningsCollection(_Collection[StockEarningsEvent]):
    not_found: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StockFilingCollection(_Collection[StockFiling]):
    next_cursor: str | None = None
    history_complete: Literal[False] = field(default=False, init=False)

    @property
    def has_more(self) -> bool:
        return bool(self.next_cursor)

    @property
    def pagination_state(self) -> Literal["more", "terminal", "unknown"]:
        if self.next_cursor is None:
            return "unknown"
        return "more" if self.next_cursor else "terminal"


def normalize_earnings_results(
    payload: Mapping[str, object],
    *,
    received_at: datetime,
    observation_sha256: str,
    requested_symbol: str,
) -> StockEarningsCollection:
    """Keep actuals, estimates and scheduling separate; reject future actual report dates."""
    symbol = _symbol(requested_symbol)
    receipt = StockEventReceipt("get_earnings_results", received_at, observation_sha256)
    data = _data(payload, {"results", "not_found"}, {"results"})
    rows = _rows(data["results"], 8)
    not_found = tuple(_symbol(item) for item in _rows(data.get("not_found"), 1))
    _check(not not_found or not_found == (symbol,))
    records: list[StockEarningsEvent] = []
    previous: tuple[int, int] | None = None
    nulls = 0
    for item in rows:
        if item is None:
            nulls += 1
            continue
        fields = {"symbol", "year", "quarter", "eps", "report"}
        row = _mapping(item, fields, fields)
        _check(_symbol(row["symbol"]) == symbol)
        year, quarter = row["year"], row["quarter"]
        _check(type(year) is int and 1 <= year <= 9999)
        _check(type(quarter) is int and 1 <= quarter <= 4)
        if not isinstance(year, int) or not isinstance(quarter, int):
            raise ValueError("stock_events_invalid")
        period = (year, quarter)
        _check(previous is None or period > previous)
        previous = period
        eps = _mapping(row["eps"], {"actual", "estimate"}, {"actual", "estimate"})
        actual, estimate = _eps(eps["actual"]), _eps(eps["estimate"])
        report_date: date | None = None
        report_timing: Literal["am", "pm"] | None = None
        verified: bool | None = None
        scheduled = row["report"] is not None
        if scheduled:
            fields = {"date", "timing", "verified"}
            report = _mapping(row["report"], fields, fields)
            report_date = None if report["date"] is None else _date(report["date"])
            _check(report["timing"] in (None, "am", "pm"))
            report_timing = (
                None if report["timing"] is None else "am" if report["timing"] == "am" else "pm"
            )
            _check(type(report["verified"]) is bool)
            verified = bool(report["verified"])
        _check(actual is None or report_date is None or report_date <= receipt.received_at.date())
        records.append(
            StockEarningsEvent(
                symbol,
                receipt,
                year,
                quarter,
                actual,
                estimate,
                report_date,
                report_timing,
                verified,
                scheduled,
            )
        )
    _check(not not_found or not rows)
    missing = data["results"] is None
    return StockEarningsCollection(
        receipt,
        symbol,
        tuple(records),
        nulls,
        missing,
        bool(records or not_found) and not nulls and not missing,
        not_found,
    )


def normalize_filing_index(
    payload: Mapping[str, object],
    *,
    received_at: datetime,
    observation_sha256: str,
    requested_symbol: str,
) -> StockFilingCollection:
    """Normalize one index page; terminal pagination never certifies full filing history."""
    symbol = _symbol(requested_symbol)
    receipt = StockEventReceipt("get_sec_filing_index", received_at, observation_sha256)
    data = _data(payload, {"symbol", "filings", "next"}, {"symbol", "filings"})
    _check(_symbol(data["symbol"]) == symbol)
    cursor = _text(data["next"], 4096, empty=True) if "next" in data else None
    rows = _rows(data["filings"], 1000)
    records: list[StockFiling] = []
    seen: set[str] = set()
    previous: date | None = None
    nulls = 0
    for item in rows:
        if item is None:
            nulls += 1
            continue
        fields = {"filing_id", "date_filed", "form_type", "description"}
        row = _mapping(item, fields, fields)
        identity = _text(row["filing_id"], 512)
        _check(identity not in seen)
        seen.add(identity)
        filed = _date(row["date_filed"])
        _check(filed <= receipt.received_at.date() and (previous is None or filed <= previous))
        previous = filed
        records.append(
            StockFiling(
                symbol,
                receipt,
                identity,
                filed,
                _text(row["form_type"], 64),
                _text(row["description"], 4096, empty=True),
            )
        )
    return StockFilingCollection(
        receipt,
        symbol,
        tuple(records),
        nulls,
        data["filings"] is None,
        True,
        cursor,
    )
