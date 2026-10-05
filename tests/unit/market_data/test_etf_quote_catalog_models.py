"""Receipt catalog wire integrity; no economic or executable qualification."""

import hashlib
import importlib
import json
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from trading_bot.market_data.alpaca_native import AlpacaQuoteRecord, parse_timestamp_ns


def api():
    try:
        return importlib.import_module("trading_bot.market_data.etf_quote_catalog_models")
    except ModuleNotFoundError:
        pytest.fail("versioned native quote catalog models are missing")


START = parse_timestamp_ns("2016-01-04T00:00:00Z")


def reference(name="capture", start=START, end=START + 60_000_000_000, digest="a"):
    m = api()
    return m.QuoteCaptureReference(
        m.QuoteCaptureLocation(name, digest * 64), digest * 63 + "0", start, end, 2
    )


def day():
    return api().QuoteDayIndex(date(2016, 1, 4), (reference(),))


def catalog():
    m = api()
    return m.QuoteCatalog(
        "a" * 40, "b" * 64, (m.QuoteDayReference(date(2016, 1, 4), "c" * 64, 1, 2),)
    )


@pytest.mark.parametrize("kind", ["day", "catalog"])
def test_roundtrip_domain_and_hash_are_exact_and_unqualified(kind):
    m = api()
    value = day() if kind == "day" else catalog()
    encode, decode = getattr(m, "encode_" + kind), getattr(m, "decode_" + kind)
    body = encode(value)
    assert encode(decode(body)) == body
    wire = json.loads(body)
    assert wire["schema"] == "etf-native-quote-" + kind + "-v1"
    for flag in ("source_qualified", "cost_qualified", "execution_enabled", "evidence_promotable"):
        assert wire[flag] is False
    assert getattr(m, kind + "_hash")(value) == hashlib.sha256(body).hexdigest()


def test_adjacent_and_gapped_requests_never_claim_gap_coverage():
    m = api()
    first = reference()
    second = reference("second", first.end_ns, first.end_ns + 10, "c")
    third = reference("third", second.end_ns + 10, second.end_ns + 20, "d")
    value = m.QuoteDayIndex(date(2016, 1, 4), (first, second, third))
    assert len(value.captures) == 3
    assert not value.source_qualified and not value.execution_enabled
    with pytest.raises(ValueError):
        replace(value, captures=(first, replace(second, start_ns=first.end_ns - 1)))


@pytest.mark.parametrize(
    "path", ["", "/absolute", "../outside", "a/../b", "a//b", ".", "a/./b", "a/", "a\\b", "a\n"]
)
def test_unsafe_paths_deny(path):
    with pytest.raises(ValueError):
        api().QuoteCaptureLocation(path, "a" * 64)


@pytest.mark.parametrize(
    "change",
    [
        {"start_ns": True},
        {"record_count": False},
        {"record_count": 128001},
        {"end_ns": START},
        {"archive_hash": "A" * 64},
    ],
)
def test_invalid_capture_bounds_or_identity_deny(change):
    with pytest.raises(ValueError):
        replace(reference(), **change)


@pytest.mark.parametrize("captures", ["duplicate", "reverse", "cross_day", "too_many"])
def test_day_bounds_and_unique_sorted_captures_deny(captures):
    first = reference()
    if captures == "duplicate":
        rows = (first, first)
    elif captures == "reverse":
        rows = (reference("other", START + 100_000_000_000, START + 200_000_000_000, "c"), first)
    elif captures == "cross_day":
        rows = (replace(first, end_ns=START + 86_400_000_000_001),)
    else:
        rows = (first,) * 1025
    with pytest.raises(ValueError):
        replace(day(), captures=rows)


@pytest.mark.parametrize(
    "change", [{"days": ()}, {"days": "bad"}, {"code_revision": "dirty"}, {"config_hash": "x" * 64}]
)
def test_catalog_requires_declared_code_config_and_bounded_days(change):
    with pytest.raises(ValueError):
        replace(catalog(), **change)


def test_duplicate_reverse_or_overlimit_days_deny():
    value = catalog()
    later = replace(value.days[0], day=date(2016, 1, 5), index_hash="d" * 64)
    for rows in ((value.days[0], value.days[0]), (later, value.days[0]), value.days * 4001):
        with pytest.raises(ValueError):
            replace(value, days=rows)


@pytest.mark.parametrize("kind", ["day", "catalog"])
@pytest.mark.parametrize(
    "mutation", ["flag", "nested", "unknown", "float", "bool", "duplicate", "oversize", "schema"]
)
def test_dirty_wire_does_not_reconstruct_trusted_models(kind, mutation):
    m = api()
    body = getattr(m, "encode_" + kind)(day() if kind == "day" else catalog())
    wire = json.loads(body)
    rows = wire["captures" if kind == "day" else "days"]
    if mutation == "flag":
        wire["execution_enabled"] = True
    elif mutation == "nested":
        rows[0]["source_qualified"] = True
    elif mutation == "unknown":
        wire["unexpected"] = 1
    elif mutation in ("float", "bool"):
        rows[0]["record_count" if kind == "day" else "capture_count"] = (
            1.0 if mutation == "float" else True
        )
    elif mutation == "schema":
        wire["schema"] = "legacy-v1"
    body = json.dumps(wire).encode()
    if mutation == "duplicate":
        body = b'{"schema":"duplicate",' + body[1:]
    elif mutation == "oversize":
        body += b" " * 1048576
    with pytest.raises(ValueError):
        getattr(m, "decode_" + kind)(body)


def test_occurrence_preserves_native_decimal_nanoseconds_and_unknown_availability():
    m = api()
    native = AlpacaQuoteRecord(
        "a" * 64,
        0,
        1,
        START + 123456789,
        Decimal("200.123456789123456789"),
        Decimal("200.25"),
        3,
        7,
        "P",
        "N",
        ("R", "Y"),
        "B",
    )
    value = m.CatalogQuoteOccurrence(reference().location, "b" * 64, native)
    assert value.record.bid == Decimal("200.123456789123456789")
    assert value.record.timestamp_ns == START + 123456789
    assert value.record.conditions == ("R", "Y")
    assert value.record.row_index == 1
    assert value.record.publication_at_ns is None
    assert value.record.executable is False
    assert value.record.record_hash == native.record_hash
