"""The capital-plan command reports assumptions without authenticated access."""

import importlib
import json
from pathlib import Path

from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[3]


def api():
    return importlib.import_module("trading_bot.cli.etf_capital_research")


def test_capital_plan_has_six_tiers_and_unknown_actual_costs():
    result = CliRunner().invoke(api().app, ["capital-plan", "--config-dir", str(ROOT / "configs")])
    assert result.exit_code == 0, result.stdout
    body = json.loads(result.stdout)
    assert body["report"]["schema"] == "etf-capital-feasibility-v1"
    assert [row["budget"]["equity"] for row in body["report"]["tiers"]] == [
        "100",
        "250",
        "500",
        "1000",
        "5000",
        "10000",
    ]
    assert body["report"]["tiers"][0]["compute_12_monthly_annual_equity_pct"] == "144"
    for key in ("actual_recurring_data_cost", "actual_customer_fee_cost", "actual_tax_cost"):
        assert body["report"][key] is None
    assert body["report"]["execution_enabled"] is False
    assert body["report"]["evidence_promotable"] is False
    assert body["report"]["broker_fractional_route_verified"] is False
    assert body["production_order_cap_usd"] == "15"
    assert body["production_live_ceiling_usd"] == "1000"
    assert len(body["report_hash"]) == 64


def test_no_live_capture_or_custom_threshold_commands():
    result = CliRunner().invoke(api().app, ["capital-plan", "--help"])
    assert result.exit_code == 0
    for option in ("--live", "--capture", "--credentials", "--capital", "--risk"):
        assert option not in result.stdout
    assert CliRunner().invoke(api().app, ["live"]).exit_code != 0


def test_bad_configuration_is_sanitized(tmp_path):
    result = CliRunner().invoke(api().app, ["capital-plan", "--config-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert json.loads(result.stdout) == {"reason": "capital_research_input_invalid"}
    assert str(tmp_path) not in result.stdout


def test_recursive_yaml_is_reported_as_invalid_not_raw_exception(tmp_path):
    (tmp_path / "base.yaml").write_text("a: &loop [*loop]\n")
    result = CliRunner().invoke(api().app, ["capital-plan", "--config-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert json.loads(result.stdout) == {"reason": "capital_research_input_invalid"}
