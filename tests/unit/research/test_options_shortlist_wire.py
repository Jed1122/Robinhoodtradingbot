"""Closed wire boundaries cannot relabel origins or accept unbounded inputs."""

import json
from dataclasses import replace

import pytest

from tests.unit.research._options_shortlist_fixtures import imported_case, load_shortlist, make_case
from trading_bot.domain import CorporateAction, DataHash, InstrumentId
from trading_bot.market_data.options_data_codec import encode_record
from trading_bot.research.options_shortlist_models import ShortlistAction, ShortlistDiscontinuity


def wire(case=None):
    from trading_bot.research.options_shortlist_wire import encode_shortlist_input

    return json.loads(encode_shortlist_input(case or make_case()))


def decode(value, settings=None):
    from trading_bot.research.options_shortlist_wire import decode_shortlist_input

    return decode_shortlist_input(
        value if type(value) is bytes else json.dumps(value).encode(),
        settings=settings or load_shortlist().config.options.research_shortlist,
    )


@pytest.mark.parametrize("origin", ["synthetic", "imported", "missing"])
def test_exact_round_trip_and_unchanged_nested_record_hashes(origin):
    from trading_bot.research.options_shortlist_wire import encode_shortlist_input

    case = imported_case() if origin == "imported" else make_case()
    if origin == "missing":
        case = replace(
            case,
            prior_session=None,
            calendar=None,
            chain_evidence=None,
            action_evidence=None,
            actions=(),
            closes=(),
            records=(),
        )
    encoded = encode_shortlist_input(case)
    assert decode(encoded) == case
    assert encode_shortlist_input(decode(encoded)) == encoded
    if case.records:
        assert json.loads(encoded)["sessions"][0]["records"][0] == json.loads(
            encode_record(case.records[0])
        )


@pytest.mark.parametrize("extra", ["verified", "live_authorized", "quotes", "returns"])
def test_extra_authority_or_outcome_fields_rejected(extra):
    row = wire()
    row[extra] = True
    with pytest.raises(ValueError):
        decode(row)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"schema":NaN}',
        b'{"schema":Infinity}',
        b'{"schema":1.5}',
        b'{"schema":-0}',
        b'{"schema":1,"schema":2}',
        b"\xff",
        b"\x1f\x8b",
        b"[",
        b"[" * 17 + b"0" + b"]" * 17,
    ],
)
def test_invalid_json_numeric_depth_encoding_and_compression_denied(payload):
    with pytest.raises(ValueError):
        decode(payload)


@pytest.mark.parametrize("bad", [True, 100.0, "NaN", "Infinity", "1e2", "100.00"])
def test_financial_values_must_have_exact_canonical_spelling(bad):
    row = wire()
    row["sessions"][0]["closes"][0]["bar"]["close"] = bad
    with pytest.raises(ValueError):
        decode(row)


@pytest.mark.parametrize(
    "change", ["schema", "two_sessions", "origin", "hash", "nested_extra", "session_bool"]
)
def test_schema_origin_nested_identity_and_hash_tampering_denied(change):
    row = wire()
    session = row["sessions"][0]
    if change == "schema":
        row["schema"] = "options-shortlist-input-v2"
    elif change == "two_sessions":
        row["sessions"].append(session)
    elif change == "origin":
        session["source_kind"] = "imported"
    elif change == "hash":
        session["records"][0]["record_hash"] = "0" * 64
    elif change == "nested_extra":
        session["closes"][0]["evidence"]["verified"] = True
    else:
        session["current_session"]["session_id"] = True
    with pytest.raises(ValueError):
        decode(row)


def test_reordered_json_keys_are_semantically_equivalent():
    row = wire()
    assert decode(dict(reversed(tuple(row.items())))) == decode(row)


def test_byte_and_record_caps_checked_before_nested_decode(monkeypatch):
    import trading_bot.research.options_shortlist_wire as module

    settings = load_shortlist().config.options.research_shortlist
    with pytest.raises(ValueError):
        decode(b" " * (settings.max_input_bytes + 1))
    row = wire()
    row["sessions"][0]["records"] = [{}] * (settings.max_input_records + 1)

    def unexpected_decode(*args, **kwargs):
        raise AssertionError("oversized collection reached record decoder")

    monkeypatch.setattr(module, "decode_record", unexpected_decode)
    with pytest.raises(ValueError):
        decode(row)


@pytest.mark.parametrize("kind", ["split", "dividend", "merger", "unknown"])
def test_actions_use_closed_legacy_or_research_only_shapes(kind):
    from decimal import Decimal

    case = make_case()
    known = case.prior_session.closes_at
    if kind in {"split", "dividend"}:
        value = CorporateAction(
            InstrumentId("SPY"),
            kind,
            case.current_session.trading_date,
            known,
            Decimal("2") if kind == "split" else None,
            Decimal("1") if kind == "dividend" else None,
            DataHash("a" * 64),
        )
    else:
        value = ShortlistDiscontinuity(
            "SPY", kind, case.current_session.trading_date, known, DataHash("a" * 64)
        )
    case = replace(case, actions=(ShortlistAction(value, known),))
    assert decode(wire(case)) == case
    row = wire(case)
    row["sessions"][0]["actions"][0]["action"]["unexpected"] = True
    with pytest.raises(ValueError):
        decode(row)
