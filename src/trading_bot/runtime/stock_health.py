"""Pure stock operations incident evaluation; no I/O or execution authority.

Inputs are observations, not proof of their origin. The owner must bind source,
release and success receipts independently. Missing/invalid observations must not
clear retained incidents in the caller's durable spool. A valid empty research
ranking says nothing about investment eligibility or strategy performance.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from trading_bot.clock import require_utc
from trading_bot.research.stock_dashboard import StockDashboardExport

_RUN_SECONDS = 450
_MINIMUM_BYTES = 100 * 1024 * 1024
_MINIMUM_INODES = 128

STOCK_HEALTH_INCIDENTS = frozenset(
    {
        "observation_invalid",
        "projection_missing",
        "projection_invalid",
        "projection_identity_mismatch",
        "timer_disabled",
        "timer_inactive",
        "worker_exit_unknown",
        "worker_exit_failed",
        "worker_failed",
        "worker_never_run",
        "worker_pending_stuck",
        "worker_claim_stale",
        "worker_result_stale",
        "acquisition_missing",
        "source_stale",
        "storage_bytes_low",
        "storage_inodes_low",
        "backup_missing",
        "backup_stale",
        "backup_invalid",
        "offhost_copy_missing",
        "offhost_copy_stale",
        "offhost_copy_invalid",
        "restore_missing",
        "restore_stale",
        "restore_invalid",
    }
)


def _digest(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _integer(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _success_time(
    incidents: set[str], *, prefix: str, at: datetime | None, now: datetime, maximum_hours: int
) -> None:
    if at is None:
        incidents.add(prefix + "_missing")
        return
    try:
        at = require_utc(at)
        if at > now:
            raise ValueError
        if now - at > timedelta(hours=maximum_hours):
            incidents.add(prefix + "_stale")
    except (ValueError, TypeError, OverflowError):
        incidents.add(prefix + "_invalid")


def _projection(
    value: dict[str, Any], *, now: datetime, scan_interval_seconds: int
) -> StockDashboardExport:
    if type(value) is not dict:
        raise ValueError
    export = StockDashboardExport.model_validate(value)
    worker = export.worker
    if export.generated_at > now:
        raise ValueError
    if worker.last_claim_at is not None:
        if worker.next_eligible_at != worker.last_claim_at + timedelta(
            seconds=scan_interval_seconds
        ):
            raise ValueError
        if any(
            section is not None and section.claimed_at > worker.last_claim_at
            for section in (export.discovery, export.enrichment)
        ):
            raise ValueError
        if (
            worker.status == "pending"
            and worker.last_result_at is not None
            and worker.last_result_at > worker.last_claim_at
        ):
            raise ValueError
    return export


def _research(
    incidents: set[str],
    *,
    export: StockDashboardExport,
    now: datetime,
    maximum_source_age_seconds: int,
    scan_interval_seconds: int,
) -> None:
    worker = export.worker
    if worker.status in {"blocked", "failed", "cancelled"}:
        incidents.add("worker_failed")
    if worker.status == "never_run":
        incidents.add("worker_never_run")
    if (
        worker.pending_claims
        and worker.last_claim_at is not None
        and (now - worker.last_claim_at).total_seconds() > _RUN_SECONDS
    ):
        incidents.add("worker_pending_stuck")

    # A valid current-day exhausted budget explains an expected gap in cadence.
    # It never makes absent/stale evidence or a failed worker healthy.
    exhausted = (
        worker.remaining_calls == 0
        and export.generated_at.date() == now.date()
        and worker.status not in {"never_run", "pending"}
        and worker.last_result_at is not None
        and worker.last_result_at.date() == now.date()
    )
    if not exhausted and worker.status != "pending":
        # Completion-relative cadence permits the preceding finite run and the
        # current finite run before a new completed projection is available.
        if (
            worker.last_claim_at is not None
            and (now - worker.last_claim_at).total_seconds()
            > scan_interval_seconds + 2 * _RUN_SECONDS
        ):
            incidents.add("worker_claim_stale")
        if (
            worker.last_result_at is not None
            and (now - worker.last_result_at).total_seconds() > scan_interval_seconds + _RUN_SECONDS
        ):
            incidents.add("worker_result_stale")

    if export.discovery is None:
        incidents.add("acquisition_missing")
    times: list[datetime] = []
    for section in (export.discovery, export.enrichment):
        if section is not None:
            times.extend((section.claimed_at, section.as_of))
    if export.discovery is not None:
        times.extend(row.available_at for row in export.discovery.opportunities)
    if any((now - at).total_seconds() > maximum_source_age_seconds for at in times):
        incidents.add("source_stale")


def evaluate_stock_health(
    *,
    expected_config_hash: str,
    expected_code_hash: str,
    control_status: str,
    timer_enabled: bool,
    timer_active: bool,
    worker_exit_code: int | None,
    projection: dict[str, Any] | None,
    backup_created_at: datetime | None,
    offhost_copied_at: datetime | None,
    restore_verified_at: datetime | None,
    free_bytes: int,
    free_inodes: int,
    now: datetime,
    maximum_source_age_seconds: int,
    scan_interval_seconds: int,
) -> tuple[str, ...]:
    """Return only closed, sorted incident codes from independently obtained facts.

    Projection dictionaries use Python-mode UTC datetimes. The observer can first
    parse saved JSON through StockDashboardExport.model_validate_json().model_dump().
    This function revalidates the entire projection and never renews source times.
    Intentionally paused/killed controls suppress expected acquisition inactivity;
    projection validity, backup freshness and storage remain checked.
    """
    if not (
        _digest(expected_config_hash)
        and _digest(expected_code_hash)
        and type(control_status) is str
        and control_status in {"running", "paused", "killed"}
        and type(timer_enabled) is bool
        and type(timer_active) is bool
        and (worker_exit_code is None or _integer(worker_exit_code, 0, 255))
        and _integer(free_bytes, 0, 2**63 - 1)
        and _integer(free_inodes, 0, 2**63 - 1)
        and _integer(maximum_source_age_seconds, 60, 86400)
        and _integer(scan_interval_seconds, 900, 3600)
        and scan_interval_seconds % 60 == 0
        and maximum_source_age_seconds > scan_interval_seconds
    ):
        return ("observation_invalid",)
    try:
        now = require_utc(now)
    except (ValueError, TypeError, OverflowError):
        return ("observation_invalid",)

    incidents: set[str] = set()
    if free_bytes < _MINIMUM_BYTES:
        incidents.add("storage_bytes_low")
    if free_inodes < _MINIMUM_INODES:
        incidents.add("storage_inodes_low")
    for prefix, at, hours in (
        ("backup", backup_created_at, 26),
        ("offhost_copy", offhost_copied_at, 26),
        ("restore", restore_verified_at, 8 * 24),
    ):
        _success_time(incidents, prefix=prefix, at=at, now=now, maximum_hours=hours)

    export = None
    if projection is None:
        incidents.add("projection_missing")
    else:
        try:
            export = _projection(projection, now=now, scan_interval_seconds=scan_interval_seconds)
        except (ValueError, TypeError, OverflowError, RecursionError, AttributeError):
            incidents.add("projection_invalid")
    if export is not None and (
        export.config_hash != expected_config_hash or export.code_hash != expected_code_hash
    ):
        incidents.add("projection_identity_mismatch")
        export = None
    if control_status == "running":
        if not timer_enabled:
            incidents.add("timer_disabled")
        if not timer_active:
            incidents.add("timer_inactive")
        if worker_exit_code is None:
            incidents.add("worker_exit_unknown")
        elif worker_exit_code != 0:
            incidents.add("worker_exit_failed")
        if export is not None:
            _research(
                incidents,
                export=export,
                now=now,
                maximum_source_age_seconds=maximum_source_age_seconds,
                scan_interval_seconds=scan_interval_seconds,
            )
    return tuple(sorted(incidents))
