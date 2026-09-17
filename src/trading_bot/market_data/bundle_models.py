"""Immutable offline bundle values; structural validity is not source authenticity."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.domain import Bar, BarInterval, CorporateAction, DataHash, InstrumentId
from trading_bot.domain.decimal_utils import require_bounded_decimal
from trading_bot.market_data.recording import ResearchDataManifest
from trading_bot.market_data.universe import UniverseMembership

type RecordKind = Literal["bar", "membership", "baseline", "corporate_action", "coverage"]
type CoverageKind = Literal["bar", "membership", "corporate_action"]
type CoverageState = Literal["complete", "gap", "unknown"]

_REASONS = frozenset(
    [
        "bundle_limits_invalid",
        "bundle_input_too_large",
        "bundle_json_invalid",
        "bundle_schema_invalid",
        "bundle_value_invalid",
        "bundle_source_unsupported",
        "bundle_hash_mismatch",
        "bundle_blob_mismatch",
        "bundle_normalization_mismatch",
        "bundle_manifest_mismatch",
        "bundle_record_conflict",
        "bundle_scope_mismatch",
        "bundle_coverage_invalid",
        "bundle_fixture_mismatch",
        "bundle_path_invalid",
        "bundle_storage_unavailable",
        "bundle_storage_conflict",
        "snapshot_query_invalid",
        "snapshot_coverage_missing",
        "snapshot_records_unavailable",
        "snapshot_membership_missing",
        "snapshot_not_member",
        "snapshot_history_insufficient",
        "snapshot_interpolated",
        "snapshot_price_basis_unsupported",
        "snapshot_action_unsupported",
    ]
)
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SYMBOL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}\Z")
_LABEL = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
RECORD_KINDS = ("bar", "membership", "baseline", "corporate_action", "coverage")


class BundleError(ValueError):
    """Bounded public failure; never stores rejected input or private path text."""

    def __init__(self, code: str, *, record_index: int | None = None) -> None:
        if (
            type(code) is not str
            or code not in _REASONS
            or (record_index is not None and (type(record_index) is not int or record_index < 0))
        ):
            code, record_index = "bundle_value_invalid", None
            super().__init__(code)
            self.code, self.record_index = code, record_index
            raise self
        super().__init__(code)
        self.code, self.record_index = code, record_index


def _check(condition: bool, code: str = "bundle_value_invalid") -> None:
    if not condition:
        raise BundleError(code)


def _text(value: object, pattern: re.Pattern[str] = _LABEL) -> None:
    _check(type(value) is str and pattern.fullmatch(value) is not None)


def _instant(value: datetime) -> None:
    try:
        require_utc(value)
        return
    except (ValueError, TypeError, OverflowError):
        pass
    raise BundleError("bundle_value_invalid")


def _window(start: datetime, end: datetime) -> None:
    _instant(start)
    _instant(end)
    _check(start < end)


def _choice(value: object, choices: tuple[str, ...]) -> None:
    _check(type(value) is str and value in choices)


def _strings(values: tuple[str, ...], pattern: re.Pattern[str], *, nonempty: bool = False) -> None:
    _check(type(values) is tuple)
    _check(not nonempty or bool(values))
    for value in values:
        _text(value, pattern)
    _check(len(values) == len(set(values)))


def _items(values: tuple[object, ...], item_type: type[object]) -> None:
    _check(type(values) is tuple and all(type(item) is item_type for item in values))


@dataclass(frozen=True, slots=True)
class BundleLimits:
    max_envelope_bytes: int
    max_blob_bytes: int
    max_total_bytes: int
    max_records: int
    max_json_depth: int

    def __post_init__(self) -> None:
        values = (
            self.max_envelope_bytes,
            self.max_blob_bytes,
            self.max_total_bytes,
            self.max_records,
            self.max_json_depth,
        )
        _check(all(type(value) is int and value > 0 for value in values), "bundle_limits_invalid")
        _check(
            self.max_total_bytes >= max(self.max_envelope_bytes, self.max_blob_bytes),
            "bundle_limits_invalid",
        )


@dataclass(frozen=True, slots=True)
class InstrumentMapping:
    instrument_id: InstrumentId
    symbol: str

    def __post_init__(self) -> None:
        _text(self.instrument_id, _ID)
        _text(self.symbol, _SYMBOL)


@dataclass(frozen=True, slots=True)
class BarSlot:
    starts_at: datetime
    ends_at: datetime

    def __post_init__(self) -> None:
        _window(self.starts_at, self.ends_at)


@dataclass(frozen=True, slots=True)
class MembershipBaseline:
    instrument_id: InstrumentId
    coverage_start: datetime
    effective_at: datetime
    announced_at: datetime
    included: bool

    def __post_init__(self) -> None:
        _text(self.instrument_id, _ID)
        for value in (self.coverage_start, self.effective_at, self.announced_at):
            _instant(value)
        _check(self.effective_at <= self.coverage_start and type(self.included) is bool)


@dataclass(frozen=True, slots=True)
class CoverageDeclaration:
    instrument_id: InstrumentId
    record_kind: CoverageKind
    interval: BarInterval | None
    starts_at: datetime
    ends_at: datetime
    state: CoverageState
    expected_slots: tuple[BarSlot, ...]

    def __post_init__(self) -> None:
        _text(self.instrument_id, _ID)
        _choice(self.record_kind, ("bar", "membership", "corporate_action"))
        _choice(self.state, ("complete", "gap", "unknown"))
        _window(self.starts_at, self.ends_at)
        _items(self.expected_slots, BarSlot)
        _check(
            type(self.interval) is BarInterval
            if self.record_kind == "bar"
            else self.interval is None
        )
        _check(not self.expected_slots or (self.record_kind == "bar" and self.state == "complete"))
        previous_end = self.starts_at
        for slot in self.expected_slots:
            _check(previous_end <= slot.starts_at < slot.ends_at <= self.ends_at)
            previous_end = slot.ends_at


def _source_fields(
    source_id: str,
    origin: str,
    instrument_ids: tuple[InstrumentId, ...],
    record_kinds: tuple[RecordKind, ...],
    requested_start: datetime,
    requested_end: datetime,
    collected_at: datetime,
    claimed_published_at: datetime | None,
    limitation_codes: tuple[str, ...],
) -> None:
    _text(source_id)
    _choice(origin, ("synthetic", "imported"))
    _strings(instrument_ids, _ID, nonempty=True)
    _strings(record_kinds, _LABEL, nonempty=True)
    for kind in record_kinds:
        _choice(kind, RECORD_KINDS)
    _window(requested_start, requested_end)
    _instant(collected_at)
    if claimed_published_at is not None:
        _instant(claimed_published_at)
    _strings(limitation_codes, _LABEL)


@dataclass(frozen=True, slots=True)
class SourceCapture:
    source_id: str
    origin: Literal["synthetic", "imported"]
    instrument_ids: tuple[InstrumentId, ...]
    record_kinds: tuple[RecordKind, ...]
    requested_start: datetime
    requested_end: datetime
    collected_at: datetime
    claimed_published_at: datetime | None
    limitation_codes: tuple[str, ...]
    raw_bytes: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _source_fields(
            self.source_id,
            self.origin,
            self.instrument_ids,
            self.record_kinds,
            self.requested_start,
            self.requested_end,
            self.collected_at,
            self.claimed_published_at,
            self.limitation_codes,
        )
        _check(type(self.raw_bytes) is bytes)


@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    source_id: str
    format_id: str
    normalizer_version: str
    origin: Literal["synthetic", "imported"]
    instrument_ids: tuple[InstrumentId, ...]
    record_kinds: tuple[RecordKind, ...]
    requested_start: datetime
    requested_end: datetime
    collected_at: datetime
    claimed_published_at: datetime | None
    limitation_codes: tuple[str, ...]
    byte_length: int
    blob_sha256: str
    descriptor_hash: DataHash

    def __post_init__(self) -> None:
        _source_fields(
            self.source_id,
            self.origin,
            self.instrument_ids,
            self.record_kinds,
            self.requested_start,
            self.requested_end,
            self.collected_at,
            self.claimed_published_at,
            self.limitation_codes,
        )
        _text(self.format_id)
        _text(self.normalizer_version)
        _check(
            self.format_id == "synthetic-market-v1"
            and self.normalizer_version == "synthetic-normalizer-v1"
            and self.origin == "synthetic",
            "bundle_source_unsupported",
        )
        _check(type(self.byte_length) is int and self.byte_length >= 0)
        _text(self.blob_sha256, _HASH)
        _text(self.descriptor_hash, _HASH)


type RecordValue = (
    Bar | UniverseMembership | MembershipBaseline | CorporateAction | CoverageDeclaration
)


@dataclass(frozen=True, slots=True)
class NormalizedRecord:
    kind: RecordKind
    source_hash: DataHash
    locator: int
    available_at: datetime
    price_basis: Literal["unadjusted", "adjusted", "unknown"] | None
    value: RecordValue
    record_hash: DataHash

    def __post_init__(self) -> None:
        _choice(self.kind, RECORD_KINDS)
        expected = {
            "bar": Bar,
            "membership": UniverseMembership,
            "baseline": MembershipBaseline,
            "corporate_action": CorporateAction,
            "coverage": CoverageDeclaration,
        }
        _check(type(self.value) is expected[self.kind])
        _text(self.source_hash, _HASH)
        _text(self.record_hash, _HASH)
        _check(type(self.locator) is int and self.locator >= 0)
        _instant(self.available_at)
        _text(self.value.instrument_id, _ID)
        if type(self.value) is Bar:
            _choice(self.price_basis, ("unadjusted", "adjusted", "unknown"))
            _text(self.value.source)
            numbers: tuple[Decimal, ...] = (
                self.value.open,
                self.value.high,
                self.value.low,
                self.value.close,
                self.value.volume,
            )
        else:
            _check(self.price_basis is None)
            numbers = ()
            if type(self.value) is CorporateAction:
                _check(type(self.value.effective_date) is date)
                numbers = tuple(
                    v for v in (self.value.split_ratio, self.value.cash_amount) if v is not None
                )
        invalid = False
        try:
            for number in numbers:
                require_bounded_decimal(number, "value")
        except ValueError:
            invalid = True
        _check(not invalid)


@dataclass(frozen=True, slots=True)
class BundleEnvelope:
    schema: Literal["research-bundle-v1"]
    instruments: tuple[InstrumentMapping, ...]
    sources: tuple[SourceDescriptor, ...]
    records: tuple[NormalizedRecord, ...]
    manifest: ResearchDataManifest
    classification: Literal["synthetic"]
    limitation_codes: tuple[str, ...]
    bundle_hash: DataHash

    def __post_init__(self) -> None:
        _check(
            type(self.schema) is str and self.schema == "research-bundle-v1",
            "bundle_schema_invalid",
        )
        _items(self.instruments, InstrumentMapping)
        _items(self.sources, SourceDescriptor)
        _items(self.records, NormalizedRecord)
        _check(bool(self.instruments) and bool(self.sources))
        _check(len({v.instrument_id for v in self.instruments}) == len(self.instruments))
        _check(len({v.symbol for v in self.instruments}) == len(self.instruments))
        _check(len({v.descriptor_hash for v in self.sources}) == len(self.sources))
        _check(type(self.manifest) is ResearchDataManifest)
        _strings(self.manifest.raw_hashes, _HASH)
        _strings(self.manifest.cleaned_hashes, _HASH)
        _text(self.manifest.corporate_action_coverage)
        _check(type(self.manifest.point_in_time_universe) is bool)
        _strings(self.manifest.survivorship_limitations, _LABEL)
        _strings(self.manifest.licensing_limitations, _LABEL)
        _strings(self.manifest.known_gaps, _LABEL)
        _text(self.manifest.manifest_hash, _HASH)
        _check(
            type(self.classification) is str and self.classification == "synthetic",
            "bundle_fixture_mismatch",
        )
        _strings(self.limitation_codes, _LABEL)
        _text(self.bundle_hash, _HASH)


@dataclass(frozen=True, slots=True)
class BundlePackage:
    envelope_bytes: bytes = field(repr=False)
    blobs: tuple[tuple[str, bytes], ...] = field(repr=False)

    def __post_init__(self) -> None:
        _check(type(self.envelope_bytes) is bytes and type(self.blobs) is tuple)
        digests: list[str] = []
        for entry in self.blobs:
            _check(type(entry) is tuple and len(entry) == 2)
            digest, body = entry
            _text(digest, _HASH)
            _check(type(body) is bytes)
            digests.append(digest)
        _check(digests == sorted(set(digests)))


@dataclass(frozen=True, slots=True)
class SnapshotSettings:
    interval: BarInterval
    history_start: datetime
    minimum_bars: int

    def __post_init__(self) -> None:
        _check(type(self.interval) is BarInterval)
        _instant(self.history_start)
        _check(type(self.minimum_bars) is int and self.minimum_bars >= 2)
