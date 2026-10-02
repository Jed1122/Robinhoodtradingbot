"""Invented official-shaped stream rows test syntax, never actual source evidence."""

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, Inexact, Overflow, Rounded, localcontext

import pytest

from trading_bot.market_data.alpaca_observations import (
    MAX_FRAME_BYTES,
    MAX_FRAME_ROWS,
    AlpacaObservationError,
    AlpacaStreamObservation,
    parse_alpaca_observation_frame,
)

STAMP = "2026-10-01T13:30:00.123456789Z"
STAMP_NS = 1790861400123456789
RECEIVED_NS = STAMP_NS + 123


def quote(**changes):
    return {
        "T": "q",
        "S": "SPY",
        "t": STAMP,
        "bp": 500,
        "ap": 501,
        "bs": 40,
        "as": 80,
        "bx": "P",
        "ax": "N",
        "c": ["R"],
        "z": "B",
    } | changes


def status(**changes):
    return {
        "T": "s",
        "S": "SPY",
        "t": STAMP,
        "sc": "H",
        "sm": "Trading Halt",
        "rc": "T1",
        "rm": "News Pending",
        "z": "B",
    } | changes


def luld(**changes):
    return {
        "T": "l",
        "S": "SPY",
        "t": STAMP,
        "u": 510,
        "d": 490,
        "i": "B",
        "z": "B",
    } | changes


def encoded(*rows):
    return json.dumps(rows, separators=(",", ":"), ensure_ascii=False).encode()


def parse(body, *, frame_index=12345, received_at_ns=RECEIVED_NS):
    return parse_alpaca_observation_frame(
        body, frame_index=frame_index, received_at_ns=received_at_ns
    )


def test_quote_status_and_luld_preserve_native_fields_and_stream_identity():
    body = encoded(quote(c=["R", "A"]), status(), luld())
    observations = parse(body)
    assert type(observations) is tuple
    assert [o.kind for o in observations] == ["quote", "status", "luld"]
    assert [o.row_index for o in observations] == [0, 1, 2]
    assert all(o.frame_index == 12345 for o in observations)
    assert all(o.timestamp_ns == STAMP_NS for o in observations)
    assert all(o.received_at_ns == RECEIVED_NS for o in observations)
    assert all(o.body_sha256 == hashlib.sha256(body).hexdigest() for o in observations)
    assert all(o.tape == "B" for o in observations)
    first, second, third = observations
    assert first.quote.page_index == 0
    assert first.quote.row_index == first.row_index
    assert first.quote.timestamp_ns == STAMP_NS
    assert (first.quote.bid, first.quote.ask) == (Decimal("500"), Decimal("501"))
    assert (first.quote.bid_size, first.quote.ask_size) == (40, 80)
    assert first.quote.size_unit == "shares"
    assert (first.quote.bid_exchange, first.quote.ask_exchange) == ("P", "N")
    assert first.quote.conditions == ("R", "A")
    assert first.quote.body_sha256 == first.body_sha256
    assert not first.quote.executable
    assert (second.status_code, second.status_message) == ("H", "Trading Halt")
    assert (second.reason_code, second.reason_message) == ("T1", "News Pending")
    assert second.quote is None and third.quote is None
    assert (third.upper_band, third.lower_band, third.indicator) == (
        Decimal("510"),
        Decimal("490"),
        "B",
    )
    assert all(not o.source_qualified for o in observations)
    assert all(not o.evidence_promotable for o in observations)
    assert all(not o.execution_enabled for o in observations)


def test_decimal_lexemes_are_exact_without_host_context_rounding():
    body = encoded(quote(), luld())
    body = body.replace(b'"bp":500', b'"bp":500.000000000000000000001')
    body = body.replace(b'"ap":501', b'"ap":5.01000000000000000000001e2')
    body = body.replace(b'"u":510', b'"u":510.000000000000000000001')
    body = body.replace(b'"d":490', b'"d":4.90000000000000000000001e2')
    with localcontext() as context:
        context.prec = 1
        context.Emax = 1
        context.Emin = -1
        for signal in (Inexact, Rounded, Overflow):
            context.traps[signal] = True
        first, second = parse(body)
        identity = first.observation_hash
    assert first.quote.bid == Decimal("500.000000000000000000001")
    assert first.quote.ask == Decimal("501.000000000000000000001")
    assert second.upper_band == Decimal("510.000000000000000000001")
    assert second.lower_band == Decimal("490.000000000000000000001")
    assert identity == first.observation_hash


def test_repeated_and_out_of_order_timestamps_preserve_rows_without_deduplication():
    body = encoded(quote(), quote(), quote(t="2026-10-01T13:29:59.123456789Z"))
    first = parse(body)
    second = parse(body, frame_index=12346)
    assert [o.timestamp_ns for o in first] == [STAMP_NS, STAMP_NS, STAMP_NS - 10**9]
    assert len({o.observation_hash for o in (*first, *second)}) == 6
    assert first[0].quote.record_hash == second[0].quote.record_hash
    assert first[0].observation_hash != second[0].observation_hash
    assert first[0].observation_hash == parse(body)[0].observation_hash
    received_later = parse(body, received_at_ns=RECEIVED_NS + 1)[0]
    assert first[0].observation_hash != received_later.observation_hash


def test_raw_body_identity_changes_when_equivalent_numeric_spelling_changes():
    body = encoded(quote())
    changed = body.replace(b'"bp":500', b'"bp":500.00')
    original, equivalent = parse(body)[0], parse(changed)[0]
    assert original.quote.bid == equivalent.quote.bid
    assert original.body_sha256 != equivalent.body_sha256
    assert original.observation_hash != equivalent.observation_hash


def test_clock_skew_is_preserved_as_diagnostic_without_inventing_latency():
    item = parse(encoded(quote()), received_at_ns=STAMP_NS - 1)[0]
    assert item.received_at_ns == STAMP_NS - 1
    assert "receipt_clock_precedes_provider_timestamp" in item.observation_reasons
    no_skew = parse(encoded(quote()))[0]
    assert "receipt_clock_precedes_provider_timestamp" not in no_skew.observation_reasons
    assert not hasattr(item, "latency_ns")


def test_status_and_luld_codes_preserve_raw_empty_spaces_and_unrecognized_strings():
    first, second = parse(
        encoded(status(sc="", sm="  raw message \u00e9  ", rc=" ", rm="unknown"), luld(i=" raw "))
    )
    assert (first.status_code, first.status_message, first.reason_code, first.reason_message) == (
        "",
        "  raw message \u00e9  ",
        " ",
        "unknown",
    )
    assert second.indicator == " raw "
    assert not first.execution_enabled and not second.execution_enabled


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"bp": 0, "bs": 0, "bx": " "}, "inactive_bid"),
        ({"ap": 0, "as": 0}, "inactive_ask"),
        ({"bp": 501}, "locked_quote"),
        ({"bp": 502}, "crossed_quote"),
    ],
)
def test_zero_locked_and_crossed_quotes_are_observations_only(changes, reason):
    item = parse(encoded(quote(**changes)))[0]
    assert reason in item.observation_reasons
    assert not item.quote.executable and not item.execution_enabled


def test_zero_or_inverted_luld_bands_remain_observations_without_eligibility():
    first, second = parse(encoded(luld(u=0, d=0), luld(u=1, d=2)))
    assert (first.upper_band, first.lower_band) == (Decimal(0), Decimal(0))
    assert (second.upper_band, second.lower_band) == (Decimal(1), Decimal(2))
    assert not first.execution_enabled and not second.execution_enabled


@pytest.mark.parametrize("builder", [quote, status, luld])
def test_all_wire_fields_are_required_and_extra_fields_are_denied(builder):
    row = builder()
    for missing in row:
        with pytest.raises(AlpacaObservationError, match=r"^alpaca_observation_invalid$"):
            parse(encoded({key: value for key, value in row.items() if key != missing}))
    for extra in ("unknown", "execution_enabled", "source_qualified", "evidence_promotable"):
        with pytest.raises(AlpacaObservationError):
            parse(encoded(row | {extra: True}))


@pytest.mark.parametrize(
    "row",
    [
        quote(S="QQQ"),
        quote(S="spy"),
        quote(S=True),
        quote(T="t"),
        quote(T="success"),
        quote(T="error"),
        quote(T="subscription"),
        quote(T=True),
        quote(z="N"),
        quote(z=None),
        quote(bp="500"),
        quote(bp=True),
        quote(bp=-1),
        quote(bs=True),
        quote(bs=-1),
        quote(bs=2**32),
        quote(bs=1.0),
        quote(c="R"),
        quote(c=[True]),
        quote(c=["R"] * 33),
        quote(bx=""),
        quote(ax="\u00e9"),
        status(sc=1),
        status(sm=None),
        status(rc=True),
        status(rm="x" * 4097),
        luld(u=None),
        luld(d="490"),
        luld(i=True),
        luld(i="x" * 4097),
    ],
)
def test_closed_schema_rejects_wrong_types_ranges_and_other_symbols(row):
    with pytest.raises(AlpacaObservationError, match=r"^alpaca_observation_invalid$"):
        parse(encoded(row))


@pytest.mark.parametrize(
    "stamp",
    [
        True,
        1,
        None,
        "2026-10-01",
        "2026-10-01T13:30:00",
        "2026-10-01T13:30:00.1234567891Z",
        "2026-02-30T13:30:00Z",
        "2026-10-01T13:30:60Z",
        "2026-10-01T13:30:00-00:00",
        "2026-10-01T13:30:00+24:00",
        "1969-12-31T23:59:59Z",
        "9999-01-01T00:00:00Z",
    ],
)
def test_invalid_or_precision_losing_timestamps_are_denied(stamp):
    with pytest.raises(AlpacaObservationError):
        parse(encoded(quote(t=stamp)))


def test_valid_offset_timestamp_preserves_all_nine_fractional_digits():
    item = parse(encoded(quote(t="2026-10-01T09:30:00.123456789-04:00")))[0]
    assert item.timestamp_ns == STAMP_NS


@pytest.mark.parametrize(
    "literal",
    [b"NaN", b"Infinity", b"-Infinity", b"-0", b"1e513", b"1e-513", b"0e513", b"0e-513"],
)
def test_nonfinite_ambiguous_or_unbounded_numeric_lexemes_are_denied(literal):
    body = encoded(quote()).replace(b'"bp":500', b'"bp":' + literal)
    with pytest.raises(AlpacaObservationError):
        parse(body)


def test_numeric_lexeme_character_bound_applies_before_large_decimal_allocation():
    body = encoded(quote()).replace(b'"bp":500', b'"bp":0.' + b"0" * 512)
    with pytest.raises(AlpacaObservationError):
        parse(body)


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"null",
        b"{}",
        b"[1]",
        b"[null]",
        b"[[]]",
        b"not-json",
        b"\xff",
        b"\xef\xbb\xbf[]",
        b'[{"T":"q","T":"q"}]',
        b'[{"T":"q","S":"SPY","S":"SPY"}]',
        b'[{"T":"q","c":[{"hidden":"a","hidden":"b"}]}]',
        b'[[[[[]]]]]',
        b'[{"T":"error","code":403,"msg":"fixture-provider-error"}]',
    ],
)
def test_malformed_ambiguous_control_and_excessive_depth_frames_are_denied(body):
    with pytest.raises(AlpacaObservationError, match=r"^alpaca_observation_invalid$"):
        parse(body)


def test_duplicate_json_fields_in_complete_row_are_denied():
    body = encoded(quote()).replace(b'"bp":500', b'"bp":500,"bp":500')
    with pytest.raises(AlpacaObservationError):
        parse(body)


def test_one_invalid_row_denies_the_entire_frame_without_partial_results():
    with pytest.raises(AlpacaObservationError):
        parse(encoded(quote(), status(), luld(S="QQQ")))


def test_empty_frame_yields_no_observations_or_completeness_evidence():
    assert parse(b"[]") == ()


def test_explicit_frame_byte_and_row_bounds_allow_boundary_and_deny_overflow():
    body = encoded(quote())
    at_limit = body + b" " * (MAX_FRAME_BYTES - len(body))
    assert len(parse(at_limit)) == 1
    with pytest.raises(AlpacaObservationError):
        parse(at_limit + b" ")
    assert len(parse(encoded(*[quote()] * MAX_FRAME_ROWS))) == MAX_FRAME_ROWS
    with pytest.raises(AlpacaObservationError):
        parse(encoded(*[quote()] * (MAX_FRAME_ROWS + 1)))


@pytest.mark.parametrize("body", ["[]", bytearray(b"[]"), None, True, memoryview(b"[]")])
def test_frame_body_must_be_exact_bytes(body):
    with pytest.raises(AlpacaObservationError):
        parse(body)


@pytest.mark.parametrize("value", [True, -1, 2**63, Decimal(0), "0", None])
@pytest.mark.parametrize("field", ["frame_index", "received_at_ns"])
def test_frame_and_receipt_metadata_require_bounded_exact_integers(field, value):
    with pytest.raises(AlpacaObservationError):
        parse(encoded(quote()), **{field: value})


def test_observations_and_flags_are_immutable_and_do_not_repr_payloads():
    item = parse(encoded(status(rm="fixture-sensitive-message")))[0]
    assert "fixture-sensitive-message" not in repr(item)
    assert "Trading Halt" not in repr(item)
    with pytest.raises(FrozenInstanceError):
        item.received_at_ns = 0
    for flag in ("execution_enabled", "source_qualified", "evidence_promotable"):
        assert item.__dataclass_fields__[flag].init is False
        with pytest.raises(FrozenInstanceError):
            setattr(item, flag, True)
        # Some CPython releases delegate replace() to the constructor (TypeError);
        # others explicitly reject init=False fields (ValueError).
        with pytest.raises((TypeError, ValueError), match=flag):
            replace(item, **{flag: True})
        assert getattr(item, flag) is False
        with pytest.raises(TypeError, match=flag):
            AlpacaStreamObservation(
                "status", 0, 0, STAMP_NS, RECEIVED_NS, "a" * 64, None, "B", **{flag: True}
            )


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "other"),
        ("frame_index", True),
        ("row_index", MAX_FRAME_ROWS),
        ("timestamp_ns", -1),
        ("received_at_ns", None),
        ("body_sha256", "fixture-sensitive-message"),
        ("tape", "N"),
        ("status_code", "unexpected"),
        ("upper_band", Decimal(1)),
        ("indicator", "unexpected"),
        ("source_qualified", True),
        ("source_qualified", 0),
        ("evidence_promotable", True),
        ("execution_enabled", True),
    ],
)
def test_content_addressing_revalidates_forged_observation_fields_and_flags(field, value):
    item = parse(encoded(quote()))[0]
    object.__setattr__(item, field, value)
    with pytest.raises(AlpacaObservationError, match=r"^alpaca_observation_invalid$"):
        _ = item.observation_hash


@pytest.mark.parametrize(
    "field,value",
    [
        ("page_index", 1),
        ("row_index", 1),
        ("timestamp_ns", STAMP_NS + 1),
        ("body_sha256", "a" * 64),
        ("tape", "A"),
        ("executable", True),
        ("publication_at_ns", RECEIVED_NS),
        ("bid", Decimal("0e513")),
    ],
)
def test_content_addressing_revalidates_embedded_quote_identity_and_flags(field, value):
    item = parse(encoded(quote()))[0]
    object.__setattr__(item.quote, field, value)
    with pytest.raises(AlpacaObservationError):
        _ = item.observation_hash


@pytest.mark.parametrize(
    "builder,field,value",
    [
        (status, "status_code", None),
        (status, "status_message", 1),
        (status, "upper_band", Decimal(1)),
        (luld, "upper_band", Decimal("NaN")),
        (luld, "lower_band", Decimal(-1)),
        (luld, "indicator", None),
        (luld, "reason_code", "unexpected"),
    ],
)
def test_status_and_luld_models_deny_forged_inconsistent_fields(builder, field, value):
    item = parse(encoded(builder()))[0]
    object.__setattr__(item, field, value)
    with pytest.raises(AlpacaObservationError):
        _ = item.observation_hash
