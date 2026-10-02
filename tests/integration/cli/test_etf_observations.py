"""Standalone private observations CLI; all inputs are manufactured."""

import hashlib
import json

from typer.testing import CliRunner

from trading_bot.cli import etf_observations


def test_calibration_missing_orders_writes_blocked_private_report(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir(mode=0o700)
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o700)
    input_file = inputs / "observations.json"
    input_file.write_text(
        json.dumps(
            {
                "schema": "etf-cost-observations-v1",
                "provenance": "synthetic",
                "execution_broker": "robinhood",
                "market_data_source": "alpaca-sip",
                "orders": [],
            }
        )
    )
    input_file.chmod(0o600)
    result = CliRunner().invoke(
        etf_observations.app,
        [
            "calibrate-costs",
            "--input-file",
            str(input_file),
            "--input-root",
            str(inputs),
            "--report-dir",
            str(reports),
        ],
    )
    assert result.exit_code == 2, result.output
    response = json.loads(result.output)
    assert response["status"] == "BLOCKED_INPUTS"
    assert response["evidence_promotable"] is False
    path = reports / (response["report_hash"] + ".observation-report.json")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == response["report_hash"]
    report = json.loads(path.read_bytes())
    assert report["charged_order_fee_usd"]["total"] is None
    assert report["execution_enabled"] is False
    assert report["economic_verdict"] == "ECONOMIC_NO_GO"
    assert path.stat().st_mode & 0o777 == 0o600
    assert str(inputs) not in result.output


def test_untrusted_input_is_sanitized_and_does_not_publish(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir(mode=0o700)
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o700)
    path = inputs / "synthetic-secret-file.json"
    path.write_text('{"token":"synthetic-secret-value"}')
    path.chmod(0o600)
    result = CliRunner().invoke(
        etf_observations.app,
        [
            "calibrate-costs",
            "--input-file",
            str(path),
            "--input-root",
            str(inputs),
            "--report-dir",
            str(reports),
        ],
    )
    assert result.exit_code == 1
    assert json.loads(result.output) == {
        "status": "denied",
        "reason": "etf_observation_input_invalid",
    }
    assert "synthetic-secret" not in result.output
    assert list(reports.iterdir()) == []


def test_audit_missing_archive_denies_without_authentication(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline audit tried opening a credential")

    monkeypatch.setattr(etf_observations, "capture_observations", forbidden)
    inputs = tmp_path / "inputs"
    inputs.mkdir(mode=0o700)
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o700)
    result = CliRunner().invoke(
        etf_observations.app,
        [
            "audit",
            "--input-root",
            str(inputs),
            "--result-hash",
            "a" * 64,
            "--report-dir",
            str(reports),
        ],
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "denied"
    assert list(reports.iterdir()) == []


def test_capture_wrong_hash_is_rejected_before_keys(tmp_path, monkeypatch):
    from trading_bot.clock import SystemClock
    from trading_bot.diagnostics.alpaca_observe import (
        encode_observation_plan,
        prepare_observation_capture,
    )

    inputs = tmp_path / "inputs"
    inputs.mkdir(mode=0o700)
    keys = tmp_path / "keys"
    keys.mkdir(mode=0o700)
    plan = prepare_observation_capture(
        etf_observations._loaded(etf_observations._REPOSITORY / "configs"),
        clock=SystemClock(),
        code_revision="a" * 40,
        credential_file=keys / "missing.json",
        output_root=inputs,
        repository_root=etf_observations._REPOSITORY,
    )
    path = inputs / "plan.json"
    path.write_bytes(encode_observation_plan(plan))
    path.chmod(0o600)
    monkeypatch.setattr(etf_observations, "_revision", lambda: "a" * 40)
    result = CliRunner().invoke(
        etf_observations.app,
        [
            "capture",
            "--manifest-file",
            str(path),
            "--approved-plan-hash",
            "b" * 64,
        ],
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "denied"
    assert not list(inputs.glob("*.attempt"))
