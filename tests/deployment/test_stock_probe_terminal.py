"""Durable terminal sequencing; private evidence minting represents fictional wire EOF."""

import hashlib
import json
from dataclasses import replace

import pytest
from test_stock_probe_admission import admitted, opened, setup
from test_stock_probe_admission import scenario as admission_scenario
from test_stock_probe_cleanup import cleanup, running, started, stopped
from test_stock_probe_history import make_probe
from test_stock_probe_output import document, frame
from test_stock_probe_records import NOW, encoded


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    return admission_scenario.__wrapped__(tmp_path, monkeypatch)


def method(store, name):
    result = getattr(store, name, None)
    assert callable(result), "The probe store lacks terminal writer " + name
    return result


def natural(store, scenario, **facts):
    snapshot = started(store, scenario)
    scenario[2]["monotonic_ns"] += 2000000000
    raw = encoded(stopped(snapshot, **facts))
    store.record_stopped(raw)
    return snapshot, raw


def output(store, body=None, **kwargs):
    fence = method(store, "prepare_output")(**kwargs)
    store.claim_output(fence)
    return fence, store.record_output(fence, frame(document()) if body is None else body)


def removal(store, raw, **kwargs):
    fence = method(store, "prepare_removal")(**kwargs)
    store.claim_retirement(fence)
    store.claim_removal(fence, raw)
    proof = store._retirement_evidence(fence, "delete_204")
    store.record_removed(fence, proof)
    return fence


def test_natural_output_original_bytes_and_closed_success(scenario):
    _, root, clock, *_ = scenario
    with opened(scenario) as store:
        snapshot, raw = natural(store, scenario)
        fence, status = output(store)
        assert status == "valid" and fence.deadline_ns == NOW + 7000000000
        directory = root / snapshot.probe_id
        assert (directory / "framed-logs.bin").read_bytes() == frame(document())
        canonical = (directory / "configuration.bin").read_bytes()
        record = json.loads((directory / "output.json").read_bytes())
        assert record["canonical_sha256"] == hashlib.sha256(canonical).hexdigest()
        assert record["stopped_sha256"] == dict(store.snapshot().receipt_hashes)["stopped.json"]
        retired = removal(store, raw)
        assert retired.deadline_ns == clock["monotonic_ns"] + 15000000000
        assert store.close_success() == canonical
        assert store.snapshot().closed_outcome == "succeeded"
        with pytest.raises(ValueError):
            store.close_success()
    with opened(scenario) as recovered, pytest.raises(ValueError):
        recovered.close_success()


@pytest.mark.parametrize("body", [b"", b"x", frame(b"{}"), frame(document()) + frame(b"x", 2)])
def test_invalid_complete_output_remains_original_failure_evidence(scenario, body):
    _, root, *_ = scenario
    with opened(scenario) as store:
        snapshot, raw = natural(store, scenario)
        _, status = output(store, body)
        assert status == "invalid"
        directory = root / snapshot.probe_id
        assert (directory / "framed-logs.bin").read_bytes() == body
        assert not (directory / "configuration.bin").exists()
        removal(store, raw)
        with pytest.raises(ValueError):
            store.close_success()
    with opened(scenario) as recovered:
        token = cleanup(recovered)
        fence = method(recovered, "prepare_removal")(cleanup=token)
        recovered.claim_retirement(fence)
        proof = recovered._retirement_evidence(fence, "inspect_404")
        recovered.record_removed(fence, proof)
        recovered.close_failed("invalid_output")
        assert recovered.snapshot().closed_outcome == "failed"


@pytest.mark.parametrize("when", ["prepare", "claim", "record"])
def test_original_output_window_cannot_be_renewed(scenario, when):
    _, root, clock, *_ = scenario
    with opened(scenario) as store:
        snapshot, _ = natural(store, scenario)
        prepare = method(store, "prepare_output")
        fence = None if when == "prepare" else prepare()
        if when == "record":
            store.claim_output(fence)
        clock["monotonic_ns"] = NOW + 7000000000
        with pytest.raises(ValueError):
            if when == "prepare":
                prepare()
            elif when == "claim":
                store.claim_output(fence)
            else:
                store.record_output(fence, frame(document()))
        assert not (root / snapshot.probe_id / "output.json").exists()


def test_copied_output_fence_burns_retrieval_without_writing(scenario):
    with opened(scenario) as store:
        natural(store, scenario)
        fence = method(store, "prepare_output")()
        with pytest.raises(ValueError):
            store.claim_output(replace(fence))
        with pytest.raises(ValueError):
            store.claim_output(fence)
        with pytest.raises(ValueError):
            store.record_output(fence, frame(document()))


def test_output_requires_current_stop_and_actual_retrieval_claim(scenario):
    with opened(scenario) as store:
        started(store, scenario)
        with pytest.raises(ValueError):
            method(store, "prepare_output")()
    with opened(scenario) as recovered:
        token = cleanup(recovered)
        raw = encoded(stopped(recovered.snapshot()))
        recovered.record_stopped(raw, cleanup=token)
        fence = method(recovered, "prepare_output")(cleanup=token)
        with pytest.raises(ValueError):
            recovered.record_output(fence, frame(document()))


@pytest.mark.parametrize("point", ["framed-logs.bin", "configuration.bin", "output.json"])
def test_lost_output_ack_cannot_be_reconstructed_from_complete_files(scenario, monkeypatch, point):
    api, root, *_ = scenario
    with opened(scenario) as store:
        snapshot, _ = natural(store, scenario)
        fence = method(store, "prepare_output")()
        store.claim_output(fence)
        name = "_write_new" if point.endswith(".json") else "_write_bytes"
        original = getattr(api, name)

        def failed_ack(directory, slot, *args):
            result = original(directory, slot, *args)
            if slot == point:
                raise OSError("fictional post-write acknowledgement failure")
            return result

        monkeypatch.setattr(api, name, failed_ack)
        with pytest.raises(ValueError):
            store.record_output(fence, frame(document()))
        assert (root / snapshot.probe_id / point).exists()
        assert store._output_ack is None
        with pytest.raises(ValueError):
            store.record_output(fence, frame(document()))
        monkeypatch.setattr(api, name, original)
    if point == "output.json":
        with opened(scenario) as recovered:
            assert recovered.snapshot().output_status == "valid"
            with pytest.raises(ValueError):
                recovered.close_success()
    else:
        with pytest.raises(ValueError), opened(scenario):
            pass


def test_cleanup_valid_output_is_never_natural_success(scenario):
    with opened(scenario) as store:
        snapshot = started(store, scenario)
    with opened(scenario) as recovered:
        token = cleanup(recovered)
        raw = encoded(stopped(snapshot))
        recovered.record_stopped(raw, cleanup=token)
        fence, status = output(recovered, cleanup=token)
        assert status == "valid" and fence.deadline_ns <= token.final_deadline_ns
        removal(recovered, raw, cleanup=token)
        with pytest.raises(ValueError):
            recovered.close_success()
    with opened(scenario) as recovered:
        token = cleanup(recovered)
        fence = method(recovered, "prepare_removal")(cleanup=token)
        recovered.claim_retirement(fence)
        recovered.record_removed(fence, recovered._retirement_evidence(fence, "inspect_404"))
        recovered.close_failed("recovery")
        assert recovered.snapshot().closed_outcome == "failed"


@pytest.mark.parametrize("kind", ["delete_204", "inspect_404"])
def test_retirement_evidence_is_exact_registered_object(scenario, kind):
    with opened(scenario) as store:
        _, raw = natural(store, scenario)
        output(store)
        fence = method(store, "prepare_removal")()
        store.claim_retirement(fence)
        if kind == "delete_204":
            store.claim_removal(fence, raw)
        proof = store._retirement_evidence(fence, kind)
        with pytest.raises(ValueError):
            store.record_removed(fence, replace(proof))
        assert store._removed_ack is None
        with pytest.raises(ValueError):
            store.record_removed(fence, proof)


@pytest.mark.parametrize("stage", ["none", "inspection", "delete"])
def test_removal_requires_actual_single_use_sequencing(scenario, stage):
    with opened(scenario) as store:
        _, raw = natural(store, scenario)
        output(store)
        fence = method(store, "prepare_removal")()
        if stage != "none":
            store.claim_retirement(fence)
        if stage == "delete":
            store.claim_removal(fence, raw)
            with pytest.raises(ValueError):
                store.claim_removal(fence, raw)
        else:
            with pytest.raises(ValueError):
                store._retirement_evidence(fence, "delete_204")
        with pytest.raises(ValueError):
            store.claim_retirement(fence)


@pytest.mark.parametrize("change", ["running", "id", "lifetime", "created"])
def test_retirement_inspection_must_be_same_owned_stopped_lifetime(scenario, change):
    with opened(scenario) as store:
        snapshot, _ = natural(store, scenario)
        output(store)
        fence = method(store, "prepare_removal")()
        store.claim_retirement(fence)
        value = running(snapshot) if change == "running" else stopped(snapshot)
        if change == "id":
            value["Id"] = "e" * 64
        elif change == "lifetime":
            value["State"]["FinishedAt"] = "2026-10-21T21:00:02Z"
        elif change == "created":
            value = stopped(snapshot, "created")
        with pytest.raises(ValueError):
            store.claim_removal(fence, encoded(value))
        with pytest.raises(ValueError):
            store._retirement_evidence(fence, "delete_204")


def test_changed_cleanup_diagnostics_disable_natural_success(scenario):
    with opened(scenario) as store:
        snapshot, _ = natural(store, scenario)
        output(store)
        removal(store, encoded(stopped(snapshot, "dead", ExitCode=128, Error="fictional")))
        with pytest.raises(ValueError):
            store.close_success()


def test_recovery_existing_intent_uses_finite_new_cleanup_cap_without_rewrite(scenario):
    _, root, clock, *_ = scenario
    with opened(scenario) as store:
        snapshot, _ = natural(store, scenario)
        output(store)
        method(store, "prepare_removal")()
        original = (root / snapshot.probe_id / "removal-intent.json").read_bytes()
    clock["monotonic_ns"] += 200000000000
    with opened(scenario) as recovered:
        token = cleanup(recovered)
        fence = method(recovered, "prepare_removal")(cleanup=token)
        assert fence.deadline_ns == clock["monotonic_ns"] + 15000000000
        recovered.claim_retirement(fence)
        recovered.record_removed(fence, recovered._retirement_evidence(fence, "inspect_404"))
        recovered.close_failed("recovery")
        assert (root / snapshot.probe_id / "removal-intent.json").read_bytes() == original
        assert recovered.snapshot().closed_outcome == "failed"


def test_already_removed_receipt_and_present_resource_is_contradiction(scenario):
    with opened(scenario) as store:
        _, raw = natural(store, scenario)
        output(store)
        removal(store, raw)
    with opened(scenario) as recovered:
        token = cleanup(recovered)
        fence = method(recovered, "prepare_removal")(cleanup=token)
        recovered.claim_retirement(fence)
        with pytest.raises(ValueError):
            recovered.claim_removal(fence, raw)


@pytest.mark.parametrize("when", ["claim", "proof", "record", "closed"])
def test_retirement_deadline_never_renews(scenario, when):
    _, _, clock, *_ = scenario
    with opened(scenario) as store:
        _, raw = natural(store, scenario)
        output(store)
        fence = method(store, "prepare_removal")()
        if when != "claim":
            store.claim_retirement(fence)
            store.claim_removal(fence, raw)
        proof = None
        if when in ("record", "closed"):
            proof = store._retirement_evidence(fence, "delete_204")
        if when == "closed":
            store.record_removed(fence, proof)
        clock["monotonic_ns"] = fence.deadline_ns
        with pytest.raises(ValueError):
            if when == "claim":
                store.claim_retirement(fence)
            elif when == "proof":
                store._retirement_evidence(fence, "delete_204")
            elif when == "record":
                store.record_removed(fence, proof)
            else:
                store.close_success()


@pytest.mark.parametrize("facts", [{"ExitCode": 1}, {"OOMKilled": True}, {"Error": "fictional"}])
def test_nonnatural_process_cannot_close_success(scenario, facts):
    with opened(scenario) as store:
        _, raw = natural(store, scenario, **facts)
        output(store)
        removal(store, raw)
        with pytest.raises(ValueError):
            store.close_success()


@pytest.mark.parametrize("stage", ["intent", "create"])
def test_abandon_only_valid_no_create_intent(scenario, stage):
    with opened(scenario) as store:
        admitted(store, scenario)
        if stage == "create":
            store.prepare_create()
    with opened(scenario) as recovered:
        token = cleanup(recovered)
        abandon = method(recovered, "abandon")
        if stage == "create":
            with pytest.raises(ValueError):
                abandon(token)
        else:
            abandon(token)
            assert recovered.snapshot().closed_outcome == "abandoned_before_create"
        with pytest.raises(ValueError):
            abandon(token)


@pytest.mark.parametrize("copy_proof", [True, False])
def test_closed_entry_requires_current_exact_absence_and_fresh_durability(scenario, copy_proof):
    _, root, clock, *_ = scenario
    previous = make_probe(root)
    clock["monotonic_ns"] = previous["values"]["closed"]["monotonic_ns"] + 1
    with opened(scenario) as store:
        token = setup(store)
        proof = method(store, "_entry_absence_evidence")(token)
        if copy_proof:
            with pytest.raises(ValueError):
                store.record_entry_absence(token, replace(proof))
            with pytest.raises(ValueError):
                store.begin(token, scenario[3], scenario[4])
        else:
            store.record_entry_absence(token, proof)
            snapshot = store.begin(token, scenario[3], scenario[4])
            assert snapshot.probe_id != previous["probe_id"]
            assert snapshot.probe_id == token.probe_id
            intent = json.loads((root / snapshot.probe_id / "intent.json").read_bytes())
            assert intent["predecessor_closed_sha256"] == previous["hashes"]["closed"]


def test_closed_entry_absence_flush_cannot_extend_setup_or_ignore_failure(scenario, monkeypatch):
    api, root, clock, *_ = scenario
    previous = make_probe(root)
    clock["monotonic_ns"] = previous["values"]["closed"]["monotonic_ns"] + 1
    with opened(scenario) as store:
        token = setup(store)
        proof = method(store, "_entry_absence_evidence")(token)
        original = api._reconfirm_durability

        def late(*args):
            result = original(*args)
            clock["monotonic_ns"] = token.deadline_ns
            return result

        monkeypatch.setattr(api, "_reconfirm_durability", late)
        with pytest.raises(ValueError):
            store.record_entry_absence(token, proof)
        with pytest.raises(ValueError):
            store.begin(token, scenario[3], scenario[4])
        assert not (root / token.probe_id).exists()


@pytest.mark.parametrize("slot", ["removal-intent.json", "removed.json", "closed.json"])
def test_post_write_lost_ack_never_grants_terminal_authority(scenario, monkeypatch, slot):
    api, root, *_ = scenario
    with opened(scenario) as store:
        snapshot, raw = natural(store, scenario)
        output(store)
        original = api._write_new

        def failed_ack(directory, name, *args):
            result = original(directory, name, *args)
            if name == slot:
                raise OSError("fictional post-write acknowledgement failure")
            return result

        if slot != "removal-intent.json":
            fence = method(store, "prepare_removal")()
            store.claim_retirement(fence)
            store.claim_removal(fence, raw)
            proof = store._retirement_evidence(fence, "delete_204")
            if slot == "closed.json":
                store.record_removed(fence, proof)
        monkeypatch.setattr(api, "_write_new", failed_ack)
        with pytest.raises(ValueError):
            if slot == "removal-intent.json":
                store.prepare_removal()
            elif slot == "removed.json":
                store.record_removed(fence, proof)
            else:
                store.close_success()
        assert (root / snapshot.probe_id / slot).exists()
        if slot == "removal-intent.json":
            assert store._removal_token is None
        elif slot == "removed.json":
            assert store._removed_ack is None
        with pytest.raises(ValueError):
            store.close_success()
        monkeypatch.setattr(api, "_write_new", original)
    with opened(scenario) as recovered:
        if slot != "closed.json":
            token = cleanup(recovered)
            fence = recovered.prepare_removal(cleanup=token)
            recovered.claim_retirement(fence)
            recovered.record_removed(fence, recovered._retirement_evidence(fence, "inspect_404"))
            recovered.close_failed("recovery")
            assert recovered.snapshot().closed_outcome == "failed"
        else:
            assert recovered.snapshot().closed_outcome == "succeeded"
            with pytest.raises(ValueError):
                recovered.close_success()
            new_setup = setup(recovered)
            with pytest.raises(ValueError):
                recovered.begin(new_setup, scenario[3], scenario[4])


@pytest.mark.parametrize("phase", ["output", "removal", "removed", "closed", "abandon"])
def test_late_durable_ack_cannot_return_authority(scenario, monkeypatch, phase):
    api, _, clock, *_ = scenario
    with opened(scenario) as store:
        if phase == "abandon":
            admitted(store, scenario)
            token = cleanup(store)
            deadline = token.final_deadline_ns
            slot = "closed.json"
        else:
            _, raw = natural(store, scenario)
            output_fence = method(store, "prepare_output")()
            store.claim_output(output_fence)
            if phase != "output":
                store.record_output(output_fence, frame(document()))
            if phase in ("removed", "closed"):
                fence = store.prepare_removal()
                store.claim_retirement(fence)
                store.claim_removal(fence, raw)
                proof = store._retirement_evidence(fence, "delete_204")
                if phase == "closed":
                    store.record_removed(fence, proof)
                deadline = fence.deadline_ns
            elif phase == "removal":
                deadline = clock["monotonic_ns"] + 15000000000
            else:
                deadline = output_fence.deadline_ns
            slot = {
                "output": "output.json",
                "removal": "removal-intent.json",
                "removed": "removed.json",
                "closed": "closed.json",
            }[phase]
        original = api._write_new

        def late(directory, name, *args):
            result = original(directory, name, *args)
            if name == slot:
                clock["monotonic_ns"] = deadline
            return result

        monkeypatch.setattr(api, "_write_new", late)
        with pytest.raises(ValueError):
            if phase == "output":
                store.record_output(output_fence, frame(document()))
            elif phase == "removal":
                store.prepare_removal()
            elif phase == "removed":
                store.record_removed(fence, proof)
            elif phase == "closed":
                store.close_success()
            else:
                store.abandon(token)
        if phase == "output":
            assert store._output_ack is None
        elif phase == "removal":
            assert store._removal_token is None
        elif phase == "removed":
            assert store._removed_ack is None


@pytest.mark.parametrize("point", ["stop", "intent"])
def test_failed_fresh_removal_durability_does_not_dispatch_delete(scenario, monkeypatch, point):
    api, _, *_ = scenario
    with opened(scenario) as store:
        _, raw = natural(store, scenario)
        output(store)
        fence = method(store, "prepare_removal")()
        store.claim_retirement(fence)
        original = api._reconfirm_durability

        def failed(directory, name, *args):
            if name == ("stopped.json" if point == "stop" else "removal-intent.json"):
                raise OSError("fictional durability failure")
            return original(directory, name, *args)

        monkeypatch.setattr(api, "_reconfirm_durability", failed)
        with pytest.raises(ValueError):
            store.claim_removal(fence, raw)
        assert not store._delete_ready
        with pytest.raises(ValueError):
            store._retirement_evidence(fence, "delete_204")


@pytest.mark.parametrize("target", ["record_removed", "close_success", "entry"])
def test_fresh_durability_failure_does_not_reconstruct_ack(scenario, monkeypatch, target):
    api, root, clock, *_ = scenario
    if target == "entry":
        previous = make_probe(root)
        clock["monotonic_ns"] = previous["values"]["closed"]["monotonic_ns"] + 1
    with opened(scenario) as store:
        if target == "entry":
            token = setup(store)
            proof = method(store, "_entry_absence_evidence")(token)
        else:
            _, raw = natural(store, scenario)
            output(store)
            fence = method(store, "prepare_removal")()
            store.claim_retirement(fence)
            store.claim_removal(fence, raw)
            proof = store._retirement_evidence(fence, "delete_204")
            if target == "close_success":
                store.record_removed(fence, proof)

        def failed(*args):
            raise OSError("fictional durability failure")

        monkeypatch.setattr(api, "_reconfirm_durability", failed)
        with pytest.raises(ValueError):
            if target == "entry":
                store.record_entry_absence(token, proof)
            elif target == "record_removed":
                store.record_removed(fence, proof)
            else:
                store.close_success()
        if target == "entry":
            assert store._entry_absence_ack is None
        elif target == "record_removed":
            assert store._removed_ack is None
        with pytest.raises(ValueError):
            store.close_success()


@pytest.mark.parametrize("change", ["boot", "mono", "utc"])
@pytest.mark.parametrize("point", ["output", "removal", "removed", "closed"])
def test_clock_discontinuity_denies_terminal_progress_and_success(scenario, change, point):
    _, _, clock, *_ = scenario
    with opened(scenario) as store:
        _, raw = natural(store, scenario)
        if point != "output":
            output(store)
        if point in ("removed", "closed"):
            fence = method(store, "prepare_removal")()
            store.claim_retirement(fence)
            store.claim_removal(fence, raw)
            proof = store._retirement_evidence(fence, "delete_204")
            if point == "closed":
                store.record_removed(fence, proof)
        if change == "boot":
            clock["boot_id"] = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        elif change == "mono":
            clock["monotonic_ns"] -= 1
        else:
            clock["utc"] = "2026-10-21T20:59:59+00:00"
        with pytest.raises(ValueError):
            if point == "output":
                method(store, "prepare_output")()
            elif point == "removal":
                store.prepare_removal()
            elif point == "removed":
                store.record_removed(fence, proof)
            else:
                store.close_success()
        assert store.recovery_only
        assert store._natural_stopped_ack is None and store._removed_ack is None


@pytest.mark.parametrize("reason", ["completed", "", "private fictional error", None, True])
def test_failed_closure_accepts_only_safe_reason_enum(scenario, reason):
    _, root, *_ = scenario
    with opened(scenario) as store:
        snapshot, raw = natural(store, scenario)
        output(store)
        removal(store, raw)
        with pytest.raises(ValueError):
            store.close_failed(reason)
        assert not (root / snapshot.probe_id / "closed.json").exists()


@pytest.mark.parametrize("body", ["text", bytearray(b"x"), b"x" * 16385])
def test_output_limit_or_type_failure_leaves_no_ack(scenario, body):
    with opened(scenario) as store:
        natural(store, scenario)
        fence = method(store, "prepare_output")()
        store.claim_output(fence)
        with pytest.raises(ValueError):
            store.record_output(fence, body)
        assert store._output_ack is None


def test_reopened_fence_and_private_proof_objects_cannot_resume_dispatch(scenario):
    with opened(scenario) as store:
        _, raw = natural(store, scenario)
        output(store)
        fence = method(store, "prepare_removal")()
        store.claim_retirement(fence)
        store.claim_removal(fence, raw)
        proof = store._retirement_evidence(fence, "delete_204")
    with opened(scenario) as recovered:
        with pytest.raises(ValueError):
            recovered.check_removal_fence(fence)
        with pytest.raises(ValueError):
            recovered.record_removed(fence, proof)
        with pytest.raises(ValueError):
            recovered.close_success()


def test_valid_failure_can_close_in_normal_session_without_success_attempt(scenario):
    with opened(scenario) as store:
        _, raw = natural(store, scenario, ExitCode=1)
        output(store)
        removal(store, raw)
        store.close_failed("process_failed")
        assert store.snapshot().closed_outcome == "failed"


def test_delayed_normal_retirement_entry_cannot_reopen_completed_output_window(scenario):
    _, root, clock, *_ = scenario
    with opened(scenario) as store:
        snapshot, _ = natural(store, scenario)
        output(store)
        clock["monotonic_ns"] = NOW + 7000000000
        with pytest.raises(ValueError):
            store.prepare_removal()
        assert store._removal_token is None
        assert not (root / snapshot.probe_id / "removal-intent.json").exists()


def test_recovery_cannot_inspect_until_saved_removal_intent_is_freshly_acknowledged(
    scenario, monkeypatch
):
    api, *_ = scenario
    with opened(scenario) as store:
        natural(store, scenario)
        output(store)
        method(store, "prepare_removal")()
    with opened(scenario) as recovered:
        token = cleanup(recovered)
        original = api._reconfirm_durability

        def failed(directory, name, *args):
            if name == "removal-intent.json":
                raise OSError("fictional saved-intent durability failure")
            return original(directory, name, *args)

        monkeypatch.setattr(api, "_reconfirm_durability", failed)
        with pytest.raises(ValueError):
            recovered.prepare_removal(cleanup=token)
        assert recovered._removal_token is None


@pytest.mark.parametrize("point", ["artifact", "lock", "directory"])
def test_entry_absence_io_failure_consumes_ack_and_blocks_successor(scenario, monkeypatch, point):
    api, root, clock, *_ = scenario
    previous = make_probe(root)
    clock["monotonic_ns"] = previous["values"]["closed"]["monotonic_ns"] + 1
    with opened(scenario) as store:
        token = setup(store)
        proof = method(store, "_entry_absence_evidence")(token)
        if point == "artifact":
            def fail_artifact(*args):
                raise OSError("fictional artifact sync failure")

            monkeypatch.setattr(api, "_reconfirm_bytes", fail_artifact)
        else:
            original = api.os.fsync
            target = store._lock if point == "lock" else store._directory

            def fail_sync(fd):
                if fd == target:
                    raise OSError("fictional metadata sync failure")
                return original(fd)

            monkeypatch.setattr(api.os, "fsync", fail_sync)
        with pytest.raises(ValueError):
            store.record_entry_absence(token, proof)
        assert store._entry_absence_ack is None
        with pytest.raises(ValueError):
            store.record_entry_absence(token, proof)
        with pytest.raises(ValueError):
            store.begin(token, scenario[3], scenario[4])
        assert not (root / token.probe_id).exists()


@pytest.mark.parametrize("phase", ["removed", "closed", "entry"])
@pytest.mark.parametrize("change", ["boot", "mono", "utc"])
def test_clock_discontinuity_during_fresh_terminal_flush_denies_ack(
    scenario, monkeypatch, phase, change
):
    api, root, clock, *_ = scenario
    if phase == "entry":
        previous = make_probe(root)
        clock["monotonic_ns"] = previous["values"]["closed"]["monotonic_ns"] + 1
    with opened(scenario) as store:
        if phase == "entry":
            token = setup(store)
            proof = method(store, "_entry_absence_evidence")(token)
        else:
            _, raw = natural(store, scenario)
            output(store)
            fence = method(store, "prepare_removal")()
            store.claim_retirement(fence)
            store.claim_removal(fence, raw)
            proof = store._retirement_evidence(fence, "delete_204")
            if phase == "closed":
                store.record_removed(fence, proof)
        original = api._reconfirm_durability

        def changed_during_flush(directory, name, *args):
            result = original(directory, name, *args)
            if name == ("namespace.json" if phase == "entry" else "intent.json"):
                if change == "boot":
                    clock["boot_id"] = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
                elif change == "mono":
                    clock["monotonic_ns"] -= 1
                else:
                    clock["utc"] = "2026-10-21T20:59:59+00:00"
            return result

        monkeypatch.setattr(api, "_reconfirm_durability", changed_during_flush)
        with pytest.raises(ValueError):
            if phase == "entry":
                store.record_entry_absence(token, proof)
            elif phase == "removed":
                store.record_removed(fence, proof)
            else:
                store.close_success()
        assert store.recovery_only and store._removed_ack is None
        assert store._entry_absence_ack is None


@pytest.mark.parametrize("phase", ["removed", "entry"])
@pytest.mark.parametrize("slot", ["engine.bin", "stopped.json", "active.json"])
def test_substitution_after_evidence_cannot_acknowledge_or_retry(scenario, phase, slot):
    _, root, clock, *_ = scenario
    if phase == "entry":
        previous = make_probe(root)
        clock["monotonic_ns"] = previous["values"]["closed"]["monotonic_ns"] + 1
    with opened(scenario) as store:
        if phase == "entry":
            snapshot = store.snapshot()
            token = setup(store)
            proof = method(store, "_entry_absence_evidence")(token)
        else:
            snapshot, raw = natural(store, scenario)
            output(store)
            fence = method(store, "prepare_removal")()
            store.claim_retirement(fence)
            store.claim_removal(fence, raw)
            proof = store._retirement_evidence(fence, "delete_204")
        path = root / "active.json" if slot == "active.json" else root / snapshot.probe_id / slot
        path.write_bytes(path.read_bytes() + b" ")
        for _ in range(2):
            with pytest.raises(ValueError):
                if phase == "entry":
                    store.record_entry_absence(token, proof)
                else:
                    store.record_removed(fence, proof)
        assert store._removed_ack is None and store._entry_absence_ack is None


def test_maximum_history_successor_admission_keeps_original_real_time_caps(scenario, monkeypatch):
    import time

    api, root, clock, *_ = scenario
    previous = None
    for number in range(1, 128):
        previous = make_probe(root, number=number, predecessor=previous)
    base = previous["values"]["closed"]["monotonic_ns"] + 1
    native_origin = time.monotonic_ns()
    monkeypatch.setattr(
        api,
        "_clock",
        lambda: {**clock, "monotonic_ns": base + time.monotonic_ns() - native_origin},
    )
    with opened(scenario) as store:
        token = setup(store)
        proof = method(store, "_entry_absence_evidence")(token)
        store.record_entry_absence(token, proof)
        snapshot = store.begin(token, scenario[3], scenario[4])
        fence = store.prepare_create()
        store.claim_create(fence)
        assert snapshot.probe_id == token.probe_id
        assert fence.deadline_ns <= token.deadline_ns
        assert api._clock()["monotonic_ns"] < fence.deadline_ns
        print(
            "127-predecessor actual local setup seconds:",
            (time.monotonic_ns() - native_origin) / 1e9,
        )
