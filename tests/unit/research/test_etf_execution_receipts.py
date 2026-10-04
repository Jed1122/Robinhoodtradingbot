"""Synthetic receipt fixtures; never actual customer execution evidence."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading_bot.market_data.recording import canonical_json
from trading_bot.research.etf_cost_calibration import measure_etf_cost_observations
from trading_bot.research.etf_execution_receipts import EtfReceiptError, link_execution_receipts

START = datetime(2026, 10, 2, 14, tzinfo=UTC)
ORDER = "a" * 64
FILL = "b" * 64


def instant(offset: int) -> str:
    return (
        (START + timedelta(microseconds=offset))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def encode(value: object) -> bytes:
    return canonical_json(value).encode()


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def fixture() -> tuple[bytes, list[dict], dict[str, bytes]]:
    from trading_bot.market_data.alpaca_native import parse_timestamp_ns
    from trading_bot.market_data.alpaca_observations import parse_alpaca_observation_frame

    session = encode(
        {
            "schema": "etf-execution-clock-session-v1",
            "nonce": "c" * 64,
            "provenance": "synthetic",
            "code_revision": "d" * 40,
            "started_at": instant(-1),
            "started_monotonic_ns": 0,
            "maximum_quote_age_ns": 1_000_000_000,
            "evidence_promotable": False,
        }
    )
    sources: dict[str, bytes] = {}

    def source(body: bytes) -> str:
        h = digest(body)
        sources[h] = body
        return h

    def quote(offset: int, bid: float, ask: float, index: int) -> tuple[dict, str]:
        body = json.dumps(
            [
                {
                    "T": "q",
                    "S": "SPY",
                    "t": instant(offset),
                    "z": "B",
                    "bp": bid,
                    "ap": ask,
                    "bs": 10,
                    "as": 10,
                    "bx": "P",
                    "ax": "P",
                    "c": ["R"],
                }
            ]
        ).encode()
        observation = parse_alpaca_observation_frame(
            body, frame_index=index, received_at_ns=parse_timestamp_ns(instant(offset))
        )[0]
        return {"frame_index": index, "body_sha256": source(body)}, observation.observation_hash

    first, observation = quote(0, 100, 100.1, 0)
    arrival, _ = quote(3, 100.02, 100.12, 1)
    terms = source(b"synthetic terms")
    broker = source(b"synthetic execution record")
    fees = {
        "commission": "0.01",
        "sec": "0",
        "taf": "0.01",
        "cat": "0.01",
        "other": "0",
        "total": "0.03",
        "source_hash": broker,
    }
    events = [
        ("alpaca_frame", first),
        (
            "decision",
            {
                "order_hash": ORDER,
                "side": "buy",
                "terms_hash": terms,
                "observation_hash": observation,
            },
        ),
        ("submitted", {"order_hash": ORDER, "source_hash": broker}),
        ("alpaca_frame", arrival),
        ("acknowledged", {"order_hash": ORDER, "source_hash": broker}),
        (
            "fill",
            {
                "order_hash": ORDER,
                "fill_hash": FILL,
                "quantity": "1",
                "price": "100.1",
                "source_hash": broker,
            },
        ),
        (
            "fill",
            {
                "order_hash": ORDER,
                "fill_hash": "e" * 64,
                "quantity": "2",
                "price": "100.2",
                "source_hash": broker,
            },
        ),
        (
            "terminal",
            {"order_hash": ORDER, "source_hash": broker, "state": "filled", "charged_fees": fees},
        ),
    ]
    records = [
        {
            "schema": "etf-execution-receipt-v1",
            "session_hash": digest(session),
            "sequence": i,
            "previous_hash": None,
            "kind": kind,
            "received_at": instant(i),
            "received_monotonic_ns": (i + 1) * 10,
            "payload": payload,
        }
        for i, (kind, payload) in enumerate(events)
    ]
    return session, records, sources


def receipts(rows: list[dict]) -> tuple[bytes, ...]:
    result = []
    previous = None
    for i, original in enumerate(rows):
        row = deepcopy(original)
        row["sequence"], row["previous_hash"] = i, previous
        body = encode(row)
        result.append(body)
        previous = digest(body)
    return tuple(result)


def test_quotes_are_derived_from_raw_frames_and_fees_group_once():
    session, rows, sources = fixture()
    result = link_execution_receipts(session, receipts(rows), sources)
    assert result["incomplete_order_count"] == 0
    assert result["evidence_promotable"] is False
    assert result["execution_enabled"] is False
    order = result["cost_input"]["orders"][0]
    assert order["decision_quote"]["bid"] == "100"
    assert order["decision_quote"]["ask"] == "100.1"
    assert order["arrival_quote"]["ask"] == "100.12"
    report = measure_etf_cost_observations(encode(result["cost_input"]))
    assert report["executed_notional_usd"] == Decimal("300.50")
    assert report["fill_count"] == 2
    assert report["charged_order_fee_usd"]["total"]["mean"] == Decimal("0.03")
    assert report["calibration_status"] == "unverified"


def test_incomplete_prefix_preserves_pending_order_without_forced_fill():
    session, rows, sources = fixture()
    result = link_execution_receipts(session, receipts(rows[:6]), sources)
    assert result["incomplete_order_count"] == 1
    assert result["cost_input"]["orders"] == []


def test_duplicate_fill_delivery_does_not_double_count():
    session, rows, sources = fixture()
    extra = deepcopy(rows[5])
    rows.insert(6, extra)
    result = link_execution_receipts(session, receipts(rows), sources)
    assert len(result["cost_input"]["orders"][0]["fills"]) == 2


@pytest.mark.parametrize(
    "change",
    [
        "source",
        "session",
        "previous",
        "clock",
        "utc",
        "decision",
        "fee",
        "duplicate",
        "new_after_terminal",
    ],
)
def test_invalid_or_conflicting_evidence_is_denied(change):
    session, rows, sources = fixture()
    if change == "source":
        sources[next(iter(sources))] += b" "
    elif change == "session":
        rows[2]["session_hash"] = "f" * 64
    elif change == "clock":
        rows[6]["received_monotonic_ns"] = 1
    elif change == "utc":
        rows[6]["received_at"] = instant(-2)
    elif change == "decision":
        rows[1]["payload"]["observation_hash"] = "f" * 64
    elif change == "fee":
        rows[7]["payload"]["charged_fees"]["total"] = "0.04"
    elif change == "duplicate":
        rows[6]["payload"]["fill_hash"] = FILL
    elif change == "new_after_terminal":
        rows.append(deepcopy(rows[6]))
        rows[-1]["payload"]["fill_hash"] = "f" * 64
        rows[-1]["received_at"], rows[-1]["received_monotonic_ns"] = instant(8), 90
    encoded = receipts(rows)
    if change == "previous":
        broken = json.loads(encoded[3])
        broken["previous_hash"] = "f" * 64
        encoded = (*encoded[:3], encode(broken), *encoded[4:])
    with pytest.raises(EtfReceiptError, match="etf_execution_receipt_invalid"):
        link_execution_receipts(session, encoded, sources)


def test_absent_fees_remain_absent():
    session, rows, sources = fixture()
    rows[-1]["payload"]["charged_fees"] = None
    result = link_execution_receipts(session, receipts(rows), sources)
    assert result["cost_input"]["orders"][0]["charged_fees"] is None
    assert result["missing_fee_order_count"] == 1


def test_unfilled_cancellation_is_not_an_execution_sample():
    session, rows, sources = fixture()
    rows = [*rows[:3], rows[-1]]
    rows[-1]["payload"]["state"] = "cancelled"
    rows[-1]["payload"]["charged_fees"] = None
    result = link_execution_receipts(session, receipts(rows), sources)
    assert result["unfilled_order_count"] == 1
    assert result["cost_input"]["orders"] == []


def test_arrival_age_is_checked_at_first_fill_not_later_partial_deliveries():
    session, rows, sources = fixture()
    clock = json.loads(session)
    clock["maximum_quote_age_ns"] = 2000
    session = encode(clock)
    for row in rows:
        row["session_hash"] = digest(session)
    result = link_execution_receipts(session, receipts(rows), sources)
    assert result["completed_order_count"] == 1
    assert len(result["cost_input"]["orders"][0]["fills"]) == 2


def test_unfilled_order_charges_are_preserved_outside_cost_samples():
    session, rows, sources = fixture()
    rows = [*rows[:3], rows[-1]]
    rows[-1]["payload"]["state"] = "cancelled"
    result = link_execution_receipts(session, receipts(rows), sources)
    assert result["cost_input"]["orders"] == []
    assert result["unfilled_outcomes"][0]["charged_fees"]["total"] == "0.03"


def test_quote_age_beyond_explicit_bound_is_denied():
    session, rows, sources = fixture()
    clock = json.loads(session)
    clock["maximum_quote_age_ns"] = 1999
    session = encode(clock)
    for row in rows:
        row["session_hash"] = digest(session)
    with pytest.raises(EtfReceiptError):
        link_execution_receipts(session, receipts(rows), sources)


def test_first_arrival_quote_is_used_not_favorable_later_quote():
    session, rows, sources = fixture()
    from trading_bot.market_data.alpaca_native import parse_timestamp_ns
    from trading_bot.market_data.alpaca_observations import parse_alpaca_observation_frame

    arrival = rows[3]["payload"]["body_sha256"]
    values = json.loads(sources[arrival])
    later = deepcopy(values[0])
    later["ap"] = 100.03
    values.append(later)
    body = json.dumps(values).encode()
    sources[digest(body)] = body
    rows[3]["payload"]["body_sha256"] = digest(body)
    result = link_execution_receipts(session, receipts(rows), sources)
    assert result["cost_input"]["orders"][0]["arrival_quote"]["ask"] == "100.12"
    assert (
        len(
            parse_alpaca_observation_frame(
                body, frame_index=1, received_at_ns=parse_timestamp_ns(instant(3))
            )
        )
        == 2
    )


def test_future_provider_nanosecond_is_not_hidden_by_microsecond_conversion():
    session, rows, sources = fixture()
    arrival = rows[3]["payload"]["body_sha256"]
    values = json.loads(sources[arrival])
    values[0]["t"] = "2026-10-02T14:00:00.000003001Z"
    body = json.dumps(values).encode()
    sources[digest(body)] = body
    rows[3]["payload"]["body_sha256"] = digest(body)
    with pytest.raises(EtfReceiptError):
        link_execution_receipts(session, receipts(rows), sources)


def test_equal_clock_values_do_not_allow_decision_forward_reference():
    session, rows, sources = fixture()
    rows[0], rows[1] = rows[1], rows[0]
    rows[0]["received_at"] = rows[1]["received_at"] = instant(0)
    rows[0]["received_monotonic_ns"] = rows[1]["received_monotonic_ns"] = 10
    with pytest.raises(EtfReceiptError):
        link_execution_receipts(session, receipts(rows), sources)


def test_identical_fill_redelivery_after_terminal_preserves_earliest_receipt():
    session, rows, sources = fixture()
    duplicate = deepcopy(rows[5])
    duplicate["received_at"], duplicate["received_monotonic_ns"] = instant(8), 90
    rows.append(duplicate)
    result = link_execution_receipts(session, receipts(rows), sources)
    assert result["cost_input"]["orders"][0]["fills"][0]["received_monotonic_ns"] == 60
    assert len(result["cost_input"]["orders"][0]["fills"]) == 2


def test_acknowledgement_after_first_fill_is_denied():
    session, rows, sources = fixture()
    rows[4], rows[5] = rows[5], rows[4]
    for i, row in enumerate(rows):
        row["received_at"], row["received_monotonic_ns"] = instant(i), (i + 1) * 10
    with pytest.raises(EtfReceiptError):
        link_execution_receipts(session, receipts(rows), sources)
