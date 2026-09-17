"""Bounded, explicit JSON codecs for offline research bundles, without I/O."""

from __future__ import annotations

import json
from dataclasses import fields
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, NoReturn, cast

from trading_bot.domain import Bar, BarInterval, CorporateAction, DataHash, InstrumentId
from trading_bot.domain.decimal_utils import (
    MAX_CANONICAL_DECIMAL_TEXT_LENGTH,
    canonical_decimal_text,
)
from trading_bot.market_data.bundle_models import (
    _HASH,
    RECORD_KINDS,
    BarSlot,
    BundleEnvelope,
    BundleError,
    BundleLimits,
    CoverageDeclaration,
    CoverageKind,
    CoverageState,
    InstrumentMapping,
    MembershipBaseline,
    NormalizedRecord,
    RecordKind,
    RecordValue,
    SourceDescriptor,
    _check,
    _choice,
    _instant,
    _text,
)
from trading_bot.market_data.recording import ResearchDataManifest, canonical_json
from trading_bot.market_data.universe import UniverseMembership


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise BundleError("bundle_json_invalid")
        result[key] = value
    return result


def _reject_number(value: str) -> NoReturn:
    raise BundleError("bundle_json_invalid")


def _parse_integer(value: str) -> int:
    _check(value != "-0", "bundle_json_invalid")
    return int(value)


def _json(encoded: bytes, *, max_bytes: int, limits: BundleLimits) -> object:
    _check(type(limits) is BundleLimits, "bundle_limits_invalid")
    _check(type(encoded) is bytes)
    _check(len(encoded) <= max_bytes, "bundle_input_too_large")
    quoted = escaped = False
    depth = 0
    for char in encoded:
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
            encoded.decode("utf-8"),
            object_pairs_hook=_object,
            parse_int=_parse_integer,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
    except BundleError:
        raise
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        pass
    raise BundleError("bundle_json_invalid")


def _mapping(value: object, keys: set[str]) -> dict[str, object]:
    _check(type(value) is dict, "bundle_schema_invalid")
    result = cast(dict[str, object], value)
    _check(set(result) == keys, "bundle_schema_invalid")
    return result


def _array(value: object) -> list[object]:
    _check(type(value) is list, "bundle_schema_invalid")
    return cast(list[object], value)


def _string(value: object) -> str:
    _check(type(value) is str)
    return cast(str, value)


def _integer(value: object) -> int:
    _check(type(value) is int)
    return cast(int, value)


def _boolean(value: object) -> bool:
    _check(type(value) is bool)
    return cast(bool, value)


def _digest(value: object) -> DataHash:
    text = _string(value)
    _text(text, _HASH)
    return DataHash(text)


def _strings(value: object) -> tuple[str, ...]:
    return tuple(_string(item) for item in _array(value))


def _time(value: object) -> datetime:
    text = _string(value)
    _check(len(text) == 27 and text.endswith("Z"))
    result = datetime.fromisoformat(text)
    _instant(result)
    _check(result.isoformat(timespec="microseconds").replace("+00:00", "Z") == text)
    return result


def _date(value: object) -> date:
    text = _string(value)
    result = date.fromisoformat(text)
    _check(result.isoformat() == text)
    return result


def _decimal(value: object) -> Decimal:
    text = _string(value)
    _check(len(text) <= MAX_CANONICAL_DECIMAL_TEXT_LENGTH)
    # Reject exponent spelling before Decimal construction/canonical rendering.
    _check("e" not in text.lower())
    result = Decimal(text)
    _check(canonical_decimal_text(result) == text)
    return result


def _kind(value: object) -> RecordKind:
    _choice(value, RECORD_KINDS)
    return cast(RecordKind, value)


def _slot(value: object) -> BarSlot:
    row = _mapping(value, {"starts_at", "ends_at"})
    return BarSlot(_time(row["starts_at"]), _time(row["ends_at"]))


def _value(kind: RecordKind, value: object, *, raw_hash: DataHash | None = None) -> RecordValue:
    classes = {
        "bar": Bar,
        "membership": UniverseMembership,
        "baseline": MembershipBaseline,
        "corporate_action": CorporateAction,
        "coverage": CoverageDeclaration,
    }
    keys = {item.name for item in fields(classes[kind])}
    if raw_hash is not None and kind in ("bar", "corporate_action"):
        keys.remove("data_hash")
    row = _mapping(value, keys)
    instrument = InstrumentId(_string(row["instrument_id"]))
    if kind == "bar":
        return Bar(
            instrument,
            BarInterval(_string(row["interval"])),
            _time(row["starts_at"]),
            _time(row["ends_at"]),
            _decimal(row["open"]),
            _decimal(row["high"]),
            _decimal(row["low"]),
            _decimal(row["close"]),
            _decimal(row["volume"]),
            _string(row["source"]),
            raw_hash if raw_hash is not None else _digest(row["data_hash"]),
            _boolean(row["interpolated"]),
        )
    if kind == "membership":
        return UniverseMembership(
            instrument,
            _time(row["effective_at"]),
            _time(row["announced_at"]),
            _boolean(row["included"]),
        )
    if kind == "baseline":
        return MembershipBaseline(
            instrument,
            _time(row["coverage_start"]),
            _time(row["effective_at"]),
            _time(row["announced_at"]),
            _boolean(row["included"]),
        )
    if kind == "corporate_action":
        return CorporateAction(
            instrument,
            _string(row["action_type"]),
            _date(row["effective_date"]),
            _time(row["announced_at"]),
            None if row["split_ratio"] is None else _decimal(row["split_ratio"]),
            None if row["cash_amount"] is None else _decimal(row["cash_amount"]),
            raw_hash if raw_hash is not None else _digest(row["data_hash"]),
        )
    return CoverageDeclaration(
        instrument,
        cast(CoverageKind, _string(row["record_kind"])),
        None if row["interval"] is None else BarInterval(_string(row["interval"])),
        _time(row["starts_at"]),
        _time(row["ends_at"]),
        cast(CoverageState, _string(row["state"])),
        tuple(_slot(slot) for slot in _array(row["expected_slots"])),
    )


def _record(value: object) -> NormalizedRecord:
    row = _mapping(value, {item.name for item in fields(NormalizedRecord)})
    kind = _kind(row["kind"])
    basis = row["price_basis"]
    if basis is not None:
        _choice(basis, ("unadjusted", "adjusted", "unknown"))
    return NormalizedRecord(
        kind,
        _digest(row["source_hash"]),
        _integer(row["locator"]),
        _time(row["available_at"]),
        cast(Literal["unadjusted", "adjusted", "unknown"] | None, basis),
        _value(kind, row["value"]),
        _digest(row["record_hash"]),
    )


def _source(value: object) -> SourceDescriptor:
    row = _mapping(value, {item.name for item in fields(SourceDescriptor)})
    return SourceDescriptor(
        _string(row["source_id"]),
        _string(row["format_id"]),
        _string(row["normalizer_version"]),
        cast(Literal["synthetic", "imported"], _string(row["origin"])),
        tuple(InstrumentId(item) for item in _strings(row["instrument_ids"])),
        tuple(_kind(kind) for kind in _array(row["record_kinds"])),
        _time(row["requested_start"]),
        _time(row["requested_end"]),
        _time(row["collected_at"]),
        None if row["claimed_published_at"] is None else _time(row["claimed_published_at"]),
        _strings(row["limitation_codes"]),
        _integer(row["byte_length"]),
        _string(row["blob_sha256"]),
        _digest(row["descriptor_hash"]),
    )


def _manifest(value: object) -> ResearchDataManifest:
    row = _mapping(value, {item.name for item in fields(ResearchDataManifest)})
    return ResearchDataManifest(
        tuple(_digest(item) for item in _array(row["raw_hashes"])),
        tuple(_digest(item) for item in _array(row["cleaned_hashes"])),
        _string(row["corporate_action_coverage"]),
        _boolean(row["point_in_time_universe"]),
        _strings(row["survivorship_limitations"]),
        _strings(row["licensing_limitations"]),
        _strings(row["known_gaps"]),
        _digest(row["manifest_hash"]),
    )


def decode_envelope(encoded: bytes, *, limits: BundleLimits) -> BundleEnvelope:
    """Decode structure only; callers must use verification before snapshot loading."""
    _check(type(limits) is BundleLimits, "bundle_limits_invalid")
    value = _json(encoded, max_bytes=limits.max_envelope_bytes, limits=limits)
    row = _mapping(value, {item.name for item in fields(BundleEnvelope)})
    _check(row["schema"] == "research-bundle-v1", "bundle_schema_invalid")
    records = _array(row["records"])
    _check(len(records) <= limits.max_records, "bundle_input_too_large")
    try:
        mappings = tuple(
            _mapping(item, {"instrument_id", "symbol"}) for item in _array(row["instruments"])
        )
        return BundleEnvelope(
            "research-bundle-v1",
            tuple(
                InstrumentMapping(
                    InstrumentId(_string(item["instrument_id"])), _string(item["symbol"])
                )
                for item in mappings
            ),
            tuple(_source(item) for item in _array(row["sources"])),
            tuple(_record(item) for item in records),
            _manifest(row["manifest"]),
            cast(Literal["synthetic"], _string(row["classification"])),
            _strings(row["limitation_codes"]),
            _digest(row["bundle_hash"]),
        )
    except BundleError:
        raise
    except (ValueError, TypeError, ArithmeticError, OverflowError):
        pass
    raise BundleError("bundle_value_invalid")


def encode_envelope(envelope: BundleEnvelope) -> bytes:
    """Encode the existing canonical dataclass graph, without changing legacy hashes."""
    _check(type(envelope) is BundleEnvelope)
    return canonical_json(envelope).encode("utf-8")
