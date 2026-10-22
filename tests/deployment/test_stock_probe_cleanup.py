"""Root cleanup and STOP sequencing with fictional process observations only."""

import json
from dataclasses import replace

import pytest
from test_stock_probe_admission import OTHER_BOOT, admitted, created, opened, prepared_start
from test_stock_probe_admission import scenario as admission_scenario
from test_stock_probe_history import make_probe
from test_stock_probe_records import NOW, ZERO, encoded


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    return admission_scenario.__wrapped__(tmp_path, monkeypatch)


def running(snapshot):
    return {
        "Id": "f" * 64,
        "Image": snapshot.image_digest,
        "Name": "/hybrid-stock-probe-" + snapshot.probe_id,
        "Platform": "linux",
        "RestartCount": 0,
        "Config": {
            "Labels": {
                "org.hybrid.stock.managed": "stock-configuration-probe",
                "org.hybrid.stock.probe": snapshot.probe_id,
            }
        },
        "HostConfig": {
            "AutoRemove": False,
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
        },
        "State": {
            "Status": "running",
            "Running": True,
            "Paused": False,
            "Restarting": False,
            "OOMKilled": False,
            "Dead": False,
            "Pid": 200,
            "ExitCode": 0,
            "Error": "",
            "StartedAt": "2026-10-21T21:00:00.123456789Z",
            "FinishedAt": ZERO,
        },
    }


def stopped(snapshot, status="exited", **facts):
    value = running(snapshot)
    value["State"].update(
        Status=status,
        Running=False,
        Dead=status == "dead",
        Pid=0,
        StartedAt=ZERO if status == "created" else "2026-10-21T21:00:00.123456789Z",
        FinishedAt=ZERO if status == "created" else "2026-10-21T21:00:01.123456789Z",
        **facts,
    )
    return value


def started(store, scenario):
    _, snapshot, _, fence = prepared_start(store, scenario)
    store.claim_start(fence)
    return snapshot


def cleanup(store):
    claim = getattr(store, "begin_cleanup", None)
    assert callable(claim), "The probe store lacks bounded cleanup ownership"
    return claim()


def test_shutdown_cleanup_uses_one_earlier_origin_and_never_renews(scenario):
    _, _, clock, *_ = scenario
    with opened(scenario) as store:
        snapshot = started(store, scenario)
        clock["monotonic_ns"] += 1000000000
        token = cleanup(store)
        assert token.origin_ns == NOW + 1000000000
        assert (token.term_deadline_ns, token.kill_deadline_ns, token.final_deadline_ns) == (
            NOW + 11000000000,
            NOW + 16000000000,
            NOW + 21000000000,
        )
        assert store.recovery_only and store.cleanup_target(token).probe_id == snapshot.probe_id
        assert store.snapshot().run_deadline_ns == NOW + 30000000000
        with pytest.raises(ValueError):
            cleanup(store)
        with pytest.raises(ValueError):
            store.prepare_start()
        with pytest.raises(ValueError):
            store.check_cleanup(replace(token))
        clock["monotonic_ns"] = token.final_deadline_ns
        with pytest.raises(ValueError):
            store.check_cleanup(token)
        assert token.final_deadline_ns == NOW + 21000000000


def test_expired_run_cleanup_uses_original_run_deadline_not_late_observation(scenario):
    _, _, clock, *_ = scenario
    with opened(scenario) as store:
        started(store, scenario)
        clock["monotonic_ns"] = NOW + 31000000000
        token = cleanup(store)
        assert (token.origin_ns, token.final_deadline_ns) == (NOW + 30000000000, NOW + 50000000000)


def test_missed_all_normal_cleanup_caps_requires_a_later_explicit_recovery(scenario):
    _, _, clock, *_ = scenario
    with opened(scenario) as store:
        started(store, scenario)
        clock["monotonic_ns"] = NOW + 50000000000
        with pytest.raises(ValueError):
            cleanup(store)
        with pytest.raises(ValueError):
            cleanup(store)
    with opened(scenario) as recovered:
        token = cleanup(recovered)
        assert token.origin_ns == NOW + 50000000000
        assert recovered.snapshot().run_deadline_ns == NOW + 30000000000
        assert recovered.recovery_only


@pytest.mark.parametrize("change", ["boot", "monotonic", "utc"])
def test_first_clock_discontinuity_enters_one_current_domain_cleanup(scenario, change):
    _, _, clock, *_ = scenario
    with opened(scenario) as store:
        started(store, scenario)
        if change == "boot":
            clock["boot_id"] = OTHER_BOOT
        elif change == "monotonic":
            clock["monotonic_ns"] -= 1
        else:
            clock["utc"] = "2026-10-21T20:59:59+00:00"
        token = cleanup(store)
        assert token.boot_id == clock["boot_id"] and token.origin_ns == clock["monotonic_ns"]
        assert store.recovery_only
        clock["monotonic_ns"] -= 1
        with pytest.raises(ValueError):
            store.check_cleanup(token)
        with pytest.raises(ValueError):
            cleanup(store)


def test_empty_cleanup_burns_admission_and_closed_history_cannot_be_adopted(scenario):
    _, root, *_ = scenario
    with opened(scenario) as store:
        assert cleanup(store) is None
        with pytest.raises(ValueError):
            store.begin_setup("sha256:" + "b" * 64)
    make_probe(root)
    with opened(scenario) as store, pytest.raises(ValueError):
        cleanup(store)


def test_recovery_name_inspection_retains_full_cid_and_original_bytes_only(scenario):
    _, root, *_ = scenario
    with opened(scenario) as store:
        _, snapshot = admitted(store, scenario)
        store.prepare_create()
    with opened(scenario) as recovered:
        token = cleanup(recovered)
        raw = encoded(stopped(snapshot, "created"))
        assert recovered.record_discovered_cid(token, raw) == "f" * 64
        assert recovered.cleanup_target(token).container_id == "f" * 64
        assert (root / snapshot.probe_id / "discovery.bin").read_bytes() == raw
        value = json.loads((root / snapshot.probe_id / "cid.json").read_bytes())
        assert value["evidence_kind"] == "name_inspection"
        assert not (root / snapshot.probe_id / "create-response.bin").exists()
        with pytest.raises(ValueError):
            recovered.prepare_start()
        with pytest.raises(ValueError):
            recovered.record_discovered_cid(token, raw)


@pytest.mark.parametrize("change", ["name", "id", "image", "labels"])
def test_name_lookup_cannot_capture_an_unowned_or_abbreviated_cid(scenario, change):
    _, root, *_ = scenario
    with opened(scenario) as store:
        _, snapshot = admitted(store, scenario)
        store.prepare_create()
    with opened(scenario) as recovered:
        token = cleanup(recovered)
        value = stopped(snapshot, "created")
        if change == "name":
            value["Name"] = "/another-container"
        elif change == "id":
            value["Id"] = "f" * 12
        elif change == "image":
            value["Image"] = "sha256:" + "e" * 64
        else:
            value["Config"]["Labels"]["org.hybrid.stock.probe"] = "e" * 32
        with pytest.raises(ValueError):
            recovered.record_discovered_cid(token, encoded(value))
        assert not (root / snapshot.probe_id / "cid.json").exists()


def test_natural_stop_has_durable_original_facts_without_extending_run(scenario):
    _, root, clock, *_ = scenario
    with opened(scenario) as store:
        snapshot = started(store, scenario)
        clock["monotonic_ns"] = NOW + 25000000000
        raw = encoded(stopped(snapshot))
        actual = store.record_stopped(raw)
        assert actual.status == "exited" and not store.recovery_only
        assert store.snapshot().run_deadline_ns == NOW + 30000000000
        assert (root / snapshot.probe_id / "stopped.bin").read_bytes() == raw
        value = json.loads((root / snapshot.probe_id / "stopped.json").read_bytes())
        assert value["monotonic_ns"] == NOW + 25000000000
        assert value["start_sha256"] == dict(store.snapshot().receipt_hashes)["start.json"]
        assert value["container_finished_at"] == "2026-10-21T21:00:01.123456789Z"
        with pytest.raises(ValueError):
            store.record_stopped(raw)


@pytest.mark.parametrize("status", ["created", "exited", "dead"])
def test_cleanup_without_start_can_acknowledge_owned_stopped_failure_facts(scenario, status):
    _, root, *_ = scenario
    with opened(scenario) as store:
        _, snapshot, _ = created(store, scenario)
        token = cleanup(store)
        raw = encoded(
            stopped(snapshot, status, ExitCode=128, Error="sensitive fictional start error")
        )
        actual = store.record_stopped(raw, cleanup=token)
        assert actual.status == status and actual.error_present and actual.exit_code == 128
        assert store.recovery_only
        assert "sensitive" not in (root / snapshot.probe_id / "stopped.json").read_text()
        assert not (root / snapshot.probe_id / "start.json").exists()


@pytest.mark.parametrize("status", ["created", "running"])
def test_queued_start_or_running_state_cannot_acknowledge_stopped(scenario, status):
    _, root, *_ = scenario
    with opened(scenario) as store:
        snapshot = started(store, scenario)
        token = cleanup(store)
        value = running(snapshot) if status == "running" else stopped(snapshot, "created")
        with pytest.raises(ValueError):
            store.record_stopped(encoded(value), cleanup=token)
        assert not (root / snapshot.probe_id / "stopped.json").exists()


@pytest.mark.parametrize("operation", ["record", "reconfirm"])
@pytest.mark.parametrize("change", ["cid", "image", "name", "lifetime"])
def test_changed_stopped_identity_or_lifetime_cannot_be_reconfirmed(scenario, operation, change):
    _, root, *_ = scenario
    with opened(scenario) as store:
        snapshot = started(store, scenario)
        original = encoded(stopped(snapshot))
        store.record_stopped(original)
    with opened(scenario) as recovered:
        token = cleanup(recovered)
        value = stopped(snapshot)
        if change == "cid":
            value["Id"] = "e" * 64
        elif change == "image":
            value["Image"] = "sha256:" + "e" * 64
        elif change == "name":
            value["Name"] = "/another-container"
        else:
            value["State"]["FinishedAt"] = "2026-10-21T21:00:01.123456788Z"
        with pytest.raises(ValueError):
            if operation == "record":
                recovered.record_stopped(encoded(value), cleanup=token)
            else:
                recovered.reconfirm_stopped(token, encoded(value))
        assert (root / snapshot.probe_id / "stopped.bin").read_bytes() == original


def test_later_dead_error_facts_can_reconfirm_same_lifetime_for_cleanup_only(scenario):
    _, root, *_ = scenario
    with opened(scenario) as store:
        snapshot = started(store, scenario)
        original = encoded(stopped(snapshot))
        store.record_stopped(original)
    with opened(scenario) as recovered:
        token = cleanup(recovered)
        actual = recovered.reconfirm_stopped(
            token, encoded(stopped(snapshot, "dead", Error="later fictional removal error"))
        )
        assert actual.status == "dead" and actual.error_present and recovered.recovery_only
        assert (root / snapshot.probe_id / "stopped.bin").read_bytes() == original
        with pytest.raises(ValueError):
            recovered.prepare_start()


@pytest.mark.parametrize("stage", ["artifact", "receipt", "post-clock"])
def test_failed_stop_acknowledgement_does_not_adopt_complete_bytes(scenario, monkeypatch, stage):
    api, root, clock, *_ = scenario
    with opened(scenario) as store:
        snapshot = started(store, scenario)
        raw = encoded(stopped(snapshot))
        original_bytes, original_receipt = api._write_bytes, api._write_new
        if stage == "artifact":

            def failing_bytes(directory, name, body, uid):
                result = original_bytes(directory, name, body, uid)
                if name == "stopped.bin":
                    raise OSError("fictional lost byte acknowledgement")
                return result

            monkeypatch.setattr(api, "_write_bytes", failing_bytes)
        else:

            def failing_receipt(directory, name, value, uid):
                result = original_receipt(directory, name, value, uid)
                if name == "stopped.json":
                    if stage == "post-clock":
                        clock["monotonic_ns"] = NOW + 30000000000
                    else:
                        raise OSError("fictional lost receipt acknowledgement")
                return result

            monkeypatch.setattr(api, "_write_new", failing_receipt)
        with pytest.raises(ValueError):
            store.record_stopped(raw)
        assert (root / snapshot.probe_id / "stopped.bin").read_bytes() == raw
        with pytest.raises(ValueError):
            store.record_stopped(raw)
    if stage == "artifact":
        with pytest.raises(ValueError), opened(scenario):
            pytest.fail("torn artifact was synthesized into a receipt")
    else:
        with opened(scenario) as recovered:
            token = cleanup(recovered)
            assert recovered.reconfirm_stopped(token, raw).status == "exited"
            assert recovered.recovery_only


def test_term_and_kill_are_one_use_phase_bound_and_require_fresh_running_ownership(scenario):
    _, _, clock, *_ = scenario
    with opened(scenario) as store:
        snapshot = started(store, scenario)
        token = cleanup(store)
        term = store.prepare_signal(token, "TERM")
        assert term.container_id == "f" * 64 and term.deadline_ns == token.term_deadline_ns
        with pytest.raises(ValueError):
            store.check_signal_fence(replace(term))
        store.claim_signal(term, encoded(running(snapshot)))
        store.check_signal_fence(term)
        with pytest.raises(ValueError):
            store.claim_signal(term, encoded(running(snapshot)))
        with pytest.raises(ValueError):
            store.prepare_signal(token, "TERM")
        clock["monotonic_ns"] = token.term_deadline_ns
        kill = store.prepare_signal(token, "KILL")
        assert kill.deadline_ns == token.kill_deadline_ns
        store.claim_signal(kill, encoded(running(snapshot)))
        clock["monotonic_ns"] = token.kill_deadline_ns
        with pytest.raises(ValueError):
            store.check_signal_fence(kill)
        assert store.snapshot().stopped is None


def test_early_kill_cannot_renew_grace_or_retry_after_failed_preparation(scenario):
    with opened(scenario) as store:
        started(store, scenario)
        token = cleanup(store)
        with pytest.raises(ValueError):
            store.prepare_signal(token, "KILL")
        with pytest.raises(ValueError):
            store.prepare_signal(token, "KILL")


@pytest.mark.parametrize("mode", ["no-start", "stopped", "wrong-cid"])
def test_signal_never_targets_an_unstarted_stopped_or_unowned_process(scenario, mode):
    with opened(scenario) as store:
        if mode == "no-start":
            _, snapshot, _ = created(store, scenario)
        else:
            snapshot = started(store, scenario)
        token = cleanup(store)
        if mode == "no-start":
            with pytest.raises(ValueError):
                store.prepare_signal(token, "TERM")
        else:
            fence = store.prepare_signal(token, "TERM")
            value = stopped(snapshot) if mode == "stopped" else running(snapshot)
            if mode == "wrong-cid":
                value["Id"] = "e" * 64
            with pytest.raises(ValueError):
                store.claim_signal(fence, encoded(value))


def test_pending_exact_intent_can_be_cleaned_after_head_acknowledgement_failure(
    scenario, monkeypatch
):
    api, root, *_ = scenario
    with opened(scenario) as store:
        setup = store.begin_setup("sha256:" + "b" * 64)
        original = api.os.replace

        def failed_ack(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("fictional head acknowledgement failure")

        monkeypatch.setattr(api.os, "replace", failed_ack)
        with pytest.raises(ValueError):
            store.begin(setup, scenario[3], scenario[4])
        monkeypatch.setattr(api.os, "replace", original)
        token = cleanup(store)
        assert token.probe_id == setup.probe_id
        assert store.cleanup_target(token).container_id is None
        assert not (root / token.probe_id / "create.json").exists()


def test_unexpected_valid_head_after_entry_is_not_adopted_for_cleanup(scenario):
    _, root, *_ = scenario
    with opened(scenario) as store:
        make_probe(root, stage="intent")
        with pytest.raises(ValueError):
            cleanup(store)


def test_name_discovery_requires_a_retained_create_fence(scenario):
    with opened(scenario) as store:
        _, snapshot = admitted(store, scenario)
    with opened(scenario) as recovered:
        token = cleanup(recovered)
        with pytest.raises(ValueError):
            recovered.record_discovered_cid(token, encoded(stopped(snapshot, "created")))


def test_discovery_cannot_reuse_a_prior_full_cid(scenario):
    _, root, *_ = scenario
    prior = make_probe(root, number=1)
    current = make_probe(root, number=2, predecessor=prior, stage="create")
    with opened(scenario) as recovered:
        token = cleanup(recovered)
        snapshot = recovered.cleanup_target(token)
        value = stopped(snapshot, "created")
        value["Id"] = prior["cid"]
        with pytest.raises(ValueError):
            recovered.record_discovered_cid(token, encoded(value))
        assert not (root / current["probe_id"] / "cid.json").exists()


def test_late_discovery_ack_does_not_renew_original_cleanup_cap(scenario, monkeypatch):
    api, _, clock, *_ = scenario
    with opened(scenario) as store:
        _, snapshot = admitted(store, scenario)
        store.prepare_create()
    with opened(scenario) as recovered:
        token = cleanup(recovered)
        original = api._write_new

        def delayed(directory, name, value, uid):
            result = original(directory, name, value, uid)
            if name == "cid.json":
                clock["monotonic_ns"] = token.final_deadline_ns
            return result

        monkeypatch.setattr(api, "_write_new", delayed)
        with pytest.raises(ValueError):
            recovered.record_discovered_cid(token, encoded(stopped(snapshot, "created")))
        with pytest.raises(ValueError):
            recovered.check_cleanup(token)
        with pytest.raises(ValueError):
            cleanup(recovered)


def test_no_normal_stop_acknowledgement_without_actual_start_dispatch_claim(scenario):
    _, root, *_ = scenario
    with opened(scenario) as store:
        _, snapshot, _, _ = prepared_start(store, scenario)
        with pytest.raises(ValueError):
            store.record_stopped(encoded(stopped(snapshot)))
        assert not (root / snapshot.probe_id / "stopped.json").exists()


@pytest.mark.parametrize("stage", ["fsync", "clock"])
def test_failed_stopped_reconfirmation_does_not_adopt_cached_complete_bytes(
    scenario, monkeypatch, stage
):
    api, _, clock, *_ = scenario
    with opened(scenario) as store:
        snapshot = started(store, scenario)
        raw = encoded(stopped(snapshot))
        store.record_stopped(raw)
    with opened(scenario) as recovered:
        token = cleanup(recovered)
        original = api._reconfirm_bytes

        def failed_reconfirm(*args):
            result = original(*args)
            if stage == "fsync":
                raise OSError("fictional failed reconfirmation acknowledgement")
            clock["monotonic_ns"] = token.final_deadline_ns
            return result

        monkeypatch.setattr(api, "_reconfirm_bytes", failed_reconfirm)
        with pytest.raises(ValueError):
            recovered.reconfirm_stopped(token, raw)
        with pytest.raises(ValueError):
            recovered.reconfirm_stopped(token, raw)
        assert recovered.recovery_only


@pytest.mark.parametrize("stage", ["invalid-clock", "second-shift"])
def test_uncertain_clock_during_cleanup_never_obtains_an_unbounded_fallback(
    scenario, monkeypatch, stage
):
    api, _, clock, *_ = scenario
    with opened(scenario) as store:
        started(store, scenario)
        if stage == "invalid-clock":
            clock["monotonic_ns"] = True
        else:
            calls = 0

            def shifting():
                nonlocal calls
                calls += 1
                return {**clock, "monotonic_ns": NOW - calls}

            monkeypatch.setattr(api, "_clock", shifting)
        with pytest.raises(ValueError):
            cleanup(store)
        with pytest.raises(ValueError):
            cleanup(store)


@pytest.mark.parametrize("change", ["cid", "lifetime", "state"])
def test_stored_stop_is_not_rewritten_from_a_contradictory_reconfirmation(scenario, change):
    _, root, *_ = scenario
    with opened(scenario) as store:
        snapshot = started(store, scenario)
        raw = encoded(stopped(snapshot))
        store.record_stopped(raw)
    with opened(scenario) as recovered:
        token = cleanup(recovered)
        value = stopped(snapshot)
        if change == "cid":
            value["Id"] = "a" * 64
        elif change == "lifetime":
            value["State"]["StartedAt"] = "2026-10-21T21:00:00.123456788Z"
        else:
            value = running(snapshot)
        with pytest.raises(ValueError):
            recovered.reconfirm_stopped(token, encoded(value))
        assert (root / snapshot.probe_id / "stopped.bin").read_bytes() == raw


def test_copied_signal_claim_burns_dispatch_without_permitting_a_retry(scenario):
    with opened(scenario) as store:
        snapshot = started(store, scenario)
        token = cleanup(store)
        fence = store.prepare_signal(token, "TERM")
        with pytest.raises(ValueError):
            store.claim_signal(replace(fence), encoded(running(snapshot)))
        with pytest.raises(ValueError):
            store.claim_signal(fence, encoded(running(snapshot)))
