import json
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


def test_optional_stock_export_composes_only_a_config_bound_file_reader(tmp_path):
    state = tmp_path / "private"
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>fixture</html>")
    env = os.environ | {"PYTHONPATH": str(ROOT / "src")}
    initialize = subprocess.run(
        [sys.executable, "-m", "trading_bot.hybrid.cli", "--state-dir", str(state), "init"],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert initialize.returncode == 0
    code = """import sys, uvicorn
from trading_bot.hybrid import api
from trading_bot.runtime.stock_dashboard_export import (
    StockDashboardReader, StockDashboardExportError,
)
original = api.build_hybrid_app
def build(*args, **kwargs):
    reader = kwargs['stock_research_reader']
    assert isinstance(reader, StockDashboardReader)
    assert reader.maximum_age_seconds == 7200
    try:
        reader()
    except StockDashboardExportError:
        print('BOUND_READER_WITH_UNAVAILABLE_EXPORT')
    else:
        raise AssertionError('missing fixture export must not become research')
    return original(*args, **kwargs)
api.build_hybrid_app = build
uvicorn.run = lambda *args, **kwargs: None
state, static, export = sys.argv[1:]
from trading_bot.hybrid.cli import main
sys.argv = ['hybrid', '--state-dir', state, 'serve', '--dashboard-dir', static,
            '--stock-export-dir', export]
main()
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(state), str(static), str(tmp_path / "missing-export")],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "BOUND_READER_WITH_UNAVAILABLE_EXPORT"
    assert not (tmp_path / "missing-export").exists()
    assert (state / "dashboard.token").read_text().strip() not in result.stdout + result.stderr
