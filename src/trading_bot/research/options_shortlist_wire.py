"""Strict versioned shortlist wire format; no I/O or source-authentication claims."""

import json
from dataclasses import asdict, fields
from typing import Literal, cast

from trading_bot.config.models import OptionsShortlistSettings
from trading_bot.domain import Bar, CorporateAction
from trading_bot.market_data.bundle_codec import (
    _array,
    _date,
    _digest,
    _json,
    _mapping,
    _string,
    _time,
    _value,
)
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.options_data_codec import _session, decode_record, encode_record
from trading_bot.market_data.recording import canonical_json
from trading_bot.research.options_shortlist_models import (
    ShortlistAction,
    ShortlistCalendar,
    ShortlistCalendarDay,
    ShortlistClose,
    ShortlistDiscontinuity,
    ShortlistEvidence,
    ShortlistSessionInput,
    SourceKind,
    _check,
)

SCHEMA = "options-shortlist-input-v1"


def shortlist_limits(settings: OptionsShortlistSettings) -> BundleLimits:
    _check(type(settings) is OptionsShortlistSettings)
    settings = OptionsShortlistSettings.model_validate(settings.model_dump())
    return BundleLimits(
        settings.max_input_bytes,
        settings.max_input_bytes,
        settings.max_input_bytes,
        settings.max_input_records,
        settings.max_json_depth,
    )


def _evidence(value: object) -> ShortlistEvidence:
    row = _mapping(value, {f.name for f in fields(ShortlistEvidence)})
    return ShortlistEvidence(
        _string(row["source"]),
        cast(SourceKind, _string(row["source_kind"])),
        _digest(row["raw_hash"]),
        _time(row["available_at"]),
        _time(row["covers_from"]),
        _time(row["covers_through"]),
        cast(Literal["synthetic-shortlist-v1", "unverified-import-v1"], _string(row["semantics"])),
    )


def _optional_evidence(value: object) -> ShortlistEvidence | None:
    return None if value is None else _evidence(value)


def _calendar(value: object) -> ShortlistCalendar | None:
    if value is None:
        return None
    row = _mapping(value, {"evidence", "days"})
    days = []
    for item in _array(row["days"]):
        day = _mapping(item, {"trading_date", "regular_session"})
        days.append(
            ShortlistCalendarDay(
                _date(day["trading_date"]),
                None if day["regular_session"] is None else _session(day["regular_session"]),
            )
        )
    return ShortlistCalendar(_evidence(row["evidence"]), tuple(days))


def _close(value: object) -> ShortlistClose:
    row = _mapping(value, {f.name for f in fields(ShortlistClose)})
    bar = _value("bar", row["bar"])
    _check(type(bar) is Bar)
    return ShortlistClose(
        cast(Bar, bar),
        _time(row["available_at"]),
        cast(Literal["unadjusted"], _string(row["price_basis"])),
        cast(
            Literal["source_last_trade", "official_consolidated_close"],
            _string(row["coverage_label"]),
        ),
        _evidence(row["evidence"]),
    )


def _action(value: object) -> ShortlistAction:
    row = _mapping(value, {"action", "available_at"})
    action = row["action"]
    _check(type(action) is dict)
    kind = _string(cast(dict[str, object], action).get("action_type"))
    decoded: CorporateAction | ShortlistDiscontinuity
    if kind in {"split", "dividend"}:
        legacy = _value("corporate_action", action)
        _check(type(legacy) is CorporateAction)
        decoded = cast(CorporateAction, legacy)
    else:
        data = _mapping(action, {f.name for f in fields(ShortlistDiscontinuity)})
        decoded = ShortlistDiscontinuity(
            _string(data["instrument_id"]),
            cast(Literal["merger", "denomination_change", "deliverable_change", "unknown"], kind),
            _date(data["effective_date"]),
            _time(data["announced_at"]),
            _digest(data["data_hash"]),
        )
    return ShortlistAction(decoded, _time(row["available_at"]))


def encode_shortlist_input(session: ShortlistSessionInput) -> bytes:
    _check(type(session) is ShortlistSessionInput)
    session.__post_init__()
    row = asdict(session)
    row["records"] = [json.loads(encode_record(record)) for record in session.records]
    return canonical_json({"schema": SCHEMA, "sessions": [row]}).encode("utf-8")


def decode_shortlist_input(
    encoded: bytes, *, settings: OptionsShortlistSettings
) -> ShortlistSessionInput:
    limits = shortlist_limits(settings)
    wire = _mapping(
        _json(encoded, max_bytes=limits.max_envelope_bytes, limits=limits), {"schema", "sessions"}
    )
    _check(_string(wire["schema"]) == SCHEMA)
    sessions = _array(wire["sessions"])
    _check(len(sessions) == 1)
    row = _mapping(sessions[0], {f.name for f in fields(ShortlistSessionInput)})
    closes, actions, records = (_array(row[name]) for name in ("closes", "actions", "records"))
    calendar_count = 0
    if row["calendar"] is not None:
        calendar_row = _mapping(row["calendar"], {"evidence", "days"})
        calendar_count = len(_array(calendar_row["days"]))
    _check(len(closes) + len(actions) + len(records) + calendar_count <= limits.max_records)
    return ShortlistSessionInput(
        _session(row["current_session"]),
        None if row["prior_session"] is None else _session(row["prior_session"]),
        _calendar(row["calendar"]),
        tuple(_close(item) for item in closes),
        _optional_evidence(row["action_evidence"]),
        tuple(_action(item) for item in actions),
        _string(row["option_source"]),
        _optional_evidence(row["chain_evidence"]),
        tuple(decode_record(canonical_json(item).encode(), limits=limits) for item in records),
        cast(SourceKind, _string(row["source_kind"])),
    )
