"""Bounded descriptive exports cannot turn missing/stale data into authority."""

from datetime import UTC, datetime, timedelta

import pytest

from trading_bot.research.stock_dashboard import (
    StockDashboardExport,
    present_stock_dashboard,
    unavailable_stock_dashboard,
)

NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)


def document():
    return {
        "schema_version": 1,
        "kind": "stock_research_dashboard",
        "generated_at": NOW,
        "config_hash": "a" * 64,
        "code_hash": "b" * 64,
        "state_sha256": "c" * 64,
        "worker": {
            "last_claim_at": NOW - timedelta(minutes=1),
            "last_result_at": NOW,
            "phase": "discovery",
            "status": "succeeded",
            "reason": "complete",
            "pending_claims": 0,
            "reserved_today": 17,
            "daily_limit": 512,
            "remaining_calls": 495,
            "next_eligible_at": NOW + timedelta(minutes=59),
        },
        "discovery": {
            "claimed_at": NOW - timedelta(minutes=1),
            "as_of": NOW,
            "report_sha256": "d" * 64,
            "manifest_sha256": "e" * 64,
            "candidate_count": 1,
            "scorable_count": 1,
            "opportunities": [
                {
                    "symbol": "ALFA",
                    "research_priority_score": "75.25",
                    "available_at": NOW - timedelta(seconds=30),
                    "source_observation_sha256": "f" * 64,
                    "metrics": {
                        "roe": "0.2",
                        "net_margin": "0.1",
                        "annual_eps_growth": "0.3",
                        "quarterly_revenue_growth": "0.2",
                        "earnings_yield": "0.05",
                        "fcf_yield": None,
                    },
                }
            ],
        },
        "enrichment": None,
        "qualified": False,
        "investment_eligible": False,
        "live_enabled": False,
    }


def test_projection_preserves_source_times_missing_facts_and_false_flags():
    export = StockDashboardExport.model_validate(document())
    view = present_stock_dashboard(export, now=NOW, maximum_age_seconds=7200)
    row = view["opportunities"][0]
    assert row["research_priority_score"] == "75.25"
    assert row["available_at"] == (NOW - timedelta(seconds=30)).isoformat()
    assert row["metrics"]["fcf_yield"] is None
    assert row["dossier_as_of"] is None
    assert row["gaps"] == ["deeper_research_pending"]
    assert view["stock_worker"]["reserved_today"] == 17
    assert view["stock_worker"]["remaining_calls"] == 495
    assert view["stock_worker"]["control_scope"] == "separate"
    assert view["qualified"] is view["investment_eligible"] is view["live_enabled"] is False


def test_stale_export_or_future_clock_suppresses_all_opportunities():
    export = StockDashboardExport.model_validate(document())
    for now, reason in [
        (NOW + timedelta(seconds=7201), "stale_export"),
        (NOW - timedelta(seconds=1), "future_export"),
    ]:
        view = present_stock_dashboard(export, now=now, maximum_age_seconds=7200)
        assert view["opportunities"] == []
        assert view["stock_worker"]["status"] == "unavailable"
        assert view["stock_worker"]["reason"] == reason
        assert view["stock_worker"]["reserved_today"] is None


def test_current_export_cannot_relabel_old_discovery_as_fresh():
    value = document()
    value["generated_at"] = NOW + timedelta(seconds=7200)
    export = StockDashboardExport.model_validate(value)
    view = present_stock_dashboard(
        export, now=NOW + timedelta(seconds=7200), maximum_age_seconds=7200
    )
    assert view["opportunities"] == []
    assert view["stock_worker"]["reason"] == "complete"
    assert view["sources"][0]["status"] == "stale"
    assert view["sources"][0]["as_of"] == NOW.isoformat()


def test_enrichment_gaps_only_join_matching_fresh_company():
    value = document()
    value["enrichment"] = {
        "claimed_at": NOW - timedelta(seconds=20),
        "as_of": NOW,
        "report_sha256": "1" * 64,
        "manifest_sha256": "2" * 64,
        "dossiers": [{"symbol": "ALFA", "gaps": ["history_interpolation_unknown"]}],
    }
    export = StockDashboardExport.model_validate(value)
    row = present_stock_dashboard(export, now=NOW, maximum_age_seconds=7200)["opportunities"][0]
    assert row["gaps"] == ["history_interpolation_unknown"]
    assert row["dossier_as_of"] == NOW.isoformat()


@pytest.mark.parametrize(
    "change", ["true", "zero", "nan", "future", "budget", "duplicate", "extra", "bool_version"]
)
def test_invalid_export_is_rejected_without_coercion(change):
    value = document()
    if change == "true":
        value["live_enabled"] = True
    elif change == "zero":
        value["qualified"] = 0
    elif change == "nan":
        value["discovery"]["opportunities"][0]["research_priority_score"] = "NaN"
    elif change == "future":
        value["discovery"]["opportunities"][0]["available_at"] = NOW + timedelta(seconds=1)
    elif change == "budget":
        value["worker"]["remaining_calls"] = 512
    elif change == "duplicate":
        value["discovery"]["opportunities"] *= 2
    elif change == "extra":
        value["private_account"] = "must-never-be-exported"
    else:
        value["schema_version"] = True
    with pytest.raises(ValueError):
        StockDashboardExport.model_validate(value)


def test_revalidation_rejects_model_copy_bypass_and_unknown_unavailable_reason():
    export = StockDashboardExport.model_validate(document()).model_copy(
        update={"live_enabled": True}
    )
    with pytest.raises(ValueError):
        present_stock_dashboard(export, now=NOW, maximum_age_seconds=7200)
    with pytest.raises(ValueError):
        unavailable_stock_dashboard("raw-provider-text")


def test_unavailable_budget_is_unknown_and_contains_no_claimed_results():
    view = unavailable_stock_dashboard("export_unavailable")
    assert view["opportunities"] == view["sources"] == []
    assert view["stock_worker"]["reserved_today"] is None
    assert view["stock_worker"]["pending_claims"] is None
    assert view["stock_worker"]["live_enabled"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"last_result_at": None, "reason": None},
        {"reason": "auth_unavailable"},
        {"status": "failed", "reason": "complete"},
        {"last_result_at": NOW - timedelta(hours=1)},
    ],
)
def test_terminal_status_must_match_a_result_after_its_claim(changes):
    value = document()
    value["worker"].update(changes)
    with pytest.raises(ValueError):
        StockDashboardExport.model_validate(value)


def test_never_run_cannot_supply_discovery_evidence():
    value = document()
    value["worker"] = {
        "last_claim_at": None,
        "last_result_at": None,
        "phase": None,
        "status": "never_run",
        "reason": None,
        "pending_claims": 0,
        "reserved_today": 0,
        "daily_limit": 512,
        "remaining_calls": 512,
        "next_eligible_at": None,
    }
    with pytest.raises(ValueError):
        StockDashboardExport.model_validate(value)


def test_raw_escaped_secret_is_rejected_before_json_encoding(monkeypatch):
    from trading_bot.research import stock_dashboard as module

    value = document()
    marker = "987654\n"
    value["discovery"]["opportunities"][0]["metrics"]["roe"] = marker
    monkeypatch.setattr(module, "contains_registered_secret", lambda text: marker in text)
    with pytest.raises(ValueError):
        StockDashboardExport.model_validate(value)


def test_presentation_rechecks_raw_values_after_registry_changes(monkeypatch):
    from trading_bot.research import stock_dashboard as module

    value = document()
    marker = "987654"
    value["discovery"]["opportunities"][0]["metrics"]["roe"] = marker
    export = StockDashboardExport.model_validate(value)
    monkeypatch.setattr(module, "contains_registered_secret", lambda text: marker in text)
    with pytest.raises(ValueError):
        present_stock_dashboard(export, now=NOW, maximum_age_seconds=7200)


def test_decimal_projection_uses_exact_plain_text_accepted_by_dashboard():
    value = document()
    value["discovery"]["opportunities"][0]["metrics"]["roe"] = "-3E-7"
    value["discovery"]["opportunities"][0]["research_priority_score"] = "1E+2"
    export = StockDashboardExport.model_validate(value)
    row = present_stock_dashboard(export, now=NOW, maximum_age_seconds=7200)["opportunities"][0]
    assert row["metrics"]["roe"] == "-0.0000003"
    assert row["research_priority_score"] == "100"


def test_stale_source_does_not_replace_actual_worker_failure_reason():
    value = document()
    value["generated_at"] = NOW + timedelta(hours=3)
    value["worker"].update(
        {
            "last_claim_at": NOW + timedelta(hours=2),
            "last_result_at": NOW + timedelta(hours=3),
            "next_eligible_at": NOW + timedelta(hours=3),
            "status": "blocked",
            "reason": "auth_unavailable",
        }
    )
    export = StockDashboardExport.model_validate(value)
    view = present_stock_dashboard(export, now=value["generated_at"], maximum_age_seconds=7200)
    assert view["stock_worker"]["reason"] == "auth_unavailable"
    assert view["sources"][0]["status"] == "stale"
    assert view["opportunities"] == []


def test_metric_text_boundary_is_stable_under_storage_revalidation():
    value = document()
    value["discovery"]["opportunities"][0]["metrics"]["roe"] = "1E-126"
    first = StockDashboardExport.model_validate(value)
    assert len(first.discovery.opportunities[0].metrics.roe) == 128
    assert StockDashboardExport.model_validate(first.model_dump()) == first
