"""One boot scheduling request after separate recovery and bound research consent.

No recovery, control mutation, OAuth, container creation or retry occurs here.
The scheduled worker rechecks its own control grant and UTC admission ledger.
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from infra.hybrid.stock_attempts import operations
from infra.hybrid.stock_engine import StockEngineReader
from infra.hybrid.stock_maintenance_process import helper_invocation, run_local_helper
from infra.hybrid.stock_process import _capture
from infra.hybrid.stock_release import load_release
from infra.hybrid.stock_units import unit_files


def _grant(value: dict[str, Any]) -> None:
    if (
        type(value) is not dict
        or set(value) != {"status", "control_sha256", "control_id", "generation"}
        or value["status"] != "running"
        or type(value["control_sha256"]) is not str
        or re.fullmatch(r"[0-9a-f]{64}", value["control_sha256"]) is None
        or type(value["control_id"]) is not str
        or re.fullmatch(r"[0-9a-f]{32}", value["control_id"]) is None
        or type(value["generation"]) is not int
        or not 1 <= value["generation"] <= 1_000_000_000
    ):
        raise ValueError


def bootstrap_research(manifest: Path, *, checkout: Path) -> dict[str, object]:
    """Queue the existing singleton service once, only from complete observations."""
    try:
        if sys.platform != "linux" or os.geteuid() != 0:
            raise ValueError
        release = load_release(manifest)
        unit_files(release, checkout)
        deadline = time.monotonic() + 45
        with operations() as store:
            target = store.snapshot()
            if target is not None:
                if target.stopped_sha256 is None and target.abandoned_sha256 is None:
                    raise ValueError
                if target.stopped_sha256 is not None:
                    if target.container_id is None:
                        raise ValueError
                    from infra.hybrid.stock_attempts import _stopped

                    _stopped(
                        StockEngineReader().inspect(target.container_id),
                        target.attempt,
                        target.container_id,
                    )
            _grant(run_local_helper(checkout, release, "control-check", deadline=deadline))
            _, env = helper_invocation(checkout, release, "control-check")
            observed = _capture(
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
            lines = observed.decode("ascii").splitlines()
            if len(lines) != 2 or set(lines) != {"ActiveState=active", "UnitFileState=enabled"}:
                raise ValueError
        # The worker takes the same nonblocking barrier, so release it before
        # queuing. It independently rechecks controls, lifecycle and UTC quota.
        # A response failure is ambiguous; never issue another start here.
        _capture(
            ("/usr/bin/systemctl", "--no-block", "start", "hybrid-stock-research.service"),
            cwd=checkout,
            env=env,
            limit=4096,
            deadline=deadline,
        )
        return {"status": "queued", "live_enabled": False}
    except Exception:
        raise ValueError("stock_bootstrap_unavailable") from None


def main() -> int:
    try:
        if len(sys.argv) != 2:
            raise ValueError
        bootstrap_research(Path(sys.argv[1]), checkout=Path(__file__).resolve().parents[2])
        print('{"live_enabled":false,"status":"queued"}')
        return 0
    except Exception:
        print('{"live_enabled":false,"status":"stock_bootstrap_unavailable"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
