from typer.testing import CliRunner

from trading_bot.cli.main import app


def test_clear_requires_reason() -> None:
    result = CliRunner().invoke(
        app, ["clear-kill-switch", "--reason", "", "--acknowledge", "wrong"]
    )
    assert result.exit_code != 0 and "reason" in result.output
