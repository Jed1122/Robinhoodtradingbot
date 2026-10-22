"""Fictional minute rows prove local contracts, never provider/source acceptance."""

import hashlib
import importlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from trading_bot.market_data.alpaca_native import format_timestamp_ns, parse_timestamp_ns


def api():
    try:
        return importlib.import_module("trading_bot.market_data.alpaca_stock_minutes")
    except ModuleNotFoundError:
        pytest.fail("pure Alpaca stock-minute contract is not implemented")


def instant(text):
    return datetime.fromisoformat(text)


def session(day="2026-03-09", opening="13:30", closing="20:00", **changes):
    values = {
        "session_date": date.fromisoformat(day),
        "opens_at": instant(f"{day}T{opening}:00+00:00"),
        "closes_at": instant(f"{day}T{closing}:00+00:00"),
        "calendar_source_url": "https://www.nyse.com/trade/hours-calendars",
        "calendar_sha256": "a" * 64,
        "calendar_received_at": instant("2026-01-02T00:00:00+00:00"),
    }
    return api().StockCoreSessionDeclaration(**(values | changes))


def request(window=None, symbol="ALFA"):
    return api().StockMinuteRequest(symbol, session() if window is None else window)


def row(stamp="2026-03-09T13:30:00Z", **changes):
    return {"t": stamp, "o": 10, "h": 13, "l": 9, "c": 12, "v": 100, "n": 5, "vw": 11} | changes


def body(rows, *, symbol="ALFA", token=None, **extra):
    return json.dumps(
        {"symbol": symbol, "bars": rows, "next_page_token": token, **extra},
        separators=(",", ":"),
    ).encode()


def rows_for(req):
    start = parse_timestamp_ns(req.session.opens_at.isoformat())
    count = int((req.session.closes_at - req.session.opens_at).total_seconds() // 60)
    return [row(format_timestamp_ns(start + index * 60_000_000_000)) for index in range(count)]


def page(encoded, req=None, *, index=0, token=None, started=None, received=None, **changes):
    req = request() if req is None else req
    started = instant("2026-11-30T00:00:00+00:00") if started is None else started
    values = {
        "request": req,
        "expected_sha256": hashlib.sha256(encoded).hexdigest(),
        "page_index": index,
        "requested_page_token": token,
        "capture_started_at": started,
        "received_at": started + timedelta(seconds=index + 1) if received is None else received,
    }
    return api().parse_stock_minute_page(encoded, **(values | changes))


def assess(requests, pages, *, as_of=None):
    return api().assess_stock_minute_proof(
        requests=requests,
        pages=pages,
        as_of=instant("2026-12-01T00:00:00+00:00") if as_of is None else as_of,
    )


def test_request_freezes_endpoint_sip_raw_and_exclusive_close_nanosecond():
    req = request()
    assert req.url == "https://data.alpaca.markets/v2/stocks/ALFA/bars"
    assert dict(req.query()) == {
        "start": "2026-03-09T13:30:00.000000000Z",
        "end": "2026-03-09T19:59:59.999999999Z",
        "timeframe": "1Min",
        "feed": "sip",
        "adjustment": "raw",
        "currency": "USD",
        "asof": "-",
        "sort": "asc",
        "limit": "1000",
    }
    assert dict(req.query("opaque+/="))["page_token"] == "opaque+/="
    assert req.request_sha256 != request(symbol="BETA").request_sha256


@pytest.mark.parametrize("symbol", ["alfa", " ALFA", "ALFA/OTHER", "", "A" * 17])
def test_request_denies_uncanonical_or_path_changing_symbols(symbol):
    with pytest.raises(ValueError):
        request(symbol=symbol)


def test_dst_and_early_close_are_explicit_and_not_a_fixed_utc_schedule():
    before = request(session("2026-03-06", "14:30", "21:00"))
    after = request()
    early = request(session("2026-11-27", "14:30", "18:00"))
    assert before.session.expected_minutes == after.session.expected_minutes == 390
    assert early.session.expected_minutes == 210
    assert before.session.opens_at.hour == 14 and after.session.opens_at.hour == 13
    result = assess((early,), (page(body(rows_for(early)), early),))
    assert result.sessions[0].aggregate.close == Decimal(12)
    assert result.sessions[0].observed_minutes == 210
    assert result.sessions[0].calendar_authenticity_verified is False


@pytest.mark.parametrize(
    "changes",
    [
        {"opens_at": instant("2026-03-09T14:30:00+00:00")},
        {"closes_at": instant("2026-03-09T20:01:00+00:00")},
        {"session_date": date(2026, 3, 10)},
        {"calendar_sha256": "bad"},
        {"calendar_source_url": "http://example.test/calendar"},
        {"calendar_received_at": datetime(2026, 1, 2)},
    ],
)
def test_calendar_declaration_denies_inconsistent_or_unbounded_context(changes):
    with pytest.raises(ValueError):
        session(**changes)


def test_complete_two_session_proof_preserves_exact_hashes_receipts_and_aggregate():
    first = request(session("2026-03-06", "14:30", "21:00"))
    second = request()
    first_rows = rows_for(first)
    first_rows[0].update(o=11, h=15)
    first_rows[-1].update(c=8, l=7, o=10)
    p0 = page(body(first_rows), first)
    p1 = page(body(rows_for(second)), second, received=p0.received_at + timedelta(seconds=1))
    result = assess((first, second), (p0, p1))
    assert result.two_session_proof_complete is True
    assert result.total_pages == 2 and result.total_bytes == p0.body_bytes + p1.body_bytes
    window = result.sessions[0]
    aggregate = window.aggregate
    assert window.status == "complete_grid" and window.missing_minute_starts_ns == ()
    assert (aggregate.open, aggregate.high, aggregate.low, aggregate.close) == (
        Decimal(11),
        Decimal(15),
        Decimal(7),
        Decimal(8),
    )
    assert aggregate.volume == 39000 and aggregate.trade_count == 1950
    assert aggregate.member_record_sha256 == tuple(r.record_sha256 for r in p0.records)
    assert aggregate.source_body_sha256 == (p0.body_sha256,)
    assert window.pages == (p0,) and window.available_at >= p0.received_at
    assert aggregate.no_fill_applied is True and aggregate.native_interpolated is None
    assert aggregate.session_basis == "core_window_[open,close)"
    assert aggregate.provider_finality_verified is False and aggregate.publication_at is None
    for item in (p0, p0.records[0], result, window, aggregate):
        assert item.qualified is item.source_qualified is item.investment_eligible is False
        assert item.trading_enabled is item.live_authorized is False
    with pytest.raises(FrozenInstanceError):
        p0.body_sha256 = "b" * 64
    assert result.assessment_sha256 == assess((first, second), (p0, p1)).assessment_sha256


def test_decimal_lexemes_and_optional_currency_are_preserved_without_defaults():
    encoded = body([row()]).replace(b'"o":10', b'"o":10.000000000000001')
    parsed = page(encoded)
    assert parsed.records[0].open == Decimal("10.000000000000001")
    assert parsed.response_currency is None
    assert parsed.native_payload is True and parsed.receipt_is_caller_declared is True
    assert parsed.records[0].native_interpolated is None
    assert page(body([row()], currency="USD")).response_currency == "USD"


@pytest.mark.parametrize(
    "changes",
    [
        {"o": 0},
        {"h": 8},
        {"l": 14},
        {"c": -1},
        {"v": 0},
        {"n": 0},
        {"v": True},
        {"n": 1.5},
        {"vw": "11"},
        {"o": "NaN"},
        {"t": "2026-03-09T13:30:00.000000001Z"},
        {"t": "2026-03-09T13:29:00Z"},
        {"t": "2026-03-09T20:00:00Z"},
        {"interpolated": False},
    ],
)
def test_native_bar_validation_denies_bad_real_rows_without_repair(changes):
    with pytest.raises(ValueError, match="alpaca_stock_minutes_invalid"):
        page(body([row(**changes)]))


@pytest.mark.parametrize(
    "encoded",
    [
        b'{"symbol":"ALFA","symbol":"BETA","bars":[],"next_page_token":null}',
        b'{"symbol":"ALFA","bars":[],"next_page_token":null,"other":1}',
        body([row()], symbol="BETA"),
        body([row()], currency="EUR"),
        body([row(), row()]),
        body([row("2026-03-09T13:31:00Z"), row()]),
        b'{"symbol":"ALFA","bars":null,"next_page_token":null}',
    ],
)
def test_page_scope_syntax_order_and_duplicate_failures_deny_whole_page(encoded):
    with pytest.raises(ValueError):
        page(encoded)


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_sha256": "b" * 64},
        {"page_index": 2},
        {"page_index": True},
        {"capture_started_at": instant("2026-03-09T20:14:59+00:00")},
        {"capture_started_at": datetime(2026, 3, 10)},
        {"received_at": instant("2026-03-09T20:14:00+00:00")},
        {"received_at": instant("2026-11-30T00:01:01+00:00")},
        {"requested_page_token": "unsafe\n"},
    ],
)
def test_hash_delay_deadline_and_receipt_failures_are_fixed_sanitized_errors(changes):
    with pytest.raises(ValueError, match=r"^alpaca_stock_minutes_invalid$"):
        page(body([row()]), **changes)


def test_missing_minute_is_explicit_and_never_zero_filled_or_aggregated():
    req = request()
    rows = rows_for(req)
    del rows[5]
    result = assess((req,), (page(body(rows), req),))
    window = result.sessions[0]
    assert window.status == "incomplete" and window.aggregate is None
    assert window.observed_minutes == 389 and window.expected_minutes == 390
    assert window.missing_minute_starts_ns == (parse_timestamp_ns("2026-03-09T13:35:00Z"),)
    assert window.reason_codes == ("missing_minutes",)
    assert result.two_session_proof_complete is False


def test_no_response_and_empty_response_remain_unavailable_with_explicit_missingness():
    req = request()
    for pages in ((), (page(body([]), req),)):
        window = assess((req,), pages).sessions[0]
        assert window.status == "unavailable" and window.aggregate is None
        assert window.observed_minutes == 0 and len(window.missing_minute_starts_ns) == 390
    assert assess((req,), ()).sessions[0].reason_codes == ("pages_missing", "missing_minutes")


def test_two_page_chain_must_terminate_and_preserves_page_indices():
    req = request()
    rows = rows_for(req)
    first = page(body(rows[:200], token="next"), req)
    second = page(body(rows[200:]), req, index=1, token="next")
    window = assess((req,), (first, second)).sessions[0]
    assert window.transport_complete is True and window.aggregate.volume == 39000
    assert window.aggregate.source_body_sha256 == (first.body_sha256, second.body_sha256)
    assert second.records[0].page_index == 1 and second.records[0].row_index == 0
    incomplete = assess((req,), (first,)).sessions[0]
    assert incomplete.aggregate is None and incomplete.transport_complete is False
    assert "pagination_incomplete" in incomplete.reason_codes


@pytest.mark.parametrize(
    "fault", ["wrong_token", "overlap", "terminal_extra", "loop", "receipt", "start"]
)
def test_cross_page_identity_order_chain_and_receipt_failures_deny_proof(fault):
    req = request()
    rows = rows_for(req)
    first = page(body(rows[:200], token=None if fault == "terminal_extra" else "next"), req)
    second = page(
        body(
            rows[199:] if fault == "overlap" else rows[200:],
            token="next" if fault == "loop" else None,
        ),
        req,
        index=1,
        token="wrong" if fault == "wrong_token" else "next",
        received=first.received_at if fault == "receipt" else None,
        started=first.capture_started_at + timedelta(seconds=1) if fault == "start" else None,
    )
    with pytest.raises(ValueError):
        assess((req,), (first, second))


def test_proof_denies_future_receipt_wrong_request_order_duplicate_sessions_and_oversize():
    req = request()
    parsed = page(body(rows_for(req)), req)
    cases = [
        ((req, req), (parsed,)),
        ((req, request(symbol="BETA")), (parsed,)),
        ((req,), (page(body(rows_for(req), symbol="BETA"), request(symbol="BETA")),)),
        ((req, req, req), (parsed,)),
        ((req,), (parsed,) * 5),
    ]
    for requests, pages in cases:
        with pytest.raises(ValueError):
            assess(requests, pages)
    with pytest.raises(ValueError):
        assess((req,), (parsed,), as_of=parsed.received_at - timedelta(microseconds=1))
    with pytest.raises(ValueError):
        page(b" " * 1_048_577)


def test_relabelled_hash_or_record_provenance_cannot_survive_dataclass_reconstruction():
    parsed = page(body([row()]))
    with pytest.raises(ValueError):
        replace(parsed, records=(replace(parsed.records[0], body_sha256="b" * 64),))
    with pytest.raises(ValueError):
        replace(parsed, body_bytes=1_048_577)
    with pytest.raises(ValueError):
        replace(parsed, records=(replace(parsed.records[0], request_sha256="b" * 64),))
    with pytest.raises(ValueError):
        replace(parsed, records=(replace(parsed.records[0], close=Decimal(11)),))


def test_proof_requires_one_bounded_capture_clock_across_both_sessions():
    first = request(session("2026-03-06", "14:30", "21:00"))
    second = request()
    started = instant("2026-03-10T00:00:00+00:00")
    p0 = page(body(rows_for(first)), first, started=started)
    p1 = page(body(rows_for(second)), second, started=started + timedelta(seconds=2))
    with pytest.raises(ValueError):
        assess((first, second), (p0, p1))
