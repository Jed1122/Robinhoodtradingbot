"""Strict JSON codec for credential-free options data records."""

from dataclasses import fields
from typing import Any, Literal, cast

from trading_bot.domain import CorporateAction, InstrumentId, Quote, TimestampSource
from trading_bot.domain.decimal_utils import DomainValidationError
from trading_bot.domain.options import OptionContract, OptionQuote, OptionSession
from trading_bot.domain.options_serialization import _decode
from trading_bot.market_data.bundle_codec import (
    _array,
    _boolean,
    _date,
    _decimal,
    _digest,
    _integer,
    _json,
    _mapping,
    _string,
    _strings,
    _time,
)
from trading_bot.market_data.bundle_models import BundleError, BundleLimits, _check, _choice
from trading_bot.market_data.options_records import (
    SCHEMA,
    ChainSnapshot,
    OptionsDataKind,
    OptionsDataRecord,
    OptionsDataValue,
)
from trading_bot.market_data.recording import canonical_json

_KINDS = (
    "chain",
    "contract",
    "option_quote",
    "session",
    "underlying_quote",
    "corporate_action",
)


def _field_names(value_type: type[Any]) -> set[str]:
    return {item.name for item in fields(value_type)}


def _kind(value: object) -> OptionsDataKind:
    _choice(value, _KINDS)
    return cast(OptionsDataKind, value)


def _session_wire(value: object) -> dict[str, object]:
    row = _mapping(value, _field_names(OptionSession))
    _string(row["session_id"])
    _time(row["opens_at"])
    _time(row["closes_at"])
    _date(row["trading_date"])
    _string(row["exchange_timezone"])
    return row


def _session(value: object) -> OptionSession:
    result = _decode(_session_wire(value), OptionSession)
    _check(type(result) is OptionSession)
    return cast(OptionSession, result)


def _contract(value: object) -> OptionContract:
    row = _mapping(value, _field_names(OptionContract))
    for name in ("contract_id", "standardized_id", "underlying", "deliverable_symbol", "currency"):
        _string(row[name])
    for name in ("kind", "exercise_style", "settlement_kind", "settlement_timing"):
        _string(row[name])
    for name in ("strike", "premium_multiplier", "deliverable_units", "tick_size"):
        _decimal(row[name])
    _date(row["expiration"])
    for name in ("last_trading_at", "settlement_at", "available_at"):
        _time(row[name])
    _boolean(row["adjusted"])
    for item in _array(row["eligible_sessions"]):
        _session_wire(item)
    _digest(row["data_hash"])
    result = _decode(row, OptionContract)
    _check(type(result) is OptionContract)
    return cast(OptionContract, result)


def _optional_integer(value: object) -> int | None:
    return None if value is None else _integer(value)


def _option_quote(value: object) -> OptionQuote:
    row = _mapping(value, _field_names(OptionQuote))
    return OptionQuote(
        _string(row["contract_id"]),
        _decimal(row["bid"]),
        _decimal(row["ask"]),
        _optional_integer(row["bid_size"]),
        _optional_integer(row["ask_size"]),
        _time(row["event_at"]),
        _time(row["received_at"]),
        _time(row["underlying_event_at"]),
        _string(row["source"]),
        _digest(row["data_hash"]),
        _strings(row["quality_flags"]),
        _string(row["underlying"]),
    )


def _underlying_quote(value: object) -> Quote:
    row = _mapping(value, _field_names(Quote))
    return Quote(
        InstrumentId(_string(row["instrument_id"])),
        _time(row["observed_at"]),
        _decimal(row["bid"]),
        _decimal(row["ask"]),
        None if row["last"] is None else _decimal(row["last"]),
        _string(row["source"]),
        _digest(row["data_hash"]),
        _boolean(row["freshness_verified"]),
        TimestampSource(_string(row["timestamp_source"])),
    )


def _corporate_action(value: object) -> CorporateAction:
    row = _mapping(value, _field_names(CorporateAction))
    return CorporateAction(
        InstrumentId(_string(row["instrument_id"])),
        _string(row["action_type"]),
        _date(row["effective_date"]),
        _time(row["announced_at"]),
        None if row["split_ratio"] is None else _decimal(row["split_ratio"]),
        None if row["cash_amount"] is None else _decimal(row["cash_amount"]),
        _digest(row["data_hash"]),
    )


def _value(kind: OptionsDataKind, value: object, *, limits: BundleLimits) -> OptionsDataValue:
    if kind == "chain":
        row = _mapping(value, _field_names(ChainSnapshot))
        contract_ids = _array(row["contract_ids"])
        _check(len(contract_ids) <= limits.max_records, "bundle_input_too_large")
        return ChainSnapshot(
            _string(row["underlying"]), tuple(_string(item) for item in contract_ids)
        )
    if kind == "contract":
        return _contract(value)
    if kind == "option_quote":
        return _option_quote(value)
    if kind == "session":
        return _session(value)
    if kind == "underlying_quote":
        return _underlying_quote(value)
    return _corporate_action(value)


def encode_record(record: OptionsDataRecord) -> bytes:
    """Encode one exact record into its canonical, versioned evidence envelope."""
    _check(type(record) is OptionsDataRecord)
    envelope = {
        "schema": SCHEMA,
        "kind": record.kind,
        "record": {
            "source": record.source,
            "source_kind": record.source_kind,
            "raw_hash": record.raw_hash,
            "event_at": record.event_at,
            "available_at": record.available_at,
            "value": record.value,
        },
        "record_hash": record.record_hash,
    }
    return canonical_json(envelope).encode("utf-8")


def decode_record(encoded: bytes, *, limits: BundleLimits) -> OptionsDataRecord:
    """Decode and verify one record without acquiring data or conferring capability."""
    _check(type(limits) is BundleLimits, "bundle_limits_invalid")
    value = _json(encoded, max_bytes=limits.max_envelope_bytes, limits=limits)
    envelope = _mapping(value, {"schema", "kind", "record", "record_hash"})
    _check(envelope["schema"] == SCHEMA, "bundle_schema_invalid")
    kind = _kind(envelope["kind"])
    row = _mapping(
        envelope["record"],
        {"source", "source_kind", "raw_hash", "event_at", "available_at", "value"},
    )
    _choice(row["source_kind"], ("synthetic", "imported"))
    try:
        result = OptionsDataRecord(
            _string(row["source"]),
            cast(Literal["synthetic", "imported"], row["source_kind"]),
            str(_digest(row["raw_hash"])),
            _time(row["event_at"]),
            _time(row["available_at"]),
            _value(kind, row["value"], limits=limits),
        )
        _check(result.kind == kind, "bundle_schema_invalid")
        expected_hash = _digest(envelope["record_hash"])
        _check(result.record_hash == expected_hash, "bundle_hash_mismatch")
        return result
    except BundleError:
        raise
    except (DomainValidationError, ValueError, TypeError, ArithmeticError, OverflowError):
        raise BundleError("bundle_value_invalid") from None
