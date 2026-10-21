"""Pure declared-profile SEC metadata receipts; native API compatibility is unverified.

Original bytes establish local integrity only. Acceptance text has no inferred
timezone/publication meaning, and a newly received response cannot backfill history.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, cast

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex

MAX_RESPONSE_BYTES = 2_097_152
MAX_RECENT_ROWS = 10_000
MAX_HISTORY_REFERENCES = 100
_MAX_COUNT = 2**63 - 1
_FLAGS = (
    "qualified",
    "source_qualified",
    "strategy_qualified",
    "investment_eligible",
    "trading_enabled",
    "live_authorized",
    "provider_authenticated",
    "publication_verified",
    "history_complete",
    "acceptance_timezone_verified",
    "native_api_compatibility_verified",
)
_ERRORS = (ValueError, TypeError, AttributeError, ArithmeticError, RecursionError)


class SecSubmissionsError(ValueError):
    """Fixed validation error without rejected values, bodies or diagnostics."""

    def __init__(self) -> None:
        super().__init__("sec_submissions_invalid")


def _check(valid: bool) -> None:
    if not valid:
        raise SecSubmissionsError()


def _date(value: object) -> date:
    _check(type(value) is str and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is not None)
    parsed = date.fromisoformat(cast(str, value))
    _check(parsed.isoformat() == value)
    return parsed


def _text(value: object, bound: int, *, empty: bool = False, ascii_only: bool = False) -> str:
    _check(type(value) is str)
    text = cast(str, value)
    _check((empty or bool(text)) and len(text) <= bound)
    _check(all(char.isprintable() for char in text))
    _check(not ascii_only or text.isascii())
    return text


def _cik(value: str | int) -> str:
    if type(value) is int:
        _check(0 < value <= 9_999_999_999)
        return str(value).zfill(10)
    _check(type(value) is str and re.fullmatch(r"[0-9]{1,10}", value) is not None)
    _check(int(cast(str, value)) > 0)
    return cast(str, value).zfill(10)


@dataclass(frozen=True, slots=True, repr=False)
class _Receipt:
    body_sha256: str
    received_at: datetime
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    provider_authenticated: Literal[False] = field(default=False, init=False)
    publication_verified: Literal[False] = field(default=False, init=False)
    history_complete: Literal[False] = field(default=False, init=False)
    acceptance_timezone_verified: Literal[False] = field(default=False, init=False)
    native_api_compatibility_verified: Literal[False] = field(default=False, init=False)
    publication_at: None = field(default=None, init=False)

    def __post_init__(self) -> None:
        try:
            _require_sha256_hex(self.body_sha256, "SEC response")
            require_utc(self.received_at)
            _check(all(getattr(self, name) is False for name in _FLAGS))
            _check(self.publication_at is None)
        except _ERRORS:
            raise SecSubmissionsError() from None

    @property
    def available_at(self) -> datetime:
        return self.received_at


@dataclass(frozen=True, slots=True, repr=False)
class SecSubmissionFiling(_Receipt):
    row_index: int
    accession_number: str
    form: str
    filing_date: date
    report_date_raw: str | None
    acceptance_datetime_raw: str | None

    def __post_init__(self) -> None:
        try:
            _Receipt.__post_init__(self)
            _check(type(self.row_index) is int and 0 <= self.row_index < MAX_RECENT_ROWS)
            _check(type(self.accession_number) is str)
            _check(re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", self.accession_number) is not None)
            _text(self.form, 32, ascii_only=True)
            _check(type(self.filing_date) is date and self.filing_date <= self.received_at.date())
            if self.report_date_raw is not None:
                _check(type(self.report_date_raw) is str)
                if self.report_date_raw != "":
                    _date(self.report_date_raw)
            if self.acceptance_datetime_raw is not None:
                _text(self.acceptance_datetime_raw, 128, empty=True)
        except _ERRORS:
            raise SecSubmissionsError() from None

    @property
    def is_amendment(self) -> bool:
        return self.form.endswith("/A")


@dataclass(frozen=True, slots=True, repr=False)
class SecHistoryReference(_Receipt):
    row_index: int
    name: str
    filing_count: int
    filing_from: date
    filing_to: date

    def __post_init__(self) -> None:
        try:
            _Receipt.__post_init__(self)
            _check(type(self.row_index) is int and 0 <= self.row_index < MAX_HISTORY_REFERENCES)
            name = _text(self.name, 255, ascii_only=True)
            _check(all(33 <= ord(char) <= 126 for char in name))
            _check("/" not in name and "\\" not in name and bool(name.strip(".")))
            _check(type(self.filing_count) is int and 0 <= self.filing_count <= _MAX_COUNT)
            _check(type(self.filing_from) is date and type(self.filing_to) is date)
            _check(self.filing_from <= self.filing_to)
        except _ERRORS:
            raise SecSubmissionsError() from None


def _pairs(values: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in values:
        _check(name not in result)
        result[name] = value
    return result


def _constant(value: str) -> object:
    raise SecSubmissionsError()


def _mapping(value: object, required: set[str]) -> dict[str, object]:
    _check(type(value) is dict)
    result = cast(dict[str, object], value)
    _check(required <= result.keys())
    return result


def _filings(
    recent: dict[str, object],
    body_hash: str,
    received: datetime,
) -> tuple[SecSubmissionFiling, ...]:
    _check({"accessionNumber", "form", "filingDate"} <= recent.keys())
    _check(all(type(column) is list for column in recent.values()))
    size = len(cast(list[object], recent["accessionNumber"]))
    _check(size <= MAX_RECENT_ROWS)
    _check(all(len(cast(list[object], column)) == size for column in recent.values()))
    columns = cast(dict[str, list[object]], recent)
    records = []
    seen: set[str] = set()
    for index in range(size):
        accession = columns["accessionNumber"][index]
        _check(type(accession) is str and accession not in seen)
        seen.add(cast(str, accession))
        records.append(
            SecSubmissionFiling(
                body_hash,
                received,
                index,
                cast(str, accession),
                cast(str, columns["form"][index]),
                _date(columns["filingDate"][index]),
                cast(str | None, columns["reportDate"][index]) if "reportDate" in columns else None,
                cast(str | None, columns["acceptanceDateTime"][index])
                if "acceptanceDateTime" in columns
                else None,
            )
        )
    return tuple(records)


def _references(
    value: object,
    body_hash: str,
    received: datetime,
) -> tuple[SecHistoryReference, ...]:
    _check(type(value) is list and len(cast(list[object], value)) <= MAX_HISTORY_REFERENCES)
    result = []
    seen: set[str] = set()
    for index, item in enumerate(cast(list[object], value)):
        row = _mapping(item, {"name", "filingCount", "filingFrom", "filingTo"})
        reference = SecHistoryReference(
            body_hash,
            received,
            index,
            cast(str, row["name"]),
            cast(int, row["filingCount"]),
            _date(row["filingFrom"]),
            _date(row["filingTo"]),
        )
        _check(reference.name not in seen)
        seen.add(reference.name)
        result.append(reference)
    return tuple(result)


@dataclass(frozen=True, slots=True, repr=False)
class SecSubmissionsObservation(_Receipt):
    original_body: bytes
    requested_cik: str
    reported_cik: str | int = field(init=False)
    normalized_cik: str = field(init=False)
    recent_columns: tuple[str, ...] = field(init=False)
    records: tuple[SecSubmissionFiling, ...] = field(init=False)
    history_references: tuple[SecHistoryReference, ...] | None = field(init=False)

    def __post_init__(self) -> None:
        try:
            _Receipt.__post_init__(self)
            _check(
                type(self.original_body) is bytes
                and 0 < len(self.original_body) <= MAX_RESPONSE_BYTES
            )
            _check(hashlib.sha256(self.original_body).hexdigest() == self.body_sha256)
            _check(type(self.requested_cik) is str)
            _check(re.fullmatch(r"[0-9]{10}", self.requested_cik) is not None)
            _check(_cik(self.requested_cik) == self.requested_cik)
            root = _mapping(
                json.loads(
                    self.original_body.decode("utf-8"),
                    object_pairs_hook=_pairs,
                    parse_float=Decimal,
                    parse_constant=_constant,
                ),
                {"cik", "filings"},
            )
            normalized = _cik(cast(str | int, root["cik"]))
            _check(normalized == self.requested_cik)
            filings = _mapping(root["filings"], {"recent"})
            recent = _mapping(filings["recent"], set())
            records = _filings(recent, self.body_sha256, self.received_at)
            references = (
                _references(filings["files"], self.body_sha256, self.received_at)
                if "files" in filings
                else None
            )
            object.__setattr__(self, "reported_cik", root["cik"])
            object.__setattr__(self, "normalized_cik", normalized)
            object.__setattr__(self, "recent_columns", tuple(recent))
            object.__setattr__(self, "records", records)
            object.__setattr__(self, "history_references", references)
        except _ERRORS:
            raise SecSubmissionsError() from None

    @property
    def source_url(self) -> str:
        return "https://data.sec.gov/submissions/CIK" + self.requested_cik + ".json"


def parse_sec_submissions(
    raw: bytes,
    *,
    requested_cik: str,
    expected_sha256: str,
    received_at: datetime,
) -> SecSubmissionsObservation:
    """Interpret only the declared offline profile; no native compatibility or I/O claim."""
    try:
        return SecSubmissionsObservation(expected_sha256, received_at, raw, requested_cik)
    except _ERRORS:
        raise SecSubmissionsError() from None
