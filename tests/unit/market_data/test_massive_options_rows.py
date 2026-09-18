"""Strict, credential-free Massive REST options quote row parsing."""

import json
from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from trading_bot.market_data.bundle_models import BundleError, BundleLimits
from trading_bot.market_data.massive_options_rows import (
    MASSIVE_OPTIONS_REST_SOURCE,
    MASSIVE_OPTIONS_SIZE_UNIT,
    MassiveOptionsQuoteRow,
    parse_massive_options_quote_row,
)

LIMITS = BundleLimits(4096, 4096, 8192, 100, 8)


def body(**overrides: object) -> bytes:
    row: dict[str, object] = {
        "ask_exchange": 301,
        "ask_price": 1.25,
        "ask_size": 2,
        "bid_exchange": 316,
        "bid_price": 1.2,
        "bid_size": 1,
        "sequence_number": 99,
        "sip_timestamp": 1_725_621_234_567_890_123,
    }
    row.update(overrides)
    return json.dumps(row, separators=(",", ":")).encode("utf-8")


def direct_row(**overrides: object) -> MassiveOptionsQuoteRow:
    values: dict[str, object] = {
        "bid_price": Decimal("1.2"),
        "ask_price": Decimal("1.25"),
        "bid_size": Decimal("1"),
        "ask_size": Decimal("2"),
        "bid_exchange": 316,
        "ask_exchange": 301,
        "sequence_number": 99,
        "sip_timestamp": 1_725_621_234_567_890_123,
    }
    values.update(overrides)
    return MassiveOptionsQuoteRow(**values)  # type: ignore[arg-type]


def test_parse_preserves_exact_decimal_prices_native_sizes_and_nanosecond_timestamp() -> None:
    result = parse_massive_options_quote_row(body(), limits=LIMITS)

    assert result == MassiveOptionsQuoteRow(
        bid_price=Decimal("1.2"),
        ask_price=Decimal("1.25"),
        bid_size=Decimal("1"),
        ask_size=Decimal("2"),
        bid_exchange=316,
        ask_exchange=301,
        sequence_number=99,
        sip_timestamp=1_725_621_234_567_890_123,
    )
    assert result.source == MASSIVE_OPTIONS_REST_SOURCE
    assert result.size_unit == MASSIVE_OPTIONS_SIZE_UNIT
    assert result.sip_timestamp == 1_725_621_234_567_890_123
    assert result.bid_size == Decimal("1")
    assert result.ask_size == Decimal("2")


@pytest.mark.parametrize("field", ["bid_price", "ask_price", "bid_size", "ask_size"])
@pytest.mark.parametrize("bad", [1, 1.0, True, "1"])
def test_direct_construction_requires_exact_decimal_quote_values(field: str, bad: object) -> None:
    with pytest.raises(BundleError, match=r"^bundle_value_invalid$"):
        direct_row(**{field: bad})


def test_direct_construction_retains_exact_decimal_values_and_is_immutable() -> None:
    bid = Decimal("1.20")
    result = direct_row(bid_price=bid)

    assert result.bid_price is bid
    with pytest.raises(FrozenInstanceError):
        result.bid_price = Decimal("2")  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("source", "other_provider"),
        ("size_unit", "option_contracts"),
    ],
)
def test_direct_source_and_size_labels_cannot_be_overridden_inconsistently(
    field: str, bad: object
) -> None:
    with pytest.raises(BundleError, match=r"^bundle_value_invalid$"):
        direct_row(**{field: bad})


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("bid_price", -1),
        ("ask_price", -1),
        ("bid_size", -1),
        ("ask_size", -1),
        ("bid_size", 1.5),
        ("ask_size", 1.5),
        ("bid_exchange", -1),
        ("ask_exchange", -1),
        ("sequence_number", -1),
        ("sip_timestamp", -1),
    ],
)
def test_nonnegative_integral_subset_is_enforced(field: str, bad: object) -> None:
    with pytest.raises(BundleError, match=r"^bundle_value_invalid$"):
        parse_massive_options_quote_row(body(**{field: bad}), limits=LIMITS)


def test_zero_bid_is_preserved_but_crossed_prices_are_rejected() -> None:
    assert parse_massive_options_quote_row(body(bid_price=0), limits=LIMITS).bid_price == 0
    locked = parse_massive_options_quote_row(
        body(bid_price=1, ask_price=1, bid_size=0, ask_size=0), limits=LIMITS
    )
    assert locked.bid_size == locked.ask_size == 0

    with pytest.raises(BundleError, match=r"^bundle_value_invalid$"):
        parse_massive_options_quote_row(body(bid_price=2, ask_price=1), limits=LIMITS)


@pytest.mark.parametrize(
    "payload",
    [
        body(unexpected="secret-marker"),
        body(ask_exchange=True),
        body(bid_price="1.2"),
        b'{"bid_price":NaN}',
        b'{"bid_price":1,"bid_price":2}',
        b"{",
        b"\xff",
    ],
)
def test_malformed_or_non_schema_input_is_rejected_without_echoing_input(payload: bytes) -> None:
    with pytest.raises(BundleError) as caught:
        parse_massive_options_quote_row(payload, limits=LIMITS)

    assert "secret-marker" not in str(caught.value)


def test_limits_are_enforced_and_invalid_limits_fail_closed() -> None:
    with pytest.raises(BundleError, match=r"^bundle_input_too_large$"):
        parse_massive_options_quote_row(body(), limits=BundleLimits(1, 1, 1, 1, 1))

    with pytest.raises(BundleError, match=r"^bundle_limits_invalid$"):
        parse_massive_options_quote_row(body(), limits=object())  # type: ignore[arg-type]


def test_long_fractional_json_literal_is_bounded_without_float_rounding() -> None:
    payload = body().replace(b'"bid_price":1.2', b'"bid_price":0.' + b"1" * 2000)

    with pytest.raises(BundleError, match=r"^bundle_value_invalid$"):
        parse_massive_options_quote_row(payload, limits=LIMITS)


def test_excessive_json_depth_is_rejected_before_schema_interpretation() -> None:
    with pytest.raises(BundleError, match=r"^bundle_input_too_large$"):
        parse_massive_options_quote_row(b"[" * 9 + b"]" * 9, limits=LIMITS)


def test_absent_required_field_is_rejected() -> None:
    wire = json.loads(body())
    del wire["sip_timestamp"]

    with pytest.raises(BundleError, match=r"^bundle_schema_invalid$"):
        parse_massive_options_quote_row(json.dumps(wire).encode(), limits=LIMITS)
