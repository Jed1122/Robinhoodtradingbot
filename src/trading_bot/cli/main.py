"""Operator CLI; offline commands cannot construct a live broker writer."""

import json
import os
import re
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from trading_bot.cli.kill_switch import validate_clear
from trading_bot.cli.live import validate_acknowledgement
from trading_bot.cli.preflight import locked_preflight
from trading_bot.cli.promotion_status import (
    PromotionStatusUnavailable,
    read_promotion_status,
)
from trading_bot.cli.status import locked_status
from trading_bot.config import LoadedConfig, load_config
from trading_bot.domain import ExecutionMode
from trading_bot.market_data import content_hash
from trading_bot.runtime.capability_capture import (
    AuthenticatedCapabilityCaptureError,
    run_authenticated_schema_capture,
)
from trading_bot.runtime.connected_research import (
    ConnectedResearchNotReady,
    run_connected_equity_research_once,
)
from trading_bot.runtime.connected_shadow import (
    ConnectedShadowNotReady,
    bootstrap_read_only_oauth,
    run_connected_shadow_once,
)
from trading_bot.runtime.paper_promotion_runtime import (
    PaperPromotionNotReady,
    run_paper_promotion_once,
)
from trading_bot.runtime.paused_service import build_paused_monitoring_service

app = typer.Typer(no_args_is_help=True)
_PROBE_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,14}\Z")


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
        "status": "configuration_only",
        "executed": False,
    }


def _emit(mode: str, config: Path, seed: int) -> None:
    typer.echo(json.dumps(_summary(mode, config, seed), sort_keys=True, separators=(",", ":")))


@app.command()
def backtest(
    config: Annotated[Path, typer.Option()] = Path("configs/backtest.yaml"),
    seed: Annotated[int, typer.Option()] = 20260710,
) -> None:
    """Validate offline configuration; no strategy backtest is executed yet."""
    _emit("backtest", config, seed)


@app.command("simulate")
def simulate(
    config: Annotated[Path, typer.Option()] = Path("configs/simulation.yaml"),
    seed: Annotated[int, typer.Option()] = 20260710,
) -> None:
    """Validate offline configuration; no strategy simulation is executed yet."""
    _emit("simulation", config, seed)


@app.command()
def paper(
    config: Annotated[Path, typer.Option()] = Path("configs/paper.yaml"),
    once: Annotated[bool, typer.Option("--once")] = False,
    ledger: Annotated[Path, typer.Option()] = Path("/var/lib/trading-bot/evidence/ledger.db"),
    lock_directory: Annotated[Path, typer.Option()] = Path("/var/lib/trading-bot/paper-locks"),
) -> None:
    if not once:
        raise typer.BadParameter("paper currently requires --once")
    try:
        output = run_paper_promotion_once(
            loaded=_load_runtime_config(config),
            repository_root=config.resolve().parent.parent,
            ledger=ledger,
            lock_directory=lock_directory,
        )
    except PaperPromotionNotReady as exc:
        typer.echo("paper_promotion_not_ready")
        typer.echo(",".join(exc.blockers), err=True)
        raise typer.Exit(2) from None
    typer.echo(json.dumps(output, sort_keys=True, separators=(",", ":")))


@app.command()
def shadow(
    config: Annotated[Path, typer.Option()] = Path("configs/shadow.yaml"),
    once: Annotated[bool, typer.Option("--once")] = False,
    oauth_store: Annotated[Path, typer.Option()] = Path("/var/lib/trading-bot/oauth"),
    account_fingerprint_file: Annotated[Path, typer.Option()] = Path(
        "/var/lib/trading-bot/oauth/account-fingerprint"
    ),
    ledger: Annotated[Path, typer.Option()] = Path("/var/lib/trading-bot/evidence/ledger.db"),
    image_digest: Annotated[str | None, typer.Option(envvar="TRADING_BOT_IMAGE_DIGEST")] = None,
    image_attestation: Annotated[Path, typer.Option()] = Path(
        "/run/trading-bot/runtime-image-attestation.json"
    ),
    probe_symbol: Annotated[str | None, typer.Option()] = None,
    strategy_version: Annotated[str | None, typer.Option()] = None,
    research_evidence_hash: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Run one authenticated, write-incapable connected-shadow evidence probe."""
    if not once:
        raise typer.BadParameter("shadow currently requires --once")
    loaded = _load_runtime_config(config)
    if loaded.config.mode is not ExecutionMode.SHADOW:
        raise typer.BadParameter("configuration mode does not match command")
    if loaded.config.live_trading_enabled or not loaded.config.runtime.start_paused:
        raise typer.BadParameter("connected shadow requires fail-closed configuration")
    if not loaded.config.equities.enabled or loaded.config.crypto.enabled:
        raise typer.BadParameter("connected Agentic shadow requires an equity-only profile")
    if image_digest is None:
        raise typer.BadParameter("connected shadow requires TRADING_BOT_IMAGE_DIGEST")
    if probe_symbol is not None and _PROBE_SYMBOL.fullmatch(probe_symbol) is None:
        raise typer.BadParameter("probe symbol must be an exact uppercase ticker")
    if (strategy_version is None) != (research_evidence_hash is None):
        raise typer.BadParameter(
            "strategy version and research evidence hash must be supplied together"
        )

    try:
        output = run_connected_shadow_once(
            loaded=loaded,
            repository_root=config.resolve().parent.parent,
            oauth_store=oauth_store,
            account_fingerprint_file=account_fingerprint_file,
            ledger=ledger,
            image_digest=image_digest,
            image_attestation=image_attestation,
            probe_symbol=probe_symbol,
            strategy_version=strategy_version,
            research_evidence_hash=research_evidence_hash,
        )
    except ConnectedShadowNotReady:
        typer.echo("connected_shadow_not_ready", err=True)
        raise typer.Exit(2) from None
    typer.echo(json.dumps(output, sort_keys=True, separators=(",", ":")))


@app.command("mcp-oauth-bootstrap")
def mcp_oauth_bootstrap(
    oauth_store: Annotated[Path, typer.Option()],
    account_fingerprint_file: Annotated[Path, typer.Option()],
) -> None:
    """Authorize the MCP credential used only by the write-incapable client."""

    try:
        output = bootstrap_read_only_oauth(
            oauth_store=oauth_store,
            account_fingerprint_file=account_fingerprint_file,
        )
    except ConnectedShadowNotReady:
        typer.echo("oauth_bootstrap_failed", err=True)
        raise typer.Exit(2) from None
    typer.echo(json.dumps(output, sort_keys=True, separators=(",", ":")))


@app.command("capture-mcp-capabilities")
def capture_mcp_capabilities(
    oauth_store: Annotated[Path, typer.Option()],
    output: Annotated[Path, typer.Option()],
) -> None:
    """Capture sanitized authenticated tools/list declarations without invoking tools."""

    try:
        summary = run_authenticated_schema_capture(
            oauth_store=oauth_store,
            output=output,
        )
    except AuthenticatedCapabilityCaptureError:
        typer.echo("authenticated_capability_capture_failed", err=True)
        raise typer.Exit(2) from None
    typer.echo(json.dumps(summary, sort_keys=True, separators=(",", ":")))


@app.command("research-equities")
def research_equities(
    config: Annotated[Path, typer.Option()] = Path("configs/shadow.yaml"),
    once: Annotated[bool, typer.Option("--once")] = False,
    oauth_store: Annotated[Path, typer.Option()] = Path("/var/lib/trading-bot/oauth"),
    account_fingerprint_file: Annotated[Path, typer.Option()] = Path(
        "/var/lib/trading-bot/oauth/account-fingerprint"
    ),
    ledger: Annotated[Path, typer.Option()] = Path(
        "/var/lib/trading-bot/evidence/ledger.db"
    ),
    artifact_dir: Annotated[Path, typer.Option()] = Path(
        "/var/lib/trading-bot/evidence/research"
    ),
    image_digest: Annotated[
        str | None, typer.Option(envvar="TRADING_BOT_IMAGE_DIGEST")
    ] = None,
    image_attestation: Annotated[Path, typer.Option()] = Path(
        "/run/trading-bot/runtime-image-attestation.json"
    ),
) -> None:
    """Record one authenticated, write-incapable ETF candidate comparison."""

    if not once:
        raise typer.BadParameter("connected equity research currently requires --once")
    if image_digest is None:
        raise typer.BadParameter("connected equity research requires TRADING_BOT_IMAGE_DIGEST")
    loaded = _load_runtime_config(config)
    try:
        output = run_connected_equity_research_once(
            loaded=loaded,
            repository_root=config.resolve().parent.parent,
            oauth_store=oauth_store,
            account_fingerprint_file=account_fingerprint_file,
            ledger=ledger,
            artifact_dir=artifact_dir,
            image_digest=image_digest,
            image_attestation=image_attestation,
        )
    except ConnectedResearchNotReady:
        typer.echo("connected_research_not_ready", err=True)
        raise typer.Exit(2) from None
    typer.echo(json.dumps(output, sort_keys=True, separators=(",", ":")))


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


@app.command("promotion-status")
def promotion_status(
    config: Annotated[Path, typer.Option()] = Path("configs/micro_live.yaml"),
    ledger: Annotated[Path, typer.Option()] = Path("/var/lib/trading-bot/evidence/ledger.db"),
) -> None:
    """Preview identity-bound promotion progress without mutating evidence."""

    try:
        output = read_promotion_status(
            loaded=_load_runtime_config(config),
            ledger=ledger,
        )
    except PromotionStatusUnavailable:
        typer.echo("promotion_status_unavailable", err=True)
        raise typer.Exit(2) from None
    typer.echo(json.dumps(output, sort_keys=True, separators=(",", ":")))


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
