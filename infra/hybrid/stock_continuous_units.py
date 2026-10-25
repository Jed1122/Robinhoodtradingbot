"""Pure stock maintenance and boot unit composition; never installs or activates.

The caller verifies the root-owned immutable source/maintenance runtime, initializes
private state and existing lock anchors, and performs native unit verification.
Collector bytes remain exactly those produced by the existing paused-install
renderer. These additional bytes do not establish runtime or collection evidence.
"""

from __future__ import annotations

from pathlib import Path

from infra.hybrid.stock_release import RELEASE_ROOT, StockRelease
from infra.hybrid.stock_units import unit_files as collector_unit_files

_PREFIX = "hybrid-stock-research-"
_SPOOL = "/var/lib/hybrid-stock-maintenance"
_INCIDENTS = _SPOOL + "/incidents"
_RECEIPTS = _SPOOL + "/receipts"
_OPERATIONS = "/var/lib/hybrid-stock-operations"
_LEASE = _OPERATIONS + "/launcher.lock"
_CONTROL_LOCK = "/var/lib/hybrid-stock-research/controls/.stock-control.lock"


def _service(
    checkout: Path,
    command: str,
    writable: tuple[str, ...],
    *,
    description: str,
    start: int,
    stop: int,
    memory: str,
    tasks: int,
    cpu: int,
    requires: str = "",
    after: str = "",
    retained: bool = False,
    boot_install: bool = False,
    reduced_uid_helper: bool = False,
) -> bytes:
    dependency = f"Requires={requires}\n" if requires else ""
    ordered = after or requires or "docker.service"
    install = "\n[Install]\nWantedBy=multi-user.target\n" if boot_install else ""
    # Explicit User=root in systemd255's seccomp setup drops CAP_SETUID before
    # our setpriv helper can use it. System services already default to root.
    user = "" if reduced_uid_helper else "User=root\n"
    return f"""# Generated stock operations unit; installation and activation are separate.
[Unit]
Description={description}
{dependency}After={ordered}

[Service]
Type=oneshot
{user}Group=root
WorkingDirectory={checkout}
Environment="PYTHONDONTWRITEBYTECODE=1" "PYTHONPATH={checkout}:{checkout}/src" "PYTHONNOUSERSITE=1"
ExecStart={command}
RemainAfterExit={"yes" if retained else "no"}
Restart=no
TimeoutStartSec={start}s
TimeoutStopSec={stop}s
KillMode=control-group
UMask=0077
MemoryMax={memory}
TasksMax={tasks}
CPUQuota={cpu}%
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateNetwork=yes
PrivateDevices=yes
RestrictAddressFamilies=AF_UNIX
InaccessiblePaths=/var/lib/hybrid-stock-research/oauth
ReadWritePaths={" ".join(writable)}
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes
SystemCallArchitectures=native
StandardOutput=journal
StandardError=journal
LogRateLimitIntervalSec=300s
LogRateLimitBurst=5
{install}""".encode("ascii")


def _timer(operation: str, cadence: int) -> bytes:
    return f"""# Generated stock maintenance timer; no catch-up or research activation.
[Unit]
Description=Completion-relative stock {operation} schedule

[Timer]
OnActiveSec={cadence}s
OnUnitInactiveSec={cadence}s
AccuracySec=1s
RandomizedDelaySec=0
Persistent=false
Unit={_PREFIX}{operation}.service

[Install]
WantedBy=timers.target
""".encode("ascii")


def unit_files(release: StockRelease, checkout: Path) -> dict[str, bytes]:
    """Extend the exact collector units using only fixed, release-bound commands.

    The existing renderer validates all release/source types, identities and caps
    before any source component is interpolated. Maintenance execution is pinned
    to the same source commit. No filesystem, Docker, systemd, credential or
    control operation occurs. Writable payload exceptions are existing lock files
    and the explicitly initialized helper staging directory, never OAuth.
    """
    files = collector_unit_files(release, checkout)
    manifest = RELEASE_ROOT / release.release_id / "manifest.json"
    interpreter = Path("/opt/hybrid-stock-research/maintenance") / checkout.name / "bin/python"
    command = f"{interpreter} -B -m infra.hybrid.stock_maintenance"
    files[_PREFIX + "monitor.service"] = _service(
        checkout,
        f"{command} monitor {manifest}",
        (_INCIDENTS, _RECEIPTS + "/.stock-receipts.lock", _LEASE, _CONTROL_LOCK),
        description="Read-only stock operational observations and private local incidents",
        start=60,
        stop=15,
        memory="256M",
        tasks=64,
        cpu=50,
        reduced_uid_helper=True,
    )
    files[_PREFIX + "monitor.timer"] = _timer("monitor", 300)
    files[_PREFIX + "backup.service"] = _service(
        checkout,
        f"{command} backup-integrity {manifest}",
        (
            _RECEIPTS,
            _LEASE,
            "/var/lib/hybrid-stock-backups",
            "/var/lib/hybrid-stock-research/maintenance",
            "/var/lib/hybrid-stock-research/archive/.stock-research.lock",
            _CONTROL_LOCK,
            "/var/lib/hybrid-stock-research/exports/.stock-research.lock",
        ),
        description="Coherent stock snapshot and authenticated encrypted backup",
        start=300,
        stop=45,
        memory="384M",
        tasks=64,
        cpu=25,
        after="docker.service hybrid-stock-research.service",
        reduced_uid_helper=True,
    )
    files[_PREFIX + "backup.timer"] = _timer("backup", 86400)
    files[_PREFIX + "recovery.service"] = _service(
        checkout,
        "/usr/bin/python3 -B -m infra.hybrid.stock_recover",
        (_OPERATIONS,),
        description="Recovery-only stock boot gate without new worker dispatch",
        start=45,
        stop=15,
        memory="128M",
        tasks=32,
        cpu=50,
        requires="docker.service",
        retained=True,
    )
    files[_PREFIX + "bootstrap.service"] = _service(
        checkout,
        f"/usr/bin/python3 -B -m infra.hybrid.stock_bootstrap {manifest}",
        (_LEASE, _CONTROL_LOCK),
        description="Verified stock boot bootstrap after recovery and running authority",
        start=60,
        stop=15,
        memory="128M",
        tasks=32,
        cpu=50,
        requires="docker.service " + _PREFIX + "recovery.service",
        retained=True,
        boot_install=True,
        reduced_uid_helper=True,
    )
    return files
