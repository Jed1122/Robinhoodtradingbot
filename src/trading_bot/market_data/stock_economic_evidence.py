"""Bounded observations of MCP-decoded CSV, with no completeness or trade authority.

Security descriptions are retrospective dated observations, not contemporaneous
receipts. Dividend rows are native cash events; adjustment columns are deliberately
not interpreted. A local hash binds bytes and does not authenticate their origin.
"""

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
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

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal

_MAX_BYTES = 1_048_576
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
_IDENTITY_HEADERS = frozenset(
    {
        "ticker",
        "name",
        "market",
        "locale",
        "primary_exchange",
        "type",
        "active",
        "currency_name",
        "cik",
        "composite_figi",
        "share_class_figi",
        "list_date",
    }
)
_DIVIDEND_HEADERS = frozenset(
    {
        "id",
        "ticker",
        "record_date",
        "pay_date",
        "declaration_date",
        "ex_dividend_date",
        "frequency",
        "cash_amount",
        "currency",
        "distribution_type",
    }
)
_DISTRIBUTION_TYPES = frozenset({"recurring", "special", "supplemental", "irregular", "unknown"})
_LIMITATIONS = (
    "mcp_decoded_csv_not_original_http_wire",
    "local_hash_does_not_authenticate_source_or_request",
    "no_http_status_or_pagination_proof",
    "no_api_wide_or_corporate_action_completeness_assertion",
    "retrospective_observation_not_historical_receipt",
    "extra_native_columns_retained_by_original_bytes_hash_only",
    "not_investment_eligibility_or_live_authorization",
)


class StockEconomicEvidenceError(ValueError):
    """The source observation or accrual is outside this narrow contract."""

    def __init__(self) -> None:
        super().__init__("stock_economic_evidence_invalid")


def _check(condition: bool) -> None:
    if not condition:
        raise StockEconomicEvidenceError()


def _symbol(value: str) -> None:
    _check(
        type(value) is str and re.fullmatch(r"[A-Z0-9][A-Z0-9.$+^=/@_-]{0,31}", value) is not None
    )


def _day(value: date) -> None:
    _check(type(value) is date)


def _optional_text(value: str) -> str | None:
    _check(type(value) is str and len(value) <= 4096 and value == value.strip())
    return value or None


def _date_text(value: str) -> date | None:
    if value == "":
        return None
    _check(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is not None)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise StockEconomicEvidenceError() from None


def _scope(value: "_Observation") -> None:
    _check(value.qualified is value.investment_eligible is value.live_authorized is False)
    _check(value.limitations == _LIMITATIONS)


def _binding(sha256: str, received_at: datetime) -> None:
    try:
        _require_sha256_hex(sha256, "original_csv_sha256")
        require_utc(received_at)
    except (ValueError, TypeError, AttributeError):
        raise StockEconomicEvidenceError() from None


def _strict_csv_grammar(text: str) -> None:
    """csv.strict alone accepts quotes embedded in unquoted cells; reject those."""
    state = "start"
    index = 0
    while index < len(text):
        char = text[index]
        if state == "quoted":
            if char == '"':
                if index + 1 < len(text) and text[index + 1] == '"':
                    index += 1
                else:
                    state = "closed"
        elif char in "\r\n":
            if char == "\r":
                _check(index + 1 < len(text) and text[index + 1] == "\n")
                index += 1
            state = "start"
        elif char == ",":
            state = "start"
        elif char == '"':
            _check(state == "start")
            state = "quoted"
        else:
            _check(state != "closed")
            state = "plain"
        index += 1
    _check(state != "quoted")


def _rows(
    original_csv: bytes, expected_sha256: str, required: frozenset[str]
) -> tuple[dict[str, str], ...]:
    try:
        _check(type(original_csv) is bytes and 0 < len(original_csv) <= _MAX_BYTES)
        _require_sha256_hex(expected_sha256, "expected_sha256")
        _check(hashlib.sha256(original_csv).hexdigest() == expected_sha256)
        text = original_csv.decode("utf-8", errors="strict")
        _check("\x00" not in text)
        _strict_csv_grammar(text)
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
        _check(bool(rows))
        headers = rows[0]
        _check(0 < len(headers) <= 256)
        _check(all(bool(h) and h == h.strip() for h in headers))
        _check(len(set(headers)) == len(headers) and required <= set(headers))
        _check(all(len(row) == len(headers) for row in rows[1:]))
        return tuple(dict(zip(headers, row, strict=True)) for row in rows[1:])
    except (ValueError, TypeError, UnicodeError, csv.Error, AttributeError):
        raise StockEconomicEvidenceError() from None


@dataclass(frozen=True, slots=True)
class _Observation:
    qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)


@dataclass(frozen=True, slots=True)
class DatedStockIdentity(_Observation):
    symbol: str
    name: str
    market: Literal["stocks"]
    locale: Literal["us"]
    active: bool
    currency_name: str
    currency: Literal["USD"]
    cik: str | None
    composite_figi: str | None
    share_class_figi: str | None
    security_type: str | None
    primary_exchange: str | None
    list_date: date | None
    requested_date: date
    received_at: datetime
    original_csv_sha256: str

    def __post_init__(self) -> None:
        _scope(self)
        _binding(self.original_csv_sha256, self.received_at)
        _symbol(self.symbol)
        _day(self.requested_date)
        _check(self.requested_date <= self.received_at.date())
        _check(type(self.name) is str and bool(self.name.strip()) and len(self.name) <= 4096)
        _check(self.market == "stocks" and self.locale == "us" and type(self.active) is bool)
        _check(self.currency_name in {"usd", "USD"} and self.currency == "USD")
        if self.cik is not None:
            _check(type(self.cik) is str and re.fullmatch(r"[0-9]{1,10}", self.cik) is not None)
        for figi in (self.composite_figi, self.share_class_figi):
            if figi is not None:
                _check(type(figi) is str and re.fullmatch(r"[A-Z0-9]{12}", figi) is not None)
        for text in (self.security_type, self.primary_exchange):
            if text is not None:
                _check(_optional_text(text) is not None)
        if self.list_date is not None:
            _day(self.list_date)
            _check(self.list_date <= self.requested_date)


@dataclass(frozen=True, slots=True)
class StockCashDividendEvent(_Observation):
    id: str
    ticker: str
    cash_amount: Decimal
    currency: Literal["USD"]
    ex_dividend_date: date
    pay_date: date | None
    record_date: date | None
    declaration_date: date | None
    distribution_type: str | None
    frequency: int | None
    received_at: datetime
    source_csv_sha256: str

    def __post_init__(self) -> None:
        try:
            _scope(self)
            _binding(self.source_csv_sha256, self.received_at)
            _check(type(self.id) is str and _optional_text(self.id) is not None)
            _symbol(self.ticker)
            require_bounded_decimal(self.cash_amount, "cash_amount", positive=True)
            _check(self.currency == "USD")
            _day(self.ex_dividend_date)
            for optional in (self.pay_date, self.record_date, self.declaration_date):
                if optional is not None:
                    _day(optional)
            if self.pay_date is not None:
                _check(self.pay_date >= self.ex_dividend_date)
            if self.declaration_date is not None:
                _check(self.declaration_date <= self.ex_dividend_date)
                _check(self.declaration_date <= self.received_at.date())
            if self.frequency is not None:
                _check(type(self.frequency) is int and 0 <= self.frequency <= 999_999)
            _check(self.distribution_type is None or self.distribution_type in _DISTRIBUTION_TYPES)
        except (ValueError, TypeError, AttributeError, DecimalException):
            raise StockEconomicEvidenceError() from None

    @property
    def symbol(self) -> str:
        return self.ticker

    @property
    def ex_date(self) -> date:
        return self.ex_dividend_date


@dataclass(frozen=True, slots=True)
class StockCashDividendEvidence(_Observation):
    symbol: str
    ex_start: date
    ex_end: date
    received_at: datetime
    original_csv_sha256: str
    events: tuple[StockCashDividendEvent, ...]

    def __post_init__(self) -> None:
        _scope(self)
        _binding(self.original_csv_sha256, self.received_at)
        _symbol(self.symbol)
        _day(self.ex_start)
        _day(self.ex_end)
        _check(self.ex_start <= self.ex_end and type(self.events) is tuple)
        ids: set[str] = set()
        economics: set[tuple[str, date, Decimal, date | None]] = set()
        for event in self.events:
            _check(type(event) is StockCashDividendEvent)
            event.__post_init__()
            _check(event.symbol == self.symbol and self.ex_start <= event.ex_date <= self.ex_end)
            _check(event.source_csv_sha256 == self.original_csv_sha256)
            _check(event.received_at == self.received_at)
            economic = (event.symbol, event.ex_date, event.cash_amount, event.pay_date)
            _check(event.id not in ids and economic not in economics)
            ids.add(event.id)
            economics.add(economic)


@dataclass(frozen=True, slots=True)
class CashDividendAccrual(_Observation):
    event_id: str
    symbol: str
    currency: Literal["USD"]
    ex_date: date
    pay_date: date | None
    held_at: date
    as_of: date
    shares_before_ex: Decimal
    accrued_amount: Decimal
    receivable: Decimal
    cash_available: Decimal

    def __post_init__(self) -> None:
        try:
            _scope(self)
            _check(type(self.event_id) is str and _optional_text(self.event_id) is not None)
            _symbol(self.symbol)
            _check(self.currency == "USD")
            for day in (self.ex_date, self.held_at, self.as_of):
                _day(day)
            _check(self.held_at <= self.as_of)
            if self.pay_date is not None:
                _day(self.pay_date)
                _check(self.pay_date >= self.ex_date)
            for amount in (
                self.shares_before_ex,
                self.accrued_amount,
                self.receivable,
                self.cash_available,
            ):
                require_bounded_decimal(amount, "accrual_amount", nonnegative=True)
            if not (self.held_at < self.ex_date <= self.as_of) or self.shares_before_ex == 0:
                _check(self.accrued_amount == 0)
            paid = self.pay_date is not None and self.pay_date <= self.as_of
            _check(self.receivable == (Decimal(0) if paid else self.accrued_amount))
            _check(self.cash_available == (self.accrued_amount if paid else Decimal(0)))
        except (ValueError, TypeError, AttributeError, DecimalException):
            raise StockEconomicEvidenceError() from None


def parse_dated_stock_identity(
    original_csv: bytes,
    *,
    expected_sha256: str,
    symbol: str,
    requested_date: date,
    received_at: datetime,
) -> DatedStockIdentity:
    """Admit one USD security observation while discarding financial attributes."""
    rows = _rows(original_csv, expected_sha256, _IDENTITY_HEADERS)
    _check(len(rows) == 1)
    row = rows[0]
    _check(row["ticker"] == symbol and row["active"] in {"true", "false"})
    _check(row["market"] == "stocks" and row["locale"] == "us")
    return DatedStockIdentity(
        symbol=symbol,
        name=row["name"],
        market="stocks",
        locale="us",
        active=row["active"] == "true",
        currency_name=row["currency_name"],
        currency="USD",
        cik=_optional_text(row["cik"]),
        composite_figi=_optional_text(row["composite_figi"]),
        share_class_figi=_optional_text(row["share_class_figi"]),
        security_type=_optional_text(row["type"]),
        primary_exchange=_optional_text(row["primary_exchange"]),
        list_date=_date_text(row["list_date"]),
        requested_date=requested_date,
        received_at=received_at,
        original_csv_sha256=expected_sha256,
    )


def _amount(text: str) -> Decimal:
    try:
        _check(
            len(text) <= 512
            and re.fullmatch(
                r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?",
                text,
            )
            is not None
        )
        return require_bounded_decimal(Decimal(text), "cash_amount", positive=True)
    except (ValueError, TypeError, DecimalException):
        raise StockEconomicEvidenceError() from None


def parse_cash_dividends(
    original_csv: bytes,
    *,
    expected_sha256: str,
    symbol: str,
    ex_start: date,
    ex_end: date,
    received_at: datetime,
) -> StockCashDividendEvidence:
    """Retain native cash events, without inferring complete provider pagination."""
    return parse_cash_dividend_panel(
        original_csv,
        expected_sha256=expected_sha256,
        symbols=(symbol,),
        ex_start=ex_start,
        ex_end=ex_end,
        received_at=received_at,
    )[0]


def _cash_event_from_row(
    row: dict[str, str], *, received_at: datetime, expected_sha256: str
) -> StockCashDividendEvent:
    ex_date = _date_text(row["ex_dividend_date"])
    _check(row["currency"] == "USD")
    frequency_text = row["frequency"]
    _check(frequency_text == "" or re.fullmatch(r"[0-9]{1,6}", frequency_text) is not None)
    if ex_date is None:
        raise StockEconomicEvidenceError()
    return StockCashDividendEvent(
        id=row["id"],
        ticker=row["ticker"],
        cash_amount=_amount(row["cash_amount"]),
        currency="USD",
        ex_dividend_date=ex_date,
        pay_date=_date_text(row["pay_date"]),
        record_date=_date_text(row["record_date"]),
        declaration_date=_date_text(row["declaration_date"]),
        distribution_type=_optional_text(row["distribution_type"]),
        frequency=int(frequency_text) if frequency_text else None,
        received_at=received_at,
        source_csv_sha256=expected_sha256,
    )


def parse_cash_dividend_panel(
    original_csv: bytes,
    *,
    expected_sha256: str,
    symbols: tuple[str, ...],
    ex_start: date,
    ex_end: date,
    received_at: datetime,
) -> tuple[StockCashDividendEvidence, ...]:
    """Validate every original panel row before returning requested-symbol views.

    Each derived view and event binds the entire original CSV hash, never a
    filtered CSV. Missing requested-symbol rows remain empty observations, without
    asserting absence of distributions or terminal provider pagination.
    """
    _check(type(symbols) is tuple and 1 <= len(symbols) <= 32)
    for symbol in symbols:
        _symbol(symbol)
    _check(len(set(symbols)) == len(symbols))
    _day(ex_start)
    _day(ex_end)
    _check(ex_start <= ex_end)
    _binding(expected_sha256, received_at)
    rows = _rows(original_csv, expected_sha256, _DIVIDEND_HEADERS)
    events = []
    ids: set[str] = set()
    economics: set[tuple[str, date, Decimal, date | None]] = set()
    for row in rows:
        event = _cash_event_from_row(row, received_at=received_at, expected_sha256=expected_sha256)
        _check(event.symbol in symbols and ex_start <= event.ex_date <= ex_end)
        economic = (event.symbol, event.ex_date, event.cash_amount, event.pay_date)
        _check(event.id not in ids and economic not in economics)
        ids.add(event.id)
        economics.add(economic)
        events.append(event)

    # Partition only after every native row, ID and economic key has passed.
    buckets: dict[str, list[StockCashDividendEvent]] = {symbol: [] for symbol in symbols}
    for event in events:
        buckets[event.symbol].append(event)
    return tuple(
        StockCashDividendEvidence(
            symbol=symbol,
            ex_start=ex_start,
            ex_end=ex_end,
            received_at=received_at,
            original_csv_sha256=expected_sha256,
            events=tuple(buckets[symbol]),
        )
        for symbol in symbols
    )


def dividend_entitlement(
    event: StockCashDividendEvent, *, shares_before_ex: Decimal, held_at: date, as_of: date
) -> CashDividendAccrual:
    """Accrue verified prior-ex holdings; a receivable never supplies early cash.

    The caller must establish that the supplied holdings persisted through the
    pre-ex entitlement boundary. ``held_at`` is their verified holding date;
    same-day and later acquisitions do not earn the distribution.
    """
    try:
        _check(type(event) is StockCashDividendEvent)
        event.__post_init__()
        require_bounded_decimal(shares_before_ex, "shares_before_ex", nonnegative=True)
        _day(held_at)
        _day(as_of)
        _check(held_at <= as_of)
        amount = Decimal(0)
        if held_at < event.ex_date <= as_of:
            with localcontext(_CONTEXT):
                amount = shares_before_ex * event.cash_amount
        paid = event.pay_date is not None and event.pay_date <= as_of
        return CashDividendAccrual(
            event_id=event.id,
            symbol=event.symbol,
            currency=event.currency,
            ex_date=event.ex_date,
            pay_date=event.pay_date,
            held_at=held_at,
            as_of=as_of,
            shares_before_ex=shares_before_ex,
            accrued_amount=amount,
            receivable=Decimal(0) if paid else amount,
            cash_available=amount if paid else Decimal(0),
        )
    except (ValueError, TypeError, AttributeError, DecimalException):
        raise StockEconomicEvidenceError() from None
