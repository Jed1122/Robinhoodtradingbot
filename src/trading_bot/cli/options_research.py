"""Offline options research commands, isolated from every broker composition.

Run with ``python -m trading_bot.cli.options_research --help``. The existing, already
modified operator CLI is deliberately not rewritten during this incremental migration.
"""

from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer

from trading_bot.config import LoadedConfig, load_config
from trading_bot.domain.decimal_utils import parse_decimal, require_bounded_decimal
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.risk.options_economics import (
    OptionsCapitalState,
    TrialLossState,
    long_option_feasibility,
)
from trading_bot.simulation.options_fixtures import synthetic_options_request
from trading_bot.simulation.options_replay import replay_options

app = typer.Typer(no_args_is_help=True)
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


@app.command("options-replay")
def options_replay(
    research_capital: Annotated[str, typer.Option()] = "100",
    scenario: Annotated[str, typer.Option()] = "completed",
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """Run a fabricated engineering fixture, never real market or broker evidence."""
    try:
        result = replay_options(
            synthetic_options_request(_load(config_dir), parse_decimal(research_capital), scenario)
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
