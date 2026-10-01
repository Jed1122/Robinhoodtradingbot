"""Independent synthetic wire fixtures: implementation checks, never source evidence."""

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from trading_bot.market_data.etf_source import (
    EtfActionEvent,
    EtfControlEvent,
    EtfObservedBar,
    EtfObservedQuote,
    EtfSessionEvent,
    EtfSourceError,
    QualifiedEtfDataset,
    iter_etf_events,
    parse_etf_fixture,
)
from trading_bot.market_data.recording import canonical_json

T = 1478289600000000000  # 2016-11-04 20:00 UTC, before US DST change


def record(kind="bar", ordinal=0, **changes):
    payloads = {
        "bar": dict(
            instrument_id="SPY",
            interval="one_day",
            starts_at="2016-11-04T13:30:00.000000Z",
            ends_at="2016-11-04T20:00:00.000000Z",
            open="100",
            high="102",
            low="99",
            close="101",
            volume="123",
            source="synthetic",
            interpolated=False,
        ),
        "quote": dict(bid="100", ask="101", bid_size="2.5", ask_size="3"),
        "action": dict(
            instrument_id="SPY",
            action_type="dividend",
            effective_date="2016-11-04",
            announced_at="2016-11-04T20:00:00.000000Z",
            split_ratio=None,
            cash_amount="0.2",
        ),
        "session": dict(
            venue="XNYS",
            is_open=False,
            halted=False,
            trading_disabled=False,
            cancel_only=False,
            next_open_at="2016-11-07T14:30:00.000000Z",
            next_close_at="2016-11-07T21:00:00.000000Z",
        ),
        "control": dict(
            venue="XNYS",
            is_open=False,
            halted=True,
            trading_disabled=True,
            cancel_only=True,
            next_open_at=None,
            next_close_at=None,
        ),
    }
    row = dict(
        kind=kind,
        ordinal=ordinal,
        instrument_id="SPY",
        event_at_ns=T,
        published_at_ns=T + 1,
        received_at_ns=T + 2,
        revision_of=None,
        payload=payloads[kind],
    )
    row.update(changes)
    return row


def encoded(*rows):
    return json.dumps(
        dict(
            schema="etf-synthetic-page-v1",
            feed="synthetic",
            page=0,
            next_page=None,
            records=list(rows),
        )
    ).encode()


def parse(*rows):
    body = encoded(*rows)
    return parse_etf_fixture(body, expected_sha256=hashlib.sha256(body).hexdigest())


def test_closed_typed_events_preserve_exact_ns_decimal_and_no_authority():
    events = parse(
        *(record(k, i) for i, k in enumerate(("bar", "quote", "action", "session", "control")))
    )
    assert tuple(type(e) for e in events) == (
        EtfObservedBar,
        EtfObservedQuote,
        EtfActionEvent,
        EtfSessionEvent,
        EtfControlEvent,
    )
    assert events[0].payload.close == Decimal("101")
    assert events[1].bid_size == Decimal("2.5")
    assert events[1].payload.freshness_verified is False
    assert events[0].available_at_ns == T + 2
    assert events[0].payload.ends_at == datetime(2016, 11, 4, 20, tzinfo=UTC)
    with pytest.raises(FrozenInstanceError):
        events[0].ordinal = 9


@pytest.mark.parametrize("kind", ["session", "control"])
def test_open_session_clock_closes_before_the_next_session_opens(kind):
    instant = T - 3600 * 10**9
    row = record(kind, event_at_ns=instant, published_at_ns=instant, received_at_ns=instant)
    row["payload"].update(
        is_open=True,
        next_close_at="2016-11-04T20:00:00.000000Z",
        next_open_at="2016-11-07T14:30:00.000000Z",
    )
    event = parse(row)[0]
    assert event.payload.is_open is True
    assert event.payload.next_close_at < event.payload.next_open_at


@pytest.mark.parametrize("value", [["2016-11-04"], "2016-11-04", datetime(2016, 11, 4, tzinfo=UTC)])
def test_action_effective_date_must_be_an_exact_immutable_date(value):
    event = parse(record("action"))[0]
    with pytest.raises(ValueError):
        replace(event, payload=replace(event.payload, effective_date=value))


@pytest.mark.parametrize("value", [True, 1.2, "1", -1, 2**63])
def test_exact_ordinal(value):
    with pytest.raises(EtfSourceError):
        parse(record(ordinal=value))


@pytest.mark.parametrize(
    "field,value",
    [
        ("received_at_ns", None),
        ("received_at_ns", T - 1),
        ("published_at_ns", None),
        ("published_at_ns", T + 3),
        ("event_at_ns", True),
        ("instrument_id", "QQQ"),
        ("revision_of", "f" * 64),
    ],
)
def test_missing_receipt_bad_clock_or_identity_deny(field, value):
    with pytest.raises(EtfSourceError):
        parse(record(**{field: value}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("close", 100.1),
        ("close", True),
        ("close", "NaN"),
        ("close", "1e10000"),
        ("close", "0"),
        ("interpolated", True),
        ("source", "SIP"),
        ("interval", "one_minute"),
        ("ends_at", "2016-11-05T20:00:00.000000Z"),
    ],
)
def test_bar_projection_rejects_unsafe_or_unfinished_inputs(field, value):
    row = record()
    row["payload"][field] = value
    with pytest.raises(EtfSourceError):
        parse(row)


def test_substitution_duplicate_json_and_bounds():
    body = encoded(record())
    for invalid in (body + b" ", b'{"schema":0,"schema":1}', b"[" * 100, b"x" * (1048576 + 1)):
        with pytest.raises(EtfSourceError, match=r"^etf_source_invalid$"):
            parse_etf_fixture(invalid, expected_sha256=hashlib.sha256(body).hexdigest())


def test_order_collisions_and_backwards_receipts_deny():
    for rows in (
        (record(), record()),
        (record(ordinal=1), record(ordinal=0)),
        (record(received_at_ns=T + 10), record(ordinal=1)),
    ):
        with pytest.raises(EtfSourceError):
            parse(*rows)


def test_late_bar_revision_does_not_change_earlier_record_bytes():
    original = record()
    old = parse(original)[0]
    revision = record(
        ordinal=1,
        published_at_ns=T + 100,
        received_at_ns=T + 101,
        revision_of=old.source_record_hash,
    )
    revision["payload"]["close"] = "102"
    events = parse(original, revision)
    # Page hash changes; the decision input payload and record identity do not.
    assert events[0].source_record_hash == old.source_record_hash
    assert canonical_json(events[0].payload) == canonical_json(old.payload)
    assert events[1].event_at_ns == old.event_at_ns
    assert events[1].available_at_ns == T + 101
    assert events[1].revision_of == old.source_record_hash


@pytest.mark.parametrize("kind", ["dividend", "split"])
def test_action_revisions_retained_without_retroactive_application(kind):
    row = record("action")
    if kind == "split":
        row["payload"].update(action_type="split", cash_amount=None, split_ratio="2")
    old = parse(row)[0]
    revised = record(
        "action",
        ordinal=1,
        revision_of=old.source_record_hash,
        published_at_ns=T + 10,
        received_at_ns=T + 11,
    )
    revised["payload"] = dict(row["payload"])
    revised["payload"]["cash_amount" if kind == "dividend" else "split_ratio"] = "3"
    events = parse(row, revised)
    assert events[0].payload == old.payload
    assert events[1].available_at_ns > events[0].available_at_ns


def test_quote_crossed_denies_locked_and_delayed_remain_unverified():
    row = record("quote")
    row["payload"]["bid"] = "102"
    with pytest.raises(EtfSourceError):
        parse(row)
    row["payload"]["bid"] = "101"
    row["received_at_ns"] = T + 86400 * 10**9
    event = parse(row)[0]
    assert event.payload.bid == event.payload.ask
    assert event.payload.freshness_verified is False
    assert event.available_at_ns == row["received_at_ns"]


@pytest.mark.parametrize("size", [None, -1, "-1", True, 1.5])
def test_missing_or_invalid_quote_capacity_denies(size):
    row = record("quote")
    row["payload"]["bid_size"] = size
    with pytest.raises(EtfSourceError):
        parse(row)


def test_direct_event_replacement_revalidates_payload_and_clocks():
    event = parse(record())[0]
    for changes in (
        dict(ordinal=True),
        dict(available_at_ns=T - 1),
        dict(payload={}),
        dict(instrument_id="QQQ"),
        dict(payload=replace(event.payload, source="SIP")),
    ):
        with pytest.raises(ValueError):
            replace(event, **changes)


def test_no_caller_can_construct_qualified_data_or_iterate_fixture_as_real():
    with pytest.raises(EtfSourceError):
        QualifiedEtfDataset()
    with pytest.raises((TypeError, EtfSourceError)):
        QualifiedEtfDataset(verified=True)
    with pytest.raises(EtfSourceError):
        tuple(
            iter_etf_events(
                parse(record()),
                starts_at=datetime(2016, 1, 1, tzinfo=UTC),
                ends_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )


def test_unlinked_conflicting_bar_and_action_versions_deny():
    for kind in ("bar", "action"):
        with pytest.raises(EtfSourceError):
            parse(record(kind), record(kind, ordinal=1))


def test_future_revision_preserves_entire_earlier_event_bytes():
    original = record()
    first = parse(original)[0]
    revised = record(
        ordinal=1,
        published_at_ns=T + 10,
        received_at_ns=T + 11,
        revision_of=first.source_record_hash,
    )
    assert canonical_json(parse(original, revised)[0]) == canonical_json(first)


@pytest.mark.parametrize(
    "next_open,next_close",
    [
        ("2016-11-07T14:30:00.000000Z", "2016-11-07T21:00:00.000000Z"),
        ("2016-11-25T14:30:00.000000Z", "2016-11-25T18:00:00.000000Z"),
        (None, None),
    ],
)
def test_session_dst_early_close_and_closure_are_preserved_not_inferred(next_open, next_close):
    row = record("session")
    row["payload"].update(next_open_at=next_open, next_close_at=next_close)
    event = parse(row)[0]
    assert event.payload.is_open is False
    assert event.payload.next_open_at == (
        None if next_open is None else datetime.fromisoformat(next_open)
    )
    assert event.payload.next_close_at == (
        None if next_close is None else datetime.fromisoformat(next_close)
    )


def test_bad_session_close_and_nanosecond_rounding():
    row = record("session")
    row["payload"]["next_close_at"] = "2016-11-07T14:00:00.000000Z"
    with pytest.raises(EtfSourceError):
        parse(row)
    event = parse(record("quote", event_at_ns=T + 1))[0]
    assert event.event_at_ns == T + 1
    assert event.payload.observed_at.microsecond == 1


@pytest.mark.parametrize(
    "body", [b'{"a":0,"a":1}', b"[" * 100, b'{"a":NaN}', b'{"a":1.2}', b"\xff"]
)
def test_malformed_json_with_matching_hash_is_sanitized(body):
    with pytest.raises(EtfSourceError, match=r"^etf_source_invalid$"):
        parse_etf_fixture(body, expected_sha256=hashlib.sha256(body).hexdigest())
