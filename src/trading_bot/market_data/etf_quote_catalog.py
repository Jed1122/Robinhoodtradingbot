"""Receipt-bound private indexes and capture-bounded traversal, never execution."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from contextlib import ExitStack
from datetime import date, timedelta
from pathlib import Path
from typing import cast

from trading_bot.config import LoadedConfig
from trading_bot.diagnostics.alpaca_probe import _loaded_identity
from trading_bot.domain import ExecutionMode
from trading_bot.market_data.alpaca_native import MAX_PAGE_BYTES
from trading_bot.market_data.bundle_codec import _array, _json
from trading_bot.market_data.bundle_store import _subdirectory
from trading_bot.market_data.databento_bar_store import (
    _private_file,
    _private_root,
    _publish_checked,
    _read,
)
from trading_bot.market_data.etf_native_archive import (
    EtfNativeQuotePagesArchive,
    read_etf_native_quote_pages,
)
from trading_bot.market_data.etf_quote_catalog_models import (
    _LIMITS,
    DAY_NS,
    MAX_CATALOG_DAYS,
    MAX_DAY_CAPTURES,
    MAX_INDEX_BYTES,
    CatalogQuoteOccurrence,
    QuoteCaptureLocation,
    QuoteCaptureReference,
    QuoteCatalog,
    QuoteCatalogError,
    QuoteDayIndex,
    QuoteDayReference,
    catalog_hash,
    day_hash,
    decode_catalog,
    decode_day,
    digest,
    encode_catalog,
    encode_day,
    require,
    window,
)

_DAYS = "etf-native-quote-days-v1"
_CATALOGS = "etf-native-quote-catalogs-v1"
_ERRORS = (ValueError, TypeError, ArithmeticError, AttributeError, OSError)


def _metadata(parent: int, name: str) -> dict[str, object]:
    value = _json(_read(parent, name, 16384), max_bytes=16384, limits=_LIMITS)
    require(type(value) is dict)
    # Exact schemas and hashes are independently checked by the native reader.
    return cast(dict[str, object], value)


def _capture_files(parent: int, manifest_hash: str) -> None:
    """Check only explicitly receipt-listed files, before native decoding."""
    _read(parent, manifest_hash + ".capture-manifest.json", 16384)
    result = _metadata(parent, manifest_hash + ".capture-result.json")
    receipts = _array(result.get("receipt_sha256s"))
    require(0 < len(receipts) <= 128)
    for item in receipts:
        receipt = _metadata(parent, digest(item) + ".capture-receipt.json")
        with _private_file(parent, digest(receipt.get("body_sha256")) + ".raw", MAX_PAGE_BYTES):
            pass


def _same_directory(parent: int, path: Path, repository_root: Path) -> None:
    current = _private_root(path, repository_root)
    try:
        expected, observed = os.fstat(parent), os.fstat(current)
        require((expected.st_dev, expected.st_ino) == (observed.st_dev, observed.st_ino))
    finally:
        os.close(current)


def _capture(
    root: Path, location: QuoteCaptureLocation, repository_root: Path
) -> EtfNativeQuotePagesArchive:
    location.__post_init__()
    with ExitStack() as stack:
        parent = _private_root(root, repository_root)
        stack.callback(os.close, parent)
        for part in location.relative_path.split("/"):
            parent = _subdirectory(parent, part, create=False)
            stack.callback(os.close, parent)
        path = root / location.relative_path
        _same_directory(parent, path, repository_root)
        _capture_files(parent, location.manifest_hash)
        archive = read_etf_native_quote_pages(
            path, location.manifest_hash, repository_root=repository_root
        )
        _same_directory(parent, path, repository_root)
        _capture_files(parent, location.manifest_hash)
        return archive


def _reference(
    location: QuoteCaptureLocation, archive: EtfNativeQuotePagesArchive
) -> QuoteCaptureReference:
    return QuoteCaptureReference(
        location,
        archive.archive_hash,
        archive.request.start_ns,
        archive.request.end_ns,
        archive.record_count,
    )


def _day_ref(day: QuoteDayIndex) -> QuoteDayReference:
    return QuoteDayReference(
        day.day, day_hash(day), len(day.captures), sum(ref.record_count for ref in day.captures)
    )


def _read_day(parent: int, index_hash: str) -> QuoteDayIndex:
    body = _read(parent, digest(index_hash) + ".json", MAX_INDEX_BYTES)
    require(hashlib.sha256(body).hexdigest() == index_hash)
    value = decode_day(body)
    require(day_hash(value) == index_hash)
    return value


def publish_quote_day(
    root: Path, locations: tuple[QuoteCaptureLocation, ...], *, repository_root: Path
) -> QuoteDayReference:
    """Bind complete native receipts; does not certify session or tick coverage."""
    try:
        require(type(locations) is tuple and 0 < len(locations) <= MAX_DAY_CAPTURES)
        refs = []
        for location in locations:
            require(type(location) is QuoteCaptureLocation)
            archive = _capture(root, location, repository_root)
            refs.append(_reference(location, archive))
            del archive
        refs.sort(key=lambda ref: ref.start_ns)
        day = date(1970, 1, 1) + timedelta(days=refs[0].start_ns // DAY_NS)
        value = QuoteDayIndex(day, tuple(refs))
        reference = _day_ref(value)
        with ExitStack() as stack:
            parent = _private_root(root, repository_root)
            stack.callback(os.close, parent)
            directory = _subdirectory(parent, _DAYS, create=True)
            stack.callback(os.close, directory)
            _publish_checked(directory, reference.index_hash + ".json", encode_day(value))
        return reference
    except _ERRORS:
        raise QuoteCatalogError() from None


def publish_quote_catalog(
    root: Path,
    day_hashes: tuple[str, ...],
    *,
    loaded: LoadedConfig,
    code_revision: str,
    repository_root: Path,
) -> str:
    """Code identity is a declaration, not operator/release/runtime attestation."""
    try:
        _loaded_identity(loaded)
        require(
            loaded.config.mode is ExecutionMode.BACKTEST and not loaded.config.live_trading_enabled
        )
        require(type(day_hashes) is tuple and 0 < len(day_hashes) <= MAX_CATALOG_DAYS)
        with ExitStack() as stack:
            parent = _private_root(root, repository_root)
            stack.callback(os.close, parent)
            days_dir = _subdirectory(parent, _DAYS, create=False)
            stack.callback(os.close, days_dir)
            days = tuple(
                sorted(
                    (_day_ref(_read_day(days_dir, item)) for item in day_hashes),
                    key=lambda ref: ref.day,
                )
            )
            value = QuoteCatalog(code_revision, str(loaded.config_hash), days)
            result = catalog_hash(value)
            directory = _subdirectory(parent, _CATALOGS, create=True)
            stack.callback(os.close, directory)
            _publish_checked(directory, result + ".json", encode_catalog(value))
            return result
    except _ERRORS:
        raise QuoteCatalogError() from None


def read_quote_catalog(root: Path, catalog_hash: str, *, repository_root: Path) -> QuoteCatalog:
    """Rehash every bound metadata index without opening any raw capture."""
    try:
        with ExitStack() as stack:
            parent = _private_root(root, repository_root)
            stack.callback(os.close, parent)
            directory = _subdirectory(parent, _CATALOGS, create=False)
            stack.callback(os.close, directory)
            body = _read(directory, digest(catalog_hash) + ".json", MAX_INDEX_BYTES)
            require(hashlib.sha256(body).hexdigest() == catalog_hash)
            value = decode_catalog(body)
            require(encode_catalog(value) == body)
            days_dir = _subdirectory(parent, _DAYS, create=False)
            stack.callback(os.close, days_dir)
            for reference in value.days:
                require(_day_ref(_read_day(days_dir, reference.index_hash)) == reference)
            return value
    except _ERRORS:
        raise QuoteCatalogError() from None


def _selected(
    root: Path, catalog: QuoteCatalog, start_ns: int, end_ns: int, repository_root: Path
) -> Iterator[QuoteCaptureReference]:
    with ExitStack() as stack:
        parent = _private_root(root, repository_root)
        stack.callback(os.close, parent)
        directory = _subdirectory(parent, _DAYS, create=False)
        stack.callback(os.close, directory)
        for reference in catalog.days:
            day_start = (reference.day - date(1970, 1, 1)).days * DAY_NS
            if day_start >= end_ns or day_start + DAY_NS <= start_ns:
                continue
            day = _read_day(directory, reference.index_hash)
            require(_day_ref(day) == reference)
            for ref in day.captures:
                if ref.start_ns < end_ns and start_ns < ref.end_ns:
                    yield ref


def iter_catalog_quotes(
    root: Path, catalog_hash: str, *, start_ns: int, end_ns: int, repository_root: Path
) -> Iterator[CatalogQuoteOccurrence]:
    """Validate selected captures before yield, then reread one bounded capture.

    A later external mutation may raise after a prefix was yielded. Only normal
    exhaustion completes traversal; no economics or completion receipt is issued.
    """
    try:
        window(start_ns, end_ns)
        catalog = read_quote_catalog(root, catalog_hash, repository_root=repository_root)
        for ref in _selected(root, catalog, start_ns, end_ns, repository_root):
            archive = _capture(root, ref.location, repository_root)
            require(_reference(ref.location, archive) == ref)
            del archive
        for ref in _selected(root, catalog, start_ns, end_ns, repository_root):
            archive = _capture(root, ref.location, repository_root)
            require(_reference(ref.location, archive) == ref)
            for page in archive.pages:
                for record in page:
                    if start_ns <= record.timestamp_ns < end_ns:
                        yield CatalogQuoteOccurrence(ref.location, ref.archive_hash, record)
            del archive
    except _ERRORS:
        raise QuoteCatalogError() from None
