"""Strict, credential-free wire contract for one options data record."""

import importlib
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import cast

import pytest

from tests.unit.domain.test_options import NOW, contract, quote
from trading_bot.domain import CorporateAction, DataHash, InstrumentId, Quote, TimestampSource
from trading_bot.domain.options import OptionQuote
from trading_bot.market_data.bundle_models import BundleError, BundleLimits
from trading_bot.market_data.options_data_codec import decode_record, encode_record
from trading_bot.market_data.options_records import ChainSnapshot, OptionsDataRecord

LIMITS = BundleLimits(65536, 65536, 262144, 100, 16)


def underlying_quote() -> Quote:
    return Quote(
        InstrumentId("SYN"),
        NOW,
        Decimal("99"),
        Decimal("101"),
        Decimal("100"),
        "synthetic",
        DataHash("e" * 64),
        True,
        TimestampSource.SIMULATED,
    )


def corporate_action() -> CorporateAction:
    return CorporateAction(
        InstrumentId("SYN"),
        "dividend",
        NOW.date(),
        NOW - timedelta(days=1),
        None,
        Decimal("0.5"),
        DataHash("d" * 64),
    )


def data_record(value: object) -> OptionsDataRecord:
    event_at = value.event_at if type(value) is OptionQuote else NOW
    if type(value) is Quote:
        event_at = value.observed_at
    return OptionsDataRecord(
        "fixture",
        "synthetic",
        "f" * 64,
        event_at,
        NOW,
        value,  # type: ignore[arg-type]
    )


def wire_record(record: OptionsDataRecord) -> dict[str, object]:
    return cast(dict[str, object], json.loads(encode_record(record)))


def encoded(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()


def test_codec_exposes_the_frozen_record_api() -> None:
    codec = importlib.import_module("trading_bot.market_data.options_data_codec")
    assert callable(codec.encode_record)
    assert callable(codec.decode_record)


@pytest.mark.parametrize(
    "value",
    [
        ChainSnapshot("SYN", ("synthetic-call-100",)),
        contract(),
        quote(),
        contract().eligible_sessions[0],
        underlying_quote(),
        corporate_action(),
    ],
    ids=["chain", "contract", "option_quote", "session", "underlying_quote", "corporate_action"],
)
def test_all_record_kinds_round_trip_through_the_exact_versioned_envelope(value: object) -> None:
    original = data_record(value)
    body = encode_record(original)
    wire = cast(dict[str, object], json.loads(body))

    assert set(wire) == {"schema", "kind", "record", "record_hash"}
    assert wire["schema"] == "options-data-record-v1"
    assert wire["kind"] == original.kind
    assert wire["record_hash"] == original.record_hash
    assert set(cast(dict[str, object], wire["record"])) == {
        "source",
        "source_kind",
        "raw_hash",
        "event_at",
        "available_at",
        "value",
    }
    assert decode_record(body, limits=LIMITS) == original
    assert encode_record(decode_record(body, limits=LIMITS)) == body


@pytest.mark.parametrize("layer", ["envelope", "record", "value"])
def test_unknown_fields_are_rejected_at_every_layer_without_value_leaks(layer: str) -> None:
    wire = wire_record(data_record(quote()))
    target = wire
    if layer == "record":
        target = cast(dict[str, object], wire["record"])
    elif layer == "value":
        target = cast(dict[str, object], cast(dict[str, object], wire["record"])["value"])
    target["auth_header"] = "private-payload-marker"

    with pytest.raises(BundleError) as caught:
        decode_record(encoded(wire), limits=LIMITS)

    assert caught.value.args in (("bundle_schema_invalid",), ("bundle_value_invalid",))
    assert "auth_header" not in str(caught.value)
    assert "private-payload-marker" not in str(caught.value)


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("event_at", "2026-09-18T15:00:00+00:00"),
        ("available_at", "2026-09-18T15:00:00.000000+00:00"),
    ],
)
def test_noncanonical_record_times_are_rejected(field: str, bad: str) -> None:
    wire = wire_record(data_record(quote()))
    cast(dict[str, object], wire["record"])[field] = bad
    with pytest.raises(BundleError):
        decode_record(encoded(wire), limits=LIMITS)


@pytest.mark.parametrize("bad", ["0.20", "2e-1", 0.2])
def test_noncanonical_or_binary_option_quote_decimals_are_rejected(bad: object) -> None:
    wire = wire_record(data_record(quote()))
    value = cast(dict[str, object], cast(dict[str, object], wire["record"])["value"])
    value["bid"] = bad
    with pytest.raises(BundleError):
        decode_record(encoded(wire), limits=LIMITS)


def test_record_hash_and_kind_must_match_the_reconstructed_value() -> None:
    wire = wire_record(data_record(quote()))
    wire["record_hash"] = "0" * 64
    with pytest.raises(BundleError, match=r"^bundle_hash_mismatch$"):
        decode_record(encoded(wire), limits=LIMITS)

    wire = wire_record(data_record(quote()))
    wire["kind"] = "underlying_quote"
    with pytest.raises(BundleError):
        decode_record(encoded(wire), limits=LIMITS)


@pytest.mark.parametrize(
    "body",
    [
        b'{"schema":"options-data-record-v1","schema":"duplicate"}',
        b'{"schema":NaN}',
        b'{"schema":Infinity}',
        b'{"schema":-Infinity}',
        b'{"schema":1.25}',
        b'{"schema":1e2}',
        b"\xff",
        b"{",
        b"{} trailing",
        b'[{"nested":[]}]',
    ],
)
def test_ambiguous_or_malformed_json_is_rejected(body: bytes) -> None:
    with pytest.raises(BundleError):
        decode_record(body, limits=LIMITS)


def test_schema_origin_and_digest_fields_are_exact_and_errors_are_sanitized() -> None:
    wire = wire_record(data_record(quote()))
    wire["schema"] = "options-data-record-v2"
    with pytest.raises(BundleError, match=r"^bundle_schema_invalid$"):
        decode_record(encoded(wire), limits=LIMITS)

    wire = wire_record(data_record(quote()))
    record = cast(dict[str, object], wire["record"])
    record["source_kind"] = "authenticated"
    record["raw_hash"] = "private-payload-marker"
    with pytest.raises(BundleError) as caught:
        decode_record(encoded(wire), limits=LIMITS)
    assert caught.value.args == ("bundle_value_invalid",)
    assert "private-payload-marker" not in str(caught.value)


def test_bytes_depth_and_chain_count_are_bounded_by_bundle_limits() -> None:
    chain = data_record(ChainSnapshot("SYN", ("one", "two")))
    body = encode_record(chain)
    for limits in (
        replace(LIMITS, max_envelope_bytes=len(body) - 1),
        replace(LIMITS, max_json_depth=3),
        replace(LIMITS, max_records=1),
    ):
        with pytest.raises(BundleError, match=r"^bundle_input_too_large$"):
            decode_record(body, limits=limits)


def test_non_bytes_and_invalid_limits_are_rejected_without_coercion() -> None:
    body = encode_record(data_record(quote()))
    with pytest.raises(BundleError):
        decode_record("private-payload-marker", limits=LIMITS)  # type: ignore[arg-type]
    with pytest.raises(BundleError, match=r"^bundle_limits_invalid$"):
        decode_record(body, limits=object())  # type: ignore[arg-type]
