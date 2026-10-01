"""Offline ETF commands; no broker, credential or network composition.

Run with python -m trading_bot.cli.etf_research. The existing dirty main operator
CLI is not modified. Research-owned fixture databases cannot adopt unknown ledgers.
"""

import fcntl
import hashlib
import os
import stat
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer

from trading_bot.config import LoadedConfig, load_config
from trading_bot.domain.decimal_utils import parse_decimal, require_bounded_decimal
from trading_bot.market_data.bundle_store import (
    _open_root,
    _private,
    _publish,
    _read,
    _subdirectory,
)
from trading_bot.market_data.etf_native_archive import read_etf_native_bars
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research.etf_economics import evaluate_etf_account_economics
from trading_bot.research.etf_latest_vintage import (
    EtfLatestVintageRequest,
    latest_vintage_source_plan_hash,
    run_latest_vintage_etf,
)
from trading_bot.research.etf_study import EtfStudy, freeze_etf_study
from trading_bot.simulation.etf_account import (
    EtfAccountRequest,
    EtfAccountResult,
    replay_etf_account,
)
from trading_bot.simulation.etf_fixtures import synthetic_etf_account_request

app = typer.Typer(no_args_is_help=True)
_REPOSITORY = Path(__file__).resolve().parents[3]
_SOURCE = Path(__file__).resolve().parents[1]


def _code_hash() -> str:
    paths = (
        tuple(sorted(_SOURCE.rglob("*.py")))
        + tuple(sorted((_REPOSITORY / "migrations").rglob("*.py")))
        + (_REPOSITORY / "uv.lock", _REPOSITORY / "pyproject.toml")
    )
    if any(path.is_symlink() for path in paths):
        raise ValueError("etf_code_identity_invalid")
    return content_hash(
        tuple(
            (str(path.relative_to(_REPOSITORY)), hashlib.sha256(path.read_bytes()).hexdigest())
            for path in paths
        )
    )


def _load(config_dir: Path) -> LoadedConfig:
    return load_config(
        config_dir / "base.yaml",
        config_dir / "backtest.yaml",
        config_dir / "safety-envelope.yaml",
        {"TRADING_BOT__EQUITY_STRATEGIES__ETF_PILOT__ENABLED": "true"},
    )


def _study(loaded: LoadedConfig, *, source_plan_hash: str) -> EtfStudy:
    return freeze_etf_study(
        loaded,
        code_hash=_code_hash(),
        source_plan_hash=source_plan_hash,
        cost_plan_hash=content_hash("ETF uncalibrated diagnostic costs v1"),
        holdout_previously_examined=False,
    )


def _invalid() -> None:
    typer.echo(canonical_json({"status": "denied", "reason": "etf_research_input_invalid"}))
    raise typer.Exit(1)


def _report(state: EtfAccountResult, operating_cost: Decimal) -> dict[str, object]:
    economics = evaluate_etf_account_economics(state, operating_cost=operating_cost)
    return {
        "schema": "etf-account-report-v1",
        "source_kind": "synthetic-account-facts-v1",
        "state_hash": state.state_hash,
        "study_hash": state.study_hash,
        "initial_cash": state.initial_cash,
        "cash": state.cash,
        "settled_cash": state.settled_cash,
        "shares": state.shares,
        "reserved_cash": state.reserved_cash,
        "reserved_trial_risk": state.trial.reserved_risk,
        "consumed_trial_loss": state.trial.consumed_loss,
        "complete": state.complete,
        "entry_halted": state.entry_halted,
        "trading_pnl": economics.trading_pnl,
        "operating_cost": operating_cost,
        "operating_profit": economics.operating_profit,
        "economic_verdict": economics.verdict,
        "reasons": economics.reasons,
        "evidence_promotable": False,
        "live_authorized": False,
        "execution_enabled": False,
    }


def _publish_report(directory: Path, report: dict[str, object]) -> str:
    encoded = canonical_json(report).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    descriptor = _open_root(directory, _REPOSITORY)
    try:
        _publish(descriptor, digest + ".etf-report.json", encoded)
    finally:
        os.close(descriptor)
    return digest


def _fixture(config_dir: Path, capital: str, scenario: str) -> EtfAccountRequest:
    study = _study(
        _load(config_dir), source_plan_hash=content_hash("ETF synthetic account fixture v1")
    )
    return synthetic_etf_account_request(study, parse_decimal(capital), scenario)


@app.command("account-fixture-run")
def account_fixture_run(
    capital: Annotated[str, typer.Option()] = "500",
    scenario: Annotated[str, typer.Option()] = "completed",
    operating_cost: Annotated[str, typer.Option()] = "0",
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """Simulate exact fabricated cash flows; no empirical edge or live capability."""
    try:
        state = replay_etf_account(_fixture(config_dir, capital, scenario))
        report = _report(state, parse_decimal(operating_cost))
    except (ValueError, TypeError, ArithmeticError, OSError, RuntimeError):
        _invalid()
        return
    typer.echo(canonical_json(report))
    if not state.complete:
        raise typer.Exit(2)


def _checkpoint_run(root: Path, request: EtfAccountRequest, through: int) -> EtfAccountResult:
    """Descriptor-bound immutable snapshots using the existing private publisher.

    This is an offline replay checkpoint, not a SQLite/live execution ledger. Keep
    verified descriptors open through every read/publication, so a renamed parent
    cannot redirect writes into an unrelated pathname. No state owner is duplicated:
    every stored prefix is reconstructed by replay_etf_account before use.
    """
    descriptor = _open_root(root, _REPOSITORY)
    child = lock = -1
    try:
        child = _subdirectory(descriptor, "etf-account-checkpoints", create=True)
        marker = canonical_json(
            {
                "schema": "etf-fixture-checkpoint-owner-v1",
                "request_hash": content_hash(request),
                "execution_enabled": False,
            }
        ).encode()
        try:
            previous = _read(child, "owner.json", 16384)
        except FileNotFoundError:
            if set(os.listdir(child)):
                raise ValueError("etf_checkpoint_owner_invalid") from None
            _publish(child, "owner.json", marker)
        else:
            if previous != marker:
                raise ValueError("etf_checkpoint_owner_invalid")
        lock = os.open("writer.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=child)
        _private(lock, directory=False)
        lock_metadata = os.fstat(lock)
        if (
            not stat.S_ISREG(lock_metadata.st_mode)
            or lock_metadata.st_nlink != 1
            or lock_metadata.st_size != 0
        ):
            raise ValueError("etf_checkpoint_owner_invalid")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous_hash = "0" * 64
        cursor = 0
        state = replay_etf_account(replace(request, events=()))
        names = set(os.listdir(child)) - {"owner.json", "writer.lock"}
        if not names <= {f"{i:08d}.etf-checkpoint.json" for i in range(1, len(request.events) + 1)}:
            raise ValueError("etf_checkpoint_invalid")
        for i in range(1, len(request.events) + 1):
            state_at = replay_etf_account(replace(request, events=request.events[:i]))
            checkpoint = canonical_json(
                {
                    "schema": "etf-account-checkpoint-v1",
                    "cursor": i,
                    "request_hash": content_hash(request),
                    "previous_hash": previous_hash,
                    "source_event": request.events[i - 1],
                    "state_hash": state_at.state_hash,
                    "execution_enabled": False,
                }
            ).encode()
            name = f"{i:08d}.etf-checkpoint.json"
            if name not in names:
                if any(
                    f"{j:08d}.etf-checkpoint.json" in names
                    for j in range(i + 1, len(request.events) + 1)
                ):
                    raise ValueError("etf_checkpoint_gap")
                break
            if _read(child, name, 1048576) != checkpoint:
                raise ValueError("etf_checkpoint_invalid")
            previous_hash = hashlib.sha256(checkpoint).hexdigest()
            state, cursor = state_at, i
        if through < cursor:
            raise ValueError("etf_checkpoint_cursor_invalid")
        for i in range(cursor + 1, through + 1):
            state = replay_etf_account(replace(request, events=request.events[:i]))
            checkpoint = canonical_json(
                {
                    "schema": "etf-account-checkpoint-v1",
                    "cursor": i,
                    "request_hash": content_hash(request),
                    "previous_hash": previous_hash,
                    "source_event": request.events[i - 1],
                    "state_hash": state.state_hash,
                    "execution_enabled": False,
                }
            ).encode()
            _publish(child, f"{i:08d}.etf-checkpoint.json", checkpoint)
            previous_hash = hashlib.sha256(checkpoint).hexdigest()
        return state
    finally:
        if lock >= 0:
            os.close(lock)
        if child >= 0:
            os.close(child)
        os.close(descriptor)


@app.command("account-ledger-run")
def account_ledger_run(
    output_dir: Annotated[Path, typer.Option()],
) -> None:
    """Denied: this stack cannot bind SQLite journals to a verified directory fd."""
    del output_dir
    typer.echo(
        canonical_json({"status": "denied", "reason": "etf_sqlite_path_binding_unsupported"})
    )
    raise typer.Exit(1)


@app.command("account-checkpoint-run")
def account_checkpoint_run(
    output_dir: Annotated[Path, typer.Option()],
    capital: Annotated[str, typer.Option()] = "500",
    through_events: Annotated[int, typer.Option()] = 8,
    operating_cost: Annotated[str, typer.Option()] = "0",
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """Persist/restart exact fabricated facts in descriptor-bound private snapshots."""
    try:
        request = _fixture(config_dir, capital, "completed")
        cost = parse_decimal(operating_cost)
        require_bounded_decimal(cost, "operating cost", nonnegative=True)
        if not 0 <= through_events <= len(request.events):
            raise ValueError("etf_checkpoint_cursor_invalid")
        state = _checkpoint_run(output_dir, request, through_events)
        report = _report(state, cost)
    except (ValueError, TypeError, ArithmeticError, OSError, RuntimeError):
        _invalid()
        return
    typer.echo(canonical_json(report))
    if not state.complete:
        raise typer.Exit(2)


@app.command("latest-vintage-run")
def latest_vintage_run(
    capture_dir: Annotated[Path, typer.Option()],
    manifest_hash: Annotated[str, typer.Option()],
    report_dir: Annotated[Path, typer.Option()],
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """Run fixed development signals from saved SIP bars; holdout/fills stay blocked."""
    try:
        source = read_etf_native_bars(capture_dir, manifest_hash, repository_root=_REPOSITORY)
        study = _study(_load(config_dir), source_plan_hash=latest_vintage_source_plan_hash(source))
        # Publish the protocol before any outcomes are evaluated.
        _publish_report(
            report_dir,
            {
                "schema": "etf-latest-vintage-preregistration-v1",
                "study": study,
                "source_plan_hash": study.source_plan_hash,
                "economic_verdict": "NOT_EVALUATED",
                "execution_enabled": False,
                "evidence_promotable": False,
            },
        )
        result = run_latest_vintage_etf(EtfLatestVintageRequest(study, source))
        report = {
            "schema": "etf-latest-vintage-report-v1",
            **asdict(result),
            "result_hash": result.result_hash,
            "live_authorized": False,
        }
        digest = _publish_report(report_dir, report)
    except (ValueError, TypeError, ArithmeticError, OSError, RuntimeError):
        _invalid()
        return
    typer.echo(
        canonical_json(
            {
                "report_hash": digest,
                "study_hash": study.study_hash,
                "development_records": result.development_records,
                "holdout_evaluated": False,
                "economic_verdict": result.economic_verdict,
                "execution_enabled": False,
                "evidence_promotable": False,
            }
        )
    )


if __name__ == "__main__":
    app()
