"""Bounded fixed local maintenance subprocess; no browser, broker or shell."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from infra.hybrid.stock_container import _object
from infra.hybrid.stock_maintenance_verify import verify_local_runtime
from infra.hybrid.stock_process import _capture
from infra.hybrid.stock_release import StockRelease
from infra.hybrid.stock_units import unit_files


def helper_invocation(
    checkout: Path, release: StockRelease, action: str, *, identifier: str | None = None
) -> tuple[tuple[str, ...], dict[str, str]]:
    """Render a reduced-owner helper using the separately verified locked venv.

    Installation must establish an immutable root-owned runtime and sandbox it
    against OAuth, Docker and outbound networking. This pure renderer does not
    attest that installation, dependencies or filesystem ownership itself.
    """
    try:
        unit_files(release, checkout)  # Shared closed identity/path contract.
        if (
            type(action) is not str
            or action not in {"observe", "control-check", "snapshot"}
            or ((action == "snapshot") != (identifier is not None))
            or (
                identifier is not None
                and (
                    type(identifier) is not str or re.fullmatch(r"[0-9a-f]{32}", identifier) is None
                )
            )
        ):
            raise ValueError
        interpreter = Path("/opt/hybrid-stock-research/maintenance") / checkout.name / "bin/python"
        code_hash = hashlib.sha256(f"oci-image:{release.image_digest}".encode()).hexdigest()
        argv: tuple[str, ...] = (
            "/usr/bin/setpriv",
            "--reuid=10001",
            "--regid=10001",
            "--clear-groups",
            "--no-new-privs",
            str(interpreter),
            "-B",
            "-m",
            "trading_bot.runtime.stock_local_state",
            action,
            release.config_hash,
            code_hash,
        )
        if identifier is not None:
            argv += (identifier,)
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/nonexistent",
            "LANG": "C.UTF-8",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(checkout) + ":" + str(checkout / "src"),
            "LIVE_TRADING_ENABLED": "false",
            "PREDICTION_LIVE_ENABLED": "false",
        }
        return argv, env
    except Exception:
        raise ValueError("stock_maintenance_helper_unavailable") from None


def run_local_helper(
    checkout: Path,
    release: StockRelease,
    action: str,
    *,
    deadline: float,
    identifier: str | None = None,
) -> dict[str, Any]:
    """Reap the fixed process before returning; partial output is never success."""
    try:
        argv, env = helper_invocation(checkout, release, action, identifier=identifier)
        verify_local_runtime(checkout, release, deadline=deadline)
        captured = _capture(argv, cwd=checkout, env=env, limit=524288, deadline=deadline)
        value = _object(captured.stdout)
        if (
            captured.stdout
            != (
                json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
            ).encode()
        ):
            raise ValueError
        return value
    except Exception:
        raise ValueError("stock_maintenance_helper_unavailable") from None
