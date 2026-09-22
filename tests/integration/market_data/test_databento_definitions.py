"""Official offline decoder, synthetic versioned bytes, no licensed fixtures or network."""

import hashlib
import importlib
import inspect
import io
import struct
from dataclasses import replace

import pytest

from tests.unit.market_data.test_databento_batch import END, START, no_network  # noqa: F401
from trading_bot.market_data.databento_batch import DatabentoImportError, DefinitionRequest

dbn = pytest.importorskip("databento_dbn")
zstd = pytest.importorskip("zstandard")
REQUEST = DefinitionRequest("SPY.OPT", START, END)


def api():
    try:
        return importlib.import_module("trading_bot.market_data.databento_definitions")
    except ModuleNotFoundError:
        pytest.fail("strict offline DBN definition decoder is not implemented")


def fixture(version=3, *, metadata_changes=None, record_changes=None, count=2):
    meta = dict(
        dataset="OPRA.PILLAR",
        start=START,
        end=END,
        stype_in=dbn.SType.PARENT,
        stype_out=dbn.SType.INSTRUMENT_ID,
        schema=dbn.Schema.DEFINITION,
        symbols=["SPY.OPT"],
        version=version,
    )
    meta.update(metadata_changes or {})
    fields = dict(
        publisher_id=1,
        instrument_id=42,
        ts_event=1672704000000000001,
        ts_recv=1672704000000000002,
        min_price_increment=10000000,
        display_factor=1000000000,
        raw_symbol="SPY   230120C00400000",
        asset="SPY",
        security_type="OPT",
        instrument_class=dbn.InstrumentClass.CALL,
        security_update_action=dbn.SecurityUpdateAction.ADD,
        strike_price=400123456789,
        expiration=1674172800000000000,
    )
    fields.update(record_changes or {})
    record = dbn.InstrumentDefMsg(**fields)
    if version < 3:
        cls = dbn.InstrumentDefMsgV1 if version == 1 else dbn.InstrumentDefMsgV2
        record = cls(
            **{
                name: getattr(record, name, 0)
                for name, parameter in inspect.signature(cls).parameters.items()
                if parameter.default is inspect.Parameter.empty
            }
        )
    return dbn.Metadata(**meta).encode() + bytes(record) * count


def scan(raw, *, compressed=None, limits=None):
    module = api()
    body = (
        zstd.ZstdCompressor(write_checksum=True).compress(raw) if compressed is None else compressed
    )
    rows = []
    result = module.scan_definitions(
        io.BytesIO(body),
        expected=REQUEST,
        expected_sha256=hashlib.sha256(body).hexdigest(),
        limits=limits or module.DefinitionLimits(),
        consume=rows.append,
    )
    return result, rows


@pytest.mark.parametrize("version", [1, 2, 3])
def test_all_supported_versions_preserve_exact_native_units_and_original_record_hash(version):
    raw = fixture(version)
    profile, rows = scan(raw)
    assert profile["record_count"] == 2
    assert profile["dbn_version"] == version
    assert profile["record_validation_complete"] is True
    assert profile["economic_evidence"] is False
    assert profile["production_eligible"] is False
    assert profile["complete_chains_verified"] is False
    assert rows[0]["ts_recv"] == 1672704000000000002
    assert rows[0]["strike_price"] == 400123456789
    assert rows[0]["raw_symbol"] == "SPY   230120C00400000"
    assert rows[0]["record_ordinal"] == 0 and rows[1]["record_ordinal"] == 1
    size = {1: 360, 2: 400, 3: 520}[version]
    assert rows[0]["record_sha256"] == hashlib.sha256(raw[-size:]).hexdigest()
    assert profile["unknown_premium_multiplier_rows"] == 2
    assert "available_at" not in rows[0]


@pytest.mark.parametrize(
    "change",
    [
        {"symbols": ["QQQ.OPT"]},
        {"limit": 1},
        {"end": END - 1},
        {"not_found": ["SPY.OPT"]},
        {"schema": dbn.Schema.MBP_1},
        {"ts_out": True},
        {"dataset": "WRONG"},
    ],
)
def test_header_scope_mismatch_and_partial_selection_denied(change):
    with pytest.raises(DatabentoImportError):
        scan(fixture(metadata_changes=change))


@pytest.mark.parametrize("cut", [1, 7, 100, -1, -100])
def test_truncated_dbn_never_returns_complete_profile(cut):
    with pytest.raises(DatabentoImportError):
        scan(fixture()[:cut])


@pytest.mark.parametrize("cut", [1, 4, 20])
def test_truncated_zstd_footer_or_payload_never_returns_complete_profile(cut):
    body = zstd.ZstdCompressor(write_checksum=True).compress(fixture())
    with pytest.raises(DatabentoImportError):
        scan(b"", compressed=body[:-cut])


def test_concatenated_frames_work_but_trailing_garbage_and_extra_record_bytes_do_not():
    raw = fixture()
    compressor = zstd.ZstdCompressor(write_checksum=True)
    compressed = compressor.compress(raw[:203]) + compressor.compress(raw[203:])
    assert scan(b"", compressed=compressed)[0]["record_count"] == 2
    for body in [compressed + b"garbage", compressor.compress(raw + b"x")]:
        with pytest.raises(DatabentoImportError):
            scan(b"", compressed=body)


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_records", 1),
        ("max_compressed_bytes", 1),
        ("max_decompressed_bytes", 100),
        ("max_metadata_bytes", 120),
    ],
)
def test_explicit_resource_limits_are_enforced(field, value):
    with pytest.raises(DatabentoImportError, match="databento_limit_exceeded"):
        scan(fixture(), limits=replace(api().DefinitionLimits(), **{field: value}))


def test_tampered_metadata_length_unsupported_record_and_empty_stream_fail():
    raw = fixture()
    for bad in [raw[:4] + struct.pack("<I", 1) + raw[8:], raw[:200], raw[:200] + b"\x01\x13\0\0"]:
        with pytest.raises(DatabentoImportError):
            scan(bad)


def test_native_sentinels_and_delete_updates_retained_without_inventing_contracts():
    _, rows = scan(
        fixture(
            record_changes={
                "strike_price": 2**63 - 1,
                "expiration": 2**64 - 1,
                "security_update_action": dbn.SecurityUpdateAction.DELETE,
            }
        )
    )
    assert rows[0]["strike_price"] is None
    assert rows[0]["expiration"] is None
    assert rows[0]["security_update_action"] == "D"
    assert rows[0]["contract_multiplier"] is None


def test_out_of_window_events_are_disclosed_not_relabelled_as_available():
    profile, rows = scan(fixture(record_changes={"ts_event": START - 1, "ts_recv": START - 1}))
    assert profile["outside_requested_receive_window_rows"] == 2
    assert rows[0]["ts_recv"] == START - 1


def test_wrong_expected_file_digest_rejects_even_well_formed_data():
    module = api()
    with pytest.raises(DatabentoImportError):
        module.scan_definitions(
            io.BytesIO(zstd.ZstdCompressor().compress(fixture())),
            expected=REQUEST,
            expected_sha256="0" * 64,
            limits=module.DefinitionLimits(),
        )


def mapped_fixture(*, start_date=20230103, end_date=20230104, mapping_count=1):
    raw = fixture(1)
    header_end = 8 + struct.unpack("<I", raw[4:8])[0]
    # Hand-encoded single mapping; V1 symbol width22 and interval width30.
    body = raw[8 : header_end - 4] + struct.pack("<I", mapping_count)
    body += b"SPY   230120C00400000\0" + struct.pack("<I", 1)
    body += struct.pack("<II", start_date, end_date) + b"42" + b"\0" * 20
    return b"DBN\x01" + struct.pack("<I", len(body)) + body + raw[header_end:]


def test_large_metadata_mapping_scanner_does_not_claim_resolved_mappings():
    profile, _ = scan(mapped_fixture())
    assert profile["metadata"]["mapping_count"] == 1
    assert profile["metadata"]["mapping_interval_count"] == 1
    assert profile["metadata"]["mapping_resolution_verified"] is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"start_date": 20230230},
        {"end_date": 20230103},
        {"mapping_count": 2},
    ],
)
def test_invalid_mapping_dates_counts_and_intervals_fail_closed(kwargs):
    with pytest.raises(DatabentoImportError):
        scan(mapped_fixture(**kwargs))


def test_streaming_decoder_accepts_bounded_multimegabyte_zstd_window():
    profile, rows = scan(fixture(count=10000))
    assert profile["record_count"] == len(rows) == 10000


def test_partial_symbol_resolution_is_preserved_as_a_non_executable_staging_limitation():
    profile, rows = scan(fixture(metadata_changes={"partial": ["SPY   230120C00400000"]}))
    assert len(rows) == 2
    assert profile["metadata"]["partial_symbol_count"] == 1
    assert profile["complete_chains_verified"] is False
    assert profile["historical_availability_verified"] is False
    assert profile["production_eligible"] is False
