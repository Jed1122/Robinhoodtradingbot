"""Exact, independently versioned indexes over unqualified native quote captures."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Literal

from trading_bot.market_data.alpaca_native import AlpacaQuoteRecord
from trading_bot.market_data.bundle_codec import _array, _date, _integer, _json, _mapping, _string
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.recording import canonical_json

MAX_INDEX_BYTES = 1_048_576
MAX_DAY_CAPTURES = 1024
MAX_CATALOG_DAYS = 4000
MAX_CAPTURE_RECORDS = 128_000
DAY_NS = 86_400_000_000_000
_LIMITS = BundleLimits(MAX_INDEX_BYTES, MAX_INDEX_BYTES, MAX_INDEX_BYTES, 4000, 16)
_FLAGS = {"source_qualified", "cost_qualified", "execution_enabled", "evidence_promotable"}
_HASH = re.compile(r"[a-f0-9]{64}\Z")


class QuoteCatalogError(ValueError):
    """Sanitized catalog denial, without customer paths or source values."""

    def __init__(self) -> None:
        super().__init__("etf_quote_catalog_invalid")


def require(value: bool) -> None:
    if not value:
        raise QuoteCatalogError()


def digest(value: object) -> str:
    require(type(value) is str and _HASH.fullmatch(value) is not None)
    return str(value)


def integer(value: object, maximum: int, *, minimum: int = 0) -> None:
    require(type(value) is int and minimum <= value <= maximum)


def window(start_ns: int, end_ns: int) -> None:
    integer(start_ns, 2**63 - 1)
    integer(end_ns, 2**63 - 1)
    require(start_ns < end_ns)


class _Unqualified:
    __slots__ = ()

    def _flags_valid(self) -> None:
        require(all(getattr(self, flag) is False for flag in _FLAGS))


@dataclass(frozen=True, slots=True)
class QuoteCaptureLocation:
    relative_path: str
    manifest_hash: str

    def __post_init__(self) -> None:
        require(type(self.relative_path) is str and 0 < len(self.relative_path) <= 512)
        parts = self.relative_path.split("/")
        require(len(parts) <= 16)
        require(
            all(
                re.fullmatch(r"[A-Za-z0-9_.-]+", part) and part not in (".", "..") for part in parts
            )
        )
        digest(self.manifest_hash)


@dataclass(frozen=True, slots=True)
class QuoteCaptureReference:
    location: QuoteCaptureLocation
    archive_hash: str
    start_ns: int
    end_ns: int
    record_count: int

    def __post_init__(self) -> None:
        require(type(self.location) is QuoteCaptureLocation)
        self.location.__post_init__()
        digest(self.archive_hash)
        window(self.start_ns, self.end_ns)
        integer(self.record_count, MAX_CAPTURE_RECORDS, minimum=1)


@dataclass(frozen=True, slots=True)
class QuoteDayIndex(_Unqualified):
    day: date
    captures: tuple[QuoteCaptureReference, ...]
    source_qualified: Literal[False] = field(default=False, init=False)
    cost_qualified: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        self._flags_valid()
        require(type(self.day) is date)
        require(type(self.captures) is tuple and 0 < len(self.captures) <= MAX_DAY_CAPTURES)
        start = (self.day - date(1970, 1, 1)).days * DAY_NS
        end, paths, manifests, archives = start, set(), set(), set()
        for ref in self.captures:
            require(type(ref) is QuoteCaptureReference)
            ref.__post_init__()
            require(start <= end <= ref.start_ns < ref.end_ns <= start + DAY_NS)
            require(ref.location.relative_path not in paths)
            require(
                ref.location.manifest_hash not in manifests and ref.archive_hash not in archives
            )
            paths.add(ref.location.relative_path)
            manifests.add(ref.location.manifest_hash)
            archives.add(ref.archive_hash)
            end = ref.end_ns


@dataclass(frozen=True, slots=True)
class QuoteDayReference:
    day: date
    index_hash: str
    capture_count: int
    observation_count: int

    def __post_init__(self) -> None:
        require(type(self.day) is date)
        digest(self.index_hash)
        integer(self.capture_count, MAX_DAY_CAPTURES, minimum=1)
        integer(
            self.observation_count,
            self.capture_count * MAX_CAPTURE_RECORDS,
            minimum=self.capture_count,
        )


@dataclass(frozen=True, slots=True)
class QuoteCatalog(_Unqualified):
    code_revision: str
    config_hash: str
    days: tuple[QuoteDayReference, ...]
    source_qualified: Literal[False] = field(default=False, init=False)
    cost_qualified: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        self._flags_valid()
        require(
            type(self.code_revision) is str
            and re.fullmatch(r"[a-f0-9]{40}", self.code_revision) is not None
        )
        digest(self.config_hash)
        require(type(self.days) is tuple and 0 < len(self.days) <= MAX_CATALOG_DAYS)
        previous, hashes = None, set()
        for ref in self.days:
            require(type(ref) is QuoteDayReference)
            ref.__post_init__()
            require(previous is None or previous < ref.day)
            require(ref.index_hash not in hashes)
            hashes.add(ref.index_hash)
            previous = ref.day


@dataclass(frozen=True, slots=True, repr=False)
class CatalogQuoteOccurrence:
    location: QuoteCaptureLocation
    archive_hash: str
    record: AlpacaQuoteRecord

    def __post_init__(self) -> None:
        require(type(self.location) is QuoteCaptureLocation)
        self.location.__post_init__()
        digest(self.archive_hash)
        require(type(self.record) is AlpacaQuoteRecord)
        self.record.__post_init__()


def _encode(value: QuoteDayIndex | QuoteCatalog, schema: str) -> bytes:
    value.__post_init__()
    body = canonical_json({"schema": schema, **asdict(value)}).encode()
    require(len(body) <= MAX_INDEX_BYTES)
    return body


def encode_day(value: QuoteDayIndex) -> bytes:
    require(type(value) is QuoteDayIndex)
    return _encode(value, "etf-native-quote-day-v1")


def encode_catalog(value: QuoteCatalog) -> bytes:
    require(type(value) is QuoteCatalog)
    return _encode(value, "etf-native-quote-catalog-v1")


def _wire(encoded: bytes, keys: set[str], schema: str) -> dict[str, object]:
    row = _mapping(
        _json(encoded, max_bytes=MAX_INDEX_BYTES, limits=_LIMITS), keys | _FLAGS | {"schema"}
    )
    require(row["schema"] == schema and all(row[flag] is False for flag in _FLAGS))
    return row


def decode_day(encoded: bytes) -> QuoteDayIndex:
    try:
        wire = _wire(encoded, {"day", "captures"}, "etf-native-quote-day-v1")
        rows = _array(wire["captures"])
        require(len(rows) <= MAX_DAY_CAPTURES)
        captures = []
        for value in rows:
            row = _mapping(
                value, {"location", "archive_hash", "start_ns", "end_ns", "record_count"}
            )
            location = _mapping(row["location"], {"relative_path", "manifest_hash"})
            captures.append(
                QuoteCaptureReference(
                    QuoteCaptureLocation(
                        _string(location["relative_path"]), digest(location["manifest_hash"])
                    ),
                    digest(row["archive_hash"]),
                    _integer(row["start_ns"]),
                    _integer(row["end_ns"]),
                    _integer(row["record_count"]),
                )
            )
        return QuoteDayIndex(_date(wire["day"]), tuple(captures))
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise QuoteCatalogError() from None


def decode_catalog(encoded: bytes) -> QuoteCatalog:
    try:
        wire = _wire(
            encoded, {"code_revision", "config_hash", "days"}, "etf-native-quote-catalog-v1"
        )
        rows = _array(wire["days"])
        require(len(rows) <= MAX_CATALOG_DAYS)
        days = []
        for value in rows:
            row = _mapping(value, {"day", "index_hash", "capture_count", "observation_count"})
            days.append(
                QuoteDayReference(
                    _date(row["day"]),
                    digest(row["index_hash"]),
                    _integer(row["capture_count"]),
                    _integer(row["observation_count"]),
                )
            )
        return QuoteCatalog(
            _string(wire["code_revision"]), digest(wire["config_hash"]), tuple(days)
        )
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise QuoteCatalogError() from None


def day_hash(value: QuoteDayIndex) -> str:
    return hashlib.sha256(encode_day(value)).hexdigest()


def catalog_hash(value: QuoteCatalog) -> str:
    return hashlib.sha256(encode_catalog(value)).hexdigest()
