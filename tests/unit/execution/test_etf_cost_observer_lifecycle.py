"""Checked local lifecycle facts and real private sink; no broker transport."""

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.integration.execution.test_service import make_broker_order
from tests.unit.diagnostics.test_etf_execution_receipts import START, directories, recorder
from tests.unit.execution.test_etf_cost_observer import api, quote, submission
from tests.unit.simulation.test_etf_account import intent
from trading_bot.diagnostics.etf_execution_receipts import read_execution_receipts
from trading_bot.domain import DataHash, Fill, FillId, OrderEvent, OrderState
from trading_bot.domain.owned_order_lifecycle import OwnedOrderEvent
from trading_bot.research.etf_execution_receipts import EtfReceiptError


async def setup_observer(tmp_path):
    root, repository = directories(tmp_path)
    sink = recorder(root, repository)
    observer = api().EtfCostObserver(sink, decision_quote_hash=quote(sink))
    order = intent(at=START, quantity=Decimal("3"))
    await observer.decision(order)
    pending = submission(order)
    await observer.submitting(pending)
    accepted = replace(
        make_broker_order(order, state=OrderState.SUBMITTED),
        created_at=START,
        updated_at=START,
    )
    await observer.responded(pending, accepted)
    sink.record_alpaca_frame(
        json.dumps(
            [
                {
                    "T": "q",
                    "S": "SPY",
                    "t": (START + timedelta(microseconds=4)).isoformat(),
                    "z": "B",
                    "bp": 99.8,
                    "ap": 100,
                    "bs": 10,
                    "as": 10,
                    "bx": "P",
                    "ax": "P",
                    "c": ["R"],
                }
            ]
        ).encode()
    )
    return root, repository, sink, observer, accepted


def event(order, number, kind=OrderEvent.PARTIAL_FILL, quantity="1", **changes):
    filled = kind in {OrderEvent.PARTIAL_FILL, OrderEvent.FILL}
    stamp = START + timedelta(microseconds=number)
    value = OwnedOrderEvent(
        id=f"event-{number}",
        order_id=order.id,
        event=kind,
        occurred_at=stamp,
        data_hash=DataHash("e" * 64),
        fill=Fill(
            id=FillId(f"fill-{number}"),
            broker_order_id=order.broker_order_id,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            side=order.side,
            quantity=Decimal(quantity),
            price=Decimal("100"),
            fee=Decimal(".01"),
            occurred_at=stamp,
            data_hash=DataHash("f" * 64),
        )
        if filled
        else None,
        external_execution_key=f"native-{number}" if filled else None,
        occurrence_ordinal=number - 1 if filled else None,
    )
    return replace(value, **changes)


def observed(observer):
    method = getattr(observer, "observed", None)
    assert method is not None, "owned fill/terminal recorder integration is missing"
    return method


@pytest.mark.asyncio
async def test_partial_final_and_exact_redelivery_preserve_first_receipt(tmp_path):
    root, repository, sink, observer, order = await setup_observer(tmp_path)
    try:
        observe = observed(observer)
        partial = event(order, 1)
        await observe(partial)
        before = sink.checkpoint()
        await observe(partial)
        assert sink.checkpoint() == before
        await observe(event(order, 2, OrderEvent.FILL, "2"))
        report = read_execution_receipts(root, sink.checkpoint(), repository)
        assert report["completed_order_count"] == 1
        assert report["incomplete_order_count"] == 0
        sample = report["cost_input"]["orders"][0]
        assert [f["quantity"] for f in sample["fills"]] == ["1", "2"]
        assert [f["price"] for f in sample["fills"]] == ["100", "100"]
        assert sample["charged_fees"] is None
        assert report["customer_authenticated"] is False
        assert report["calibration_verified"] is False
        original = {p.name: p.read_bytes() for p in root.iterdir()}
        await observe(event(order, 2, OrderEvent.FILL, "2"))
        assert {p.name: p.read_bytes() for p in root.iterdir()} == original
        assert order.account_id.encode() not in b"".join(original.values())
        assert order.broker_order_id.encode() not in b"".join(original.values())
    finally:
        sink.close()


@pytest.mark.asyncio
async def test_partial_cancel_race_stays_incomplete_until_confirmation(tmp_path):
    root, repository, sink, observer, order = await setup_observer(tmp_path)
    try:
        observe = observed(observer)
        await observe(event(order, 1, OrderEvent.REQUEST_CANCEL))
        await observe(event(order, 2, occurrence_ordinal=0))
        before = read_execution_receipts(root, sink.checkpoint(), repository)
        assert before["incomplete_order_count"] == 1
        await observe(event(order, 3, OrderEvent.CANCEL_CONFIRMED))
        after = read_execution_receipts(root, sink.checkpoint(), repository)
        assert after["completed_order_count"] == 1
        assert after["cost_input"]["orders"][0]["fills"][0]["quantity"] == "1"
    finally:
        sink.close()


@pytest.mark.asyncio
async def test_expiry_is_expiry_in_new_version_and_does_not_infer_fees(tmp_path):
    root, repository, sink, observer, order = await setup_observer(tmp_path)
    try:
        await observed(observer)(event(order, 1, OrderEvent.BROKER_EXPIRED))
        report = read_execution_receipts(root, sink.checkpoint(), repository)
        assert report["unfilled_outcomes"][0]["state"] == "expired"
        assert report["unfilled_outcomes"][0]["charged_fees"] is None
        assert any(b"etf-execution-receipt-v3" in p.read_bytes() for p in root.iterdir())
    finally:
        sink.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["quantity", "account", "native_identity", "terminal"])
async def test_conflict_wrong_account_and_overfill_latch_without_second_sample(tmp_path, changed):
    root, repository, sink, observer, order = await setup_observer(tmp_path)
    try:
        observe = observed(observer)
        first = event(order, 1)
        await observe(first)
        prefix = sink.checkpoint()
        if changed == "quantity":
            bad = replace(first, fill=replace(first.fill, quantity=Decimal("2")))
        elif changed == "account":
            bad = event(order, 2, fill=replace(first.fill, account_id="other-account"))
        elif changed == "native_identity":
            bad = event(order, 2, external_execution_key=first.external_execution_key)
        else:
            bad = event(order, 2, OrderEvent.FILL, "3")
        with pytest.raises(EtfReceiptError):
            await observe(bad)
        with pytest.raises(EtfReceiptError):
            await observe(first)
        assert read_execution_receipts(root, prefix, repository)["incomplete_order_count"] == 1
    finally:
        sink.close()


@pytest.mark.asyncio
async def test_recording_failure_keeps_previous_checkpoint_and_latches(tmp_path, monkeypatch):
    import trading_bot.diagnostics.etf_execution_receipts as module

    root, repository, sink, observer, order = await setup_observer(tmp_path)
    try:
        prefix = sink.checkpoint()
        observe = observed(observer)

        def fail(*args):
            raise OSError("synthetic disk failure")

        monkeypatch.setattr(module, "_publish", fail)
        with pytest.raises(EtfReceiptError):
            await observe(event(order, 1))
        monkeypatch.undo()
        with pytest.raises(EtfReceiptError):
            await observe(event(order, 1))
        assert read_execution_receipts(root, prefix, repository)["incomplete_order_count"] == 1
        assert order.filled_quantity == Decimal("0")
    finally:
        sink.close()
