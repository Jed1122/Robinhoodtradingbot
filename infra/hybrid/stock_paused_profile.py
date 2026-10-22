"""Pure fixed paused-worker acceptance request and never-started comparison.

The worker command and five non-OAuth binds retain the production policy. The
acceptance identity has no network and no OAuth bind. This module performs no
Docker, filesystem, credential, control or ledger operation; matching supplied
metadata is neither provenance nor authority to start a container.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NoReturn

from infra.hybrid.stock_container import ImageProfile, _object, _require
from infra.hybrid.stock_prestart import (
    _ERRORS,
    _canonical,
    _hex,
    _mounts,
    _state,
    _verify_config,
    _verify_container_metadata,
    _verify_host,
    worker_request,
)
from infra.hybrid.stock_release import StockRelease


@dataclass(frozen=True, slots=True)
class CreatedPausedContainer:
    container_id: str
    check_id: str
    release_id: str
    image_digest: str
    config_hash: str
    compose_sha256: str


def _deny() -> NoReturn:
    raise ValueError("stock_paused_profile_unavailable") from None


def paused_name(check_id: str) -> str:
    """Generate only the distinct acceptance name; the operator owns uniqueness."""
    try:
        _require(type(check_id) is str and re.fullmatch(r"[0-9a-f]{32}", check_id) is not None)
        return "hybrid-stock-paused-check-" + check_id
    except _ERRORS:
        _deny()


def paused_request(release: StockRelease, image: ImageProfile, check_id: str) -> bytes:
    """Derive the closed acceptance request after validating the production policy."""
    try:
        paused_name(check_id)
        request = _object(worker_request(release, image, check_id))
        request["Labels"] = {
            "org.hybrid.stock.managed": "stock-paused-check",
            "org.hybrid.stock.release": release.release_id,
            "org.hybrid.stock.probe": check_id,
        }
        request["NetworkDisabled"] = True
        host = request["HostConfig"]
        host["NetworkMode"] = "none"
        host["Mounts"] = [mount for mount in host["Mounts"] if mount["Target"] != "/stock-oauth"]
        _require(len(host["Mounts"]) == 5)
        return _canonical(request)
    except _ERRORS:
        _deny()


def verify_paused_created(
    raw: bytes,
    *,
    release: StockRelease,
    image: ImageProfile,
    check_id: str,
    container_id: str,
) -> CreatedPausedContainer:
    """Check all actual never-started metadata against the separate fixed profile."""
    try:
        _require(_hex(container_id))
        expected_config = _object(paused_request(release, image, check_id))
        expected_host = expected_config.pop("HostConfig")
        expected_config["Hostname"] = container_id[:12]
        record = _object(raw)
        _verify_container_metadata(
            record,
            {
                "Id": container_id,
                "Path": expected_config["Entrypoint"][0],
                "Args": expected_config["Entrypoint"][1:] + expected_config["Cmd"],
                "State": _state(),
                "Image": image.image_digest,
                "Name": "/" + paused_name(check_id),
                "RestartCount": 0,
                "Platform": "linux",
                "MountLabel": "",
                "ProcessLabel": "",
                "AppArmorProfile": "",
                "ExecIDs": None,
                # The pinned never-started, disabled-network profile has no endpoint.
                "NetworkSettings": {"SandboxID": "", "SandboxKey": "", "Ports": {}, "Networks": {}},
            },
        )
        _verify_config(record["Config"], expected_config)
        _verify_host(record["HostConfig"], expected_host)
        resolved_mounts = [
            {
                "Type": "bind",
                "Source": mount["Source"],
                "Destination": mount["Target"],
                "Mode": "",
                "RW": not mount.get("ReadOnly", False),
                "Propagation": "private",
            }
            for mount in expected_host["Mounts"]
        ]
        _mounts(record["Mounts"], resolved_mounts, resolved=True)
        return CreatedPausedContainer(
            container_id,
            check_id,
            release.release_id,
            image.image_digest,
            release.config_hash,
            release.compose_sha256,
        )
    except _ERRORS:
        _deny()
