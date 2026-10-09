"""Private supplied-byte daily archives; no authenticated capture or acceptance."""

import hashlib
import os
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.alpaca_capital_native import (
    CapitalDailyPage,
    CapitalDailyRequest,
    assess_capital_daily_pages,
    parse_capital_daily_page,
)
from trading_bot.market_data.alpaca_native import MAX_PAGE_BYTES, MAX_PAGES
from trading_bot.market_data.bundle_codec import _array, _json, _mapping
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.bundle_store import _open_root, _publish, _read
from trading_bot.market_data.etf_source import _ns
from trading_bot.market_data.recording import canonical_json, content_hash

_LIMITS = BundleLimits(1048576, 1048576, 1048576, 1000, 16)
_SCHEMA = "alpaca-capital-daily-capture-v1"


def _check(condition: bool) -> None:
    if not condition:
        raise ValueError("capital_daily_archive_invalid")


@dataclass(frozen=True, slots=True, repr=False)
class CapitalDailyArchive:
    manifest_hash: str
    request: CapitalDailyRequest
    pages: tuple[CapitalDailyPage, ...]
    received_at: tuple[datetime, ...]
    source_qualified: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_sha256_hex(self.manifest_hash, "manifest")
        _check(type(self.request) is CapitalDailyRequest)
        replace(self.request)
        _check(type(self.pages) is tuple and 0 < len(self.pages) <= MAX_PAGES)
        _check(type(self.received_at) is tuple and len(self.received_at) == len(self.pages))
        assess_capital_daily_pages(self.pages)
        previous = None
        for page, instant in zip(self.pages, self.received_at, strict=True):
            _check(page.request == self.request)
            _check(type(instant) is datetime)
            require_utc(instant)
            _check(all(record.bar.timestamp_ns <= _ns(instant) for record in page.records))
            _check(previous is None or instant >= previous)
            previous = instant
        _check(self.source_qualified is False and self.evidence_promotable is False)

    @property
    def archive_hash(self) -> str:
        self.__post_init__()
        return content_hash({"schema": "capital-daily-archive-v1", "archive": self})


def _payload(
    request: CapitalDailyRequest, pages: tuple[CapitalDailyPage, ...], clocks: tuple[datetime, ...]
) -> dict[str, object]:
    assessment = assess_capital_daily_pages(pages)
    return {
        "schema": _SCHEMA,
        "request": asdict(request),
        "request_hash": request.request_hash,
        "receipts": tuple(
            {
                "page_index": page.page_index,
                "body_sha256": page.body_sha256,
                "received_at_utc": instant.isoformat(),
            }
            for page, instant in zip(pages, clocks, strict=True)
        ),
        "record_count": assessment.record_count,
        "pagination_complete": assessment.pagination_complete,
        "source_qualified": False,
        "evidence_promotable": False,
    }


def _pages(request: CapitalDailyRequest, bodies: tuple[bytes, ...]) -> tuple[CapitalDailyPage, ...]:
    _check(type(bodies) is tuple and 0 < len(bodies) <= MAX_PAGES)
    pages: list[CapitalDailyPage] = []
    previous: str | None = None
    for index, body in enumerate(bodies):
        _check(type(body) is bytes and 0 < len(body) <= MAX_PAGE_BYTES)
        page = parse_capital_daily_page(
            body,
            request=request,
            expected_sha256=hashlib.sha256(body).hexdigest(),
            page_index=index,
            requested_page_token=previous,
        )
        pages.append(page)
        previous = page.next_page_token
    result = tuple(pages)
    assess_capital_daily_pages(result)
    return result


def write_capital_daily_archive(
    root: Path,
    *,
    repository_root: Path,
    request: CapitalDailyRequest,
    bodies: tuple[bytes, ...],
    received_at: tuple[datetime, ...],
) -> str:
    """Validate supplied fixtures/captures completely before any publication."""
    descriptor = -1
    try:
        pages = _pages(request, bodies)
        draft = CapitalDailyArchive("a" * 64, request, pages, received_at)
        encoded = canonical_json(_payload(draft.request, draft.pages, draft.received_at)).encode()
        _check(len(encoded) <= MAX_PAGE_BYTES)
        digest = hashlib.sha256(encoded).hexdigest()
        descriptor = _open_root(root, repository_root)
        for page, body in zip(pages, bodies, strict=True):
            _publish(descriptor, page.body_sha256 + ".capital-daily-body", body)
        _publish(descriptor, digest + ".capital-daily-manifest.json", encoded)
        return digest
    except (OSError, ValueError, TypeError, ArithmeticError, RecursionError):
        raise ValueError("capital_daily_archive_invalid") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def read_capital_daily_archive(
    root: Path,
    manifest_hash: str,
    *,
    repository_root: Path,
) -> CapitalDailyArchive:
    """Rehash and reparse private original bytes without opening credentials."""
    descriptor = -1
    try:
        _require_sha256_hex(manifest_hash, "manifest")
        descriptor = _open_root(root, repository_root)
        encoded = _read(descriptor, manifest_hash + ".capital-daily-manifest.json", MAX_PAGE_BYTES)
        _check(hashlib.sha256(encoded).hexdigest() == manifest_hash)
        wire = _mapping(
            _json(encoded, max_bytes=MAX_PAGE_BYTES, limits=_LIMITS),
            {
                "schema",
                "request",
                "request_hash",
                "receipts",
                "record_count",
                "pagination_complete",
                "source_qualified",
                "evidence_promotable",
            },
        )
        _check(wire["schema"] == _SCHEMA)
        _check(wire["source_qualified"] is False and wire["evidence_promotable"] is False)
        spec = _mapping(wire["request"], {"symbol", "start_ns", "end_ns", "limit"})
        request = CapitalDailyRequest(
            cast(Literal["SPY", "QQQ", "IWM", "SHY", "IEF"], spec["symbol"]),
            cast(int, spec["start_ns"]),
            cast(int, spec["end_ns"]),
            cast(int, spec["limit"]),
        )
        _check(wire["request_hash"] == request.request_hash)
        receipts = _array(wire["receipts"])
        _check(0 < len(receipts) <= MAX_PAGES)
        bodies: list[bytes] = []
        clocks: list[datetime] = []
        for index, entry in enumerate(receipts):
            row = _mapping(entry, {"page_index", "body_sha256", "received_at_utc"})
            _check(type(row["page_index"]) is int and row["page_index"] == index)
            digest = _require_sha256_hex(cast(str, row["body_sha256"]), "body")
            body = _read(descriptor, digest + ".capital-daily-body", MAX_PAGE_BYTES)
            _check(hashlib.sha256(body).hexdigest() == digest)
            bodies.append(body)
            _check(type(row["received_at_utc"]) is str and len(row["received_at_utc"]) <= 40)
            instant = require_utc(datetime.fromisoformat(cast(str, row["received_at_utc"])))
            _check(instant.isoformat() == row["received_at_utc"])
            clocks.append(instant)
        pages = _pages(request, tuple(bodies))
        value = CapitalDailyArchive(manifest_hash, request, pages, tuple(clocks))
        _check(canonical_json(_payload(request, pages, value.received_at)).encode() == encoded)
        return value
    except (OSError, ValueError, TypeError, ArithmeticError, RecursionError):
        raise ValueError("capital_daily_archive_invalid") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
