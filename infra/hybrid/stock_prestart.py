"""Data-only, fixed-policy API 1.52 worker request and prestart comparison.

No Docker, filesystem, credential or control operation occurs here. Callers must
load the trusted release and obtain image/container observations independently;
internally consistent supplied data is never execution authority or provenance.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from infra.hybrid.stock_container import ImageProfile, _deny, _environment, _object, _require
from infra.hybrid.stock_release import RELEASE_ROOT, StockRelease, _exact, _policy

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_THERMAL = re.compile(r"/sys/devices/system/cpu/cpu(0|[1-9][0-9]{0,5})/thermal_throttle\Z")
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,9})?Z\Z")
_MASKS = frozenset(
    {
        "/proc/acpi",
        "/proc/asound",
        "/proc/interrupts",
        "/proc/kcore",
        "/proc/keys",
        "/proc/latency_stats",
        "/proc/sched_debug",
        "/proc/scsi",
        "/proc/timer_list",
        "/proc/timer_stats",
        "/sys/devices/virtual/powercap",
        "/sys/firmware",
    }
)
_READONLY = frozenset({"/proc/bus", "/proc/fs", "/proc/irq", "/proc/sys", "/proc/sysrq-trigger"})
_EMPTY_ARRAYS = frozenset(
    {
        "Binds",
        "VolumesFrom",
        "CapAdd",
        "ExtraHosts",
        "GroupAdd",
        "Links",
        "Dns",
        "DnsOptions",
        "DnsSearch",
        "BlkioWeightDevice",
        "BlkioDeviceReadBps",
        "BlkioDeviceWriteBps",
        "BlkioDeviceReadIOps",
        "BlkioDeviceWriteIOps",
        "Devices",
        "DeviceCgroupRules",
        "DeviceRequests",
        "Ulimits",
    }
)
_OPTIONAL_EMPTY_MAPS = frozenset({"Annotations", "StorageOpt", "Sysctls"})
_ERRORS = (ValueError, TypeError, KeyError, OverflowError, RecursionError, AttributeError)


@dataclass(frozen=True, slots=True)
class CreatedContainer:
    container_id: str
    attempt_id: str
    release_id: str
    image_digest: str
    config_hash: str
    compose_sha256: str


def container_name(attempt_id: str) -> str:
    """Generate the sole accepted name; randomness/uniqueness belongs to the owner."""
    _require(type(attempt_id) is str and _ATTEMPT.fullmatch(attempt_id) is not None)
    return "hybrid-stock-research-" + attempt_id


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def _hex(value: Any) -> bool:
    return type(value) is str and _HEX.fullmatch(value) is not None


def _configuration(release: StockRelease, image: ImageProfile, attempt_id: str) -> dict[str, Any]:
    container_name(attempt_id)
    _require(type(release) is StockRelease and type(image) is ImageProfile)
    _require(
        _hex(release.release_id) and _hex(release.config_hash) and _hex(release.compose_sha256)
    )
    _require(release.image_digest == image.image_digest)
    _require(re.fullmatch(r"sha256:[0-9a-f]{64}", image.image_digest) is not None)
    _require(image.architecture in ("amd64", "arm64"))
    attestation = RELEASE_ROOT / release.release_id / "runtime-image-attestation.json"
    _require(release.attestation_path == attestation)
    _require(release.compose_path == attestation.parent / "stock-compose.resolved.json")
    _require(type(release.max_run_seconds) is int and 60 <= release.max_run_seconds <= 450)
    _require(
        type(release.scan_interval_seconds) is int and 900 <= release.scan_interval_seconds <= 3600
    )
    _require(release.scan_interval_seconds % 60 == 0)
    model = _object(release.compose_bytes)
    _require(_canonical(model) == release.compose_bytes)
    _require(hashlib.sha256(release.compose_bytes).hexdigest() == release.compose_sha256)
    _require(_exact(model, _policy(image.image_digest, attestation)))
    worker = model["services"]["stock-research"]
    health = _object(image.disabled_healthcheck)
    expected_health = {
        "Test": ["NONE"],
        "Interval": 15000000000,
        "Timeout": 3000000000,
        "StartPeriod": 5000000000,
        "Retries": 3,
    }
    if "StartInterval" in health:
        _require(type(health["StartInterval"]) is int and health.pop("StartInterval") == 0)
    _require(_exact(health, expected_health))
    return {
        "Hostname": "",
        "Domainname": "",
        "User": worker["user"],
        "AttachStdin": False,
        "AttachStdout": False,
        "AttachStderr": False,
        "Tty": False,
        "OpenStdin": False,
        "StdinOnce": False,
        "Env": list(_environment(list(image.environment))),
        "Cmd": worker["command"],
        "Healthcheck": health,
        "Image": image.image_digest,
        "Volumes": {},
        "WorkingDir": "/app",
        "Entrypoint": worker["entrypoint"],
        "Labels": {
            "org.hybrid.stock.managed": "stock-research",
            "org.hybrid.stock.release": release.release_id,
            "org.hybrid.stock.attempt": attempt_id,
        },
        "StopSignal": worker["stop_signal"],
        "StopTimeout": 10,
    }


def _host_config(release: StockRelease) -> dict[str, Any]:
    worker = _object(release.compose_bytes)["services"]["stock-research"]
    mounts: list[dict[str, Any]] = []
    for volume in worker["volumes"]:
        mount = {
            "Type": "bind",
            "Source": volume["source"],
            "Target": volume["target"],
            "BindOptions": {"Propagation": "private"},
        }
        if volume.get("read_only") is True:
            mount["ReadOnly"] = True
        mounts.append(mount)
    host: dict[str, Any] = {
        name: 0
        for name in (
            "CpuShares",
            "BlkioWeight",
            "CpuPeriod",
            "CpuQuota",
            "CpuRealtimePeriod",
            "CpuRealtimeRuntime",
            "MemoryReservation",
            "CpuCount",
            "CpuPercent",
            "IOMaximumIOps",
            "IOMaximumBandwidth",
            "OomScoreAdj",
        )
    }
    host.update(
        {
            name: ""
            for name in (
                "ContainerIDFile",
                "VolumeDriver",
                "Cgroup",
                "PidMode",
                "UTSMode",
                "UsernsMode",
                "Isolation",
                "CgroupParent",
                "CpusetCpus",
                "CpusetMems",
            )
        }
    )
    host.update({name: None for name in _EMPTY_ARRAYS})
    host.update({"Dns": [], "DnsOptions": [], "DnsSearch": [], "MemorySwappiness": None})
    host.update(
        {name: False for name in ("AutoRemove", "Privileged", "PublishAllPorts", "OomKillDisable")}
    )
    host.update(
        {
            "LogConfig": {"Type": "json-file", "Config": worker["logging"]["options"]},
            "NetworkMode": worker["network_mode"],
            "PortBindings": {},
            "RestartPolicy": {"Name": worker["restart"], "MaximumRetryCount": 0},
            "ConsoleSize": [0, 0],
            "CapDrop": worker["cap_drop"],
            "CgroupnsMode": "private",
            "IpcMode": "private",
            "ReadonlyRootfs": worker["read_only"],
            "SecurityOpt": worker["security_opt"],
            "Tmpfs": {"/tmp": worker["tmpfs"][0].partition(":")[2]},  # nosec B108
            "ShmSize": 67108864,
            "Runtime": "runc",
            "Mounts": mounts,
            "MaskedPaths": None,
            "ReadonlyPaths": None,
            "Init": worker["init"],
            "Memory": int(worker["mem_limit"]),
            "MemorySwap": int(worker["memswap_limit"]),
            "NanoCpus": 500000000,
            "PidsLimit": worker["pids_limit"],
        }
    )
    return host


def worker_request(release: StockRelease, image: ImageProfile, attempt_id: str) -> bytes:
    """Return fixed request bytes only; neither create nor start is performed."""
    try:
        config = _configuration(release, image, attempt_id)
        return _canonical({**config, "HostConfig": _host_config(release)})
    except _ERRORS:
        _deny()


def verify_creation(raw: bytes) -> str:
    """A successful create response still requires separate actual-CID inspection."""
    try:
        response = _object(raw)
        _require(set(response) == {"Id", "Warnings"} and _hex(response["Id"]))
        _require(response["Warnings"] is None or _exact(response["Warnings"], []))
        return str(response["Id"])
    except _ERRORS:
        _deny()


def _paths(value: Any, required: frozenset[str], *, thermal: bool = False) -> None:
    _require(type(value) is list and len(value) <= len(required) + (4096 if thermal else 0))
    _require(all(type(item) is str for item in value))
    paths = set(value)
    _require(len(paths) == len(value) and required.issubset(paths))
    extras = paths - required
    _require(
        all(_THERMAL.fullmatch(item) is not None for item in extras) if thermal else not extras
    )


def _mounts(value: Any, expected: list[dict[str, Any]], *, resolved: bool = False) -> None:
    _require(type(value) is list and len(value) == len(expected))
    key = "Destination" if resolved else "Target"
    indexed: dict[str, dict[str, Any]] = {}
    for mount in value:
        _require(type(mount) is dict and type(mount.get(key)) is str)
        _require(mount[key] not in indexed)
        indexed[mount[key]] = mount
    for mount in expected:
        _require(mount[key] in indexed and _exact(indexed[mount[key]], mount))


def _verify_host(actual: Any, expected: dict[str, Any]) -> None:
    _require(type(actual) is dict and set(expected).issubset(actual))
    _require(set(actual).issubset(set(expected) | _OPTIONAL_EMPTY_MAPS))
    for key, value in actual.items():
        if key in _OPTIONAL_EMPTY_MAPS:
            _require(_exact(value, {}))
        elif key in _EMPTY_ARRAYS:
            _require(value is None or _exact(value, []))
        elif key == "MaskedPaths":
            _paths(value, _MASKS, thermal=True)
        elif key == "ReadonlyPaths":
            _paths(value, _READONLY)
        elif key == "Mounts":
            _mounts(value, expected[key])
        else:
            _require(_exact(value, expected[key]))


def _verify_config(actual: Any, expected: dict[str, Any]) -> None:
    _require(type(actual) is dict and set(expected).issubset(actual))
    optional = {
        "ExposedPorts": {},
        "ArgsEscaped": False,
        "NetworkDisabled": False,
        "OnBuild": [],
        "Shell": [],
    }
    _require(set(actual).issubset(set(expected) | set(optional)))
    for key, value in actual.items():
        _require(_exact(value, expected[key] if key in expected else optional[key]))


def _network() -> dict[str, Any]:
    endpoint: dict[str, Any] = {
        name: ""
        for name in (
            "NetworkID",
            "EndpointID",
            "Gateway",
            "IPAddress",
            "MacAddress",
            "IPv6Gateway",
            "GlobalIPv6Address",
        )
    }
    endpoint.update(
        {name: None for name in ("IPAMConfig", "Links", "Aliases", "DriverOpts", "DNSNames")}
    )
    endpoint.update({"GwPriority": 0, "IPPrefixLen": 0, "GlobalIPv6PrefixLen": 0})
    return {"SandboxID": "", "SandboxKey": "", "Ports": {}, "Networks": {"bridge": endpoint}}


def _state() -> dict[str, Any]:
    return {
        "Status": "created",
        "Running": False,
        "Paused": False,
        "Restarting": False,
        "OOMKilled": False,
        "Dead": False,
        "Pid": 0,
        "ExitCode": 0,
        "Error": "",
        "StartedAt": "0001-01-01T00:00:00Z",
        "FinishedAt": "0001-01-01T00:00:00Z",
    }


def verify_created(
    raw: bytes,
    *,
    release: StockRelease,
    image: ImageProfile,
    attempt_id: str,
    container_id: str,
) -> CreatedContainer:
    """Compare a supplied never-started CID to all fixed execution policy fields."""
    try:
        _require(_hex(container_id))
        expected_config = _configuration(release, image, attempt_id)
        expected_config["Hostname"] = container_id[:12]
        expected_host = _host_config(release)
        record = _object(raw)
        fixed = {
            "Id": container_id,
            "Path": expected_config["Entrypoint"][0],
            "Args": expected_config["Entrypoint"][1:] + expected_config["Cmd"],
            "State": _state(),
            "Image": image.image_digest,
            "Name": "/" + container_name(attempt_id),
            "RestartCount": 0,
            "Platform": "linux",
            "MountLabel": "",
            "ProcessLabel": "",
            "AppArmorProfile": "",
            "ExecIDs": None,
            "NetworkSettings": _network(),
        }
        paths = {"ResolvConfPath", "HostnamePath", "HostsPath", "LogPath"}
        required = set(fixed) | paths | {"Created", "Driver", "Config", "HostConfig", "Mounts"}
        optional = {"GraphDriver", "Storage", "ImageManifestDescriptor"}
        _require(required.issubset(record) and set(record).issubset(required | optional))
        for key, value in fixed.items():
            _require(_exact(record[key], value))
        for key in paths | {"Driver"}:
            _require(
                type(record[key]) is str and len(record[key]) <= 4096 and "\x00" not in record[key]
            )
        _require(bool(record["Driver"]))
        _require(
            type(record["Created"]) is str and _TIMESTAMP.fullmatch(record["Created"]) is not None
        )
        _require(datetime.fromisoformat(record["Created"]).year >= 1970)
        for key in optional & set(record):
            _require(type(record[key]) is dict)
        _verify_config(record["Config"], expected_config)
        _verify_host(record["HostConfig"], expected_host)
        expected_mounts = [
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
        _mounts(record["Mounts"], expected_mounts, resolved=True)
        return CreatedContainer(
            container_id,
            attempt_id,
            release.release_id,
            image.image_digest,
            release.config_hash,
            release.compose_sha256,
        )
    except _ERRORS:
        _deny()
