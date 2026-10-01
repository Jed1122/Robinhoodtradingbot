"""Receipt-verified, latest-vintage SIP bars; not executable or original history.

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
    AlpacaBarRecord,
    AlpacaStockRequest,
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
    descriptor = -1
    try:
        _require_sha256_hex(manifest_hash, "manifest")
        descriptor = _open_root(root, repository_root)
        body = _read(descriptor, manifest_hash + ".capture-manifest.json", 16384)
        _check(hashlib.sha256(body).hexdigest() == manifest_hash)
        manifest = decode_capture_manifest(body)
        _check(manifest.request.kind == "bars" and manifest.quarantine_root == root)
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
        bars = tuple(row for page in pages for row in page.records if type(row) is AlpacaBarRecord)
        _check(len(bars) == assessed.record_count and 0 < len(bars) <= 10000)
        return EtfNativeBarsArchive(manifest_hash, manifest.request, receipts, bars, last_time)
    except (ValueError, TypeError, ArithmeticError, OSError, AttributeError):
        raise EtfNativeArchiveError() from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
