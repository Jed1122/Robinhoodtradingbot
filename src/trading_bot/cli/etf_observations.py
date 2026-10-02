"""Explicit standalone observations and offline cost measurements; no daemon."""

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Annotated

import typer

from trading_bot.clock import SystemClock
from trading_bot.code_identity import resolve_code_identity
from trading_bot.config import LoadedConfig, load_config
from trading_bot.diagnostics.alpaca_observe import (
    audit_observation_capture,
    capture_observations,
    decode_observation_plan,
    encode_observation_plan,
    prepare_observation_capture,
)
from trading_bot.diagnostics.alpaca_probe_io import _publish_private_file, _read_private_file
from trading_bot.market_data.bundle_store import _open_root, _publish
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research.etf_cost_calibration import load_etf_cost_observations

app = typer.Typer(no_args_is_help=True)
_REPOSITORY = Path(__file__).resolve().parents[3]


def _revision() -> str:
    # Capture, audit, and cost reports require a committed checkout; no guessed
    # source revision or report identity for dirty source.
    identity = resolve_code_identity(_REPOSITORY, image_digest=None)
    if identity.dirty or identity.git_commit is None:
        raise ValueError("observation_source_uncommitted")
    return identity.git_commit


def _loaded(config_dir: Path) -> LoadedConfig:
    return load_config(
        config_dir / "base.yaml",
        config_dir / "backtest.yaml",
        config_dir / "safety-envelope.yaml",
        {},
    )


def _denied() -> None:
    typer.echo(canonical_json({"status": "denied", "reason": "etf_observation_input_invalid"}))
    raise typer.Exit(1)


def _publish_report(root: Path, report: dict[str, object]) -> str:
    descriptor = _open_root(root, _REPOSITORY)
    try:
        body = canonical_json(report).encode()
        digest = hashlib.sha256(body).hexdigest()
        _publish(descriptor, digest + ".observation-report.json", body)
        return digest
    finally:
        os.close(descriptor)


@app.command("prepare")
def prepare(
    credential_file: Annotated[Path, typer.Option()],
    output_root: Annotated[Path, typer.Option()],
    manifest_file: Annotated[Path, typer.Option()],
    duration_seconds: Annotated[int, typer.Option(min=1, max=900)] = 60,
    max_frames: Annotated[int, typer.Option(min=1, max=10000)] = 10000,
    predecessor_result_hash: Annotated[str | None, typer.Option()] = None,
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """Prepare a private fixed SPY/SIP scope offline; opens no credentials."""
    try:
        plan = prepare_observation_capture(
            _loaded(config_dir),
            clock=SystemClock(),
            code_revision=_revision(),
            credential_file=credential_file,
            output_root=output_root,
            repository_root=_REPOSITORY,
            duration_seconds=duration_seconds,
            max_frames=max_frames,
            predecessor_result_hash=predecessor_result_hash,
        )
        _publish_private_file(
            manifest_file, encode_observation_plan(plan), repository_root=_REPOSITORY
        )
    except (
        ValueError,
        TypeError,
        ArithmeticError,
        OSError,
        RuntimeError,
    ):
        _denied()
        return
    typer.echo(
        canonical_json(
            {"status": "prepared_offline", "plan_hash": plan.plan_hash, "execution_enabled": False}
        )
    )


@app.command("capture")
def capture(
    manifest_file: Annotated[Path, typer.Option()],
    approved_plan_hash: Annotated[str, typer.Option()],
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """One explicitly scoped local market-data run; never broker order execution."""
    try:
        plan = decode_observation_plan(
            _read_private_file(
                manifest_file,
                repository_root=_REPOSITORY,
                max_bytes=16384,
                code="probe_manifest_invalid",
            )
        )
        if plan.repository_root != _REPOSITORY:
            raise ValueError("observation_repository_mismatch")
        result = asyncio.run(
            capture_observations(
                plan,
                loaded=_loaded(config_dir),
                clock=SystemClock(),
                active_code_revision=_revision(),
                approved_plan_hash=approved_plan_hash,
            )
        )
    except (
        ValueError,
        TypeError,
        ArithmeticError,
        OSError,
        RuntimeError,
    ):
        _denied()
        return
    typer.echo(canonical_json(result))
    if result["termination"] not in ("frame_limit", "duration_limit"):
        raise typer.Exit(2)


@app.command("audit")
def audit(
    input_root: Annotated[Path, typer.Option()],
    result_hash: Annotated[str, typer.Option()],
    report_dir: Annotated[Path, typer.Option()],
) -> None:
    """Revalidate retained frames privately; no source qualification or fills."""
    try:
        auditor_revision = _revision()
        report = audit_observation_capture(input_root, result_hash, _REPOSITORY)
        report["auditor_code_revision"] = auditor_revision
        digest = _publish_report(report_dir, report)
    except (ValueError, TypeError, ArithmeticError, OSError, RuntimeError):
        _denied()
        return
    typer.echo(
        canonical_json(
            {
                "status": report["status"],
                "report_hash": digest,
                "artifact_digest": digest,
                "source_qualified": False,
            }
        )
    )
    raise typer.Exit(2)


@app.command("calibrate-costs")
def calibrate_costs(
    input_file: Annotated[Path, typer.Option()],
    input_root: Annotated[Path, typer.Option()],
    report_dir: Annotated[Path, typer.Option()],
) -> None:
    """Measure supplied whole-order records offline; missing costs stay missing."""
    try:
        calibrator_revision = _revision()
        report = load_etf_cost_observations(input_file, input_root, _REPOSITORY)
        report.pop("report_hash")
        report["calibrator_code_revision"] = calibrator_revision
        report["report_hash"] = content_hash(report)
        digest = _publish_report(report_dir, report)
    except (ValueError, TypeError, ArithmeticError, OSError, RuntimeError):
        _denied()
        return
    typer.echo(
        canonical_json(
            {
                "status": report["status"],
                "report_hash": report["report_hash"],
                "artifact_digest": digest,
                "calibration_status": "unverified",
                "evidence_promotable": False,
            }
        )
    )
    raise typer.Exit(2)


if __name__ == "__main__":
    app()
