"""Offline options research commands, isolated from every broker composition.

Run with ``python -m trading_bot.cli.options_research --help``. The existing, already
modified operator CLI is deliberately not rewritten during this incremental migration.
"""

from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer

from trading_bot.cli.options_native import (
    native_bars_import,
    native_options_shortlist,
    native_source_verify,
    options_coverage_manifest,
)
from trading_bot.config import LoadedConfig, load_config
from trading_bot.domain.decimal_utils import parse_decimal, require_bounded_decimal
from trading_bot.domain.options import OptionKind
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research.options_shortlist import select_options_shortlist
from trading_bot.research.options_shortlist_io import (
    ShortlistFileError,
    read_shortlist_input,
    shortlist_code_hash,
    write_shortlist_manifest,
)
from trading_bot.risk.options_economics import (
    OptionsCapitalState,
    TrialLossState,
    long_option_feasibility,
)
from trading_bot.simulation.options_fixtures import synthetic_options_request
from trading_bot.simulation.options_replay import replay_options
from trading_bot.simulation.options_replay_io import (
    read_options_replay_file,
    replay_options_report,
    write_options_replay_input,
)
from trading_bot.simulation.options_replay_models import SOURCE, OptionsReplayResult

app = typer.Typer(no_args_is_help=True)
app.command("native-bars-import")(native_bars_import)
app.command("native-source-verify")(native_source_verify)
app.command("native-options-shortlist")(native_options_shortlist)
app.command("options-coverage-manifest")(options_coverage_manifest)
CAPITAL_TIERS = (100, 500, 1000, 2500, 5000, 10000, 25000, 50000)


def _load(config_dir: Path) -> LoadedConfig:
    # Research does not read environment credentials or inherit ambient live flags.
    return load_config(
        config_dir / "base.yaml",
        config_dir / "options/simulation.yaml",
        config_dir / "safety-envelope.yaml",
        {},
    )


def _invalid() -> None:
    typer.echo(canonical_json({"status": "denied", "reason": "options_research_input_invalid"}))
    raise typer.Exit(1)


@app.command("export-options-fixture")
def export_options_fixture(
    output_dir: Annotated[Path, typer.Option()],
    research_capital: Annotated[str, typer.Option()] = "100",
    scenario: Annotated[str, typer.Option()] = "completed",
    option_kind: Annotated[str, typer.Option()] = "call",
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """Save fabricated inputs in an existing private directory outside the repository."""
    try:
        request = synthetic_options_request(
            _load(config_dir),
            parse_decimal(research_capital),
            scenario,
            option_kind=OptionKind(option_kind),
        )
        digest = write_options_replay_input(
            output_dir,
            request,
            repository_root=Path(__file__).resolve().parents[3],
        )
    except (ValueError, TypeError, ArithmeticError, OSError):
        _invalid()
        return
    typer.echo(
        canonical_json(
            {
                "document_hash": digest,
                "source_kind": SOURCE,
                "production_eligible": False,
                "evidence_promotable": False,
            }
        )
    )


@app.command("replay-file")
def replay_file(
    input_path: Annotated[Path, typer.Argument()],
    report_dir: Annotated[Path | None, typer.Option()] = None,
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """Replay strict saved synthetic inputs; never load configuration from the document."""
    try:
        repository = Path(__file__).resolve().parents[3]
        request = read_options_replay_file(
            input_path, _load(config_dir), repository_root=repository
        )
        row = replay_options_report(request, report_dir=report_dir, repository_root=repository)
    except (ValueError, TypeError, ArithmeticError, OSError, RuntimeError):
        _invalid()
        return
    typer.echo(canonical_json(row))
    result = row["result"]
    if isinstance(result, OptionsReplayResult) and result.status == "incomplete_synthetic_replay":
        raise typer.Exit(2)


@app.command("options-replay")
def options_replay(
    research_capital: Annotated[str, typer.Option()] = "100",
    scenario: Annotated[str, typer.Option()] = "completed",
    option_kind: Annotated[str, typer.Option()] = "call",
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """Run a fabricated engineering fixture, never real market or broker evidence."""
    try:
        result = replay_options(
            synthetic_options_request(
                _load(config_dir),
                parse_decimal(research_capital),
                scenario,
                option_kind=OptionKind(option_kind),
            )
        )
        payload = asdict(result)
        payload["result_hash"] = content_hash(result)
    except (ValueError, TypeError, ArithmeticError, RuntimeError):
        _invalid()
        return
    typer.echo(canonical_json(payload))
    if result.status == "incomplete_synthetic_replay":
        raise typer.Exit(2)


@app.command("capital-feasibility")
def capital_feasibility(
    premium: Annotated[str, typer.Option()] = "0.25",
    multiplier: Annotated[str, typer.Option()] = "100",
    fee_reserve: Annotated[str, typer.Option()] = "1",
    annual_operating_cost: Annotated[str, typer.Option()] = "0",
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """Necessary whole-unit budget checks for hypothetical tiers, not recommendations."""
    try:
        loaded = _load(config_dir)
        annual = require_bounded_decimal(
            parse_decimal(annual_operating_cost), "annual_operating_cost", nonnegative=True
        )
        rows: list[dict[str, object]] = []
        for tier in CAPITAL_TIERS:
            equity = Decimal(tier)
            result = long_option_feasibility(
                loaded,
                OptionsCapitalState(equity, equity, equity, Decimal(0), Decimal(0), 0, 0),
                premium=parse_decimal(premium),
                multiplier=parse_decimal(multiplier),
                fee_reserve_per_unit=parse_decimal(fee_reserve),
                trial=TrialLossState(()),
            )
            rows.append(
                {
                    "capital": equity,
                    **asdict(result),
                    "annual_operating_cost_drag_pct": annual / equity * 100,
                    "production_eligible": False,
                }
            )
    except (ValueError, TypeError, ArithmeticError):
        _invalid()
        return
    typer.echo(
        canonical_json(
            {
                "schema": "options-capital-feasibility-v1",
                "config_hash": loaded.config_hash,
                "source_kind": "hypothetical-inputs",
                "tiers": rows,
                "input_assumptions": {
                    "premium": parse_decimal(premium),
                    "multiplier": parse_decimal(multiplier),
                    "bounded_round_trip_fee_reserve": parse_decimal(fee_reserve),
                    "annual_operating_cost": annual,
                },
                "live_authorized": False,
                "economic_verdict": "ECONOMIC_NO_GO",
                "limitations": [
                    "necessary_capital_filter_not_final_pretrade",
                    "fees_and_operating_costs_unverified",
                    "no_empirical_edge_evidence",
                    "account_capabilities_unverified",
                    "legacy_stricter_caps_retained",
                ],
            }
        )
    )


def _load_shortlist(config_dir: Path) -> LoadedConfig:
    return load_config(
        config_dir / "base.yaml",
        config_dir / "options/shortlist/simulation.yaml",
        config_dir / "safety-envelope.yaml",
        {},
    )


@app.command("options-shortlist")
def options_shortlist(
    input_path: Annotated[Path, typer.Argument()],
    output_dir: Annotated[Path, typer.Option()],
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """Select a private offline acquisition universe, never an order or data download."""
    reason = "options_shortlist_input_invalid"
    try:
        loaded = _load_shortlist(config_dir)
        settings = loaded.config.options.research_shortlist
        repository = Path(__file__).resolve().parents[3]
        session, input_hash = read_shortlist_input(
            input_path,
            settings=settings,
            repository_root=repository,
        )
        result = select_options_shortlist(
            session,
            settings=settings,
            config_hash=loaded.config_hash,
            code_hash=shortlist_code_hash(),
            input_hash=input_hash,
        )
        digest = write_shortlist_manifest(
            output_dir,
            result,
            repository_root=repository,
            settings=settings,
        )
        typer.echo(
            canonical_json(
                {
                    "status": result.status,
                    "decision_sessions": 1,
                    "candidate_count": len(result.candidates),
                    "denied_sessions": int(result.status == "no_candidate"),
                    "reasons": result.reasons,
                    "manifest_hash": digest,
                }
            )
        )
        return
    except ShortlistFileError as error:
        if error.code != "shortlist_input_invalid":
            reason = error.code
    except (ValueError, TypeError, ArithmeticError, OSError):
        pass
    typer.echo(canonical_json({"status": "denied", "reason": reason}))
    raise typer.Exit(1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
