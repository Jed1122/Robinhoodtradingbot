"""Strict, credential-free parsing of one Massive REST options quote row.

This module only preserves documented provider-row values.  It has no transport,
credentials, contract lookup, receipt time, or executable-quote conversion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, NoReturn, cast

from trading_bot.domain.decimal_utils import DomainValidationError, require_bounded_decimal
from trading_bot.market_data.bundle_codec import _object
from trading_bot.market_data.bundle_models import BundleError, BundleLimits, _check

type MassiveOptionsRestSource = Literal["massive_options_rest_v3"]
type MassiveOptionsSizeUnit = Literal["provider_documented_round_lot_orders"]
MASSIVE_OPTIONS_REST_SOURCE: MassiveOptionsRestSource = "massive_options_rest_v3"
MASSIVE_OPTIONS_SIZE_UNIT: MassiveOptionsSizeUnit = "provider_documented_round_lot_orders"
_FIELDS = {
    "ask_exchange",
    "ask_price",
    "ask_size",
    "bid_exchange",
    "bid_price",
    "bid_size",
    "sequence_number",
    "sip_timestamp",
}


@dataclass(frozen=True, slots=True)
class MassiveOptionsQuoteRow:
    """One provider row; sizes retain the documented provider-native round-lot count."""

    bid_price: Decimal
    ask_price: Decimal
    bid_size: Decimal
    ask_size: Decimal
    bid_exchange: int
    ask_exchange: int
    sequence_number: int
    sip_timestamp: int
    source: MassiveOptionsRestSource = MASSIVE_OPTIONS_REST_SOURCE
    size_unit: MassiveOptionsSizeUnit = MASSIVE_OPTIONS_SIZE_UNIT

    def __post_init__(self) -> None:
        _price(self.bid_price)
        _price(self.ask_price)
        _size(self.bid_size)
        _size(self.ask_size)
        _nonnegative_integer(self.bid_exchange)
        _nonnegative_integer(self.ask_exchange)
        _nonnegative_integer(self.sequence_number)
        _nonnegative_integer(self.sip_timestamp)
        _check(self.bid_price <= self.ask_price)
        _check(self.source == MASSIVE_OPTIONS_REST_SOURCE)
        _check(self.size_unit == MASSIVE_OPTIONS_SIZE_UNIT)


def parse_massive_options_quote_row(body: bytes, *, limits: BundleLimits) -> MassiveOptionsQuoteRow:
    """Parse one exact Massive REST result row without I/O or domain conversion."""
    _check(type(limits) is BundleLimits, "bundle_limits_invalid")
    try:
        row = _mapping(_json_decimal(body, limits=limits), _FIELDS)
        return MassiveOptionsQuoteRow(
            bid_price=_decimal_from_json_number(row["bid_price"]),
            ask_price=_decimal_from_json_number(row["ask_price"]),
            bid_size=_decimal_from_json_number(row["bid_size"]),
            ask_size=_decimal_from_json_number(row["ask_size"]),
            bid_exchange=_nonnegative_integer(row["bid_exchange"]),
            ask_exchange=_nonnegative_integer(row["ask_exchange"]),
            sequence_number=_nonnegative_integer(row["sequence_number"]),
            sip_timestamp=_nonnegative_integer(row["sip_timestamp"]),
        )
    except BundleError:
        raise
    except (DomainValidationError, ValueError, TypeError, ArithmeticError, OverflowError):
        raise BundleError("bundle_value_invalid") from None


def _json_decimal(body: bytes, *, limits: BundleLimits) -> object:
    """Apply the bundle codec's byte/depth/duplicate-object safeguards with Decimals."""
    _check(type(body) is bytes)
    _check(len(body) <= limits.max_blob_bytes, "bundle_input_too_large")
    quoted = escaped = False
    depth = 0
    for char in body:
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted = True
        elif char in (91, 123):
            depth += 1
            _check(depth <= limits.max_json_depth, "bundle_input_too_large")
        elif char in (93, 125):
            depth -= 1
    try:
        return json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_object,
            parse_int=int,
            parse_float=Decimal,
            parse_constant=_reject_constant,
        )
    except BundleError:
        raise
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise BundleError("bundle_json_invalid") from None


def _reject_constant(value: str) -> NoReturn:
    raise BundleError("bundle_json_invalid")


def _mapping(value: object, fields: set[str]) -> dict[str, object]:
    _check(type(value) is dict, "bundle_schema_invalid")
    result = cast(dict[str, object], value)
    _check(set(result) == fields, "bundle_schema_invalid")
    return result


def _price(value: object) -> Decimal:
    _check(type(value) is Decimal)
    result = cast(Decimal, value)
    try:
        require_bounded_decimal(result, "price", nonnegative=True)
    except DomainValidationError:
        raise BundleError("bundle_value_invalid") from None
    return result


def _decimal_from_json_number(value: object) -> Decimal:
    _check(type(value) in (int, Decimal))
    return value if type(value) is Decimal else Decimal(str(value))


def _size(value: object) -> Decimal:
    _check(type(value) is Decimal)
    result = cast(Decimal, value)
    try:
        require_bounded_decimal(result, "size", nonnegative=True)
    except DomainValidationError:
        raise BundleError("bundle_value_invalid") from None
    _check(result == result.to_integral_value())
    return result


def _nonnegative_integer(value: object) -> int:
    _check(type(value) is int and value >= 0)
    return cast(int, value)


__all__ = [
    "MASSIVE_OPTIONS_REST_SOURCE",
    "MASSIVE_OPTIONS_SIZE_UNIT",
    "MassiveOptionsQuoteRow",
    "parse_massive_options_quote_row",
]
