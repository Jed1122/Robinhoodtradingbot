"""Fictional bytes verify reconstruction, never actual source or HTTP provenance."""

import base64
import hashlib
import importlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta

import pytest

from trading_bot.market_data.alpaca_native import format_timestamp_ns, parse_timestamp_ns
from trading_bot.market_data.alpaca_stock_minutes import (
    StockCoreSessionDeclaration,
    StockMinuteRequest,
    assess_stock_minute_proof,
    parse_stock_minute_page,
)

START = datetime(2026, 3, 10, tzinfo=UTC)
BOOT = "0edeb8bf-0bbb-48ef-9826-d051de17a001"
CALENDAR = b"fictional original calendar\r\n"
FLAGS = (
    "qualified",
    "source_qualified",
    "strategy_qualified",
    "investment_eligible",
    "trading_enabled",
    "live_authorized",
)


def api():
    try:
        return importlib.import_module("trading_bot.market_data.stock_capture_manifest")
    except ModuleNotFoundError:
        pytest.fail("pure stock capture manifest is not implemented")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def request(day="2026-03-09", *, calendar=CALENDAR, symbol="ALFA"):
    opening, closing = ("14:30", "21:00") if day == "2026-03-06" else ("13:30", "20:00")
    return StockMinuteRequest(
        symbol,
        StockCoreSessionDeclaration(
            date.fromisoformat(day),
            datetime.fromisoformat(f"{day}T{opening}:00+00:00"),
            datetime.fromisoformat(f"{day}T{closing}:00+00:00"),
            "https://calendar.example.test/stock-calendar",
            digest(calendar),
            datetime(2026, 1, 2, tzinfo=UTC),
        ),
    )


def values(**changes):
    return {
        "capture_id": "a" * 32,
        "code_sha256": "b" * 64,
        "config_sha256": "c" * 64,
        "requests": (request("2026-03-06"), request()),
        "calendar_bodies": (CALENDAR,),
        "capture_boot_id": BOOT,
        "capture_started_monotonic_ns": 1_000_000_000,
        "capture_started_at": START,
    } | changes


def manifest(**changes):
    return api().StockMinuteCaptureManifest(**values(**changes))


def canonical(value):
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode()


def encoded_manifest(**changes):
    return api().dump_stock_capture_manifest(manifest(**changes))


def rows(req):
    start = parse_timestamp_ns(req.session.opens_at.isoformat())
    return [
        {
            "t": format_timestamp_ns(start + index * 60_000_000_000),
            "o": 10,
            "h": 13,
            "l": 9,
            "c": 12,
            "v": 100,
            "n": 5,
            "vw": 11,
        }
        for index in range(req.session.expected_minutes)
    ]


def body(req, records=None, token=None):
    return json.dumps(
        {
            "symbol": req.symbol,
            "bars": rows(req) if records is None else records,
            "next_page_token": token,
        },
        separators=(",", ":"),
    ).encode()


def response(req=None, *, raw=None, second=1, **changes):
    req = request() if req is None else req
    raw = body(req) if raw is None else raw
    return api().StockMinuteCapturedResponse(
        **(
            {
                "request_sha256": req.request_sha256,
                "body_sha256": digest(raw),
                "body": raw,
                "page_index": 0,
                "requested_page_token": None,
                "received_at": START + timedelta(seconds=second),
                "received_monotonic_ns": 1_000_000_000 + second * 1_000_000_000,
                "boot_id": BOOT,
                "http_status": 200,
            }
            | changes
        )
    )


def reconstruct(responses, *, raw=None, as_of=None):
    return api().reconstruct_stock_capture(
        encoded_manifest() if raw is None else raw,
        responses,
        as_of=START + timedelta(minutes=1) if as_of is None else as_of,
    )


def invalid(call):
    with pytest.raises(api().StockCaptureManifestError, match=r"^stock_capture_manifest_invalid$"):
        call()


def test_manifest_exact_canonical_round_trip_preserves_original_calendar_and_request_hashes():
    original = manifest()
    raw = api().dump_stock_capture_manifest(original)
    wire = json.loads(raw)
    assert set(wire) == {
        "schema_version",
        "capture_id",
        "code_sha256",
        "config_sha256",
        "requests",
        "calendar_bodies",
        "capture_boot_id",
        "capture_started_monotonic_ns",
        "capture_started_at",
    }
    assert wire["schema_version"] == 1
    assert wire["capture_started_at"] == "2026-03-10T00:00:00+00:00"
    assert wire["calendar_bodies"] == [
        {
            "sha256": digest(CALENDAR),
            "body_base64": base64.b64encode(CALENDAR).decode("ascii"),
        }
    ]
    assert set(wire["requests"][0]) == {
        "symbol",
        "request_sha256",
        "session_date",
        "opens_at",
        "closes_at",
        "calendar_source_url",
        "calendar_sha256",
        "calendar_received_at",
    }
    assert wire["requests"][0]["session_date"] == "2026-03-06"
    assert raw == canonical(wire)
    restored = api().parse_stock_capture_manifest(raw)
    assert restored == original and restored.calendar_bodies == (CALENDAR,)
    assert api().dump_stock_capture_manifest(restored) == raw
    assert all(getattr(restored, name) is False for name in FLAGS)
    assert "ALFA" not in repr(restored) and "calendar" not in repr(restored)
    with pytest.raises(FrozenInstanceError):
        restored.capture_id = "d" * 32
    with pytest.raises(TypeError):
        api().StockMinuteCaptureManifest(**values(), live_authorized=True)


@pytest.mark.parametrize(
    "changes",
    [
        {"capture_id": "A" * 32},
        {"capture_id": 1},
        {"capture_id": "a" * 31},
        {"code_sha256": "B" * 64},
        {"config_sha256": "bad"},
        {"capture_boot_id": BOOT.upper()},
        {"capture_boot_id": "bad"},
        {"capture_started_monotonic_ns": True},
        {"capture_started_monotonic_ns": 0},
        {"capture_started_monotonic_ns": -1},
        {"capture_started_monotonic_ns": 2**63},
        {"capture_started_monotonic_ns": 1.0},
        {"capture_started_at": datetime(2026, 3, 10)},
        {"requests": []},
        {"requests": ()},
        {"requests": (request(),) * 3},
        {"requests": (request(), request())},
        {"requests": (request(), request("2026-03-06"))},
        {"requests": (request("2026-03-06"), request(symbol="BETA"))},
        {"calendar_bodies": []},
        {"calendar_bodies": ()},
        {"calendar_bodies": (CALENDAR, CALENDAR)},
        {"calendar_bodies": (b"wrong",)},
        {"calendar_bodies": (CALENDAR, b"unreferenced")},
        {"calendar_bodies": (bytearray(CALENDAR),)},
        {"calendar_bodies": (b"x" * 1_048_577,)},
        {"capture_started_at": datetime(2026, 3, 9, 20, 14, 59, tzinfo=UTC)},
    ],
)
def test_manifest_denies_invalid_types_context_calendar_scope_and_resource_bounds(changes):
    invalid(lambda: manifest(**changes))


def test_manifest_requires_calendar_receipt_before_capture_and_validates_nested_mutations():
    req = request()
    future = replace(req.session, calendar_received_at=START + timedelta(seconds=1))
    invalid(lambda: manifest(requests=(replace(req, session=future),)))
    object.__setattr__(req, "feed", "iex")
    invalid(lambda: manifest(requests=(req,)))
    req = request()
    object.__setattr__(req.session, "calendar_authenticity_verified", True)
    invalid(lambda: manifest(requests=(req,)))


def test_two_original_calendars_are_hash_sorted_and_every_body_is_referenced():
    calendars = tuple(sorted((CALENDAR, b"another fictional calendar"), key=digest))
    reqs = (request("2026-03-06", calendar=calendars[0]), request(calendar=calendars[1]))
    original = manifest(requests=reqs, calendar_bodies=calendars)
    assert (
        api().parse_stock_capture_manifest(api().dump_stock_capture_manifest(original)) == original
    )
    invalid(lambda: manifest(requests=reqs, calendar_bodies=calendars[::-1]))


def test_calendar_bytes_cannot_be_empty_even_with_a_matching_declared_hash():
    invalid(lambda: manifest(requests=(request(calendar=b""),), calendar_bodies=(b"",)))


def test_calendar_receipt_at_capture_start_preserves_existing_inclusive_boundary():
    req = request()
    req = replace(req, session=replace(req.session, calendar_received_at=START))
    item = manifest(requests=(req,))
    assert api().parse_stock_capture_manifest(api().dump_stock_capture_manifest(item)) == item


@pytest.mark.parametrize(
    "target, field, value",
    [
        ("request", "qualified", 0),
        ("session", "source_qualified", 0),
        ("request", "request_is_caller_declared", 1),
        ("session", "calendar_authenticity_verified", 0),
    ],
)
def test_equality_equivalent_nested_flag_mutations_do_not_become_valid_evidence(
    target, field, value
):
    req = request()
    object.__setattr__(req if target == "request" else req.session, field, value)
    invalid(lambda: manifest(requests=(req,)))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda w: w.update(schema_version=True),
        lambda w: w.update(schema_version=2),
        lambda w: w.update(schema_version=1.0),
        lambda w: w.update(live_authorized=False),
        lambda w: w.pop("capture_id"),
        lambda w: w["requests"][0].update(request_sha256="e" * 64),
        lambda w: w["requests"][0].update(symbol="BETA"),
        lambda w: w["requests"][0].update(feed="sip"),
        lambda w: w["requests"][0].update(session_date="20260306"),
        lambda w: w["requests"][0].update(opens_at="2026-03-06T14:30:00Z"),
        lambda w: w.update(capture_started_at="2026-03-10T00:00:00.000000+00:00"),
        lambda w: w["calendar_bodies"][0].update(sha256="f" * 64),
        lambda w: w["calendar_bodies"][0].update(body_base64="YQ=== "),
        lambda w: w["calendar_bodies"][0].update(body_base64="YR=="),
        lambda w: w["calendar_bodies"][0].update(other=False),
        lambda w: w["calendar_bodies"].clear(),
    ],
)
def test_closed_manifest_parser_denies_changed_hashes_flags_and_noncanonical_values(mutate):
    wire = json.loads(encoded_manifest())
    mutate(wire)
    invalid(lambda: api().parse_stock_capture_manifest(canonical(wire)))


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"[]\n",
        b"null\n",
        b"{}\n",
        b"\xff",
        b"x" * 3_145_729,
        b'{"schema_version":1,"schema_version":1}\n',
        b'{"schema_version":NaN}\n',
        b'{"schema_version":Infinity}\n',
    ],
)
def test_parser_bounds_and_json_failures_are_fixed_and_sanitized(raw):
    invalid(lambda: api().parse_stock_capture_manifest(raw))


def test_parser_requires_exact_bytes_and_dump_revalidates_mutated_manifest():
    raw = encoded_manifest()
    for changed in (raw[:-1], raw + b"\n", b" " + raw, raw.replace(b'":', b'": ', 1)):
        invalid(lambda changed=changed: api().parse_stock_capture_manifest(changed))
    invalid(lambda: api().parse_stock_capture_manifest(bytearray(raw)))
    item = manifest()
    object.__setattr__(item, "live_authorized", True)
    invalid(lambda: api().dump_stock_capture_manifest(item))


def test_base64_nonzero_padding_bits_cannot_relabel_the_same_original_calendar():
    wire = json.loads(encoded_manifest(requests=(request(calendar=b"a"),), calendar_bodies=(b"a",)))
    assert wire["calendar_bodies"][0]["body_base64"] == "YQ=="
    wire["calendar_bodies"][0]["body_base64"] = "YR=="
    assert base64.b64decode("YR==", validate=True) == b"a"
    invalid(lambda: api().parse_stock_capture_manifest(canonical(wire)))


def test_nested_duplicate_keys_and_noncanonical_json_order_do_not_round_trip():
    raw = encoded_manifest()
    duplicated = raw.replace(b'"symbol":"ALFA"', b'"symbol":"ALFA","symbol":"ALFA"', 1)
    invalid(lambda: api().parse_stock_capture_manifest(duplicated))
    reordered = (json.dumps(json.loads(raw), sort_keys=False) + "\n").encode()
    invalid(lambda: api().parse_stock_capture_manifest(reordered))


def test_two_maximum_original_calendars_remain_within_the_closed_manifest_byte_limit():
    calendars = tuple(sorted((b"x" * 1_048_576, b"y" * 1_048_576), key=digest))
    reqs = (request("2026-03-06", calendar=calendars[0]), request(calendar=calendars[1]))
    raw = encoded_manifest(requests=reqs, calendar_bodies=calendars)
    assert len(raw) < 3_145_728
    assert api().parse_stock_capture_manifest(raw).calendar_bodies == calendars


@pytest.mark.parametrize(
    "changes",
    [
        {"request_sha256": "x" * 64},
        {"body_sha256": "d" * 64},
        {"body": b""},
        {"body": b"x" * 1_048_577},
        {"body": bytearray(b"{}")},
        {"page_index": True},
        {"page_index": -1},
        {"page_index": 2},
        {"requested_page_token": ""},
        {"requested_page_token": "unsafe\n"},
        {"requested_page_token": "x" * 4097},
        {"requested_page_token": 1},
        {"received_at": datetime(2026, 3, 10)},
        {"received_monotonic_ns": True},
        {"received_monotonic_ns": 0},
        {"received_monotonic_ns": 2**63},
        {"boot_id": "bad"},
        {"http_status": True},
        {"http_status": 200.0},
        {"http_status": 201},
    ],
)
def test_captured_response_denies_wrong_hashes_http_status_types_and_bounds(changes):
    invalid(lambda: response(**changes))


def test_complete_reconstruction_matches_existing_proof_and_preserves_unknown_semantics():
    m = manifest()
    captures = tuple(response(req, second=index + 1) for index, req in enumerate(m.requests))
    result = reconstruct(captures)
    expected_pages = tuple(
        parse_stock_minute_page(
            captured.body,
            request=req,
            expected_sha256=captured.body_sha256,
            capture_started_at=START,
            received_at=captured.received_at,
        )
        for req, captured in zip(m.requests, captures, strict=True)
    )
    expected = assess_stock_minute_proof(
        requests=m.requests,
        pages=expected_pages,
        as_of=START + timedelta(minutes=1),
    )
    assert result == expected and result.two_session_proof_complete is True
    assert result.total_pages == 2 and all(w.observed_minutes == 390 for w in result.sessions)
    for item in (m, *captures, result, *result.sessions):
        assert all(getattr(item, name) is False for name in FLAGS)
    for window in result.sessions:
        assert window.aggregate.volume == 39000
        assert window.aggregate.native_interpolated is None
        assert window.aggregate.no_fill_applied is True
        assert window.aggregate.session_basis == "core_window_[open,close)"
        assert window.pages[0].original_body == captures[result.sessions.index(window)].body
    assert "ALFA" not in repr(captures[0])


def test_empty_partial_and_missing_minute_captures_remain_explicitly_unavailable_or_incomplete():
    empty = reconstruct(())
    assert empty.total_pages == 0 and empty.two_session_proof_complete is False
    assert all(w.status == "unavailable" and w.aggregate is None for w in empty.sessions)
    req = request("2026-03-06")
    partial = reconstruct((response(req),))
    assert partial.sessions[0].status == "complete_grid"
    assert partial.sessions[1].reason_codes == ("pages_missing", "missing_minutes")
    absent_minute = reconstruct((response(req, raw=body(req, rows(req)[1:])),))
    assert absent_minute.sessions[0].aggregate is None
    assert len(absent_minute.sessions[0].missing_minute_starts_ns) == 1
    no_rows = reconstruct((response(req, raw=body(req, [])),))
    assert no_rows.sessions[0].status == "unavailable"
    assert no_rows.sessions[0].transport_complete is True


def test_paginated_reconstruction_requires_cursor_chain_without_discarding_partial_input():
    req = request("2026-03-06")
    first = response(req, raw=body(req, rows(req)[:200], "next"))
    last = response(
        req,
        raw=body(req, rows(req)[200:]),
        second=2,
        page_index=1,
        requested_page_token="next",
    )
    complete = reconstruct((first, last))
    assert complete.sessions[0].status == "complete_grid"
    partial = reconstruct((first,))
    assert partial.sessions[0].transport_complete is False
    assert "pagination_incomplete" in partial.sessions[0].reason_codes
    invalid(lambda: reconstruct((first, replace(last, requested_page_token="wrong"))))
    invalid(lambda: reconstruct((replace(first, page_index=1),)))
    invalid(lambda: reconstruct((first, first)))


def test_four_maximum_size_pages_preserve_all_bytes_and_both_complete_sessions():
    captures = []
    for req in manifest().requests:
        records = rows(req)
        for index, records_part in enumerate((records[:200], records[200:])):
            raw = body(req, records_part, "next" if index == 0 else None)
            raw += b" " * (1_048_576 - len(raw))
            captures.append(
                response(
                    req,
                    raw=raw,
                    second=len(captures) + 1,
                    page_index=index,
                    requested_page_token="next" if index else None,
                )
            )
    result = reconstruct(tuple(captures))
    assert result.total_bytes == 4_194_304 and result.total_pages == 4
    assert result.two_session_proof_complete is True
    assert all(w.observed_minutes == 390 for w in result.sessions)


@pytest.mark.parametrize(
    "fault",
    [
        "unknown_request",
        "boot",
        "utc_before",
        "utc_after",
        "mono_before",
        "mono_after",
        "equal_utc",
        "equal_mono",
        "decreasing_mono",
        "session_order",
        "future",
        "mutated_body",
        "mutated_flag",
        "list",
        "derived",
        "too_many",
        "empty_future_cutoff",
    ],
)
def test_reconstruction_denies_clock_boot_identity_scope_and_mutation_drift(fault):
    reqs = manifest().requests
    first, last = response(reqs[0]), response(reqs[1], second=2)
    captures, cutoff = (first, last), START + timedelta(minutes=1)
    if fault == "unknown_request":
        captures = (replace(first, request_sha256="d" * 64), last)
    elif fault == "boot":
        captures = (replace(first, boot_id="7dd4182c-21ad-46cf-8320-4796a1c09e8e"), last)
    elif fault in {"utc_before", "utc_after"}:
        offset = -1 if fault == "utc_before" else 61
        captures = (replace(first, received_at=START + timedelta(seconds=offset)),)
    elif fault in {"mono_before", "mono_after"}:
        value = 999_999_999 if fault == "mono_before" else 61_000_000_001
        captures = (replace(first, received_monotonic_ns=value),)
    elif fault == "equal_utc":
        captures = (first, replace(last, received_at=first.received_at))
    elif fault in {"equal_mono", "decreasing_mono"}:
        value = first.received_monotonic_ns - (fault == "decreasing_mono")
        captures = (first, replace(last, received_monotonic_ns=value))
    elif fault == "session_order":
        captures = (response(reqs[1]), response(reqs[0], second=2))
    elif fault == "future":
        cutoff = START + timedelta(seconds=1)
    elif fault in {"mutated_body", "mutated_flag"}:
        object.__setattr__(
            first,
            "body" if fault == "mutated_body" else "live_authorized",
            b"changed original bytes" if fault == "mutated_body" else True,
        )
    elif fault == "list":
        captures = [first, last]
    elif fault == "derived":
        captures = (reconstruct(()),)
    elif fault == "too_many":
        captures = (first,) * 5
    else:
        captures, cutoff = (), START - timedelta(seconds=1)
    invalid(lambda: reconstruct(captures, as_of=cutoff))


def test_capture_window_includes_sixty_seconds_and_clocks_remain_independent_declarations():
    first = response(request("2026-03-06"), second=60, received_monotonic_ns=1_000_000_001)
    assert reconstruct((first,)).sessions[0].status == "complete_grid"


def test_native_validation_error_does_not_leak_source_text_or_repair_rows():
    req = request("2026-03-06")
    malformed = response(req, raw=b'{"symbol":"SECRET-SOURCE-DIAGNOSTIC"}')
    invalid(lambda: reconstruct((malformed,)))
