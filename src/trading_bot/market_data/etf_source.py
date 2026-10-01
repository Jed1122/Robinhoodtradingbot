"""Offline ETF fixture contracts, not a qualified provider adapter.

The only supported wire format is code-owned synthetic JSON. Its timestamps,
calendar and feed labels are test declarations, never historical receipt proof.
No actual-source role/era has been approved, so qualification always fails closed.
Actual parsers, fractional terms, payable action semantics and source rule adoption
remain with the authoritative owner. No transport or output writer exists here.
"""

import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

from trading_bot.clock import require_utc
from trading_bot.domain import (
    AssetClass,
    Bar,
    BarInterval,
    CorporateAction,
    DataHash,
    InstrumentId,
    MarketClock,
    Quote,
    TimestampSource,
)
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.bundle_codec import (
    _array,
    _boolean,
    _decimal,
    _digest,
    _integer,
    _json,
    _mapping,
    _string,
    _time,
    _value,
)
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.bundle_store import _open_root, _read
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_study import EtfStudy

_MAX_BYTES = 1048576
_MAX_RECORDS = 25000
_MAX_PAGES = 128
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class EtfSourceError(ValueError):
    def __init__(self) -> None:
        super().__init__("etf_source_invalid")


def _check(ok: bool) -> None:
    if not ok:
        raise EtfSourceError()


def _ns(value: datetime) -> int:
    require_utc(value)
    delta = value - _EPOCH
    return (delta.days * 86400 + delta.seconds) * 10**9 + delta.microseconds * 1000


def _instant(value: int) -> None:
    _check(type(value) is int and 0 < value < 2**63)


def _ceil_time(value: int) -> datetime:
    _instant(value)
    return _EPOCH + timedelta(microseconds=(value + 999) // 1000)


@dataclass(frozen=True, slots=True)
class _Observed:
    source_record_hash: DataHash
    ordinal: int
    event_at_ns: int
    available_at_ns: int
    instrument_id: InstrumentId
    revision_of: DataHash | None

    def __post_init__(self) -> None:
        _require_sha256_hex(self.source_record_hash, "source record")
        _check(type(self.ordinal) is int and 0 <= self.ordinal < 2**63)
        _instant(self.event_at_ns)
        _instant(self.available_at_ns)
        _check(self.event_at_ns <= self.available_at_ns)
        _check(type(self.instrument_id) is str and self.instrument_id == "SPY")
        if self.revision_of is not None:
            _require_sha256_hex(self.revision_of, "revision")
            _check(self.revision_of != self.source_record_hash)


@dataclass(frozen=True, slots=True)
class EtfObservedBar(_Observed):
    payload: Bar

    def __post_init__(self) -> None:
        _Observed.__post_init__(self)
        _check(type(self.payload) is Bar)
        bar = self.payload
        _check(bar.instrument_id == self.instrument_id and bar.source == "synthetic")
        _check(bar.data_hash == self.source_record_hash)
        _check(bar.interval is BarInterval.ONE_DAY and not bar.interpolated)
        _check(_ns(bar.ends_at) == self.event_at_ns)
        for value in (bar.open, bar.high, bar.low, bar.close, bar.volume):
            require_bounded_decimal(value, "bar value", nonnegative=True)


@dataclass(frozen=True, slots=True)
class EtfObservedQuote(_Observed):
    payload: Quote
    bid_size: Decimal
    ask_size: Decimal

    def __post_init__(self) -> None:
        _Observed.__post_init__(self)
        _check(type(self.payload) is Quote and self.revision_of is None)
        quote = self.payload
        _check(quote.instrument_id == self.instrument_id and quote.source == "synthetic")
        _check(quote.data_hash == self.source_record_hash)
        _check(quote.observed_at == _ceil_time(self.event_at_ns))
        _check(not quote.freshness_verified and quote.timestamp_source is TimestampSource.SIMULATED)
        for value in (quote.bid, quote.ask, self.bid_size, self.ask_size):
            require_bounded_decimal(value, "quote value", nonnegative=True)


@dataclass(frozen=True, slots=True)
class EtfActionEvent(_Observed):
    payload: CorporateAction

    def __post_init__(self) -> None:
        _Observed.__post_init__(self)
        _check(type(self.payload) is CorporateAction)
        action = self.payload
        _check(type(action.effective_date) is date)
        _check(action.instrument_id == self.instrument_id)
        _check(action.data_hash == self.source_record_hash)
        _check(_ns(action.announced_at) <= self.available_at_ns)
        value = action.split_ratio if action.action_type == "split" else action.cash_amount
        _check(value is not None)
        require_bounded_decimal(cast(Decimal, value), "action value", nonnegative=True)


@dataclass(frozen=True, slots=True)
class EtfSessionEvent(_Observed):
    payload: MarketClock

    def __post_init__(self) -> None:
        _Observed.__post_init__(self)
        _clock(self)


@dataclass(frozen=True, slots=True)
class EtfControlEvent(_Observed):
    payload: MarketClock

    def __post_init__(self) -> None:
        _Observed.__post_init__(self)
        _clock(self)


def _clock(event: EtfSessionEvent | EtfControlEvent) -> None:
    clock = event.payload
    _check(type(clock) is MarketClock and event.revision_of is None)
    _check(clock.asset_class is AssetClass.EQUITY and clock.venue == "XNYS")
    _check(clock.observed_at == _ceil_time(event.event_at_ns))
    for future in (clock.next_open_at, clock.next_close_at):
        _check(future is None or _ns(future) > event.event_at_ns)
    if clock.next_open_at is not None and clock.next_close_at is not None:
        if clock.is_open:
            _check(clock.next_close_at < clock.next_open_at)
        else:
            _check(clock.next_open_at < clock.next_close_at)


type EtfSourceEvent = (
    EtfObservedBar | EtfObservedQuote | EtfActionEvent | EtfSessionEvent | EtfControlEvent
)


class QualifiedEtfDataset:
    """Reserved owner seam. There is no approved real-source factory yet."""

    __slots__ = ()

    def __new__(cls) -> "QualifiedEtfDataset":
        raise EtfSourceError()


@dataclass(frozen=True, slots=True)
class EtfSourceAssessment:
    reasons: tuple[str, ...]
    parsed_event_count: int = 0
    status: Literal["BLOCKED_INPUTS"] = field(default="BLOCKED_INPUTS", init=False)
    dataset: QualifiedEtfDataset | None = field(default=None, init=False)
    role_era_evidence_hashes: tuple[DataHash, ...] = field(default=(), init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)


def _event(value: object) -> EtfSourceEvent:
    row = _mapping(
        value,
        {
            "kind",
            "ordinal",
            "instrument_id",
            "event_at_ns",
            "published_at_ns",
            "received_at_ns",
            "revision_of",
            "payload",
        },
    )
    kind = _string(row["kind"])
    event_ns = _integer(row["event_at_ns"])
    publication = _integer(row["published_at_ns"])
    receipt = _integer(row["received_at_ns"])
    for instant in (event_ns, publication, receipt):
        _instant(instant)
    _check(event_ns <= publication <= receipt)
    digest = content_hash(row)
    args = (
        digest,
        _integer(row["ordinal"]),
        event_ns,
        receipt,
        InstrumentId(_string(row["instrument_id"])),
        None if row["revision_of"] is None else _digest(row["revision_of"]),
    )
    if kind == "bar":
        return EtfObservedBar(*args, cast(Bar, _value("bar", row["payload"], raw_hash=digest)))
    if kind == "action":
        return EtfActionEvent(
            *args,
            cast(CorporateAction, _value("corporate_action", row["payload"], raw_hash=digest)),
        )
    if kind == "quote":
        payload = _mapping(row["payload"], {"bid", "ask", "bid_size", "ask_size"})
        return EtfObservedQuote(
            *args,
            Quote(
                args[4],
                _ceil_time(event_ns),
                _decimal(payload["bid"]),
                _decimal(payload["ask"]),
                None,
                "synthetic",
                digest,
                False,
                TimestampSource.SIMULATED,
            ),
            _decimal(payload["bid_size"]),
            _decimal(payload["ask_size"]),
        )
    _check(kind in ("session", "control"))
    payload = _mapping(
        row["payload"],
        {
            "venue",
            "is_open",
            "halted",
            "trading_disabled",
            "cancel_only",
            "next_open_at",
            "next_close_at",
        },
    )
    clock = MarketClock(
        AssetClass.EQUITY,
        _string(payload["venue"]),
        _ceil_time(event_ns),
        _boolean(payload["is_open"]),
        _boolean(payload["halted"]),
        _boolean(payload["trading_disabled"]),
        _boolean(payload["cancel_only"]),
        None if payload["next_open_at"] is None else _time(payload["next_open_at"]),
        None if payload["next_close_at"] is None else _time(payload["next_close_at"]),
    )
    return (EtfSessionEvent if kind == "session" else EtfControlEvent)(*args, clock)


def _sequence(events: tuple[EtfSourceEvent, ...]) -> None:
    seen: dict[DataHash, EtfSourceEvent] = {}
    superseded: set[DataHash] = set()
    previous: EtfSourceEvent | None = None
    versions: dict[tuple[object, ...], DataHash] = {}
    for event in events:
        if previous is not None:
            _check(previous.ordinal < event.ordinal)
            _check(previous.available_at_ns <= event.available_at_ns)
        _check(event.source_record_hash not in seen)
        if event.revision_of is not None:
            old = seen.get(event.revision_of)
            _check(old is not None and event.revision_of not in superseded)
            _check(type(old) is type(event))
            if old is None:
                raise EtfSourceError()
            _check(old.event_at_ns == event.event_at_ns)
            _check(old.available_at_ns < event.available_at_ns)
            if isinstance(old, EtfObservedBar) and isinstance(event, EtfObservedBar):
                _check(old.payload.starts_at == event.payload.starts_at)
            if isinstance(old, EtfActionEvent) and isinstance(event, EtfActionEvent):
                _check(
                    (old.payload.action_type, old.payload.effective_date)
                    == (event.payload.action_type, event.payload.effective_date)
                )
            superseded.add(event.revision_of)
        key: tuple[object, ...] | None = None
        if isinstance(event, EtfObservedBar):
            key = ("bar", event.instrument_id, event.payload.starts_at, event.payload.ends_at)
        elif isinstance(event, EtfActionEvent):
            key = (
                "action",
                event.instrument_id,
                event.payload.action_type,
                event.payload.effective_date,
            )
        if key is not None:
            _check(versions.get(key) == event.revision_of)
            versions[key] = event.source_record_hash
        seen[event.source_record_hash] = event
        previous = event


def _page(encoded: bytes, digest: str) -> tuple[int, int | None, tuple[EtfSourceEvent, ...]]:
    _require_sha256_hex(digest, "page hash")
    _check(type(encoded) is bytes and len(encoded) <= _MAX_BYTES)
    _check(hashlib.sha256(encoded).hexdigest() == digest)
    row = _mapping(
        _json(
            encoded,
            max_bytes=_MAX_BYTES,
            limits=BundleLimits(_MAX_BYTES, _MAX_BYTES, _MAX_BYTES * _MAX_PAGES, _MAX_RECORDS, 16),
        ),
        {"schema", "feed", "page", "next_page", "records"},
    )
    _check(row["schema"] == "etf-synthetic-page-v1" and row["feed"] == "synthetic")
    page = _integer(row["page"])
    _check(0 <= page < _MAX_PAGES)
    next_page = None if row["next_page"] is None else _integer(row["next_page"])
    _check(next_page is None or next_page == page + 1)
    records = _array(row["records"])
    _check(len(records) <= _MAX_RECORDS)
    events = tuple(_event(record) for record in records)
    return page, next_page, events


def parse_etf_fixture(encoded: bytes, *, expected_sha256: str) -> tuple[EtfSourceEvent, ...]:
    """Parse one complete synthetic page. Returns observations, never a dataset.

    Decimal text is canonical; exact nanoseconds remain authoritative. Datetime
    projections round upward. Locked/delayed quotes retain unverified freshness;
    deciding usable age or capacity belongs to the owner, not this parser.
    """
    try:
        page, next_page, events = _page(encoded, expected_sha256)
        _check(page == 0 and next_page is None)
        _sequence(events)
        return events
    except (ValueError, TypeError, ArithmeticError, RecursionError):
        raise EtfSourceError() from None


def qualify_etf_source(
    study: EtfStudy, *, manifest_path: Path, allowed_root: Path
) -> EtfSourceAssessment:
    """Inspect a private synthetic package without trusting its provenance claims.

    Filenames must be SHA256.json, paths cannot contain symlinks/traversal, and
    root/files must have private ownership/modes using the existing safe reader.
    Nothing is written, so existing archives are never overwritten. A complete
    fixture stream still supplies no actual role/era, coverage or receipt evidence.
    """
    denied = {
        "source_reference_unverified",
        "historical_availability_unverified",
        "source_coverage_unverified",
        "fractional_terms_unverified",
    }
    count = 0
    try:
        _check(type(study) is EtfStudy)
        _check(isinstance(manifest_path, Path) and isinstance(allowed_root, Path))
        _check(manifest_path.is_absolute() and ".." not in manifest_path.parts)
        _check(manifest_path.parent == allowed_root)
        _check(manifest_path.suffix == ".json")
        _require_sha256_hex(manifest_path.stem, "manifest hash")
        root = _open_root(allowed_root, Path(__file__).resolve().parents[3])
        try:
            encoded = _read(root, manifest_path.name, _MAX_BYTES)
            _check(hashlib.sha256(encoded).hexdigest() == manifest_path.stem)
            manifest = _mapping(
                _json(
                    encoded,
                    max_bytes=_MAX_BYTES,
                    limits=BundleLimits(
                        _MAX_BYTES, _MAX_BYTES, _MAX_BYTES * _MAX_PAGES, _MAX_RECORDS, 16
                    ),
                ),
                {
                    "schema",
                    "study_hash",
                    "source_plan_hash",
                    "origin",
                    "feed",
                    "starts_at",
                    "ends_at",
                    "pages",
                },
            )
            _check(manifest["schema"] == "etf-synthetic-manifest-v1")
            _check(manifest["origin"] == "synthetic" and manifest["feed"] == "synthetic")
            _check(manifest["study_hash"] == study.study_hash)
            _check(manifest["source_plan_hash"] == study.source_plan_hash)
            _check(_time(manifest["starts_at"]) == study.requested_start)
            _check(_time(manifest["ends_at"]) == study.requested_end)
            pages = tuple(_digest(item) for item in _array(manifest["pages"]))
            _check(len(pages) <= _MAX_PAGES and len(set(pages)) == len(pages))
            events: list[EtfSourceEvent] = []
            for index, digest in enumerate(pages):
                page, next_page, items = _page(_read(root, digest + ".json", _MAX_BYTES), digest)
                _check(page == index)
                _check(next_page == (index + 1 if index + 1 < len(pages) else None))
                events.extend(items)
                _check(len(events) <= _MAX_RECORDS)
            _sequence(tuple(events))
            _check(
                all(
                    _ns(study.requested_start) <= item.event_at_ns < _ns(study.requested_end)
                    for item in events
                )
            )
            count = len(events)
            denied.add("synthetic_inputs_only")
            if not events:
                denied.add("source_coverage_empty")
        finally:
            os.close(root)
    except (OSError, ValueError, TypeError, ArithmeticError, RecursionError):
        denied.add("source_input_invalid")
    return EtfSourceAssessment(tuple(sorted(denied)), count)


def iter_etf_events(
    dataset: QualifiedEtfDataset, *, starts_at: datetime, ends_at: datetime
) -> Iterator[EtfSourceEvent]:
    """Fail closed until the owner adopts an actual-source qualification factory."""
    # No instance (including object.__new__) can bypass absent reviewed evidence.
    raise EtfSourceError()
