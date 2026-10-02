"""Receipt-verified latest-vintage SIP observations, not executable/original history.

Reads only the saved native capture. The credential path in its manifest is never
opened. Existing synthetic and qualified-source contracts are left unchanged.
"""

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.diagnostics.alpaca_capture import decode_capture_manifest
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.alpaca_native import (
    MAX_PAGE_BYTES,
    MAX_PAGES,
    AlpacaBarRecord,
    AlpacaQuoteRecord,
    AlpacaStockRequest,
    NativeRecord,
    parse_alpaca_page,
    validate_alpaca_pages,
)
from trading_bot.market_data.bundle_codec import _array, _digest, _integer, _json, _mapping
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.bundle_store import _open_root, _read
from trading_bot.market_data.recording import content_hash

_LIMITS = BundleLimits(1048576, 1048576, 1048576, 1000, 16)


class EtfNativeArchiveError(ValueError):
    def __init__(self) -> None:
        super().__init__("etf_native_archive_invalid")


def _check(condition: bool) -> None:
    if not condition:
        raise EtfNativeArchiveError()


def _receipt_time(value: object) -> datetime:
    if type(value) is not str or len(value) > 40:
        raise EtfNativeArchiveError()
    parsed = require_utc(datetime.fromisoformat(value))
    _check(parsed.isoformat() == value)
    return parsed


@dataclass(frozen=True, slots=True, repr=False)
class EtfNativeBarsArchive:
    manifest_hash: str
    request: AlpacaStockRequest
    receipt_hashes: tuple[str, ...]
    bars: tuple[AlpacaBarRecord, ...]
    captured_at: datetime
    source_kind: Literal["alpaca-sip-latest-vintage-v1"] = field(
        default="alpaca-sip-latest-vintage-v1", init=False
    )
    limitations: tuple[str, ...] = field(
        default=(
            "original_correction_timeline_waived",
            "retrieval_is_not_historical_availability",
            "session_control_and_action_coverage_unqualified",
            "daily_bars_not_executable_quotes",
            "later_corrections_may_change_signals",
        ),
        init=False,
    )
    source_qualified: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    @property
    def archive_hash(self) -> str:
        return content_hash({"schema": "etf-native-bars-archive-v1", "archive": self})


def read_etf_native_bars(
    root: Path, manifest_hash: str, *, repository_root: Path
) -> EtfNativeBarsArchive:
    request, receipts, records, _, captured_at = _read_etf_native(
        root, manifest_hash, repository_root=repository_root, kind="bars"
    )
    bars = tuple(row for row in records if type(row) is AlpacaBarRecord)
    _check(len(bars) == len(records))
    return EtfNativeBarsArchive(manifest_hash, request, receipts, bars, captured_at)


@dataclass(frozen=True, slots=True, repr=False)
class EtfNativeQuotesArchive:
    manifest_hash: str
    request: AlpacaStockRequest
    receipt_hashes: tuple[str, ...]
    quotes: tuple[AlpacaQuoteRecord, ...]
    captured_at: datetime
    source_kind: Literal["alpaca-sip-latest-vintage-quotes-v1"] = field(
        default="alpaca-sip-latest-vintage-quotes-v1", init=False
    )
    limitations: tuple[str, ...] = field(
        default=(
            "retrieval_is_not_historical_availability",
            "transport_completeness_is_not_quote_coverage",
            "response_order_is_not_exchange_sequence",
            "condition_interpretation_unverified",
            "size_conversion_unverified",
            "session_control_and_action_coverage_unqualified",
            "fractional_terms_unverified",
            "source_rights_unverified",
            "native_quotes_not_executable",
        ),
        init=False,
    )
    source_qualified: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)

    @property
    def archive_hash(self) -> str:
        return content_hash({"schema": "etf-native-quotes-archive-v1", "archive": self})


def read_etf_native_quotes(
    root: Path, manifest_hash: str, *, repository_root: Path
) -> EtfNativeQuotesArchive:
    """Retain native quote evidence without size conversion, filtering or execution."""
    request, receipts, records, _, captured_at = _read_etf_native(
        root, manifest_hash, repository_root=repository_root, kind="quotes"
    )
    quotes = tuple(row for row in records if type(row) is AlpacaQuoteRecord)
    _check(len(quotes) == len(records))
    return EtfNativeQuotesArchive(manifest_hash, request, receipts, quotes, captured_at)


@dataclass(frozen=True, slots=True, repr=False)
class EtfNativeQuotePagesArchive:
    """Full bounded capture intake, not a streaming store or executable dataset."""

    manifest_hash: str
    request: AlpacaStockRequest
    receipt_hashes: tuple[str, ...]
    pages: tuple[tuple[AlpacaQuoteRecord, ...], ...]
    captured_at: datetime
    source_kind: Literal["alpaca-sip-latest-vintage-quote-pages-v1"] = field(
        default="alpaca-sip-latest-vintage-quote-pages-v1", init=False
    )
    limitations: tuple[str, ...] = field(
        default=(
            "retrieval_is_not_historical_availability",
            "transport_completeness_is_not_quote_coverage",
            "response_order_is_not_exchange_sequence",
            "condition_interpretation_unverified",
            "size_conversion_unverified",
            "session_control_and_action_coverage_unqualified",
            "fractional_terms_unverified",
            "source_rights_unverified",
            "native_quotes_not_executable",
        ),
        init=False,
    )
    source_qualified: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_sha256_hex(self.manifest_hash, "manifest")
        _check(type(self.request) is AlpacaStockRequest)
        self.request.__post_init__()
        _check(self.request.kind == "quotes" and self.request.limit <= 1000)
        require_utc(self.captured_at)
        _check(type(self.pages) is tuple and 0 < len(self.pages) <= MAX_PAGES)
        _check(type(self.receipt_hashes) is tuple and len(self.receipt_hashes) == len(self.pages))
        _check(len(set(self.receipt_hashes)) == len(self.receipt_hashes))
        for receipt in self.receipt_hashes:
            _require_sha256_hex(receipt, "receipt")
        previous = None
        for page_index, page in enumerate(self.pages):
            _check(type(page) is tuple and len(page) <= self.request.limit)
            for row_index, row in enumerate(page):
                _check(type(row) is AlpacaQuoteRecord)
                row.__post_init__()
                _check((row.page_index, row.row_index) == (page_index, row_index))
                _check(self.request.start_ns <= row.timestamp_ns < self.request.end_ns)
                _check(previous is None or previous <= row.timestamp_ns)
                previous = row.timestamp_ns
        _check(self.record_count > 0)

    @property
    def record_count(self) -> int:
        return sum(len(page) for page in self.pages)

    @property
    def archive_hash(self) -> str:
        return content_hash({"schema": "etf-native-quote-pages-archive-v1", "archive": self})


def read_etf_native_quote_pages(
    root: Path, manifest_hash: str, *, repository_root: Path
) -> EtfNativeQuotePagesArchive:
    """Validate every receipt before returning all pages of a bounded capture.

    The separate legacy small reader retains its 10,000-row ceiling and identities.
    This intake supports the existing capture ceiling: 128 pages of at most 1,000
    rows and at most 1 MiB raw bytes each. It materializes the bounded archive; it
    is not a continuous collector, a partitioned bulk store or a throughput promise.
    """
    request, receipts, _, pages, captured_at = _read_etf_native(
        root, manifest_hash, repository_root=repository_root, kind="quotes", page_bounded=True
    )
    quotes = tuple(tuple(row for row in page if type(row) is AlpacaQuoteRecord) for page in pages)
    _check(all(len(source) == len(result) for source, result in zip(pages, quotes, strict=True)))
    return EtfNativeQuotePagesArchive(manifest_hash, request, receipts, quotes, captured_at)


def _read_etf_native(
    root: Path,
    manifest_hash: str,
    *,
    repository_root: Path,
    kind: Literal["bars", "quotes"],
    page_bounded: bool = False,
) -> tuple[
    AlpacaStockRequest,
    tuple[str, ...],
    tuple[NativeRecord, ...],
    tuple[tuple[NativeRecord, ...], ...],
    datetime,
]:
    """Shared private-FD and exact receipt chain validation for either native kind."""
    descriptor = -1
    try:
        _require_sha256_hex(manifest_hash, "manifest")
        descriptor = _open_root(root, repository_root)
        body = _read(descriptor, manifest_hash + ".capture-manifest.json", 16384)
        _check(hashlib.sha256(body).hexdigest() == manifest_hash)
        manifest = decode_capture_manifest(body)
        _check(manifest.request.kind == kind and manifest.quarantine_root == root)
        result = _mapping(
            _json(
                _read(descriptor, manifest_hash + ".capture-result.json", 16384),
                max_bytes=16384,
                limits=_LIMITS,
            ),
            {
                "schema",
                "manifest_sha256",
                "reason",
                "record_count",
                "pagination_complete",
                "receipt_sha256s",
                "source_qualified",
                "evidence_promotable",
            },
        )
        _check(
            result["schema"] == "alpaca-native-capture-result-v1"
            and result["manifest_sha256"] == manifest_hash
            and result["reason"] == "capture_transport_complete"
            and result["pagination_complete"] is True
            and result["source_qualified"] is False
            and result["evidence_promotable"] is False
        )
        receipts = tuple(_digest(item) for item in _array(result["receipt_sha256s"]))
        _check(0 < len(receipts) <= manifest.max_pages and len(set(receipts)) == len(receipts))
        pages = []
        previous = None
        token = None
        last_time = manifest.prepared_at
        for index, digest in enumerate(receipts):
            body = _read(descriptor, digest + ".capture-receipt.json", 16384)
            _check(hashlib.sha256(body).hexdigest() == digest)
            receipt = _mapping(
                _json(body, max_bytes=16384, limits=_LIMITS),
                {
                    "schema",
                    "manifest_sha256",
                    "request_sha256",
                    "page_index",
                    "query_sha256",
                    "previous_receipt_sha256",
                    "started_at",
                    "completed_at",
                    "status_code",
                    "body_sha256",
                    "body_bytes",
                    "reason",
                    "source_qualified",
                    "evidence_promotable",
                },
            )
            _check(
                receipt["schema"] == "alpaca-native-page-receipt-v1"
                and receipt["manifest_sha256"] == manifest_hash
                and receipt["request_sha256"] == manifest.request.request_hash
                and receipt["page_index"] == index
                and receipt["query_sha256"] == content_hash(manifest.request.query(token))
                and receipt["previous_receipt_sha256"] == previous
                and receipt["status_code"] == 200
                and receipt["reason"] == "page_retained"
                and receipt["source_qualified"] is False
                and receipt["evidence_promotable"] is False
            )
            started, completed = (
                _receipt_time(receipt["started_at"]),
                _receipt_time(receipt["completed_at"]),
            )
            _check(last_time <= started <= completed < manifest.expires_at)
            raw_hash = _digest(receipt["body_sha256"])
            raw = _read(descriptor, raw_hash + ".raw", MAX_PAGE_BYTES)
            _check(len(raw) == _integer(receipt["body_bytes"]))
            page = parse_alpaca_page(
                raw,
                request=manifest.request,
                expected_sha256=raw_hash,
                page_index=index,
                requested_page_token=token,
            )
            pages.append(page)
            previous, token, last_time = digest, page.next_page_token, completed
        assessed = validate_alpaca_pages(manifest.request, tuple(pages))
        _check(
            assessed.pagination_complete
            and assessed.record_count == _integer(result["record_count"])
        )
        records = tuple(row for page in pages for row in page.records)
        _check(not page_bounded or kind == "quotes")
        ceiling = manifest.max_pages * manifest.request.limit if page_bounded else 10000
        _check(len(records) == assessed.record_count and 0 < len(records) <= ceiling)
        return manifest.request, receipts, records, tuple(page.records for page in pages), last_time
    except (ValueError, TypeError, ArithmeticError, OSError, AttributeError):
        raise EtfNativeArchiveError() from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
