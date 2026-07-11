"""Strict decimal and shared domain validation helpers."""

import re
from decimal import Decimal, DecimalException, getcontext, localcontext

from trading_bot.clock import DomainValidationError as DomainValidationError

_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")


class InvalidDecimal(DomainValidationError):
    """Raised when a trading decimal is malformed, nonfinite, or otherwise unsafe."""


def parse_decimal(value: str) -> Decimal:
    """Parse a finite decimal from text without accepting binary floating-point input."""
    try:
        parsed = Decimal(value)
    except (DecimalException, TypeError, ValueError) as exc:
        raise InvalidDecimal("decimal must be valid base-10 text") from exc
    if not parsed.is_finite():
        raise InvalidDecimal("decimal must be finite")
    return parsed


def quantize_down(value: Decimal, increment: Decimal) -> Decimal:
    """Round a finite Decimal toward zero to a positive discrete increment."""
    _require_decimal(value, "value")
    _require_decimal(increment, "increment", positive=True)
    try:
        value_digits = len(value.as_tuple().digits)
        increment_digits = len(increment.as_tuple().digits)
        magnitude_gap = abs(value.adjusted() - increment.adjusted())
        required_precision = value_digits + increment_digits + magnitude_gap + 2
        with localcontext() as context:
            context.prec = max(getcontext().prec, required_precision)
            return (value // increment) * increment
    except DecimalException as exc:
        raise InvalidDecimal("value cannot be quantized to the requested increment") from exc


def _require_decimal(
    value: Decimal,
    field_name: str,
    *,
    nonnegative: bool = False,
    positive: bool = False,
) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvalidDecimal(f"{field_name} must be a finite Decimal")
    if positive and value <= 0:
        raise InvalidDecimal(f"{field_name} must be positive")
    if nonnegative and value < 0:
        raise InvalidDecimal(f"{field_name} must be nonnegative")
    return value


def _require_sha256_hex(value: str, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_HEX.fullmatch(value) is None:
        raise DomainValidationError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


def _require_nonempty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError(f"{field_name} must be a nonempty string")
    return value


def _require_tuple(value: object, field_name: str) -> None:
    if not isinstance(value, tuple):
        raise DomainValidationError(f"{field_name} must be an immutable tuple")
