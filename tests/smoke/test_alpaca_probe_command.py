"""Run the actual diagnostic command with temporary paths and no real credentials."""

import json
import os
import runpy
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/probe_alpaca_data.py"


def run(*arguments):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )


def arguments(tmp_path):
    root = tmp_path.resolve() / "private"
    root.mkdir(mode=0o700)
    return [
        "--manifest-file",
        str(root / "manifest.json"),
        "--credential-file",
        str(root / "absent-key.json"),
        "--quarantine-root",
        str(root / "absent-raw"),
        "--requested-end",
        (datetime.now(UTC) - timedelta(days=2)).isoformat(),
    ]


def test_help_exposes_no_arbitrary_endpoint_or_trading_flags():
    result = run("--help")
    assert result.returncode == 0
    assert "--prepare" in result.stdout and "--capture" in result.stdout
    for flag in ("--host", "--url", "--live", "--order", "--retry", "--feed"):
        assert flag not in result.stdout


def test_default_preparation_is_private_and_does_not_read_missing_credential(tmp_path):
    args = arguments(tmp_path)
    result = run(*args)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["status"] == "prepared_offline"
    assert output["disposition"] == "BLOCKED_PREREQUISITES"
    assert output["checks"]["requested_history"]["status"] == "not_checked"
    assert output["minimum_history_bars"] == 750
    assert "private" not in result.stdout
    path = Path(args[1])
    assert path.stat().st_mode & 0o777 == 0o600
    assert not Path(args[3]).exists() and not Path(args[5]).exists()
    assert not result.stderr
    first = path.read_bytes()
    repeated = run(*args)
    assert repeated.returncode == 2
    assert path.read_bytes() == first


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--capture"],
        ["--capture", "--prepare"],
        ["--secret-key", "synthetic-do-not-echo"],
        ["--approved-manifest-sha256", "a" * 64],
    ],
)
def test_invalid_invocations_fail_closed_without_argument_echo(args):
    result = run(*args)
    assert result.returncode == 2
    assert json.loads(result.stdout)["disposition"] == "BLOCKED_PREREQUISITES"
    assert "synthetic-do-not-echo" not in result.stdout + result.stderr


def test_prepare_cannot_overwrite_an_existing_private_file(tmp_path):
    args = arguments(tmp_path)
    manifest = Path(args[1])
    manifest.write_bytes(b"synthetic-do-not-read-or-replace")
    manifest.chmod(0o600)
    result = run(*args)
    assert result.returncode == 2
    assert manifest.read_bytes() == b"synthetic-do-not-read-or-replace"
    assert "synthetic-do-not-read-or-replace" not in result.stdout + result.stderr


def test_no_capture_without_the_exact_scope_digest(tmp_path):
    args = arguments(tmp_path)
    assert run(*args).returncode == 0
    result = run("--capture", "--manifest-file", args[1], "--approved-manifest-sha256", "0" * 64)
    assert result.returncode == 2
    assert json.loads(result.stdout)["checks"]["technical_access"]["status"] == "not_checked"
    assert not Path(args[3]).exists()


def test_failed_run_does_not_claim_zero_retained_samples():
    summary = runpy.run_path(str(SCRIPT))["_summary"]
    result = summary(
        now=datetime.now(UTC),
        status="blocked",
        code="probe_access_denied",
        loaded=None,
        digest="a" * 64,
        receipts=(),
    )
    assert result["sample_count"] is None
    assert result["sample_body_sha256"] is None
    assert result["checks"]["original_bytes"]["status"] == "not_checked"


def test_sample_report_cannot_certify_history_or_rights():
    from trading_bot.diagnostics.alpaca_probe import ProbeReceipt

    summary = runpy.run_path(str(SCRIPT))["_summary"]
    now = datetime.now(UTC)
    receipts = tuple(
        ProbeReceipt("a" * 64, index, now, now, 200, "b" * 64, 2, "probe_sample_retained")
        for index in range(2)
    )
    result = summary(
        now=now,
        status="capture_completed",
        code="probe_sample_retained",
        loaded=None,
        digest="a" * 64,
        receipts=receipts,
    )
    assert result["sample_count"] == 2
    assert result["disposition"] == "INSUFFICIENT_SOURCE_EVIDENCE"
    assert result["checks"]["technical_access"]["status"] == "observed_pass"
    assert result["checks"]["requested_history"]["status"] == "not_checked"
    assert result["checks"]["retention_rights"]["status"] == "unresolved"
    assert len(result["checks"]) == 14
