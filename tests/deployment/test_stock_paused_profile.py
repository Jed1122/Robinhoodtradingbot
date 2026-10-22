"""Fictional never-started paused acceptance metadata; never contacts Docker."""

import copy
import hashlib
import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_stock_prestart import ATTEMPT, CID, IMAGE, RELEASE, encoded, record
from test_stock_prestart import policy as worker_policy

from infra.hybrid.stock_prestart import worker_request

CHECK = "a" * 32
DENIAL = r"^stock_paused_profile_unavailable$"


def module():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_paused_profile.py"
    assert path.is_file(), "The pure stock paused-check profile is missing"
    return importlib.import_module("infra.hybrid.stock_paused_profile")


@pytest.fixture
def policy():
    return worker_policy.__wrapped__()


@pytest.fixture
def paused(policy):
    value = record(policy)
    value["Name"] = "/hybrid-stock-paused-check-" + CHECK
    value["Config"]["Labels"] = {
        "org.hybrid.stock.managed": "stock-paused-check",
        "org.hybrid.stock.release": RELEASE,
        "org.hybrid.stock.probe": CHECK,
    }
    value["Config"]["NetworkDisabled"] = True
    value["HostConfig"]["NetworkMode"] = "none"
    value["HostConfig"]["Mounts"].pop(4)
    value["Mounts"].pop(4)
    value["NetworkSettings"] = {"SandboxID": "", "SandboxKey": "", "Ports": {}, "Networks": {}}
    return value


def verify(policy, value, *, check_id=CHECK, container_id=CID):
    return module().verify_paused_created(
        encoded(value),
        release=policy[0],
        image=policy[1],
        check_id=check_id,
        container_id=container_id,
    )


def test_request_keeps_fixed_worker_and_five_mounts_without_oauth(policy, paused):
    request = json.loads(module().paused_request(*policy, CHECK))
    expected = copy.deepcopy(paused["Config"])
    expected["Hostname"] = ""
    expected["HostConfig"] = copy.deepcopy(paused["HostConfig"])
    expected["HostConfig"]["MaskedPaths"] = None
    expected["HostConfig"]["ReadonlyPaths"] = None
    assert request == expected
    assert module().paused_name(CHECK) == "hybrid-stock-paused-check-" + CHECK
    assert len(request["HostConfig"]["Mounts"]) == 5
    assert {mount["Target"] for mount in request["HostConfig"]["Mounts"]} == {
        "/stock-state",
        "/stock-archive",
        "/stock-controls",
        "/stock-exports",
        "/run/trading-bot/stock-image-attestation.json",
    }
    production = json.loads(worker_request(*policy, CHECK))
    assert request["Entrypoint"] == production["Entrypoint"]
    assert request["Cmd"] == production["Cmd"]
    assert "--oauth-store" in request["Cmd"] and "/stock-oauth" in request["Cmd"]
    assert module().paused_request(*policy, CHECK) == encoded(request)


def test_complete_created_observation_returns_only_copied_release_identity(policy, paused):
    result = verify(policy, paused)
    assert (result.container_id, result.check_id, result.release_id) == (CID, CHECK, RELEASE)
    assert (result.image_digest, result.config_hash, result.compose_sha256) == (
        IMAGE,
        policy[0].config_hash,
        policy[0].compose_sha256,
    )
    assert not hasattr(result, "start_fence")
    assert "Env" not in repr(result) and "HostConfig" not in repr(result)


def test_production_request_identity_and_six_mount_policy_remain_unchanged(policy):
    raw = worker_request(*policy, ATTEMPT)
    assert hashlib.sha256(raw).hexdigest() == (
        "75438f69c605f0ec5edf4154ca2f534f665dd6238cb70a1dd7052d5c29aac2a9"
    )
    request = json.loads(raw)
    assert request["HostConfig"]["NetworkMode"] == "bridge"
    assert len(request["HostConfig"]["Mounts"]) == 6
    assert "NetworkDisabled" not in request


@pytest.mark.parametrize(
    "path,replacement",
    [
        (("Id",), CID[:12]),
        (("Id",), "e" * 64),
        (("Name",), "/hybrid-stock-research-" + CHECK),
        (("Name",), "/hybrid-stock-paused-check-" + "b" * 32),
        (("Image",), "sha256:" + "e" * 64),
        (("Path",), "sh"),
        (("Args",), ["-m", "trading_bot.runtime.stock_research_identity"]),
        (("Created",), "2026-10-22T24:00:00Z"),
        (("Created",), "1969-12-31T23:59:59Z"),
        (("Driver",), ""),
        (("LogPath",), "bad\x00path"),
        (("Platform",), "windows"),
        (("RestartCount",), True),
        (("ExecIDs",), ["exec-id"]),
        (("AppArmorProfile",), "unconfined"),
        (("GraphDriver",), []),
        (("State", "Status"), "exited"),
        (("State", "Running"), True),
        (("State", "Paused"), True),
        (("State", "Restarting"), True),
        (("State", "OOMKilled"), 0),
        (("State", "Dead"), True),
        (("State", "Pid"), 1),
        (("State", "ExitCode"), 2),
        (("State", "Error"), "failed earlier start"),
        (("State", "StartedAt"), "2026-10-22T20:00:00Z"),
        (("State", "FinishedAt"), "2026-10-22T20:00:00Z"),
        (("State", "Health"), {"Status": "starting"}),
        (("Config", "NetworkDisabled"), False),
        (("Config", "NetworkDisabled"), 1),
        (("Config", "Image"), "sha256:" + "e" * 64),
        (("Config", "Hostname"), "other"),
        (("Config", "User"), "0:0"),
        (("Config", "WorkingDir"), "/tmp"),
        (("Config", "Tty"), True),
        (("Config", "OpenStdin"), True),
        (("Config", "Entrypoint"), ["python", "-m", "other"]),
        (("Config", "Cmd"), ["--export-only"]),
        (("Config", "Env"), ["LIVE_TRADING_ENABLED=true"]),
        (("Config", "Healthcheck", "Test"), ["CMD", "true"]),
        (("Config", "Volumes"), {"/stock-oauth": {}}),
        (("Config", "Labels", "org.hybrid.stock.managed"), "stock-research"),
        (("Config", "Labels", "org.hybrid.stock.release"), "e" * 64),
        (("Config", "Labels", "org.hybrid.stock.probe"), "b" * 32),
        (("Config", "Labels", "org.hybrid.stock.attempt"), CHECK),
        (("Config", "StopTimeout"), True),
        (("Config", "StopSignal"), "SIGKILL"),
        (("HostConfig", "NetworkMode"), "bridge"),
        (("HostConfig", "Privileged"), True),
        (("HostConfig", "AutoRemove"), True),
        (("HostConfig", "ReadonlyRootfs"), False),
        (("HostConfig", "RestartPolicy", "Name"), "always"),
        (("HostConfig", "Binds"), ["/private:/stock-oauth"]),
        (("HostConfig", "Tmpfs"), {"/tmp": "size=1g,exec"}),
        (("HostConfig", "SecurityOpt"), []),
        (("HostConfig", "CapDrop"), []),
        (("HostConfig", "CapAdd"), ["NET_ADMIN"]),
        (("HostConfig", "PortBindings"), {"80/tcp": []}),
        (("HostConfig", "IpcMode"), "host"),
        (("HostConfig", "CgroupnsMode"), "host"),
        (("HostConfig", "Init"), False),
        (("HostConfig", "PidsLimit"), 129),
        (("HostConfig", "Memory"), 536870912.0),
        (("HostConfig", "MemorySwap"), -1),
        (("HostConfig", "NanoCpus"), 1000000000),
        (("HostConfig", "ShmSize"), 0),
        (("HostConfig", "LogConfig", "Type"), "none"),
        (("HostConfig", "LogConfig", "Config"), {}),
        (("HostConfig", "MaskedPaths"), []),
        (("HostConfig", "ReadonlyPaths"), []),
        (("HostConfig", "Devices"), [{}]),
        (("HostConfig", "UnknownUnsafe"), True),
        (("NetworkSettings", "Networks"), {"none": {}}),
        (("NetworkSettings", "Networks"), {"bridge": {}}),
        (("NetworkSettings", "Ports"), {"80/tcp": None}),
        (("NetworkSettings", "SandboxID"), "e" * 64),
        (("NetworkSettings", "SandboxKey"), "/var/run/netns/other"),
        (("UnknownTopLevel",), True),
    ],
)
def test_configuration_command_resources_state_and_network_drift_deny(
    policy, paused, path, replacement
):
    target = paused
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    with pytest.raises(ValueError, match=DENIAL):
        verify(policy, paused)


@pytest.mark.parametrize("which", ["request", "resolved"])
@pytest.mark.parametrize(
    "change",
    ["oauth", "extra", "missing", "duplicate", "source", "writable", "propagation", "option"],
)
def test_request_and_resolved_mounts_must_be_exact_without_oauth(policy, paused, which, change):
    requested = which == "request"
    mounts = paused["HostConfig"]["Mounts"] if requested else paused["Mounts"]
    if change == "oauth":
        production = record(policy)
        original = production["HostConfig"]["Mounts"] if requested else production["Mounts"]
        mounts.append(original[4])
    elif change == "extra":
        mounts.append({"Type": "volume", "Target" if requested else "Destination": "/other"})
    elif change == "missing":
        mounts.pop()
    elif change == "duplicate":
        mounts[-1] = copy.deepcopy(mounts[0])
    elif change == "source":
        mounts[0]["Source"] = "/other"
    elif change == "writable":
        mounts[-1]["ReadOnly" if requested else "RW"] = not requested
    elif change == "propagation":
        if requested:
            mounts[0]["BindOptions"]["Propagation"] = "rslave"
        else:
            mounts[0]["Propagation"] = "rslave"
    elif requested:
        mounts[0]["BindOptions"]["CreateMountpoint"] = True
    else:
        mounts[0]["Driver"] = "other"
    with pytest.raises(ValueError, match=DENIAL):
        verify(policy, paused)


@pytest.mark.parametrize("which", [None, "Config", "HostConfig", "State", "NetworkSettings"])
def test_missing_required_observation_cannot_be_assumed_safe(policy, paused, which):
    original = paused if which is None else paused[which]
    for field in original:
        changed = copy.deepcopy(paused)
        del (changed if which is None else changed[which])[field]
        with pytest.raises(ValueError, match=DENIAL):
            verify(policy, changed)


def test_named_empty_native_normalizations_and_unordered_mounts_remain_eligible(policy, paused):
    paused["HostConfig"]["Mounts"].reverse()
    paused["Mounts"].reverse()
    paused["Config"]["Volumes"] = None
    for name in ("Annotations", "StorageOpt", "Sysctls"):
        paused["HostConfig"][name] = {}
    for name in ("Binds", "VolumesFrom", "Devices"):
        paused["HostConfig"][name] = []
    paused["HostConfig"]["MaskedPaths"].append("/sys/devices/system/cpu/cpu0/thermal_throttle")
    assert verify(policy, paused).container_id == CID


@pytest.mark.parametrize("check_id", [None, "", "a" * 31, "A" * 32, "../unsafe", True])
def test_bad_check_identity_denies_request_name_and_comparison(policy, paused, check_id):
    api = module()
    with pytest.raises(ValueError, match=DENIAL):
        api.paused_name(check_id)
    with pytest.raises(ValueError, match=DENIAL):
        api.paused_request(*policy, check_id)
    with pytest.raises(ValueError, match=DENIAL):
        verify(policy, paused, check_id=check_id)


@pytest.mark.parametrize("container_id", [None, CID[:12], "F" * 64, True])
def test_supplied_container_identity_must_be_a_full_lowercase_cid(policy, paused, container_id):
    with pytest.raises(ValueError, match=DENIAL):
        verify(policy, paused, container_id=container_id)


@pytest.mark.parametrize(
    "updates",
    [
        {"release_id": "x" * 64},
        {"image_digest": "sha256:" + "e" * 64},
        {"config_hash": "x" * 64},
        {"compose_bytes": b"{}"},
        {"compose_sha256": "0" * 64},
        {"attestation_path": Path("/other")},
        {"compose_path": Path("/other")},
    ],
)
def test_fabricated_release_does_not_bypass_production_policy_checks(policy, paused, updates):
    changed = replace(policy[0], **updates), policy[1]
    with pytest.raises(ValueError, match=DENIAL):
        module().paused_request(*changed, CHECK)
    with pytest.raises(ValueError, match=DENIAL):
        verify(changed, paused)


@pytest.mark.parametrize(
    "updates",
    [
        {"image_digest": "latest"},
        {"architecture": "other"},
        {"environment": ("LIVE_TRADING_ENABLED=true",)},
        {"disabled_healthcheck": b'{"Test":["NONE"]}'},
    ],
)
def test_fabricated_image_does_not_bypass_production_policy_checks(policy, paused, updates):
    changed = policy[0], replace(policy[1], **updates)
    with pytest.raises(ValueError, match=DENIAL):
        module().paused_request(*changed, CHECK)
    with pytest.raises(ValueError, match=DENIAL):
        verify(changed, paused)


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
        b'{"ignored":NaN}',
        b" " * 1048577,
    ],
)
def test_hostile_json_returns_only_fixed_denial(policy, raw):
    with pytest.raises(ValueError, match=DENIAL):
        module().verify_paused_created(
            raw, release=policy[0], image=policy[1], check_id=CHECK, container_id=CID
        )
