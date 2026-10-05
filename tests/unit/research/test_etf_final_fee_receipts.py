"""A terminal order may receive later explicit final fees, never inferred zeros."""

from copy import deepcopy

import pytest

from tests.unit.research.test_etf_execution_receipts import (
    ORDER,
    digest,
    encode,
    fixture,
    instant,
    receipts,
)
from trading_bot.research.etf_execution_receipts import EtfReceiptError, link_execution_receipts


def delayed():
    session, rows, sources = fixture()
    fees = deepcopy(rows[-1]["payload"]["charged_fees"])
    rows[-1]["payload"]["charged_fees"] = None
    terminal_hash = digest(receipts(rows)[-1])
    fee_source = encode({"schema": "synthetic-final-fees-v1", "total": "0.03"})
    fee_hash = digest(fee_source)
    sources[fee_hash] = fee_source
    fees["source_hash"] = fee_hash
    row = {
        "schema": "etf-execution-receipt-v2",
        "session_hash": digest(session),
        "sequence": len(rows),
        "previous_hash": None,
        "kind": "final_fees",
        "received_at": instant(20),
        "received_monotonic_ns": 210,
        "payload": {
            "order_hash": ORDER,
            "terminal_hash": terminal_hash,
            "source_hash": fee_hash,
            "charged_fees": fees,
        },
    }
    return session, rows, sources, row


def test_delayed_final_fee_links_once_without_changing_execution_clock():
    session, rows, sources, later = delayed()
    before = link_execution_receipts(session, receipts(rows), sources)
    assert before["missing_fee_order_count"] == 1
    after = link_execution_receipts(session, receipts([*rows, later]), sources)
    assert after["missing_fee_order_count"] == 0
    original, finalized = before["cost_input"]["orders"][0], after["cost_input"]["orders"][0]
    assert finalized["charged_fees"]["total"] == "0.03"
    assert finalized["terminal_monotonic_ns"] == original["terminal_monotonic_ns"]
    assert after["calibration_verified"] is False
    assert after["customer_authenticated"] is False


def test_exact_final_fee_redelivery_is_idempotent():
    session, rows, sources, later = delayed()
    one = link_execution_receipts(session, receipts([*rows, later]), sources)
    twice = link_execution_receipts(session, receipts([*rows, later, later]), sources)
    assert twice == one


@pytest.mark.parametrize("change", ["terminal", "order", "missing", "total", "source", "v1"])
def test_invalid_final_fee_evidence_denies(change):
    session, rows, sources, later = delayed()
    if change == "terminal":
        later["payload"]["terminal_hash"] = "f" * 64
    elif change == "order":
        later["payload"]["order_hash"] = "f" * 64
    elif change == "missing":
        later["payload"]["charged_fees"] = None
    elif change == "total":
        later["payload"]["charged_fees"]["total"] = "0.04"
    elif change == "source":
        later["payload"]["charged_fees"]["source_hash"] = "f" * 64
    else:
        later["schema"] = "etf-execution-receipt-v1"
    with pytest.raises(EtfReceiptError):
        link_execution_receipts(session, receipts([*rows, later]), sources)


def test_conflicting_finalization_cannot_overwrite_previous_components():
    session, rows, sources, later = delayed()
    conflict = deepcopy(later)
    conflict["payload"]["charged_fees"]["other"] = "0.01"
    conflict["payload"]["charged_fees"]["total"] = "0.04"
    with pytest.raises(EtfReceiptError):
        link_execution_receipts(session, receipts([*rows, later, conflict]), sources)


def test_explicit_zero_is_final_but_not_inferred_from_missing():
    session, rows, sources, later = delayed()
    for name in ("commission", "sec", "taf", "cat", "other", "total"):
        later["payload"]["charged_fees"][name] = "0"
    result = link_execution_receipts(session, receipts([*rows, later]), sources)
    assert result["missing_fee_order_count"] == 0
    assert result["cost_input"]["orders"][0]["charged_fees"]["total"] == "0"


@pytest.mark.parametrize(
    "kind", ["alpaca_frame", "decision", "submitted", "acknowledged", "fill", "terminal"]
)
def test_v2_is_reserved_for_additive_final_fee_events(kind):
    session, rows, sources = fixture()
    next(row for row in rows if row["kind"] == kind)["schema"] = "etf-execution-receipt-v2"
    with pytest.raises(EtfReceiptError):
        link_execution_receipts(session, receipts(rows), sources)
