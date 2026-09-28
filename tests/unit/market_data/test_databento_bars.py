"""Boundary tests for exact, bounded, non-promotable native observations."""

import hashlib
import io
import struct
from dataclasses import FrozenInstanceError, replace
from datetime import date
from types import SimpleNamespace

import pytest

from tests.unit.market_data._native_bars_fixtures import (
    END,
    MINUTE,
    PRICES,
    STAMP,
    START,
    api,
    bar_fixture,
    dbn,
    models,
    native_bytes,
    native_record,
    zstd,
)
from tests.unit.market_data.test_databento_batch import no_network  # noqa: F401
from trading_bot.market_data.databento_batch import DatabentoImportError
from trading_bot.market_data.databento_definitions import DefinitionLimits


def scan(raw=None, *, body=None, limits=None, digest=None):
    module = api()
    request = models().NativeBarRequest(START, END)
    if body is None:
        body = zstd.ZstdCompressor(write_checksum=True).compress(
            native_bytes() if raw is None else raw
        )
    rows = []
    profile = module.scan_bars(
        io.BytesIO(body),
        expected=request,
        expected_sha256=digest or hashlib.sha256(body).hexdigest(),
        limits=limits or DefinitionLimits(),
        consume=rows.append,
    )
    return profile, rows


@pytest.mark.parametrize("version", [1, 2, 3])
def test_supported_versions_preserve_native_integer_values_and_record_hash(version):
    raw = native_bytes(version=version)
    profile, rows = scan(raw)
    assert profile.dbn_version == version
    assert (profile.decoded_count, profile.accepted_count) == (1, 1)
    row = rows[0]
    assert (row.open_nanos, row.high_nanos, row.low_nanos, row.close_nanos) == PRICES
    assert (row.interval_start_ns, row.volume, row.instrument_id) == (STAMP, 100, 42)
    assert row.record_hash == hashlib.sha256(raw[-56:]).hexdigest()
    assert row.raw_hash == profile.raw_hash
    assert row.disposition == "accepted"
    assert row.reasons == ()
    assert not hasattr(row, "available_at")
    assert not any(
        (
            profile.production_eligible,
            profile.evidence_promotable,
            profile.download_authorized,
            profile.live_authorized,
            profile.historical_availability_verified,
            profile.economic_evidence,
        )
    )
    with pytest.raises(FrozenInstanceError):
        profile.accepted_count = 5


def test_undefined_ohlc_is_rejected_even_when_ordering_matches():
    body, request, digest = bar_fixture(prices=(2**63 - 1,) * 4)
    rows = []
    profile = api().scan_bars(
        io.BytesIO(body),
        expected=request,
        expected_sha256=digest,
        limits=DefinitionLimits(),
        consume=rows.append,
    )
    assert (profile.decoded_count, profile.rejected_count) == (1, 1)
    assert rows[0].open_nanos is None
    assert rows[0].reasons == ("native_undefined_ohlc",)
    assert profile.historical_availability_verified is False


@pytest.mark.parametrize(
    "prices,reason",
    [
        ((0, 102, 0, 101), "native_nonpositive_price"),
        ((100, 99, 98, 100), "native_invalid_ohlc"),
        ((100, 102, 103, 101), "native_invalid_ohlc"),
    ],
)
def test_unusable_prices_remain_rejected_observations(prices, reason):
    profile, rows = scan(native_bytes(prices=prices))
    assert profile.rejected_count == 1
    assert rows[0].disposition == "rejected"
    assert reason in rows[0].reasons


def test_native_stream_row_conservation():
    good = native_record()
    bad = native_record(stamp=STAMP + MINUTE, prices=(2**63 - 1,) * 4)
    profile, rows = scan(native_bytes(records=(good, good, bad, bad)))
    assert (
        profile.decoded_count,
        profile.accepted_count,
        profile.rejected_count,
        profile.duplicate_count,
    ) == (4, 1, 1, 2)
    assert [row.disposition for row in rows] == ["accepted", "duplicate", "rejected", "duplicate"]
    assert rows[-1].open_nanos is None
    assert "native_undefined_ohlc" in rows[-1].reasons


def test_conflicting_duplicate_invalidates_stream():
    api()
    records = (
        native_record(),
        native_record(prices=(100000000000, 102000000000, 99000000000, 100000000000)),
    )
    with pytest.raises(DatabentoImportError):
        scan(native_bytes(records=records))


@pytest.mark.parametrize(
    "change",
    [
        {"dataset": "OPRA.PILLAR"},
        {"schema": dbn.Schema.DEFINITION},
        {"symbols": ["QQQ"]},
        {"stype_in": dbn.SType.PARENT},
        {"stype_out": dbn.SType.RAW_SYMBOL},
        {"limit": 1},
        {"ts_out": True},
        {"start": START + 1},
        {"end": END - 1},
        {"not_found": ["SPY"]},
        {"partial": ["SPY"]},
        {"mappings": []},
    ],
)
def test_schema_scope_and_mapping_mismatch_denied(change):
    api()
    with pytest.raises(DatabentoImportError):
        scan(native_bytes(metadata_changes=change))


@pytest.mark.parametrize("stamp", [START - MINUTE, END, STAMP + 1, 2**64 - 1])
def test_record_timestamp_must_match_minute_query(stamp):
    api()
    with pytest.raises(DatabentoImportError):
        scan(native_bytes(records=(native_record(stamp=stamp),)))


def test_regressing_time_and_unmapped_identity_denied():
    api()
    for records in (
        (native_record(stamp=STAMP + MINUTE), native_record()),
        (native_record(instrument_id=43),),
    ):
        with pytest.raises(DatabentoImportError):
            scan(native_bytes(records=records))


@pytest.mark.parametrize("mapping_end", [date(2024, 1, 2), date(2024, 1, 1)])
def test_mapping_end_is_exclusive_and_empty_intervals_denied(mapping_end):
    api()
    mapping = SimpleNamespace(
        raw_symbol="SPY",
        intervals=[SimpleNamespace(start_date=date(2024, 1, 1), end_date=mapping_end, symbol="42")],
    )
    with pytest.raises(DatabentoImportError):
        scan(native_bytes(metadata_changes={"mappings": [mapping]}))


def test_ambiguous_mapping_intervals_denied():
    api()
    mapping = SimpleNamespace(
        raw_symbol="SPY",
        intervals=[
            SimpleNamespace(start_date=date(2024, 1, 2), end_date=date(2024, 1, 22), symbol="42"),
            SimpleNamespace(start_date=date(2024, 1, 3), end_date=date(2024, 1, 22), symbol="43"),
        ],
    )
    with pytest.raises(DatabentoImportError):
        scan(native_bytes(metadata_changes={"mappings": [mapping]}))


@pytest.mark.parametrize("cut", [1, 7, 100, -1, -30])
def test_partial_record_or_metadata_never_returns_profile(cut):
    api()
    with pytest.raises(DatabentoImportError):
        scan(native_bytes()[:cut])


def test_compression_frames_are_distinct_from_dbn_documents():
    raw = native_bytes()
    compressor = zstd.ZstdCompressor(write_checksum=True)
    body = compressor.compress(raw[:153]) + compressor.compress(raw[153:])
    assert scan(body=body)[0].accepted_count == 1
    for invalid in (
        body[:-1],
        body + b"garbage",
        compressor.compress(raw + raw),
        compressor.compress(raw + b"x"),
    ):
        with pytest.raises(DatabentoImportError):
            scan(body=invalid)


def test_bad_digest_metadata_extensions_empty_stream_and_wrong_record_deny():
    api()
    raw = native_bytes()
    end = 8 + struct.unpack("<I", raw[4:8])[0]
    invalid = (
        raw[:108] + struct.pack("<I", 1) + raw[112:],
        raw[:end],
        raw[: end + 1] + b"\x20" + raw[end + 2 :],
        raw[:3] + b"\x04" + raw[4:],
    )
    for body in invalid:
        with pytest.raises(DatabentoImportError):
            scan(body)
    with pytest.raises(DatabentoImportError):
        scan(raw, digest="0" * 64)


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_records", 1),
        ("max_compressed_bytes", 1),
        ("max_decompressed_bytes", 100),
        ("max_metadata_bytes", 120),
        ("max_records", 10_000_001),
    ],
)
def test_resource_bounds_fail_closed(field, value):
    api()
    with pytest.raises(DatabentoImportError, match="databento_limit_exceeded"):
        scan(native_bytes(count=2), limits=replace(DefinitionLimits(), **{field: value}))


@pytest.mark.parametrize(
    "start,end", [(True, END), (float(START), END), (0, END), (END, START), (START, 2**63)]
)
def test_query_rejects_nonexact_or_invalid_bounds(start, end):
    model = models()
    with pytest.raises(DatabentoImportError):
        model.NativeBarRequest(start, end)


def test_row_rejects_boolean_and_float_financial_fields():
    _, rows = scan()
    for changes in ({"volume": True}, {"close_nanos": 101.0}, {"instrument_id": False}):
        with pytest.raises(DatabentoImportError):
            replace(rows[0], **changes)


def test_expansion_limit_and_same_minute_state_are_bounded():
    with pytest.raises(DatabentoImportError, match="databento_limit_exceeded"):
        scan(b"x" * 500_000, limits=replace(DefinitionLimits(), max_decompressed_bytes=1000))
    records = (native_record(), native_record(publisher_id=3))
    with pytest.raises(DatabentoImportError, match="databento_limit_exceeded"):
        scan(
            native_bytes(records=records), limits=replace(DefinitionLimits(), max_unique_symbols=1)
        )


def test_adjacent_mapping_intervals_use_the_new_identity_at_midnight():
    mapping = SimpleNamespace(
        raw_symbol="SPY",
        intervals=[
            SimpleNamespace(start_date=date(2024, 1, 1), end_date=date(2024, 1, 2), symbol="41"),
            SimpleNamespace(start_date=date(2024, 1, 2), end_date=date(2024, 1, 22), symbol="42"),
        ],
    )
    assert scan(native_bytes(metadata_changes={"mappings": [mapping]}))[0].accepted_count == 1


def test_profile_and_row_cannot_forge_counts_quality_or_authority():
    profile, rows = scan()
    for changes in (
        {"decoded_count": True},
        {"accepted_count": 2},
        {"quality_counts": (("arbitrary_provider_text", 1),)},
    ):
        with pytest.raises(DatabentoImportError):
            replace(profile, **changes)
    for name in (
        "production_eligible",
        "historical_availability_verified",
        "economic_evidence",
        "download_authorized",
        "evidence_promotable",
        "live_authorized",
    ):
        with pytest.raises(ValueError):
            replace(profile, **{name: True})
    with pytest.raises(DatabentoImportError):
        replace(rows[0], close_nanos=None)


def test_oversized_record_length_denies_before_decoder_allocations():
    raw = native_bytes()
    metadata_end = 8 + struct.unpack("<I", raw[4:8])[0]
    with pytest.raises(DatabentoImportError):
        scan(raw[:metadata_end] + b"\xff" + raw[metadata_end + 1 :])
