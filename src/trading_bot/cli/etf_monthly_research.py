"""Fixed, private monthly DEVELOPMENT invocation. No broker/provider surface."""

import os
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from trading_bot.cli.etf_research import (
    _REPOSITORY,
    _code_hash,
    _read_reference_inputs,
)
from trading_bot.cli.etf_research import (
    _publish_report_fd as _shared_publish_report_fd,
)
from trading_bot.code_identity import resolve_code_identity
from trading_bot.config import LoadedConfig, load_config
from trading_bot.market_data.bundle_store import _open_root
from trading_bot.market_data.etf_native_archive import read_etf_native_bars
from trading_bot.market_data.recording import canonical_json
from trading_bot.research.etf_monthly_economics import (
    etf_monthly_cost_plan_hash,
    etf_monthly_economic_plan_hash,
    etf_monthly_operating_basis_hash,
    monthly_expansion_disposition,
    run_etf_monthly_economics,
)
from trading_bot.research.etf_monthly_intake import (
    etf_monthly_source_plan_hash,
    make_etf_monthly_request,
)
from trading_bot.research.etf_monthly_protocol import _check
from trading_bot.research.etf_monthly_study import freeze_etf_monthly_study

app = typer.Typer(no_args_is_help=True)
MAX_REPORT_BYTES = 8 * 1024 * 1024


@app.callback()
def research() -> None:
    """Offline monthly research; no promotion or live commands."""


def _publish_report_fd(descriptor: int, report: dict[str, object]) -> str:
    # Bound this namespace before the existing descriptor-bound immutable writer.
    _check(len(canonical_json(report).encode()) <= MAX_REPORT_BYTES)
    return _shared_publish_report_fd(descriptor, report)


def _load(config_dir: Path) -> LoadedConfig:
    return load_config(
        config_dir / "base.yaml",
        config_dir / "etf/monthly/simulation.yaml",
        config_dir / "safety-envelope.yaml",
        {},
    )


@app.command("screen-run")
def screen_run(
    capture_dir: Annotated[Path, typer.Option()],
    manifest_hash: Annotated[str, typer.Option()],
    reference_dir: Annotated[Path, typer.Option()],
    calendar_hash: Annotated[str, typer.Option()],
    issuer_hash: Annotated[str, typer.Option()],
    report_dir: Annotated[Path, typer.Option()],
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """Freeze then evaluate the one fixed adaptive-development grid, privately."""
    descriptor = -1
    try:
        identity = resolve_code_identity(_REPOSITORY, None)
        _check(not identity.dirty and identity.git_commit is not None)
        loaded = _load(config_dir)
        # The argument may locate identical canonical files, never a custom risk
        # graph. No ambient environment variable can enable the legacy ETF pilot.
        _check(loaded == _load(_REPOSITORY / "configs"))
        code = _code_hash()
        source = read_etf_native_bars(capture_dir, manifest_hash, repository_root=_REPOSITORY)
        calendar, issuer = _read_reference_inputs(reference_dir, calendar_hash, issuer_hash)
        study = freeze_etf_monthly_study(
            loaded,
            code_hash=code,
            source_plan_hash=etf_monthly_source_plan_hash(source, calendar, issuer),
            cost_plan_hash=etf_monthly_cost_plan_hash(),
            operating_basis_hash=etf_monthly_operating_basis_hash(),
            holdout_exposure="unknown",
        )
        request = make_etf_monthly_request(study, source, calendar, issuer)
        economic_plan = etf_monthly_economic_plan_hash(request.protocol)
        descriptor = _open_root(report_dir, _REPOSITORY)
        preregistration_hash = _publish_report_fd(
            descriptor,
            {
                "schema": "etf-monthly-screen-preregistration-v1",
                "study": study,
                "protocol": request.protocol,
                "input_hash": request.request_hash,
                "economic_plan_hash": economic_plan,
                "source_inventory": source.manifest_hash,
                "calendar_hash": request.protocol.calendar_hash,
                "issuer_hash": issuer.archive_hash,
                "code_hash": code,
                "git_commit": identity.git_commit,
                "config_hash": loaded.config_hash,
                "operating_basis_hash": etf_monthly_operating_basis_hash(),
                "cost_plan_hash": etf_monthly_cost_plan_hash(),
                "first_rebalance": request.protocol.first_rebalance,
                "first_economic_point": request.protocol.first_evaluation_session,
                "development_previously_examined": True,
                "holdout_exposure": "unknown",
                "adaptive_attempt_history": (
                    "previous_corrected_20_100_development_attempt_9_reject_15_insufficient_0_proceed",
                    "monthly_sma10_is_new_adaptive_hypothesis_not_independent_confirmation",
                ),
                "screening_verdict": "NOT_EVALUATED",
                "holdout_evaluated": False,
                "source_qualified": False,
                "cost_qualified": False,
                "execution_enabled": False,
                "economic_admitted": False,
                "evidence_promotable": False,
                "live_authorized": False,
            },
        )
        # Detect executable/config edits during intake or preregistration, before
        # evaluating any outcomes. A Git commit is not deployment evidence.
        current = resolve_code_identity(_REPOSITORY, None)
        _check(current == identity and _code_hash() == code and _load(config_dir) == loaded)
        result = run_etf_monthly_economics(request)
        _check(resolve_code_identity(_REPOSITORY, None) == identity)
        _check(_code_hash() == code and _load(config_dir) == loaded)
        _check(
            result.input_hash == request.request_hash and result.economic_plan_hash == economic_plan
        )
        disposition = monthly_expansion_disposition(result)
        digest = _publish_report_fd(
            descriptor,
            {
                "schema": "etf-monthly-screen-report-v1",
                **asdict(result),
                "result_hash": result.result_hash,
                "preregistration_hash": preregistration_hash,
                "holdout_evaluated": False,
                "disposition": disposition,
            },
        )
    except (ValueError, TypeError, ArithmeticError, OSError, RuntimeError, AttributeError):
        typer.echo(canonical_json({"status": "denied", "reason": "etf_monthly_input_invalid"}))
        raise typer.Exit(1) from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    typer.echo(
        canonical_json(
            {
                "report_hash": digest,
                "preregistration_hash": preregistration_hash,
                "economic_plan_hash": economic_plan,
                "disposition": disposition,
                "screening_verdict_counts": dict(
                    Counter(s.screening_verdict for s in result.scores)
                ),
                "holdout_evaluated": False,
                "development_previously_examined": True,
                "source_qualified": False,
                "cost_qualified": False,
                "execution_enabled": False,
                "economic_admitted": False,
                "evidence_promotable": False,
                "live_authorized": False,
            }
        )
    )


if __name__ == "__main__":
    app()
