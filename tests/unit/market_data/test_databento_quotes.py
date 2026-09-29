"""Lossless native quote intake, not an assertion of executable prices."""

from dataclasses import replace

import pytest

from tests.unit.market_data._native_quotes_fixtures import (
    END,
    STAMP,
    compressed,
    dbn,
    module,
    native,
    record,
    request,
    scan,
    zstd,
)
from tests.unit.market_data.test_databento_batch import no_network  # noqa: F401
from trading_bot.market_data.databento_batch import DatabentoImportError
from trading_bot.market_data.databento_native_io import DefinitionLimits


@pytest.mark.parametrize("underlying", [False, True])
@pytest.mark.parametrize("version", [1, 2, 3])
def test_exact_native_values_are_preserved_without_qualification(underlying, version):
    profile, rows = scan(compressed(underlying=underlying, version=version), underlying=underlying)
    row = rows[0]
    assert (row.bid_px, row.ask_px, row.ts_event, row.ts_recv) == (
        1000000001,
        1200000003,
        STAMP,
        STAMP + 1,
    )
    assert row.record_ordinal == 0
    assert row.raw_record_hex == record(underlying=underlying).hex()
    assert row.dbn_version == version
    assert profile.accepted_count == 1
    for name in (
        "economic_evidence",
        "production_eligible",
        "evidence_promotable",
        "historical_availability_verified",
        "download_authorized",
        "live_authorized",
    ):
        assert getattr(profile, name) is False


@pytest.mark.parametrize("bid,ask", [(0, 1), (100, 100)])
def test_zero_bid_and_locked_quote_remain_observations(bid, ask):
    profile, rows = scan(compressed([record(bid=bid, ask=ask)]))
    assert rows[0].bid_px == bid
    assert profile.rejected_count == 0


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"bid": 2, "ask": 1}, "native_crossed_quote"),
        ({"bid": dbn.UNDEF_PRICE}, "native_undefined_quote"),
        ({"bid": -1}, "native_invalid_price"),
        ({"ask": 0}, "native_invalid_price"),
        ({"flags": 128 | 8}, "native_bad_timestamp"),
        ({"flags": 128 | 4}, "native_bad_book"),
        ({"flags": 128 | 2}, "native_publisher_specific"),
        ({"flags": 0}, "native_incomplete_event"),
        ({"recv": STAMP - 1}, "native_bad_timestamp"),
        ({"stamp": dbn.UNDEF_TIMESTAMP}, "native_bad_timestamp"),
    ],
)
def test_quality_rejections_are_retained_and_counted(changes, reason):
    profile, rows = scan(compressed([record(**changes)]))
    assert len(rows) == profile.rejected_count == 1
    assert reason in rows[0].reasons
    assert dict(profile.quality_counts)[reason] == 1


def test_reset_is_retained_as_control_not_as_an_entry_quote():
    profile, rows = scan(compressed([record(action="R")]))
    assert rows[0].action == "R"
    assert rows[0].disposition == "control"
    assert profile.control_count == 1
    assert profile.accepted_count == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"publisher_id": 20},
        {"action": "T", "publisher_id": 20, "side": dbn.Side.BID},
        {"action": "T", "publisher_id": 30, "side": dbn.Side.NONE},
        {"ts_in_delta": 100},
    ],
)
def test_inconsistent_opra_fields_are_retained_but_not_accepted(changes):
    profile, rows = scan(compressed([record(**changes)]))
    assert profile.rejected_count == 1
    assert rows[0].raw_record_hex == record(**changes).hex()
    assert "native_provider_inconsistent" in rows[0].reasons


def test_valid_opra_trade_and_reserved_bytes_remain_lossless():
    value = bytearray(record(action="T", publisher_id=20, side=dbn.Side.NONE, flags=129))
    value[31] = 27
    profile, rows = scan(compressed([bytes(value)]))
    assert profile.accepted_count == 1
    assert rows[0].raw_record_hex == value.hex()


@pytest.mark.parametrize("field", ["bid_pb", "ask_pb"])
def test_consolidator_cannot_be_a_best_quote_participant(field):
    levels = dict(bid_px=1000000001, ask_px=1200000003, bid_sz=2, ask_sz=3, bid_pb=20, ask_pb=22)
    levels[field] = 30
    raw = record(levels=dbn.ConsolidatedBidAskPair(**levels))
    profile, rows = scan(compressed([raw]))
    assert profile.accepted_count == 0 and profile.rejected_count == 1
    assert "native_provider_inconsistent" in rows[0].reasons
    assert rows[0].raw_record_hex == raw.hex()
    with pytest.raises(DatabentoImportError):
        replace(rows[0], reasons=(), disposition="accepted")


def test_event_time_outside_window_does_not_replace_receive_index():
    profile, rows = scan(compressed([record(stamp=1)]))
    assert profile.accepted_count == 1
    assert rows[0].ts_event == 1


def test_cmbp_nanosecond_ties_are_distinct_even_with_identical_bytes():
    values = [record(), record(), record(bid=1000000002), record(recv=STAMP + 2)]
    profile, rows = scan(compressed(values))
    assert [row.record_ordinal for row in rows] == [0, 1, 2, 3]
    assert profile.decoded_count == profile.accepted_count == 4
    assert profile.adjacent_repeat_count == 1  # Diagnostic only, never deduplicated.


def test_mbp_shared_sequence_and_same_time_variants_are_not_collapsed():
    value = record(underlying=True)
    variant = record(underlying=True, bid=1000000002)
    profile, rows = scan(compressed([value, value, variant], underlying=True), underlying=True)
    assert profile.adjacent_repeat_count == 1
    assert profile.accepted_count == 3
    assert [row.record_ordinal for row in rows] == [0, 1, 2]


@pytest.mark.parametrize(
    "changes",
    [
        {"schema": dbn.Schema.OHLCV_1M},
        {"dataset": "XNAS.ITCH"},
        {"symbols": ["OTHER"]},
        {"end": END + 1},
        {"ts_out": True},
        {"partial": ["SPY"]},
        {"mappings": []},
    ],
)
def test_metadata_mismatch_denies(changes):
    with pytest.raises(DatabentoImportError):
        scan(compressed(metadata_changes=changes))


@pytest.mark.parametrize(
    "change",
    [
        "truncated_zstd",
        "truncated_record",
        "wrong_rtype",
        "unmapped",
        "out_of_window",
        "backward",
        "unknown_action",
    ],
)
def test_structurally_invalid_archives_deny(change):
    body = compressed()
    if change == "truncated_zstd":
        body = body[:-1]
    elif change == "truncated_record":
        body = zstd.ZstdCompressor().compress(native()[:-1])
    elif change == "wrong_rtype":
        body = compressed([record(underlying=True)])
    elif change == "unmapped":
        body = compressed([record(instrument_id=43)])
    elif change == "out_of_window":
        body = compressed([record(recv=END)])
    elif change == "backward":
        body = compressed([record(recv=STAMP + 2), record(recv=STAMP + 1)])
    else:
        value = bytearray(record())
        value[28] = ord("?")
        body = compressed([bytes(value)])
    with pytest.raises(DatabentoImportError):
        scan(body)


@pytest.mark.parametrize(
    "field,maximum",
    [
        ("max_compressed_bytes", 10),
        ("max_decompressed_bytes", 100),
        ("max_records", 1),
        ("max_metadata_bytes", 100),
    ],
)
def test_all_native_resource_bounds_apply(field, maximum):
    limits = replace(DefinitionLimits(), **{field: maximum})
    with pytest.raises(DatabentoImportError):
        scan(compressed([record(), record(recv=STAMP + 2)]), limits=limits)


@pytest.mark.parametrize(
    "changes",
    [
        {"dataset": "OTHER"},
        {"schema": "bbo-1m"},
        {"stype_in": "parent"},
        {"symbols": ("ALL_SYMBOLS",)},
        {"start_ns": True},
        {"symbols": ["SPY"]},
    ],
)
def test_closed_request_rejects_unsupported_scope(changes):
    with pytest.raises(DatabentoImportError):
        replace(request(), **changes)


def test_mutable_or_float_row_fields_deny():
    _, rows = scan()
    for changes in (
        {"bid_px": 1.2},
        {"flags": True},
        {"reasons": []},
        {"raw_record_hex": "00"},
        {"record_ordinal": -1},
    ):
        with pytest.raises(DatabentoImportError):
            replace(rows[0], **changes)


def test_missing_modules_are_an_observable_red_failure():
    assert module("quote_wire").SCHEMA == "native-quotes-v1"
