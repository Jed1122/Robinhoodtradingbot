"""Sanitized, credential-free capital research feasibility command."""

from pathlib import Path
from typing import Annotated

import typer

from trading_bot.config import load_config
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research.etf_capital_feasibility import capital_feasibility

app = typer.Typer(no_args_is_help=True)


@app.callback()
def research() -> None:
    """Offline research only; no capture, brokerage or promotion commands."""


@app.command("capital-plan")
def capital_plan(
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """Print six independent capital budgets and assumed operating costs."""
    try:
        loaded = load_config(
            config_dir / "base.yaml",
            config_dir / "etf/capital/simulation.yaml",
            config_dir / "safety-envelope.yaml",
            {},
            research_policy_path=config_dir / "etf/capital/policy.yaml",
        )
        report = capital_feasibility(loaded)
        payload = canonical_json(
            {
                "report": report,
                "report_hash": content_hash(report),
                "production_order_cap_usd": loaded.config.activity.max_order_notional_usd,
                "production_live_ceiling_usd": (
                    loaded.config.portfolio.live_account_equity_ceiling_usd
                ),
            }
        )
        if len(payload.encode("utf-8")) > 65536:
            raise ValueError("capital report size exceeds bound")
    except (OSError, ValueError, TypeError, ArithmeticError, RecursionError):
        typer.echo(canonical_json({"reason": "capital_research_input_invalid"}))
        raise typer.Exit(1) from None
    typer.echo(payload)


if __name__ == "__main__":
    app()
