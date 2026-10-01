"""Strict receipt-bound latest-vintage reads; never original-history qualification."""

import importlib
from dataclasses import replace

import httpx
import pytest

from tests.unit.diagnostics.test_alpaca_capture import (
    api as capture_api,
)
from tests.unit.diagnostics.test_alpaca_capture import (
    body,
    run,
)
from tests.unit.diagnostics.test_alpaca_capture import (
    loaded as loaded,
)
from tests.unit.diagnostics.test_alpaca_capture import (
    manifest as manifest,
)
from tests.unit.diagnostics.test_alpaca_capture import (
    ready as ready,
)


def api():
    try:
        return importlib.import_module("trading_bot.market_data.etf_native_archive")
    except ModuleNotFoundError:
        pytest.fail("Receipt-bound ETF latest-vintage archive reader is missing")


async def capture(ready, loaded, monkeypatch):
    async def send(self, request, **kwargs):
        return httpx.Response(
            200, stream=httpx.ByteStream(body()), headers={"content-type": "application/json"}
        )

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    result = await run(ready, loaded)
    assert result.pagination_complete
    return capture_api().capture_manifest_sha256(ready), result


async def test_native_receipts_can_be_read_without_broker_or_credential_access(
    ready, loaded, monkeypatch
):
    digest, _ = await capture(ready, loaded, monkeypatch)
    ready.credential_file.unlink()
    archive = api().read_etf_native_bars(
        ready.quarantine_root, digest, repository_root=ready.repository_root
    )
    assert len(archive.bars) == 1
    assert archive.bars[0].close == 201
    assert archive.bars[0].publication_at_ns is None
    assert archive.source_kind == "alpaca-sip-latest-vintage-v1"
    assert not archive.source_qualified and not archive.evidence_promotable
    assert "original_correction_timeline_waived" in archive.limitations


async def test_changed_raw_receipt_truncation_and_symlink_deny(ready, loaded, monkeypatch):
    digest, result = await capture(ready, loaded, monkeypatch)
    receipt_path = ready.quarantine_root / (result.receipt_sha256s[0] + ".capture-receipt.json")
    original = receipt_path.read_bytes()
    receipt_path.write_bytes(original + b" ")
    with pytest.raises(ValueError, match="etf_native_archive_invalid"):
        api().read_etf_native_bars(
            ready.quarantine_root, digest, repository_root=ready.repository_root
        )
    receipt_path.write_bytes(original)
    target = ready.quarantine_root / "other.json"
    receipt_path.rename(target)
    receipt_path.symlink_to(target)
    with pytest.raises(ValueError, match="etf_native_archive_invalid"):
        api().read_etf_native_bars(
            ready.quarantine_root, digest, repository_root=ready.repository_root
        )


async def test_archive_identity_binds_manifest_and_rows(ready, loaded, monkeypatch):
    digest, _ = await capture(ready, loaded, monkeypatch)
    archive = api().read_etf_native_bars(
        ready.quarantine_root, digest, repository_root=ready.repository_root
    )
    changed = replace(archive, bars=(replace(archive.bars[0], close=archive.bars[0].open),))
    assert archive.archive_hash != changed.archive_hash
