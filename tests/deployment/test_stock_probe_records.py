"""Exact fictional receipt schemas; supplied records are data, never fences."""

import copy
import importlib
import json

import pytest

NAMESPACE, PROBE, HASH, CID = "a" * 32, "b" * 32, "c" * 64, "d" * 64
IMAGE = "sha256:" + "e" * 64
BOOT = "11111111-2222-4333-8444-555555555555"
NOW = 1000000000000
ZERO = "0001-01-01T00:00:00Z"


def module():
    api = importlib.import_module("infra.hybrid.stock_probe_store")
    assert callable(getattr(api, "_decode_receipt", None)), (
        "Exact probe receipt validation is missing"
    )
    return api


def encoded(value):
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def records():
    specific = {
        "intent": {
            "profile_version": 1,
            "image_digest": IMAGE,
            "engine_sha256": HASH,
            "engine_size": 10,
            "image_sha256": HASH,
            "image_size": 10,
            "request_sha256": HASH,
            "request_size": 10,
            "setup_started_ns": NOW - 1000000000,
            "setup_deadline_ns": NOW + 19000000000,
            "predecessor_probe_id": None,
            "predecessor_closed_sha256": None,
        },
        "create": {"request_sha256": HASH, "dispatch_deadline_ns": NOW + 5000000000},
        "cid": {
            "create_sha256": HASH,
            "container_id": CID,
            "evidence_kind": "create_response",
            "observation_sha256": HASH,
            "observation_size": 10,
        },
        "created": {"cid_sha256": HASH, "prestart_sha256": HASH, "prestart_size": 10},
        "start": {
            "created_sha256": HASH,
            "container_id": CID,
            "run_deadline_ns": NOW + 30000000000,
        },
        "stopped": {
            "container_id": CID,
            "start_sha256": HASH,
            "inspection_sha256": HASH,
            "inspection_size": 10,
            "status": "exited",
            "exit_code": 0,
            "oom_killed": False,
            "error_present": False,
            "container_started_at": "2026-10-21T21:00:00.123456789Z",
            "container_finished_at": "2026-10-21T21:00:01.123456789Z",
        },
        "output": {
            "stopped_sha256": HASH,
            "framed_sha256": HASH,
            "framed_size": 10,
            "status": "valid",
            "canonical_sha256": HASH,
            "canonical_size": 10,
        },
        "removal-intent": {
            "container_id": CID,
            "stopped_sha256": HASH,
            "retirement_deadline_ns": NOW + 15000000000,
        },
        "removed": {"removal_intent_sha256": HASH, "evidence_kind": "delete_204"},
        "closed": {
            "outcome": "succeeded",
            "reason": "completed",
            "output_sha256": HASH,
            "removed_sha256": HASH,
        },
    }
    return {
        name + ".json": {
            "schema_version": 1,
            "kind": "stock_probe_" + name.replace("-", "_"),
            "namespace_id": NAMESPACE,
            "probe_id": PROBE,
            "intent_sha256": None if name == "intent" else HASH,
            "boot_id": BOOT,
            "utc": "2026-10-21T21:00:00+00:00",
            "monotonic_ns": NOW,
            **fields,
        }
        for name, fields in specific.items()
    }


def decode(name, value, **override):
    arguments = {
        "namespace_id": NAMESPACE,
        "probe_id": PROBE,
        "intent_sha256": None if name == "intent.json" else HASH,
        **override,
    }
    return module()._decode_receipt(encoded(value), name, **arguments)


@pytest.mark.parametrize("name", list(records()))
def test_exact_receipt_is_copied_data_with_no_execution_authority(name):
    value = records()[name]
    result = decode(name, value)
    assert result == value and result is not value
    assert type(result) is dict and "fence" not in result


@pytest.mark.parametrize(
    "name,field", [(name, field) for name, value in records().items() for field in value]
)
def test_every_required_field_must_be_present(name, field):
    value = records()[name]
    del value[field]
    with pytest.raises(ValueError, match=r"^stock_probe_store_unavailable$"):
        decode(name, value)


@pytest.mark.parametrize("name", list(records()))
def test_unknown_receipt_field_denies(name):
    value = records()[name]
    value["unexpected"] = True
    with pytest.raises(ValueError):
        decode(name, value)


@pytest.mark.parametrize(
    "name,field",
    [
        (name, field)
        for name, value in records().items()
        for field, item in value.items()
        if type(item) is int
    ],
)
@pytest.mark.parametrize("invalid", [True, False, -1, 2**63, 1.0, "1", None])
def test_integer_fields_are_exact_and_bounded(name, field, invalid):
    value = records()[name]
    value[field] = invalid
    with pytest.raises(ValueError):
        decode(name, value)


@pytest.mark.parametrize(
    "name,field",
    [
        (name, field)
        for name, value in records().items()
        for field, item in value.items()
        if field.endswith("sha256") and item is not None
    ],
)
@pytest.mark.parametrize("invalid", ["f" * 63, "G" * 64, None, True, []])
def test_hash_fields_are_exact_lowercase_digest_strings(name, field, invalid):
    value = records()[name]
    value[field] = invalid
    if name == "stopped.json" and field == "start_sha256" and invalid is None:
        # An owned cleanup observation may have no local START fence.
        assert decode(name, value)["start_sha256"] is None
        return
    with pytest.raises(ValueError):
        decode(name, value)


@pytest.mark.parametrize("name", list(records()))
@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "stock_attempt_start"),
        ("namespace_id", "f" * 32),
        ("probe_id", "f" * 32),
        ("boot_id", "invalid"),
        ("utc", "2026-10-21"),
        ("utc", "2026-10-21T21:00:00-04:00"),
    ],
)
def test_record_identity_and_clock_substitutions_deny(name, field, value):
    body = records()[name]
    body[field] = value
    with pytest.raises(ValueError):
        decode(name, body)


@pytest.mark.parametrize(
    "name,changes",
    [
        ("intent.json", {"profile_version": 2}),
        ("intent.json", {"intent_sha256": HASH}),
        ("intent.json", {"image_digest": "tag:latest"}),
        ("intent.json", {"setup_started_ns": NOW + 1}),
        ("intent.json", {"setup_deadline_ns": NOW + 20000000000}),
        ("intent.json", {"setup_deadline_ns": NOW}),
        ("intent.json", {"predecessor_probe_id": "f" * 32}),
        ("intent.json", {"predecessor_closed_sha256": HASH}),
        ("create.json", {"dispatch_deadline_ns": NOW}),
        ("create.json", {"dispatch_deadline_ns": NOW + 5000000001}),
        ("cid.json", {"container_id": CID[:12]}),
        ("cid.json", {"evidence_kind": "lookup"}),
        ("cid.json", {"observation_size": 4097}),
        ("start.json", {"run_deadline_ns": NOW + 30000000001}),
        ("stopped.json", {"status": "running"}),
        ("stopped.json", {"exit_code": 256}),
        ("stopped.json", {"oom_killed": 0}),
        ("stopped.json", {"error_present": 0}),
        ("stopped.json", {"status": "created"}),
        ("stopped.json", {"container_started_at": ZERO}),
        ("stopped.json", {"container_finished_at": ZERO}),
        ("stopped.json", {"container_started_at": "2026-02-30T00:00:00Z"}),
        ("output.json", {"status": "unknown"}),
        ("output.json", {"status": "invalid"}),
        ("output.json", {"framed_size": 16385}),
        ("output.json", {"canonical_size": 4097}),
        ("removal-intent.json", {"retirement_deadline_ns": NOW + 15000000001}),
        ("removed.json", {"evidence_kind": "name_404"}),
        ("closed.json", {"outcome": "unknown"}),
        ("closed.json", {"reason": "unknown"}),
        ("closed.json", {"reason": "recovery"}),
        ("closed.json", {"removed_sha256": None}),
    ],
)
def test_invalid_record_specific_combinations_deny(name, changes):
    value = records()[name]
    value.update(changes)
    with pytest.raises(ValueError):
        decode(name, value)


def test_intent_predecessor_pair_can_bind_a_completed_prior_probe():
    value = records()["intent.json"]
    value.update(predecessor_probe_id="f" * 32, predecessor_closed_sha256=HASH)
    assert decode("intent.json", value) == value


def test_recovery_cid_is_explicit_original_name_inspection_not_fake_create_response():
    value = records()["cid.json"]
    value.update(evidence_kind="name_inspection", observation_size=1048576)
    assert decode("cid.json", value) == value


def test_never_started_stopped_record_has_no_start_hash_and_zero_started_at():
    value = records()["stopped.json"]
    value.update(status="created", start_sha256=None, container_started_at=ZERO)
    assert decode("stopped.json", value) == value


def test_dead_retains_failure_or_clock_reversal_facts_as_data_only():
    value = records()["stopped.json"]
    value.update(
        status="dead",
        exit_code=137,
        oom_killed=True,
        error_present=True,
        container_finished_at=ZERO,
    )
    assert decode("stopped.json", value) == value


def test_invalid_output_can_retain_empty_original_frames_without_canonical_result():
    value = records()["output.json"]
    value.update(status="invalid", framed_size=0, canonical_sha256=None, canonical_size=None)
    assert decode("output.json", value) == value


@pytest.mark.parametrize(
    "reason",
    [
        "setup_failed",
        "prestart_failed",
        "start_uncertain",
        "process_failed",
        "run_expired",
        "shutdown",
        "invalid_output",
        "recovery",
    ],
)
def test_failed_closed_record_keeps_acknowledged_cleanup_and_safe_reason(reason):
    value = records()["closed.json"]
    value.update(outcome="failed", reason=reason, output_sha256=None)
    assert decode("closed.json", value) == value


def test_abandonment_requires_no_output_or_removal_and_matching_reason():
    value = records()["closed.json"]
    value.update(
        outcome="abandoned_before_create",
        reason="abandoned_before_create",
        output_sha256=None,
        removed_sha256=None,
    )
    assert decode("closed.json", value) == value
    for field in ["output_sha256", "removed_sha256"]:
        invalid = copy.deepcopy(value)
        invalid[field] = HASH
        with pytest.raises(ValueError):
            decode("closed.json", invalid)


@pytest.mark.parametrize("name", ["../start.json", "unknown.json", "active.json", None, True])
def test_only_fixed_receipt_names_are_accepted(name):
    with pytest.raises(ValueError):
        decode(name, records()["start.json"])


def test_receipts_require_original_canonical_bytes_and_metadata_limit():
    value = records()["start.json"]
    for raw in [json.dumps(value).encode(), b" " * 4097, b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff"]:
        with pytest.raises(ValueError, match=r"^stock_probe_store_unavailable$"):
            module()._decode_receipt(
                raw, "start.json", namespace_id=NAMESPACE, probe_id=PROBE, intent_sha256=HASH
            )
