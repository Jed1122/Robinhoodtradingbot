"""A second interpreter restores the coordinator's durable prefix."""

import json
import os
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from trading_bot.cli.etf_research import app

ROOT = Path(__file__).parents[3]


def test_new_process_restores_entry_before_completing_exit_and_settlement(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    cmd = [
        sys.executable,
        "-m",
        "trading_bot.cli.etf_research",
        "strategy-checkpoint-run",
        "--output-dir",
        str(root),
        "--operating-cost",
        "0.25",
    ]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    prefix = subprocess.run(
        [*cmd, "--through-ordinal", "753"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert prefix.returncode == 2, prefix.stdout + prefix.stderr
    row = json.loads(prefix.stdout)
    assert row["shares"] == "0.15" and row["trading_pnl"] is None
    assert row["paused"] and row["checkpoint_sequence"] == 1
    resumed = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    row = json.loads(resumed.stdout)
    assert row["cash"] == "499.63553015" and row["shares"] == "0"
    assert row["trading_pnl"] == "-0.36446985"
    assert row["operating_profit"] == "-0.61446985"
    assert row["checkpoint_sequence"] == 2
    assert not row["execution_enabled"] and not row["evidence_promotable"]
    again = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert again.returncode == 0 and again.stdout == resumed.stdout


def test_strategy_checkpoint_command_denies_invalid_or_shared_directories(tmp_path):
    tmp_path.chmod(0o755)
    result = CliRunner().invoke(app, ["strategy-checkpoint-run", "--output-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "denied"


def test_invalid_operating_cost_is_denied_before_checkpoint_publication(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    result = CliRunner().invoke(
        app,
        ["strategy-checkpoint-run", "--output-dir", str(root), "--operating-cost", "-1"],
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "denied"
    assert list(root.iterdir()) == []
