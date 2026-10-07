"""Adversarial local receipt regressions using only fresh synthetic directories."""

import os
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.integration.execution.test_service import make_broker_order
from tests.unit.diagnostics.test_etf_execution_receipts import START, directories, recorder
from tests.unit.diagnostics.test_etf_fee_attachments import api, completed, publish
from tests.unit.execution.test_etf_cost_observer import quote, submission
from tests.unit.execution.test_etf_cost_observer_lifecycle import event, setup_observer
from tests.unit.simulation.test_etf_account import intent
from trading_bot.diagnostics.etf_execution_receipts import read_execution_receipts
from trading_bot.domain import OrderEvent, OrderState
from trading_bot.execution.etf_cost_observer import EtfCostObserver
from trading_bot.research.etf_execution_receipts import EtfReceiptError


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["initial_fill", "future_created", "future_updated"])
async def test_initial_anchor_requires_zero_fills_and_nonfuture_times(tmp_path, invalid):
    root, repository = directories(tmp_path)
    sink = recorder(root, repository)
    try:
        observer = EtfCostObserver(sink, decision_quote_hash=quote(sink))
        order = intent(at=START, quantity=Decimal("3"))
        await observer.decision(order)
        pending = submission(order)
        await observer.submitting(pending)
        response = replace(
            make_broker_order(order, state=OrderState.SUBMITTED),
            created_at=START,
            updated_at=START,
        )
        if invalid == "initial_fill":
            response = replace(response, filled_quantity=Decimal("1"))
        elif invalid == "future_created":
            response = replace(
                response,
                created_at=START + timedelta(days=1),
                updated_at=START + timedelta(days=1),
            )
        else:
            response = replace(response, updated_at=START + timedelta(days=1))
        prefix = sink.checkpoint()
        originals = {path.name: path.read_bytes() for path in root.iterdir()}
        with pytest.raises(EtfReceiptError):
            await observer.responded(pending, response)
        assert {path.name: path.read_bytes() for path in root.iterdir()} == originals
        retained = read_execution_receipts(root, prefix, repository)
        assert retained["completed_order_count"] == 0
        assert retained["incomplete_order_count"] == 1
    finally:
        sink.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", ["fill_id", "reused_ordinal", "gapped_ordinal"])
async def test_lifecycle_rejects_impossible_durable_fill_identity(tmp_path, identity):
    root, repository, sink, observer, order = await setup_observer(tmp_path)
    try:
        first = event(order, 1)
        await observer.observed(first)
        prefix = sink.checkpoint()
        second = event(order, 2, OrderEvent.FILL, "2")
        if identity == "fill_id":
            second = replace(second, fill=replace(second.fill, id=first.fill.id))
        elif identity == "reused_ordinal":
            second = replace(second, occurrence_ordinal=0)
        else:
            second = replace(second, occurrence_ordinal=8000)
        with pytest.raises(EtfReceiptError):
            await observer.observed(second)
        with pytest.raises(EtfReceiptError):
            await observer.observed(first)
        retained = read_execution_receipts(root, prefix, repository)
        assert retained["completed_order_count"] == 0
        assert retained["incomplete_order_count"] == 1
    finally:
        sink.close()


@pytest.mark.asyncio
async def test_lifecycle_cannot_receive_a_fill_before_its_occurrence(tmp_path):
    root, repository, sink, observer, order = await setup_observer(tmp_path)
    try:
        prefix = sink.checkpoint()
        future = START + timedelta(days=1)
        received = event(order, 1, OrderEvent.FILL, "3")
        received = replace(
            received,
            occurred_at=future,
            fill=replace(received.fill, occurred_at=future),
        )
        with pytest.raises(EtfReceiptError):
            await observer.observed(received)
        retained = read_execution_receipts(root, prefix, repository)
        assert retained["completed_order_count"] == 0
        assert retained["incomplete_order_count"] == 1
    finally:
        sink.close()


@pytest.mark.asyncio
async def test_clock_callback_cannot_change_the_checked_nested_fill(tmp_path, monkeypatch):
    root, repository, sink, observer, order = await setup_observer(tmp_path)
    try:
        checked = event(order, 1, OrderEvent.FILL, "3")
        original_clock = sink._utc_now

        def mutating_clock():
            # Frozen dataclasses do not make references safe across callbacks.
            object.__setattr__(checked.fill, "quantity", Decimal("1"))
            return original_clock()

        monkeypatch.setattr(sink, "_utc_now", mutating_clock)
        await observer.observed(checked)
        retained = read_execution_receipts(root, sink.checkpoint(), repository)
        assert retained["completed_order_count"] == 1
        assert [fill["quantity"] for fill in retained["cost_input"]["orders"][0]["fills"]] == [
            "3"
        ]
    finally:
        sink.close()


@pytest.mark.asyncio
async def test_exact_fee_retry_does_not_need_a_new_clock_sample(tmp_path):
    root, repository, checkpoint, original = await completed(tmp_path)
    first = publish(root, repository, checkpoint, original)
    originals = {path.name: path.read_bytes() for path in root.iterdir()}

    class UnavailableClock:
        def now(self):
            raise RuntimeError("synthetic unavailable clock")

    repeated = publish(root, repository, checkpoint, original, clock=UnavailableClock())
    assert repeated == first
    assert {path.name: path.read_bytes() for path in root.iterdir()} == originals
    assert api().read_fee_attachment(root, repeated, repository)["fee_observed_at"] == (
        "2026-10-04T14:00:00.000000Z"
    )


@pytest.mark.asyncio
async def test_retry_repairs_uncertain_fee_binding_directory_durability(tmp_path, monkeypatch):
    root, repository, checkpoint, original = await completed(tmp_path)
    real_fsync = os.fsync
    root_stat = root.stat()
    uncertain = False

    def is_root_directory(descriptor):
        info = os.fstat(descriptor)
        return (info.st_dev, info.st_ino) == (root_stat.st_dev, root_stat.st_ino)

    def fail_after_binding_link(descriptor):
        nonlocal uncertain
        if is_root_directory(descriptor) and list(root.glob("*.fee-binding")):
            uncertain = True
            raise OSError("synthetic post-link directory fsync failure")
        return real_fsync(descriptor)

    with monkeypatch.context() as failure:
        failure.setattr(os, "fsync", fail_after_binding_link)
        with pytest.raises(EtfReceiptError):
            publish(root, repository, checkpoint, original)
    assert uncertain
    assert len(list(root.glob("*.fee-binding"))) == 1

    repaired = False

    def repair_directory(descriptor):
        nonlocal repaired
        result = real_fsync(descriptor)
        if is_root_directory(descriptor):
            repaired = True
        return result

    with monkeypatch.context() as retry:
        retry.setattr(os, "fsync", repair_directory)
        attachment = publish(root, repository, checkpoint, original)
    assert repaired, "a successful retry must durably recover the uncertain binding"
    assert api().read_fee_attachment(root, attachment, repository)["missing_fee_order_count"] == 0


@pytest.mark.asyncio
async def test_unencodable_fee_report_cannot_poison_the_authoritative_binding(tmp_path):
    root, repository, checkpoint, original = await completed(tmp_path)
    # Exact components fit the input bound, but their rounded summary does not.
    fees = {name: "0" for name in ("commission", "sec", "taf", "cat", "other", "total")}
    fees["other"] = fees["total"] = "9" * 512
    with pytest.raises(EtfReceiptError):
        publish(root, repository, checkpoint, original, charged_fees=fees)
    assert not list(root.glob("*.fee-binding"))
    attachment = publish(root, repository, checkpoint, original)
    result = api().read_fee_attachment(root, attachment, repository)
    assert result["missing_fee_order_count"] == 0
    assert result["cost_input"]["orders"][0]["charged_fees"]["total"] == "0.03"
