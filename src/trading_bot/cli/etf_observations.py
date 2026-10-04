"""Explicit standalone observations and offline cost measurements; no daemon."""

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Annotated, cast

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
    read_observation_capture,
)
from trading_bot.diagnostics.alpaca_probe_io import _publish_private_file, _read_private_file
from trading_bot.diagnostics.etf_execution_receipts import read_execution_receipts
from trading_bot.market_data.bundle_store import _open_root, _publish, _read
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research.etf_cost_calibration import load_etf_cost_observations
from trading_bot.research.etf_execution_receipts import MAX_BODY_BYTES, source_digest

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


@app.command("stream-prefix")
def stream_prefix(
    input_root: Annotated[Path, typer.Option()],
    result_hash: Annotated[str, typer.Option()],
    received_at_ns: Annotated[str, typer.Option()],
    received_monotonic_ns: Annotated[str, typer.Option()],
    report_dir: Annotated[Path, typer.Option()],
) -> None:
    """Report a private dual-receipt-clock prefix; never infer market eligibility."""
    try:
        auditor_revision = _revision()
        utc_ns = _receipt_cutoff(received_at_ns)
        mono_ns = _receipt_cutoff(received_monotonic_ns)
        capture = read_observation_capture(input_root, result_hash, _REPOSITORY)
        frames = capture.visible_frames(received_at_ns=utc_ns, received_monotonic_ns=mono_ns)
        counts = {"quote": 0, "status": 0, "luld": 0}
        observation_hashes = []
        for frame in frames:
            for observation in frame.observations:
                counts[observation.kind] += 1
                observation_hashes.append(observation.observation_hash)
        status = "OBSERVED_UNQUALIFIED" if any(counts.values()) else "BLOCKED_INPUTS"
        report: dict[str, object] = {
            "schema": "alpaca-observation-prefix-report-v1",
            "auditor_code_revision": auditor_revision,
            "result_hash": capture.result_hash,
            "plan_hash": capture.plan_hash,
            "captured_code_revision": capture.code_revision,
            "captured_config_hash": capture.config_hash,
            "received_at_ns": utc_ns,
            "received_monotonic_ns": mono_ns,
            "frame_count": len(frames),
            "receipt_hashes": tuple(frame.receipt_sha256 for frame in frames),
            "observation_hashes": tuple(observation_hashes),
            "counts": counts,
            "status": status,
            "source_qualified": False,
            "evidence_promotable": False,
            "execution_enabled": False,
            "live_enabled": False,
        }
        digest = _publish_report(report_dir, report)
    except (ValueError, TypeError, ArithmeticError, OSError, RuntimeError, AttributeError):
        _denied()
        return
    typer.echo(
        canonical_json(
            {
                "status": status,
                "report_hash": digest,
                "artifact_digest": digest,
                "counts": counts,
                "source_qualified": False,
                "evidence_promotable": False,
                "execution_enabled": False,
                "live_enabled": False,
            }
        )
    )
    raise typer.Exit(2)


def _receipt_cutoff(value: str) -> int:
    # Parse inside the guarded command, not Typer's value-echoing coercion.
    if not (
        type(value) is str and 1 <= len(value) <= 19 and all(char in "0123456789" for char in value)
    ):
        raise ValueError("observation_clock_invalid")
    result = int(value)
    if result > 2**63 - 1:
        raise ValueError("observation_clock_invalid")
    return result


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


@app.command("link-costs")
def link_costs(
    input_root: Annotated[Path, typer.Option()],
    manifest_hash: Annotated[str, typer.Option()],
    report_dir: Annotated[Path, typer.Option()],
) -> None:
    """Link a private receipt checkpoint offline; never authenticates or trades."""
    source_descriptor = destination_descriptor = -1
    try:
        revision = _revision()
        linked = read_execution_receipts(input_root, manifest_hash, _REPOSITORY)
        body = canonical_json(linked["cost_input"]).encode()
        input_hash = source_digest(body)
        source_descriptor = _open_root(input_root, _REPOSITORY)
        destination_descriptor = _open_root(report_dir, _REPOSITORY)
        for reference in cast(list[str], linked["reference_hashes"]):
            original = _read(source_descriptor, reference + ".source", MAX_BODY_BYTES)
            if source_digest(original) != reference:
                raise ValueError("receipt_source_changed")
            _publish(destination_descriptor, reference + ".source", original)
        input_name = input_hash + ".cost-input.json"
        _publish(destination_descriptor, input_name, body)
        report = load_etf_cost_observations(report_dir / input_name, report_dir, _REPOSITORY)
        report.pop("report_hash")
        report["calibrator_code_revision"] = revision
        report["receipt_checkpoint_hash"] = linked["checkpoint_hash"]
        report["clock_session_hash"] = linked["clock_session_hash"]
        report["receipt_reference_hashes"] = linked["reference_hashes"]
        for name in (
            "completed_order_count",
            "incomplete_order_count",
            "unfilled_order_count",
            "unfilled_outcomes",
            "quote_receipt_bytes_linked",
            "clock_session_attested",
            "customer_authenticated",
            "calibration_verified",
        ):
            report[name] = linked[name]
        report["report_hash"] = content_hash(report)
        digest = _publish_report(report_dir, report)
    except (ValueError, TypeError, ArithmeticError, OSError, RuntimeError):
        _denied()
        return
    finally:
        for descriptor in (source_descriptor, destination_descriptor):
            if descriptor >= 0:
                os.close(descriptor)
    typer.echo(
        canonical_json(
            {
                "status": report["status"],
                "report_hash": report["report_hash"],
                "artifact_digest": digest,
                "input_sha256": input_hash,
                "completed_order_count": report["completed_order_count"],
                "incomplete_order_count": report["incomplete_order_count"],
                "unfilled_order_count": report["unfilled_order_count"],
                "calibration_status": "unverified",
                "evidence_promotable": False,
                "execution_enabled": False,
            }
        )
    )
    raise typer.Exit(2)


if __name__ == "__main__":
    app()
