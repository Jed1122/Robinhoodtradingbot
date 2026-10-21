import os
import subprocess
import sys
from pathlib import Path

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
