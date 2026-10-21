import importlib
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from trading_bot.config.stock_research import StockResearchSettings

NOW = datetime(2026, 10, 21, 16, tzinfo=UTC)
SHA = "a" * 64


def sample():
    module = importlib.import_module("trading_bot.research.stock_screen")
    policy = StockResearchSettings(market_cap_boundaries_usd=(Decimal(2000000000),))
    request = module.discovery_requests(policy)[1]
    rows = []
    for i, symbol in enumerate(["AAA", "BBB", "CCC"]):
        rows.append(
            {
                "ticker": symbol,
                "instrument_id": f"instrument-{symbol}",
                "instrument_type": "EQUITY",
                "columns": {
                    "Asset type": "STOCK",
                    "Last": "100",
                    "Market cap": "5000000000",
                    module.TURNOVER_COLUMN.format(sessions=30): "30000000",
                    "Sector": "Technology",
                    "Return on equity": str(Decimal("0.1") * (i + 1)),
                    "Net profit margin": str(Decimal("0.1") * (i + 1)),
                    "Annual EPS growth": str(Decimal("0.1") * (i + 1)),
                    "Quarterly revenue growth": str(Decimal("0.1") * (i + 1)),
                    "P/E": str(30 - i * 10),
                    "FCF/share": str(i + 1),
                },
            }
        )
    echoed = []
    for f in request["arguments"]["filters"]:
        e = deepcopy(f)
        if "filter_type" in e:
            e["filter_type_enum"] = e["filter_type"]
        else:
            e["filter_type_enum"] = "FILTER_TYPE_CUSTOM"
            e["filter_type"] = "Custom"
        echoed.append(e)
    observation = {
        "tool": "preview_scan",
        "arguments": request["arguments"],
        "received_at": NOW.isoformat(),
        "observation_sha256": SHA,
        "payload": {
            "data": {
                "result": {"total_items": len(rows), "results": rows, "filters_applied": echoed}
            }
        },
    }
    return module, policy, [observation]


def test_complete_screen_ranks_research_priority_without_investment_authority():
    module, policy, observations = sample()
    report = module.screen_stocks(observations, policy=policy, as_of=NOW)
    assert report["coverage_complete"] is True
    assert report["candidate_count"] == 3
    assert [r["symbol"] for r in report["opportunities"]] == ["CCC", "BBB", "AAA"]
    assert report["qualified"] is report["live_enabled"] is False
    assert report["opportunities"][0]["investment_eligible"] is False
    assert "expected_return" not in str(report)
    assert report["snapshot_atomic"] is False
    assert report["opportunities"][0]["source_observation_sha256"] == SHA


def test_truncated_prefix_never_produces_global_ranking():
    module, policy, observations = sample()
    observations[0]["payload"]["data"]["result"]["total_items"] = 400
    report = module.screen_stocks(observations, policy=policy, as_of=NOW)
    assert report["coverage_complete"] is False
    assert report["opportunities"] == []
    assert "truncated_partition" in report["coverage_issues"]


@pytest.mark.parametrize(
    "field,value", [("P/E", ""), ("Return on equity", "NaN"), ("Last", "0"), ("Asset type", "ETF")]
)
def test_missing_or_invalid_metrics_never_fabricated(field, value):
    module, policy, observations = sample()
    observations[0]["payload"]["data"]["result"]["results"][0]["columns"][field] = value
    if field in ("Last", "Asset type"):
        with pytest.raises(ValueError):
            module.screen_stocks(observations, policy=policy, as_of=NOW)
    else:
        report = module.screen_stocks(observations, policy=policy, as_of=NOW)
        assert "AAA" not in [r["symbol"] for r in report["opportunities"]]
        assert report["excluded"][0]["symbol"] == "AAA"


def test_future_stale_or_unmatched_filter_cannot_rank():
    module, policy, observations = sample()
    with pytest.raises(ValueError):
        module.screen_stocks(observations, policy=policy, as_of=NOW.replace(hour=15))
    stale = module.screen_stocks(observations, policy=policy, as_of=NOW.replace(hour=19))
    assert not stale["coverage_complete"]
    assert stale["opportunities"] == []
    observations[0]["payload"]["data"]["result"]["filters_applied"].pop()
    with pytest.raises(ValueError):
        module.screen_stocks(observations, policy=policy, as_of=NOW)


def test_missed_partition_and_repeated_partition_are_explicit():
    module, policy, observations = sample()
    other = policy.model_copy(
        update={"market_cap_boundaries_usd": (Decimal(2000000000), Decimal(10000000000))}
    )
    report = module.screen_stocks(observations, policy=other, as_of=NOW)
    assert not report["coverage_complete"]
    assert report["opportunities"] == []
    with pytest.raises(ValueError):
        module.screen_stocks(observations * 2, policy=policy, as_of=NOW)


def test_signed_fundamental_values_remain_signed_and_ties_are_deterministic():
    module, policy, observations = sample()
    for row in observations[0]["payload"]["data"]["result"]["results"]:
        row["columns"]["Annual EPS growth"] = "-0.5"
    report = module.screen_stocks(observations, policy=policy, as_of=NOW)
    assert report["opportunities"][0]["metrics"]["annual_eps_growth"] == "-0.5"
    assert [r["symbol"] for r in report["opportunities"]] == ["CCC", "BBB", "AAA"]


@pytest.mark.parametrize(
    "mutation", ["negative_expression", "missing_columns", "swapped_expressions"]
)
def test_column_identity_cannot_change_factor_meaning(mutation):
    module, policy, observations = sample()
    args = observations[0]["arguments"]
    if mutation == "negative_expression":
        args["columns"][0]["expression"] = "-fundamental.returnOnEquity"
    elif mutation == "missing_columns":
        args.pop("columns")
    else:
        args["columns"][0]["expression"], args["columns"][1]["expression"] = (
            args["columns"][1]["expression"],
            args["columns"][0]["expression"],
        )
    with pytest.raises(ValueError):
        module.screen_stocks(observations, policy=policy, as_of=NOW)


@pytest.mark.parametrize("value", ["1e999999999", "1e-1000000", "-1e999999999", "1e-500"])
def test_extreme_decimal_factors_cannot_escape_or_rank(value):
    module, policy, observations = sample()
    observations[0]["payload"]["data"]["result"]["results"][0]["columns"]["P/E"] = value
    report = module.screen_stocks(observations, policy=policy, as_of=NOW)
    assert "AAA" not in [row["symbol"] for row in report["opportunities"]]
