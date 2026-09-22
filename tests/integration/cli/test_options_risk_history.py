"""Operator rehearsal stays synthetic, credential-free, paused and deterministic."""

import importlib
import json
import socket
from datetime import timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.unit.risk.test_options_loss_history import OPEN, point
from trading_bot.persistence.options_risk import encode_point

runner = CliRunner()
CONFIGS = Path(__file__).parents[3] / "configs"


def app():
    try:
        return importlib.import_module("trading_bot.cli.options_risk_history").app
    except ModuleNotFoundError:
        pytest.fail("offline risk-history operator command not implemented")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("offline operator cannot access network")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


def test_demo_reconstructs_real_sqlite_history_and_is_not_live_evidence():
    first = runner.invoke(app(), ["demo", "--config-dir", str(CONFIGS)])
    assert first.exit_code == 0, first.output
    report = json.loads(first.stdout)
    assert report["status"] == "paused_synthetic_rehearsal"
    assert report["restart_verified"] is True
    assert report["losses"]["flow_adjusted_equity"] == "89"
    assert report["losses"]["weekly_halt"] is True
    assert report["entry_enabled"] is False
    assert report["production_eligible"] is False
    assert report["economic_verdict"] == "ECONOMIC_NO_GO"
    assert "synthetic:risk" not in first.stdout
    second = runner.invoke(
        app(),
        ["demo", "--config-dir", str(CONFIGS)],
        env={"LIVE_TRADING_ENABLED": "true", "BROKER_SECRET": "must-not-appear"},
    )
    assert second.exit_code == 0 and second.stdout == first.stdout


def fixture(tmp_path, observations=None, **changes):
    tmp_path = tmp_path.resolve()
    tmp_path.chmod(0o700)
    document = {
        "schema": "options-risk-rehearsal-v1",
        "source_kind": "synthetic",
        "as_of": OPEN.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "points": [json.loads(encode_point(p)) for p in (observations or (point(),))],
    } | changes
    path = tmp_path / "risk.json"
    path.write_text(json.dumps(document))
    path.chmod(0o600)
    return path


def test_replay_file_is_bounded_and_stale_data_is_reported_as_blocked(tmp_path):
    path = fixture(tmp_path, as_of=(OPEN + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
    result = runner.invoke(app(), ["replay-file", str(path), "--config-dir", str(CONFIGS)])
    assert result.exit_code == 2, result.output
    report = json.loads(result.stdout)
    assert report["restart_verified"]
    assert "risk_observation_stale" in report["losses"]["entry_reasons"]


@pytest.mark.parametrize(
    "changes",
    [
        {"source_kind": "historical"},
        {"schema": "other"},
        {"unknown": "secret-marker"},
        {"points": []},
        {"points": [1]},
        {"as_of": "naive"},
    ],
)
def test_invalid_inputs_never_echo_sensitive_content(tmp_path, changes):
    path = fixture(tmp_path, **changes)
    result = runner.invoke(app(), ["replay-file", str(path), "--config-dir", str(CONFIGS)])
    assert result.exit_code == 1
    assert json.loads(result.stdout) == {"status": "denied", "reason": "risk_history_input_invalid"}
    assert "secret-marker" not in result.output


def test_symlink_and_world_readable_source_rejected(tmp_path):
    path = fixture(tmp_path)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    for candidate in (link, path):
        if candidate == path:
            path.chmod(0o644)
        result = runner.invoke(app(), ["replay-file", str(candidate), "--config-dir", str(CONFIGS)])
        assert result.exit_code == 1


def test_incomplete_history_remains_blocked_after_journal_restart(tmp_path):
    at = OPEN + timedelta(seconds=1)
    path = fixture(
        tmp_path,
        (point(), point("incomplete", at=at, complete=False)),
        as_of=at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    )
    result = runner.invoke(app(), ["replay-file", str(path), "--config-dir", str(CONFIGS)])
    assert result.exit_code == 2
    report = json.loads(result.stdout)
    assert report["restart_verified"] and not report["entry_enabled"]
    assert "risk_history_incomplete" in report["losses"]["entry_reasons"]


def test_malformed_internal_report_is_denied_before_printing(monkeypatch):
    module = importlib.import_module("trading_bot.cli.options_risk_history")
    monkeypatch.setattr(module, "_rehearse", lambda *args: {"losses": [], "secret": "hidden"})
    result = runner.invoke(app(), ["demo", "--config-dir", str(CONFIGS)])
    assert result.exit_code == 1
    assert json.loads(result.stdout) == {"status": "denied", "reason": "risk_history_input_invalid"}
    assert "hidden" not in result.output


def test_database_failure_is_redacted_by_persistence_boundary(monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    from trading_bot.persistence import options_risk_rehearsal as module

    def fail(*args):
        raise SQLAlchemyError("sensitive-storage-detail")

    monkeypatch.setattr(module.command, "upgrade", fail)
    result = runner.invoke(app(), ["demo", "--config-dir", str(CONFIGS)])
    assert result.exit_code == 1
    assert "sensitive-storage-detail" not in result.output
    assert json.loads(result.stdout)["status"] == "denied"
