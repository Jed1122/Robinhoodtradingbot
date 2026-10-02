"""Page-bounded native intake cannot truncate or bless market observations."""

import hashlib
from dataclasses import replace

import pytest

from tests.unit.market_data.test_etf_native_archive import (
    api,
    quote_body,
    quote_row,
    read_quotes,
    retain,
)
from tests.unit.market_data.test_etf_native_archive import (
    loaded as loaded,
)
from tests.unit.market_data.test_etf_native_archive import (
    manifest as manifest,
)
from tests.unit.market_data.test_etf_native_archive import (
    quote_manifest as quote_manifest,
)


def read_pages(manifest, digest):
    reader = getattr(api(), "read_etf_native_quote_pages", None)
    assert callable(reader), "Page-bounded native quote intake is missing"
    return reader(manifest.quarantine_root, digest, repository_root=manifest.repository_root)


def payloads(count):
    row = quote_row()
    return [
        quote_body(
            [row] * min(1000, count - index),
            str(index + 1000) if index + 1000 < count else None,
        )
        for index in range(0, count, 1000)
    ]


def test_full_capture_batches_keep_every_row_without_relaxing_legacy_reader(quote_manifest):
    digest, receipts = retain(quote_manifest, payloads(10001))
    with pytest.raises(ValueError, match="etf_native_archive_invalid"):
        read_quotes(quote_manifest, digest)
    archive = read_pages(quote_manifest, digest)
    assert tuple(len(page) for page in archive.pages) == (1000,) * 10 + (1,)
    assert archive.record_count == 10001
    assert archive.receipt_hashes == tuple(receipts)
    assert archive.pages[0][0].page_index == 0
    assert archive.pages[-1][0].page_index == 10
    assert archive.pages[-1][0].row_index == 0
    assert archive.pages[-1][0].timestamp_ns == 1451917800123456789
    assert archive.pages[-1][0].bid_size == 3
    assert archive.pages[-1][0].ask_size == 7
    assert archive.pages[-1][0].conditions == ("R", "Y")
    assert not archive.pages[-1][0].executable
    assert not archive.source_qualified and not archive.evidence_promotable
    assert not archive.execution_enabled
    assert "response_order_is_not_exchange_sequence" in archive.limitations
    assert "native_quotes_not_executable" in archive.limitations
    assert not quote_manifest.credential_file.parent.exists()


def test_exact_capture_ceiling_is_retained_not_truncated(quote_manifest):
    scope = replace(quote_manifest, max_pages=128)
    digest, _ = retain(scope, payloads(128000))
    archive = read_pages(scope, digest)
    assert archive.record_count == 128000
    assert len(archive.pages) == 128
    assert all(len(page) == 1000 for page in archive.pages)
    assert (archive.pages[-1][-1].page_index, archive.pages[-1][-1].row_index) == (127, 999)


def test_page_ceiling_denies_a_rehashed_result_with_excess_receipts(quote_manifest):
    scope = replace(quote_manifest, max_pages=10)
    digest, _ = retain(scope, payloads(10001))
    with pytest.raises(ValueError, match="etf_native_archive_invalid"):
        read_pages(scope, digest)


def test_last_page_corruption_returns_no_partial_archive(quote_manifest):
    bodies = payloads(10001)
    digest, _ = retain(quote_manifest, bodies)
    last = quote_manifest.quarantine_root / (hashlib.sha256(bodies[-1]).hexdigest() + ".raw")
    last.write_bytes(last.read_bytes().replace(b'"bs":3', b'"bs":4'))
    with pytest.raises(ValueError, match="etf_native_archive_invalid"):
        read_pages(quote_manifest, digest)


def test_empty_terminal_batch_preserves_transport_boundary(quote_manifest):
    digest, _ = retain(quote_manifest, [quote_body(token="last"), quote_body([])])
    archive = read_pages(quote_manifest, digest)
    assert tuple(len(page) for page in archive.pages) == (1, 0)
    assert archive.record_count == 1


@pytest.mark.parametrize(
    "bodies",
    [
        [quote_body(token="missing")],
        [quote_body(token="again"), quote_body(token="again")],
        [quote_body(), quote_body()],
        [quote_body(token="next"), quote_body([quote_row("2016-01-04T14:29:59Z")])],
    ],
)
def test_unfinished_repeated_or_backward_transport_never_becomes_batch_input(
    quote_manifest, bodies
):
    digest, _ = retain(quote_manifest, bodies)
    with pytest.raises(ValueError, match="etf_native_archive_invalid"):
        read_pages(quote_manifest, digest)


def test_batch_identity_binds_rows_and_the_new_schema(quote_manifest):
    digest, _ = retain(quote_manifest, [quote_body()])
    archive = read_pages(quote_manifest, digest)
    assert archive.archive_hash != read_quotes(quote_manifest, digest).archive_hash
    changed = replace(archive, pages=((replace(archive.pages[0][0], bid_size=4),),))
    assert changed.archive_hash != archive.archive_hash


def test_coverage_accepts_every_native_page_but_cannot_grant_execution(quote_manifest):
    from tests.unit.research.test_etf_execution_coverage import inputs
    from trading_bot.research.etf_execution_coverage import audit_etf_execution_coverage

    digest, _ = retain(quote_manifest, payloads(10001))
    archive = read_pages(quote_manifest, digest)
    bars, calendar = inputs()
    report = audit_etf_execution_coverage(bars, (archive,), calendar)
    assert report.total_quote_observations == 10001
    assert report.quote_archive_hashes == (archive.archive_hash,)
    assert report.development_sessions_after750 == 1
    assert report.quoted_session_count == 0
    assert report.fully_requested_session_count == 0
    assert report.status == "BLOCKED_INPUTS"
    assert not report.source_qualified and not report.execution_enabled
    assert not report.evidence_promotable
