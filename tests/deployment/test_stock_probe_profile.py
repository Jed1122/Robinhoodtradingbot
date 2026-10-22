"""Fictional inert profile substitution checks; never contacts Docker."""

import copy
import hashlib
import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_stock_prestart import ATTEMPT, CID, IMAGE, encoded, record
from test_stock_prestart import policy as worker_policy

from infra.hybrid.stock_prestart import worker_request

PROBE = "a" * 32


def module():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_probe_profile.py"
    assert path.is_file(), "The fixed inert stock probe profile is missing"
    return importlib.import_module("infra.hybrid.stock_probe_profile")


@pytest.fixture
def policy():
    return worker_policy.__wrapped__()


@pytest.fixture
def probe(policy):
    value = record(policy)
    value["Name"] = "/hybrid-stock-probe-" + PROBE
    value["Args"] = [
        "-m",
        "trading_bot.runtime.stock_research_identity",
        "--config-root",
        "/app/configs",
    ]
    value["NetworkSettings"] = {"SandboxID": "", "SandboxKey": "", "Ports": {}, "Networks": {}}
    value["Mounts"] = []
    config = value["Config"]
    config["Cmd"] = ["--config-root", "/app/configs"]
    config["Entrypoint"] = ["python", "-m", "trading_bot.runtime.stock_research_identity"]
    config["Labels"] = {
        "org.hybrid.stock.managed": "stock-configuration-probe",
        "org.hybrid.stock.probe": PROBE,
    }
    config["NetworkDisabled"] = True
    host = value["HostConfig"]
    del host["Mounts"], host["Tmpfs"]
    host["NetworkMode"] = "none"
    host["LogConfig"] = {"Type": "json-file", "Config": {"max-size": "1m", "max-file": "1"}}
    return policy[1], value


def verify(probe):
    image, value = probe
    return module().verify_probe_created(
        encoded(value), image=image, probe_id=PROBE, container_id=CID
    )


def test_request_is_exactly_the_inert_profile_and_contains_no_host_data(probe):
    image, value = probe
    expected = copy.deepcopy(value["Config"])
    expected["Hostname"] = ""
    host = copy.deepcopy(value["HostConfig"])
    host["MaskedPaths"] = host["ReadonlyPaths"] = None
    expected["HostConfig"] = host
    assert json.loads(module().probe_request(image, PROBE)) == expected
    assert module().probe_name(PROBE) == "hybrid-stock-probe-" + PROBE


def test_supplied_created_observation_returns_copied_identity_only(probe):
    result = verify(probe)
    assert (result.container_id, result.probe_id, result.image_digest) == (CID, PROBE, IMAGE)
    assert not hasattr(result, "start_fence")


def test_production_worker_request_keeps_its_prior_canonical_wire_identity(policy):
    raw = worker_request(*policy, ATTEMPT)
    assert (
        hashlib.sha256(raw).hexdigest()
        == "75438f69c605f0ec5edf4154ca2f534f665dd6238cb70a1dd7052d5c29aac2a9"
    )
    value = json.loads(raw)
    assert value["HostConfig"]["NetworkMode"] == "bridge"
    assert len(value["HostConfig"]["Mounts"]) == 6


@pytest.mark.parametrize(
    "path,replacement",
    [
        (("Id",), "e" * 64),
        (("Image",), "sha256:" + "e" * 64),
        (("Name",), "/hybrid-stock-research-" + PROBE),
        (("Path",), "sh"),
        (("Args",), ["-m", "trading_bot.runtime.stock_research_worker"]),
        (("Created",), "invalid"),
        (("Created",), "1969-01-01T00:00:00Z"),
        (("Driver",), ""),
        (("LogPath",), "bad\x00path"),
        (("Platform",), "windows"),
        (("RestartCount",), True),
        (("ExecIDs",), ["unexpected"]),
        (("GraphDriver",), []),
        (("Mounts",), [{"Type": "bind", "Source": "/host", "Destination": "/data"}]),
        (("Mounts",), None),
        (("State", "Status"), "running"),
        (("State", "Running"), True),
        (("State", "Pid"), 1),
        (("State", "StartedAt"), "2026-10-21T20:00:00Z"),
        (("State", "OOMKilled"), 0),
        (("NetworkSettings", "Networks"), {"none": {}}),
        (("NetworkSettings", "Ports"), {"80/tcp": None}),
        (("NetworkSettings", "SandboxID"), "e" * 64),
        (("Config", "NetworkDisabled"), False),
        (("Config", "NetworkDisabled"), 1),
        (("Config", "User"), "0:0"),
        (("Config", "WorkingDir"), "/tmp"),
        (("Config", "Tty"), True),
        (("Config", "OpenStdin"), True),
        (("Config", "Entrypoint"), ["sh", "-c"]),
        (("Config", "Cmd"), []),
        (("Config", "Volumes"), {"/data": {}}),
        (("Config", "Labels", "org.hybrid.stock.probe"), "b" * 32),
        (("Config", "Env"), ["LIVE_TRADING_ENABLED=true"]),
        (("Config", "Healthcheck", "Test"), ["CMD", "python"]),
        (("HostConfig", "NetworkMode"), "bridge"),
        (("HostConfig", "Privileged"), True),
        (("HostConfig", "AutoRemove"), True),
        (("HostConfig", "ReadonlyRootfs"), False),
        (("HostConfig", "RestartPolicy", "Name"), "always"),
        (("HostConfig", "Binds"), ["/host:/data"]),
        (("HostConfig", "Mounts"), [{"Type": "bind", "Source": "/host", "Target": "/data"}]),
        (("HostConfig", "Mounts"), None),
        (("HostConfig", "Tmpfs"), {"/tmp": "size=32m"}),
        (("HostConfig", "Tmpfs"), None),
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
        (("UnknownTopLevel",), True),
    ],
)
def test_untrusted_configuration_or_identity_substitutions_deny(probe, path, replacement):
    target = probe[1]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    with pytest.raises(ValueError, match=r"^stock_probe_profile_unavailable$"):
        verify(probe)


@pytest.mark.parametrize(
    "field", ["Id", "Image", "Name", "State", "Config", "HostConfig", "Mounts", "NetworkSettings"]
)
def test_missing_essential_observations_deny(probe, field):
    del probe[1][field]
    with pytest.raises(ValueError, match=r"^stock_probe_profile_unavailable$"):
        verify(probe)


def test_missing_disabled_network_flag_is_not_assumed_true(probe):
    del probe[1]["Config"]["NetworkDisabled"]
    with pytest.raises(ValueError, match=r"^stock_probe_profile_unavailable$"):
        verify(probe)


def test_only_named_empty_mount_field_normalizations_are_accepted(probe):
    probe[1]["HostConfig"].update(Mounts=[], Tmpfs={})
    probe[1]["Config"]["Volumes"] = None
    assert verify(probe).container_id == CID


@pytest.mark.parametrize("probe_id", [None, "", "a" * 31, "A" * 32, "../unsafe", True])
def test_bad_probe_identity_cannot_produce_request(probe, probe_id):
    with pytest.raises(ValueError, match=r"^stock_probe_profile_unavailable$"):
        module().probe_request(probe[0], probe_id)


@pytest.mark.parametrize(
    "updates",
    [
        {"image_digest": "latest"},
        {"architecture": "other"},
        {"environment": ("LIVE_TRADING_ENABLED=true",)},
        {"disabled_healthcheck": b'{"Test":["NONE"]}'},
    ],
)
def test_a_fabricated_image_profile_does_not_skip_its_checks(probe, updates):
    with pytest.raises(ValueError, match=r"^stock_probe_profile_unavailable$"):
        module().probe_request(replace(probe[0], **updates), PROBE)
