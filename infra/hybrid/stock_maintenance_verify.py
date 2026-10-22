"""Check immutable filesystem trust, then fresh stdlib runtime facts, before helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from infra.hybrid.stock_container import _object
from infra.hybrid.stock_maintenance_runtime import (
    _read,
    build_runtime_receipt,
    verify_runtime_receipt,
)
from infra.hybrid.stock_process import _capture
from infra.hybrid.stock_release import StockRelease
from infra.hybrid.stock_units import unit_files

OBSERVED_FIELDS = frozenset(
    {
        "python_implementation",
        "python_version",
        "platform",
        "architecture",
        "include_system_site_packages",
        "sys_prefix",
        "site_packages",
        "distributions",
    }
)

# Only standard-library imports; never an application/dependency import or secret.
_FACTS_SCRIPT = r"""
import importlib.metadata, json, pathlib, platform, re, sys, sysconfig
if sys.flags.isolated != 1 or not sys.dont_write_bytecode:
    raise RuntimeError("runtime isolation unavailable")
site_packages = sysconfig.get_path("purelib")
settings = {}
for line in (pathlib.Path(sys.prefix) / "pyvenv.cfg").read_text().splitlines():
    key, value = line.split(" = ", 1)
    if key in settings:
        raise RuntimeError("runtime settings invalid")
    settings[key] = value
packages = []
for distribution in importlib.metadata.distributions(path=[site_packages]):
    direct = distribution.read_text("direct_url.json")
    detail = None if direct is None else json.loads(direct)
    editable = (isinstance(detail, dict)
                and isinstance(detail.get("dir_info"), dict)
                and detail["dir_info"].get("editable") is True)
    packages.append({"name": re.sub(r"[-_.]+", "-", distribution.metadata["Name"]).lower(),
                     "version": distribution.version,
                     "direct_url_present": direct is not None, "editable": editable})
packages.sort(key=lambda row: row["name"])
value = {"python_implementation": sys.implementation.name,
         "python_version": platform.python_version(), "platform": sys.platform,
         "architecture": platform.machine(),
         "include_system_site_packages": settings.get("include-system-site-packages") != "false",
         "sys_prefix": sys.prefix, "site_packages": site_packages,
         "distributions": packages}
print(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False))
"""


def verify_local_runtime(checkout: Path, release: StockRelease, *, deadline: float) -> None:
    """A receipt is checked against source inputs and then current target facts.

    The first pass establishes safe root-owned paths before executing the fixed
    interpreter. The second pass independently matches current runtime metadata.
    Installer/check flags still require retained actual installation evidence.
    """
    try:
        unit_files(release, checkout)
        runtime = Path("/opt/hybrid-stock-research/maintenance") / checkout.name
        path = runtime / "runtime-receipt.json"
        raw = _read(path, Path("/"), 0, 65536, receipt=True)
        receipt = _object(raw)
        frozen = {
            key: value for key, value in receipt.items() if key not in {"kind", "schema_version"}
        }
        if build_runtime_receipt(frozen) != raw:
            raise ValueError
        identities = {
            "source_commit": checkout.name,
            "source_archive_sha256": release.release_id,
            "uv_lock_sha256": hashlib.sha256(
                _read(checkout / "uv.lock", Path("/"), 0, 2097152)
            ).hexdigest(),
            "requirements_sha256": hashlib.sha256(
                _read(
                    checkout / "infra/hybrid/stock-maintenance-requirements.txt",
                    Path("/"),
                    0,
                    524288,
                )
            ).hexdigest(),
            "config_hash": release.config_hash,
        }
        verify_runtime_receipt(path, **identities, actual_facts=frozen)
        captured = _capture(
            (str(runtime / "bin/python"), "-I", "-B", "-c", _FACTS_SCRIPT),
            cwd=checkout,
            env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LANG": "C.UTF-8"},
            limit=65536,
            deadline=deadline,
        )
        current = _object(captured.stdout)
        if (
            set(current) != OBSERVED_FIELDS
            or captured.stdout
            != (
                json.dumps(current, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
            ).encode()
        ):
            raise ValueError
        verify_runtime_receipt(path, **identities, actual_facts=frozen | current)
    except Exception:
        raise ValueError("stock_maintenance_verification_unavailable") from None
