"""Pure fixed inert request/comparison; never creates, starts or authorizes a CID."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, NoReturn

from infra.hybrid.stock_container import ImageProfile, _environment, _object, _require
from infra.hybrid.stock_prestart import (
    _ERRORS,
    _canonical,
    _hex,
    _host_defaults,
    _image_healthcheck,
    _state,
    _verify_config,
    _verify_container_metadata,
    _verify_host,
)
from infra.hybrid.stock_release import _exact


@dataclass(frozen=True, slots=True)
class CreatedProbe:
    container_id: str
    probe_id: str
    image_digest: str


def _deny() -> NoReturn:
    raise ValueError("stock_probe_profile_unavailable") from None


def probe_name(probe_id: str) -> str:
    try:
        _require(type(probe_id) is str and re.fullmatch(r"[0-9a-f]{32}", probe_id) is not None)
        return "hybrid-stock-probe-" + probe_id
    except _ERRORS:
        _deny()


def _configuration(image: ImageProfile, probe_id: str) -> dict[str, Any]:
    probe_name(probe_id)
    _require(type(image) is ImageProfile)
    _require(re.fullmatch(r"sha256:[0-9a-f]{64}", image.image_digest) is not None)
    _require(image.architecture in ("amd64", "arm64"))
    return {
        "Hostname": "",
        "Domainname": "",
        "User": "10001:10001",
        "AttachStdin": False,
        "AttachStdout": False,
        "AttachStderr": False,
        "Tty": False,
        "OpenStdin": False,
        "StdinOnce": False,
        "Env": list(_environment(list(image.environment))),
        "Cmd": ["--config-root", "/app/configs"],
        "Healthcheck": _image_healthcheck(image),
        "Image": image.image_digest,
        "Volumes": {},
        "WorkingDir": "/app",
        "Entrypoint": ["python", "-m", "trading_bot.runtime.stock_research_identity"],
        "Labels": {
            "org.hybrid.stock.managed": "stock-configuration-probe",
            "org.hybrid.stock.probe": probe_id,
        },
        "StopSignal": "SIGTERM",
        "StopTimeout": 10,
        "NetworkDisabled": True,
    }


def _host_config() -> dict[str, Any]:
    return {
        **_host_defaults(),
        "LogConfig": {"Type": "json-file", "Config": {"max-size": "1m", "max-file": "1"}},
        "NetworkMode": "none",
        "PortBindings": {},
        "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
        "ConsoleSize": [0, 0],
        "CapDrop": ["ALL"],
        "CgroupnsMode": "private",
        "IpcMode": "private",
        "ReadonlyRootfs": True,
        "SecurityOpt": ["no-new-privileges:true"],
        "ShmSize": 67108864,
        "Runtime": "runc",
        "MaskedPaths": None,
        "ReadonlyPaths": None,
        "Init": True,
        "Memory": 536870912,
        "MemorySwap": 536870912,
        "NanoCpus": 500000000,
        "PidsLimit": 128,
    }


def probe_request(image: ImageProfile, probe_id: str) -> bytes:
    """Return one fixed inert request, with no supplied release or policy override."""
    try:
        return _canonical({**_configuration(image, probe_id), "HostConfig": _host_config()})
    except _ERRORS:
        _deny()


def verify_probe_created(
    raw: bytes, *, image: ImageProfile, probe_id: str, container_id: str
) -> CreatedProbe:
    """Compare supplied never-started metadata; copied identity is not authority."""
    try:
        _require(_hex(container_id))
        expected = _configuration(image, probe_id)
        expected["Hostname"] = container_id[:12]
        record = _object(raw)
        _verify_container_metadata(
            record,
            {
                "Id": container_id,
                "Path": "python",
                "Args": expected["Entrypoint"][1:] + expected["Cmd"],
                "State": _state(),
                "Image": image.image_digest,
                "Name": "/" + probe_name(probe_id),
                "RestartCount": 0,
                "Platform": "linux",
                "MountLabel": "",
                "ProcessLabel": "",
                "AppArmorProfile": "",
                "ExecIDs": None,
                "NetworkSettings": {"SandboxID": "", "SandboxKey": "", "Ports": {}, "Networks": {}},
            },
        )
        _verify_config(record["Config"], expected)
        host = record["HostConfig"]
        _require(type(host) is dict)
        for field, empty in (("Mounts", []), ("Tmpfs", {})):
            if field in host:
                _require(_exact(host[field], empty))
        _verify_host(
            {key: value for key, value in host.items() if key not in {"Mounts", "Tmpfs"}},
            _host_config(),
        )
        _require(_exact(record["Mounts"], []))
        return CreatedProbe(container_id, probe_id, image.image_digest)
    except _ERRORS:
        _deny()
