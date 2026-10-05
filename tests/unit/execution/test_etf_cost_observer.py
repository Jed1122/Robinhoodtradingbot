"""Use real private receipts and clocks; no authenticated broker evidence."""

import importlib
import json
from dataclasses import replace

import pytest

from tests.integration.execution.test_service import make_broker_order, make_review
from tests.unit.diagnostics.test_etf_execution_receipts import (
    START,
    directories,
    recorder,
)
from tests.unit.simulation.test_etf_account import intent
from trading_bot.diagnostics.etf_execution_receipts import read_execution_receipts
from trading_bot.domain import ExecutionMode, OrderState, PersistedReviewedOrder
from trading_bot.research.etf_execution_receipts import EtfReceiptError


def api():
    try:
        return importlib.import_module("trading_bot.execution.etf_cost_observer")
    except ModuleNotFoundError:
        pytest.fail("protected owner-to-receipt integration is missing")


def quote(sink):
    body = json.dumps(
        [
            {
                "T": "q",
                "S": "SPY",
                "t": START.isoformat(),
                "z": "B",
                "bp": 100,
                "ap": 100.1,
                "bs": 10,
                "as": 10,
                "bx": "P",
                "ax": "P",
                "c": ["R"],
            }
        ]
    ).encode()
    function = getattr(sink, "record_alpaca_frame", None)
    assert function is not None, "same-clock retained frame projection is missing"
    return function(body)[0].observation_hash


def submission(order):
    reviewed = make_review(order)
    return PersistedReviewedOrder(
        "review",
        "attempt",
        reviewed,
        "d" * 64,
        0,
        ExecutionMode.PAPER,
        None,
        None,
        order.account_id,
        order.config_hash,
    )


@pytest.mark.asyncio
async def test_owner_projection_uses_same_sink_and_safe_hashes(tmp_path):
    root, repository = directories(tmp_path)
    sink = recorder(root, repository)
    try:
        observer = api().EtfCostObserver(sink, decision_quote_hash=quote(sink))
        order = intent(at=START)
        await observer.decision(order)
        pending = submission(order)
        await observer.submitting(pending)
        await observer.responded(pending, make_broker_order(order, state=OrderState.SUBMITTED))
        linked = read_execution_receipts(root, sink.checkpoint(), repository)
        assert linked["incomplete_order_count"] == 1
        assert linked["completed_order_count"] == 0
        assert not linked["customer_authenticated"] and not linked["clock_session_attested"]
        bodies = b"".join(path.read_bytes() for path in root.iterdir())
        assert order.account_id.encode() not in bodies
        assert b"paper-broker-order-1" not in bodies
    finally:
        sink.close()


@pytest.mark.asyncio
async def test_unknown_decision_quote_denies_before_review(tmp_path):
    root, repository = directories(tmp_path)
    sink = recorder(root, repository)
    try:
        observer = api().EtfCostObserver(sink, decision_quote_hash="f" * 64)
        with pytest.raises(EtfReceiptError):
            await observer.decision(intent(at=START))
        with pytest.raises(EtfReceiptError):
            await observer.decision(intent(at=START))
    finally:
        sink.close()


@pytest.mark.asyncio
async def test_unmatched_response_never_becomes_acknowledgement(tmp_path):
    root, repository = directories(tmp_path)
    sink = recorder(root, repository)
    try:
        observer = api().EtfCostObserver(sink, decision_quote_hash=quote(sink))
        order = intent(at=START)
        await observer.decision(order)
        pending = submission(order)
        await observer.submitting(pending)
        changed = replace(
            make_broker_order(order, state=OrderState.SUBMITTED),
            requested_quantity=order.quantity * 2,
        )
        with pytest.raises(EtfReceiptError):
            await observer.responded(pending, changed)
    finally:
        sink.close()


@pytest.mark.asyncio
async def test_rejection_preserves_absent_fees_and_cannot_acknowledge_twice(tmp_path):
    root, repository = directories(tmp_path)
    sink = recorder(root, repository)
    try:
        observer = api().EtfCostObserver(sink, decision_quote_hash=quote(sink))
        order = intent(at=START)
        await observer.decision(order)
        pending = submission(order)
        await observer.submitting(pending)
        response = make_broker_order(order, state=OrderState.REJECTED)
        await observer.responded(pending, response)
        report = read_execution_receipts(root, sink.checkpoint(), repository)
        assert report["unfilled_order_count"] == 1
        assert report["unfilled_outcomes"][0]["charged_fees"] is None
        with pytest.raises(EtfReceiptError):
            await observer.responded(pending, response)
    finally:
        sink.close()


@pytest.mark.parametrize("hash_value", [None, "x", "A" * 64])
def test_invalid_quote_identity_cannot_construct_observer(tmp_path, hash_value):
    root, repository = directories(tmp_path)
    sink = recorder(root, repository)
    try:
        with pytest.raises(EtfReceiptError):
            api().EtfCostObserver(sink, decision_quote_hash=hash_value)
    finally:
        sink.close()


def test_foreign_recorder_cannot_construct_observer():
    with pytest.raises(EtfReceiptError):
        api().EtfCostObserver(object(), decision_quote_hash="a" * 64)


@pytest.mark.asyncio
async def test_submission_without_observed_decision_latches(tmp_path):
    root, repository = directories(tmp_path)
    sink = recorder(root, repository)
    try:
        observer = api().EtfCostObserver(sink, decision_quote_hash=quote(sink))
        with pytest.raises(EtfReceiptError):
            await observer.submitting(submission(intent(at=START)))
        with pytest.raises(EtfReceiptError):
            await observer.decision(intent(at=START))
    finally:
        sink.close()
