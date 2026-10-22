"""Supplied fictional probe ownership/lifetimes; no Engine operations or authority."""

import copy
import importlib
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from test_stock_prestart import CID, IMAGE, encoded
from test_stock_probe_profile import PROBE
from test_stock_probe_profile import policy as probe_policy
from test_stock_probe_profile import probe as inherited_probe

ZERO = "0001-01-01T00:00:00Z"
START = "2026-10-21T21:00:01.123456789Z"
FINISH = "2026-10-21T21:00:02.000000001Z"


def module():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_probe_observation.py"
    assert path.is_file(), "The pure stock probe lifecycle observation is missing"
    return importlib.import_module("infra.hybrid.stock_probe_observation")


@pytest.fixture
def policy():
    return probe_policy.__wrapped__()


@pytest.fixture
def probe(policy):
    return inherited_probe.__wrapped__(policy)


def record(status="created"):
    state = {
        "Status": status,
        "Running": status == "running",
        "Paused": False,
        "Restarting": False,
        "OOMKilled": False,
        "Dead": status == "dead",
        "Pid": 200 if status == "running" else 0,
        "ExitCode": 0,
        "Error": "",
        "StartedAt": ZERO if status == "created" else START,
        "FinishedAt": FINISH if status in ("exited", "dead") else ZERO,
    }
    return {
        "Id": CID,
        "Image": IMAGE,
        "Name": "/hybrid-stock-probe-" + PROBE,
        "Platform": "linux",
        "RestartCount": 0,
        "Config": {
            "Labels": {
                "org.hybrid.stock.managed": "stock-configuration-probe",
                "org.hybrid.stock.probe": PROBE,
            }
        },
        "HostConfig": {
            "AutoRemove": False,
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
        },
        "State": state,
    }


def observe(value, **overrides):
    arguments = {"probe_id": PROBE, "container_id": CID, "image_digest": IMAGE, **overrides}
    return module().observe_probe(encoded(value), **arguments)


@pytest.mark.parametrize("status", ["created", "running", "exited", "dead"])
def test_copied_data_describes_owned_native_state_without_dispatch_authority(status):
    value = record(status)
    actual = observe(value)
    assert (actual.probe_id, actual.container_id, actual.image_digest) == (PROBE, CID, IMAGE)
    assert (actual.status, actual.pid, actual.exit_code) == (status, value["State"]["Pid"], 0)
    assert (actual.oom_killed, actual.error_present) == (False, False)
    assert actual.container_started_at == value["State"]["StartedAt"]
    assert actual.container_finished_at == value["State"]["FinishedAt"]
    assert not hasattr(actual, "start_fence") and not hasattr(actual, "raw")
    with pytest.raises(FrozenInstanceError):
        actual.status = "running"
    assert replace(actual) == actual and replace(actual) is not actual
    value["State"]["Error"] = "later change"
    assert actual.error_present is False


@pytest.mark.parametrize("status", ["created", "running", "exited", "dead"])
def test_failure_facts_are_retained_for_cleanup_without_error_text(status):
    value = record(status)
    value["State"].update(Error="sensitive fictional diagnostic", OOMKilled=True, ExitCode=137)
    actual = observe(value)
    assert actual.error_present and actual.oom_killed and actual.exit_code == 137
    assert "sensitive" not in repr(actual)


def test_native_failed_start_can_still_have_created_status():
    value = record()
    value["State"].update(FinishedAt=FINISH, ExitCode=128, Error="fictional start failure")
    actual = observe(value)
    assert actual.status == "created" and actual.container_started_at == ZERO
    assert (
        actual.container_finished_at == FINISH and actual.exit_code == 128 and actual.error_present
    )


@pytest.mark.parametrize("finished", [ZERO, "2026-10-21T21:00:00.9Z", START, FINISH])
def test_running_native_observation_may_retain_earlier_finish_time(finished):
    value = record("running")
    value["State"]["FinishedAt"] = finished
    assert observe(value).status == "running"


@pytest.mark.parametrize("finished", [ZERO, FINISH])
def test_dead_can_describe_owned_never_started_resource(finished):
    value = record("dead")
    value["State"].update(StartedAt=ZERO, FinishedAt=finished)
    assert observe(value).status == "dead"


@pytest.mark.parametrize(
    "path,replacement",
    [
        (("Id",), "e" * 64),
        (("Id",), CID[:12]),
        (("Image",), "sha256:" + "e" * 64),
        (("Name",), "/hybrid-stock-research-" + PROBE),
        (("Name",), "hybrid-stock-probe-" + PROBE),
        (("Platform",), "windows"),
        (("RestartCount",), True),
        (("RestartCount",), 1),
        (("Config",), []),
        (("Config", "Labels"), None),
        (("Config", "Labels", "org.hybrid.stock.managed"), "stock-research"),
        (("Config", "Labels", "org.hybrid.stock.probe"), "e" * 32),
        (("Config", "Labels", "unexpected"), "value"),
        (("HostConfig",), []),
        (("HostConfig", "AutoRemove"), True),
        (("HostConfig", "AutoRemove"), 0),
        (("HostConfig", "RestartPolicy"), {"Name": "no", "MaximumRetryCount": False}),
        (("HostConfig", "RestartPolicy"), {"Name": "always", "MaximumRetryCount": 0}),
        (("HostConfig", "RestartPolicy"), {"Name": "no", "MaximumRetryCount": 0, "Extra": 1}),
        (("State",), []),
        (("State", "Extra"), 1),
    ],
)
def test_ownership_and_policy_substitution_denies(path, replacement):
    value = record()
    target = value
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = replacement
    with pytest.raises(ValueError, match=r"^stock_probe_observation_unavailable$"):
        observe(value)


@pytest.mark.parametrize(
    "key", [*record(), "State.Status", "Config.Labels", "HostConfig.AutoRemove"]
)
def test_missing_required_fact_denies(key):
    value = record()
    target = value
    parts = key.split(".")
    for part in parts[:-1]:
        target = target[part]
    del target[parts[-1]]
    with pytest.raises(ValueError, match=r"^stock_probe_observation_unavailable$"):
        observe(value)


@pytest.mark.parametrize("key", ["Running", "Paused", "Restarting", "OOMKilled", "Dead"])
@pytest.mark.parametrize("invalid", [0, 1, None, "false", [], {}])
def test_state_boolean_types_are_exact(key, invalid):
    value = record()
    value["State"][key] = invalid
    with pytest.raises(ValueError):
        observe(value)


@pytest.mark.parametrize("key", ["Pid", "ExitCode"])
@pytest.mark.parametrize("invalid", [True, False, -1, 2**63, 1.0, "0", None])
def test_state_integer_types_and_bounds_are_exact(key, invalid):
    value = record()
    value["State"][key] = invalid
    with pytest.raises(ValueError):
        observe(value)


@pytest.mark.parametrize("code", [256, 65535])
def test_unrepresentable_process_exit_code_denies(code):
    value = record("exited")
    value["State"]["ExitCode"] = code
    with pytest.raises(ValueError):
        observe(value)


@pytest.mark.parametrize("invalid", [None, False, 1, [], {}, "x" * 4097])
def test_error_scalar_is_bounded_and_sanitized(invalid):
    value = record()
    value["State"]["Error"] = invalid
    with pytest.raises(ValueError, match=r"^stock_probe_observation_unavailable$"):
        observe(value)


@pytest.mark.parametrize(
    "status", ["paused", "restarting", "removing", "unknown", "", None, True, {}, []]
)
def test_unsupported_state_denies(status):
    value = record()
    value["State"]["Status"] = status
    with pytest.raises(ValueError):
        observe(value)


@pytest.mark.parametrize("status", ["created", "running", "exited", "dead"])
@pytest.mark.parametrize("field", ["Running", "Dead", "Paused", "Restarting"])
def test_status_flag_contradictions_deny(status, field):
    value = record(status)
    value["State"][field] = not value["State"][field]
    with pytest.raises(ValueError):
        observe(value)


@pytest.mark.parametrize("status,pid", [("created", 1), ("exited", 1), ("dead", 1), ("running", 0)])
def test_pid_must_match_observed_lifecycle(status, pid):
    value = record(status)
    value["State"]["Pid"] = pid
    with pytest.raises(ValueError):
        observe(value)


@pytest.mark.parametrize("field", ["StartedAt", "FinishedAt"])
@pytest.mark.parametrize(
    "invalid",
    [
        None,
        0,
        False,
        [],
        {},
        "",
        "2026-10-21",
        "1969-01-01T00:00:00Z",
        "2026-02-30T00:00:00Z",
        "2026-10-21T00:00:00+00:00",
        "2026-10-21T00:00:00.1234567890Z",
        "2026-10-21T24:00:00Z",
        "0001-01-01T00:00:00.0Z",
    ],
)
def test_lifetimes_are_native_bounded_utc_timestamps(field, invalid):
    value = record("exited")
    value["State"][field] = invalid
    with pytest.raises(ValueError):
        observe(value)


@pytest.mark.parametrize(
    "status,started,finished",
    [
        ("created", START, ZERO),
        ("running", ZERO, ZERO),
        ("exited", ZERO, FINISH),
        ("exited", START, ZERO),
    ],
)
def test_status_lifetime_contradiction_denies(status, started, finished):
    value = record(status)
    value["State"].update(StartedAt=started, FinishedAt=finished)
    with pytest.raises(ValueError):
        observe(value)


@pytest.mark.parametrize(
    "timestamp",
    ["2026-10-21T21:00:01Z", "2026-10-21T21:00:01.1Z", "2026-10-21T21:00:01.123456789Z"],
)
def test_valid_nanosecond_lifetimes_are_retained_exactly(timestamp):
    value = record("exited")
    value["State"].update(StartedAt=timestamp, FinishedAt=timestamp)
    assert observe(value).container_finished_at == timestamp


@pytest.mark.parametrize("key", ["probe_id", "container_id", "image_digest"])
@pytest.mark.parametrize("invalid", [None, True, "", "x", [], {}, "A" * 64])
def test_supplied_identity_is_checked(key, invalid):
    with pytest.raises(ValueError, match=r"^stock_probe_observation_unavailable$"):
        observe(record(), **{key: invalid})


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{}",
        b"[]",
        b"null",
        b"\xff",
        b'{"State":NaN}',
        b'{"State":1e1000}',
        b'{"Id":1,"Id":2}',
        b"{} trailing",
        b" " * 1048577,
        None,
        "{}",
    ],
    ids=[
        "empty",
        "missing",
        "list",
        "null",
        "utf8",
        "nan",
        "overflow",
        "duplicate",
        "trailing",
        "oversized",
        "none",
        "string",
    ],
)
def test_bad_json_and_bounds_deny_without_payload_disclosure(raw):
    with pytest.raises(ValueError, match=r"^stock_probe_observation_unavailable$"):
        module().observe_probe(raw, probe_id=PROBE, container_id=CID, image_digest=IMAGE)


def test_cleanup_observation_does_not_replace_strict_prestart_policy(probe):
    image, value = probe
    value = copy.deepcopy(value)
    value["HostConfig"]["ReadonlyRootfs"] = False
    assert observe(value).status == "created"
    profile = importlib.import_module("infra.hybrid.stock_probe_profile")
    with pytest.raises(ValueError, match=r"^stock_probe_profile_unavailable$"):
        profile.verify_probe_created(encoded(value), image=image, probe_id=PROBE, container_id=CID)
    assert json.loads(encoded(value))["HostConfig"]["ReadonlyRootfs"] is False


@pytest.mark.parametrize("status", ["running", "exited", "dead"])
def test_wall_clock_reversal_retains_facts_for_cleanup_not_success(status):
    value = record(status)
    value["State"].update(StartedAt=FINISH, FinishedAt=START)
    actual = observe(value)
    assert actual.container_started_at == FINISH and actual.container_finished_at == START
    assert not hasattr(actual, "succeeded") and not hasattr(actual, "remove_fence")


def test_dead_preserves_lifetime_even_if_finish_was_not_recorded():
    value = record("dead")
    value["State"]["FinishedAt"] = ZERO
    assert observe(value).container_finished_at == ZERO
