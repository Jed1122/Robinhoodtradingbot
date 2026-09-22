"""The options research CLI neither imports broker adapters nor opens sockets."""

import ast
import json
import socket
from pathlib import Path

import pytest
from typer.testing import CliRunner

from trading_bot.cli.options_research import app


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("network forbidden in offline options tests")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


def test_capital_feasibility_reports_zero_at_100_and_separate_live_no_go() -> None:
    result = CliRunner().invoke(app, ["capital-feasibility"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["tiers"][0]["capital"] == "100"
    assert report["tiers"][0]["admissible_units"] == 0
    assert report["tiers"][0]["per_trade_budget"] == "0.5"
    assert len(report["tiers"]) == 8
    assert not report["live_authorized"]
    assert report["economic_verdict"] == "ECONOMIC_NO_GO"


def test_options_replay_reports_reconciled_demo_without_broker_access() -> None:
    result = CliRunner().invoke(app, ["options-replay", "--research-capital", "2500"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["cash"] == "2504"
    assert report["status"] == "completed_synthetic_replay"
    assert not report["production_eligible"]
    assert not report["evidence_promotable"]


@pytest.mark.parametrize("kind", ["call", "put"])
def test_directional_fixture_cli_supports_both_purchased_option_kinds(kind: str) -> None:
    result = CliRunner().invoke(
        app, ["options-replay", "--research-capital", "2500", "--option-kind", kind]
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["cash"] == "2504"
    assert report["position_units"] == 0
    assert not report["production_eligible"]


def test_invalid_kind_is_sanitized_without_loading_a_broker() -> None:
    result = CliRunner().invoke(app, ["options-replay", "--option-kind", "private-invalid-value"])
    assert result.exit_code == 1
    assert json.loads(result.output)["reason"] == "options_research_input_invalid"
    assert "private-invalid-value" not in result.output


def test_cli_marks_incomplete_and_rejects_invalid_values_without_echoing_inputs() -> None:
    result = CliRunner().invoke(
        app, ["options-replay", "--research-capital", "2500", "--scenario", "unknown"]
    )
    assert result.exit_code == 2
    assert json.loads(result.output)["status"] == "incomplete_synthetic_replay"
    for args in (
        ["capital-feasibility", "--premium", "NaN"],
        ["options-replay", "--scenario", "secret-like-invalid"],
    ):
        failed = CliRunner().invoke(app, args)
        assert failed.exit_code == 1
        assert json.loads(failed.output)["reason"] == "options_research_input_invalid"
        assert "secret-like-invalid" not in failed.output


def test_offline_options_modules_cannot_import_broker_or_persistence_capabilities() -> None:
    root = Path(__file__).parents[3] / "src/trading_bot"
    files = [
        root / "cli/options_research.py",
        *sorted((root / "simulation").glob("options_*.py")),
        *sorted((root / "strategies/options").rglob("*.py")),
        *sorted((root / "research").glob("options_shortlist*.py")),
    ]
    for path in files:
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            assert not any(
                name.startswith(
                    ("trading_bot.brokers", "trading_bot.persistence", "httpx", "mcp", "subprocess")
                )
                for name in names
            )
