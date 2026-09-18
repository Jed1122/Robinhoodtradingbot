"""Saved synthetic replay uses real codecs/storage and cannot gain trading authority."""

import json
import socket
from pathlib import Path

import pytest
from typer.testing import CliRunner

from trading_bot.cli.options_research import app


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("offline replay opened a network connection")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


def export(tmp_path: Path, scenario: str = "completed", capital: str = "2500") -> Path:
    tmp_path.chmod(0o700)
    result = CliRunner().invoke(
        app,
        [
            "export-options-fixture",
            "--output-dir",
            str(tmp_path),
            "--scenario",
            scenario,
            "--research-capital",
            capital,
        ],
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["source_kind"] == "synthetic-options-v1"
    assert report["production_eligible"] is False
    return tmp_path / "inputs" / (report["document_hash"] + ".json")


@pytest.mark.parametrize(
    ("scenario", "capital", "status", "cash", "exit_code"),
    [
        ("completed", "2500", "completed_synthetic_replay", "2504", 0),
        ("loss", "2500", "completed_synthetic_replay", "2494", 0),
        ("unknown", "2500", "incomplete_synthetic_replay", "2500", 2),
        ("completed", "100", "capital_denied", "100", 0),
    ],
)
def test_saved_inputs_replay_exact_cash_and_publish_truthful_report(
    tmp_path: Path,
    scenario: str,
    capital: str,
    status: str,
    cash: str,
    exit_code: int,
) -> None:
    path = export(tmp_path, scenario, capital)
    assert path.stat().st_mode & 0o777 == 0o600
    run = CliRunner().invoke(app, ["replay-file", str(path), "--report-dir", str(tmp_path)])
    assert run.exit_code == exit_code, run.output
    output = json.loads(run.output)
    assert output["result"]["status"] == status
    assert output["result"]["cash"] == cash
    assert output["result"]["economic_verdict"] == "ECONOMIC_NO_GO"
    assert output["result"]["production_eligible"] is False
    assert output["result"]["evidence_promotable"] is False
    report = tmp_path / "reports" / (output["report_hash"] + ".json")
    assert report.stat().st_mode & 0o777 == 0o600
    first = report.read_bytes()
    again = CliRunner().invoke(app, ["replay-file", str(path), "--report-dir", str(tmp_path)])
    assert again.exit_code == exit_code
    assert again.output == run.output
    assert report.read_bytes() == first


def test_saved_input_tamper_is_rejected_without_echoing_fields(tmp_path: Path) -> None:
    path = export(tmp_path)
    payload = json.loads(path.read_text())
    payload["payload"]["close_limit"] = "secret-like-invalid"
    path.write_text(json.dumps(payload))
    run = CliRunner().invoke(app, ["replay-file", str(path)])
    assert run.exit_code == 1
    assert json.loads(run.output)["reason"] == "options_research_input_invalid"
    assert "secret-like-invalid" not in run.output


def test_existing_report_is_not_overwritten_even_when_corrupted(tmp_path: Path) -> None:
    path = export(tmp_path)
    args = ["replay-file", str(path), "--report-dir", str(tmp_path)]
    run = CliRunner().invoke(app, args)
    assert run.exit_code == 0, run.output
    report = tmp_path / "reports" / (json.loads(run.output)["report_hash"] + ".json")
    report.write_text("preserve-existing-bytes")
    failed = CliRunner().invoke(app, args)
    assert failed.exit_code == 1
    assert report.read_text() == "preserve-existing-bytes"
