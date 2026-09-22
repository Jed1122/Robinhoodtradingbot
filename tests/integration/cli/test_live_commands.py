from typer.testing import CliRunner

from trading_bot.cli.main import app


def test_enable_live_requires_exact_acknowledgement() -> None:
    result = CliRunner().invoke(app, ["enable-live", "--stage", "micro", "--acknowledge", "wrong"])
    assert result.exit_code != 0
    assert "exact acknowledgement" in result.output


def test_run_live_defaults_paused() -> None:
    result = CliRunner().invoke(
        app,
        ["run", "--mode", "micro-live", "--config", "configs/micro_live.yaml", "--once"],
    )
    assert result.exit_code == 2
    assert "paused" in result.output
