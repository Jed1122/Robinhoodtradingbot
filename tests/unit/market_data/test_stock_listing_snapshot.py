"""Fictional Alpha Vantage CSV; no acquisition, credentials, or security selection."""

import hashlib
import json
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime

import pytest

from trading_bot.market_data.stock_listing_snapshot import (
    StockListingRequest,
    StockListingSnapshotError,
    assess_stock_listing_snapshot,
    parse_stock_listing_snapshot,
    select_stock_history_panel,
)

HEADER = "symbol,name,exchange,assetType,ipoDate,delistingDate,status\r\n"
RECEIVED = datetime(2026, 10, 26, 1, tzinfo=UTC)
AS_OF = datetime(2026, 10, 26, 2, tzinfo=UTC)
WHEN = date(2024, 1, 1)


def request(state="active"):
    return StockListingRequest(WHEN, state)


def parse(text, *, req=None, received=RECEIVED):
    body = text.encode() if isinstance(text, str) else text
    return parse_stock_listing_snapshot(
        body,
        expected_sha256=hashlib.sha256(body).hexdigest(),
        request=request() if req is None else req,
        received_at=received,
    )


def test_original_csv_missingness_and_source_labels_are_preserved_without_selection():
    text = HEADER + 'ODD-W,"Company, Inc.  ",NASDAQ,Stock,2020-01-02,null,Active\r\n'
    text += "FUND,,NYSE,ETF,,null,Active\r\n"
    snapshot = parse(text)
    result = assess_stock_listing_snapshot(snapshot, as_of=AS_OF)
    assert snapshot.original_csv == text.encode()
    assert snapshot.rows[0].symbol == "ODD-W"
    assert snapshot.rows[0].name == "Company, Inc.  "
    assert snapshot.rows[0].asset_type == "Stock"
    assert snapshot.rows[1].name == "" and snapshot.rows[1].ipo_date is None
    assert snapshot.rows[0].delisting_date_raw == "null"
    assert snapshot.available_at == RECEIVED and snapshot.request.requested_date == WHEN
    assert result.row_count == result.distinct_symbol_count == 2
    assert result.asset_type_counts == (("ETF", 1), ("Stock", 1))
    assert dict(result.empty_field_counts)["name"] == 1
    assert result.date_missingness == (("ipoDate", 1, 0), ("delistingDate", 0, 2))
    assert "common_stock_selection" in result.blocked_uses
    assert "historical_vintage_strategy" in result.blocked_uses
    assert snapshot.rows[0].permanent_security_id is None
    assert snapshot.rows[0].common_stock_classification is None
    for obj in (snapshot, result):
        for name in (
            "qualified",
            "source_qualified",
            "strategy_qualified",
            "investment_eligible",
            "trading_enabled",
            "live_authorized",
            "authenticated",
            "historical_vintage_verified",
            "is_original_upstream_wire",
        ):
            assert getattr(obj, name) is False
    with pytest.raises(FrozenInstanceError):
        snapshot.rows = ()


def test_duplicate_groups_keep_all_rows_and_distinguish_exact_from_conflicting():
    text = HEADER + "A,First,NYSE,Stock,2000-01-01,null,Active\n" * 2
    text += "B,Old,NYSE,Stock,1999-01-01,null,Active\n"
    text += "B,New,NASDAQ,ETF,2020-01-01,null,Active\n"
    text += "B,New,NASDAQ,ETF,2020-01-01,null,Active\n"
    snapshot = parse(text)
    result = assess_stock_listing_snapshot(snapshot, as_of=AS_OF)
    assert result.row_count == len(snapshot.rows) == 5
    assert result.distinct_symbol_count == 2
    assert result.duplicate_extra_rows == 3 and result.duplicate_row_count == 5
    exact, conflict = result.duplicate_groups
    assert (exact.symbol, exact.row_indices, exact.kind, exact.differing_fields) == (
        "A",
        (0, 1),
        "exact",
        (),
    )
    assert (conflict.symbol, conflict.row_indices, conflict.kind) == ("B", (2, 3, 4), "conflicting")
    assert conflict.differing_fields == ("name", "exchange", "assetType", "ipoDate")
    assert "unambiguous_symbol_membership" in result.blocked_uses


def test_lifecycle_contradictions_are_retained_and_flagged_without_silent_filtering():
    text = HEADER + "F,Future,NYSE,Stock,2025-01-01,null,Active\n"
    text += "D,Past,NYSE,Stock,2000-01-01,2020-01-01,Active\n"
    text += "I,Inverted,NYSE,Stock,2020-01-01,2019-01-01,Delisted\n"
    result = assess_stock_listing_snapshot(parse(text), as_of=AS_OF)
    assert result.row_count == 3
    assert result.future_ipo_row_indices == (0,)
    assert result.delisting_before_requested_row_indices == (1, 2)
    assert result.inverted_lifecycle_row_indices == (2,)
    assert result.status_mismatch_row_indices == (2,)
    assert "requested_date_membership" in result.blocked_uses


def test_empty_snapshot_and_unknown_native_labels_have_explicit_quality_outcomes():
    empty = assess_stock_listing_snapshot(parse(HEADER), as_of=AS_OF)
    assert empty.row_count == 0 and empty.reason_codes == ("empty_snapshot",)
    text = HEADER + "X,,OTHER,Unreviewed,null,,Unreviewed\n"
    snapshot = parse(text)
    quality = assess_stock_listing_snapshot(snapshot, as_of=AS_OF)
    assert snapshot.rows[0].asset_type == "Unreviewed"
    assert quality.asset_type_counts == (("Unreviewed", 1),)
    assert quality.status_mismatch_row_indices == (0,)
    assert quality.date_missingness == (("ipoDate", 0, 1), ("delistingDate", 1, 0))


@pytest.mark.parametrize(
    "text",
    [
        "",
        "bad,header\n",
        HEADER + "A,Short,NYSE\n",
        HEADER + "\n",
        HEADER + 'A,"unterminated,NYSE,Stock,2000-01-01,null,Active\n',
        HEADER + "A,Name,NYSE,Stock,2024-02-30,null,Active\n",
        HEADER + "A,Name,NYSE,Stock,2000-1-1,null,Active\n",
        HEADER + "A,Name,NYSE,Stock,2000-01-01,NULL,Active\n",
        HEADER + "A,Name\x00,NYSE,Stock,2000-01-01,null,Active\n",
        HEADER + "A," + "x" * 4097 + ",NYSE,Stock,2000-01-01,null,Active\n",
    ],
)
def test_corrupt_csv_schema_or_dates_fail_closed(text):
    with pytest.raises(StockListingSnapshotError, match=r"^stock_listing_snapshot_invalid$"):
        parse(text)


def test_immutable_bytes_hash_and_utf8_bounds_are_enforced():
    body = (HEADER + "A,Name,NYSE,Stock,2000-01-01,null,Active\n").encode()
    with pytest.raises(StockListingSnapshotError):
        parse_stock_listing_snapshot(
            body, expected_sha256="0" * 64, request=request(), received_at=RECEIVED
        )
    for malformed in (b"\xff", b"x" * (8 * 1024 * 1024 + 1), bytearray(body)):
        with pytest.raises(StockListingSnapshotError):
            parse(malformed)


@pytest.mark.parametrize("kind", ["flags", "row", "csv", "request", "future_receipt", "naive_asof"])
def test_quality_reparses_original_evidence_and_denies_changed_or_future_inputs(kind):
    snapshot = parse(HEADER + "A,Name,NYSE,Stock,2000-01-01,null,Active\n")
    cutoff = AS_OF
    if kind == "flags":
        object.__setattr__(snapshot, "source_qualified", 0)
    elif kind == "row":
        object.__setattr__(snapshot.rows[0], "name", "Changed")
    elif kind == "csv":
        object.__setattr__(snapshot, "original_csv", b"changed")
    elif kind == "request":
        object.__setattr__(snapshot.request, "return_full_data", 1)
    elif kind == "future_receipt":
        cutoff = datetime(2026, 10, 25, tzinfo=UTC)
    else:
        cutoff = AS_OF.replace(tzinfo=None)
    with pytest.raises(StockListingSnapshotError):
        assess_stock_listing_snapshot(snapshot, as_of=cutoff)


def test_hashes_bind_request_date_receipt_and_original_duplicate_counts():
    body = HEADER + "A,Name,NYSE,Stock,2000-01-01,null,Active\n"
    snapshot = parse(body)
    result = assess_stock_listing_snapshot(snapshot, as_of=AS_OF)
    assert len(result.evidence_hash) == 64
    later = parse(body, received=datetime(2026, 10, 26, 1, 1, tzinfo=UTC))
    assert assess_stock_listing_snapshot(later, as_of=AS_OF).evidence_hash != result.evidence_hash
    different = parse(body, req=StockListingRequest(date(2023, 1, 1), "active"))
    assert different.evidence_hash != snapshot.evidence_hash
    duplicate = parse(body + "A,Name,NYSE,Stock,2000-01-01,null,Active\n")
    assert (
        assess_stock_listing_snapshot(duplicate, as_of=AS_OF).evidence_hash != result.evidence_hash
    )


@pytest.mark.parametrize(
    "day,state", [(datetime(2024, 1, 1), "active"), (WHEN, "Active"), (WHEN, "unknown")]
)
def test_request_requires_an_explicit_date_and_closed_source_state(day, state):
    with pytest.raises(StockListingSnapshotError):
        StockListingRequest(day, state)


def test_future_request_date_and_too_many_rows_are_denied():
    with pytest.raises(StockListingSnapshotError):
        parse(HEADER, req=StockListingRequest(date(2027, 1, 1), "active"))
    with pytest.raises(StockListingSnapshotError):
        parse(HEADER + "A,Name,NYSE,Stock,2000-01-01,null,Active\n" * 30001)


def test_delisted_request_cannot_silently_accept_a_future_delisting_date():
    snapshot = parse(
        HEADER + "A,Name,NYSE,Stock,2000-01-01,2025-01-01,Delisted\n",
        req=request("delisted"),
    )
    result = assess_stock_listing_snapshot(snapshot, as_of=AS_OF)
    assert "requested_date_membership" in result.blocked_uses
    assert result.delisting_after_requested_row_indices == (0,)


def test_equality_equivalent_row_index_type_mutation_is_denied():
    snapshot = parse(HEADER + "A,Name,NYSE,Stock,2000-01-01,null,Active\n")
    object.__setattr__(snapshot.rows[0], "row_index", False)
    with pytest.raises(StockListingSnapshotError):
        assess_stock_listing_snapshot(snapshot, as_of=AS_OF)


def panel_inputs(rows=None):
    names = [chr(65 + i) for i in range(16)]
    if rows is None:
        rows = [f"{name},Company {name},NYSE,Stock,2000-01-01,null,Active\n" for name in names]
    body = HEADER + "".join(rows)
    snapshot = parse(body)
    source = {
        "request": {
            "tool": "mcp__codex_apps__alpha_vantage_listing_status",
            "args": {"date": "2024-01-01", "state": "active", "return_full_data": True},
        },
        "started_at": "2026-10-26 00:59:59 UTC",
        "received_at": "2026-10-26 01:00:00 UTC",
        "result": {
            "content": [{"type": "text", "text": body}],
            "structuredContent": {"result": body},
            "isError": False,
        },
    }
    source_raw = json.dumps(source).encode()
    source_sha = hashlib.sha256(source_raw).hexdigest()
    intent = {
        "schema_version": 1,
        "contract_id": "stock-task4-historical-panel-v1",
        "created_at": "2026-10-26T01:10:00Z",
        "live_enabled": False,
        "sampling_frame": {
            "receipt_sha256": source_sha,
            "tool": source["request"]["tool"],
            "request": source["request"]["args"],
        },
        "selection": {
            "asset_type": "Stock",
            "case_insensitive": True,
            "count": 12,
            "duplicate_rule": (
                "quarantine every row whose ticker occurs more than once across ALL asset types"
            ),
            "exchanges": ["NYSE", "NASDAQ"],
            "excluded_name_whole_word_regex": (
                "warrants?|rights?|units?|preferred|depositary|depository|ADR|ADS|ETF|fund|trust"
            ),
            "hash_separator_byte_hex": "00",
            "hash_utf8_prefix": "stock-task4-historical-panel-v1",
            "latest_ipo_date": "2023-01-01",
            "name_required": True,
            "no_replacement": True,
            "sort": "SHA256(UTF8(prefix) + byte00 + UTF8(symbol)), then symbol",
            "symbol_regex": "[A-Z]{1,4}",
        },
    }
    intent_raw = json.dumps(intent).encode()
    return snapshot, source_raw, intent_raw


def panel(inputs):
    snapshot, source, intent = inputs
    return select_stock_history_panel(
        snapshot,
        original_source_receipt=source,
        expected_source_receipt_sha256=hashlib.sha256(source).hexdigest(),
        original_intent=intent,
        expected_intent_sha256=hashlib.sha256(intent).hexdigest(),
    )


def test_panel_is_input_order_independent_and_uses_literal_nul_hash_order():
    first = panel(panel_inputs())
    rows = list(
        reversed(
            [
                f"{chr(65 + i)},Company {chr(65 + i)},NYSE,Stock,2000-01-01,null,Active\n"
                for i in range(16)
            ]
        )
    )
    second = panel(panel_inputs(rows))
    expected = tuple(
        sorted(
            [chr(65 + i) for i in range(16)],
            key=lambda s: (
                hashlib.sha256(b"stock-task4-historical-panel-v1\x00" + s.encode()).hexdigest(),
                s,
            ),
        )[:12]
    )
    assert tuple(member.record.symbol for member in first.selected) == expected
    assert tuple(member.record.symbol for member in second.selected) == expected
    assert first.requested_count == len(first.selected) == 12
    assert first.eligible_count == 16 and first.selection_complete is True
    assert first.benchmark_only_symbols == ("SPY",)
    assert first.source_qualified is first.investment_eligible is False
    for member in first.selected:
        assert member.record.row_index == ord(member.record.symbol) - 65
        assert member.record.common_stock_classification is None


def test_panel_quarantines_duplicate_tickers_across_types_and_preserves_denominators():
    rows = [
        "A,Company A,NYSE,Stock,2000-01-01,null,Active\n",
        "A,Fund A,NYSE,ETF,2000-01-01,null,Active\n",
        "B,Company B,NYSE,Stock,2000-01-01,null,Active\n",
        "CW,Company Warrant,NASDAQ,Stock,2000-01-01,null,Active\n",
        "UN,Company Units,NASDAQ,Stock,2000-01-01,null,Active\n",
    ]
    result = panel(panel_inputs(rows))
    assert result.raw_row_count == 5 and len(result.decisions) == 5
    assert result.eligible_count == 1 and len(result.selected) == 1
    assert result.selection_complete is False
    assert result.selected[0].record.symbol == "B"
    assert result.decisions[0].exclusion_reasons == ("duplicate_symbol",)
    assert result.decisions[1].exclusion_reasons == (
        "duplicate_symbol",
        "asset_type_not_Stock",
        "excluded_name_word",
    )
    assert result.decisions[3].exclusion_reasons == ("excluded_name_word",)
    assert result.decisions[4].exclusion_reasons == ("excluded_name_word",)
    assert result.denominators[0].before == 5 and result.denominators[0].remaining == 3


@pytest.mark.parametrize(
    "kind",
    ["source_hash", "intent_hash", "changed_csv", "replacement", "count", "date", "boolean_type"],
)
def test_panel_requires_exact_source_and_frozen_profile_without_replacement_overrides(kind):
    snapshot, source, intent = panel_inputs()
    kwargs = dict(
        original_source_receipt=source,
        expected_source_receipt_sha256=hashlib.sha256(source).hexdigest(),
        original_intent=intent,
        expected_intent_sha256=hashlib.sha256(intent).hexdigest(),
    )
    if kind in {"source_hash", "intent_hash"}:
        kwargs[
            "expected_source_receipt_sha256" if kind == "source_hash" else "expected_intent_sha256"
        ] = "0" * 64
    elif kind == "changed_csv":
        snapshot = parse(HEADER)
    else:
        value = json.loads(intent)
        if kind == "replacement":
            value["selection"]["replacement_symbols"] = ["OTHER"]
        elif kind == "count":
            value["selection"]["count"] = 13
        elif kind == "boolean_type":
            value["selection"]["case_insensitive"] = 1
        else:
            value["sampling_frame"]["request"]["date"] = "2023-01-01"
        kwargs["original_intent"] = json.dumps(value).encode()
        kwargs["expected_intent_sha256"] = hashlib.sha256(kwargs["original_intent"]).hexdigest()
    with pytest.raises(StockListingSnapshotError):
        select_stock_history_panel(snapshot, **kwargs)
