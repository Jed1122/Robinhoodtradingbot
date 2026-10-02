"""Coverage report publication cannot certify execution or inspect a holdout."""

import hashlib
import json

from typer.testing import CliRunner

from tests.unit.research.test_etf_execution_coverage import inputs, ns, quotes
from trading_bot.cli import etf_research


def test_coverage_command_records_missing_sessions_without_simulating_orders(tmp_path, monkeypatch):
    bars, calendar = inputs()
    opened = ns(calendar.sessions[-1].opens_at)
    probe = quotes("probe", opened, opened + 10**9)
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    calendar_file = root / "calendar.json"
    body = json.dumps(
        {
            "request": {"start_date": "2016-01-01", "end_date": "2025-12-31"},
            "calendar": [
                {
                    "date": s.session_date.isoformat(),
                    "open": s.session_date.isoformat() + "T09:30:00",
                    "close": s.session_date.isoformat() + "T16:00:00",
                }
                for s in calendar.sessions
            ],
        }
    ).encode()
    calendar_file.write_bytes(body)
    calendar_file.chmod(0o600)
    reports = root / "reports"
    reports.mkdir(mode=0o700)
    # The separately tested receipt reader owns transport/raw hash validation;
    # this command test exercises calendar I/O, real coverage and publication.
    monkeypatch.setattr(etf_research, "read_etf_native_bars", lambda *a, **k: bars)
    monkeypatch.setattr(etf_research, "read_etf_native_quotes", lambda *a, **k: probe)
    result = CliRunner().invoke(
        etf_research.app,
        [
            "execution-coverage-run",
            "--capture-dir",
            str(root),
            "--manifest-hash",
            "a" * 64,
            "--quote-capture-dir",
            str(root),
            "--quote-manifest-hash",
            "b" * 64,
            "--calendar-file",
            str(calendar_file),
            "--calendar-hash",
            hashlib.sha256(body).hexdigest(),
            "--report-dir",
            str(reports),
        ],
    )
    assert result.exit_code == 2, result.output
    row = json.loads(result.output)
    assert row["status"] == "BLOCKED_INPUTS"
    assert row["development_sessions_after750"] == 1
    assert row["fully_requested_session_count"] == 0
    assert row["quoted_session_count"] == 1
    assert not row["execution_enabled"] and not row["evidence_promotable"]
    saved = json.loads((reports / (row["report_hash"] + ".etf-report.json")).read_bytes())
    assert saved["missing_requested_sessions"] == ["2019-03-08"]
    assert saved["holdout_evaluated"] is False and saved["total_quote_observations"] == 1
    assert "bars" not in saved and "quotes" not in saved


def test_mismatched_capture_pairs_deny_before_loading_or_writing(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    result = CliRunner().invoke(
        etf_research.app,
        [
            "execution-coverage-run",
            "--capture-dir",
            str(root),
            "--manifest-hash",
            "a" * 64,
            "--quote-capture-dir",
            str(root),
            "--quote-capture-dir",
            str(root),
            "--quote-manifest-hash",
            "b" * 64,
            "--calendar-file",
            str(root / "absent.json"),
            "--calendar-hash",
            "c" * 64,
            "--report-dir",
            str(root),
        ],
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "denied"
    assert list(root.iterdir()) == []
