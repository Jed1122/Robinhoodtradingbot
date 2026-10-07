"""Later fee documents attach to immutable synthetic execution checkpoints."""

import importlib
import importlib.util
import json
import stat
from dataclasses import dataclass
from datetime import timedelta

import pytest

from tests.unit.diagnostics.test_etf_execution_receipts import START
from tests.unit.execution.test_etf_cost_observer_lifecycle import event, setup_observer
from trading_bot.diagnostics.etf_execution_receipts import read_execution_receipts
from trading_bot.domain import OrderEvent
from trading_bot.research.etf_execution_receipts import EtfReceiptError


@dataclass
class LaterClock:
    def now(self):
        return START + timedelta(days=2)


def api():
    name = "trading_bot.diagnostics.etf_fee_attachments"
    assert importlib.util.find_spec(name) is not None, "cross-session fee attachment is missing"
    return importlib.import_module(name)


async def completed(tmp_path):
    root, repository, sink, observer, order = await setup_observer(tmp_path)
    await observer.observed(event(order, 1, OrderEvent.FILL, "3"))
    checkpoint = sink.checkpoint()
    sink.close()
    original = read_execution_receipts(root, checkpoint, repository)
    return root, repository, checkpoint, original


def publish(root, repository, checkpoint, original, **changes):
    kwargs = dict(
        order_hash=original["cost_input"]["orders"][0]["order_hash"],
        charged_fees={
            "commission": "0",
            "sec": "0.01",
            "taf": "0.02",
            "cat": "0",
            "other": "0",
            "total": "0.03",
        },
        source=b"synthetic final fee document",
        clock=LaterClock(),
        repository_root=repository,
    )
    kwargs.update(changes)
    return api().publish_fee_attachment(root, checkpoint, **kwargs)


@pytest.mark.asyncio
async def test_later_process_fee_attachment_preserves_original_bytes_and_timings(tmp_path):
    root, repository, checkpoint, original = await completed(tmp_path)
    old_bytes = {p.name: p.read_bytes() for p in root.iterdir()}
    digest = publish(root, repository, checkpoint, original)
    result = api().read_fee_attachment(root, digest, repository)
    assert result["missing_fee_order_count"] == 0
    updated = result["cost_input"]["orders"][0]
    assert updated["charged_fees"]["total"] == "0.03"
    old_order = original["cost_input"]["orders"][0]
    assert {k: v for k, v in updated.items() if k != "charged_fees"} == {
        k: v for k, v in old_order.items() if k != "charged_fees"
    }
    assert result["clock_session_hash"] == original["clock_session_hash"]
    assert result["fee_observed_at"] == "2026-10-04T14:00:00.000000Z"
    assert not result["customer_authenticated"] and not result["calibration_verified"]
    assert not result["execution_enabled"] and not result["evidence_promotable"]
    assert all((root / name).read_bytes() == body for name, body in old_bytes.items())
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in root.iterdir())
    assert read_execution_receipts(root, checkpoint, repository) == original


@pytest.mark.asyncio
async def test_exact_retry_reuses_original_attachment_and_conflict_denies(tmp_path):
    root, repository, checkpoint, original = await completed(tmp_path)
    first = publish(root, repository, checkpoint, original)
    files = {p.name: p.read_bytes() for p in root.iterdir()}
    assert publish(root, repository, checkpoint, original) == first
    assert files == {p.name: p.read_bytes() for p in root.iterdir()}
    with pytest.raises(EtfReceiptError):
        publish(root, repository, checkpoint, original, source=b"different final fee document")
    assert api().read_fee_attachment(root, first, repository)["missing_fee_order_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["missing_component", "wrong_total", "wrong_order", "old_time"])
async def test_missing_or_inconsistent_evidence_never_becomes_final_fees(tmp_path, bad):
    root, repository, checkpoint, original = await completed(tmp_path)
    changes = {}
    if bad in {"missing_component", "wrong_total"}:
        fees = {
            "commission": "0",
            "sec": "0.01",
            "taf": "0.02",
            "cat": "0",
            "other": "0",
            "total": "0.03",
        }
        if bad == "missing_component":
            del fees["cat"]
        else:
            fees["total"] = "0"
        changes["charged_fees"] = fees
    elif bad == "wrong_order":
        changes["order_hash"] = "a" * 64
    else:

        class OldClock:
            def now(self):
                return START - timedelta(days=1)

        changes["clock"] = OldClock()
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    with pytest.raises(EtfReceiptError):
        publish(root, repository, checkpoint, original, **changes)
    assert before == {p.name: p.read_bytes() for p in root.iterdir()}


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt", ["checkpoint", "fee_source", "binding", "mode"])
async def test_restart_rehashes_original_checkpoint_source_and_binding(tmp_path, corrupt):
    root, repository, checkpoint, original = await completed(tmp_path)
    digest = publish(root, repository, checkpoint, original)
    payload = json.loads((root / (digest + ".source")).read_bytes())
    if corrupt == "checkpoint":
        path = root / (checkpoint + ".source")
    elif corrupt == "fee_source":
        path = root / (payload["source_hash"] + ".source")
    elif corrupt == "binding":
        path = next(root.glob("*.fee-binding"))
    else:
        path = root / (digest + ".source")
        path.chmod(0o644)
    if corrupt != "mode":
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(EtfReceiptError):
        api().read_fee_attachment(root, digest, repository)
