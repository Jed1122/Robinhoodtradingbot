"""Pure declared-profile SEC fact binding; native API compatibility is unverified.

Original receipts establish local integrity and conservative availability only.
Reported dates and acceptance text do not establish publication or historical access.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, cast

from trading_bot.clock import require_utc
from trading_bot.market_data.sec_submissions import (
    _ERRORS,
    SecSubmissionFiling,
    SecSubmissionsObservation,
    _cik,
    _constant,
    _date,
    _mapping,
    _pairs,
    _Receipt,
    _text,
    parse_sec_submissions,
)

MAX_RESPONSE_BYTES = 8_388_608
MAX_CONCEPT_ROWS = 20_000
MAX_TOTAL_ROWS = 50_000
MAX_UNITS = 64
SELECTED_CONCEPTS = ("Assets", "StockholdersEquity", "NetIncomeLoss", "Revenues")


class SecCompanyFactsError(ValueError):
    """Fixed validation error without original bodies or rejected diagnostics."""

    def __init__(self) -> None:
        super().__init__("sec_companyfacts_invalid")


def _check(valid: bool) -> None:
    if not valid:
        raise SecCompanyFactsError()


def _number(value: object) -> Decimal:
    _check(type(value) in (int, Decimal))
    result = Decimal(cast(int | Decimal, value))
    _check(result.is_finite())
    parts = result.as_tuple()
    _check(len(parts.digits) <= 128 and -1000 <= cast(int, parts.exponent) <= 1000)
    return result


def _year(value: object) -> int:
    _check(type(value) is int and 1 <= value <= 9999)
    return cast(int, value)


@dataclass(frozen=True, slots=True, repr=False)
class SecCompanyFact(_Receipt):
    submissions_received_at: datetime
    concept: str
    row_index: int
    value: Decimal
    period_start: date | None
    period_end: date
    accession_number: str
    form: str
    filing_date: date
    fiscal_year: int | None
    fiscal_period: str | None
    frame: str | None
    filing: SecSubmissionFiling | None
    taxonomy: Literal["us-gaap"] = field(default="us-gaap", init=False)
    unit: Literal["USD"] = field(default="USD", init=False)
    binding_status: Literal["matched", "accession_not_in_recent"] = field(init=False)

    def __post_init__(self) -> None:
        try:
            _Receipt.__post_init__(self)
            object.__setattr__(self, "received_at", require_utc(self.received_at))
            object.__setattr__(
                self, "submissions_received_at", require_utc(self.submissions_received_at)
            )
            _check(self.taxonomy == "us-gaap" and self.unit == "USD")
            _check(self.concept in SELECTED_CONCEPTS)
            _check(type(self.row_index) is int and 0 <= self.row_index < MAX_CONCEPT_ROWS)
            _check(type(self.value) is Decimal)
            _number(self.value)
            _check(type(self.period_end) is date)
            if self.period_start is not None:
                _check(type(self.period_start) is date and self.period_start <= self.period_end)
            # Reuse the exact submissions accession, form and reported-date rules.
            # This validation object is never exposed as evidence of a matching filing.
            SecSubmissionFiling(
                self.body_sha256,
                self.received_at,
                0,
                self.accession_number,
                self.form,
                self.filing_date,
                None,
                None,
            )
            if self.fiscal_year is not None:
                _year(self.fiscal_year)
            if self.fiscal_period is not None:
                _text(self.fiscal_period, 32, ascii_only=True)
            if self.frame is not None:
                _text(self.frame, 128, ascii_only=True)
            if self.filing is not None:
                _check(type(self.filing) is SecSubmissionFiling)
                self.filing.__post_init__()
                _check(self.filing.received_at == self.submissions_received_at)
                _check(self.filing.accession_number == self.accession_number)
                _check(
                    self.filing.form == self.form and self.filing.filing_date == self.filing_date
                )
            object.__setattr__(
                self,
                "binding_status",
                "matched" if self.filing is not None else "accession_not_in_recent",
            )
        except _ERRORS:
            raise SecCompanyFactsError() from None

    @property
    def available_at(self) -> datetime:
        return max(self.received_at, self.submissions_received_at)


def _row(
    value: object,
    *,
    concept: str,
    index: int,
    body_hash: str,
    received: datetime,
    submissions: SecSubmissionsObservation,
    filings: dict[str, SecSubmissionFiling],
) -> SecCompanyFact:
    row = _mapping(value, {"end", "val", "accn", "form", "filed"})
    accession = _text(row["accn"], 20, ascii_only=True)
    return SecCompanyFact(
        body_hash,
        received,
        submissions.received_at,
        concept,
        index,
        _number(row["val"]),
        _date(row["start"]) if "start" in row else None,
        _date(row["end"]),
        accession,
        _text(row["form"], 32, ascii_only=True),
        _date(row["filed"]),
        _year(row["fy"]) if "fy" in row else None,
        _text(row["fp"], 32, ascii_only=True) if "fp" in row else None,
        _text(row["frame"], 128, ascii_only=True) if "frame" in row else None,
        filings.get(accession),
    )


def _selected_units(
    facts: dict[str, object],
) -> tuple[dict[str, dict[str, object]], tuple[str, ...], tuple[str, ...]]:
    taxonomy = _mapping(facts["us-gaap"], set()) if "us-gaap" in facts else {}
    selected: dict[str, dict[str, object]] = {}
    missing: list[str] = []
    missing_usd: list[str] = []
    total = 0
    for concept in SELECTED_CONCEPTS:
        if concept not in taxonomy:
            missing.append(concept)
            continue
        units = _mapping(_mapping(taxonomy[concept], {"units"})["units"], set())
        _check(len(units) <= MAX_UNITS)
        for unit in units:
            _text(unit, 128, ascii_only=True)
        selected[concept] = units
        if "USD" not in units:
            missing_usd.append(concept)
            continue
        rows = units["USD"]
        _check(type(rows) is list and len(cast(list[object], rows)) <= MAX_CONCEPT_ROWS)
        total += len(cast(list[object], rows))
        _check(total <= MAX_TOTAL_ROWS)
    return selected, tuple(missing), tuple(missing_usd)


@dataclass(frozen=True, slots=True, repr=False)
class SecCompanyFactsObservation(_Receipt):
    original_body: bytes
    requested_cik: str
    submissions: SecSubmissionsObservation
    reported_cik: str | int = field(init=False)
    normalized_cik: str = field(init=False)
    selected_concepts: tuple[str, ...] = field(init=False)
    missing_concepts: tuple[str, ...] = field(init=False)
    concepts_missing_usd: tuple[str, ...] = field(init=False)
    non_usd_units: tuple[tuple[str, tuple[str, ...]], ...] = field(init=False)
    records: tuple[SecCompanyFact, ...] = field(init=False)

    def __post_init__(self) -> None:
        try:
            _Receipt.__post_init__(self)
            object.__setattr__(self, "received_at", require_utc(self.received_at))
            _check(
                type(self.original_body) is bytes
                and 0 < len(self.original_body) <= MAX_RESPONSE_BYTES
            )
            _check(hashlib.sha256(self.original_body).hexdigest() == self.body_sha256)
            _check(type(self.requested_cik) is str and len(self.requested_cik) == 10)
            _check(_cik(self.requested_cik) == self.requested_cik)
            _check(type(self.submissions) is SecSubmissionsObservation)
            submissions = parse_sec_submissions(
                self.submissions.original_body,
                requested_cik=self.submissions.requested_cik,
                expected_sha256=self.submissions.body_sha256,
                received_at=self.submissions.received_at,
            )
            _check(submissions.normalized_cik == self.requested_cik)
            root = _mapping(
                json.loads(
                    self.original_body.decode("utf-8"),
                    object_pairs_hook=_pairs,
                    parse_float=Decimal,
                    parse_constant=_constant,
                ),
                {"cik", "facts"},
            )
            normalized = _cik(cast(str | int, root["cik"]))
            _check(normalized == self.requested_cik)
            selected, missing, missing_usd = _selected_units(_mapping(root["facts"], set()))
            filings = {row.accession_number: row for row in submissions.records}
            records = tuple(
                _row(
                    value,
                    concept=concept,
                    index=index,
                    body_hash=self.body_sha256,
                    received=self.received_at,
                    submissions=submissions,
                    filings=filings,
                )
                for concept, units in selected.items()
                for index, value in enumerate(cast(list[object], units.get("USD", [])))
            )
            object.__setattr__(self, "submissions", submissions)
            object.__setattr__(self, "reported_cik", root["cik"])
            object.__setattr__(self, "normalized_cik", normalized)
            object.__setattr__(self, "selected_concepts", SELECTED_CONCEPTS)
            object.__setattr__(self, "missing_concepts", missing)
            object.__setattr__(self, "concepts_missing_usd", missing_usd)
            object.__setattr__(
                self,
                "non_usd_units",
                tuple(
                    (concept, tuple(unit for unit in units if unit != "USD"))
                    for concept, units in selected.items()
                ),
            )
            object.__setattr__(self, "records", records)
        except _ERRORS:
            raise SecCompanyFactsError() from None

    @property
    def available_at(self) -> datetime:
        return max(self.received_at, self.submissions.received_at)

    @property
    def source_url(self) -> str:
        return "https://data.sec.gov/api/xbrl/companyfacts/CIK" + self.requested_cik + ".json"


def parse_sec_companyfacts_with_filings(
    raw: bytes,
    *,
    requested_cik: str,
    expected_sha256: str,
    received_at: datetime,
    submissions: SecSubmissionsObservation,
) -> SecCompanyFactsObservation:
    """Bind declared-profile facts to original submissions receipts without I/O."""
    try:
        return SecCompanyFactsObservation(
            expected_sha256, received_at, raw, requested_cik, submissions
        )
    except _ERRORS:
        raise SecCompanyFactsError() from None
