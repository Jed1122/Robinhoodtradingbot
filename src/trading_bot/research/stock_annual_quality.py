"""AXP-only annual measurements from original filing contexts, never trade authority.

This explicit as-reported financing method retains native lease scope and counts
current maturities inside LongTermDebt once. It is not a universal debt mapping.
Collection receipts remain current; the filing-date proxy is retrospective.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
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
from trading_bot.market_data.stock_events import StockEventReceipt, StockFiling
from trading_bot.market_data.stock_filing_facts import StockFilingFact, StockFilingFacts

_METHOD = "axp-annual-as-reported-financing-to-reported-equity-v1"
_LIMITATIONS = (
    "retrospective_original_filing_reconstruction_not_historical_receipt",
    "filing_date_plus_two_utc_calendar_days_is_availability_proxy_not_publication",
    "source_hashes_are_caller_declared_not_authenticated_http_wire",
    "AXP_as_reported_financing_includes_native_embedded_lease_scope",
    "current_maturities_counted_once_and_deposits_separate",
    "reported_equity_ROE_not_automatically_common_share_or_issuer_ROE",
    "annual_measurements_not_strategy_source_or_investment_qualification",
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


class AnnualQualityError(ValueError):
    """Malformed or tampered measurement input/result, rather than a data gap."""

    def __init__(self) -> None:
        super().__init__("stock_annual_quality_invalid")


def _check(valid: bool) -> None:
    if not valid:
        raise AnnualQualityError()


def _text(value: str, maximum: int = 512, *, empty: bool = False) -> None:
    _check(type(value) is str and (empty or bool(value)) and len(value) <= maximum)
    _check(all(character.isprintable() for character in value))


@dataclass(frozen=True, slots=True)
class AnnualQualityPeriods:
    current_start: date
    current_end: date
    prior_start: date
    prior_end: date

    def __post_init__(self) -> None:
        _check(
            all(
                type(day) is date
                for day in (
                    self.current_start,
                    self.current_end,
                    self.prior_start,
                    self.prior_end,
                )
            )
        )
        _check(self.current_start > date.min)
        _check(self.current_start <= self.current_end and self.prior_start <= self.prior_end)


@dataclass(frozen=True, slots=True)
class AnnualQualityRequest:
    filing: StockFiling
    facts: tuple[StockFilingFacts, ...]
    entity: str
    periods: AnnualQualityPeriods
    information_at: datetime

    def __post_init__(self) -> None:
        try:
            _check(type(self.filing) is StockFiling)
            _check(type(self.facts) is tuple and 1 <= len(self.facts) <= 8)
            _check(all(type(source) is StockFilingFacts for source in self.facts))
            _check(
                sum(len(source.records) + len(source.null_row_indices) for source in self.facts)
                <= 20000
            )
            _check(
                type(self.entity) is str and re.fullmatch(r"[0-9]{1,10}", self.entity) is not None
            )
            _check(type(self.periods) is AnnualQualityPeriods)
            self.periods.__post_init__()
            require_utc(self.information_at)
        except (ValueError, TypeError, AttributeError, ArithmeticError):
            raise AnnualQualityError() from None


@dataclass(frozen=True, slots=True)
class AnnualFactReference:
    role: str
    source_collection_index: int
    source_facts_hash: str
    observation_sha256: str
    received_at: datetime
    fact: StockFilingFact


@dataclass(frozen=True, slots=True)
class _Result:
    request: AnnualQualityRequest
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    method_id: str = field(default=_METHOD, init=False)
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)
    availability_proxy_at: datetime = field(init=False)
    debt_measurement_at: date = field(init=False)
    debt_measurement_kind: Literal["instant"] = field(default="instant", init=False)

    def _metadata(self) -> None:
        _safe(self)
        object.__setattr__(self, "availability_proxy_at", _proxy(self.request.filing))
        object.__setattr__(self, "debt_measurement_at", self.request.periods.current_end)

    @property
    def evidence_hash(self) -> str:
        value = revalidate_annual_quality(self)
        payload = {
            "schema": "stock-annual-quality-v1",
            "method": value.method_id,
            "filing": {
                "symbol": value.request.filing.symbol,
                "id": value.request.filing.filing_id,
                "date_filed": value.request.filing.date_filed.isoformat(),
                "receipt_sha256": value.request.filing.receipt.observation_sha256,
                "received_at": value.request.filing.receipt.received_at.isoformat(),
            },
            "entity": value.request.entity,
            "periods": {
                "current_start": value.request.periods.current_start.isoformat(),
                "current_end": value.request.periods.current_end.isoformat(),
                "prior_start": value.request.periods.prior_start.isoformat(),
                "prior_end": value.request.periods.prior_end.isoformat(),
            },
            "information_at": value.request.information_at.isoformat(),
            "availability_proxy_at": value.availability_proxy_at.isoformat(),
            "sources": [source.facts_hash for source in value.request.facts],
            "references": [
                (ref.role, ref.source_collection_index, ref.fact.row_index)
                for ref in value.references
            ],
            "reasons": value.reason_codes,
            "values": [
                None if number is None else format(number, "f")
                for number in (value.roe, value.revenue_growth, value.debt_to_equity)
            ],
            "qualification": False,
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class DefinedAnnualQuality(_Result):
    status: Literal["defined"] = field(default="defined", init=False)
    roe: Decimal = field(init=False)
    revenue_growth: Decimal = field(init=False)
    debt_to_equity: Decimal = field(init=False)
    references: tuple[AnnualFactReference, ...] = field(init=False)
    reason_codes: tuple[str, ...] = field(default=(), init=False)

    def __post_init__(self) -> None:
        reasons, references, numbers = _assess(self.request)
        _check(not reasons and numbers is not None)
        if numbers is None:
            raise AnnualQualityError()
        self._metadata()
        object.__setattr__(self, "references", references)
        for name, number in zip(("roe", "revenue_growth", "debt_to_equity"), numbers, strict=True):
            object.__setattr__(self, name, number)


@dataclass(frozen=True, slots=True)
class UnavailableAnnualQuality(_Result):
    status: Literal["unavailable"] = field(default="unavailable", init=False)
    roe: None = field(default=None, init=False)
    revenue_growth: None = field(default=None, init=False)
    debt_to_equity: None = field(default=None, init=False)
    references: tuple[AnnualFactReference, ...] = field(init=False)
    reason_codes: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        reasons, references, _ = _assess(self.request)
        _check(bool(reasons))
        self._metadata()
        object.__setattr__(self, "references", references)
        object.__setattr__(self, "reason_codes", reasons)


def _safe(value: _Result) -> None:
    _check(
        all(
            flag is False
            for flag in (
                value.qualified,
                value.source_qualified,
                value.strategy_qualified,
                value.investment_eligible,
                value.trading_enabled,
                value.live_authorized,
            )
        )
    )
    _check(type(value.method_id) is str and value.method_id == _METHOD)
    _check(type(value.limitations) is tuple and value.limitations == _LIMITATIONS)
    _check(type(value.debt_measurement_kind) is str and value.debt_measurement_kind == "instant")


def _proxy(filing: StockFiling) -> datetime:
    return datetime.combine(filing.date_filed + timedelta(days=2), datetime.min.time(), tzinfo=UTC)


def _validate_sources(request: AnnualQualityRequest) -> tuple[str, ...]:
    try:
        _check(type(request) is AnnualQualityRequest)
        request.__post_init__()
        filing = request.filing
        _check(type(filing.receipt) is StockEventReceipt)
        filing.receipt.__post_init__()
        _check(filing.receipt.tool == "get_sec_filing_index")
        _check(filing.receipt.hash_is_caller_declared is True)
        _check(
            all(
                flag is False
                for flag in (
                    filing.qualified,
                    filing.source_qualified,
                    filing.strategy_qualified,
                    filing.trading_enabled,
                    filing.live_enabled,
                )
            )
        )
        _check(filing.publication_at is None and filing.source_url is None)
        _text(filing.symbol, 15)
        _text(filing.filing_id)
        _text(filing.form_type, 64)
        _text(filing.description, 4096, empty=True)
        _check(
            type(filing.date_filed) is date
            and filing.date_filed <= filing.receipt.received_at.date()
            and filing.date_filed <= date.max - timedelta(days=2)
        )
        source_hashes: list[str] = []
        for source in request.facts:
            _check(
                all(
                    flag is False
                    for flag in (
                        source.qualified,
                        source.source_qualified,
                        source.strategy_qualified,
                        source.investment_eligible,
                        source.trading_enabled,
                        source.live_authorized,
                    )
                )
            )
            _check(source.publication_at is None)
            # Public normalized constructors may be replaced/tampered with; their
            # own validators also verify every nested native fact/receipt.
            rebuilt = replace(source)
            _check(source == rebuilt)
            digest = source.facts_hash
            _require_sha256_hex(digest, "source_facts_hash")
            source_hashes.append(digest)
        return tuple(source_hashes)
    except (ValueError, TypeError, AttributeError, ArithmeticError):
        raise AnnualQualityError() from None


def _period_matches(fact: StockFilingFact, start: date | None, end: date) -> bool:
    def native_tokens(day: date) -> tuple[str, str]:
        return day.isoformat(), day.isoformat() + "T00:00:00"

    if start is None:
        return not fact.start_date_present and fact.period in native_tokens(end)
    pieces = fact.period.split("/")
    return (
        fact.start_date_present
        and fact.start_date == start
        and len(pieces) == 2
        and pieces[0] in native_tokens(start)
        and pieces[1] in native_tokens(end)
    )


def _assess(
    request: AnnualQualityRequest,
) -> tuple[
    tuple[str, ...], tuple[AnnualFactReference, ...], tuple[Decimal, Decimal, Decimal] | None
]:
    source_hashes = _validate_sources(request)
    reasons: list[str] = []
    p, filing = request.periods, request.filing
    if filing.symbol != "AXP" or filing.form_type != "10-K":
        reasons.append("method_or_original_filing_scope_mismatch")
    if p.current_end > filing.date_filed:
        reasons.append("period_after_filing")
    if request.information_at < _proxy(filing):
        reasons.append("filing_not_available_at_proxy")
    if (p.current_end - p.current_start).days + 1 not in {364, 365, 366, 371} or (
        (p.prior_end - p.prior_start).days + 1 not in {364, 365, 366, 371}
    ):
        reasons.append("non_annual_duration")
    if p.prior_end != p.current_start - timedelta(days=1):
        reasons.append("nonadjacent_annual_periods")
    roles = (
        ("net_income", "NetIncomeLoss", p.current_start, p.current_end),
        ("revenue_current", "RevenuesNetOfInterestExpense", p.current_start, p.current_end),
        ("revenue_prior", "RevenuesNetOfInterestExpense", p.prior_start, p.prior_end),
        ("equity_open", "StockholdersEquity", None, p.current_start - timedelta(days=1)),
        ("equity_close", "StockholdersEquity", None, p.current_end),
        ("long_term_debt", "LongTermDebt", None, p.current_end),
        ("short_borrowings", "ShortTermBorrowings", None, p.current_end),
    )
    candidates: list[tuple[int, StockFilingFacts, StockFilingFact]] = []
    for index, source in enumerate(request.facts):
        if source.receipt.received_at.date() < filing.date_filed:
            reasons.append("receipt_before_filing")
        if filing.filing_id not in source.requested_filing_ids:
            reasons.append("source_missing_target_original")
        if source.facts_missing or source.null_row_indices:
            reasons.append("incomplete_source_rows")
        for fact in source.records:
            if fact.filing_id == filing.filing_id:
                if fact.entity != request.entity:
                    reasons.append("mixed_entity")
                candidates.append((index, source, fact))
    references: list[AnnualFactReference] = []
    selected: dict[str, Decimal] = {}
    for role, concept, start, end in roles:
        values: list[Decimal] = []
        for index, source, fact in candidates:
            if fact.concept != concept or fact.end_date != end:
                continue
            if start is not None and fact.start_date != start:
                continue
            if fact.axes_raw is None:
                reasons.append("unknown_dimensions:" + role)
                continue
            if fact.axes_raw:
                continue
            references.append(
                AnnualFactReference(
                    role,
                    index,
                    source_hashes[index],
                    source.receipt.observation_sha256,
                    source.receipt.received_at,
                    fact,
                )
            )
            if not _period_matches(fact, start, end):
                reasons.append("native_period_mismatch:" + role)
                continue
            if not fact.unit_present or fact.unit_raw != "iso4217:USD":
                reasons.append("native_unit_mismatch:" + role)
                continue
            if fact.numeric_value is None:
                reasons.append("missing_numeric_value:" + role)
                continue
            try:
                values.append(require_bounded_decimal(fact.numeric_value, role))
            except ValueError:
                reasons.append("numeric_bounds:" + role)
        if not values:
            reasons.append("missing_component:" + role)
        elif any(number != values[0] for number in values[1:]):
            reasons.append("conflicting_values:" + role)
        else:
            selected[role] = values[0]
    if reasons:
        return tuple(dict.fromkeys(reasons)), tuple(references), None
    try:
        with localcontext(_CONTEXT):
            mean_equity = (selected["equity_open"] + selected["equity_close"]) / Decimal(2)
            if mean_equity <= 0 or selected["equity_close"] <= 0 or selected["revenue_prior"] <= 0:
                return ("nonpositive_denominator",), tuple(references), None
            if selected["long_term_debt"] < 0 or selected["short_borrowings"] < 0:
                return ("negative_financing_component",), tuple(references), None
            numbers = (
                selected["net_income"] / mean_equity,
                selected["revenue_current"] / selected["revenue_prior"] - Decimal(1),
                (selected["long_term_debt"] + selected["short_borrowings"])
                / selected["equity_close"],
            )
            for number in numbers:
                require_bounded_decimal(number, "derived_measurement")
        return (), tuple(references), numbers
    except (DecimalException, ValueError):
        return ("arithmetic_bounds",), tuple(references), None


def build_annual_quality(
    request: AnnualQualityRequest,
) -> DefinedAnnualQuality | UnavailableAnnualQuality:
    """Derive the frozen AXP annual method, or explicit unavailability with no partial values."""
    reasons, _, _ = _assess(request)
    return UnavailableAnnualQuality(request) if reasons else DefinedAnnualQuality(request)


def _revalidated(value: _Result) -> DefinedAnnualQuality | UnavailableAnnualQuality:
    _check(type(value) in (DefinedAnnualQuality, UnavailableAnnualQuality))
    _safe(value)
    rebuilt = build_annual_quality(value.request)
    _check(type(value) is type(rebuilt))
    _check(type(value.availability_proxy_at) is datetime)
    require_utc(value.availability_proxy_at)
    _check(value.availability_proxy_at == rebuilt.availability_proxy_at)
    _check(
        type(value.debt_measurement_at) is date
        and value.debt_measurement_at == rebuilt.debt_measurement_at
    )
    if not isinstance(value, (DefinedAnnualQuality, UnavailableAnnualQuality)):
        raise AnnualQualityError()
    _check(type(value.status) is str and value.status == rebuilt.status)
    _check(type(value.reason_codes) is tuple and value.reason_codes == rebuilt.reason_codes)
    _check(all(type(reason) is str for reason in value.reason_codes))
    _check(type(value.references) is tuple and len(value.references) == len(rebuilt.references))
    for original, expected in zip(value.references, rebuilt.references, strict=True):
        _check(type(original) is AnnualFactReference)
        _check(type(original.role) is str and original.role == expected.role)
        _check(
            type(original.source_collection_index) is int
            and original.source_collection_index == expected.source_collection_index
        )
        _check(
            type(original.source_facts_hash) is str
            and original.source_facts_hash == expected.source_facts_hash
        )
        _check(
            type(original.observation_sha256) is str
            and original.observation_sha256 == expected.observation_sha256
        )
        require_utc(original.received_at)
        _check(original.received_at == expected.received_at and original.fact is expected.fact)
    for original_number, expected_number in zip(
        (value.roe, value.revenue_growth, value.debt_to_equity),
        (rebuilt.roe, rebuilt.revenue_growth, rebuilt.debt_to_equity),
        strict=True,
    ):
        if expected_number is None:
            _check(original_number is None)
        else:
            _check(type(original_number) is Decimal)
            if not isinstance(original_number, Decimal):
                raise AnnualQualityError()
            _check(original_number.as_tuple() == expected_number.as_tuple())
    return value


def revalidate_annual_quality(value: _Result) -> DefinedAnnualQuality | UnavailableAnnualQuality:
    """Reject forged flags, native source state, references or computed result fields."""
    try:
        return _revalidated(value)
    except (ValueError, TypeError, AttributeError, ArithmeticError):
        raise AnnualQualityError() from None
