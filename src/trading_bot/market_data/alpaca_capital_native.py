"""Versioned, lossless daily syntax for the fixed capital-research ETF universe.

No I/O, credentials, dataset acceptance or historical availability assertion.
The existing SPY request and record hash formats remain unchanged.
"""

import hashlib
from dataclasses import dataclass, field, replace
from typing import Literal, cast

from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.alpaca_native import (
    MAX_PAGE_BYTES,
    MAX_PAGES,
    AlpacaArchiveAssessment,
    AlpacaBarRecord,
    AlpacaNativeError,
    AlpacaNativePage,
    AlpacaStockRequest,
    _check,
    _integer,
    _native_json,
    _price,
    parse_timestamp_ns,
)
from trading_bot.market_data.recording import content_hash


@dataclass(frozen=True, slots=True)
class CapitalDailyRequest:
    symbol: Literal["SPY", "QQQ", "IWM", "SHY", "IEF"]
    start_ns: int
    end_ns: int
    limit: int = 1000

    def __post_init__(self) -> None:
        _check(type(self.symbol) is str and self.symbol in ("SPY", "QQQ", "IWM", "SHY", "IEF"))
        self._common()

    def _common(self) -> AlpacaStockRequest:
        return AlpacaStockRequest("bars", self.start_ns, self.end_ns, self.limit)

    @property
    def path(self) -> str:
        self.__post_init__()
        return f"/v2/stocks/{self.symbol}/bars"

    @property
    def request_hash(self) -> str:
        self.__post_init__()
        return content_hash({"schema": "alpaca-capital-daily-request-v1", "request": self})

    def query(self, page_token: str | None = None) -> tuple[tuple[str, str], ...]:
        self.__post_init__()
        return self._common().query(page_token)


@dataclass(frozen=True, slots=True, repr=False)
class CapitalDailyBar:
    symbol: str
    bar: AlpacaBarRecord

    def __post_init__(self) -> None:
        _check(type(self.symbol) is str and self.symbol in ("SPY", "QQQ", "IWM", "SHY", "IEF"))
        _check(type(self.bar) is AlpacaBarRecord)
        replace(self.bar)

    @property
    def record_hash(self) -> str:
        self.__post_init__()
        return content_hash({"schema": "alpaca-capital-daily-record-v1", "record": self})


@dataclass(frozen=True, slots=True, repr=False)
class CapitalDailyPage:
    request: CapitalDailyRequest
    body_sha256: str
    page_index: int
    requested_page_token: str | None
    next_page_token: str | None
    records: tuple[CapitalDailyBar, ...]
    source_qualified: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _check(type(self.request) is CapitalDailyRequest)
        replace(self.request)
        _check(type(self.records) is tuple and len(self.records) <= self.request.limit)
        for record in self.records:
            _check(type(record) is CapitalDailyBar)
            replace(record)
            _check(record.symbol == self.request.symbol)
        # Shared native origin/range/row/cursor/count/order checks, without ever
        # rewriting the original body or mislabeling it as a SPY capture.
        AlpacaNativePage(
            self.request._common(),
            self.body_sha256,
            self.page_index,
            self.requested_page_token,
            self.next_page_token,
            tuple(record.bar for record in self.records),
        )
        _check(self.source_qualified is False and self.evidence_promotable is False)


def parse_capital_daily_page(
    body: bytes,
    *,
    request: CapitalDailyRequest,
    expected_sha256: str,
    page_index: int = 0,
    requested_page_token: str | None = None,
) -> CapitalDailyPage:
    """Retain raw origin and aggregation timestamps, not invented availability."""
    try:
        return _parse_capital_daily_page(
            body,
            request=request,
            expected_sha256=expected_sha256,
            page_index=page_index,
            requested_page_token=requested_page_token,
        )
    except (ValueError, TypeError, ArithmeticError, RecursionError):
        raise AlpacaNativeError() from None


def _parse_capital_daily_page(
    body: bytes,
    *,
    request: CapitalDailyRequest,
    expected_sha256: str,
    page_index: int,
    requested_page_token: str | None,
) -> CapitalDailyPage:
    _check(type(request) is CapitalDailyRequest)
    replace(request)
    _require_sha256_hex(expected_sha256, "expected body")
    _check(type(body) is bytes and 0 < len(body) <= MAX_PAGE_BYTES)
    _check(hashlib.sha256(body).hexdigest() == expected_sha256)
    wire = _native_json(body)
    required = {"symbol", "bars", "next_page_token"}
    _check(required <= set(wire) <= required | {"currency"})
    _check(wire["symbol"] == request.symbol and wire.get("currency", "USD") == "USD")
    rows = wire["bars"]
    _check(type(rows) is list and len(rows) <= request.limit)
    records: list[CapitalDailyBar] = []
    for index, entry in enumerate(cast(list[object], rows)):
        _check(type(entry) is dict)
        row = cast(dict[str, object], entry)
        _check(set(row) == {"t", "o", "h", "l", "c", "v", "n", "vw"})
        bar = AlpacaBarRecord(
            expected_sha256,
            page_index,
            index,
            parse_timestamp_ns(cast(str, row["t"])),
            _price(row["o"]),
            _price(row["h"]),
            _price(row["l"]),
            _price(row["c"]),
            _integer(row["v"]),
            _integer(row["n"]),
            _price(row["vw"]),
        )
        records.append(CapitalDailyBar(request.symbol, bar))
    return CapitalDailyPage(
        request,
        expected_sha256,
        page_index,
        requested_page_token,
        cast(str | None, wire["next_page_token"]),
        tuple(records),
    )


def assess_capital_daily_pages(pages: tuple[CapitalDailyPage, ...]) -> AlpacaArchiveAssessment:
    """Verify a supplied single-symbol chain; completeness is pagination only."""
    _check(type(pages) is tuple and len(pages) <= MAX_PAGES)
    previous_token: str | None = None
    previous_stamp: int | None = None
    seen: set[str] = set()
    request_hash: str | None = None
    count = 0
    for index, page in enumerate(pages):
        _check(type(page) is CapitalDailyPage)
        page.__post_init__()
        if request_hash is None:
            request_hash = page.request.request_hash
        _check(page.request.request_hash == request_hash and page.page_index == index)
        _check(page.requested_page_token == previous_token)
        if index:
            _check(previous_token is not None)
        if page.next_page_token is not None:
            _check(page.next_page_token not in seen)
            seen.add(page.next_page_token)
        for record in page.records:
            stamp = record.bar.timestamp_ns
            _check(previous_stamp is None or stamp > previous_stamp)
            previous_stamp = stamp
            count += 1
        previous_token = page.next_page_token
    complete = bool(pages) and previous_token is None
    reasons = ["historical_availability_unverified", "session_and_action_coverage_unverified"]
    if not complete:
        reasons.append("pagination_incomplete")
    if count == 0:
        reasons.append("no_observations")
    return AlpacaArchiveAssessment(count, complete, tuple(reasons))
