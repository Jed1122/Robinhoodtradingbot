"""Immutable offline research envelopes. Hashes do not authenticate source evidence."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.domain import Bar, CorporateAction, DataHash
from trading_bot.domain.decimal_utils import (
    DomainValidationError,
    _require_nonempty,
    _require_sha256_hex,
    require_bounded_decimal,
)
from trading_bot.domain.options import OptionContract, OptionKind, OptionSession
from trading_bot.market_data.options_records import ChainSnapshot, OptionsDataRecord

type SourceKind = Literal["synthetic", "imported"]
VERSION = "spy-prior-close-atm-30d-v1"
REASONS = frozenset(
    {
        "shortlist_disabled",
        "source_evidence_unverified",
        "calendar_unverified",
        "prior_close_unavailable",
        "action_coverage_unverified",
        "reference_discontinuity",
        "chain_unavailable",
        "no_common_eligible_expiry",
    }
)


def _check(ok: bool) -> None:
    if not ok:
        raise DomainValidationError("shortlist_input_invalid")


def _text(value: str) -> None:
    _check(type(value) is str)
    _require_nonempty(value, "shortlist identity")


def _origin(value: SourceKind) -> None:
    _check(type(value) is str and value in {"synthetic", "imported"})


def _items(value: tuple[object, ...], kind: type[object]) -> None:
    _check(type(value) is tuple and all(type(item) is kind for item in value))


@dataclass(frozen=True, slots=True)
class ShortlistEvidence:
    source: str
    source_kind: SourceKind
    raw_hash: DataHash
    available_at: datetime
    covers_from: datetime
    covers_through: datetime
    semantics: Literal["synthetic-shortlist-v1", "unverified-import-v1"]

    def __post_init__(self) -> None:
        _text(self.source)
        _origin(self.source_kind)
        _require_sha256_hex(self.raw_hash, "shortlist digest")
        for instant in (self.available_at, self.covers_from, self.covers_through):
            require_utc(instant)
        _check(self.covers_from <= self.covers_through)
        expected = (
            "synthetic-shortlist-v1" if self.source_kind == "synthetic" else "unverified-import-v1"
        )
        _check(type(self.semantics) is str and self.semantics == expected)


@dataclass(frozen=True, slots=True)
class ShortlistCalendarDay:
    trading_date: date
    regular_session: OptionSession | None

    def __post_init__(self) -> None:
        _check(type(self.trading_date) is date)
        if self.regular_session is not None:
            _check(type(self.regular_session) is OptionSession)
            _check(self.regular_session.trading_date == self.trading_date)


@dataclass(frozen=True, slots=True)
class ShortlistCalendar:
    evidence: ShortlistEvidence
    days: tuple[ShortlistCalendarDay, ...]

    def __post_init__(self) -> None:
        _check(type(self.evidence) is ShortlistEvidence)
        _items(self.days, ShortlistCalendarDay)
        _check(len({day.trading_date for day in self.days}) == len(self.days))


@dataclass(frozen=True, slots=True)
class ShortlistClose:
    bar: Bar
    available_at: datetime
    price_basis: Literal["unadjusted"]
    coverage_label: Literal["source_last_trade", "official_consolidated_close"]
    evidence: ShortlistEvidence

    def __post_init__(self) -> None:
        _check(type(self.bar) is Bar and type(self.evidence) is ShortlistEvidence)
        require_utc(self.available_at)
        _check(self.available_at >= self.bar.ends_at)
        _check(type(self.price_basis) is str and self.price_basis == "unadjusted")
        _check(
            type(self.coverage_label) is str
            and self.coverage_label
            in {
                "source_last_trade",
                "official_consolidated_close",
            }
        )
        _check(self.bar.source == self.evidence.source)
        require_bounded_decimal(self.bar.close, "shortlist close", positive=True)


@dataclass(frozen=True, slots=True)
class ShortlistDiscontinuity:
    instrument_id: str
    action_type: Literal["merger", "denomination_change", "deliverable_change", "unknown"]
    effective_date: date
    announced_at: datetime
    data_hash: DataHash

    def __post_init__(self) -> None:
        _text(self.instrument_id)
        _check(
            type(self.action_type) is str
            and self.action_type
            in {
                "merger",
                "denomination_change",
                "deliverable_change",
                "unknown",
            }
        )
        _check(type(self.effective_date) is date)
        require_utc(self.announced_at)
        _require_sha256_hex(self.data_hash, "shortlist digest")


@dataclass(frozen=True, slots=True)
class ShortlistAction:
    action: CorporateAction | ShortlistDiscontinuity
    available_at: datetime

    def __post_init__(self) -> None:
        _check(type(self.action) in (CorporateAction, ShortlistDiscontinuity))
        _check(type(self.action.effective_date) is date)
        require_utc(self.available_at)
        _check(self.available_at >= self.action.announced_at)


@dataclass(frozen=True, slots=True)
class ShortlistSessionInput:
    current_session: OptionSession
    prior_session: OptionSession | None
    calendar: ShortlistCalendar | None
    closes: tuple[ShortlistClose, ...]
    action_evidence: ShortlistEvidence | None
    actions: tuple[ShortlistAction, ...]
    option_source: str
    chain_evidence: ShortlistEvidence | None
    records: tuple[OptionsDataRecord, ...]
    source_kind: SourceKind

    def __post_init__(self) -> None:
        _origin(self.source_kind)
        _text(self.option_source)
        _check(type(self.current_session) is OptionSession)
        _check(self.prior_session is None or type(self.prior_session) is OptionSession)
        _check(self.calendar is None or type(self.calendar) is ShortlistCalendar)
        _items(self.closes, ShortlistClose)
        _items(self.actions, ShortlistAction)
        _items(self.records, OptionsDataRecord)
        evidence = [close.evidence for close in self.closes]
        if self.calendar is not None:
            evidence.append(self.calendar.evidence)
        for item in (self.action_evidence, self.chain_evidence):
            if item is not None:
                _check(type(item) is ShortlistEvidence)
                evidence.append(item)
        _check(all(item.source_kind == self.source_kind for item in evidence))
        if self.chain_evidence is not None:
            _check(self.chain_evidence.source == self.option_source)
        for record in self.records:
            _check(record.source_kind == self.source_kind and record.source == self.option_source)
            _check(type(record.value) in (ChainSnapshot, OptionContract))

    @property
    def record_count(self) -> int:
        return (
            len(self.records)
            + len(self.closes)
            + len(self.actions)
            + (len(self.calendar.days) if self.calendar else 0)
        )


@dataclass(frozen=True, slots=True)
class OptionsShortlistCandidate:
    session_id: str
    as_of: datetime
    kind: OptionKind
    contract_id: str
    standardized_id: str
    expiration: date
    strike: Decimal
    reference_close_hash: DataHash
    selected_input_hashes: tuple[tuple[str, DataHash], ...]

    def __post_init__(self) -> None:
        for value in (self.session_id, self.contract_id, self.standardized_id):
            _text(value)
        require_utc(self.as_of)
        _check(type(self.kind) is OptionKind and type(self.expiration) is date)
        require_bounded_decimal(self.strike, "shortlist strike", positive=True)
        _require_sha256_hex(self.reference_close_hash, "shortlist digest")
        _check(type(self.selected_input_hashes) is tuple)
        roles = []
        for item in self.selected_input_hashes:
            _check(type(item) is tuple and len(item) == 2)
            _text(item[0])
            _require_sha256_hex(item[1], "shortlist digest")
            roles.append(item[0])
        _check(bool(roles) and roles == sorted(set(roles)))


@dataclass(frozen=True, slots=True)
class OptionsShortlistResult:
    version: str
    session_id: str
    as_of: datetime
    source_kind: SourceKind
    config_hash: DataHash
    code_hash: DataHash
    input_hash: DataHash
    decision_hash: DataHash
    status: Literal["selected", "no_candidate"]
    reasons: tuple[str, ...]
    candidates: tuple[OptionsShortlistCandidate, ...]
    input_record_count: int
    production_eligible: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    download_authorized: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _check(type(self.version) is str and self.version == VERSION)
        _text(self.session_id)
        require_utc(self.as_of)
        _origin(self.source_kind)
        for digest in (self.config_hash, self.code_hash, self.input_hash, self.decision_hash):
            _require_sha256_hex(digest, "shortlist digest")
        _items(self.candidates, OptionsShortlistCandidate)
        _items(self.reasons, str)
        _check(type(self.input_record_count) is int and self.input_record_count >= 0)
        _check(type(self.status) is str and self.status in {"selected", "no_candidate"})
        if self.status == "selected":
            _check(self.source_kind == "synthetic" and not self.reasons)
            _check(tuple(c.kind for c in self.candidates) == (OptionKind.CALL, OptionKind.PUT))
            _check(len({c.expiration for c in self.candidates}) == 1)
            _check(
                all(
                    c.session_id == self.session_id and c.as_of == self.as_of
                    for c in self.candidates
                )
            )
        else:
            _check(not self.candidates and len(self.reasons) == 1 and self.reasons[0] in REASONS)
