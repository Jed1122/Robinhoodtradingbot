import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trading_bot.config import load_config
from trading_bot.research.stock_dashboard import StockDashboardExport
from trading_bot.runtime.stock_dashboard_export import publish_stock_dashboard

ROOT = Path(__file__).resolve().parents[3]


def test_initialize_private_runtime_and_report(tmp_path):
    state = tmp_path / "private"
    args = [sys.executable, "-m", "trading_bot.hybrid.cli", "--state-dir", str(state)]
    env = os.environ | {"PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run([*args, "init"], env=env, cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (state / "dashboard.token").stat().st_mode & 0o777 == 0o600
    assert (state / "ledger.db").stat().st_mode & 0o777 == 0o600
    token = (state / "dashboard.token").read_text().strip()
    assert token not in result.stdout + result.stderr

    again = subprocess.run([*args, "init"], env=env, cwd=ROOT, capture_output=True, text=True)
    assert again.returncode != 0
    result = subprocess.run([*args, "report"], env=env, cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0
    assert '"live_enabled": false' in result.stdout
    assert token not in result.stdout + result.stderr


def test_server_preserves_structured_logging_boundary(tmp_path):
    state = tmp_path / "private"
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>fixture</html>")
    env = os.environ | {"PYTHONPATH": str(ROOT / "src")}
    init = subprocess.run(
        [sys.executable, "-m", "trading_bot.hybrid.cli", "--state-dir", str(state), "init"],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert init.returncode == 0
    code = """import sys, json, uvicorn
state, static = sys.argv[1:]
uvicorn.run = lambda app, **kw: print("OPTIONS=" + json.dumps(kw))
from trading_bot.hybrid.cli import main
sys.argv = ["hybrid", "--state-dir", state, "serve", "--dashboard-dir", static]
main()
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(state), str(static)],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    options = json.loads(
        next(line[8:] for line in result.stdout.splitlines() if line.startswith("OPTIONS="))
    )
    assert options.get("log_config", "missing") is None
    assert options.get("server_header", True) is False


@pytest.mark.parametrize(
    ("flags", "expected_success", "export_present"),
    [
        ({}, True, True),
        ({"LIVE_TRADING_ENABLED": "false", "PREDICTION_LIVE_ENABLED": "false"}, True, True),
        ({"LIVE_TRADING_ENABLED": "true", "PREDICTION_LIVE_ENABLED": "false"}, False, True),
        ({"LIVE_TRADING_ENABLED": "false", "PREDICTION_LIVE_ENABLED": "true"}, False, True),
        ({}, True, False),
    ],
)
def test_optional_stock_export_composes_only_a_config_bound_file_reader(
    tmp_path, flags, expected_success, export_present
):
    state = tmp_path / "private"
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>fixture</html>")
    env = os.environ | {"PYTHONPATH": str(ROOT / "src")}
    for key in ("LIVE_TRADING_ENABLED", "PREDICTION_LIVE_ENABLED"):
        env.pop(key, None)
    env.update(flags)
    initialize = subprocess.run(
        [sys.executable, "-m", "trading_bot.hybrid.cli", "--state-dir", str(state), "init"],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert initialize.returncode == 0
    loaded = load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/hybrid/paper.yaml",
        ROOT / "configs/hybrid/safety-envelope.yaml",
        {},
        hybrid_policy_path=ROOT / "configs/hybrid/policy.yaml",
        stock_research_policy_path=ROOT / "configs/hybrid/stock-research.yaml",
        stock_worker_policy_path=ROOT / "configs/hybrid/stock-worker.yaml",
    )
    export = tmp_path.resolve() / "export"
    projection = StockDashboardExport.model_validate(
        {
            "schema_version": 1,
            "kind": "stock_research_dashboard",
            "generated_at": datetime(2026, 10, 22, 12, tzinfo=UTC),
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
    original_projection = None
    if export_present:
        export.mkdir(mode=0o700)
        publish_stock_dashboard(root=export, export=projection)
        original_projection = (export / "stock-research.json").read_bytes()
    code = """import sys, uvicorn
from trading_bot.hybrid import api
from trading_bot.runtime import stock_research_worker as worker
from trading_bot.runtime.stock_dashboard_export import (
    StockDashboardReader, StockDashboardExportError,
)
def forbidden(*args, **kwargs):
    raise AssertionError('dashboard must not open a stock SDK or research ledger')
worker.RobinhoodMcpSdkConnection = forbidden
worker.SqlStockResearchJobs = forbidden
original = api.build_hybrid_app
def build(*args, **kwargs):
    reader = kwargs['stock_research_reader']
    assert isinstance(reader, StockDashboardReader)
    assert reader.maximum_age_seconds == 7200
    try:
        projection = reader()
    except StockDashboardExportError:
        assert export_present == 'False'
        print('BOUND_READER_WITH_UNAVAILABLE_EXPORT')
    else:
        assert export_present == 'True'
        assert projection.config_hash == expected_hash
        assert projection.live_enabled is projection.qualified is False
        assert projection.investment_eligible is False
        print('BOUND_READER_FROM_CANONICAL_POLICY')
    return original(*args, **kwargs)
api.build_hybrid_app = build
uvicorn.run = lambda *args, **kwargs: None
state, static, export, expected_hash, export_present = sys.argv[1:]
from trading_bot.hybrid.cli import main
sys.argv = ['hybrid', '--state-dir', state, 'serve', '--dashboard-dir', static,
            '--stock-export-dir', export]
main()
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(state),
            str(static),
            str(export),
            str(loaded.config_hash),
            str(export_present),
        ],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == (0 if expected_success else 2), result.stderr
    if expected_success:
        assert result.stdout.strip() == (
            "BOUND_READER_FROM_CANONICAL_POLICY"
            if export_present
            else "BOUND_READER_WITH_UNAVAILABLE_EXPORT"
        )
    else:
        assert not result.stdout.strip()
        assert "Hybrid runtime denied" in result.stderr
        assert str(export) not in result.stderr
    if export_present:
        assert (export / "stock-research.json").read_bytes() == original_projection
        assert {path.name for path in export.iterdir()} == {
            "stock-research.json",
            ".stock-research.lock",
        }
    else:
        assert not export.exists()
    assert (state / "dashboard.token").read_text().strip() not in result.stdout + result.stderr


def test_current_decision_feed_is_an_explicit_optional_read_only_projection_flag():
    result = subprocess.run(
        [sys.executable, "-m", "trading_bot.hybrid.cli", "serve", "--help"],
        cwd=ROOT,
        env=os.environ | {"PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--stock-decision-export-dir" in result.stdout
    assert "read-only current decision projection" in result.stdout
