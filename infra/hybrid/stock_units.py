"""Produce stock service/timer bytes without installing or activating anything.

The caller must first load the root-owned release and verify the exact clean,
root-owned checkout and native paused-worker proof. These bytes alone do not
establish those preconditions or authorize collection.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from infra.hybrid.stock_release import RELEASE_ROOT, StockRelease

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CHECKOUT = re.compile(r"/opt/hybrid-stock-research/source/[0-9a-f]{40}\Z")
_PATH_TYPE = type(Path())


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("stock_units_unavailable")


def unit_files(release: StockRelease, checkout: Path) -> dict[str, bytes]:
    """Render bounded fixed commands from supplied verified production identities.

    No filesystem, Docker, credential, control, installation or systemd operation
    occurs here. Paths use a closed alphabet rather than shell/systemd escaping.
    The post-stop command can only recover a retained attempt; it has no release
    argument and cannot dispatch a new worker.
    """
    _require(type(release) is StockRelease)
    _require(type(checkout) is _PATH_TYPE and _CHECKOUT.fullmatch(str(checkout)) is not None)
    for identity in (release.release_id, release.config_hash, release.compose_sha256):
        _require(type(identity) is str and _HEX.fullmatch(identity) is not None)
    _require(
        type(release.image_digest) is str and _IMAGE.fullmatch(release.image_digest) is not None
    )
    directory = RELEASE_ROOT / release.release_id
    _require(
        type(release.attestation_path) is _PATH_TYPE
        and release.attestation_path == directory / "runtime-image-attestation.json"
        and type(release.compose_path) is _PATH_TYPE
        and release.compose_path == directory / "stock-compose.resolved.json"
    )
    _require(
        type(release.compose_bytes) is bytes
        and 0 < len(release.compose_bytes) <= 65536
        and hashlib.sha256(release.compose_bytes).hexdigest() == release.compose_sha256
    )
    _require(type(release.max_run_seconds) is int and 60 <= release.max_run_seconds <= 450)
    _require(
        type(release.scan_interval_seconds) is int
        and 900 <= release.scan_interval_seconds <= 3600
        and release.scan_interval_seconds % 60 == 0
    )
    service = f"""# Generated stock research unit; installation leaves scheduling disabled.
[Unit]
Description=Supervised stock research attempt
After=docker.service

[Service]
Type=oneshot
User=root
Group=root
WorkingDirectory={checkout}
Environment="PYTHONDONTWRITEBYTECODE=1" "PYTHONPATH={checkout}:{checkout}/src" "PYTHONNOUSERSITE=1"
ExecStart=/usr/bin/python3 -B -m infra.hybrid.stock_launcher {directory}/manifest.json
ExecStopPost=/usr/bin/python3 -B -m infra.hybrid.stock_recover
RemainAfterExit=no
Restart=no
TimeoutStartSec={release.max_run_seconds + 60}s
TimeoutStopSec=45s
KillMode=control-group
UMask=0077
MemoryMax=256M
TasksMax=64
CPUQuota=50%
"""
    timer = f"""# Generated stock research timer; enablement is a separate operator action.
[Unit]
Description=Completion-relative stock research schedule

[Timer]
OnUnitInactiveSec={release.scan_interval_seconds}s
AccuracySec=1s
RandomizedDelaySec=0
Persistent=false
Unit=hybrid-stock-research.service

[Install]
WantedBy=timers.target
"""
    return {
        "hybrid-stock-research.service": service.encode("ascii"),
        "hybrid-stock-research.timer": timer.encode("ascii"),
    }
