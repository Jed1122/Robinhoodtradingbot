"""Pure, unqualified stock SIP minute provenance and exclusive-close assessment.

No provider I/O or source/technical admission. Calendar, request and receipt
context remain caller declarations; exact bytes establish local integrity only.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Literal, cast
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.alpaca_native import (
    _native_json,
    format_timestamp_ns,
    parse_timestamp_ns,
)
from trading_bot.market_data.recording import content_hash

MAX_PAGE_BYTES = 1_048_576
MAX_PROOF_BYTES = 4 * MAX_PAGE_BYTES
MAX_SESSIONS = 2
MAX_PAGES_PER_SESSION = 2
MAX_PROOF_PAGES = 4
_MINUTE_NS = 60_000_000_000
_NY = ZoneInfo("America/New_York")
_SYMBOL = re.compile(r"[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)*\Z")


class AlpacaStockMinuteError(ValueError):
    """Fixed error code without source payloads or caller identifiers."""

    def __init__(self) -> None:
        super().__init__("alpaca_stock_minutes_invalid")


def _check(value: bool) -> None:
    if not value:
        raise AlpacaStockMinuteError()


def _utc(value: datetime) -> None:
    _check(type(value) is datetime and value.tzinfo is not None)
    _check(value.utcoffset() == timedelta(0))


def _integer(value: object, *, positive: bool = False, maximum: int = 2**63 - 1) -> int:
    _check(type(value) is int)
    result = cast(int, value)
    _check((1 if positive else 0) <= result <= maximum)
    return result


def _digest(value: str) -> None:
    try:
        _require_sha256_hex(value, "source")
    except ValueError:
        raise AlpacaStockMinuteError() from None


def _token(value: object) -> None:
    _check(
        value is None
        or (
            type(value) is str
            and 0 < len(value) <= 4096
            and all(33 <= ord(char) <= 126 for char in value)
        )
    )


def _ns(value: datetime) -> int:
    _utc(value)
    return parse_timestamp_ns(value.isoformat())


@dataclass(frozen=True, slots=True, repr=False)
class _Unqualified:
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True, repr=False)
class StockCoreSessionDeclaration(_Unqualified):
    """Caller-declared NY core window, not an authenticated exchange calendar."""

    session_date: date
    opens_at: datetime
    closes_at: datetime
    calendar_source_url: str
    calendar_sha256: str
    calendar_received_at: datetime
    calendar_authenticity_verified: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        try:
            _check(type(self.session_date) is date and self.session_date.weekday() < 5)
            for stamp in (self.opens_at, self.closes_at, self.calendar_received_at):
                _utc(stamp)
            opening, closing = self.opens_at.astimezone(_NY), self.closes_at.astimezone(_NY)
            _check(opening.date() == closing.date() == self.session_date)
            _check(opening.timetz().replace(tzinfo=None) == time(9, 30))
            _check(closing.timetz().replace(tzinfo=None) in (time(13), time(16)))
            _digest(self.calendar_sha256)
            _check(type(self.calendar_source_url) is str and len(self.calendar_source_url) <= 2048)
            url = urlsplit(self.calendar_source_url)
            _check(url.scheme == "https" and bool(url.hostname))
            _check(url.username is None and url.password is None and not url.fragment)
        except (ValueError, TypeError, AttributeError, OverflowError):
            raise AlpacaStockMinuteError() from None

    @property
    def expected_minutes(self) -> int:
        return (self.closes_at - self.opens_at) // timedelta(minutes=1)


@dataclass(frozen=True, slots=True, repr=False)
class StockMinuteRequest(_Unqualified):
    symbol: str
    session: StockCoreSessionDeclaration
    feed: Literal["sip"] = field(default="sip", init=False)
    timeframe: Literal["1Min"] = field(default="1Min", init=False)
    adjustment: Literal["raw"] = field(default="raw", init=False)
    currency: Literal["USD"] = field(default="USD", init=False)
    symbol_mapping: Literal["-"] = field(default="-", init=False)
    request_is_caller_declared: Literal[True] = field(default=True, init=False)

    def __post_init__(self) -> None:
        _check(type(self.symbol) is str and 1 <= len(self.symbol) <= 16)
        _check(_SYMBOL.fullmatch(self.symbol) is not None)
        _check(type(self.session) is StockCoreSessionDeclaration)
        self.session.__post_init__()

    @property
    def url(self) -> str:
        return "https://data.alpaca.markets/v2/stocks/" + self.symbol + "/bars"

    @property
    def request_sha256(self) -> str:
        return content_hash({"schema": "alpaca-stock-minute-request-v1", "request": self})

    def query(self, page_token: str | None = None) -> tuple[tuple[str, str], ...]:
        self.__post_init__()
        _token(page_token)
        values = (
            ("start", format_timestamp_ns(_ns(self.session.opens_at))),
            ("end", format_timestamp_ns(_ns(self.session.closes_at) - 1)),
            ("timeframe", "1Min"),
            ("feed", "sip"),
            ("adjustment", "raw"),
            ("currency", "USD"),
            ("asof", "-"),
            ("sort", "asc"),
            ("limit", "1000"),
        )
        return values if page_token is None else (*values, ("page_token", page_token))


@dataclass(frozen=True, slots=True, repr=False)
class StockMinuteBar(_Unqualified):
    request_sha256: str
    body_sha256: str
    page_index: int
    row_index: int
    timestamp_ns: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    trade_count: int
    vwap: Decimal
    native_interpolated: None = field(default=None, init=False)
    publication_at: None = field(default=None, init=False)

    def __post_init__(self) -> None:
        try:
            _digest(self.request_sha256)
            _digest(self.body_sha256)
            _integer(self.page_index, maximum=MAX_PAGES_PER_SESSION - 1)
            _integer(self.row_index, maximum=999)
            _integer(self.timestamp_ns)
            _check(self.timestamp_ns % _MINUTE_NS == 0)
            for price in (self.open, self.high, self.low, self.close, self.vwap):
                require_bounded_decimal(price, "minute", positive=True)
            _check(
                self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high
            )
            _integer(self.volume, positive=True)
            _integer(self.trade_count, positive=True)
        except (ValueError, TypeError, ArithmeticError):
            raise AlpacaStockMinuteError() from None

    @property
    def record_sha256(self) -> str:
        return content_hash({"schema": "alpaca-stock-minute-record-v1", "record": self})


def _price(value: object) -> Decimal:
    _check(type(value) in (int, Decimal))
    return require_bounded_decimal(Decimal(cast(int | Decimal, value)), "minute", positive=True)


def _decode(
    body: bytes, request: StockMinuteRequest, body_sha256: str, page_index: int
) -> tuple[Literal["USD"] | None, str | None, tuple[StockMinuteBar, ...]]:
    wire = _native_json(body)
    required = {"symbol", "bars", "next_page_token"}
    _check(required <= set(wire) <= required | {"currency"})
    _check(wire["symbol"] == request.symbol)
    _check("currency" not in wire or wire["currency"] == "USD")
    _token(wire["next_page_token"])
    rows = wire["bars"]
    _check(type(rows) is list and len(rows) <= 1000)
    records: list[StockMinuteBar] = []
    previous = None
    for index, entry in enumerate(cast(list[object], rows)):
        _check(type(entry) is dict)
        row = cast(dict[str, object], entry)
        _check(set(row) == {"t", "o", "h", "l", "c", "v", "n", "vw"})
        stamp = parse_timestamp_ns(cast(str, row["t"]))
        _check(_ns(request.session.opens_at) <= stamp < _ns(request.session.closes_at))
        _check(previous is None or stamp > previous)
        previous = stamp
        records.append(
            StockMinuteBar(
                request.request_sha256,
                body_sha256,
                page_index,
                index,
                stamp,
                _price(row["o"]),
                _price(row["h"]),
                _price(row["l"]),
                _price(row["c"]),
                _integer(row["v"], positive=True),
                _integer(row["n"], positive=True),
                _price(row["vw"]),
            )
        )
    return (
        "USD" if "currency" in wire else None,
        cast(str | None, wire["next_page_token"]),
        tuple(records),
    )


@dataclass(frozen=True, slots=True, repr=False)
class StockMinutePage(_Unqualified):
    request: StockMinuteRequest
    original_body: bytes
    body_sha256: str
    body_bytes: int
    page_index: int
    requested_page_token: str | None
    next_page_token: str | None
    capture_started_at: datetime
    received_at: datetime
    response_currency: Literal["USD"] | None
    records: tuple[StockMinuteBar, ...]
    receipt_is_caller_declared: Literal[True] = field(default=True, init=False)
    native_payload: Literal[True] = field(default=True, init=False)
    provider_authenticity_verified: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        try:
            _check(type(self.request) is StockMinuteRequest)
            self.request.__post_init__()
            _digest(self.body_sha256)
            _check(type(self.original_body) is bytes)
            _check(0 < _integer(self.body_bytes, maximum=MAX_PAGE_BYTES) == len(self.original_body))
            _check(hashlib.sha256(self.original_body).hexdigest() == self.body_sha256)
            _integer(self.page_index, maximum=MAX_PAGES_PER_SESSION - 1)
            _token(self.requested_page_token)
            _token(self.next_page_token)
            _utc(self.capture_started_at)
            _utc(self.received_at)
            _check(self.request.session.calendar_received_at <= self.capture_started_at)
            _check(
                self.request.session.closes_at + timedelta(minutes=15) <= self.capture_started_at
            )
            _check(self.capture_started_at <= self.received_at)
            _check(self.received_at - self.capture_started_at <= timedelta(seconds=60))
            _check(type(self.records) is tuple)
            currency, token, records = _decode(
                self.original_body, self.request, self.body_sha256, self.page_index
            )
            _check(
                (self.response_currency, self.next_page_token, self.records)
                == (currency, token, records)
            )
        except (ValueError, TypeError, ArithmeticError, AttributeError, RecursionError):
            raise AlpacaStockMinuteError() from None

    @property
    def receipt_sha256(self) -> str:
        return content_hash(
            {
                "schema": "alpaca-stock-minute-page-receipt-v1",
                "request": self.request.request_sha256,
                "body": self.body_sha256,
                "body_bytes": self.body_bytes,
                "page_index": self.page_index,
                "requested_page_token": self.requested_page_token,
                "next_page_token": self.next_page_token,
                "capture_started_at": self.capture_started_at,
                "received_at": self.received_at,
                "response_currency": self.response_currency,
            }
        )


def parse_stock_minute_page(
    body: bytes,
    *,
    request: StockMinuteRequest,
    expected_sha256: str,
    capture_started_at: datetime,
    received_at: datetime,
    page_index: int = 0,
    requested_page_token: str | None = None,
) -> StockMinutePage:
    """Verify bounded native bytes against declared request/receipt context, without I/O."""
    try:
        _check(type(request) is StockMinuteRequest)
        request.__post_init__()
        _digest(expected_sha256)
        _check(type(body) is bytes and 0 < len(body) <= MAX_PAGE_BYTES)
        _check(hashlib.sha256(body).hexdigest() == expected_sha256)
        _integer(page_index, maximum=MAX_PAGES_PER_SESSION - 1)
        currency, token, records = _decode(body, request, expected_sha256, page_index)
        return StockMinutePage(
            request,
            body,
            expected_sha256,
            len(body),
            page_index,
            requested_page_token,
            token,
            capture_started_at,
            received_at,
            currency,
            records,
        )
    except (ValueError, TypeError, ArithmeticError, AttributeError, RecursionError):
        raise AlpacaStockMinuteError() from None


@dataclass(frozen=True, slots=True, repr=False)
class StockCoreWindowAggregate(_Unqualified):
    request_sha256: str
    source_body_sha256: tuple[str, ...]
    member_record_sha256: tuple[str, ...]
    opens_at: datetime
    closes_at: datetime
    available_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    trade_count: int
    source_kind: Literal["alpaca-stock-core-minute-aggregate-v1"] = field(
        default="alpaca-stock-core-minute-aggregate-v1", init=False
    )
    session_basis: Literal["core_window_[open,close)"] = field(
        default="core_window_[open,close)", init=False
    )
    no_fill_applied: Literal[True] = field(default=True, init=False)
    raw_basis_is_caller_declared: Literal[True] = field(default=True, init=False)
    native_interpolated: None = field(default=None, init=False)
    publication_at: None = field(default=None, init=False)
    provider_finality_verified: Literal[False] = field(default=False, init=False)
    local_projection: Literal[True] = field(default=True, init=False)
    native_payload: Literal[False] = field(default=False, init=False)

    @property
    def aggregate_sha256(self) -> str:
        return content_hash({"schema": "alpaca-stock-core-window-aggregate-v1", "aggregate": self})


type MinuteReason = Literal["pages_missing", "pagination_incomplete", "missing_minutes"]


@dataclass(frozen=True, slots=True, repr=False)
class StockCoreWindowAssessment(_Unqualified):
    request: StockMinuteRequest
    pages: tuple[StockMinutePage, ...]
    assessed_at: datetime
    available_at: datetime
    transport_complete: bool
    expected_minutes: int
    observed_minutes: int
    missing_minute_starts_ns: tuple[int, ...]
    status: Literal["complete_grid", "incomplete", "unavailable"]
    reason_codes: tuple[MinuteReason, ...]
    aggregate: StockCoreWindowAggregate | None
    calendar_authenticity_verified: Literal[False] = field(default=False, init=False)

    @property
    def assessment_sha256(self) -> str:
        return content_hash(
            {
                "schema": "alpaca-stock-core-window-assessment-v1",
                "request": self.request.request_sha256,
                "page_receipts": tuple(page.receipt_sha256 for page in self.pages),
                "assessed_at": self.assessed_at,
                "available_at": self.available_at,
                "transport_complete": self.transport_complete,
                "expected_minutes": self.expected_minutes,
                "observed_minutes": self.observed_minutes,
                "missing": self.missing_minute_starts_ns,
                "status": self.status,
                "reasons": self.reason_codes,
                "aggregate": None if self.aggregate is None else self.aggregate.aggregate_sha256,
            }
        )


@dataclass(frozen=True, slots=True, repr=False)
class StockMinuteProofAssessment(_Unqualified):
    symbol: str
    sessions: tuple[StockCoreWindowAssessment, ...]
    total_pages: int
    total_bytes: int
    two_session_proof_complete: bool
    assessed_at: datetime
    entitlement_verified: Literal[False] = field(default=False, init=False)

    @property
    def assessment_sha256(self) -> str:
        return content_hash(
            {
                "schema": "alpaca-stock-minute-proof-assessment-v1",
                "symbol": self.symbol,
                "sessions": tuple(window.assessment_sha256 for window in self.sessions),
                "total_pages": self.total_pages,
                "total_bytes": self.total_bytes,
                "two_session_proof_complete": self.two_session_proof_complete,
                "assessed_at": self.assessed_at,
            }
        )


def _assess_window(
    request: StockMinuteRequest, pages: tuple[StockMinutePage, ...], as_of: datetime
) -> StockCoreWindowAssessment:
    records: list[StockMinuteBar] = []
    token = None
    seen_tokens: set[str] = set()
    previous_stamp = previous_receipt = None
    for index, page in enumerate(pages):
        _check(page.page_index == index and page.request == request)
        _check(page.requested_page_token == token and (index == 0 or token is not None))
        _check(page.capture_started_at == pages[0].capture_started_at)
        _check(previous_receipt is None or page.received_at > previous_receipt)
        previous_receipt = page.received_at
        for record in page.records:
            _check(previous_stamp is None or record.timestamp_ns > previous_stamp)
            previous_stamp = record.timestamp_ns
            records.append(record)
        token = page.next_page_token
        if token is not None:
            _check(token not in seen_tokens)
            seen_tokens.add(token)
    start, end = _ns(request.session.opens_at), _ns(request.session.closes_at)
    observed = {record.timestamp_ns for record in records}
    missing = tuple(stamp for stamp in range(start, end, _MINUTE_NS) if stamp not in observed)
    terminal = bool(pages) and token is None
    reasons: list[MinuteReason] = []
    if not pages:
        reasons.append("pages_missing")
    elif not terminal:
        reasons.append("pagination_incomplete")
    if missing:
        reasons.append("missing_minutes")
    aggregate = None
    if terminal and not missing:
        aggregate = StockCoreWindowAggregate(
            request.request_sha256,
            tuple(page.body_sha256 for page in pages),
            tuple(record.record_sha256 for record in records),
            request.session.opens_at,
            request.session.closes_at,
            as_of,
            records[0].open,
            max(record.high for record in records),
            min(record.low for record in records),
            records[-1].close,
            _integer(sum(record.volume for record in records), positive=True),
            _integer(sum(record.trade_count for record in records), positive=True),
        )
    return StockCoreWindowAssessment(
        request,
        pages,
        as_of,
        as_of,
        terminal,
        request.session.expected_minutes,
        len(records),
        missing,
        "unavailable"
        if not records
        else ("complete_grid" if aggregate is not None else "incomplete"),
        tuple(reasons),
        aggregate,
    )


def assess_stock_minute_proof(
    *, requests: tuple[StockMinuteRequest, ...], pages: tuple[StockMinutePage, ...], as_of: datetime
) -> StockMinuteProofAssessment:
    """Assess at most two declared sessions/four pages for one exact requested symbol.

    Every retained byte is rechecked; no gap filling, partial aggregate, provider
    finality, calendar authenticity, entitlement or technical admission follows.
    """
    try:
        _utc(as_of)
        _check(type(requests) is tuple and 0 < len(requests) <= MAX_SESSIONS)
        _check(type(pages) is tuple and len(pages) <= MAX_PROOF_PAGES)
        for request in requests:
            _check(type(request) is StockMinuteRequest)
            request.__post_init__()
            _check(request.symbol == requests[0].symbol)
            _check(request.session.closes_at + timedelta(minutes=15) <= as_of)
            _check(request.session.calendar_received_at <= as_of)
        _check(
            all(
                left.session.closes_at < right.session.opens_at
                for left, right in pairwise(requests)
            )
        )
        groups: list[list[StockMinutePage]] = [[] for _ in requests]
        previous_request_index = -1
        previous_receipt = None
        for page in pages:
            _check(type(page) is StockMinutePage)
            page.__post_init__()
            _check(page.request in requests and page.received_at <= as_of)
            _check(page.capture_started_at == pages[0].capture_started_at)
            _check(previous_receipt is None or page.received_at > previous_receipt)
            previous_receipt = page.received_at
            request_index = requests.index(page.request)
            _check(request_index >= previous_request_index)
            previous_request_index = request_index
            groups[request_index].append(page)
            _check(len(groups[request_index]) <= MAX_PAGES_PER_SESSION)
        total_bytes = sum(page.body_bytes for page in pages)
        _check(total_bytes <= MAX_PROOF_BYTES)
        windows = tuple(
            _assess_window(request, tuple(group), as_of)
            for request, group in zip(requests, groups, strict=True)
        )
        return StockMinuteProofAssessment(
            requests[0].symbol,
            windows,
            len(pages),
            total_bytes,
            len(windows) == 2 and all(window.status == "complete_grid" for window in windows),
            as_of,
        )
    except (ValueError, TypeError, ArithmeticError, AttributeError, RecursionError):
        raise AlpacaStockMinuteError() from None
