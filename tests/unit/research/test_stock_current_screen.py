"""Fictional provider rows; declaration support does not establish native usability."""

import hashlib

import pytest

from tests.unit.research.test_stock_screen import NOW, sample
from trading_bot.config.stock_research import StockResearchSettings, StockWorkerSettings
from trading_bot.market_data.recording import canonical_json
from trading_bot.research.stock_screen import discovery_requests, screen_stocks

PROFILE = "stock-worker-current-provider-v1"
ADDED = {
    "P/FCF": "fundamental.pfcfRatio",
    "Total stockholders equity": "fundamental.totalStockEquity",
    "Assets/equity": "fundamental.totalAssetsEquityRatio",
    "Reporting currency": "fundamental.reportCurrency",
    "Provider close 20": 'close(candleCount=20, candlePeriod="1d", session="regular")',
    "Provider SMA 50": 'closeAvg(candleCount=50, candlePeriod="1d", session="regular")',
    "Quotation currency": "currency",
}


def current_sample():
    _, policy, rows = sample()
    rows[0]["arguments"] = discovery_requests(policy, worker_profile_id=PROFILE)[1]["arguments"]
    for row in rows[0]["payload"]["data"]["result"]["results"]:
        row["columns"].update(
            {
                "P/FCF": "20",
                "Total stockholders equity": "1000000000",
                "Assets/equity": "2",
                "Reporting currency": "JPY",
                "Provider close 20": "90",
                "Provider SMA 50": "95",
                "Quotation currency": "USD",
            }
        )
    return policy, rows


def test_opt_in_profile_has_declared_columns_with_same_17_call_budget():
    policy = StockResearchSettings()
    old = discovery_requests(policy)
    new = discovery_requests(policy, worker_profile_id=PROFILE)
    assert len(old) == len(new) == 17
    assert new[0] == old[0]
    for before, after in zip(old[1:], new[1:], strict=True):
        assert after["arguments"]["filters"] == before["arguments"]["filters"]
        assert after["arguments"]["columns"][:7] == before["arguments"]["columns"]
        assert after["arguments"]["columns"][7:] == [
            {"display_name": title, "expression": expression} for title, expression in ADDED.items()
        ]


def test_current_valuation_uses_positive_pfcf_not_currency_blind_per_share():
    policy, observations = current_sample()
    for row, pfcf in zip(
        observations[0]["payload"]["data"]["result"]["results"], ["10", "20", "40"], strict=True
    ):
        row["columns"]["P/FCF"] = pfcf
        row["columns"]["FCF/share"] = "99999999"
    report = screen_stocks(observations, policy=policy, as_of=NOW, worker_profile_id=PROFILE)
    assert report["worker_profile_id"] == PROFILE
    assert report["provider_price_basis"] == "current_provider_snapshot_not_completed_close"
    assert report["balance_sheet_date"] is None
    metrics = {row["symbol"]: row["metrics"] for row in report["opportunities"]}
    assert metrics["AAA"]["fcf_yield"] == "0.1"
    assert metrics["BBB"]["fcf_yield"] == "0.05"
    assert metrics["CCC"]["fcf_yield"] == "0.025"
    assert metrics["AAA"]["report_currency"] == "JPY"
    assert metrics["AAA"]["provider_close_20"] == "90"
    assert metrics["AAA"]["provider_sma_50"] == "95"
    assert metrics["AAA"]["total_stockholders_equity"] == "1000000000"
    assert all(row["investment_eligible"] is False for row in report["opportunities"])
    assert report["qualified"] is report["live_enabled"] is False


@pytest.mark.parametrize("pfcf", ["0", "-1", "", None, True, "NaN"])
def test_missing_or_nonpositive_pfcf_is_unscorable(pfcf):
    policy, observations = current_sample()
    observations[0]["payload"]["data"]["result"]["results"][0]["columns"]["P/FCF"] = pfcf
    report = screen_stocks(observations, policy=policy, as_of=NOW, worker_profile_id=PROFILE)
    assert "AAA" not in [row["symbol"] for row in report["opportunities"]]
    assert report["excluded"][0]["missing"] == ["fcf_yield"]


def test_missing_added_facts_stay_missing_without_invented_dates_or_currency():
    policy, observations = current_sample()
    cells = observations[0]["payload"]["data"]["result"]["results"][0]["columns"]
    for name in ADDED:
        if name != "P/FCF":
            cells.pop(name)
    report = screen_stocks(observations, policy=policy, as_of=NOW, worker_profile_id=PROFILE)
    row = next(row for row in report["opportunities"] if row["symbol"] == "AAA")
    assert all(
        row["metrics"][name] is None
        for name in (
            "report_currency",
            "quotation_currency",
            "total_stockholders_equity",
            "assets_to_equity",
            "provider_close_20",
            "provider_sma_50",
        )
    )
    assert "reported_debt" not in row["metrics"]
    assert "statement_period" not in row


def test_profile_cannot_relabel_legacy_capture_or_swapped_expressions():
    _, policy, observations = sample()
    with pytest.raises(ValueError, match="stock_screen_invalid"):
        screen_stocks(observations, policy=policy, as_of=NOW, worker_profile_id=PROFILE)
    policy, observations = current_sample()
    observations[0]["arguments"]["columns"][-1]["expression"] = "fundamental.commonStockEquity"
    with pytest.raises(ValueError, match="stock_screen_invalid"):
        screen_stocks(observations, policy=policy, as_of=NOW, worker_profile_id=PROFILE)


@pytest.mark.parametrize("profile", [None, True, "stock-worker-v2", "stock-research-v1"])
def test_unknown_profiles_fail_closed(profile):
    with pytest.raises(ValueError):
        discovery_requests(StockResearchSettings(), worker_profile_id=profile)


def test_legacy_default_preimages_remain_literal():
    module, policy, observations = sample()
    assert (
        hashlib.sha256(
            canonical_json(StockWorkerSettings().model_dump(mode="json")).encode()
        ).hexdigest()
        == "daa918c0cce4d3b12b9ac9898bd455079571b9b59afdedfc602dd3105d08f3d8"
    )
    assert (
        hashlib.sha256(
            canonical_json(discovery_requests(StockResearchSettings())).encode()
        ).hexdigest()
        == "7cbb4842bf35db11e483aac3239557ef1c7d0a2445a8acda14bb4679643933eb"
    )
    assert (
        hashlib.sha256(
            canonical_json(module.screen_stocks(observations, policy=policy, as_of=NOW)).encode()
        ).hexdigest()
        == "42f4b72b36491e01334f1eb5e208ec5a48b0c39345d39d1afa799e9d2163a589"
    )
    assert StockWorkerSettings(policy_id=PROFILE).policy_id == PROFILE
    assert len(StockWorkerSettings.model_fields) == 6


def test_current_profile_never_computes_discarded_currency_blind_division(monkeypatch):
    from trading_bot.research import stock_screen

    policy, observations = current_sample()
    original = stock_screen._ratio
    numerators = []

    def ratio(numerator, denominator):
        numerators.append(numerator)
        return original(numerator, denominator)

    monkeypatch.setattr(stock_screen, "_ratio", ratio)
    screen_stocks(observations, policy=policy, as_of=NOW, worker_profile_id=PROFILE)
    assert numerators and all(value == 1 for value in numerators)
