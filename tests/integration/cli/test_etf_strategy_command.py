"""Operator demonstration is simulated accounting, never readiness evidence."""

import json

import pytest
from typer.testing import CliRunner

from trading_bot.cli.etf_research import app


@pytest.mark.parametrize("capital", ["500", "1000"])
def test_strategy_command_demonstrates_completed_stop_cash_flow(capital):
    result = CliRunner().invoke(app, ["strategy-fixture-run", "--capital", capital])
    assert result.exit_code == 0, result.output
    row = json.loads(result.output)
    assert row["source_kind"] == "synthetic-strategy-quotes-v1"
    assert row["complete"] and row["shares"] == "0"
    assert row["cash"] == str(int(capital) - 1) + ".63553015"
    assert row["consumed_trial_loss"] == "0.36446985"
    assert row["economic_verdict"] == "ECONOMIC_NO_GO"
    assert not row["evidence_promotable"] and not row["execution_enabled"]
    assert not row["live_authorized"]


def test_strategy_command_resume_preserves_incomplete_partial_reserves():
    runner = CliRunner()
    base = runner.invoke(app, ["strategy-fixture-run", "--scenario", "partial_cancel"])
    resumed = runner.invoke(
        app, ["strategy-fixture-run", "--scenario", "partial_cancel", "--restart-after", "751"]
    )
    assert base.exit_code == resumed.exit_code == 2
    assert json.loads(base.output) == json.loads(resumed.output)
    row = json.loads(base.output)
    assert not row["complete"] and row["shares"] == "0.04"
    assert row["reserved_cash"] == "11.0696"
    assert row["reserved_trial_risk"] == "15.1"
    assert row["trading_pnl"] is None


@pytest.mark.parametrize(
    "args", [["--scenario", "live"], ["--capital", "1001"], ["--restart-after", "-1"]]
)
def test_strategy_command_rejects_unknown_or_unauthorized_inputs(args):
    result = CliRunner().invoke(app, ["strategy-fixture-run", *args])
    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "denied"
