from importlib import import_module
from typing import Any

import pytest
from rich.text import Text
from typer import rich_utils
from typer.testing import CliRunner

main = import_module("trading_bot.cli.main")


def test_serve_starts_only_as_paused_shadow(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    observed: dict[str, Any] = {}

    def fake_run(application: object, **kwargs: object) -> None:
        observed["application"] = application
        observed.update(kwargs)

    monkeypatch.setattr(main.uvicorn, "run", fake_run)
    result = CliRunner().invoke(
        main.app,
        [
            "serve",
            "--mode",
            "shadow",
            "--config",
            "configs/shadow.yaml",
            "--paused",
        ],
        env={
            "LIVE_TRADING_ENABLED": "false",
            "PREDICTION_LIVE_ENABLED": "false",
            "TRADING_BOT__MONITORING__HOST": "0.0.0.0",
            "TRADING_BOT__MONITORING__CONTAINER_LOOPBACK_PUBLISH": "true",
        },
    )

    assert result.exit_code == 0, result.output
    assert observed["host"] == "0.0.0.0"
    assert observed["port"] == 8080
    assert observed["access_log"] is False


@pytest.mark.parametrize("use_color", [False, True], ids=["plain", "color"])
def test_serve_requires_explicit_paused_flag(
    monkeypatch: pytest.MonkeyPatch, use_color: bool
) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(rich_utils, "FORCE_TERMINAL", use_color)
    monkeypatch.setattr(rich_utils, "COLOR_SYSTEM", "standard" if use_color else None)
    server_starts: list[object] = []

    def record_server_start(application: object, **kwargs: object) -> None:
        server_starts.append((application, kwargs))

    monkeypatch.setattr(main.uvicorn, "run", record_server_start)
    result = CliRunner().invoke(
        main.app,
        ["serve", "--mode", "shadow", "--config", "configs/shadow.yaml"],
    )
    assert result.exit_code == 2
    assert ("\x1b[" in result.output) is use_color
    # Rich may insert ANSI boundaries within an option name on CI terminals.
    assert "paused service requires --paused" in Text.from_ansi(result.output).plain
    assert server_starts == []


def test_config_hash_uses_resolved_shadow_configuration() -> None:
    result = CliRunner().invoke(
        main.app,
        ["config-hash", "--config", "configs/shadow.yaml"],
    )
    assert result.exit_code == 0
    assert len(result.stdout.strip()) == 64
