"""Fictional API 1.52 request/inspect substitution tests; never use Docker."""

import copy
import hashlib
import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from infra.hybrid.stock_container import EngineProfile, verify_image
from infra.hybrid.stock_release import RELEASE_ROOT, StockRelease, _policy

IMAGE = "sha256:" + "b" * 64
RELEASE = "d" * 64
ATTEMPT = "e" * 32
CID = "f" * 64
ENV = [
    "PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin",
    "LANG=C.UTF-8",
    "GPG_KEY=" + "A" * 40,
    "PYTHON_VERSION=3.12.13",
    "PYTHON_SHA256=" + "a" * 64,
    "PYTHONPATH=/app/src",
    "PYTHONDONTWRITEBYTECODE=1",
    "PYTHONUNBUFFERED=1",
    "LIVE_TRADING_ENABLED=false",
    "PREDICTION_LIVE_ENABLED=false",
]
MASKS = [
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
]
READONLY = ["/proc/bus", "/proc/fs", "/proc/irq", "/proc/sys", "/proc/sysrq-trigger"]


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def module():
    source = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_prestart.py"
    assert source.is_file(), "Created-container admission is not implemented"
    return importlib.import_module("infra.hybrid.stock_prestart")


@pytest.fixture
def policy():
    attestation = RELEASE_ROOT / RELEASE / "runtime-image-attestation.json"
    model = encoded(_policy(IMAGE, attestation))
    release = StockRelease(
        RELEASE,
        IMAGE,
        "c" * 64,
        hashlib.sha256(model).hexdigest(),
        450,
        3600,
        attestation,
        attestation.parent / "stock-compose.resolved.json",
        model,
    )
    image = verify_image(
        encoded(
            {
                "Id": IMAGE,
                "Os": "linux",
                "Architecture": "amd64",
                "Config": {
                    "User": "10001:10001",
                    "WorkingDir": "/app",
                    "Env": ENV,
                    "Healthcheck": {
                        "Test": [
                            "CMD",
                            "python",
                            "-c",
                            "import urllib.request; "
                            "urllib.request.urlopen('http://127.0.0.1:8080/healthz', "
                            "timeout=2).close()",
                        ],
                        "Interval": 15000000000,
                        "Timeout": 3000000000,
                        "StartPeriod": 5000000000,
                        "Retries": 3,
                    },
                },
            }
        ),
        IMAGE,
        EngineProfile("1.52", "amd64"),
    )
    return release, image


def host_config(policy):
    release, _ = policy
    mounts = [
        {
            "Type": "bind",
            "Source": "/var/lib/hybrid-stock-research/" + name,
            "Target": "/stock-" + name,
            "BindOptions": {"Propagation": "private"},
        }
        for name in ("state", "archive", "controls", "exports", "oauth")
    ]
    mounts.append(
        {
            "Type": "bind",
            "Source": str(release.attestation_path),
            "Target": "/run/trading-bot/stock-image-attestation.json",
            "ReadOnly": True,
            "BindOptions": {"Propagation": "private"},
        }
    )
    value = {
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
    value.update(
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
    value.update(
        {
            name: None
            for name in (
                "Binds",
                "VolumesFrom",
                "CapAdd",
                "ExtraHosts",
                "GroupAdd",
                "Links",
                "BlkioWeightDevice",
                "BlkioDeviceReadBps",
                "BlkioDeviceWriteBps",
                "BlkioDeviceReadIOps",
                "BlkioDeviceWriteIOps",
                "Devices",
                "DeviceCgroupRules",
                "DeviceRequests",
                "Ulimits",
                "MemorySwappiness",
            )
        }
    )
    value.update(
        {
            name: False
            for name in (
                "AutoRemove",
                "Privileged",
                "PublishAllPorts",
                "OomKillDisable",
            )
        }
    )
    value.update(
        {
            "LogConfig": {"Type": "json-file", "Config": {"max-size": "10m", "max-file": "3"}},
            "NetworkMode": "bridge",
            "PortBindings": {},
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "ConsoleSize": [0, 0],
            "CapDrop": ["ALL"],
            "CgroupnsMode": "private",
            "Dns": [],
            "DnsOptions": [],
            "DnsSearch": [],
            "IpcMode": "private",
            "ReadonlyRootfs": True,
            "SecurityOpt": ["no-new-privileges:true"],
            "Tmpfs": {"/tmp": "size=32m,mode=1777,noexec,nosuid,nodev"},
            "ShmSize": 67108864,
            "Runtime": "runc",
            "Mounts": mounts,
            "MaskedPaths": MASKS.copy(),
            "ReadonlyPaths": READONLY.copy(),
            "Init": True,
            "Memory": 536870912,
            "MemorySwap": 536870912,
            "NanoCpus": 500000000,
            "PidsLimit": 128,
        }
    )
    return value


def record(policy):
    release, image = policy
    model = json.loads(release.compose_bytes)["services"]["stock-research"]
    host = host_config(policy)
    endpoint = {
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
        {
            name: None
            for name in (
                "IPAMConfig",
                "Links",
                "Aliases",
                "DriverOpts",
                "DNSNames",
            )
        }
    )
    endpoint.update({"GwPriority": 0, "IPPrefixLen": 0, "GlobalIPv6PrefixLen": 0})
    return {
        "Id": CID,
        "Created": "2026-10-21T20:30:00.123456789Z",
        "Path": "python",
        "Args": model["entrypoint"][1:] + model["command"],
        "State": {
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
        },
        "Image": IMAGE,
        "ResolvConfPath": "/daemon/fictional/resolv.conf",
        "HostnamePath": "/daemon/fictional/hostname",
        "HostsPath": "/daemon/fictional/hosts",
        "LogPath": "",
        "Name": "/hybrid-stock-research-" + ATTEMPT,
        "RestartCount": 0,
        "Driver": "overlayfs",
        "Platform": "linux",
        "MountLabel": "",
        "ProcessLabel": "",
        "AppArmorProfile": "",
        "ExecIDs": None,
        "HostConfig": host,
        "Mounts": [
            {
                "Type": "bind",
                "Source": mount["Source"],
                "Destination": mount["Target"],
                "Mode": "",
                "RW": not mount.get("ReadOnly", False),
                "Propagation": "private",
            }
            for mount in host["Mounts"]
        ],
        "Config": {
            "Hostname": CID[:12],
            "Domainname": "",
            "User": "10001:10001",
            "AttachStdin": False,
            "AttachStdout": False,
            "AttachStderr": False,
            "Tty": False,
            "OpenStdin": False,
            "StdinOnce": False,
            "Env": list(image.environment),
            "Cmd": model["command"],
            "Healthcheck": json.loads(image.disabled_healthcheck),
            "Image": IMAGE,
            "Volumes": {},
            "WorkingDir": "/app",
            "Entrypoint": model["entrypoint"],
            "Labels": {
                "org.hybrid.stock.managed": "stock-research",
                "org.hybrid.stock.release": RELEASE,
                "org.hybrid.stock.attempt": ATTEMPT,
            },
            "StopSignal": "SIGTERM",
            "StopTimeout": 10,
        },
        "NetworkSettings": {
            "SandboxID": "",
            "SandboxKey": "",
            "Ports": {},
            "Networks": {"bridge": endpoint},
        },
    }


def verify(policy, value):
    release, image = policy
    return module().verify_created(
        encoded(value),
        release=release,
        image=image,
        attempt_id=ATTEMPT,
        container_id=CID,
    )


def test_fixed_request_has_no_implicit_execution_or_host_creation(policy):
    release, image = policy
    api = module()
    request = json.loads(api.worker_request(release, image, ATTEMPT))
    assert api.container_name(ATTEMPT) == "hybrid-stock-research-" + ATTEMPT
    assert request["Image"] == IMAGE and request["Env"] == ENV
    assert request["HostConfig"]["PortBindings"] == {}
    assert request["HostConfig"]["IpcMode"] == "private"
    assert request["HostConfig"]["CgroupnsMode"] == "private"
    assert request["HostConfig"]["MemorySwap"] == 536870912
    assert request["HostConfig"]["RestartPolicy"]["Name"] == "no"
    assert len(request["HostConfig"]["Mounts"]) == 6
    assert all(
        "CreateMountpoint" not in mount["BindOptions"] for mount in request["HostConfig"]["Mounts"]
    )
    assert "NetworkingConfig" not in request


def test_complete_created_container_returns_only_identity(policy):
    result = verify(policy, record(policy))
    assert result.container_id == CID and result.attempt_id == ATTEMPT
    assert result.release_id == RELEASE and result.image_digest == IMAGE
    assert result.config_hash == "c" * 64 and result.compose_sha256 == policy[0].compose_sha256
    assert "Env" not in repr(result) and "HostConfig" not in repr(result)


def test_unordered_binds_masks_and_readonly_paths_are_semantic_sets(policy):
    value = record(policy)
    value["HostConfig"]["Mounts"].reverse()
    value["Mounts"].reverse()
    value["HostConfig"]["MaskedPaths"].reverse()
    value["HostConfig"]["MaskedPaths"].append("/sys/devices/system/cpu/cpu0/thermal_throttle")
    value["HostConfig"]["ReadonlyPaths"].reverse()
    assert verify(policy, value).container_id == CID


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("HostConfig", "Privileged", True),
        ("HostConfig", "ReadonlyRootfs", False),
        ("HostConfig", "Memory", 0),
        ("HostConfig", "MemorySwap", -1),
        ("HostConfig", "PidsLimit", True),
        ("HostConfig", "NanoCpus", 500000001),
        ("HostConfig", "CgroupnsMode", "host"),
        ("HostConfig", "IpcMode", "shareable"),
        ("HostConfig", "PidMode", "host"),
        ("HostConfig", "UTSMode", "host"),
        ("HostConfig", "UsernsMode", "host"),
        ("HostConfig", "NetworkMode", "host"),
        ("HostConfig", "AutoRemove", True),
        ("HostConfig", "Init", False),
        ("HostConfig", "CapAdd", ["SYS_ADMIN"]),
        ("HostConfig", "CapDrop", []),
        ("HostConfig", "Binds", ["/private:/private"]),
        ("HostConfig", "Runtime", "other"),
        ("HostConfig", "PortBindings", {"8080/tcp": []}),
        ("HostConfig", "PortBindings", {"8080/tcp": None}),
        ("HostConfig", "Ulimits", [{"Name": "nofile", "Hard": 999999, "Soft": 999999}]),
        ("HostConfig", "RestartPolicy", {"Name": "always", "MaximumRetryCount": 0}),
        ("HostConfig", "SecurityOpt", ["seccomp=unconfined"]),
        ("HostConfig", "MaskedPaths", []),
        ("HostConfig", "ReadonlyPaths", []),
        ("HostConfig", "StorageOpt", {"size": "100G"}),
        ("HostConfig", "Annotations", {"runtime.override": "1"}),
        ("HostConfig", "Sysctls", {"net.ipv4.ip_forward": "1"}),
        ("HostConfig", "UnknownFutureControl", False),
        ("Config", "User", "0:0"),
        ("Config", "Env", [*ENV, "HTTPS_PROXY=fictional"]),
        ("Config", "Entrypoint", ["sh", "-c"]),
        ("Config", "Cmd", ["--export-only"]),
        ("Config", "Volumes", {"/unexpected": {}}),
        ("Config", "ExposedPorts", {"80/tcp": {}}),
        ("Config", "Tty", True),
        ("Config", "OpenStdin", True),
        ("Config", "StopTimeout", True),
        ("Config", "StopSignal", "SIGKILL"),
        ("Config", "Labels", {}),
        ("Config", "NetworkDisabled", True),
        ("Config", "Shell", ["/bin/sh"]),
        ("Config", "UnknownFutureControl", False),
        ("State", "Running", True),
        ("State", "Pid", 1),
        ("State", "ExitCode", False),
        ("State", "Error", "previous failed start"),
        ("State", "StartedAt", "2026-10-21T20:30:00Z"),
        ("State", "Health", {"Status": "starting"}),
        ("NetworkSettings", "Ports", {"8080/tcp": None}),
        ("NetworkSettings", "SandboxID", "active"),
        ("NetworkSettings", "Networks", {}),
    ],
)
def test_host_config_command_state_and_network_substitutions_deny(policy, section, field, value):
    changed = record(policy)
    changed[section][field] = value
    with pytest.raises(ValueError, match=r"^stock_container_unavailable$"):
        verify(policy, changed)


@pytest.mark.parametrize(
    "field,value",
    [
        ("Id", CID[:12]),
        ("Image", "sha256:" + "a" * 64),
        ("Name", "/other"),
        ("RestartCount", 1),
        ("RestartCount", False),
        ("Path", "/bin/sh"),
        ("Args", []),
        ("Platform", "windows"),
        ("AppArmorProfile", "unconfined"),
        ("ExecIDs", ["other"]),
        ("Unexpected", {}),
    ],
)
def test_top_level_identity_and_execution_substitutions_deny(policy, field, value):
    changed = record(policy)
    changed[field] = value
    with pytest.raises(ValueError, match=r"^stock_container_unavailable$"):
        verify(policy, changed)


@pytest.mark.parametrize("which", ["request", "resolved"])
@pytest.mark.parametrize(
    "change", ["extra", "duplicate", "missing", "source", "writable", "propagation", "option"]
)
def test_both_complete_mount_inventories_are_checked(policy, which, change):
    changed = record(policy)
    mounts = changed["HostConfig"]["Mounts"] if which == "request" else changed["Mounts"]
    if change == "extra":
        mounts.append({"Type": "volume", "Source": "other", "Target": "/other"})
    elif change == "duplicate":
        mounts[-1] = copy.deepcopy(mounts[0])
    elif change == "missing":
        mounts.pop()
    elif change == "source":
        mounts[0]["Source"] = "/other"
    elif change == "writable":
        mounts[-1]["ReadOnly" if which == "request" else "RW"] = which != "request"
    elif change == "propagation":
        if which == "request":
            mounts[0]["BindOptions"]["Propagation"] = "rslave"
        else:
            mounts[0]["Propagation"] = "rslave"
    else:
        if which == "request":
            mounts[0]["BindOptions"]["CreateMountpoint"] = True
        else:
            mounts[0]["Driver"] = "other"
    with pytest.raises(ValueError, match=r"^stock_container_unavailable$"):
        verify(policy, changed)


@pytest.mark.parametrize("which", ["HostConfig", "Config", "State", "NetworkSettings"])
def test_missing_each_required_field_denies(policy, which):
    original = record(policy)
    for name in original[which]:
        changed = copy.deepcopy(original)
        del changed[which][name]
        with pytest.raises(ValueError, match=r"^stock_container_unavailable$"):
            verify(policy, changed)


@pytest.mark.parametrize(
    "field,value",
    [
        ("release_id", "x" * 64),
        ("image_digest", "sha256:" + "0" * 64),
        ("compose_bytes", b"{}"),
        ("compose_sha256", "0" * 64),
        ("attestation_path", Path("/other")),
        ("compose_path", Path("/other")),
    ],
)
def test_request_cannot_rebind_or_replace_verified_release_model(policy, field, value):
    release, image = policy
    with pytest.raises(ValueError, match=r"^stock_container_unavailable$"):
        module().worker_request(replace(release, **{field: value}), image, ATTEMPT)


@pytest.mark.parametrize("attempt", ["", "e" * 31, "E" * 32, "../" + "e" * 29, True])
def test_attempt_name_is_generated_only_from_exact_random_id_syntax(attempt):
    with pytest.raises(ValueError, match=r"^stock_container_unavailable$"):
        module().container_name(attempt)


def test_create_response_requires_full_cid_and_no_warning():
    api = module()
    for empty in (None, []):
        assert api.verify_creation(encoded({"Id": CID, "Warnings": empty})) == CID
    for changed in (
        {"Id": CID[:12], "Warnings": []},
        {"Id": CID, "Warnings": ["limit discarded"]},
        {"Id": CID, "Warnings": False},
        {"Id": CID},
        {"Id": CID, "Warnings": [], "extra": True},
    ):
        with pytest.raises(ValueError, match=r"^stock_container_unavailable$"):
            api.verify_creation(encoded(changed))


@pytest.mark.parametrize(
    "raw",
    [
        b"{}",
        b"[]",
        b"null",
        b"{",
        b"\xff",
        b'{"Id":"first","Id":"second"}',
        b'{"ignored":1e999}',
        b'{"ignored":-1e999}',
        b'{"ignored":NaN}',
        b" " * 1048577,
    ],
    ids=[
        "empty",
        "array",
        "null",
        "incomplete",
        "utf8",
        "duplicate",
        "overflow",
        "negative-overflow",
        "nan",
        "over-budget",
    ],
)
def test_hostile_json_returns_fixed_denial(policy, raw):
    release, image = policy
    with pytest.raises(ValueError, match=r"^stock_container_unavailable$"):
        module().verify_created(
            raw, release=release, image=image, attempt_id=ATTEMPT, container_id=CID
        )


def test_documented_empty_optional_values_and_storage_metadata_do_not_bypass_checks(policy):
    changed = record(policy)
    for field in ("Annotations", "StorageOpt", "Sysctls"):
        changed["HostConfig"][field] = {}
    for field in ("ExposedPorts",):
        changed["Config"][field] = {}
    for field in ("ArgsEscaped", "NetworkDisabled"):
        changed["Config"][field] = False
    for field in ("OnBuild", "Shell"):
        changed["Config"][field] = []
    for field in ("GraphDriver", "Storage", "ImageManifestDescriptor"):
        changed[field] = {}
    assert len(changed["HostConfig"]) == 69
    assert verify(policy, changed).container_id == CID


def test_image_zero_start_interval_is_not_expected_in_native_omitempty_healthcheck(policy):
    release, image = policy
    health = json.loads(image.disabled_healthcheck)
    health["StartInterval"] = 0
    image = replace(image, disabled_healthcheck=encoded(health))
    api = module()
    request = json.loads(api.worker_request(release, image, ATTEMPT))
    assert "StartInterval" not in request["Healthcheck"]
    assert verify((release, image), record(policy)).container_id == CID


@pytest.mark.parametrize(
    "field,changed",
    [
        ("entrypoint", ["sh"]),
        ("command", ["--export-only"]),
        ("environment", {"LIVE_TRADING_ENABLED": "true"}),
        ("read_only", False),
        ("network_mode", "host"),
        ("volumes", []),
    ],
)
def test_rehashed_unsafe_compose_still_cannot_change_fixed_request(policy, field, changed):
    release, image = policy
    model = json.loads(release.compose_bytes)
    model["services"]["stock-research"][field] = changed
    body = encoded(model)
    release = replace(release, compose_bytes=body, compose_sha256=hashlib.sha256(body).hexdigest())
    with pytest.raises(ValueError, match=r"^stock_container_unavailable$"):
        module().worker_request(release, image, ATTEMPT)


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("HostConfig", "MaskedPaths", [*MASKS, MASKS[0]]),
        ("HostConfig", "MaskedPaths", [*MASKS, "/sys/devices/system/cpu/cpu01/thermal_throttle"]),
        ("HostConfig", "MaskedPaths", [*MASKS, "/other"]),
        ("HostConfig", "ReadonlyPaths", [*READONLY, "/other"]),
        ("HostConfig", "LogConfig", {"Type": "syslog", "Config": {}}),
        (
            "HostConfig",
            "LogConfig",
            {"Type": "json-file", "Config": {"max-size": "10m", "max-file": "3", "env": "GPG_KEY"}},
        ),
        ("HostConfig", "ConsoleSize", [False, 0]),
        ("HostConfig", "Tmpfs", {"/tmp": "size=1g,exec"}),
        ("Config", "Healthcheck", {"Test": ["CMD", "false"]}),
    ],
)
def test_masks_logs_and_nested_json_types_fail_closed(policy, section, field, value):
    changed = record(policy)
    changed[section][field] = value
    with pytest.raises(ValueError, match=r"^stock_container_unavailable$"):
        verify(policy, changed)
