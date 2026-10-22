"""Private atomic projection storage; no data/broker connection is constructed."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trading_bot.config import load_config
from trading_bot.research.stock_dashboard import StockDashboardExport
from trading_bot.runtime.stock_dashboard_export import (
    StockDashboardExportError,
    StockDashboardReader,
    publish_stock_dashboard,
)

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)


@pytest.fixture
def data(tmp_path):
    loaded = load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/hybrid/paper.yaml",
        ROOT / "configs/hybrid/safety-envelope.yaml",
        {},
        hybrid_policy_path=ROOT / "configs/hybrid/policy.yaml",
        stock_research_policy_path=ROOT / "configs/hybrid/stock-research.yaml",
        stock_worker_policy_path=ROOT / "configs/hybrid/stock-worker.yaml",
    )
    root = tmp_path.resolve() / "export"
    root.mkdir(mode=0o700)
    projection = StockDashboardExport.model_validate(
        {
            "schema_version": 1,
            "kind": "stock_research_dashboard",
            "generated_at": NOW,
            "config_hash": str(loaded.config_hash),
            "code_hash": "b" * 64,
            "state_sha256": "c" * 64,
            "worker": {
                "last_claim_at": None,
                "last_result_at": None,
                "phase": None,
                "status": "never_run",
                "reason": None,
                "pending_claims": 0,
                "reserved_today": 0,
                "daily_limit": 512,
                "remaining_calls": 512,
                "next_eligible_at": None,
            },
            "discovery": None,
            "enrichment": None,
            "qualified": False,
            "investment_eligible": False,
            "live_enabled": False,
        }
    )
    return root, loaded, projection


def test_publish_round_trip_and_atomic_update_use_only_private_projection(data):
    root, loaded, projection = data
    result = publish_stock_dashboard(root=root, export=projection)
    assert result["status"] == "published" and len(result["sha256"]) == 64
    reader = StockDashboardReader(root=root, loaded=loaded)
    assert reader() == projection
    assert reader.maximum_age_seconds == 7200
    file = root / "stock-research.json"
    assert file.stat().st_mode & 0o777 == 0o600
    body = file.read_text()
    assert "private_account" not in body and "oauth" not in body
    assert json.loads(body)["live_enabled"] is False
    assert {p.name for p in root.iterdir()} == {"stock-research.json", ".stock-research.lock"}
    assert publish_stock_dashboard(root=root, export=projection)["sha256"] == result["sha256"]


@pytest.mark.parametrize(
    "unsafe", ["symlink", "hardlink", "public", "noncanonical", "oversized", "wrong_config"]
)
def test_reader_rejects_unsafe_changed_or_unbound_exports(data, unsafe):
    root, loaded, projection = data
    publish_stock_dashboard(root=root, export=projection)
    file = root / "stock-research.json"
    if unsafe == "symlink":
        file.rename(root / "other")
        file.symlink_to(root / "other")
    elif unsafe == "hardlink":
        os.link(file, root / "other")
    elif unsafe == "public":
        file.chmod(0o644)
    elif unsafe == "noncanonical":
        file.write_bytes(file.read_bytes() + b" ")
    elif unsafe == "oversized":
        file.write_bytes(b"x" * 262145)
    else:
        value = json.loads(file.read_text())
        value["config_hash"] = "d" * 64
        file.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")))
    with pytest.raises(StockDashboardExportError) as failure:
        StockDashboardReader(root=root, loaded=loaded)()
    assert str(failure.value) == "stock_dashboard_export_unavailable"
    assert str(root) not in str(failure.value)


def test_missing_reader_does_not_create_a_directory_or_file(data):
    root, loaded, _ = data
    missing = root / "missing"
    with pytest.raises(StockDashboardExportError):
        StockDashboardReader(root=missing, loaded=loaded)()
    assert not missing.exists()


def test_unknown_files_deny_publisher_without_repair_or_cleanup(data):
    root, _, projection = data
    unknown = root / "unrelated"
    unknown.write_bytes(b"preserve")
    unknown.chmod(0o600)
    with pytest.raises(StockDashboardExportError):
        publish_stock_dashboard(root=root, export=projection)
    assert list(root.iterdir()) == [unknown]
    assert unknown.read_bytes() == b"preserve"


def test_replace_failure_preserves_prior_projection_and_releases_lock(data, monkeypatch):
    from trading_bot.runtime import stock_dashboard_export as module

    root, loaded, projection = data
    publish_stock_dashboard(root=root, export=projection)
    original = (root / "stock-research.json").read_bytes()

    def fail(*args, **kwargs):
        raise OSError("private-error-do-not-log")

    with monkeypatch.context() as patch:
        patch.setattr(module.os, "replace", fail)
        with pytest.raises(StockDashboardExportError):
            publish_stock_dashboard(root=root, export=projection)
    assert (root / "stock-research.json").read_bytes() == original
    assert StockDashboardReader(root=root, loaded=loaded)() == projection
    publish_stock_dashboard(root=root, export=projection)
    assert not any(p.name.startswith(".pending-") for p in root.iterdir())


def test_publisher_revalidates_forged_model_without_creating_artifacts(data):
    root, _, projection = data
    with pytest.raises(StockDashboardExportError):
        publish_stock_dashboard(
            root=root, export=projection.model_copy(update={"live_enabled": True})
        )
    assert list(root.iterdir()) == []
