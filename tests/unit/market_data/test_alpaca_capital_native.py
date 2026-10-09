"""Fabricated native daily pages; no market or authenticated data."""

import hashlib
import json
from dataclasses import replace

import pytest

from trading_bot.market_data.alpaca_capital_native import (
    CapitalDailyRequest,
    assess_capital_daily_pages,
    parse_capital_daily_page,
)
from trading_bot.market_data.alpaca_native import AlpacaStockRequest, parse_timestamp_ns


def request(symbol="QQQ"):
    return CapitalDailyRequest(
        symbol,
        parse_timestamp_ns("2023-01-03T00:00:00Z"),
        parse_timestamp_ns("2023-01-06T00:00:00Z"),
    )


def body(symbol="QQQ", stamp="2023-01-03T05:00:00Z", token=None):
    return json.dumps(
        {
            "symbol": symbol,
            "next_page_token": token,
            "bars": [{"t": stamp, "o": 10, "h": 12, "l": 9, "c": 11, "v": 100, "n": 5, "vw": 10.5}],
        }
    ).encode()


def page(symbol="QQQ", stamp="2023-01-03T05:00:00Z", token=None, index=0, previous=None):
    raw = body(symbol, stamp, token)
    return parse_capital_daily_page(
        raw,
        request=request(symbol),
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        page_index=index,
        requested_page_token=previous,
    )


@pytest.mark.parametrize("symbol", ["SPY", "QQQ", "IWM", "SHY", "IEF"])
def test_request_is_new_symbol_bound_namespace_without_changing_legacy(symbol):
    value = request(symbol)
    assert value.path == f"/v2/stocks/{symbol}/bars"
    assert dict(value.query())["feed"] == "sip"
    assert dict(value.query())["adjustment"] == "raw"
    legacy = AlpacaStockRequest("bars", value.start_ns, value.end_ns)
    assert value.query() == legacy.query()
    assert value.request_hash != legacy.request_hash
    assert legacy.path == "/v2/stocks/SPY/bars"


def test_original_bytes_and_unknown_availability_are_preserved():
    value = page()
    assert value.body_sha256 == hashlib.sha256(body()).hexdigest()
    assert value.records[0].symbol == "QQQ"
    assert str(value.records[0].bar.vwap) == "10.5"
    assert value.records[0].bar.publication_at_ns is None
    assert value.source_qualified is value.evidence_promotable is False


def test_terminal_page_chain_and_count_are_integrity_only():
    first = page(token="cursor")
    second = page(stamp="2023-01-04T05:00:00Z", index=1, previous="cursor")
    report = assess_capital_daily_pages((first, second))
    assert report.record_count == 2
    assert report.pagination_complete is True
    assert report.source_qualified is report.evidence_promotable is False
    assert "historical_availability_unverified" in report.reasons


@pytest.mark.parametrize("change", ["symbol", "hash", "range", "keys", "duplicates"])
def test_mismatched_or_inconsistent_wire_is_rejected(change):
    raw = body()
    expected = hashlib.sha256(raw).hexdigest()
    query = request()
    if change == "symbol":
        query = request("SPY")
    elif change == "hash":
        expected = "a" * 64
    elif change == "range":
        query = replace(query, start_ns=parse_timestamp_ns("2023-01-04T00:00:00Z"))
    elif change == "keys":
        raw = raw.replace(b'"bars":', b'"quotes":')
        expected = hashlib.sha256(raw).hexdigest()
    else:
        raw = raw.replace(b'"symbol": "QQQ"', b'"symbol": "QQQ", "symbol": "SPY"')
        expected = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError):
        parse_capital_daily_page(raw, request=query, expected_sha256=expected)


@pytest.mark.parametrize(
    "pages",
    [
        (),
        (page(token="cursor"),),
    ],
)
def test_incomplete_pagination_is_not_silently_complete(pages):
    assert assess_capital_daily_pages(pages).pagination_complete is False


def test_duplicate_session_and_changed_cursor_deny_chain():
    first = page(token="cursor")
    for second in (
        page(index=1, previous="cursor"),
        page(stamp="2023-01-04T05:00:00Z", index=1, previous="different"),
        page("SPY", stamp="2023-01-04T05:00:00Z", index=1, previous="cursor"),
    ):
        with pytest.raises(ValueError):
            assess_capital_daily_pages((first, second))


@pytest.mark.parametrize("symbol", ["DIA", "QQQ/../SPY", "qqq", True])
def test_request_rejects_outside_or_ambiguous_symbols(symbol):
    with pytest.raises(ValueError):
        request(symbol)


@pytest.mark.parametrize(
    "raw",
    [b"", b"{" * 10000, b"x" * 1048577, b'{"a":NaN}', b"\xff"],
    ids=["empty", "malformed", "oversized", "nonfinite", "invalid_utf8"],
)
def test_invalid_or_oversized_bodies_fail_without_raw_details(raw):
    with pytest.raises(ValueError, match=r"^alpaca_native_invalid$"):
        parse_capital_daily_page(
            raw, request=request(), expected_sha256=hashlib.sha256(raw).hexdigest()
        )


def test_nanosecond_stamp_and_symbol_identity_are_lossless():
    value = page(stamp="2023-01-03T05:00:00.123456789Z")
    assert value.records[0].bar.timestamp_ns % 10**9 == 123456789
    assert value.records[0].record_hash != value.records[0].bar.record_hash


def test_continued_or_looping_terminal_chains_are_invalid():
    first = page(token="cursor")
    looping = page(stamp="2023-01-04T05:00:00Z", index=1, previous="cursor", token="cursor")
    with pytest.raises(ValueError):
        assess_capital_daily_pages((first, looping))
    terminal = page()
    extra = page(stamp="2023-01-04T05:00:00Z", index=1)
    with pytest.raises(ValueError):
        assess_capital_daily_pages((terminal, extra))
