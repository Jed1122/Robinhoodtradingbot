"""Lossless SPY native REST syntax, not historical availability or source acceptance.

Raw SIP requests and today's receipts cannot establish original publication time.
Daily timestamps are aggregation starts, not session closes. Native quote sizes
retain their units; response order is not a proven exchange sequence. This module
has no I/O, credentials, broker capabilities or qualified-dataset factory.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal, cast

from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.bundle_codec import _object, _parse_integer, _reject_number
from trading_bot.market_data.recording import content_hash

MAX_PAGE_BYTES = 1_048_576
MAX_PAGES = 128
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_STAMP = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})\Z")


class AlpacaNativeError(ValueError):
    def __init__(self) -> None:
        super().__init__("alpaca_native_invalid")


def _check(value: bool) -> None:
    if not value:
        raise AlpacaNativeError()


def _integer(value: object, maximum: int = 2**63 - 1) -> int:
    _check(type(value) is int and 0 <= value <= maximum)
    return cast(int, value)


def parse_timestamp_ns(value: str) -> int:
    """RFC3339 without truncation through floats or datetime microseconds."""
    try:
        _check(type(value) is str)
        match = _STAMP.fullmatch(value)
        _check(match is not None)
        if match is None:
            raise AlpacaNativeError()
        offset = match[3]
        _check(offset != "-00:00")  # RFC3339 unknown local offset is not verified UTC.
        if offset != "Z":
            _check(int(offset[1:3]) <= 23 and int(offset[4:6]) <= 59)
        instant = datetime.fromisoformat(match[1] + match[3]).astimezone(UTC)
        delta = instant - _EPOCH
        return _integer(
            (delta.days * 86400 + delta.seconds) * 10**9 + int((match[2] or "").ljust(9, "0"))
        )
    except (ValueError, TypeError, ArithmeticError):
        raise AlpacaNativeError() from None


def format_timestamp_ns(value: int) -> str:
    _integer(value)
    instant = _EPOCH + timedelta(seconds=value // 10**9)
    return instant.strftime("%Y-%m-%dT%H:%M:%S") + f".{value % 10**9:09d}Z"


def _token(value: str | None) -> None:
    _check(
        value is None
        or (
            type(value) is str
            and 0 < len(value) <= 4096
            and all(33 <= ord(c) <= 126 for c in value)
        )
    )


@dataclass(frozen=True, slots=True)
class AlpacaStockRequest:
    kind: Literal["bars", "quotes"]
    start_ns: int
    end_ns: int
    limit: int = 1000

    def __post_init__(self) -> None:
        _check(type(self.kind) is str and self.kind in ("bars", "quotes"))
        _integer(self.start_ns)
        _integer(self.end_ns)
        _check(self.start_ns < self.end_ns)
        _check(_integer(self.limit, 10000) >= 1)

    @property
    def path(self) -> str:
        return "/v2/stocks/SPY/" + self.kind

    @property
    def request_hash(self) -> str:
        return content_hash({"schema": "alpaca-spy-native-request-v1", "request": self})

    def query(self, page_token: str | None = None) -> tuple[tuple[str, str], ...]:
        self.__post_init__()
        _token(page_token)
        query = [
            ("start", format_timestamp_ns(self.start_ns)),
            ("end", format_timestamp_ns(self.end_ns - 1)),
            ("feed", "sip"),
            ("currency", "USD"),
            ("asof", "-"),
            ("sort", "asc"),
            ("limit", str(self.limit)),
        ]
        if self.kind == "bars":
            query.extend((("timeframe", "1Day"), ("adjustment", "raw")))
        if page_token is not None:
            query.append(("page_token", page_token))
        return tuple(query)


@dataclass(frozen=True, slots=True, repr=False)
class _NativeRecord:
    body_sha256: str
    page_index: int
    row_index: int
    timestamp_ns: int
    publication_at_ns: None = field(default=None, init=False)

    def __post_init__(self) -> None:
        _require_sha256_hex(self.body_sha256, "body")
        _integer(self.page_index, MAX_PAGES - 1)
        _integer(self.row_index, 9999)
        _integer(self.timestamp_ns)
        _check(self.publication_at_ns is None)

    @property
    def record_hash(self) -> str:
        return content_hash({"schema": "alpaca-native-record-v1", "record": self})


@dataclass(frozen=True, slots=True, repr=False)
class AlpacaBarRecord(_NativeRecord):
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    trade_count: int
    vwap: Decimal

    def __post_init__(self) -> None:
        _NativeRecord.__post_init__(self)
        for value in (self.open, self.high, self.low, self.close, self.vwap):
            require_bounded_decimal(value, "native bar", nonnegative=True)
        _check(self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high)
        _integer(self.volume)
        _integer(self.trade_count)


@dataclass(frozen=True, slots=True, repr=False)
class AlpacaQuoteRecord(_NativeRecord):
    bid: Decimal
    ask: Decimal
    bid_size: int
    ask_size: int
    bid_exchange: str
    ask_exchange: str
    conditions: tuple[str, ...]
    tape: str
    executable: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _NativeRecord.__post_init__(self)
        for value in (self.bid, self.ask):
            require_bounded_decimal(value, "native quote", nonnegative=True)
        for size in (self.bid_size, self.ask_size):
            _integer(size, 2**32 - 1)
        _check(type(self.conditions) is tuple and len(self.conditions) <= 32)
        for code in (self.bid_exchange, self.ask_exchange, *self.conditions):
            _check(
                type(code) is str and 0 < len(code) <= 16 and code.isascii() and code.isprintable()
            )
        _check(type(self.tape) is str and self.tape in ("A", "B", "C", "N", "O"))
        _check(self.executable is False)

    @property
    def size_unit(self) -> Literal["round_lots", "transition_unverified", "shares"]:
        # Official notice supplies a date, not an exact intraday cutover. Keep
        # the whole UTC/NY transition-date union unnormalized. No x100 assumption.
        if self.timestamp_ns < 1762128000000000000:  # 2025-11-03 00:00Z
            return "round_lots"
        if self.timestamp_ns < 1762232400000000000:  # 2025-11-04 05:00Z
            return "transition_unverified"
        return "shares"

    @property
    def observation_reasons(self) -> tuple[str, ...]:
        reasons = ["historical_availability_unverified", "size_conversion_unverified"]
        if self.bid == 0:
            reasons.append("inactive_bid")
        if self.ask == 0:
            reasons.append("inactive_ask")
        if self.bid > 0 and self.ask > 0:
            if self.bid > self.ask:
                reasons.append("crossed_quote")
            elif self.bid == self.ask:
                reasons.append("locked_quote")
        if len(self.conditions) not in (1, 2):
            reasons.append("condition_interpretation_unverified")
        return tuple(reasons)


type NativeRecord = AlpacaBarRecord | AlpacaQuoteRecord


@dataclass(frozen=True, slots=True, repr=False)
class AlpacaNativePage:
    request: AlpacaStockRequest
    body_sha256: str
    page_index: int
    requested_page_token: str | None
    next_page_token: str | None
    records: tuple[NativeRecord, ...]
    source_qualified: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _check(type(self.request) is AlpacaStockRequest)
        replace(self.request)
        _require_sha256_hex(self.body_sha256, "body")
        _integer(self.page_index, MAX_PAGES - 1)
        _token(self.requested_page_token)
        _token(self.next_page_token)
        _check(type(self.records) is tuple and len(self.records) <= self.request.limit)
        previous = None
        for index, record in enumerate(self.records):
            _check(
                type(record)
                is (AlpacaBarRecord if self.request.kind == "bars" else AlpacaQuoteRecord)
            )
            record.__post_init__()
            _check(
                record.body_sha256 == self.body_sha256
                and record.page_index == self.page_index
                and record.row_index == index
            )
            _check(self.request.start_ns <= record.timestamp_ns < self.request.end_ns)
            if previous is not None:
                _check(
                    record.timestamp_ns > previous
                    if self.request.kind == "bars"
                    else record.timestamp_ns >= previous
                )
            previous = record.timestamp_ns
        _check(self.source_qualified is False and self.evidence_promotable is False)


@dataclass(frozen=True, slots=True)
class AlpacaArchiveAssessment:
    record_count: int
    pagination_complete: bool
    reasons: tuple[str, ...]
    source_qualified: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)


def _native_json(body: bytes) -> dict[str, object]:
    _check(type(body) is bytes and 0 < len(body) <= MAX_PAGE_BYTES)
    result = json.loads(
        body,
        object_pairs_hook=_object,
        parse_int=_parse_integer,
        parse_float=Decimal,
        parse_constant=_reject_number,
    )
    _check(type(result) is dict)
    pending = [(result, 0)]
    while pending:
        item, depth = pending.pop()
        _check(depth <= 8)
        if type(item) is dict:
            pending.extend((value, depth + 1) for value in item.values())
        elif type(item) is list:
            pending.extend((value, depth + 1) for value in item)
    return cast(dict[str, object], result)


def _price(value: object) -> Decimal:
    _check(type(value) in (int, Decimal))
    return require_bounded_decimal(
        Decimal(cast(int | Decimal, value)), "native price", nonnegative=True
    )


def parse_alpaca_page(
    body: bytes,
    *,
    request: AlpacaStockRequest,
    expected_sha256: str,
    page_index: int = 0,
    requested_page_token: str | None = None,
) -> AlpacaNativePage:
    """Native syntax/integrity only. Never turns market timestamps into availability."""
    try:
        _check(type(request) is AlpacaStockRequest)
        replace(request)
        _require_sha256_hex(expected_sha256, "expected body")
        _check(type(body) is bytes and hashlib.sha256(body).hexdigest() == expected_sha256)
        wire = _native_json(body)
        required = {"symbol", request.kind, "next_page_token"}
        _check(required <= set(wire) <= required | {"currency"})
        _check(wire["symbol"] == "SPY" and wire.get("currency", "USD") == "USD")
        rows = wire[request.kind]
        _check(type(rows) is list and len(rows) <= request.limit)
        records: list[NativeRecord] = []
        for index, entry in enumerate(cast(list[object], rows)):
            _check(type(entry) is dict)
            row = cast(dict[str, object], entry)
            keys = (
                {"t", "o", "h", "l", "c", "v", "n", "vw"}
                if request.kind == "bars"
                else {"t", "bp", "ap", "bs", "as", "bx", "ax", "c", "z"}
            )
            _check(set(row) == keys)
            stamp = parse_timestamp_ns(cast(str, row["t"]))
            if request.kind == "bars":
                records.append(
                    AlpacaBarRecord(
                        expected_sha256,
                        page_index,
                        index,
                        stamp,
                        _price(row["o"]),
                        _price(row["h"]),
                        _price(row["l"]),
                        _price(row["c"]),
                        _integer(row["v"]),
                        _integer(row["n"]),
                        _price(row["vw"]),
                    )
                )
            else:
                _check(type(row["c"]) is list)
                records.append(
                    AlpacaQuoteRecord(
                        expected_sha256,
                        page_index,
                        index,
                        stamp,
                        _price(row["bp"]),
                        _price(row["ap"]),
                        _integer(row["bs"], 2**32 - 1),
                        _integer(row["as"], 2**32 - 1),
                        cast(str, row["bx"]),
                        cast(str, row["ax"]),
                        tuple(cast(list[str], row["c"])),
                        cast(str, row["z"]),
                    )
                )
        return AlpacaNativePage(
            request,
            expected_sha256,
            page_index,
            requested_page_token,
            cast(str | None, wire["next_page_token"]),
            tuple(records),
        )
    except (ValueError, TypeError, ArithmeticError, RecursionError, AttributeError):
        raise AlpacaNativeError() from None


def validate_alpaca_pages(
    request: AlpacaStockRequest, pages: tuple[AlpacaNativePage, ...]
) -> AlpacaArchiveAssessment:
    """Complete transport does not establish a complete or qualified market history."""
    try:
        _check(type(request) is AlpacaStockRequest)
        replace(request)
        _check(type(pages) is tuple and 0 < len(pages) <= MAX_PAGES)
        token = None
        tokens: set[str] = set()
        previous = None
        count = 0
        for index, page in enumerate(pages):
            _check(type(page) is AlpacaNativePage)
            page.__post_init__()
            _check(page.request == request and page.page_index == index)
            _check(page.requested_page_token == token and (index == 0 or token is not None))
            for row in page.records:
                if previous is not None:
                    _check(
                        row.timestamp_ns > previous
                        if request.kind == "bars"
                        else row.timestamp_ns >= previous
                    )
                previous = row.timestamp_ns
            count += len(page.records)
            token = page.next_page_token
            if token is not None:
                _check(token not in tokens)
                tokens.add(token)
        reasons = [
            "historical_availability_unverified",
            "source_coverage_unverified",
            "corporate_actions_unverified",
            "fractional_terms_unverified",
            "source_rights_unverified",
        ]
        if token is not None:
            reasons.append("pagination_incomplete")
        if not count:
            reasons.append("source_coverage_empty")
        return AlpacaArchiveAssessment(count, token is None, tuple(reasons))
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise AlpacaNativeError() from None
