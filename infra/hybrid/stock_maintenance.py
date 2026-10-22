"""Fixed stock operations coordinator; local incidents and encrypted backup only.

The separately locked, root-owned maintenance runtime is required. No credential,
provider, trade, control mutation, research restart or external alert is exposed.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from infra.hybrid.stock_attempts import AttemptStore, _stopped, operations
from infra.hybrid.stock_backup import backup_stock
from infra.hybrid.stock_engine import StockEngineReader
from infra.hybrid.stock_maintenance_process import helper_invocation, run_local_helper
from infra.hybrid.stock_process import _capture
from infra.hybrid.stock_release import StockRelease, load_release
from infra.hybrid.stock_units import unit_files
from trading_bot.research.stock_dashboard import StockDashboardExport
from trading_bot.runtime.stock_dashboard_export import _policy
from trading_bot.runtime.stock_health import evaluate_stock_health
from trading_bot.runtime.stock_incidents import StockIncidentSpool
from trading_bot.runtime.stock_research_controls import StockControlRecord, _encode
from trading_bot.runtime.stock_research_worker import load_stock_worker_configuration

_ROOT = Path("/var/lib/hybrid-stock-research")
_MAINTENANCE = Path("/var/lib/hybrid-stock-maintenance")


def _worker_exit(store: AttemptStore) -> tuple[int | None, bool]:
    """Inspect the actual owned container; launcher exit zero is insufficient."""
    target = store.snapshot()
    if target is None or target.abandoned_sha256 is not None:
        return None, False
    if target.stopped_sha256 is None or target.container_id is None:
        raise ValueError
    facts = _stopped(
        StockEngineReader().inspect(target.container_id), target.attempt, target.container_id
    )
    return facts["exit_code"], facts["oom_killed"] or facts["error_present"]


def _local(
    value: dict[str, Any], *, now: datetime
) -> tuple[StockControlRecord, dict[str, Any] | None]:
    if (
        type(value) is not dict
        or set(value) != {"version", "control", "control_sha256", "projection"}
        or type(value["version"]) is not int
        or value["version"] != 1
    ):
        raise ValueError
    control = StockControlRecord.model_validate_json(json.dumps(value["control"]))
    if (
        hashlib.sha256(_encode(control)).hexdigest() != value["control_sha256"]
        or control.changed_at > now
    ):
        raise ValueError
    projection = value["projection"]
    if projection is not None:
        export = StockDashboardExport.model_validate_json(json.dumps(projection, allow_nan=False))
        if export.generated_at > now:
            raise ValueError
        projection = export.model_dump()
    return control, projection


def _timer(checkout: Path, release: StockRelease, *, deadline: float) -> tuple[bool, bool]:
    _, env = helper_invocation(checkout, release, "observe")
    raw = _capture(
        (
            "/usr/bin/systemctl",
            "show",
            "--property=ActiveState,UnitFileState",
            "hybrid-stock-research.timer",
        ),
        cwd=checkout,
        env=env,
        limit=4096,
        deadline=deadline,
    ).stdout
    rows = raw.decode("ascii").splitlines()
    if len(rows) != 2:
        raise ValueError
    values = dict(row.split("=", 1) for row in rows)
    if (
        set(values) != {"ActiveState", "UnitFileState"}
        or values["ActiveState"]
        not in {"active", "inactive", "failed", "activating", "deactivating"}
        or values["UnitFileState"]
        not in {"enabled", "disabled", "static", "masked", "enabled-runtime"}
    ):
        raise ValueError
    return values["UnitFileState"] == "enabled", values["ActiveState"] == "active"


def monitor_stock(
    manifest: Path,
    *,
    checkout: Path,
    spool_root: Path = _MAINTENANCE / "incidents",
    receipt_root: Path = _MAINTENANCE / "receipts",
) -> dict[str, object]:
    """Only a complete observation may resolve incidents; uncertainty preserves them."""
    now = datetime.now(UTC)
    incidents = None
    try:
        release = load_release(manifest)
        unit_files(release, checkout)
        loaded = load_stock_worker_configuration(checkout / "configs")
        if str(loaded.config_hash) != release.config_hash:
            raise ValueError
        policy = _policy(loaded)
        code_hash = hashlib.sha256(f"oci-image:{release.image_digest}".encode()).hexdigest()
        deadline = time.monotonic() + 45
        with operations() as store:
            worker_exit, worker_error = _worker_exit(store)
            control, projection = _local(
                run_local_helper(checkout, release, "observe", deadline=deadline), now=now
            )
            if control.status == "running" and (
                control.config_hash != release.config_hash or control.code_hash != code_hash
            ):
                # The worker would reject this grant even when the preceding
                # projection and owned exit are current. Do not clear incidents.
                raise ValueError
            enabled, active = _timer(checkout, release, deadline=deadline)
            from trading_bot.runtime.stock_operation_receipts import StockOperationReceipts

            receipts = StockOperationReceipts(receipt_root).all(now=now)
            times = {
                kind: max(
                    (
                        datetime.fromisoformat(cast(str, row["at"]))
                        for row in receipts
                        if row["kind"] == kind
                    ),
                    default=None,
                )
                for kind in ("backup", "offhost", "restore")
            }
            space = os.statvfs(_ROOT)
            incidents = evaluate_stock_health(
                expected_config_hash=release.config_hash,
                expected_code_hash=code_hash,
                control_status=control.status,
                timer_enabled=enabled,
                timer_active=active,
                worker_exit_code=worker_exit,
                projection=projection,
                backup_created_at=times["backup"],
                offhost_copied_at=times["offhost"],
                restore_verified_at=times["restore"],
                free_bytes=space.f_bavail * space.f_frsize,
                free_inodes=space.f_favail,
                now=now,
                maximum_source_age_seconds=policy.stock_research.maximum_source_age_minutes * 60,
                scan_interval_seconds=release.scan_interval_seconds,
            )
            if worker_error:
                incidents = tuple(sorted({*incidents, "worker_exit_failed"}))
            if {
                "projection_missing",
                "projection_invalid",
                "projection_identity_mismatch",
                "observation_invalid",
            }.intersection(incidents):
                # These observations cannot establish whether previously retained
                # research failures recovered. The spool must preserve them.
                incidents = None
    except Exception:
        incidents = None
    try:
        record = StockIncidentSpool(spool_root).update(incidents, now=now)
        return {
            "status": "observed" if incidents is not None else "unavailable",
            "incident_count": sum(row["resolved_at"] is None for row in record["incidents"]),
            "live_enabled": False,
        }
    except Exception:
        raise ValueError("stock_monitor_unavailable") from None


def main() -> int:
    try:
        if sys.platform != "linux" or os.geteuid() != 0 or len(sys.argv) != 3:
            raise ValueError
        if sys.argv[1] not in {"monitor", "backup"}:
            raise ValueError
        operation = monitor_stock if sys.argv[1] == "monitor" else backup_stock
        result = operation(Path(sys.argv[2]), checkout=Path(__file__).resolve().parents[2])
        if result.get("live_enabled") is not False:
            raise ValueError
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0 if result["status"] in {"observed", "backup_committed"} else 2
    except Exception:
        print('{"live_enabled":false,"status":"stock_maintenance_unavailable"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
