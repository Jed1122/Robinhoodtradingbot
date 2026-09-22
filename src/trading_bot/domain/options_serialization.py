"""Versioned options evidence. Legacy single-instrument serialization is untouched."""

import hashlib
import json
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal, get_args, get_origin, get_type_hints

from trading_bot.domain.decimal_utils import (
    DomainValidationError,
    canonical_decimal_text,
    parse_decimal,
)
from trading_bot.domain.options import OptionsOrderIntent

SCHEMA = "options-order-intent-v1"


def _encode(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return canonical_decimal_text(value)
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value):
        return {f.name: _encode(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    return value


def canonical_options_intent_payload(intent: OptionsOrderIntent) -> dict[str, object]:
    if type(intent) is not OptionsOrderIntent:
        raise DomainValidationError("exact OptionsOrderIntent required")
    return {"schema": SCHEMA, **_encode(intent)}


def options_intent_sha256(intent: OptionsOrderIntent) -> str:
    text = json.dumps(
        canonical_options_intent_payload(intent),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(text.encode()).hexdigest()


def _decode(value: object, expected: Any) -> Any:
    if get_origin(expected) is tuple:
        if type(value) is not list:
            raise DomainValidationError("expected JSON array")
        return tuple(_decode(item, get_args(expected)[0]) for item in value)
    if get_origin(expected) is Literal:
        if type(value) is not str or value not in get_args(expected):
            raise DomainValidationError("invalid literal")
        return value
    if isinstance(expected, type) and is_dataclass(expected):
        if type(value) is not dict or set(value) != {f.name for f in fields(expected)}:
            raise DomainValidationError("missing or unknown options evidence fields")
        hints = get_type_hints(expected)
        return expected(**{name: _decode(item, hints[name]) for name, item in value.items()})
    if expected in (str, bool, int):
        if type(value) is not expected:
            raise DomainValidationError("incorrect primitive type")
        return value
    if type(value) is not str:
        raise DomainValidationError("financial and temporal values require text")
    if expected is Decimal:
        return parse_decimal(value)
    if expected is datetime:
        return datetime.fromisoformat(value)
    if expected is date:
        return date.fromisoformat(value)
    if isinstance(expected, type) and issubclass(expected, Enum):
        return expected(value)
    raise DomainValidationError("unsupported options evidence type")


def options_intent_from_payload(payload: dict[str, object]) -> OptionsOrderIntent:
    """Read only the declared schema; reject additions instead of dropping evidence."""
    if type(payload) is not dict or payload.get("schema") != SCHEMA:
        raise DomainValidationError("unsupported options intent schema")
    try:
        result: OptionsOrderIntent = _decode(
            {key: value for key, value in payload.items() if key != "schema"}, OptionsOrderIntent
        )
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise DomainValidationError("invalid options intent evidence") from exc
    return result
