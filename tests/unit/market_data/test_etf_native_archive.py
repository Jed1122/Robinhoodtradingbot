"""Strict receipt-bound latest-vintage reads; never original-history qualification."""

import hashlib
import importlib
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from tests.unit.diagnostics.test_alpaca_capture import (
    api as capture_api,
)
from tests.unit.diagnostics.test_alpaca_capture import (
    body,
    run,
)
from tests.unit.diagnostics.test_alpaca_capture import (
    loaded as loaded,
)
from tests.unit.diagnostics.test_alpaca_capture import (
    manifest as manifest,
)
from tests.unit.diagnostics.test_alpaca_capture import (
    ready as ready,
)
from trading_bot.market_data.alpaca_native import (
    AlpacaStockRequest,
    parse_alpaca_page,
    parse_timestamp_ns,
)
from trading_bot.market_data.recording import content_hash


def api():
    try:
        return importlib.import_module("trading_bot.market_data.etf_native_archive")
    except ModuleNotFoundError:
        pytest.fail("Receipt-bound ETF latest-vintage archive reader is missing")


async def capture(ready, loaded, monkeypatch):
    async def send(self, request, **kwargs):
        return httpx.Response(
            200, stream=httpx.ByteStream(body()), headers={"content-type": "application/json"}
        )

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    result = await run(ready, loaded)
    assert result.pagination_complete
    return capture_api().capture_manifest_sha256(ready), result


async def test_native_receipts_can_be_read_without_broker_or_credential_access(
    ready, loaded, monkeypatch
):
    digest, _ = await capture(ready, loaded, monkeypatch)
    ready.credential_file.unlink()
    archive = api().read_etf_native_bars(
        ready.quarantine_root, digest, repository_root=ready.repository_root
    )
    assert len(archive.bars) == 1
    assert archive.bars[0].close == 201
    assert archive.bars[0].publication_at_ns is None
    assert archive.source_kind == "alpaca-sip-latest-vintage-v1"
    assert not archive.source_qualified and not archive.evidence_promotable
    assert "original_correction_timeline_waived" in archive.limitations


async def test_changed_raw_receipt_truncation_and_symlink_deny(ready, loaded, monkeypatch):
    digest, result = await capture(ready, loaded, monkeypatch)
    receipt_path = ready.quarantine_root / (result.receipt_sha256s[0] + ".capture-receipt.json")
    original = receipt_path.read_bytes()
    receipt_path.write_bytes(original + b" ")
    with pytest.raises(ValueError, match="etf_native_archive_invalid"):
        api().read_etf_native_bars(
            ready.quarantine_root, digest, repository_root=ready.repository_root
        )
    receipt_path.write_bytes(original)
    target = ready.quarantine_root / "other.json"
    receipt_path.rename(target)
    receipt_path.symlink_to(target)
    with pytest.raises(ValueError, match="etf_native_archive_invalid"):
        api().read_etf_native_bars(
            ready.quarantine_root, digest, repository_root=ready.repository_root
        )


async def test_archive_identity_binds_manifest_and_rows(ready, loaded, monkeypatch):
    digest, _ = await capture(ready, loaded, monkeypatch)
    archive = api().read_etf_native_bars(
        ready.quarantine_root, digest, repository_root=ready.repository_root
    )
    changed = replace(archive, bars=(replace(archive.bars[0], close=archive.bars[0].open),))
    assert archive.archive_hash != changed.archive_hash


@pytest.fixture
def quote_manifest(manifest):
    return replace(
        manifest,
        request=AlpacaStockRequest(
            "quotes",
            parse_timestamp_ns("2016-01-04T00:00:00Z"),
            parse_timestamp_ns("2016-01-05T00:00:00Z"),
        ),
        max_pages=11,
    )


def quote_row(stamp="2016-01-04T14:30:00.123456789Z", **changes):
    return {
        "t": stamp,
        "bp": 200.125,
        "ap": 200.25,
        "bs": 3,
        "as": 7,
        "bx": "P",
        "ax": "N",
        "c": ["R", "Y"],
        "z": "B",
    } | changes


def quote_body(rows=None, token=None):
    return json.dumps(
        {
            "symbol": "SPY",
            "quotes": [quote_row()] if rows is None else rows,
            "next_page_token": token,
        },
        separators=(",", ":"),
    ).encode()


def retain(manifest, payloads, *, receipt_changes=None, result_changes=None):
    """Invent a complete retained capture without credentials or a transport call."""
    root = manifest.quarantine_root
    root.mkdir(mode=0o700)

    def save(body, suffix):
        digest = hashlib.sha256(body).hexdigest()
        target = root / (digest + suffix)
        target.write_bytes(body)
        target.chmod(0o600)
        return digest

    digest = save(capture_api().encode_capture_manifest(manifest), ".capture-manifest.json")
    previous, token, count = None, None, 0
    receipts = []
    for index, raw in enumerate(payloads):
        wire = json.loads(raw)
        raw_hash = save(raw, ".raw")
        receipt = {
            "schema": "alpaca-native-page-receipt-v1",
            "manifest_sha256": digest,
            "request_sha256": manifest.request.request_hash,
            "page_index": index,
            "query_sha256": content_hash(manifest.request.query(token)),
            "previous_receipt_sha256": previous,
            "started_at": manifest.prepared_at.isoformat(),
            "completed_at": manifest.prepared_at.isoformat(),
            "status_code": 200,
            "body_sha256": raw_hash,
            "body_bytes": len(raw),
            "reason": "page_retained",
            "source_qualified": False,
            "evidence_promotable": False,
        } | (receipt_changes or {}).get(index, {})
        previous = save(json.dumps(receipt).encode(), ".capture-receipt.json")
        receipts.append(previous)
        token = wire["next_page_token"]
        count += len(wire[manifest.request.kind])
    result = {
        "schema": "alpaca-native-capture-result-v1",
        "manifest_sha256": digest,
        "reason": "capture_transport_complete",
        "record_count": count,
        "pagination_complete": True,
        "receipt_sha256s": receipts,
        "source_qualified": False,
        "evidence_promotable": False,
    } | (result_changes or {})
    target = root / (digest + ".capture-result.json")
    target.write_bytes(json.dumps(result).encode())
    target.chmod(0o600)
    return digest, receipts


def read_quotes(manifest, digest):
    reader = getattr(api(), "read_etf_native_quotes", None)
    assert callable(reader), "Receipt-bound native quote archive reader is missing"
    return reader(manifest.quarantine_root, digest, repository_root=manifest.repository_root)


def test_quotes_preserve_nanoseconds_same_time_order_raw_sizes_and_conditions(
    quote_manifest, monkeypatch
):
    digest, receipts = retain(
        quote_manifest,
        [
            quote_body([quote_row(), quote_row()], token="next"),
            quote_body([quote_row(bs=9), quote_row("2016-01-04T14:30:00.123456790Z")]),
        ],
        receipt_changes={
            1: {"completed_at": (quote_manifest.prepared_at + timedelta(seconds=1)).isoformat()}
        },
    )

    def forbidden(*args, **kwargs):
        pytest.fail("archive read reached credentials or transport")

    original_open = os.open

    def guarded_open(path, *args, **kwargs):
        assert os.fspath(path) not in (
            str(quote_manifest.credential_file),
            str(quote_manifest.credential_file.parent),
            "credentials",
            "key.json",
        ), "credential path was opened"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(capture_api(), "read_probe_credential", forbidden)
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    monkeypatch.setattr(os, "open", guarded_open)
    archive = read_quotes(quote_manifest, digest)
    assert archive.manifest_hash == digest
    assert archive.receipt_hashes == tuple(receipts)
    assert archive.request == quote_manifest.request
    assert archive.captured_at == datetime(2026, 10, 1, 12, 0, 1, tzinfo=UTC)
    assert [(r.page_index, r.row_index) for r in archive.quotes] == [
        (0, 0),
        (0, 1),
        (1, 0),
        (1, 1),
    ]
    assert [r.timestamp_ns for r in archive.quotes] == [
        1451917800123456789,
        1451917800123456789,
        1451917800123456789,
        1451917800123456790,
    ]
    assert len({r.record_hash for r in archive.quotes}) == 4
    assert [(r.bid_size, r.ask_size) for r in archive.quotes] == [(3, 7), (3, 7), (9, 7), (3, 7)]
    assert all(r.conditions == ("R", "Y") for r in archive.quotes)
    assert all((r.bid, r.ask) == (Decimal("200.125"), Decimal("200.25")) for r in archive.quotes)
    assert all((r.bid_exchange, r.ask_exchange, r.tape) == ("P", "N", "B") for r in archive.quotes)
    assert all(r.publication_at_ns is None and not r.executable for r in archive.quotes)
    assert archive.source_kind == "alpaca-sip-latest-vintage-quotes-v1"
    assert not archive.source_qualified and not archive.evidence_promotable
    assert archive.execution_enabled is False
    assert "retrieval_is_not_historical_availability" in archive.limitations
    assert "size_conversion_unverified" in archive.limitations
    assert "response_order_is_not_exchange_sequence" in archive.limitations
    assert not quote_manifest.credential_file.parent.exists()


@pytest.mark.parametrize(
    "day,stamp,unit",
    [
        ("2025-10-31", "2025-10-31T14:30:00Z", "round_lots"),
        ("2025-11-03", "2025-11-03T14:30:00Z", "transition_unverified"),
        ("2025-11-04", "2025-11-04T14:30:00Z", "shares"),
    ],
)
def test_quotes_keep_size_era_quarantined_without_conversion(quote_manifest, day, stamp, unit):
    start = parse_timestamp_ns(day + "T00:00:00Z")
    manifest = replace(
        quote_manifest, request=AlpacaStockRequest("quotes", start, start + 86400 * 10**9)
    )
    digest, _ = retain(manifest, [quote_body([quote_row(stamp, bs=2, **{"as": 5})])])
    archive = read_quotes(manifest, digest)
    quote = archive.quotes[0]
    assert (quote.bid_size, quote.ask_size, quote.size_unit) == (2, 5, unit)
    assert "size_conversion_unverified" in quote.observation_reasons
    assert not quote.executable and not archive.execution_enabled


@pytest.mark.parametrize(
    "changes",
    [
        {"request_sha256": "1" * 64},
        {"query_sha256": "1" * 64},
        {"previous_receipt_sha256": "1" * 64},
        {"page_index": 2},
        {"body_bytes": 1},
        {"body_sha256": "1" * 64},
        {"status_code": 206},
        {"reason": "capture_native_invalid"},
        {"source_qualified": True},
        {"evidence_promotable": True},
        {"manifest_sha256": "1" * 64},
        {"completed_at": "2026-10-01T12:30:00+00:00"},
    ],
)
def test_quotes_reject_rehashed_receipt_semantic_changes(quote_manifest, changes):
    digest, _ = retain(quote_manifest, [quote_body()], receipt_changes={0: changes})
    with pytest.raises(ValueError, match="etf_native_archive_invalid"):
        read_quotes(quote_manifest, digest)


@pytest.mark.parametrize(
    "changes",
    [
        {"record_count": 2},
        {"record_count": True},
        {"pagination_complete": False},
        {"reason": "capture_page_limit"},
        {"source_qualified": True},
        {"evidence_promotable": True},
        {"manifest_sha256": "1" * 64},
        {"receipt_sha256s": []},
    ],
)
def test_quotes_reject_inconsistent_result_claims(quote_manifest, changes):
    digest, _ = retain(quote_manifest, [quote_body()], result_changes=changes)
    with pytest.raises(ValueError, match="etf_native_archive_invalid"):
        read_quotes(quote_manifest, digest)


@pytest.mark.parametrize(
    "payloads",
    [
        [quote_body(token="missing-next-page")],
        [quote_body([])],
        [quote_body(token="again"), quote_body(token="again")],
        [quote_body(), quote_body()],
        [quote_body(token="next"), quote_body([quote_row("2016-01-04T14:29:59Z")])],
    ],
)
def test_quotes_deny_partial_empty_or_disordered_capture_despite_complete_claim(
    quote_manifest, payloads
):
    digest, _ = retain(quote_manifest, payloads)
    with pytest.raises(ValueError, match="etf_native_archive_invalid"):
        read_quotes(quote_manifest, digest)


@pytest.mark.parametrize("artifact", ["manifest", "receipt", "raw", "result"])
@pytest.mark.parametrize("damage", ["truncate", "symlink", "public"])
def test_quotes_require_intact_private_nonsymlink_capture_files(quote_manifest, artifact, damage):
    digest, receipts = retain(quote_manifest, [quote_body()])
    paths = {
        "manifest": quote_manifest.quarantine_root / (digest + ".capture-manifest.json"),
        "receipt": quote_manifest.quarantine_root / (receipts[0] + ".capture-receipt.json"),
        "raw": quote_manifest.quarantine_root / (hashlib.sha256(quote_body()).hexdigest() + ".raw"),
        "result": quote_manifest.quarantine_root / (digest + ".capture-result.json"),
    }
    target = paths[artifact]
    if damage == "truncate":
        target.write_bytes(target.read_bytes()[:-1])
    elif damage == "symlink":
        retained = target.with_suffix(".retained")
        target.rename(retained)
        target.symlink_to(retained)
    else:
        target.chmod(0o644)
    with pytest.raises(ValueError, match="etf_native_archive_invalid"):
        read_quotes(quote_manifest, digest)


@pytest.mark.parametrize("count", [10000, 10001])
def test_quotes_accept_exact_row_cap_and_never_truncate_excess(quote_manifest, count):
    rows = [quote_row()] * count
    payloads = [
        quote_body(rows[index : index + 1000], str(index + 1000) if index + 1000 < count else None)
        for index in range(0, count, 1000)
    ]
    digest, _ = retain(quote_manifest, payloads)
    if count == 10000:
        assert len(read_quotes(quote_manifest, digest).quotes) == 10000
    else:
        with pytest.raises(ValueError, match="etf_native_archive_invalid"):
            read_quotes(quote_manifest, digest)


def test_quotes_refuse_bar_manifest_and_bars_refuse_quote_manifest(manifest, quote_manifest):
    digest, _ = retain(manifest, [body()])
    with pytest.raises(ValueError, match="etf_native_archive_invalid"):
        read_quotes(manifest, digest)
    # Use a separate quarantine root for the second independently retained capture.
    quote_manifest = replace(
        quote_manifest, quarantine_root=manifest.quarantine_root.parent / "quotes"
    )
    digest, _ = retain(quote_manifest, [quote_body()])
    with pytest.raises(ValueError, match="etf_native_archive_invalid"):
        api().read_etf_native_bars(
            quote_manifest.quarantine_root, digest, repository_root=quote_manifest.repository_root
        )


def test_quote_identity_binds_schema_manifest_request_receipts_rows_and_capture_time(
    quote_manifest,
):
    digest, _ = retain(quote_manifest, [quote_body()])
    archive = read_quotes(quote_manifest, digest)
    assert archive.archive_hash == content_hash(
        {"schema": "etf-native-quotes-archive-v1", "archive": archive}
    )
    changes = [
        {"manifest_hash": "1" * 64},
        {"receipt_hashes": ("1" * 64,)},
        {"quotes": (replace(archive.quotes[0], bid_size=4),)},
        {"request": replace(archive.request, limit=999)},
        {"captured_at": archive.captured_at.replace(second=1)},
    ]
    assert all(
        replace(archive, **change).archive_hash != archive.archive_hash for change in changes
    )


def test_legacy_bar_archive_retains_pre_quote_reader_hash():
    request = AlpacaStockRequest("bars", 1451606400000000000, 1452038400000000000)
    raw = body()
    row = parse_alpaca_page(
        raw, request=request, expected_sha256=hashlib.sha256(raw).hexdigest()
    ).records[0]
    archive = api().EtfNativeBarsArchive(
        "a" * 64, request, ("b" * 64,), (row,), datetime(2026, 10, 1, 12, tzinfo=UTC)
    )
    # Golden value from base revision 64335e7, before the shared-reader refactor.
    assert (
        archive.archive_hash == "171c027e2b0b048925db93664ead13c66e436e459c3fc9b6de57fcb3c7a8b580"
    )


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"bp": 0}, "inactive_bid"),
        ({"ap": 0}, "inactive_ask"),
        ({"bp": 201}, "crossed_quote"),
        ({"bp": 200.25}, "locked_quote"),
        ({"c": []}, "condition_interpretation_unverified"),
    ],
)
def test_quotes_preserve_unusable_observations_without_filtering(quote_manifest, changes, reason):
    digest, _ = retain(quote_manifest, [quote_body([quote_row(**changes)])])
    archive = read_quotes(quote_manifest, digest)
    assert len(archive.quotes) == 1
    assert reason in archive.quotes[0].observation_reasons
    assert not archive.quotes[0].executable and not archive.execution_enabled


def test_empty_terminal_page_does_not_invent_or_drop_prior_quotes(quote_manifest):
    digest, receipts = retain(quote_manifest, [quote_body(token="last"), quote_body([])])
    archive = read_quotes(quote_manifest, digest)
    assert len(archive.quotes) == 1 and len(archive.receipt_hashes) == 2
    assert archive.receipt_hashes == tuple(receipts)
    assert "transport_completeness_is_not_quote_coverage" in archive.limitations


def test_valid_json_raw_tampering_with_unchanged_length_still_denies(quote_manifest):
    digest, _ = retain(quote_manifest, [quote_body()])
    target = quote_manifest.quarantine_root / (hashlib.sha256(quote_body()).hexdigest() + ".raw")
    target.write_bytes(quote_body().replace(b'"bs":3', b'"bs":4'))
    with pytest.raises(ValueError, match="etf_native_archive_invalid"):
        read_quotes(quote_manifest, digest)


def test_result_cannot_duplicate_a_receipt(quote_manifest):
    digest, receipts = retain(quote_manifest, [quote_body()])
    target = quote_manifest.quarantine_root / (digest + ".capture-result.json")
    wire = json.loads(target.read_bytes())
    wire["receipt_sha256s"] = receipts * 2
    target.write_bytes(json.dumps(wire).encode())
    with pytest.raises(ValueError, match="etf_native_archive_invalid"):
        read_quotes(quote_manifest, digest)


def test_quote_reader_reuses_private_root_and_repository_boundary(quote_manifest):
    digest, _ = retain(quote_manifest, [quote_body()])
    with pytest.raises(ValueError, match="etf_native_archive_invalid"):
        api().read_etf_native_quotes(
            quote_manifest.quarantine_root,
            digest,
            repository_root=quote_manifest.quarantine_root,
        )
    quote_manifest.quarantine_root.chmod(0o755)
    with pytest.raises(ValueError, match="etf_native_archive_invalid"):
        read_quotes(quote_manifest, digest)
