"""Root attempt sequencing against fictional private files; never Docker."""

import hashlib
import importlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from infra.hybrid.stock_prestart import CreatedContainer
from infra.hybrid.stock_release import RELEASE_ROOT, StockRelease, _policy

IMAGE = "sha256:" + "b" * 64
RELEASE = "d" * 64
BOOT = "11111111-2222-4333-8444-555555555555"
CID = "f" * 64


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def module():
    source = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_attempts.py"
    assert source.is_file(), "Durable stock attempt store is not implemented"
    return importlib.import_module("infra.hybrid.stock_attempts")


@pytest.fixture
def policy():
    attestation = RELEASE_ROOT / RELEASE / "runtime-image-attestation.json"
    body = encoded(_policy(IMAGE, attestation))
    return StockRelease(
        RELEASE,
        IMAGE,
        "c" * 64,
        hashlib.sha256(body).hexdigest(),
        450,
        3600,
        attestation,
        attestation.parent / "stock-compose.resolved.json",
        body,
    )


@pytest.fixture
def operations(tmp_path, monkeypatch):
    api = module()
    root = tmp_path.resolve() / "operations"
    api._initialize(root, trusted_uid=os.geteuid())
    clock = {"boot_id": BOOT, "utc": "2026-10-21T21:00:00+00:00", "monotonic_ns": 1000000000000}
    monkeypatch.setattr(api, "_clock", lambda: clock.copy())
    return api, root, clock


def opened(operations):
    api, root, _ = operations
    return api._open_operations(root, trusted_uid=os.geteuid())


def snapshot(store):
    accessor = getattr(store, "snapshot", None)
    assert callable(accessor), "Recovery snapshots must validate persisted container/start identity"
    return accessor()


def cleanup_target(store):
    accessor = getattr(store, "cleanup_target", None)
    assert callable(accessor), "Cleanup must revoke launch authority before recovery validation"
    return accessor()


def created(intent, *, cid=CID):
    return CreatedContainer(cid, intent.attempt_id, RELEASE, IMAGE, "c" * 64, intent.compose_sha256)


def dispatch_prepared(store, policy, clock):
    claim = store.claim_create(policy)
    prepare = getattr(store, "prepare_create", None)
    assert callable(prepare), "The actual dispatch needs a durable CREATE fence"
    fence = prepare(claim, "a" * 64, clock["monotonic_ns"] + 5000000000)
    store.check_create_fence(fence)
    return fence


def removed(store, api, clock, *, evidence="delete_204"):
    fence = store.prepare_removal()
    store.check_removal_fence(fence)
    proof = api.RetirementProof(fence, evidence, clock["boot_id"], clock["monotonic_ns"])
    store.record_removed(fence, proof)
    return fence


def stopped(intent, *, cid=CID, status="exited", running=False):
    return {
        "Id": cid,
        "Image": IMAGE,
        "Name": "/hybrid-stock-research-" + intent.attempt_id,
        "Platform": "linux",
        "RestartCount": 0,
        "Config": {
            "Labels": {
                "org.hybrid.stock.managed": "stock-research",
                "org.hybrid.stock.release": RELEASE,
                "org.hybrid.stock.attempt": intent.attempt_id,
            }
        },
        "HostConfig": {
            "AutoRemove": False,
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
        },
        "State": {
            "Status": status,
            "Running": running,
            "Paused": False,
            "Restarting": False,
            "OOMKilled": False,
            "Dead": status == "dead",
            "Pid": 0,
            "ExitCode": 0,
            "Error": "",
            "StartedAt": "2026-10-21T21:00:01Z",
            "FinishedAt": "2026-10-21T21:00:02Z",
        },
    }


def test_new_namespace_and_intent_bind_explicit_v2_lineage(operations, policy):
    _, root, _ = operations
    assert json.loads((root / "namespace.json").read_bytes())["schema_version"] == 2
    with opened(operations) as store:
        attempt = store.begin(policy)
        raw = json.loads((root / attempt.attempt_id / "intent.json").read_bytes())
        assert raw["schema_version"] == attempt.schema_version == 2
        for name in (
            "predecessor_attempt_id",
            "predecessor_terminal_kind",
            "predecessor_terminal_sha256",
            "retirement_attempt_id",
            "retirement_container_id",
            "retirement_stopped_sha256",
        ):
            assert raw[name] is None


def test_v1_namespace_is_readable_but_cannot_admit_a_new_attempt(operations, policy):
    _, root, _ = operations
    namespace = json.loads((root / "namespace.json").read_bytes())
    namespace["schema_version"] = 1
    (root / "namespace.json").write_bytes(encoded(namespace))
    with opened(operations) as store:
        assert store.snapshot() is None
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.begin(policy)
    assert not (root / "active.json").exists()


def test_v2_cid_cannot_be_recorded_without_durable_create_dispatch_fence(operations, policy):
    with opened(operations) as store:
        attempt = store.begin(policy)
        store.claim_create(policy)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.record_created(created(attempt))


def test_create_fence_is_durable_and_only_its_fresh_issued_object_can_dispatch(operations, policy):
    _, root, clock = operations
    with opened(operations) as store:
        attempt = store.begin(policy)
        claim = store.claim_create(policy)
        prepare = getattr(store, "prepare_create", None)
        assert callable(prepare), "CREATE needs a durable dispatch fence before wire"
        fence = prepare(claim, "a" * 64, clock["monotonic_ns"] + 5000000000)
        path = root / attempt.attempt_id / "create.json"
        raw = json.loads(path.read_bytes())
        assert raw["schema_version"] == 2
        assert raw["intent_sha256"] == attempt.intent_sha256
        assert raw["request_sha256"] == "a" * 64
        assert raw["dispatch_deadline_ns"] == clock["monotonic_ns"] + 5000000000
        store.check_create_fence(fence)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.check_create_fence(replace(fence))
    with (
        opened(operations) as reopened,
        pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"),
    ):
        reopened.check_create_fence(fence)


def test_no_dispatch_abandonment_is_terminal_but_cannot_admit_during_recovery(operations, policy):
    _, root, _ = operations
    with opened(operations) as store:
        attempt = store.begin(policy)
        abandon = getattr(store, "record_abandoned_before_dispatch", None)
        assert callable(abandon), "A checked v2 no-dispatch recovery needs its own terminal kind"
        abandon()
        raw = json.loads((root / attempt.attempt_id / "abandoned.json").read_bytes())
        assert raw["kind"] == "stock_attempt_abandoned_before_dispatch"
        assert raw["removed_sha256"] is None and "container_id" not in raw
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.begin(policy)
    with opened(operations) as reopened:
        reopened.acknowledge_abandoned_terminal()
        successor = reopened.begin(policy)
        assert successor.predecessor_attempt_id == attempt.attempt_id
        assert successor.predecessor_terminal_kind == "abandoned_before_dispatch"
        assert successor.retirement_container_id is None


def test_recovery_burns_dispatch_authority_before_failed_snapshot_validation(
    operations, policy, monkeypatch
):
    with opened(operations) as store:
        store.begin(policy)
        recover = getattr(store, "recovery_snapshot", None)
        assert callable(recover), "Recovery must burn fresh authority before any fallible read"

        def fail():
            raise ValueError("fictional corrupt chain")

        monkeypatch.setattr(store, "snapshot", fail)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            recover()
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.claim_create(policy)


def test_stopped_handoff_requires_retirement_before_successor_create(operations, policy):
    api, root, clock = operations
    with opened(operations) as store:
        predecessor = store.begin(policy)
        dispatch_prepared(store, policy, clock)
        store.record_created(created(predecessor))
        store.record_stopped(encoded(stopped(predecessor)))
    with opened(operations) as store:
        store.record_stopped(encoded(stopped(predecessor)))
        successor = store.begin(policy)
        assert successor.predecessor_attempt_id == predecessor.attempt_id
        assert successor.predecessor_terminal_kind == "stopped"
        assert successor.retirement_container_id == CID
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.claim_create(policy)
        fence = removed(store, api, clock)
        assert fence.target_attempt_id == predecessor.attempt_id
        assert fence.target_container_id == CID
        removal = root / successor.attempt_id / "removed.json"
        assert json.loads(removal.read_bytes())["evidence_kind"] == "delete_204"
        # A failed admission claim was consumed, even after cleanup completes.
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.claim_create(policy)


@pytest.mark.parametrize("evidence", ["delete_204", "inspect_404"])
def test_retired_then_abandoned_successor_preserves_complete_logical_lineage(
    operations, policy, evidence
):
    api, root, clock = operations
    with opened(operations) as store:
        predecessor = store.begin(policy)
        dispatch_prepared(store, policy, clock)
        store.record_stopped(encoded(stopped(predecessor)))
    with opened(operations) as store:
        store.record_stopped(encoded(stopped(predecessor)))
        successor = store.begin(policy)
    with opened(operations) as recovery:
        recovery.recovery_snapshot()
        removed(recovery, api, clock, evidence=evidence)
        recovery.record_abandoned_before_dispatch()
        assert recovery.snapshot().abandoned_sha256 is not None
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            recovery.begin(policy)
    with opened(operations) as store:
        store.acknowledge_abandoned_terminal()
        third = store.begin(policy)
        assert third.predecessor_attempt_id == successor.attempt_id
        assert third.retirement_attempt_id is None
        assert third.retirement_container_id is None
        dispatch_prepared(store, policy, clock)
        store.record_created(created(third, cid="e" * 64))
        assert store.prepare_start().container_id == "e" * 64
    # Even a valid terminal-chain member cannot silently disappear.
    os.rename(root / predecessor.attempt_id, root / ("0" * 32))
    with (
        pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"),
        opened(operations) as store,
    ):
        store.snapshot()


@pytest.mark.parametrize("change", ["copy", "wrong_fence", "expired", "rollback", "boot", "kind"])
def test_removal_completion_requires_issued_scoped_fresh_proof(operations, policy, change):
    api, _, clock = operations
    with opened(operations) as store:
        predecessor = store.begin(policy)
        dispatch_prepared(store, policy, clock)
        store.record_stopped(encoded(stopped(predecessor)))
    with opened(operations) as store:
        store.record_stopped(encoded(stopped(predecessor)))
        store.begin(policy)
        fence = store.prepare_removal()
        proof = api.RetirementProof(fence, "delete_204", BOOT, clock["monotonic_ns"])
        selected = replace(fence) if change == "copy" else fence
        if change == "wrong_fence":
            proof = replace(proof, fence=replace(fence))
        elif change == "expired":
            clock["monotonic_ns"] = fence.deadline_ns
        elif change == "rollback":
            proof = replace(proof, observed_monotonic_ns=fence.issued_monotonic_ns - 1)
        elif change == "boot":
            proof = replace(proof, boot_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
        elif change == "kind":
            proof = replace(proof, evidence_kind="generic_absence")
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.record_removed(selected, proof)
        assert store.snapshot().removed_sha256 is None
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.record_removed(fence, proof)


@pytest.mark.parametrize("phase", ["create", "created", "start", "unresolved_retirement"])
def test_abandonment_never_reinterprets_dispatch_or_unresolved_retirement(
    operations, policy, phase
):
    _, _, clock = operations
    with opened(operations) as store:
        attempt = store.begin(policy)
        dispatch_prepared(store, policy, clock)
        if phase in ("created", "start"):
            store.record_created(created(attempt))
        if phase == "start":
            store.prepare_start()
        if phase == "unresolved_retirement":
            store.record_stopped(encoded(stopped(attempt)))
    with opened(operations) as store:
        if phase == "unresolved_retirement":
            store.record_stopped(encoded(stopped(attempt)))
            store.begin(policy)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.record_abandoned_before_dispatch()
        assert store.snapshot().abandoned_sha256 is None
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.begin(policy)


def test_historical_cid_cannot_be_reused_by_a_successor(operations, policy):
    api, _, clock = operations
    with opened(operations) as store:
        predecessor = store.begin(policy)
        dispatch_prepared(store, policy, clock)
        store.record_stopped(encoded(stopped(predecessor)))
    with opened(operations) as store:
        store.record_stopped(encoded(stopped(predecessor)))
        successor = store.begin(policy)
        removed(store, api, clock)
        dispatch_prepared(store, policy, clock)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.record_created(created(successor))
        assert store.snapshot().created_sha256 is None


def test_unfinished_entry_cannot_admit_even_after_it_records_terminal_stop(operations, policy):
    _, _, clock = operations
    with opened(operations) as store:
        attempt = store.begin(policy)
        dispatch_prepared(store, policy, clock)
    with opened(operations) as store:
        store.record_stopped(encoded(stopped(attempt)))
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.begin(policy)


@pytest.mark.parametrize("phase", ["prepare", "dispatch"])
def test_start_keeps_the_acknowledged_create_receipt_binding(operations, policy, phase):
    _, root, clock = operations
    with opened(operations) as store:
        attempt = store.begin(policy)
        dispatch_prepared(store, policy, clock)
        store.record_created(created(attempt))
        fence = store.prepare_start() if phase == "dispatch" else None
        path = root / attempt.attempt_id / "create.json"
        value = json.loads(path.read_bytes())
        value["request_sha256"] = "b" * 64
        path.write_bytes(encoded(value))
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            if phase == "prepare":
                store.prepare_start()
            else:
                store.check_start_fence(fence)


def test_cid_clock_cannot_precede_the_create_dispatch_fence(operations, policy):
    _, root, clock = operations
    with opened(operations) as store:
        attempt = store.begin(policy)
        clock["monotonic_ns"] += 100
        dispatch_prepared(store, policy, clock)
        clock["monotonic_ns"] -= 1
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.record_created(created(attempt))
        assert not (root / attempt.attempt_id / "created.json").exists()


def test_uncertain_removal_receipt_never_grants_fresh_create(operations, policy, monkeypatch):
    api, _, clock = operations
    original = api._write_new
    with opened(operations) as store:
        predecessor = store.begin(policy)
        dispatch_prepared(store, policy, clock)
        store.record_stopped(encoded(stopped(predecessor)))
    with opened(operations) as store:
        store.record_stopped(encoded(stopped(predecessor)))
        store.begin(policy)

        def lose_ack(directory, name, value, uid):
            digest = original(directory, name, value, uid)
            if name == "removed.json":
                raise OSError("fictional removed acknowledgement loss")
            return digest

        monkeypatch.setattr(api, "_write_new", lose_ack)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            removed(store, api, clock)
        assert store.snapshot().removed_sha256 is not None
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.claim_create(policy)


def test_abandonment_reconfirms_retirement_durability_before_its_terminal_write(
    operations, policy, monkeypatch
):
    api, root, clock = operations
    with opened(operations) as store:
        predecessor = store.begin(policy)
        dispatch_prepared(store, policy, clock)
        store.record_stopped(encoded(stopped(predecessor)))
    with opened(operations) as store:
        store.record_stopped(encoded(stopped(predecessor)))
        successor = store.begin(policy)
        removed(store, api, clock)
    with opened(operations) as recovery:
        original = api._reconfirm_durability

        def fail_removed(directory, name, value, uid):
            if name == "removed.json":
                raise OSError("fictional retirement durability failure")
            return original(directory, name, value, uid)

        monkeypatch.setattr(api, "_reconfirm_durability", fail_removed)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            recovery.record_abandoned_before_dispatch()
        assert not (root / successor.attempt_id / "abandoned.json").exists()


@pytest.mark.parametrize("after_write", [False, True])
def test_failed_create_fence_ack_cannot_be_retried_or_adopted(
    operations, policy, monkeypatch, after_write
):
    api, root, clock = operations
    original = api._write_new
    with opened(operations) as store:
        attempt = store.begin(policy)
        claim = store.claim_create(policy)

        def fail_create(directory, name, value, uid):
            if name == "create.json":
                if after_write:
                    original(directory, name, value, uid)
                raise OSError("fictional CREATE fence acknowledgement loss")
            return original(directory, name, value, uid)

        monkeypatch.setattr(api, "_write_new", fail_create)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.prepare_create(claim, "a" * 64, clock["monotonic_ns"] + 5000000000)
        monkeypatch.setattr(api, "_write_new", original)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.prepare_create(claim, "a" * 64, clock["monotonic_ns"] + 5000000000)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.record_created(created(attempt))
    assert (root / attempt.attempt_id / "create.json").exists() is after_write
    with opened(operations) as recovery:
        if after_write:
            with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
                recovery.record_abandoned_before_dispatch()
        else:
            recovery.record_abandoned_before_dispatch()
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            recovery.begin(policy)


@pytest.mark.parametrize("change", ["expiry", "boot", "rollback", "receipt"])
def test_create_dispatch_fence_retains_original_budget_and_acknowledged_bytes(
    operations, policy, change
):
    _, root, clock = operations
    with opened(operations) as store:
        attempt = store.begin(policy)
        fence = dispatch_prepared(store, policy, clock)
        if change == "expiry":
            clock["monotonic_ns"] = fence.dispatch_deadline_ns
        elif change == "boot":
            clock["boot_id"] = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        elif change == "rollback":
            clock["monotonic_ns"] -= 1
        else:
            path = root / attempt.attempt_id / "create.json"
            value = json.loads(path.read_bytes())
            value["utc"] = "2026-10-21T21:00:01+00:00"
            path.write_bytes(encoded(value))
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.check_create_fence(fence)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.prepare_create(attempt, "a" * 64, clock["monotonic_ns"] + 5000000000)


@pytest.mark.parametrize("change", ["skip", "terminal_hash", "terminal_kind", "target", "partial"])
def test_rehashed_intent_cannot_skip_or_retarget_a_terminal_predecessor(operations, policy, change):
    _, root, clock = operations
    with opened(operations) as store:
        predecessor = store.begin(policy)
        dispatch_prepared(store, policy, clock)
        store.record_stopped(encoded(stopped(predecessor)))
    with opened(operations) as store:
        store.record_stopped(encoded(stopped(predecessor)))
        successor = store.begin(policy)
    path = root / successor.attempt_id / "intent.json"
    value = json.loads(path.read_bytes())
    if change == "skip":
        for key in (
            "predecessor_attempt_id",
            "predecessor_terminal_kind",
            "predecessor_terminal_sha256",
            "retirement_attempt_id",
            "retirement_container_id",
            "retirement_stopped_sha256",
        ):
            value[key] = None
    elif change == "terminal_hash":
        value["predecessor_terminal_sha256"] = "a" * 64
    elif change == "terminal_kind":
        value["predecessor_terminal_kind"] = "abandoned_before_dispatch"
    elif change == "target":
        value["retirement_container_id"] = "e" * 64
    else:
        value["retirement_attempt_id"] = None
    path.write_bytes(encoded(value))
    head = json.loads((root / "active.json").read_bytes())
    head["intent_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "active.json").write_bytes(encoded(head))
    with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"), opened(operations):
        pytest.fail("Rehashed broken history was admitted")


def test_v1_start_fenced_history_stays_cleanup_only(operations, policy):
    _, root, clock = operations
    with opened(operations) as store:
        attempt = store.begin(policy)
        dispatch_prepared(store, policy, clock)
        store.record_created(created(attempt))
        store.prepare_start()
    # Explicit historical v1 fixture; production never rewrites a namespace.
    intent_path = root / attempt.attempt_id / "intent.json"
    intent = json.loads(intent_path.read_bytes())
    for key in tuple(intent):
        if key.startswith(("predecessor_", "retirement_")):
            del intent[key]
    intent["schema_version"] = 1
    intent_path.write_bytes(encoded(intent))
    digest = hashlib.sha256(intent_path.read_bytes()).hexdigest()
    for path in (
        root / "namespace.json",
        root / "active.json",
        root / attempt.attempt_id / "created.json",
        root / attempt.attempt_id / "start.json",
    ):
        value = json.loads(path.read_bytes())
        value["schema_version"] = 1
        if "intent_sha256" in value:
            value["intent_sha256"] = digest
        path.write_bytes(encoded(value))
    (root / attempt.attempt_id / "create.json").unlink()
    with opened(operations) as store:
        state = store.cleanup_target()
        assert state.attempt.schema_version == 1 and state.container_id == CID
        assert state.create_sha256 is None and state.start_fence is not None
        store.record_stopped(encoded(stopped(state.attempt)))
        for operation in (
            lambda: store.begin(policy),
            lambda: store.claim_create(policy),
            store.prepare_start,
            store.prepare_removal,
        ):
            with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
                operation()


def test_explicit_initialize_and_reopen_preserve_namespace_identity(operations):
    api, root, _ = operations
    namespace = (root / "namespace.json").read_bytes()
    assert root.stat().st_mode & 0o777 == 0o700
    assert sorted(path.name for path in root.iterdir()) == ["launcher.lock", "namespace.json"]
    for path in root.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
    with opened(operations) as store:
        assert store.active() is None
    with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
        api._initialize(root, trusted_uid=os.geteuid())
    assert (root / "namespace.json").read_bytes() == namespace


def test_nonblocking_single_owner_and_release_after_exception(operations):
    with pytest.raises(RuntimeError, match="fictional"), opened(operations):
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"), opened(operations):
            pytest.fail("Duplicate launcher acquired lock")
        raise RuntimeError("fictional")
    with opened(operations) as store:
        assert store.active() is None


def test_intent_is_durable_before_return_and_bound_to_active_hash(operations, policy):
    _, root, _ = operations
    with opened(operations) as store:
        intent = store.begin(policy)
        assert store.active() == intent
        head = json.loads((root / "active.json").read_bytes())
        raw = (root / intent.attempt_id / "intent.json").read_bytes()
        assert head["intent_sha256"] == hashlib.sha256(raw).hexdigest() == intent.intent_sha256
        assert json.loads(raw)["boot_id"] == BOOT
        assert intent.max_run_seconds == 450 and intent.image_digest == IMAGE
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.begin(policy)
    with opened(operations) as recovered:
        assert recovered.active() == intent
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            recovered.begin(policy)


def test_verified_cid_is_required_before_exclusive_start_fence(operations, policy):
    _, root, clock = operations
    with opened(operations) as store:
        intent = store.begin(policy)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.prepare_start()
        dispatch_prepared(store, policy, clock)
        store.record_created(created(intent))
        fence = store.prepare_start()
        assert fence.container_id == CID
        assert fence.term_deadline_ns == clock["monotonic_ns"] + 450000000000
        assert (root / intent.attempt_id / "start.json").is_file()
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.prepare_start()


def test_reopening_never_adopts_an_unfinished_attempt_for_execution(operations, policy):
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_created(created(intent))
    with opened(operations) as recovered:
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            recovered.prepare_start()
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            recovered.record_created(created(intent))


def test_terminal_ack_allows_later_fresh_attempt_not_replay(operations, policy):
    with opened(operations) as store:
        old = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_created(created(old))
        store.prepare_start()
        result = store.record_stopped(encoded(stopped(old)))
        assert result["container_id"] == CID and result["exit_code"] == 0
    with opened(operations) as later:
        later.record_stopped(encoded(stopped(old)))
        fresh = later.begin(policy)
        assert fresh.attempt_id != old.attempt_id


def test_same_session_cannot_start_after_stopped_ack(operations, policy):
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_created(created(intent))
        store.record_stopped(encoded(stopped(intent)))
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.prepare_start()


def test_fsync_delay_cannot_return_an_expired_start_fence(operations, policy, monkeypatch):
    api, _, clock = operations
    original = api._write_new

    def delayed(directory, name, value, uid):
        digest = original(directory, name, value, uid)
        if name == "start.json":
            clock["monotonic_ns"] += 450000000001
        return digest

    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_created(created(intent))
        monkeypatch.setattr(api, "_write_new", delayed)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.prepare_start()


def test_lost_create_ack_recovery_can_only_record_matching_stopped_identity(operations, policy):
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
    with opened(operations) as recovered:
        assert recovered.record_stopped(encoded(stopped(intent)))["container_id"] == CID
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            recovered.prepare_start()


@pytest.mark.parametrize(
    "field,value",
    [
        ("container_id", "a" * 64),
        ("attempt_id", "a" * 32),
        ("release_id", "a" * 64),
        ("config_hash", "a" * 64),
        ("compose_sha256", "a" * 64),
        ("image_digest", "sha256:" + "a" * 64),
    ],
)
def test_cid_receipt_is_bound_to_all_prestart_identities(operations, policy, field, value):
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        changed = replace(created(intent), **{field: value})
        if field == "container_id":
            store.record_created(changed)
            with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
                store.record_stopped(encoded(stopped(intent)))
        else:
            with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
                store.record_created(changed)


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("State", "Running", True),
        ("State", "Paused", True),
        ("State", "Restarting", True),
        ("State", "Pid", 1),
        ("State", "Pid", False),
        ("State", "ExitCode", False),
        ("State", "Status", "running"),
        ("State", "Health", {}),
        ("HostConfig", "AutoRemove", True),
        ("HostConfig", "RestartPolicy", {"Name": "always", "MaximumRetryCount": 0}),
        ("Config", "Labels", {}),
    ],
)
def test_nonterminal_or_unowned_observations_cannot_acknowledge_completion(
    operations, policy, section, field, value
):
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        observation = stopped(intent)
        observation[section][field] = value
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.record_stopped(encoded(observation))


@pytest.mark.parametrize("anchor", ["launcher.lock", "namespace.json"])
def test_missing_anchor_is_not_recreated(operations, anchor):
    _, root, _ = operations
    (root / anchor).unlink()
    with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"), opened(operations):
        pytest.fail("Lost namespace was adopted")
    assert not (root / anchor).exists()


def test_lost_active_pointer_after_use_is_not_fresh_state(operations, policy):
    _, root, _ = operations
    with opened(operations) as store:
        store.begin(policy)
    (root / "active.json").unlink()
    with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"), opened(operations):
        pytest.fail("The opener adopted an orphaned attempt")


def test_boot_change_or_monotonic_rollback_blocks_start(operations, policy):
    _, _, clock = operations
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_created(created(intent))
        clock["boot_id"] = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.prepare_start()


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("kind", "other"),
        ("namespace_id", "x" * 32),
        ("root_inode", 0),
        ("lock_inode", 0),
        ("root_device", True),
        ("unexpected", 1),
    ],
)
def test_namespace_corruption_is_not_adopted(operations, field, value):
    _, root, _ = operations
    path = root / "namespace.json"
    record = json.loads(path.read_bytes())
    record[field] = value
    path.write_bytes(encoded(record))
    with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"), opened(operations):
        pytest.fail("Corrupt namespace was adopted")


@pytest.mark.parametrize("target", ["namespace.json", "launcher.lock"])
@pytest.mark.parametrize("substitution", ["symlink", "hardlink", "permissions"])
def test_anchor_substitutions_and_permissions_fail_closed(operations, target, substitution):
    _, root, _ = operations
    path = root / target
    if substitution == "permissions":
        path.chmod(0o640)
    else:
        saved = root.parent / (target + ".saved")
        path.rename(saved)
        if substitution == "symlink":
            path.symlink_to(saved)
        else:
            os.link(saved, path)
    with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"), opened(operations):
        pytest.fail("Unsafe anchor was adopted")


def test_root_replacement_is_detected_while_lease_is_held(operations):
    _, root, _ = operations
    with opened(operations) as store:
        root.rename(root.with_name("moved-operations"))
        root.mkdir(mode=0o700)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.active()


def test_lock_replacement_is_detected_without_rebinding(operations):
    _, root, _ = operations
    with opened(operations) as store:
        (root / "launcher.lock").unlink()
        (root / "launcher.lock").write_bytes(b"")
        (root / "launcher.lock").chmod(0o600)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.active()
    with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"), opened(operations):
        pytest.fail("Replacement anchor was blessed")


def test_uncertain_start_write_is_one_use_even_without_file(operations, policy, monkeypatch):
    api, root, _ = operations
    original = api._write_new

    def failed(directory, name, value, uid):
        if name == "start.json":
            raise OSError("fictional private failure")
        return original(directory, name, value, uid)

    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_created(created(intent))
        monkeypatch.setattr(api, "_write_new", failed)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.prepare_start()
        monkeypatch.setattr(api, "_write_new", original)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.prepare_start()
        assert not (root / intent.attempt_id / "start.json").exists()


def test_uncertain_active_publication_does_not_grant_dispatch(operations, policy, monkeypatch):
    api, root, _ = operations
    original = api.os.replace

    def failed(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("publication acknowledgement lost")

    with opened(operations) as store:
        monkeypatch.setattr(api.os, "replace", failed)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.begin(policy)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.record_created(
                CreatedContainer(CID, "e" * 32, RELEASE, IMAGE, "c" * 64, policy.compose_sha256)
            )
    monkeypatch.setattr(api.os, "replace", original)
    assert (root / "active.json").is_file()
    with opened(operations) as recovered:
        assert recovered.active() is not None
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            recovered.prepare_start()


def test_monotonic_rollback_blocks_before_fence_write(operations, policy):
    _, root, clock = operations
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_created(created(intent))
        clock["monotonic_ns"] -= 1
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.prepare_start()
        assert not (root / intent.attempt_id / "start.json").exists()


def test_stopped_diagnostics_are_reduced_to_presence_not_retained(operations, policy):
    _, root, _ = operations
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        observation = stopped(intent)
        observation["State"]["Error"] = "fictional private diagnostic"
        observation["State"]["OOMKilled"] = True
        observation["State"]["ExitCode"] = 137
        result = store.record_stopped(encoded(observation))
        assert result["error_present"] is True and result["oom_killed"] is True
        raw = (root / intent.attempt_id / "stopped.json").read_bytes()
        assert b"private diagnostic" not in raw and result["exit_code"] == 137


def test_store_cannot_be_used_after_context_closes(operations):
    with opened(operations) as store:
        pass
    with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
        store.active()


def test_actual_clock_reader_uses_only_fixed_bounded_boot_file(tmp_path, monkeypatch):
    api = module()
    boot = tmp_path / "fictional-boot-id"
    boot.write_text(BOOT + "\n")
    original = api.os.open
    calls = []

    def selected(path, flags):
        assert path == "/proc/sys/kernel/random/boot_id"
        assert flags & os.O_NOFOLLOW and flags & os.O_NONBLOCK
        calls.append(path)
        return original(boot, flags)

    monkeypatch.setattr(api.sys, "platform", "linux")
    monkeypatch.setattr(api.os, "open", selected)
    value = api._clock()
    assert value["boot_id"] == BOOT and value["monotonic_ns"] > 0
    assert len(calls) == 1


def test_fixed_public_selectors_have_no_path_override(monkeypatch):
    api = module()
    calls = []
    selected = object()
    monkeypatch.setattr(api.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        api, "_initialize", lambda root, *, trusted_uid: calls.append((root, trusted_uid))
    )
    monkeypatch.setattr(
        api,
        "_open_operations",
        lambda root, *, trusted_uid: calls.append((root, trusted_uid)) or selected,
    )
    api.initialize_operations()
    assert api.operations() is selected
    assert calls == [(api.OPERATIONS_ROOT, 0), (api.OPERATIONS_ROOT, 0)]


def test_public_nonroot_selection_never_initializes_or_opens(monkeypatch):
    api = module()
    monkeypatch.setattr(api.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(
        api, "_initialize", lambda *_a, **_k: pytest.fail("Initialization attempted")
    )
    monkeypatch.setattr(api, "_open_operations", lambda *_a, **_k: pytest.fail("Open attempted"))
    for operation in (api.initialize_operations, api.operations):
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            operation()


def test_never_started_created_observation_is_not_research_success(operations, policy):
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        observation = stopped(intent, status="created")
        for key in ("StartedAt", "FinishedAt"):
            observation["State"][key] = "0001-01-01T00:00:00Z"
        result = store.record_stopped(encoded(observation))
        assert result["status"] == "created" and result["start_fence_present"] is False
        assert "research_succeeded" not in result


@pytest.mark.parametrize(
    "field,value",
    [("max_run_seconds", True), ("release_id", "x" * 64), ("image_digest", "other:latest")],
)
def test_invalid_release_identity_cannot_become_an_attempt(operations, policy, field, value):
    _, root, _ = operations
    with (
        pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"),
        opened(operations) as store,
    ):
        store.begin(replace(policy, **{field: value}))
    assert not (root / "active.json").exists()


def test_unexpected_namespace_file_and_unreferenced_attempt_block_admission(operations, policy):
    _, root, _ = operations
    (root / "unknown").write_bytes(b"fictional")
    with (
        pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"),
        opened(operations) as store,
    ):
        store.begin(policy)


def test_failed_cid_fsync_never_becomes_dispatch_ack(operations, policy, monkeypatch):
    api, _, _ = operations
    original = api.os.fsync
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        monkeypatch.setattr(
            api.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("fictional"))
        )
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.record_created(created(intent))
        monkeypatch.setattr(api.os, "fsync", original)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.prepare_start()


def test_lost_cid_anchor_cannot_relax_durable_start_identity(operations, policy):
    _, root, _ = operations
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_created(created(intent))
        store.prepare_start()
    (root / intent.attempt_id / "created.json").unlink()
    with (
        pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"),
        opened(operations) as recovered,
    ):
        recovered.record_stopped(encoded(stopped(intent, cid="a" * 64)))


@pytest.mark.parametrize("failed_fsync", [False, True])
def test_reopened_terminal_bytes_require_fresh_reconfirmation(
    operations, policy, monkeypatch, failed_fsync
):
    api, _, _ = operations
    original = api.os.fsync
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        if failed_fsync:
            monkeypatch.setattr(
                api.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("fictional"))
            )
            with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
                store.record_stopped(encoded(stopped(intent)))
            monkeypatch.setattr(api.os, "fsync", original)
        else:
            store.record_stopped(encoded(stopped(intent)))
    with opened(operations) as recovered:
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            recovered.begin(policy)
        recovered.record_stopped(encoded(stopped(intent)))
        fresh = recovered.begin(policy)
        assert fresh.attempt_id != intent.attempt_id


@pytest.mark.parametrize(
    "field,value",
    [
        ("container_id", "a" * 64),
        ("boot_id", "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"),
        ("term_deadline_ns", True),
    ],
)
def test_persisted_start_and_created_receipts_must_agree(operations, policy, field, value):
    _, root, _ = operations
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_created(created(intent))
        store.prepare_start()
    path = root / intent.attempt_id / "start.json"
    record = json.loads(path.read_bytes())
    record[field] = value
    path.write_bytes(encoded(record))
    with (
        pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"),
        opened(operations) as recovered,
    ):
        recovered.record_stopped(encoded(stopped(intent)))


def test_start_clock_cannot_precede_acknowledged_created_clock(operations, policy):
    _, root, clock = operations
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        clock["monotonic_ns"] += 100
        store.record_created(created(intent))
        store.prepare_start()
    path = root / intent.attempt_id / "start.json"
    record = json.loads(path.read_bytes())
    record["monotonic_ns"] -= 1
    record["term_deadline_ns"] -= 1
    path.write_bytes(encoded(record))
    with (
        pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"),
        opened(operations) as recovered,
    ):
        recovered.record_stopped(encoded(stopped(intent)))


def test_cid_receipt_must_still_equal_the_acknowledged_bytes(operations, policy):
    _, root, _ = operations
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_created(created(intent))
        path = root / intent.attempt_id / "created.json"
        record = json.loads(path.read_bytes())
        record["utc"] = "2026-10-21T21:00:01+00:00"
        path.write_bytes(encoded(record))
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.prepare_start()


def test_fresh_reconfirmation_rejects_changed_container_lifetime(operations, policy):
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_stopped(encoded(stopped(intent)))
    with opened(operations) as recovered:
        changed = stopped(intent)
        changed["State"]["FinishedAt"] = "2026-10-21T21:00:03Z"
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            recovered.record_stopped(encoded(changed))
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            recovered.begin(policy)


def test_failed_reconfirmation_clears_earlier_terminal_ack(operations, policy, monkeypatch):
    api, _, _ = operations
    original = api.os.fsync
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_stopped(encoded(stopped(intent)))
    with opened(operations) as recovered:
        recovered.record_stopped(encoded(stopped(intent)))
        monkeypatch.setattr(
            api.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("fictional"))
        )
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            recovered.record_stopped(encoded(stopped(intent)))
        monkeypatch.setattr(api.os, "fsync", original)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            recovered.begin(policy)


def test_recovery_ends_before_a_later_terminal_handoff_can_start(operations, policy):
    api, _, clock = operations
    with opened(operations) as store:
        old = store.begin(policy)
        dispatch_prepared(store, policy, clock)
        store.record_created(created(old))
    with opened(operations) as recovered:
        recovered.record_stopped(encoded(stopped(old)))
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            recovered.begin(policy)
    with opened(operations) as fresh_session:
        fresh_session.record_stopped(encoded(stopped(old)))
        fresh = fresh_session.begin(policy)
        removed(fresh_session, api, clock)
        dispatch_prepared(fresh_session, policy, clock)
        fresh_session.record_created(created(fresh, cid="e" * 64))
        fence = fresh_session.prepare_start()
        assert fence.attempt_id == fresh.attempt_id and fresh.attempt_id != old.attempt_id


@pytest.mark.parametrize("prior_ack", ["terminal", "created"])
def test_initial_stop_validation_failure_revokes_prior_session_acknowledgements(
    operations, policy, monkeypatch, prior_ack
):
    api, _, _ = operations
    original_fstat = api.os.fstat
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_created(created(intent))
        if prior_ack == "terminal":
            store.record_stopped(encoded(stopped(intent)))
        if prior_ack == "created":
            _assert_failed_stop_revokes_ack(
                store, intent, prior_ack, api, original_fstat, monkeypatch, policy
            )
    if prior_ack == "terminal":
        with opened(operations) as recovered:
            recovered.record_stopped(encoded(stopped(intent)))
            _assert_failed_stop_revokes_ack(
                recovered, intent, prior_ack, api, original_fstat, monkeypatch, policy
            )


def _assert_failed_stop_revokes_ack(
    active_store, intent, prior_ack, api, original_fstat, monkeypatch, policy
):
    calls = 0

    def fail_first_fstat(fd):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("fictional initial validation failure")
        return original_fstat(fd)

    with monkeypatch.context() as scoped:
        scoped.setattr(api.os, "fstat", fail_first_fstat)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            active_store.record_stopped(encoded(stopped(intent)))
    with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
        if prior_ack == "terminal":
            active_store.begin(policy)
        else:
            active_store.prepare_start()


def test_create_claim_is_owned_one_use_and_not_recovery_authority(operations, policy):
    with opened(operations) as store:
        intent = store.begin(policy)
        claim = store.claim_create(policy)
        assert claim == intent
        store.check_create_claim(claim)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.check_create_claim(replace(claim))
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.claim_create(policy)
    with opened(operations) as recovered:
        assert recovered.active() == intent
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            recovered.claim_create(policy)


@pytest.mark.parametrize(
    "changes",
    [
        {"release_id": "a" * 64},
        {"image_digest": "sha256:" + "a" * 64},
        {"config_hash": "a" * 64},
        {"compose_sha256": "a" * 64},
        {"max_run_seconds": 449},
    ],
)
def test_create_claim_checks_retained_release_and_burns_failure(operations, policy, changes):
    with opened(operations) as store:
        store.begin(policy)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.claim_create(replace(policy, **changes))
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.claim_create(policy)


def test_create_claim_is_consumed_even_if_initial_validation_fails(operations, policy, monkeypatch):
    api, _, _ = operations
    with opened(operations) as store:
        store.begin(policy)
        with monkeypatch.context() as scoped:
            scoped.setattr(api.os, "fstat", lambda _fd: (_ for _ in ()).throw(OSError("fictional")))
            with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
                store.claim_create(policy)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.claim_create(policy)


@pytest.mark.parametrize("phase", ["created", "start", "stopped"])
def test_create_claim_cannot_follow_existing_execution_receipts(operations, policy, phase):
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_created(created(intent))
        if phase == "start":
            store.prepare_start()
        if phase == "stopped":
            store.record_stopped(encoded(stopped(intent)))
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.claim_create(policy)


@pytest.mark.parametrize("change", ["boot", "rollback", "receipt"])
def test_final_create_check_rejects_changed_state(operations, policy, change):
    _, root, clock = operations
    with opened(operations) as store:
        intent = store.begin(policy)
        fence = dispatch_prepared(store, policy, clock)
        if change == "boot":
            clock["boot_id"] = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        elif change == "rollback":
            clock["monotonic_ns"] -= 1
        else:
            store.record_created(created(intent))
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.check_create_fence(fence)
        assert (root / intent.attempt_id / "intent.json").is_file()


@pytest.mark.parametrize("change", ["copy", "clock", "start_bytes", "stopped"])
def test_final_start_check_requires_issued_unchanged_unexpired_fence(operations, policy, change):
    _, root, clock = operations
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_created(created(intent))
        fence = store.prepare_start()
        store.check_start_fence(fence)
        if change == "copy":
            fence = replace(fence)
        elif change == "clock":
            clock["monotonic_ns"] = fence.term_deadline_ns
        elif change == "start_bytes":
            path = root / intent.attempt_id / "start.json"
            value = json.loads(path.read_bytes())
            value["utc"] = "2026-10-21T21:00:01+00:00"
            path.write_bytes(encoded(value))
        else:
            store.record_stopped(encoded(stopped(intent)))
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.check_start_fence(fence)


def test_snapshot_empty_and_each_stage_preserve_receipts_and_authority(operations, policy):
    _, root, _ = operations
    with opened(operations) as store:
        assert snapshot(store) is None
        intent = store.begin(policy)
        initial = snapshot(store)
        assert initial.attempt == intent and initial.container_id is None
        assert initial.start_fence is None
        assert (initial.created_sha256, initial.start_sha256, initial.stopped_sha256) == (
            None,
            None,
            None,
        )
        assert initial.create_sha256 is None
        dispatch_prepared(store, policy, operations[2])
        assert (
            snapshot(store).create_sha256
            == hashlib.sha256((root / intent.attempt_id / "create.json").read_bytes()).hexdigest()
        )
        store.record_created(created(intent))
        recorded = snapshot(store)
        assert recorded.container_id == CID and recorded.start_fence is None
        assert (
            recorded.created_sha256
            == hashlib.sha256((root / intent.attempt_id / "created.json").read_bytes()).hexdigest()
        )
        fence = store.prepare_start()
        store.check_start_fence(fence)
        before = {path.name: path.read_bytes() for path in (root / intent.attempt_id).iterdir()}
        launched = snapshot(store)
        assert launched.start_fence == fence and launched.start_fence is not fence
        assert launched.start_sha256 == hashlib.sha256(before["start.json"]).hexdigest()
        store.check_start_fence(fence)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.check_start_fence(launched.start_fence)
        assert before == {
            path.name: path.read_bytes() for path in (root / intent.attempt_id).iterdir()
        }
        store.record_stopped(encoded(stopped(intent)))
        terminal = snapshot(store)
        assert terminal.container_id == CID and terminal.start_fence == fence
        assert (
            terminal.stopped_sha256
            == hashlib.sha256((root / intent.attempt_id / "stopped.json").read_bytes()).hexdigest()
        )
    with opened(operations) as store:
        assert snapshot(store) == terminal
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.begin(policy)


def test_snapshot_retains_stopped_cid_after_lost_create_ack(operations, policy):
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_stopped(encoded(stopped(intent, status="created")))
        view = snapshot(store)
        assert view.container_id == CID and view.created_sha256 is None
        assert view.start_sha256 is None and view.start_fence is None
        assert view.stopped_sha256 is not None


@pytest.mark.parametrize(
    "change", ["created_missing", "start_cid", "start_clock", "stop_cid", "stop_flag"]
)
def test_snapshot_rejects_inconsistent_receipt_chain(operations, policy, change):
    _, root, _ = operations
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_created(created(intent))
        store.prepare_start()
        store.record_stopped(encoded(stopped(intent)))
        if change == "created_missing":
            (root / intent.attempt_id / "created.json").unlink()
        else:
            name = "start.json" if change.startswith("start") else "stopped.json"
            path = root / intent.attempt_id / name
            value = json.loads(path.read_bytes())
            if change == "start_clock":
                value["monotonic_ns"] -= 1
                value["term_deadline_ns"] -= 1
            elif change == "stop_flag":
                value["start_fence_present"] = False
            else:
                value["container_id"] = "a" * 64
            path.write_bytes(encoded(value))
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            snapshot(store)


@pytest.mark.parametrize("change", ["reopened", "expired", "old_boot", "rollback"])
def test_cleanup_recovers_original_target_without_new_launch_authority(operations, policy, change):
    _, root, clock = operations
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_created(created(intent))
        fence = store.prepare_start()
    before = {path.name: path.read_bytes() for path in (root / intent.attempt_id).iterdir()}
    if change == "expired":
        clock["monotonic_ns"] = fence.term_deadline_ns + 1
    elif change == "old_boot":
        clock["boot_id"] = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        clock["monotonic_ns"] = 1
    elif change == "rollback":
        clock["monotonic_ns"] = 1
    with opened(operations) as store:
        target = cleanup_target(store)
        assert target.attempt == intent and target.container_id == CID
        assert target.start_fence == fence and target.start_fence is not fence
        assert target.stopped_sha256 is None
        for operation in [
            store.prepare_start,
            lambda: store.claim_create(policy),
            lambda: store.begin(policy),
        ]:
            with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
                operation()
    assert before == {path.name: path.read_bytes() for path in (root / intent.attempt_id).iterdir()}


@pytest.mark.parametrize("stage", ["empty", "intent", "created", "stopped"])
def test_cleanup_rejects_unfenced_or_terminal_stage(operations, policy, stage):
    with opened(operations) as store:
        if stage != "empty":
            intent = store.begin(policy)
            if stage != "intent":
                dispatch_prepared(store, policy, operations[2])
                store.record_created(created(intent))
            if stage == "stopped":
                store.prepare_start()
                store.record_stopped(encoded(stopped(intent)))
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            cleanup_target(store)
        if stage != "empty":
            with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
                store.prepare_start()
            with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
                store.claim_create(policy)


def test_cleanup_revokes_start_before_failed_namespace_validation(operations, policy):
    _, root, _ = operations
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_created(created(intent))
        fence = store.prepare_start()
        (root / "launcher.lock").chmod(0o640)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            cleanup_target(store)
        (root / "launcher.lock").chmod(0o600)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.check_start_fence(fence)


def test_cleanup_revokes_terminal_admission_before_failed_validation(operations, policy):
    _, root, _ = operations
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_created(created(intent))
        store.prepare_start()
        store.record_stopped(encoded(stopped(intent)))
    with opened(operations) as store:
        store.record_stopped(encoded(stopped(intent)))
        (root / "launcher.lock").chmod(0o640)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            cleanup_target(store)
        (root / "launcher.lock").chmod(0o600)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.begin(policy)


@pytest.mark.parametrize("reopened", [False, True])
def test_start_fenced_created_state_cannot_acknowledge_termination(operations, policy, reopened):
    _, root, _ = operations

    def reject(store, intent, fence):
        observation = stopped(intent, status="created")
        observation["State"]["StartedAt"] = "0001-01-01T00:00:00Z"
        observation["State"]["FinishedAt"] = "0001-01-01T00:00:00Z"
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.record_stopped(encoded(observation))
        assert not (root / intent.attempt_id / "stopped.json").exists()
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.check_start_fence(fence)
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            store.begin(policy)

    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_created(created(intent))
        fence = store.prepare_start()
        if not reopened:
            reject(store, intent, fence)
    if reopened:
        with opened(operations) as store:
            reject(store, intent, fence)


def retained_created_receipt(root, intent):
    path = root / intent.attempt_id / "stopped.json"
    receipt = json.loads(path.read_bytes())
    receipt["status"] = "created"
    receipt["container_started_at"] = "0001-01-01T00:00:00Z"
    receipt["container_finished_at"] = "0001-01-01T00:00:00Z"
    path.write_bytes(encoded(receipt))


def test_snapshot_rejects_preexisting_created_terminal_receipt_with_start(operations, policy):
    _, root, _ = operations
    with opened(operations) as store:
        intent = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_created(created(intent))
        store.prepare_start()
        store.record_stopped(encoded(stopped(intent)))
    retained_created_receipt(root, intent)
    with (
        pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"),
        opened(operations) as store,
    ):
        snapshot(store)


@pytest.mark.parametrize("status,flag", [("created", True), ("created", False), ("exited", False)])
def test_historical_start_fenced_created_receipt_blocks_later_admission(
    operations, policy, status, flag
):
    api, root, clock = operations
    with opened(operations) as store:
        first = store.begin(policy)
        dispatch_prepared(store, policy, operations[2])
        store.record_created(created(first))
        store.prepare_start()
        store.record_stopped(encoded(stopped(first)))
    with opened(operations) as store:
        store.record_stopped(encoded(stopped(first)))
        second = store.begin(policy)
        removed(store, api, clock)
        dispatch_prepared(store, policy, clock)
        store.record_created(created(second, cid="e" * 64))
        store.prepare_start()
        store.record_stopped(encoded(stopped(second, cid="e" * 64)))
    retained_created_receipt(root, first)
    path = root / first.attempt_id / "stopped.json"
    receipt = json.loads(path.read_bytes())
    receipt["status"] = status
    receipt["start_fence_present"] = flag
    path.write_bytes(encoded(receipt))
    with (
        pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"),
        opened(operations) as store,
    ):
        store.begin(policy)
