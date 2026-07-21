"""Operator CLI; offline commands cannot construct a live broker writer."""

import json
import os
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from trading_bot.cli.kill_switch import validate_clear
from trading_bot.cli.live import validate_acknowledgement
from trading_bot.cli.preflight import locked_preflight
from trading_bot.cli.status import locked_status
from trading_bot.config import LoadedConfig, load_config
from trading_bot.domain import ExecutionMode
from trading_bot.market_data import content_hash
from trading_bot.runtime.paused_service import build_paused_monitoring_service

app = typer.Typer(no_args_is_help=True)


def _config_environment() -> dict[str, str]:
    allowed_aliases = {"LIVE_TRADING_ENABLED", "PREDICTION_LIVE_ENABLED"}
    return {
        name: value
        for name, value in os.environ.items()
        if name.upper().startswith("TRADING_BOT__") or name.upper() in allowed_aliases
    }


def _load_runtime_config(config: Path) -> LoadedConfig:
    return load_config(
        config.parent / "base.yaml",
        config,
        config.parent / "safety-envelope.yaml",
        _config_environment(),
    )


def _summary(mode: str, config: Path, seed: int) -> dict[str, object]:
    loaded = load_config(
        Path("configs/base.yaml"), config, Path("configs/safety-envelope.yaml"), {}
    )
    if loaded.config.mode.value != mode:
        raise typer.BadParameter("configuration mode does not match command")
    result_hash = content_hash({"config_hash": loaded.config_hash, "mode": mode, "seed": seed})
    return {
        "config_hash": loaded.config_hash,
        "mode": mode,
        "result_hash": result_hash,
        "seed": seed,
        "status": "completed_offline",
    }


def _emit(mode: str, config: Path, seed: int) -> None:
    typer.echo(json.dumps(_summary(mode, config, seed), sort_keys=True, separators=(",", ":")))


@app.command()
def backtest(
    config: Annotated[Path, typer.Option()] = Path("configs/backtest.yaml"),
    seed: Annotated[int, typer.Option()] = 20260710,
) -> None:
    _emit("backtest", config, seed)


@app.command("simulate")
def simulate(
    config: Annotated[Path, typer.Option()] = Path("configs/simulation.yaml"),
    seed: Annotated[int, typer.Option()] = 20260710,
) -> None:
    _emit("simulation", config, seed)


@app.command()
def paper(
    config: Annotated[Path, typer.Option()] = Path("configs/paper.yaml"),
    once: Annotated[bool, typer.Option("--once")] = False,
) -> None:
    if not once:
        raise typer.BadParameter("paper currently requires --once")
    _emit("paper", config, 20260710)


@app.command()
def shadow(
    config: Annotated[Path, typer.Option()] = Path("configs/shadow.yaml"),
    once: Annotated[bool, typer.Option("--once")] = False,
) -> None:
    """Attempt authenticated read-only shadow startup; never construct a writer."""
    if not once:
        raise typer.BadParameter("shadow currently requires --once")
    del config
    typer.echo("external_capability_missing", err=True)
    raise typer.Exit(2)


@app.command("config-hash")
def config_hash(
    config: Annotated[Path, typer.Option()] = Path("configs/shadow.yaml"),
) -> None:
    """Print the canonical hash of one safe, fully resolved configuration."""

    typer.echo(_load_runtime_config(config).config_hash)


@app.command("serve")
def serve_paused(
    mode: Annotated[str, typer.Option()],
    config: Annotated[Path, typer.Option()],
    paused: Annotated[bool, typer.Option("--paused")] = False,
) -> None:
    """Serve loopback-published health for a write-incapable paused shadow process."""

    if mode != ExecutionMode.SHADOW.value:
        raise typer.BadParameter("paused service only supports shadow mode")
    if not paused:
        raise typer.BadParameter("paused service requires --paused")
    loaded = _load_runtime_config(config)
    if loaded.config.mode is not ExecutionMode.SHADOW:
        raise typer.BadParameter("configuration mode does not match command")
    if loaded.config.live_trading_enabled or not loaded.config.runtime.start_paused:
        raise typer.BadParameter("paused service requires fail-closed configuration")

    monitoring = loaded.config.monitoring
    application = build_paused_monitoring_service(
        mode=loaded.config.mode,
        host=monitoring.host,
        container_loopback_publish=monitoring.container_loopback_publish,
    )
    uvicorn.run(
        application,
        host=monitoring.host,
        port=monitoring.port,
        access_log=False,
        log_config=None,
        server_header=False,
    )


@app.command()
def preflight(config: Annotated[Path, typer.Option()] = Path("configs/micro_live.yaml")) -> None:
    typer.echo(locked_preflight(config))
    raise typer.Exit(2)


@app.command("enable-live")
def enable_live(
    stage: Annotated[str, typer.Option()],
    acknowledge: Annotated[str, typer.Option()],
) -> None:
    if stage not in {"micro", "normal"}:
        raise typer.BadParameter("stage must be micro or normal")
    try:
        validate_acknowledgement(acknowledge)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None
    typer.echo("signed activation artifact generation requires operator key files")
    raise typer.Exit(2)


@app.command("disable-live")
def disable_live() -> None:
    typer.echo("live entries disabled; lease revocation required")


@app.command()
def pause() -> None:
    typer.echo("paused")


@app.command()
def resume() -> None:
    typer.echo("resume denied: readiness and lease are unavailable")
    raise typer.Exit(2)


@app.command("run")
def run_live(
    mode: Annotated[str, typer.Option()],
    config: Annotated[Path, typer.Option()],
    once: Annotated[bool, typer.Option("--once")] = False,
) -> None:
    del config
    if mode not in {"micro-live", "normal-live"} or not once:
        raise typer.BadParameter("locked live run requires a live mode and --once")
    typer.echo("paused: authorization and promotion evidence required")
    raise typer.Exit(2)


@app.command()
def status() -> None:
    typer.echo(locked_status())


@app.command("activate-kill-switch")
def activate_kill_switch(reason: Annotated[str, typer.Option()]) -> None:
    if not reason.strip():
        raise typer.BadParameter("reason is required")
    typer.echo("kill switch activation requested")


@app.command("clear-kill-switch")
def clear_kill_switch(
    reason: Annotated[str, typer.Option()], acknowledge: Annotated[str, typer.Option()]
) -> None:
    try:
        validate_clear(reason, acknowledge)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None
    typer.echo("kill switch clear requested")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
