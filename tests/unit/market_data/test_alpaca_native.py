"""Invented native-shaped rows validate mechanics, never actual source evidence."""

import hashlib
import importlib
import json
from dataclasses import replace
from decimal import Decimal

import pytest


def api():
    try:
        return importlib.import_module("trading_bot.market_data.alpaca_native")
    except ModuleNotFoundError:
        pytest.fail("native Alpaca codec is not implemented")


def request(kind="quotes", start="2016-01-04T00:00:00Z", end="2016-01-05T00:00:00Z"):
    module = api()
    return module.AlpacaStockRequest(
        kind, module.parse_timestamp_ns(start), module.parse_timestamp_ns(end)
    )


def quote(**changes):
    row = {
        "t": "2016-01-04T14:30:00.000000001Z",
        "bp": 200,
        "ap": 201,
        "bs": 2,
        "as": 3,
        "bx": "P",
        "ax": "P",
        "c": ["R"],
        "z": "B",
    }
    return row | changes


def bar(**changes):
    return {
        "t": "2016-01-04T05:00:00Z",
        "o": 200,
        "h": 202,
        "l": 199,
        "c": 201,
        "v": 1000,
        "n": 10,
        "vw": 200,
    } | changes


def encoded(rows, kind="quotes", token=None, **extra):
    return json.dumps(
        {"symbol": "SPY", kind: rows, "next_page_token": token, **extra}, separators=(",", ":")
    ).encode()


def parse(body, req=None, *, page=0, token=None):
    return api().parse_alpaca_page(
        body,
        request=request() if req is None else req,
        expected_sha256=hashlib.sha256(body).hexdigest(),
        page_index=page,
        requested_page_token=token,
    )


def test_query_is_single_symbol_raw_sip_and_half_open_without_losing_last_nanosecond():
    req = request("bars")
    query = dict(req.query())
    assert req.path == "/v2/stocks/SPY/bars"
    assert query["end"] == "2016-01-04T23:59:59.999999999Z"
    assert query["start"] == "2016-01-04T00:00:00.000000000Z"
    assert {
        key: query[key] for key in ("feed", "asof", "currency", "sort", "timeframe", "adjustment")
    } == {
        "feed": "sip",
        "asof": "-",
        "currency": "USD",
        "sort": "asc",
        "timeframe": "1Day",
        "adjustment": "raw",
    }
    assert dict(req.query("opaque+/="))["page_token"] == "opaque+/="
    assert "adjustment" not in dict(request().query())


def test_decimal_lexemes_and_timestamp_nanoseconds_are_lossless():
    body = encoded([quote()]).replace(b'"bp":200', b'"bp":200.000000000000001')
    row = parse(body).records[0]
    assert row.bid == Decimal("200.000000000000001")
    assert row.timestamp_ns == 1451917800000000001
    assert row.bid_size == 2 and row.ask_size == 3
    assert row.size_unit == "round_lots"
    assert row.conditions == ("R",) and row.tape == "B"
    assert row.publication_at_ns is None


def test_offset_timestamp_retains_ns_without_float_datetime_rounding():
    module = api()
    assert module.parse_timestamp_ns("2016-01-04T09:30:00.123456789-05:00") == 1451917800123456789
    assert module.format_timestamp_ns(1451917800123456789) == "2016-01-04T14:30:00.123456789Z"


@pytest.mark.parametrize(
    "value",
    [
        "2016-01-04",
        "2016-01-04T14:30:00",
        "2016-01-04T14:30:00.1234567891Z",
        "2016-02-30T00:00:00Z",
        "2016-01-04T14:30:00+05:60",
        "2016-01-04T14:30:00-00:00",
        True,
    ],
)
def test_invalid_or_precision_losing_timestamp_denies(value):
    with pytest.raises(ValueError):
        api().parse_timestamp_ns(value)


def test_quote_size_units_do_not_silently_multiply_old_rows_by_100():
    req = request(start="2025-11-02T00:00:00Z", end="2025-11-05T00:00:00Z")
    page = parse(
        encoded(
            [
                quote(t="2025-11-02T14:30:00Z"),
                quote(t="2025-11-03T14:30:00Z"),
                quote(t="2025-11-04T14:30:00Z"),
            ]
        ),
        req,
    )
    assert [row.size_unit for row in page.records] == [
        "round_lots",
        "transition_unverified",
        "shares",
    ]
    assert [row.bid_size for row in page.records] == [2, 2, 2]
    assert page.source_qualified is False and page.evidence_promotable is False


@pytest.mark.parametrize(
    "stamp,unit",
    [
        ("2025-11-02T23:59:59.999999999Z", "round_lots"),
        ("2025-11-03T00:00:00Z", "transition_unverified"),
        ("2025-11-04T04:59:59.999999999Z", "transition_unverified"),
        ("2025-11-04T05:00:00Z", "shares"),
    ],
)
def test_unverified_quote_unit_transition_includes_both_utc_and_local_date(stamp, unit):
    req = request(start="2025-11-02T00:00:00Z", end="2025-11-05T00:00:00Z")
    assert parse(encoded([quote(t=stamp)]), req).records[0].size_unit == unit


def test_same_timestamp_quotes_preserve_page_and_row_order_even_when_identical():
    req = request()
    first = parse(encoded([quote(), quote()], token="next"), req)
    second = parse(encoded([quote()]), req, page=1, token="next")
    archive = api().validate_alpaca_pages(req, (first, second))
    assert archive.record_count == 3
    assert archive.pagination_complete and not archive.source_qualified
    assert [r.row_index for r in first.records] == [0, 1]
    assert first.records[0].record_hash != first.records[1].record_hash
    assert "historical_availability_unverified" in archive.reasons


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"bp": 0, "bs": 0, "bx": " "}, "inactive_bid"),
        ({"ap": 0, "as": 0}, "inactive_ask"),
        ({"bp": 202}, "crossed_quote"),
        ({"bp": 201}, "locked_quote"),
    ],
)
def test_non_executable_quotes_are_preserved_with_explicit_observation_reasons(changes, reason):
    row = parse(encoded([quote(**changes)])).records[0]
    assert reason in row.observation_reasons
    assert not row.executable


def test_daily_bar_is_native_aggregation_not_a_completed_session_or_receipt():
    row = parse(encoded([bar()], "bars"), request("bars")).records[0]
    assert row.timestamp_ns == 1451883600000000000
    assert row.close == Decimal("201") and row.volume == 1000 and row.trade_count == 10
    assert row.publication_at_ns is None
    assert not hasattr(row, "ends_at")


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r | {"unexpected": "field"},
        lambda r: r | {"bs": True},
        lambda r: r | {"bp": "200"},
        lambda r: r | {"bp": -1},
        lambda r: r | {"bs": 2**32},
        lambda r: {k: v for k, v in r.items() if k != "c"},
    ],
)
def test_native_quote_schema_rejects_coercion_missing_or_unknown_fields(change):
    with pytest.raises(ValueError):
        parse(encoded([change(quote())]))


@pytest.mark.parametrize(
    "body",
    [
        b'{"symbol":"SPY","symbol":"SPY","quotes":[],"next_page_token":null}',
        b'{"symbol":"SPY","quotes":[],"next_page_token":null,"secret":"not accepted"}',
        b'{"symbol":"SPY","quotes":null,"next_page_token":null}',
        b'{"symbol":"SPY","quotes":[],"next_page_token":NaN}',
    ],
)
def test_closed_envelope_rejects_ambiguous_or_nonfinite_json(body):
    with pytest.raises(ValueError):
        parse(body)


def test_body_hash_currency_symbol_and_request_window_are_enforced():
    module = api()
    body = encoded([quote()])
    with pytest.raises(ValueError):
        module.parse_alpaca_page(body, request=request(), expected_sha256="a" * 64)
    for changed in (
        encoded([quote()], currency="EUR"),
        body.replace(b"SPY", b"QQQ"),
        encoded([quote(t="2016-01-05T00:00:00Z")]),
    ):
        with pytest.raises(ValueError):
            parse(changed)


def test_short_page_with_token_is_not_complete_and_broken_chains_deny():
    module = api()
    req = request()
    first = parse(encoded([quote()], token="next"), req)
    partial = module.validate_alpaca_pages(req, (first,))
    assert not partial.pagination_complete and "pagination_incomplete" in partial.reasons
    second = parse(encoded([]), req, page=1, token="wrong")
    with pytest.raises(ValueError):
        module.validate_alpaca_pages(req, (first, second))
    repeated = parse(encoded([], token="next"), req, page=1, token="next")
    with pytest.raises(ValueError):
        module.validate_alpaca_pages(req, (first, repeated))


def test_page_order_bar_duplicates_and_unvalidated_records_deny():
    module = api()
    req = request("bars")
    with pytest.raises(ValueError):
        parse(encoded([bar(), bar()], "bars"), req)
    first = parse(encoded([bar()], "bars", token="next"), req)
    second = parse(encoded([bar()], "bars"), req, page=1, token="next")
    with pytest.raises(ValueError):
        module.validate_alpaca_pages(req, (first, second))
    forged = replace(first.records[0])
    object.__setattr__(forged, "volume", -1)
    with pytest.raises(ValueError):
        replace(first, records=(forged,))


def test_valid_empty_response_is_transport_complete_but_not_qualified():
    req = request()
    result = api().validate_alpaca_pages(req, (parse(encoded([]), req),))
    assert result.record_count == 0 and result.pagination_complete
    assert "source_coverage_empty" in result.reasons
    assert not result.source_qualified and not result.evidence_promotable
