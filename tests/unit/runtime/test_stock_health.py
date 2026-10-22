"""Pure stock operations checks using complete fictional dashboard projections."""

import copy
import importlib
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)
CONFIG = "a" * 64
CODE = "b" * 64
MIB = 1024 * 1024


def evaluate(**observed):
    path = Path(__file__).resolve().parents[3] / "src/trading_bot/runtime/stock_health.py"
    assert path.is_file(), "The pure stock operations health evaluator is missing"
    return importlib.import_module("trading_bot.runtime.stock_health").evaluate_stock_health(
        **observed
    )


@pytest.fixture
def observed():
    claimed = NOW - timedelta(seconds=120)
    return {
        "expected_config_hash": CONFIG,
        "expected_code_hash": CODE,
        "control_status": "running",
        "timer_enabled": True,
        "timer_active": True,
        "worker_exit_code": 0,
        "projection": {
            "schema_version": 1,
            "kind": "stock_research_dashboard",
            "generated_at": NOW,
            "config_hash": CONFIG,
            "code_hash": CODE,
            "state_sha256": "c" * 64,
            "worker": {
                "last_claim_at": claimed,
                "last_result_at": NOW - timedelta(seconds=60),
                "phase": "discovery",
                "status": "succeeded",
                "reason": "complete",
                "pending_claims": 0,
                "reserved_today": 12,
                "daily_limit": 512,
                "remaining_calls": 500,
                "next_eligible_at": claimed + timedelta(seconds=3600),
            },
            "discovery": {
                "claimed_at": claimed,
                "as_of": NOW - timedelta(seconds=90),
                "report_sha256": "d" * 64,
                "manifest_sha256": "e" * 64,
                "candidate_count": 0,
                "scorable_count": 0,
                "opportunities": [],
            },
            "enrichment": None,
            "qualified": False,
            "investment_eligible": False,
            "live_enabled": False,
        },
        "backup_created_at": NOW - timedelta(hours=1),
        "offhost_copied_at": NOW - timedelta(minutes=30),
        "restore_verified_at": NOW - timedelta(days=1),
        "free_bytes": 200 * MIB,
        "free_inodes": 256,
        "now": NOW,
        "maximum_source_age_seconds": 7200,
        "scan_interval_seconds": 3600,
    }


def old_worker(observed, *, seconds):
    claim = NOW - timedelta(seconds=seconds)
    worker = observed["projection"]["worker"]
    worker.update(
        last_claim_at=claim,
        last_result_at=claim + timedelta(seconds=30),
        next_eligible_at=claim + timedelta(seconds=3600),
    )
    observed["projection"]["discovery"].update(
        claimed_at=claim, as_of=claim + timedelta(seconds=20)
    )


def test_verified_current_acquisition_with_valid_empty_rankings_is_healthy(observed):
    assert evaluate(**observed) == ()


def test_nonempty_valid_research_remains_healthy_without_financial_claims(observed):
    discovery = observed["projection"]["discovery"]
    discovery.update(candidate_count=10, scorable_count=1)
    discovery["opportunities"] = [
        {
            "symbol": "EXAMPLE",
            "research_priority_score": "50",
            "available_at": discovery["as_of"],
            "source_observation_sha256": "f" * 64,
            "metrics": dict.fromkeys(
                (
                    "roe",
                    "net_margin",
                    "annual_eps_growth",
                    "quarterly_revenue_growth",
                    "earnings_yield",
                    "fcf_yield",
                )
            ),
        }
    ]
    assert evaluate(**observed) == ()


@pytest.mark.parametrize("field", ["config_hash", "code_hash"])
def test_projection_identity_cannot_be_adopted_from_another_release(observed, field):
    observed["projection"][field] = "f" * 64
    assert evaluate(**observed) == ("projection_identity_mismatch",)


@pytest.mark.parametrize(
    "path,replacement",
    [
        (("schema_version",), True),
        (("kind",), "other"),
        (("live_enabled",), True),
        (("qualified",), True),
        (("investment_eligible",), True),
        (("state_sha256",), "wrong"),
        (("generated_at",), NOW + timedelta(microseconds=1)),
        (("generated_at",), NOW.replace(tzinfo=None)),
        (("generated_at",), NOW.isoformat()),
        (("worker", "status"), "healthy"),
        (("worker", "remaining_calls"), 501),
        (("worker", "pending_claims"), True),
        (("worker", "next_eligible_at"), NOW + timedelta(days=365)),
        (("worker", "last_result_at"), NOW + timedelta(seconds=1)),
        (("worker", "last_claim_at"), NOW + timedelta(seconds=1)),
        (("discovery", "candidate_count"), -1),
        (("discovery", "manifest_sha256"), "latest"),
        (("discovery", "as_of"), NOW + timedelta(seconds=1)),
        (("discovery", "claimed_at"), NOW - timedelta(seconds=110)),
        (("extra",), "untrusted"),
    ],
)
def test_complete_strict_projection_validation_denies_false_health(observed, path, replacement):
    target = observed["projection"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    assert evaluate(**observed) == ("projection_invalid",)


@pytest.mark.parametrize("field", ["worker", "discovery", "generated_at", "live_enabled"])
def test_omitted_projection_fields_cannot_clear_incidents(observed, field):
    del observed["projection"][field]
    assert evaluate(**observed) == ("projection_invalid",)


def test_missing_projection_and_missing_acquisition_are_distinct(observed):
    observed["projection"] = None
    assert evaluate(**observed) == ("projection_missing",)
    observed["projection"] = {}
    assert evaluate(**observed) == ("projection_invalid",)


def test_success_without_retained_discovery_is_not_acquisition_success(observed):
    observed["projection"]["discovery"] = None
    assert evaluate(**observed) == ("acquisition_missing",)


def test_never_run_does_not_become_healthy_from_launcher_exit_zero(observed):
    observed["projection"]["worker"].update(
        last_claim_at=None,
        last_result_at=None,
        phase=None,
        status="never_run",
        reason=None,
        pending_claims=0,
        reserved_today=0,
        remaining_calls=512,
        next_eligible_at=None,
    )
    observed["projection"]["discovery"] = None
    assert evaluate(**observed) == ("acquisition_missing", "worker_never_run")


@pytest.mark.parametrize("code", [1, 2, 137, 143, 255])
def test_actual_nonzero_worker_exit_is_failure(observed, code):
    observed["worker_exit_code"] = code
    assert evaluate(**observed) == ("worker_exit_failed",)


def test_unknown_worker_exit_cannot_be_inferred_from_successful_projection(observed):
    observed["worker_exit_code"] = None
    assert evaluate(**observed) == ("worker_exit_unknown",)


@pytest.mark.parametrize(
    "status,reason",
    [("blocked", "auth_unavailable"), ("failed", "runtime_failure"), ("cancelled", "cancelled")],
)
def test_failed_acquisition_cannot_be_hidden_by_launcher_zero(observed, status, reason):
    observed["projection"]["worker"].update(status=status, reason=reason)
    assert evaluate(**observed) == ("worker_failed",)


@pytest.mark.parametrize(
    "field,incident", [("timer_enabled", "timer_disabled"), ("timer_active", "timer_inactive")]
)
def test_running_collector_requires_both_timer_states(observed, field, incident):
    observed[field] = False
    assert evaluate(**observed) == (incident,)


def test_reexport_does_not_refresh_original_source_clock(observed):
    discovery = observed["projection"]["discovery"]
    discovery.update(claimed_at=NOW - timedelta(seconds=7201), as_of=NOW - timedelta(seconds=90))
    assert evaluate(**observed) == ("source_stale",)


def test_old_source_as_of_is_stale_even_when_claim_and_export_are_recent(observed):
    # The full schema rejects an impossible report predating its own claim.
    observed["projection"]["discovery"]["as_of"] = NOW - timedelta(seconds=7201)
    assert evaluate(**observed) == ("projection_invalid",)


def test_original_opportunity_receipt_age_cannot_be_renewed_by_report_clock(observed):
    discovery = observed["projection"]["discovery"]
    discovery.update(claimed_at=NOW - timedelta(seconds=7201), candidate_count=1, scorable_count=1)
    discovery["opportunities"] = [
        {
            "symbol": "EXAMPLE",
            "research_priority_score": "50",
            "available_at": NOW - timedelta(seconds=7201),
            "source_observation_sha256": "f" * 64,
            "metrics": dict.fromkeys(
                (
                    "roe",
                    "net_margin",
                    "annual_eps_growth",
                    "quarterly_revenue_growth",
                    "earnings_yield",
                    "fcf_yield",
                )
            ),
        }
    ]
    assert evaluate(**observed) == ("source_stale",)


def test_stale_enrichment_cannot_hide_behind_fresh_discovery(observed):
    observed["projection"]["enrichment"] = {
        "claimed_at": NOW - timedelta(seconds=7201),
        "as_of": NOW - timedelta(seconds=7100),
        "report_sha256": "d" * 64,
        "manifest_sha256": "e" * 64,
        "dossiers": [],
    }
    assert evaluate(**observed) == ("source_stale",)


def test_worker_cadence_uses_claim_and_result_clocks_not_export_generation(observed):
    old_worker(observed, seconds=5401)
    assert evaluate(**observed) == ("worker_claim_stale", "worker_result_stale")


def test_completion_relative_cadence_allows_previous_and_current_finite_run_budgets(observed):
    old_worker(observed, seconds=4500)
    observed["projection"]["worker"]["last_result_at"] = NOW - timedelta(seconds=4050)
    assert evaluate(**observed) == ()


@pytest.mark.parametrize("seconds,incident", [(450, ()), (451, ("worker_pending_stuck",))])
def test_pending_claim_expires_after_fixed_worker_budget(observed, seconds, incident):
    worker = observed["projection"]["worker"]
    worker.update(
        last_claim_at=NOW - timedelta(seconds=seconds),
        status="pending",
        reason=None,
        last_result_at=NOW - timedelta(seconds=600),
        pending_claims=1,
        next_eligible_at=NOW + timedelta(seconds=3600 - seconds),
    )
    observed["projection"]["discovery"].update(
        claimed_at=NOW - timedelta(seconds=800), as_of=NOW - timedelta(seconds=700)
    )
    assert evaluate(**observed) == incident


def test_daily_budget_depletion_is_information_and_never_hides_stale_sources(observed):
    old_worker(observed, seconds=6000)
    observed["projection"]["worker"].update(reserved_today=512, remaining_calls=0)
    assert evaluate(**observed) == ()
    observed["projection"]["discovery"]["claimed_at"] = NOW - timedelta(seconds=7201)
    assert evaluate(**observed) == ("source_stale",)


def test_yesterdays_budget_does_not_suppress_current_day_cadence_failure(observed):
    old_worker(observed, seconds=86400)
    observed["projection"]["worker"].update(reserved_today=512, remaining_calls=0)
    assert evaluate(**observed) == ("source_stale", "worker_claim_stale", "worker_result_stale")


@pytest.mark.parametrize("status", ["paused", "killed"])
def test_intentionally_stopped_collection_does_not_alarm_for_expected_inactivity(observed, status):
    observed.update(
        control_status=status, timer_enabled=False, timer_active=False, worker_exit_code=2
    )
    old_worker(observed, seconds=90000)
    observed["projection"]["worker"].update(status="blocked", reason="control_denied")
    assert evaluate(**observed) == ()
    observed["projection"]["live_enabled"] = True
    assert evaluate(**observed) == ("projection_invalid",)


@pytest.mark.parametrize("status", ["paused", "killed"])
def test_paused_or_killed_still_detects_storage_and_backup_failures(observed, status):
    observed.update(control_status=status, free_bytes=0, free_inodes=0, backup_created_at=None)
    assert evaluate(**observed) == ("backup_missing", "storage_bytes_low", "storage_inodes_low")


@pytest.mark.parametrize(
    "field,threshold,incident",
    [
        ("free_bytes", 100 * MIB, "storage_bytes_low"),
        ("free_inodes", 128, "storage_inodes_low"),
    ],
)
def test_fixed_research_storage_floor_is_inclusive(observed, field, threshold, incident):
    observed[field] = threshold
    assert evaluate(**observed) == ()
    observed[field] -= 1
    assert evaluate(**observed) == (incident,)


@pytest.mark.parametrize(
    "field,prefix,hours",
    [
        ("backup_created_at", "backup", 26),
        ("offhost_copied_at", "offhost_copy", 26),
        ("restore_verified_at", "restore", 8 * 24),
    ],
)
def test_backup_copy_and_restore_require_actual_recent_successes(observed, field, prefix, hours):
    observed[field] = NOW - timedelta(hours=hours)
    assert evaluate(**observed) == ()
    observed[field] -= timedelta(microseconds=1)
    assert evaluate(**observed) == (prefix + "_stale",)
    observed[field] = None
    assert evaluate(**observed) == (prefix + "_missing",)


@pytest.mark.parametrize(
    "field,prefix",
    [
        ("backup_created_at", "backup"),
        ("offhost_copied_at", "offhost_copy"),
        ("restore_verified_at", "restore"),
    ],
)
@pytest.mark.parametrize(
    "stamp",
    [
        NOW + timedelta(microseconds=1),
        NOW.replace(tzinfo=None),
        NOW.isoformat(),
        False,
        NOW.astimezone(timezone(timedelta(hours=1))),
    ],
)
def test_unknown_or_future_success_times_never_count_as_recent(observed, field, prefix, stamp):
    observed[field] = stamp
    assert evaluate(**observed) == (prefix + "_invalid",)


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_config_hash", "A" * 64),
        ("expected_code_hash", None),
        ("control_status", "unknown"),
        ("control_status", False),
        ("timer_enabled", 1),
        ("timer_active", None),
        ("worker_exit_code", False),
        ("worker_exit_code", -1),
        ("worker_exit_code", 256),
        ("free_bytes", False),
        ("free_bytes", -1),
        ("free_bytes", 2**63),
        ("free_inodes", 128.0),
        ("free_inodes", -1),
        ("maximum_source_age_seconds", True),
        ("maximum_source_age_seconds", 59),
        ("maximum_source_age_seconds", 86401),
        ("maximum_source_age_seconds", 3600),
        ("scan_interval_seconds", 899),
        ("scan_interval_seconds", 3601),
        ("scan_interval_seconds", 901),
        ("now", NOW.replace(tzinfo=None)),
        ("now", NOW.isoformat()),
    ],
)
def test_malformed_observations_return_a_closed_uncertainty_code(observed, field, value):
    observed[field] = value
    assert evaluate(**observed) == ("observation_invalid",)


def test_incidents_are_closed_sorted_unique_and_evaluation_does_not_mutate_inputs(observed):
    observed.update(
        timer_enabled=False,
        timer_active=False,
        worker_exit_code=2,
        free_bytes=0,
        free_inodes=0,
        backup_created_at=None,
        offhost_copied_at=None,
        restore_verified_at=None,
    )
    observed["projection"]["worker"].update(status="blocked", reason="auth_unavailable")
    observed["projection"]["discovery"] = None
    before = copy.deepcopy(observed)
    assert evaluate(**observed) == (
        "acquisition_missing",
        "backup_missing",
        "offhost_copy_missing",
        "restore_missing",
        "storage_bytes_low",
        "storage_inodes_low",
        "timer_disabled",
        "timer_inactive",
        "worker_exit_failed",
        "worker_failed",
    )
    assert observed == before
