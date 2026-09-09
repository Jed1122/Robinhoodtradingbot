from typer.testing import CliRunner

from trading_bot.cli.main import app

runner = CliRunner()


def test_paper_once_fails_closed_until_trusted_composition_exists() -> None:
    result = runner.invoke(app, ["paper", "--config", "configs/paper.yaml", "--once"])
    assert result.exit_code == 2
    assert result.stdout == "paper_promotion_not_ready\n"
    assert "accepted_research_evidence_unavailable" in result.stderr


def test_backtest_is_deterministic() -> None:
    args = ["backtest", "--config", "configs/backtest.yaml", "--seed", "20260710"]
    assert runner.invoke(app, args).stdout == runner.invoke(app, args).stdout


def test_simulation_command_uses_simulation_config() -> None:
    result = runner.invoke(app, ["simulate", "--config", "configs/simulation.yaml"])
    assert result.exit_code == 0
    assert '"mode":"simulation"' in result.stdout
