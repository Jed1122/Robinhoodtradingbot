"""Complete fictional retained probe histories; data cannot reconstruct dispatch."""

import copy
import hashlib
import importlib
import json
import os
import tracemalloc
from dataclasses import replace

import pytest
from test_stock_container import engine, image
from test_stock_prestart import ENV, IMAGE
from test_stock_probe_profile import policy as policy_fixture
from test_stock_probe_profile import probe as probe_fixture
from test_stock_probe_records import BOOT, NOW, ZERO, encoded
from test_stock_probe_store import initialized as foundation_initialized
from test_stock_probe_store import opened

OTHER_BOOT = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
STAGES = [
    "intent",
    "create",
    "cid",
    "created",
    "start",
    "stopped",
    "output",
    "removal-intent",
    "removed",
    "closed",
]


@pytest.fixture
def initialized(tmp_path):
    return foundation_initialized.__wrapped__(tmp_path)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def put(directory, name, raw):
    path = directory / name
    path.write_bytes(raw)
    path.chmod(0o600)
    return digest(raw)


def make_probe(
    root,
    *,
    number=1,
    predecessor=None,
    stage="closed",
    cid=None,
    ending=None,
    outcome="succeeded",
    recovered=False,
    cleanup_boot=BOOT,
    late_stop=False,
    image_padding=0,
):
    api = importlib.import_module("infra.hybrid.stock_container")
    profile = importlib.import_module("infra.hybrid.stock_probe_profile")
    output = importlib.import_module("infra.hybrid.stock_probe_output")
    output_fixture = importlib.import_module("test_stock_probe_output")
    probe_id = f"{number:032x}"
    cid = cid or f"{number:064x}"
    directory = root / probe_id
    directory.mkdir(mode=0o700)
    namespace_id = json.loads((root / "namespace.json").read_bytes())["namespace_id"]
    base = NOW + number * 60000000000
    metadata = image()
    if image_padding:
        metadata["Comment"] = "x" * image_padding
    metadata["Config"]["Env"] = ENV.copy()
    engine_raw, image_raw = encoded(engine()), encoded(metadata)
    observed = api.verify_image(image_raw, IMAGE, api.verify_engine_version(engine_raw))
    request = profile.probe_request(observed, probe_id)
    artifacts, hashes, values = {}, {}, {}
    for name, raw in [
        ("engine.bin", engine_raw),
        ("image.bin", image_raw),
        ("request.bin", request),
    ]:
        put(directory, name, raw)
        artifacts[name] = raw

    def receipt(name, specific, index, *, boot=BOOT):
        value = {
            "schema_version": 1,
            "kind": "stock_probe_" + name.replace("-", "_"),
            "namespace_id": namespace_id,
            "probe_id": probe_id,
            "intent_sha256": None if name == "intent" else hashes["intent"],
            "boot_id": boot,
            "utc": "2026-10-21T21:00:00+00:00",
            "monotonic_ns": base + index * 1000000000,
            **specific,
        }
        hashes[name] = put(directory, name + ".json", encoded(value))
        values[name] = value

    def blob(prefix, raw):
        return {prefix + "_sha256": digest(raw), prefix + "_size": len(raw)}

    receipt(
        "intent",
        {
            "profile_version": 1,
            "image_digest": IMAGE,
            **blob("engine", engine_raw),
            **blob("image", image_raw),
            **blob("request", request),
            "setup_started_ns": base,
            "setup_deadline_ns": base + 20000000000,
            "predecessor_probe_id": None if predecessor is None else predecessor["probe_id"],
            "predecessor_closed_sha256": None
            if predecessor is None
            else predecessor["hashes"]["closed"],
        },
        1,
    )
    if stage == "abandoned":
        receipt(
            "closed",
            {
                "outcome": "abandoned_before_create",
                "reason": "abandoned_before_create",
                "output_sha256": None,
                "removed_sha256": None,
            },
            2,
        )
    else:
        _, created = probe_fixture.__wrapped__(policy_fixture.__wrapped__())
        created["Id"], created["Name"] = cid, "/hybrid-stock-probe-" + probe_id
        created["Config"]["Hostname"] = cid[:12]
        created["Config"]["Labels"]["org.hybrid.stock.probe"] = probe_id
        created_raw = encoded(created)
        stop_state = {
            "Status": "created" if recovered else "exited",
            "Running": False,
            "Paused": False,
            "Restarting": False,
            "OOMKilled": False,
            "Dead": False,
            "Pid": 0,
            "ExitCode": 0,
            "Error": "",
            "StartedAt": ZERO if recovered else "2026-10-21T21:00:05.123456789Z",
            "FinishedAt": ZERO if recovered else "2026-10-21T21:00:06.123456789Z",
            **(ending or {}),
        }
        stopped = copy.deepcopy(created)
        stopped["State"] = stop_state
        stopped_raw = encoded(stopped)
        framed = b"" if recovered else output_fixture.frame(output_fixture.document())
        canonical = None if recovered else output.decode_probe_output(framed)
        maximum = STAGES.index(stage)
        for name in STAGES[1 : maximum + 1]:
            if name == "create":
                receipt(
                    name,
                    {"request_sha256": digest(request), "dispatch_deadline_ns": base + 7000000000},
                    2,
                )
            elif name == "cid":
                raw = created_raw if recovered else encoded({"Id": cid, "Warnings": []})
                artifact_name = "discovery.bin" if recovered else "create-response.bin"
                put(directory, artifact_name, raw)
                artifacts[artifact_name] = raw
                receipt(
                    name,
                    {
                        "create_sha256": hashes["create"],
                        "container_id": cid,
                        "evidence_kind": "name_inspection" if recovered else "create_response",
                        **blob("observation", raw),
                    },
                    3,
                    boot=cleanup_boot if recovered else BOOT,
                )
            elif name == "created" and not recovered:
                put(directory, "prestart.bin", created_raw)
                artifacts["prestart.bin"] = created_raw
                receipt(name, {"cid_sha256": hashes["cid"], **blob("prestart", created_raw)}, 4)
            elif name == "start" and not recovered:
                receipt(
                    name,
                    {
                        "created_sha256": hashes["created"],
                        "container_id": cid,
                        "run_deadline_ns": base + 35000000000,
                    },
                    5,
                )
            elif name == "stopped":
                put(directory, "stopped.bin", stopped_raw)
                artifacts["stopped.bin"] = stopped_raw
                receipt(
                    name,
                    {
                        "container_id": cid,
                        "start_sha256": hashes.get("start"),
                        **blob("inspection", stopped_raw),
                        "status": stop_state["Status"],
                        "exit_code": stop_state["ExitCode"],
                        "oom_killed": stop_state["OOMKilled"],
                        "error_present": bool(stop_state["Error"]),
                        "container_started_at": stop_state["StartedAt"],
                        "container_finished_at": stop_state["FinishedAt"],
                    },
                    40 if late_stop else 6,
                    boot=cleanup_boot,
                )
            elif name == "output":
                put(directory, "framed-logs.bin", framed)
                artifacts["framed-logs.bin"] = framed
                if canonical is not None:
                    put(directory, "configuration.bin", canonical)
                    artifacts["configuration.bin"] = canonical
                receipt(
                    name,
                    {
                        "stopped_sha256": hashes["stopped"],
                        **blob("framed", framed),
                        "status": "invalid" if recovered else "valid",
                        "canonical_sha256": None if canonical is None else digest(canonical),
                        "canonical_size": None if canonical is None else len(canonical),
                    },
                    41 if late_stop else 7,
                    boot=cleanup_boot,
                )
            elif name == "removal-intent":
                index = 42 if late_stop else 8
                receipt(
                    name,
                    {
                        "container_id": cid,
                        "stopped_sha256": hashes["stopped"],
                        "retirement_deadline_ns": base + (index + 15) * 1000000000,
                    },
                    index,
                    boot=cleanup_boot,
                )
            elif name == "removed":
                receipt(
                    name,
                    {
                        "removal_intent_sha256": hashes["removal-intent"],
                        "evidence_kind": "delete_204",
                    },
                    43 if late_stop else 9,
                    boot=cleanup_boot,
                )
            elif name == "closed":
                receipt(
                    name,
                    {
                        "outcome": outcome,
                        "reason": "completed" if outcome == "succeeded" else "recovery",
                        "output_sha256": hashes.get("output"),
                        "removed_sha256": hashes["removed"],
                    },
                    44 if late_stop else 10,
                    boot=cleanup_boot,
                )
    head = {
        "schema_version": 1,
        "kind": "stock_probe_active",
        "namespace_id": namespace_id,
        "probe_id": probe_id,
        "intent_sha256": hashes["intent"],
    }
    put(root, "active.json", encoded(head))
    return {
        "probe_id": probe_id,
        "directory": directory,
        "hashes": hashes,
        "values": values,
        "artifacts": artifacts,
        "cid": cid,
    }


@pytest.mark.parametrize("stage", [*STAGES, "abandoned"])
def test_complete_supplied_stage_is_classified_once_without_reconstructing_authority(
    initialized, stage
):
    _, root = initialized
    data = make_probe(root, stage=stage)
    with opened(initialized) as store:
        accessor = getattr(store, "snapshot", None)
        assert callable(accessor), "The probe store has no complete lineage snapshot"
        snapshot = accessor()
        assert snapshot.probe_id == data["probe_id"]
        assert snapshot.intent_sha256 == data["hashes"]["intent"]
        assert snapshot.image_digest == IMAGE
        assert snapshot.container_id == (
            data["cid"] if stage not in ("intent", "create", "abandoned") else None
        )
        assert store.recovery_only is (stage not in ("closed", "abandoned"))
        assert dict(snapshot.receipt_hashes) == {
            name + ".json": value for name, value in data["hashes"].items()
        }
        assert replace(snapshot) == snapshot and replace(snapshot) is not snapshot
        assert not hasattr(snapshot, "create_fence") and not hasattr(snapshot, "start_fence")
    with pytest.raises(ValueError, match=r"^stock_probe_store_unavailable$"):
        accessor()


def test_empty_namespace_has_no_snapshot_and_no_recovery_target(initialized):
    with opened(initialized) as store:
        accessor = getattr(store, "snapshot", None)
        assert callable(accessor), "The probe store has no complete lineage snapshot"
        assert accessor() is None and store.recovery_only is False


def test_complete_predecessor_chain_includes_every_retained_probe(initialized):
    _, root = initialized
    predecessor = None
    for number in range(1, 5):
        predecessor = make_probe(root, number=number, predecessor=predecessor)
    with opened(initialized) as store:
        assert store.snapshot().probe_id == predecessor["probe_id"]
        assert store.recovery_only is False


@pytest.mark.parametrize(
    "mutation",
    [
        "orphan",
        "missing-head",
        "head-hash",
        "head-kind",
        "head-boolean",
        "predecessor-hash",
        "predecessor-unclosed",
        "duplicate-cid",
        "extra-temp",
        "unknown-file",
        "unknown-directory",
    ],
)
def test_noncanonical_forked_or_unretired_history_denies(initialized, mutation):
    _, root = initialized
    first = make_probe(
        root, number=1, stage="stopped" if mutation == "predecessor-unclosed" else "closed"
    )
    if mutation == "predecessor-unclosed":
        # A fabricated closed hash cannot turn an unclosed predecessor into a terminal one.
        first["hashes"]["closed"] = "e" * 64
    second = make_probe(
        root, number=2, predecessor=first, cid=first["cid"] if mutation == "duplicate-cid" else None
    )
    if mutation == "orphan":
        make_probe(root, number=3)
    elif mutation == "missing-head":
        (root / "active.json").unlink()
    elif mutation.startswith("head-"):
        path = root / "active.json"
        head = json.loads(path.read_bytes())
        head[
            {"head-hash": "intent_sha256", "head-kind": "kind", "head-boolean": "schema_version"}[
                mutation
            ]
        ] = {"head-hash": "e" * 64, "head-kind": "stock_attempt_head", "head-boolean": True}[
            mutation
        ]
        put(root, path.name, encoded(head))
    elif mutation == "predecessor-hash":
        path = second["directory"] / "intent.json"
        value = json.loads(path.read_bytes())
        value["predecessor_closed_sha256"] = "e" * 64
        put(second["directory"], path.name, encoded(value))
    elif mutation == "extra-temp":
        put(root, ".active-leftover.tmp", b"uncertain")
    elif mutation == "unknown-file":
        put(second["directory"], "unexpected", b"uncertain")
    elif mutation == "unknown-directory":
        (root / "unknown").mkdir(mode=0o700)
    with pytest.raises(ValueError, match=r"^stock_probe_store_unavailable$"), opened(initialized):
        pytest.fail("contradictory history was admitted")


@pytest.mark.parametrize(
    "name",
    [
        "engine.bin",
        "image.bin",
        "request.bin",
        "create-response.bin",
        "prestart.bin",
        "stopped.bin",
        "framed-logs.bin",
        "configuration.bin",
    ],
)
@pytest.mark.parametrize("mutation", ["changed", "missing", "mode", "link"])
def test_every_original_artifact_is_required_and_bound(initialized, tmp_path, name, mutation):
    _, root = initialized
    data = make_probe(root)
    path = data["directory"] / name
    if mutation == "changed":
        path.write_bytes(b"changed bytes")
    elif mutation == "missing":
        path.unlink()
    elif mutation == "mode":
        path.chmod(0o644)
    else:
        os.link(path, tmp_path / "link")
    with pytest.raises(ValueError), opened(initialized):
        pytest.fail("unbound artifact was admitted")


@pytest.mark.parametrize(
    "ending",
    [
        {"ExitCode": 1},
        {"OOMKilled": True},
        {"Error": "sensitive fictional error"},
        {"Status": "dead", "Dead": True},
        {
            "StartedAt": "2026-10-21T21:00:06.000000002Z",
            "FinishedAt": "2026-10-21T21:00:06.000000001Z",
        },
    ],
)
def test_consistent_failure_facts_cannot_form_successful_closed_history(initialized, ending):
    _, root = initialized
    make_probe(root, ending=ending)
    with pytest.raises(ValueError), opened(initialized):
        pytest.fail("failed execution was accepted as successful")


def test_clean_exit_observed_after_original_run_cap_is_not_success(initialized):
    _, root = initialized
    make_probe(root, late_stop=True)
    with pytest.raises(ValueError), opened(initialized):
        pytest.fail("late observation became a successful run")


def test_current_domain_recovery_closes_failure_and_never_reconstructs_success(initialized):
    _, root = initialized
    data = make_probe(root, outcome="failed", cleanup_boot=OTHER_BOOT)
    with opened(initialized) as store:
        assert store.snapshot().closed_outcome == "failed"
        assert store.snapshot().container_id == data["cid"]
        assert store.recovery_only is False


def test_name_inspection_cid_remains_valid_cleanup_data_without_start_chain(initialized):
    _, root = initialized
    make_probe(root, recovered=True, outcome="failed", cleanup_boot=OTHER_BOOT)
    with opened(initialized) as store:
        snapshot = store.snapshot()
        assert snapshot.closed_outcome == "failed" and snapshot.run_deadline_ns is None
        assert snapshot.stopped.status == "created"


def test_same_lock_history_cache_checks_changed_named_bytes(initialized):
    _, root = initialized
    data = make_probe(root)
    with opened(initialized) as store:
        assert store.snapshot().closed_outcome == "succeeded"
        (data["directory"] / "image.bin").write_bytes(b"changed")
        with pytest.raises(ValueError):
            store.snapshot()


def test_lock_and_root_path_substitution_are_detected_after_entry(initialized, tmp_path):
    _, root = initialized
    with opened(initialized) as store:
        (root / "launcher.lock").rename(root / "old.lock")
        put(root, "launcher.lock", b"")
        with pytest.raises(ValueError):
            store.snapshot()
    (root / "launcher.lock").unlink()
    (root / "old.lock").rename(root / "launcher.lock")
    with opened(initialized) as store:
        root.rename(tmp_path / "moved")
        root.mkdir(mode=0o700)
        with pytest.raises(ValueError):
            store.snapshot()


def test_new_root_inventory_during_final_validation_is_not_ignored(initialized, monkeypatch):
    _, root = initialized
    make_probe(root)
    with opened(initialized) as store:
        original = store._guard
        calls = 0

        def changed_guard():
            nonlocal calls
            original()
            calls += 1
            if calls == 2:
                put(root, "unexpected", b"late")

        monkeypatch.setattr(store, "_guard", changed_guard)
        with pytest.raises(ValueError):
            store.snapshot()


def test_new_probe_inventory_during_validation_is_not_ignored(initialized, monkeypatch):
    _, root = initialized
    data = make_probe(root)
    with opened(initialized) as store:
        store._nodes.clear()
        original = store._bind_node

        def changed_bind(*args):
            result = original(*args)
            put(data["directory"], "unexpected", b"late")
            return result

        monkeypatch.setattr(store, "_bind_node", changed_bind)
        with pytest.raises(ValueError):
            store.snapshot()


@pytest.mark.parametrize(
    "stage,missing,artifacts",
    [
        ("cid", ["create"], []),
        ("created", ["cid"], ["create-response.bin"]),
        ("start", ["created"], ["prestart.bin"]),
        ("stopped", ["cid", "created", "start"], ["create-response.bin", "prestart.bin"]),
    ],
)
def test_missing_prerequisite_receipt_never_reconstructs_a_later_stage(
    initialized, stage, missing, artifacts
):
    _, root = initialized
    data = make_probe(root, stage=stage)
    for name in [*(name + ".json" for name in missing), *artifacts]:
        (data["directory"] / name).unlink()
    if stage == "stopped":
        value = data["values"]["stopped"]
        value["start_sha256"] = None
        put(data["directory"], "stopped.json", encoded(value))
    with pytest.raises(ValueError), opened(initialized):
        pytest.fail("missing predecessor was reconstructed")


def test_capacity_is_exactly_128_retained_probes_without_automatic_pruning(initialized):
    _, root = initialized
    predecessor = None
    for number in range(1, 129):
        predecessor = make_probe(root, number=number, predecessor=predecessor, stage="abandoned")
    with opened(initialized) as store:
        assert store.snapshot().probe_id == predecessor["probe_id"]
    make_probe(root, number=129, predecessor=predecessor, stage="abandoned")
    with pytest.raises(ValueError), opened(initialized):
        pytest.fail("retention capacity silently expanded")
    assert len([path for path in root.iterdir() if path.is_dir()]) == 129


def test_validated_history_does_not_retain_all_large_original_payloads_in_memory(initialized):
    _, root = initialized
    predecessor = None
    for number in range(1, 17):
        predecessor = make_probe(
            root, number=number, predecessor=predecessor, stage="abandoned", image_padding=900000
        )
    tracemalloc.start()
    try:
        with opened(initialized) as store:
            assert store.snapshot().probe_id == predecessor["probe_id"]
            _, peak = tracemalloc.get_traced_memory()
            assert peak < 12 * 1024 * 1024, (
                "Retained history must cache validation facts, not every original payload"
            )
    finally:
        tracemalloc.stop()
