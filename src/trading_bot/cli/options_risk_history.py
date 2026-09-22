"""Offline loss-history rehearsal. Only disposable private SQLite databases are written.

No existing ledger path is accepted, no ambient credentials are read, and no live owner
or broker is constructed. A simulated restart is engineering evidence only.
"""

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer

from trading_bot.config import LoadedConfig, load_config
from trading_bot.domain import AccountId
from trading_bot.market_data.bundle_codec import _json, _mapping, _time
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.bundle_store import _open_root, _read
from trading_bot.market_data.recording import canonical_json
from trading_bot.persistence.options_risk import decode_point
from trading_bot.persistence.options_risk_rehearsal import (
    MAX_REHEARSAL_POINTS,
)
from trading_bot.persistence.options_risk_rehearsal import (
    rehearse_risk_history as _rehearse,
)
from trading_bot.risk.options_loss_history import OptionsLossPoint

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
_ROOT = Path(__file__).resolve().parents[3]
_LIMITS = BundleLimits(
    max_envelope_bytes=1048576,
    max_blob_bytes=1048576,
    max_total_bytes=1048576,
    max_records=50000,
    max_json_depth=12,
)


def _load(directory: Path) -> LoadedConfig:
    return load_config(
        directory / "base.yaml",
        directory / "options/simulation.yaml",
        directory / "safety-envelope.yaml",
        {},
    )


def _read_fixture(path: Path) -> tuple[tuple[OptionsLossPoint, ...], datetime]:
    directory = _open_root(path.parent, _ROOT)
    try:
        body = _read(directory, path.name, _LIMITS.max_blob_bytes)
    finally:
        os.close(directory)
    root = _mapping(
        _json(body, max_bytes=_LIMITS.max_blob_bytes, limits=_LIMITS),
        {"schema", "source_kind", "points", "as_of"},
    )
    if root["schema"] != "options-risk-rehearsal-v1" or root["source_kind"] != "synthetic":
        raise ValueError("unsupported risk rehearsal")
    values = root["points"]
    if type(values) is not list or not 1 <= len(values) <= MAX_REHEARSAL_POINTS:
        raise ValueError("bounded risk history required")
    return tuple(decode_point(canonical_json(p)) for p in values), _time(root["as_of"])


def _emit(report: dict[str, object]) -> None:
    losses = report["losses"]
    if not isinstance(losses, dict):
        _denied()
        return
    typer.echo(canonical_json(report))
    if any(
        reason in losses["entry_reasons"]
        for reason in ("risk_history_incomplete", "risk_observation_stale", "outside_session")
    ):
        raise typer.Exit(2)


def _denied() -> None:
    typer.echo(canonical_json({"status": "denied", "reason": "risk_history_input_invalid"}))
    raise typer.Exit(1)


@app.command("demo")
def demo(config_dir: Annotated[Path, typer.Option()] = Path("configs")) -> None:
    """Rehearse a fabricated loss then deposit, including database close/reopen recovery."""
    try:
        loaded = _load(config_dir)
        opening = datetime(2026, 9, 18, 13, 30, tzinfo=UTC)
        first = OptionsLossPoint(
            "initial",
            AccountId("synthetic:risk-demo"),
            str(loaded.config_hash),
            opening,
            "2026-09-18",
            opening,
            opening.replace(hour=20, minute=0),
            None,
            Decimal(100),
            Decimal(0),
            "a" * 64,
            True,
        )
        loss = replace(
            first,
            event_id="loss",
            observed_at=opening + timedelta(seconds=1),
            liquidation_equity=Decimal(89),
        )
        deposit = replace(
            loss,
            event_id="deposit",
            observed_at=opening + timedelta(seconds=2),
            liquidation_equity=Decimal(1089),
            cumulative_external_flows=Decimal(1000),
        )
        report = _rehearse(loaded, (first, loss, deposit), deposit.observed_at)
    except (ValueError, TypeError, ArithmeticError, OSError, RuntimeError):
        _denied()
        return
    _emit(report)


@app.command("replay-file")
def replay_file(
    input_path: Annotated[Path, typer.Argument()],
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """Read a private bounded synthetic fixture and verify a disposable journal restart."""
    try:
        loaded = _load(config_dir)
        points, as_of = _read_fixture(input_path)
        report = _rehearse(loaded, points, as_of)
    except (ValueError, TypeError, ArithmeticError, OSError, RuntimeError):
        _denied()
        return
    _emit(report)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
