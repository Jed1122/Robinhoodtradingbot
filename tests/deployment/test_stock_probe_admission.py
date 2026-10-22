"""Actual private admission/fence code against fictional files and clocks only."""

import copy
import json
import os
from dataclasses import replace

import pytest
from test_stock_container import engine, image
from test_stock_prestart import CID, ENV, IMAGE, encoded
from test_stock_probe_history import make_probe
from test_stock_probe_profile import policy as policy_fixture
from test_stock_probe_profile import probe as probe_fixture
from test_stock_probe_records import BOOT, NOW
from test_stock_probe_store import module

OTHER_BOOT = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    api = module()
    root = tmp_path.resolve() / "probes"
    api._initialize(root, trusted_uid=os.geteuid())
    clock = {"boot_id": BOOT, "utc": "2026-10-21T21:00:00+00:00", "monotonic_ns": NOW}
    monkeypatch.setattr(api, "_clock", lambda: clock.copy(), raising=False)
    metadata = image()
    metadata["Config"]["Env"] = ENV.copy()
    return api, root, clock, encoded(engine()), encoded(metadata)


def opened(scenario):
    api, root, *_ = scenario
    return api._open_namespace(root, trusted_uid=os.geteuid())


def setup(store):
    claim = getattr(store, "begin_setup", None)
    assert callable(claim), "The probe store lacks one-use setup admission"
    return claim(IMAGE)


def admitted(store, scenario):
    token = setup(store)
    return token, store.begin(token, scenario[3], scenario[4])


def prestart(snapshot):
    _, value = probe_fixture.__wrapped__(policy_fixture.__wrapped__())
    value["Name"] = "/hybrid-stock-probe-" + snapshot.probe_id
    value["Config"]["Labels"]["org.hybrid.stock.probe"] = snapshot.probe_id
    return encoded(value)


def created(store, scenario):
    token, snapshot = admitted(store, scenario)
    fence = store.prepare_create()
    store.claim_create(fence)
    store.check_create_fence(fence)
    store.record_cid(fence, encoded({"Id": CID, "Warnings": []}))
    return token, snapshot, fence


def prepared_start(store, scenario):
    token, snapshot, create = created(store, scenario)
    observation = store.record_created(prestart(snapshot))
    assert observation.container_id == CID
    return token, snapshot, create, store.prepare_start()


def test_original_setup_origin_precedes_metadata_and_durable_admission(scenario):
    api, root, clock, engine_raw, image_raw = scenario
    with opened(scenario) as store:
        token = setup(store)
        assert (token.boot_id, token.started_ns, token.deadline_ns) == (
            BOOT,
            NOW,
            NOW + 20000000000,
        )
        assert token.image_digest == IMAGE and token.predecessor_container_id is None
        clock["monotonic_ns"] += 3000000000
        snapshot = store.begin(token, engine_raw, image_raw)
        assert snapshot.probe_id == token.probe_id and store.snapshot() == snapshot
        assert (snapshot.setup_started_ns, snapshot.setup_deadline_ns) == (NOW, NOW + 20000000000)
        directory = root / token.probe_id
        assert (directory / "engine.bin").read_bytes() == engine_raw
        assert (directory / "image.bin").read_bytes() == image_raw
        intent = json.loads((directory / "intent.json").read_bytes())
        assert intent["monotonic_ns"] == NOW + 3000000000
        assert intent["setup_started_ns"] == NOW
        assert (
            json.loads((root / "active.json").read_bytes())["intent_sha256"]
            == snapshot.intent_sha256
        )
        request = json.loads((directory / "request.bin").read_bytes())
        assert request["NetworkDisabled"] and request["HostConfig"]["NetworkMode"] == "none"
        assert request["Entrypoint"][-1] == "trading_bot.runtime.stock_research_identity"
        assert not hasattr(snapshot, "start_fence")
        with pytest.raises(ValueError):
            store.begin(token, engine_raw, image_raw)
        with pytest.raises(ValueError):
            store.begin_setup(IMAGE)
    with pytest.raises(ValueError):
        store.check_setup(token)
    with opened(scenario) as recovered:
        assert recovered.recovery_only
        with pytest.raises(ValueError):
            recovered.begin_setup(IMAGE)
    assert not hasattr(api, "enable_live")


@pytest.mark.parametrize("kind", ["copy", "replace", "other-context"])
def test_copied_setup_data_never_owns_admission(scenario, kind):
    with opened(scenario) as store:
        token = setup(store)
        supplied = copy.copy(token) if kind == "copy" else replace(token)
        assert supplied == token and supplied is not token
        with pytest.raises(ValueError):
            store.check_setup(supplied)
        if kind == "other-context":
            pass
        else:
            with pytest.raises(ValueError):
                store.begin(supplied, scenario[3], scenario[4])
            with pytest.raises(ValueError):
                store.begin(token, scenario[3], scenario[4])
    with opened(scenario) as another, pytest.raises(ValueError):
        another.check_setup(token)


@pytest.mark.parametrize("elapsed", [20000000000, 20000000001])
def test_begin_cannot_renew_original_setup_cap(scenario, elapsed):
    _, root, clock, engine_raw, image_raw = scenario
    with opened(scenario) as store:
        token = setup(store)
        clock["monotonic_ns"] = NOW + elapsed
        with pytest.raises(ValueError):
            store.begin(token, engine_raw, image_raw)
        assert set(path.name for path in root.iterdir()) == {"launcher.lock", "namespace.json"}


@pytest.mark.parametrize("operation", ["engine", "image"])
def test_invalid_supplied_metadata_cannot_produce_owned_admission(scenario, operation):
    _, root, _, engine_raw, image_raw = scenario
    with opened(scenario) as store:
        token = setup(store)
        with pytest.raises(ValueError):
            store.begin(
                token,
                b"{}" if operation == "engine" else engine_raw,
                b"{}" if operation == "image" else image_raw,
            )
        assert not (root / token.probe_id).exists()
        with pytest.raises(ValueError):
            store.begin(token, engine_raw, image_raw)


@pytest.mark.parametrize("entry", ["intent", "create", "cid", "start", "stopped", "removed"])
def test_unfinished_entry_burns_all_new_admission_before_recovery(scenario, entry):
    _, root, *_ = scenario
    make_probe(root, stage=entry)
    with opened(scenario) as store:
        assert store.recovery_only
        with pytest.raises(ValueError):
            setup(store)
        with pytest.raises(ValueError):
            store.prepare_create()
        with pytest.raises(ValueError):
            store.prepare_start()


def test_closed_cid_bytes_alone_do_not_admit_a_new_probe(scenario):
    _, root, clock, engine_raw, image_raw = scenario
    previous = make_probe(root)
    clock["monotonic_ns"] = previous["values"]["closed"]["monotonic_ns"] + 1
    with opened(scenario) as store:
        token = setup(store)
        assert token.predecessor_container_id is not None
        with pytest.raises(ValueError):
            store.begin(token, engine_raw, image_raw)


def test_closed_abandonment_can_precede_fresh_durable_probe(scenario):
    _, root, clock, *_ = scenario
    previous = make_probe(root, stage="abandoned")
    clock["monotonic_ns"] = previous["values"]["closed"]["monotonic_ns"] + 1
    with opened(scenario) as store:
        token, snapshot = admitted(store, scenario)
        assert snapshot.probe_id != previous["probe_id"]
        intent = json.loads((root / token.probe_id / "intent.json").read_bytes())
        assert intent["predecessor_probe_id"] == previous["probe_id"]
        assert intent["predecessor_closed_sha256"] == previous["hashes"]["closed"]


def test_create_fence_binds_actual_fixed_request_and_one_dispatch(scenario):
    _, root, clock, *_ = scenario
    with opened(scenario) as store:
        token, snapshot = admitted(store, scenario)
        clock["monotonic_ns"] += 1000000000
        fence = store.prepare_create()
        assert (fence.probe_id, fence.boot_id, fence.deadline_ns) == (
            token.probe_id,
            BOOT,
            NOW + 6000000000,
        )
        assert store.create_request(fence) == (root / token.probe_id / "request.bin").read_bytes()
        value = json.loads((root / token.probe_id / "create.json").read_bytes())
        assert value["dispatch_deadline_ns"] == fence.deadline_ns
        assert value["request_sha256"] == fence.request_sha256
        store.check_create_fence(fence)
        store.claim_create(fence)
        store.check_create_fence(fence)
        with pytest.raises(ValueError):
            store.claim_create(fence)
        with pytest.raises(ValueError):
            store.prepare_create()
        with pytest.raises(ValueError):
            store.record_created(prestart(snapshot))


@pytest.mark.parametrize("operation", ["create", "start"])
def test_copied_dispatch_fence_never_passes_final_wire_barrier(scenario, operation):
    with opened(scenario) as store:
        if operation == "create":
            admitted(store, scenario)
            fence = store.prepare_create()
        else:
            *_, fence = prepared_start(store, scenario)
        checker = getattr(store, "check_" + operation + "_fence")
        with pytest.raises(ValueError):
            checker(replace(fence))
        checker(fence)


def test_cid_retention_is_distinct_from_strict_prestart_acknowledgement(scenario):
    _, root, *_ = scenario
    with opened(scenario) as store:
        _, snapshot, fence = created(store, scenario)
        assert store.snapshot().container_id == CID
        assert (root / snapshot.probe_id / "create-response.bin").read_bytes() == encoded(
            {"Id": CID, "Warnings": []}
        )
        with pytest.raises(ValueError):
            store.prepare_start()
        with pytest.raises(ValueError):
            store.prepare_start()
        assert not (root / snapshot.probe_id / "start.json").exists()
        with pytest.raises(ValueError):
            store.record_cid(fence, encoded({"Id": CID, "Warnings": []}))


def test_actual_strict_prestart_acknowledgement_permits_one_original_start_fence(scenario):
    _, root, clock, *_ = scenario
    with opened(scenario) as store:
        token, snapshot, _, fence = prepared_start(store, scenario)
        assert fence.container_id == CID and fence.probe_id == snapshot.probe_id
        assert fence.started_ns == NOW and fence.run_deadline_ns == NOW + 30000000000
        assert fence.dispatch_deadline_ns == NOW + 5000000000
        receipt = json.loads((root / token.probe_id / "start.json").read_bytes())
        assert receipt["run_deadline_ns"] == NOW + 30000000000
        store.check_start_fence(fence)
        store.claim_start(fence)
        store.check_start_fence(fence)
        with pytest.raises(ValueError):
            store.claim_start(fence)
        with pytest.raises(ValueError):
            store.prepare_start()
        clock["monotonic_ns"] += 6000000000
        with pytest.raises(ValueError):
            store.check_start_fence(fence)
        assert store.snapshot().run_deadline_ns == NOW + 30000000000
    with opened(scenario) as recovered:
        assert recovered.recovery_only
        assert recovered.snapshot().run_deadline_ns == NOW + 30000000000
        with pytest.raises(ValueError):
            recovered.check_start_fence(fence)
        with pytest.raises(ValueError):
            recovered.prepare_start()


@pytest.mark.parametrize("change", ["boot", "monotonic", "utc"])
def test_clock_discontinuity_burns_normal_fences_without_renewal(scenario, change):
    _, _, clock, *_ = scenario
    with opened(scenario) as store:
        *_, fence = prepared_start(store, scenario)
        clock["monotonic_ns"] += 1000000000
        store.check_start_fence(fence)
        if change == "boot":
            clock["boot_id"] = OTHER_BOOT
        elif change == "monotonic":
            clock["monotonic_ns"] -= 1
        else:
            clock["utc"] = "2026-10-21T20:59:59+00:00"
        with pytest.raises(ValueError):
            store.check_start_fence(fence)
        assert store.recovery_only
        assert store.snapshot().run_deadline_ns == NOW + 30000000000


@pytest.mark.parametrize(
    "stage",
    [
        "engine.bin",
        "image.bin",
        "request.bin",
        "intent.json",
        "head-replace",
        "head-directory-sync",
    ],
)
def test_begin_write_crash_window_never_creates_dispatch_authority(scenario, monkeypatch, stage):
    api, root, _, engine_raw, image_raw = scenario
    with opened(scenario) as store:
        token = setup(store)
        real_bytes, real_metadata, real_replace, real_sync = (
            api._write_bytes,
            api._write_new,
            api.os.replace,
            api.os.fsync,
        )
        if stage.endswith(".bin"):

            def fail_bytes(directory, name, raw, uid):
                result = real_bytes(directory, name, raw, uid)
                if name == stage:
                    raise OSError("sensitive fictional failure")
                return result

            monkeypatch.setattr(api, "_write_bytes", fail_bytes)
        elif stage == "intent.json":

            def fail_metadata(directory, name, value, uid):
                result = real_metadata(directory, name, value, uid)
                if name == stage:
                    raise OSError("sensitive fictional failure")
                return result

            monkeypatch.setattr(api, "_write_new", fail_metadata)
        else:
            renamed = False

            def fail_replace(*args, **kwargs):
                nonlocal renamed
                result = real_replace(*args, **kwargs)
                renamed = True
                if stage == "head-replace":
                    raise OSError("sensitive fictional failure")
                return result

            def fail_sync(fd):
                if renamed and stage == "head-directory-sync":
                    raise OSError("sensitive fictional failure")
                return real_sync(fd)

            monkeypatch.setattr(api.os, "replace", fail_replace)
            monkeypatch.setattr(api.os, "fsync", fail_sync)
        with pytest.raises(ValueError, match=r"^stock_probe_store_unavailable$"):
            store.begin(token, engine_raw, image_raw)
        with pytest.raises(ValueError):
            store.prepare_create()
        assert not (root / token.probe_id / "create.json").exists()


@pytest.mark.parametrize("operation", ["create", "created", "start"])
def test_complete_receipt_after_failed_acknowledgement_never_issues_or_adopts_token(
    scenario, monkeypatch, operation
):
    api, root, _, *_ = scenario
    with opened(scenario) as store:
        if operation == "create":
            _, snapshot = admitted(store, scenario)
        else:
            _, snapshot, _ = created(store, scenario)
            if operation == "start":
                store.record_created(prestart(snapshot))
        original = api._write_new

        def fail_after_write(directory, name, value, uid):
            result = original(directory, name, value, uid)
            if name == operation + ".json":
                raise OSError("sensitive fictional acknowledgement failure")
            return result

        monkeypatch.setattr(api, "_write_new", fail_after_write)
        call = (
            (lambda: store.record_created(prestart(snapshot)))
            if operation == "created"
            else getattr(store, "prepare_" + operation)
        )
        with pytest.raises(ValueError, match=r"^stock_probe_store_unavailable$"):
            call()
        assert (root / snapshot.probe_id / (operation + ".json")).is_file()
        with pytest.raises(ValueError):
            call()
    with opened(scenario) as recovered:
        assert recovered.recovery_only
        with pytest.raises(ValueError):
            recovered.prepare_start()


@pytest.mark.parametrize("operation", ["create", "created", "start"])
def test_post_write_setup_expiry_never_becomes_a_fresh_dispatch_window(
    scenario, monkeypatch, operation
):
    api, root, clock, *_ = scenario
    with opened(scenario) as store:
        if operation == "create":
            _, snapshot = admitted(store, scenario)
        else:
            _, snapshot, _ = created(store, scenario)
            if operation == "start":
                store.record_created(prestart(snapshot))
        original = api._write_new

        def delayed_write(directory, name, value, uid):
            result = original(directory, name, value, uid)
            if name == operation + ".json":
                clock["monotonic_ns"] = NOW + 20000000000
            return result

        monkeypatch.setattr(api, "_write_new", delayed_write)
        call = (
            (lambda: store.record_created(prestart(snapshot)))
            if operation == "created"
            else getattr(store, "prepare_" + operation)
        )
        with pytest.raises(ValueError):
            call()
        value = json.loads((root / snapshot.probe_id / (operation + ".json")).read_bytes())
        assert value["monotonic_ns"] == NOW
        if operation == "start":
            assert value["run_deadline_ns"] == NOW + 30000000000
        with pytest.raises(ValueError):
            store.prepare_start()


@pytest.mark.parametrize("operation", ["create", "start"])
@pytest.mark.parametrize("elapsed", [5000000000, 5000000001])
def test_late_fence_acknowledgement_uses_original_five_second_cap(
    scenario, monkeypatch, operation, elapsed
):
    api, root, clock, *_ = scenario
    with opened(scenario) as store:
        if operation == "create":
            _, snapshot = admitted(store, scenario)
        else:
            _, snapshot, _ = created(store, scenario)
            store.record_created(prestart(snapshot))
        original = api._write_new

        def delayed(directory, name, value, uid):
            result = original(directory, name, value, uid)
            if name == operation + ".json":
                clock["monotonic_ns"] = NOW + elapsed
            return result

        monkeypatch.setattr(api, "_write_new", delayed)
        with pytest.raises(ValueError):
            getattr(store, "prepare_" + operation)()
        value = json.loads((root / snapshot.probe_id / (operation + ".json")).read_bytes())
        assert value["monotonic_ns"] == NOW
        if operation == "start":
            assert value["run_deadline_ns"] == NOW + 30000000000
        with pytest.raises(ValueError):
            getattr(store, "prepare_" + operation)()


@pytest.mark.parametrize("operation", ["create", "start"])
def test_dispatch_window_is_shortened_by_nearby_setup_expiry(scenario, operation):
    _, _, clock, *_ = scenario
    with opened(scenario) as store:
        if operation == "create":
            admitted(store, scenario)
        else:
            _, snapshot, _ = created(store, scenario)
            store.record_created(prestart(snapshot))
        clock["monotonic_ns"] = NOW + 19000000000
        fence = getattr(store, "prepare_" + operation)()
        deadline = fence.deadline_ns if operation == "create" else fence.dispatch_deadline_ns
        assert deadline == NOW + 20000000000
        if operation == "start":
            assert fence.run_deadline_ns == NOW + 49000000000
        clock["monotonic_ns"] += 1000000000
        with pytest.raises(ValueError):
            getattr(store, "claim_" + operation)(fence)


def test_cid_may_be_retained_after_setup_expiry_but_cannot_authorize_start(scenario):
    _, root, clock, *_ = scenario
    with opened(scenario) as store:
        _, snapshot = admitted(store, scenario)
        fence = store.prepare_create()
        store.claim_create(fence)
        clock["monotonic_ns"] = NOW + 21000000000
        assert store.record_cid(fence, encoded({"Id": CID, "Warnings": None})) == CID
        assert store.snapshot().container_id == CID
        with pytest.raises(ValueError):
            store.record_created(prestart(snapshot))
        with pytest.raises(ValueError):
            store.prepare_start()
        assert not (root / snapshot.probe_id / "start.json").exists()


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{",
        b"{}",
        encoded({"Id": CID, "Warnings": ["unexpected"]}),
        encoded({"Id": CID[:12], "Warnings": []}),
    ],
    ids=["empty", "partial", "missing", "warning", "abbreviated"],
)
def test_invalid_complete_create_response_never_acknowledges_a_cid(scenario, raw):
    _, root, *_ = scenario
    with opened(scenario) as store:
        _, snapshot = admitted(store, scenario)
        fence = store.prepare_create()
        store.claim_create(fence)
        with pytest.raises(ValueError):
            store.record_cid(fence, raw)
        assert not (root / snapshot.probe_id / "cid.json").exists()
        assert not (root / snapshot.probe_id / "create-response.bin").exists()
        with pytest.raises(ValueError):
            store.record_cid(fence, encoded({"Id": CID, "Warnings": []}))


@pytest.mark.parametrize("copied", [False, True])
def test_no_cid_can_be_acknowledged_without_the_actual_claimed_create(scenario, copied):
    _, root, *_ = scenario
    with opened(scenario) as store:
        _, snapshot = admitted(store, scenario)
        fence = store.prepare_create()
        if copied:
            store.claim_create(fence)
        with pytest.raises(ValueError):
            store.record_cid(
                replace(fence) if copied else fence, encoded({"Id": CID, "Warnings": []})
            )
        assert not (root / snapshot.probe_id / "cid.json").exists()


@pytest.mark.parametrize(
    "path,value",
    [
        (("HostConfig", "ReadonlyRootfs"), False),
        (("HostConfig", "NetworkMode"), "bridge"),
        (("Config", "User"), "0:0"),
        (("Config", "NetworkDisabled"), False),
        (("State", "Running"), True),
    ],
)
def test_prestart_drift_preserves_cid_but_never_acknowledges_created(scenario, path, value):
    _, root, *_ = scenario
    with opened(scenario) as store:
        _, snapshot, _ = created(store, scenario)
        record = json.loads(prestart(snapshot))
        record[path[0]][path[1]] = value
        with pytest.raises(ValueError):
            store.record_created(encoded(record))
        assert store.snapshot().container_id == CID
        assert not (root / snapshot.probe_id / "created.json").exists()
        with pytest.raises(ValueError):
            store.prepare_start()


@pytest.mark.parametrize("invalid", [None, True, "", "tag:latest", "sha256:" + "A" * 64])
def test_invalid_image_claim_is_burned_without_files(scenario, invalid):
    _, root, *_ = scenario
    with opened(scenario) as store:
        with pytest.raises(ValueError):
            store.begin_setup(invalid)
        with pytest.raises(ValueError):
            store.begin_setup(IMAGE)
    assert set(path.name for path in root.iterdir()) == {"namespace.json", "launcher.lock"}


@pytest.mark.parametrize(
    "field,value",
    [
        ("boot_id", "invalid"),
        ("monotonic_ns", True),
        ("monotonic_ns", 0),
        ("utc", "2026-10-21"),
        ("utc", "2026-10-21T21:00:00+0000"),
    ],
)
def test_invalid_native_clock_cannot_claim_setup(scenario, field, value):
    _, _, clock, *_ = scenario
    clock[field] = value
    with opened(scenario) as store, pytest.raises(ValueError):
        setup(store)


def test_nanosecond_utc_rollback_is_not_hidden_by_datetime_truncation(scenario):
    _, _, clock, *_ = scenario
    clock["utc"] = "2026-10-21T21:00:00.123456789Z"
    with opened(scenario) as store:
        token = setup(store)
        clock["monotonic_ns"] += 1
        clock["utc"] = "2026-10-21T21:00:00.123456788Z"
        with pytest.raises(ValueError):
            store.check_setup(token)
        assert store.recovery_only


@pytest.mark.parametrize("operation", ["create", "start"])
@pytest.mark.parametrize("name", ["request.bin", "intent.json"])
def test_changed_named_source_after_fence_acknowledgement_denies_wire_check(
    scenario, operation, name
):
    _, root, *_ = scenario
    with opened(scenario) as store:
        if operation == "create":
            _, snapshot = admitted(store, scenario)
            fence = store.prepare_create()
        else:
            _, snapshot, _, fence = prepared_start(store, scenario)
        (root / snapshot.probe_id / name).write_bytes(b"changed")
        with pytest.raises(ValueError):
            getattr(store, "check_" + operation + "_fence")(fence)


def test_expired_begin_acknowledgement_cannot_be_adopted_from_complete_head(scenario, monkeypatch):
    api, root, clock, engine_raw, image_raw = scenario
    with opened(scenario) as store:
        token = setup(store)
        original = api.os.replace

        def delayed_replace(*args, **kwargs):
            result = original(*args, **kwargs)
            clock["monotonic_ns"] = NOW + 20000000000
            return result

        monkeypatch.setattr(api.os, "replace", delayed_replace)
        with pytest.raises(ValueError):
            store.begin(token, engine_raw, image_raw)
        assert (root / "active.json").is_file()
        with pytest.raises(ValueError):
            store.prepare_create()
    with opened(scenario) as recovered:
        assert recovered.recovery_only
        with pytest.raises(ValueError):
            recovered.prepare_create()


def test_fresh_entry_durability_failure_is_not_replaced_by_cached_validity(scenario, monkeypatch):
    api, root, clock, *_ = scenario
    prior = make_probe(root, stage="abandoned")
    clock["monotonic_ns"] = prior["values"]["closed"]["monotonic_ns"] + 1
    with opened(scenario) as store:
        token = setup(store)
        original = api._reconfirm_bytes

        def fail_reconfirmation(*_):
            raise OSError("sensitive fictional fsync failure")

        monkeypatch.setattr(api, "_reconfirm_bytes", fail_reconfirmation)
        with pytest.raises(ValueError):
            store.begin(token, scenario[3], scenario[4])
        monkeypatch.setattr(api, "_reconfirm_bytes", original)
        assert not (root / token.probe_id).exists()
        with pytest.raises(ValueError):
            store.begin(token, scenario[3], scenario[4])


@pytest.mark.parametrize("change", ["monotonic", "utc"])
def test_same_boot_reopened_closed_entry_cannot_hide_clock_rollback(scenario, change):
    _, root, clock, *_ = scenario
    prior = make_probe(root, stage="abandoned")
    clock["monotonic_ns"] = prior["values"]["closed"]["monotonic_ns"] + 1
    if change == "monotonic":
        clock["monotonic_ns"] -= 2
    else:
        clock["utc"] = "2026-10-21T20:59:59+00:00"
    with opened(scenario) as store:
        with pytest.raises(ValueError):
            setup(store)
        assert store.recovery_only
        assert store.snapshot().probe_id == prior["probe_id"]
