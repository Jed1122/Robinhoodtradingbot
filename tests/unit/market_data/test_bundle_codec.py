import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from trading_bot.domain import BarInterval
from trading_bot.market_data.bundle_codec import decode_envelope, encode_envelope
from trading_bot.market_data.bundle_models import BundleError, BundleLimits

NOW = datetime(2026, 1, 1, tzinfo=UTC)
END = NOW + timedelta(days=1)
LIMITS = BundleLimits(65536, 65536, 262144, 100, 16)


def wire_envelope() -> dict:
    start = "2026-01-01T00:00:00.000000Z"
    end = "2026-01-02T00:00:00.000000Z"
    rows = [
        (
            "bar",
            {
                "instrument_id": "SYNTH",
                "interval": "one_day",
                "starts_at": start,
                "ends_at": end,
                "open": "10",
                "high": "11",
                "low": "9",
                "close": "10",
                "volume": "100",
                "source": "fixture",
                "data_hash": "b" * 64,
                "interpolated": False,
            },
        ),
        (
            "membership",
            {
                "instrument_id": "SYNTH",
                "effective_at": start,
                "announced_at": start,
                "included": True,
            },
        ),
        (
            "baseline",
            {
                "instrument_id": "SYNTH",
                "coverage_start": start,
                "effective_at": start,
                "announced_at": start,
                "included": True,
            },
        ),
        (
            "corporate_action",
            {
                "instrument_id": "SYNTH",
                "action_type": "split",
                "effective_date": "2026-01-01",
                "announced_at": start,
                "split_ratio": "2",
                "cash_amount": None,
                "data_hash": "b" * 64,
            },
        ),
        (
            "coverage",
            {
                "instrument_id": "SYNTH",
                "record_kind": "bar",
                "interval": "one_day",
                "starts_at": start,
                "ends_at": end,
                "state": "complete",
                "expected_slots": [{"starts_at": start, "ends_at": end}],
            },
        ),
    ]
    records = [
        {
            "kind": kind,
            "source_hash": "a" * 64,
            "locator": index,
            "available_at": end,
            "price_basis": "unadjusted" if kind == "bar" else None,
            "value": value,
            "record_hash": "b" * 64,
        }
        for index, (kind, value) in enumerate(rows)
    ]
    return {
        "schema": "research-bundle-v1",
        "classification": "synthetic",
        "instruments": [{"instrument_id": "SYNTH", "symbol": "SYNTH"}],
        "sources": [
            {
                "source_id": "fixture",
                "format_id": "synthetic-market-v1",
                "normalizer_version": "synthetic-normalizer-v1",
                "origin": "synthetic",
                "instrument_ids": ["SYNTH"],
                "record_kinds": [kind for kind, _ in rows],
                "requested_start": start,
                "requested_end": end,
                "collected_at": end,
                "claimed_published_at": None,
                "limitation_codes": [],
                "byte_length": 2,
                "blob_sha256": "a" * 64,
                "descriptor_hash": "a" * 64,
            }
        ],
        "records": records,
        "manifest": {
            "raw_hashes": ["a" * 64],
            "cleaned_hashes": ["b" * 64],
            "corporate_action_coverage": "declared_unverified",
            "point_in_time_universe": False,
            "survivorship_limitations": [],
            "licensing_limitations": [],
            "known_gaps": [],
            "manifest_hash": "c" * 64,
        },
        "limitation_codes": ["synthetic_data"],
        "bundle_hash": "d" * 64,
    }


def encoded(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


@pytest.mark.parametrize(
    "key,bad",
    [
        ("format_id", "future-market-v2"),
        ("normalizer_version", "future-normalizer-v2"),
        ("origin", "imported"),
    ],
)
def test_unsupported_source_contract_is_rejected(key: str, bad: str) -> None:
    wire = wire_envelope()
    wire["sources"][0][key] = bad
    with pytest.raises(BundleError, match=r"^bundle_source_unsupported$") as caught:
        decode_envelope(encoded(wire), limits=LIMITS)
    assert caught.value.args == ("bundle_source_unsupported",)


@pytest.mark.parametrize("field", ["locator", "byte_length"])
def test_negative_zero_integer_is_not_coerced(field: str) -> None:
    wire = wire_envelope()
    wire["sources"][0]["byte_length"] = 0
    body = encoded(wire).replace(f'"{field}":0'.encode(), f'"{field}":-0'.encode())
    with pytest.raises(BundleError, match=r"^bundle_json_invalid$"):
        decode_envelope(body, limits=LIMITS)


def test_duplicate_source_descriptors_are_rejected_but_shared_blobs_are_allowed() -> None:
    wire = wire_envelope()
    wire["sources"].append(deepcopy(wire["sources"][0]))
    with pytest.raises(BundleError, match=r"^bundle_value_invalid$"):
        decode_envelope(encoded(wire), limits=LIMITS)
    wire["sources"][1]["descriptor_hash"] = "e" * 64
    wire["sources"][1]["claimed_published_at"] = "2026-01-01T00:00:00.000000Z"
    assert len(decode_envelope(encoded(wire), limits=LIMITS).sources) == 2


def test_codec_reconstructs_every_record_kind_without_claiming_hash_verification() -> None:
    wire = wire_envelope()
    result = decode_envelope(encoded(wire), limits=LIMITS)
    assert result.records[0].value.interval is BarInterval.ONE_DAY
    assert result.records[0].value.starts_at == NOW
    assert str(result.records[0].value.close) == "10"
    assert result.records[3].value.effective_date.isoformat() == "2026-01-01"
    assert tuple(record.kind for record in result.records) == (
        "bar",
        "membership",
        "baseline",
        "corporate_action",
        "coverage",
    )
    assert encode_envelope(result) == encoded(wire)
    assert decode_envelope(encode_envelope(result), limits=LIMITS) == result


@pytest.mark.parametrize(
    "body",
    [
        b'{"schema":"a","schema":"b"}',
        b'{"schema":NaN}',
        b'{"schema":Infinity}',
        b'{"schema":1.25}',
        b'{"schema":1e2}',
        b"\xff",
        b"{",
        b"{} trailing",
        b'{"nested":{"a":1,"a":2}}',
    ],
)
def test_ambiguous_or_non_json_input_fails_before_schema(body: bytes) -> None:
    with pytest.raises(BundleError, match=r"^bundle_json_invalid$"):
        decode_envelope(body, limits=LIMITS)


@pytest.mark.parametrize("body", [b"[]", b"null", b"{}", b'{"schema":"unknown"}'])
def test_unknown_or_incomplete_envelope_is_not_inferred(body: bytes) -> None:
    with pytest.raises(BundleError, match=r"^bundle_schema_invalid$"):
        decode_envelope(body, limits=LIMITS)


@pytest.mark.parametrize(
    "path", [(), ("sources", 0), ("records", 0), ("records", 0, "value"), ("manifest",)]
)
def test_unknown_fields_are_rejected_at_each_layer(path: tuple) -> None:
    wire = wire_envelope()
    target = wire
    for key in path:
        target = target[key]
    target["auth_header"] = "private-payload-marker"
    with pytest.raises(BundleError) as caught:
        decode_envelope(encoded(wire), limits=LIMITS)
    assert "private-payload-marker" not in str(caught.value)
    assert "auth_header" not in str(caught.value)


@pytest.mark.parametrize(
    "key,bad",
    [
        ("close", "NaN"),
        ("close", "1e2"),
        ("close", "10.0"),
        ("close", 10),
        ("close", "1" * 513),
        ("interpolated", 0),
        ("starts_at", "2026-01-01"),
        ("starts_at", "2026-01-01T00:00:00+00:00"),
        ("interval", "daily"),
        ("data_hash", "../outside"),
        ("source", "Bearer secret"),
    ],
)
def test_noncanonical_bar_fields_are_not_coerced(key: str, bad: object) -> None:
    wire = wire_envelope()
    wire["records"][0]["value"][key] = bad
    with pytest.raises(BundleError):
        decode_envelope(encoded(wire), limits=LIMITS)


@pytest.mark.parametrize(
    "changes",
    [
        {"locator": True},
        {"kind": "quote"},
        {"available_at": "yesterday"},
        {"price_basis": None},
        {"source_hash": "invalid"},
    ],
)
def test_normalized_entry_requires_typed_discriminator_and_provenance(changes: dict) -> None:
    wire = wire_envelope()
    wire["records"][0].update(changes)
    with pytest.raises(BundleError):
        decode_envelope(encoded(wire), limits=LIMITS)


def test_duplicate_instrument_mapping_is_rejected() -> None:
    wire = wire_envelope()
    wire["instruments"].append(deepcopy(wire["instruments"][0]))
    with pytest.raises(BundleError):
        decode_envelope(encoded(wire), limits=LIMITS)


def test_bytes_depth_and_record_limits_are_enforced() -> None:
    body = encoded(wire_envelope())
    for limits in (
        replace(LIMITS, max_envelope_bytes=len(body) - 1),
        replace(LIMITS, max_json_depth=2),
        replace(LIMITS, max_records=4),
    ):
        with pytest.raises(BundleError, match=r"^bundle_input_too_large$"):
            decode_envelope(body, limits=limits)


def test_braces_inside_strings_do_not_count_as_nesting() -> None:
    wire = wire_envelope()
    # A bad label should reach value validation, rather than trip the nesting scanner.
    wire["sources"][0]["source_id"] = "[" * 20
    with pytest.raises(BundleError) as caught:
        decode_envelope(encoded(wire), limits=LIMITS)
    assert caught.value.code == "bundle_value_invalid"


def test_non_bytes_input_is_rejected_without_stringification() -> None:
    with pytest.raises(BundleError):
        decode_envelope("private-payload-marker", limits=LIMITS)  # type: ignore[arg-type]
