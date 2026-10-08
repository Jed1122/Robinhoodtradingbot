"""Development command is private, preregistered and unable to enable execution."""

import importlib
import json
import os
import stat
from dataclasses import replace
from pathlib import Path

from typer.testing import CliRunner

ROOT = Path(__file__).parents[3]


def args(private):
    return [
        "daily-screen-run",
        "--capture-dir",
        str(private),
        "--manifest-hash",
        "a" * 64,
        "--reference-dir",
        str(private),
        "--calendar-hash",
        "b" * 64,
        "--issuer-hash",
        "c" * 64,
        "--report-dir",
        str(private),
        "--config-dir",
        str(ROOT / "configs"),
    ]


def test_daily_command_bad_inputs_fail_sanitized_without_output(tmp_path):
    module = importlib.import_module("trading_bot.cli.etf_research")
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    result = CliRunner().invoke(module.app, args(private))
    assert result.exit_code == 1, result.stdout
    assert json.loads(result.stdout)["reason"] == "etf_research_input_invalid"
    assert list(private.iterdir()) == []


def test_daily_command_has_no_holdout_live_cost_or_risk_override():
    module = importlib.import_module("trading_bot.cli.etf_research")
    result = CliRunner().invoke(module.app, ["daily-screen-run", "--help"])
    assert result.exit_code == 0
    for option in ("--live", "--holdout", "--capital", "--cost-bps", "--qualified", "--risk"):
        assert option not in result.stdout


def fixtures(monkeypatch, module):
    from tests.unit.research.test_etf_benchmark_screen import inputs
    from tests.unit.research.test_etf_daily_economics import gap_request

    intake = importlib.import_module("trading_bot.research.etf_daily_intake")
    package = inputs()
    monkeypatch.setattr(module, "read_etf_native_bars", lambda *a, **kw: package.archive)
    monkeypatch.setattr(
        module, "_read_reference_inputs", lambda *a: (package.calendar, package.issuer)
    )

    def projected(study, *a):
        req = gap_request()
        return replace(req, protocol=replace(req.protocol, study=study))

    monkeypatch.setattr(intake, "make_etf_daily_request", projected)


def test_daily_preregistration_precedes_results_and_keeps_verified_output_inode(
    tmp_path, monkeypatch
):
    module = importlib.import_module("trading_bot.cli.etf_research")
    economics = importlib.import_module("trading_bot.research.etf_daily_economics")
    fixtures(monkeypatch, module)
    private, moved, foreign = tmp_path / "private", tmp_path / "moved", tmp_path / "foreign"
    private.mkdir(mode=0o700)
    foreign.mkdir(mode=0o700)
    (foreign / "unrelated.json").write_bytes(b"unrelated")
    publish = module._publish
    calls = []

    def switched(descriptor, name, body):
        value = json.loads(body)
        calls.append(value["schema"])
        if len(calls) == 1:
            assert value["screening_verdict"] == "NOT_EVALUATED"
            assert value["economic_admitted"] is False
            assert value["study"]["cost_plan_hash"] == economics.etf_daily_cost_plan_hash()
        publish(descriptor, name, body)
        if len(calls) == 1:
            private.rename(moved)
            foreign.rename(private)

    monkeypatch.setattr(module, "_publish", switched)
    result = CliRunner().invoke(module.app, args(private))
    assert result.exit_code == 0, result.stdout
    assert calls == ["etf-daily-screen-preregistration-v1", "etf-daily-screen-report-v1"]
    assert {path.name for path in private.iterdir()} == {"unrelated.json"}
    paths = list(moved.iterdir())
    assert len(paths) == 2
    for path in paths:
        info = path.stat()
        assert stat.S_IMODE(info.st_mode) == 0o600 and info.st_uid == os.getuid()
    summary = json.loads(result.stdout)
    assert summary["holdout_evaluated"] is False and summary["economic_admitted"] is False
    assert summary["cost_qualified"] is False and summary["execution_enabled"] is False
    assert summary["screening_verdict_counts"] == {"REJECT": 24}
    assert "101.060505" not in result.stdout  # Assumed prices stay in the private report.


def test_daily_failure_after_preregistration_cannot_publish_results(tmp_path, monkeypatch):
    module = importlib.import_module("trading_bot.cli.etf_research")
    economics = importlib.import_module("trading_bot.research.etf_daily_economics")
    fixtures(monkeypatch, module)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)

    def failed(*a):
        raise ValueError("sensitive input must not escape")

    monkeypatch.setattr(economics, "run_etf_daily_economics", failed)
    result = CliRunner().invoke(module.app, args(private))
    assert result.exit_code == 1
    assert "sensitive input" not in result.stdout
    assert json.loads(result.stdout)["reason"] == "etf_research_input_invalid"
    rows = [json.loads(path.read_bytes()) for path in private.iterdir()]
    assert len(rows) == 1 and rows[0]["schema"] == "etf-daily-screen-preregistration-v1"
