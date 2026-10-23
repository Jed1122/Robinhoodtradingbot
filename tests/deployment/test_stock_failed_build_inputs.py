"""Synthetic supplied bytes; no files, Engine, process or write authority."""

import copy
import hashlib
import json
import os
import socket
import stat
import subprocess
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from test_stock_build_inputs import archive
from test_stock_container import engine

from infra.hybrid import stock_failed_build_inputs as codec
from infra.hybrid.stock_build_engine import _source_request
from infra.hybrid.stock_build_inputs import inspect_source

BOOT = "11111111-1111-1111-1111-111111111111"
IMAGE = "sha256:" + "b" * 64
NAMESPACE = "a" * 32
ERROR = "stock_failed_build_inputs_unavailable"
SERVICE_SHA = "2e35580df3c26dc898440289f4abad013fbd62722f00c93f994dba002e468873"
SOCKET_SHA = "96c04477e86bd6f724560f3a78b7c0b00b539d5254a251d247641029fc7ad92e"
BINARY_SHA = "237b0603cc24496c74433aeb32d70a16931ae7e015f183b8f3c7c7db83c72a5f"


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def clock(second):
    return {"boot_id": BOOT, "monotonic_ns": second * 1_000_000_000,
            "utc": f"2026-10-23T00:00:{second:02d}+00:00"}


def fixture(monkeypatch):
    """Only private compiled profile constants are replaced for synthetic bytes."""
    source = archive()
    source_sha = digest(source)
    parsed = inspect_source(source, expected_sha256=source_sha)
    namespace = {
        "schema_version": 1, "kind": "stock_producer_namespace", "namespace_id": NAMESPACE,
        "root_device": 1, "root_inode": 10, "lock_device": 1, "lock_inode": 21,
    }
    version = canonical({**engine(), "Version": "29.1.3",
                         "GitCommit": "29.1.3-0ubuntu3~24.04.2"})
    preparation = canonical({
        "schema_version": 1, "kind": "stock_source_preparation", "namespace_id": NAMESPACE,
        "source_sha256": source_sha, "commit": parsed.commit, "source_copy_sha256": source_sha,
        "started_clock": clock(11), "completed_clock": clock(12),
    })
    request = _source_request(parsed)
    dispatch = canonical({
        "schema_version": 1, "kind": "stock_build_dispatch", "namespace_id": NAMESPACE,
        "source_sha256": source_sha, "source_copy_sha256": source_sha,
        "source_preparation_sha256": digest(preparation), "engine_sha256": digest(version),
        "request_sha256": digest(request), "origin": clock(10), "dispatch_clock": clock(13),
        "build_deadline_ns": 912_000_000_000, "producer_deadline_ns": 1_210_000_000_000,
    })
    body = json.dumps({"stream": IMAGE + "\n"}, separators=(",", ":")).encode() + b"\r\n"
    response = (b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                + str(len(body)).encode() + b"\r\n\r\n" + body)
    original = {"source.tar": source, "source-preparation.json": preparation,
                "engine.bin": version, "build-request.http": request,
                "dispatch.json": dispatch, "build-response.http": response}
    monkeypatch.setattr(codec, "_SOURCE_COMMIT", parsed.commit)
    monkeypatch.setattr(codec, "_SOURCE_SHA256", source_sha)
    monkeypatch.setattr(codec, "_ENGINE_SHA256", digest(version))
    directories = {"producer": [1, 10], "inputs": [1, 11], "attempts": [1, 12],
                   "attempt": [1, 13], "release_root": [1, 14]}
    raws = {"namespace.json": canonical(namespace), "producer.lock": b"",
            "inputs/" + source_sha + ".tar": source,
            **{"attempt/" + name: raw for name, raw in original.items()}}
    files = {
        name: {"sha256": digest(raw), "fingerprint": [1, 20 + index, stat.S_IFREG | 0o600,
                                                    0, 0, 1, len(raw), 1, 1]}
        for index, (name, raw) in enumerate(raws.items())
    }
    observation = {
        "reconciler_origin": clock(20), "reconciler_deadline_ns": 140_000_000_000,
        "reconciled_clock": clock(22),
        "daemon_profile": {
            "profile_id": "ubuntu-docker-legacy-q-29.1.3-v1", "binary_sha256": BINARY_SHA,
            "binary_bytes": 83879288, "peer_pid": 1, "daemon_pid": 950,
            "daemon_start_boottime_upper_ns": 9_000_000_000,
            "socket_activation": {
                "mode": "systemd_socket_activation", "service_unit_sha256": SERVICE_SHA,
                "socket_unit_sha256": SOCKET_SHA, "listener_inode": 900,
                "socket_file_fingerprint": [1, 901, stat.S_IFSOCK | 0o660, 0, 999, 1, 0, 1, 1],
            },
            "boot_id": BOOT, "observed_clock": clock(21),
            "source_profile_id": "stock-producer-causal-479-v1",
            "source_tree": "98257c8083cc6395fde92c600b1683b783952955",
            "docker_root": "/var/lib/docker",
        },
        "capacity": {
            name: {"path": path, "device": 1, "inode": inode,
                   "available_bytes": 5 * 1024**3, "available_inodes": 4096}
            for name, path, inode in (
                ("producer", "/var/lib/hybrid-stock-producer", 10),
                ("release_root", "/opt/hybrid-stock-research/releases", 14),
                ("docker", "/var/lib/docker", 15),
            )
        },
    }
    return {"source_sha256": source_sha, "namespace_raw": canonical(namespace),
            "input_raw": source, "original": original, "directories": directories,
            "files": files, "observation": observation}


@pytest.fixture
def sample(monkeypatch):
    return fixture(monkeypatch)


def inspect(sample):
    return codec.inspect_failed_build(
        sample["source_sha256"], sample["namespace_raw"], sample["input_raw"], sample["original"]
    )


def encode(sample, evidence=None):
    return codec.encode_failed_facts(
        inspect(sample) if evidence is None else evidence, observation=sample["observation"],
        directories=sample["directories"], files=sample["files"],
    )


def validate(raw, sample, evidence=None):
    return codec.validate_failed_facts(
        raw, inspect(sample) if evidence is None else evidence,
        directories=sample["directories"], files=sample["files"],
    )


def test_complete_six_file_evidence_derives_identity_and_clocks(sample):
    evidence = inspect(sample)
    assert evidence is not None, "Complete six-file negative evidence must be decoded"
    assert evidence.source_sha256 == sample["source_sha256"]
    assert evidence.source_commit == "a" * 40 and evidence.image_digest == IMAGE
    assert evidence.namespace_id == NAMESPACE
    assert evidence.original_origin == clock(10)
    assert evidence.original_dispatch_clock == clock(13)
    assert evidence.preparation_started_clock == clock(11)
    assert evidence.preparation_completed_clock == clock(12)
    assert evidence.original_hashes == {name: digest(raw)
                                        for name, raw in sample["original"].items()}
    assert IMAGE not in repr(evidence)
    with pytest.raises(FrozenInstanceError):
        evidence.image_digest = "sha256:" + "e" * 64
    evidence.original_origin["monotonic_ns"] = 1
    evidence.original_hashes["engine.bin"] = "e" * 64
    assert evidence.original_origin == clock(10)
    assert evidence.original_hashes["engine.bin"] == digest(sample["original"]["engine.bin"])


def test_canonical_facts_round_trip_has_only_negative_claims(sample):
    raw = encode(sample)
    assert raw, "Negative facts must be encoded"
    facts = validate(raw, sample)
    assert canonical(facts) == raw and len(raw) <= 16384
    assert facts["kind"] == "stock_failed_build_terminal_facts"
    assert facts["schema_version"] == 1 and type(facts["schema_version"]) is int
    assert facts["backend_terminal"] is True
    for name in ("producer_success", "release_qualified", "cleanup_qualified",
                 "source_replay_permitted"):
        assert facts[name] is False
    assert not {"native_complete", "manifest", "eligible"}.intersection(facts)
    assert facts["files"] == sample["files"] and facts["directories"] == sample["directories"]


def test_missing_original_and_false_positive_claims_deny(sample):
    bad = copy.deepcopy(sample)
    del bad["original"]["engine.bin"]
    with pytest.raises(ValueError, match=ERROR):
        inspect(bad)
    facts = json.loads(encode(sample))
    facts["producer_success"] = True
    with pytest.raises(ValueError, match=ERROR):
        validate(canonical(facts), sample)


def update_document(sample, name, field, value):
    document = json.loads(sample["original"][name])
    if value is ...:
        del document[field]
    else:
        document[field] = value
    sample["original"][name] = canonical(document)
    if name == "source-preparation.json":
        update_document(sample, "dispatch.json", "source_preparation_sha256",
                        digest(sample["original"][name]))


def set_path(value, path, replacement):
    parts = path.split(".")
    for key in parts[:-1]:
        value = value[int(key)] if isinstance(value, list) else value[key]
    key = int(parts[-1]) if isinstance(value, list) else parts[-1]
    if replacement is ...:
        del value[key]
    else:
        value[key] = replacement


def test_compiled_original_profile_is_exact_and_has_no_public_override():
    assert codec._SOURCE_COMMIT == "479fca6ce789692d2a088b162fe6bcfeb2ad8336"
    assert codec._SOURCE_TREE == "98257c8083cc6395fde92c600b1683b783952955"
    assert codec._SOURCE_SHA256 == (
        "a54a71ab93bbddb9b098678ba4fe638c12faefc0157ddc7cc3a7f7d1e120b674"
    )
    assert codec._ENGINE_SHA256 == (
        "657cc3c9b56b63ae49d7e175d83afa6eabdb68637ad552e26e015f43f0733d3a"
    )
    assert codec._OWNER_UID == codec._OWNER_GID == 0


@pytest.mark.parametrize("name", ["source.tar", "source-preparation.json", "engine.bin",
                                  "build-request.http", "dispatch.json", "build-response.http"])
@pytest.mark.parametrize("mutation", ["missing", "empty", "bytearray", "oversized"])
def test_six_exact_nonempty_bounded_bytes(sample, name, mutation):
    if mutation == "missing":
        del sample["original"][name]
    elif mutation == "empty":
        sample["original"][name] = b""
    elif mutation == "bytearray":
        sample["original"][name] = bytearray(sample["original"][name])
    else:
        sample["original"][name] = bytes(codec._ORIGINAL_LIMITS[name] + 1)
    with pytest.raises(ValueError, match=ERROR):
        inspect(sample)


@pytest.mark.parametrize("name", ["image.bin", "build-complete.json", "probe-intent.json",
                                  "terminal.json", "failed-build-terminal.json", "other"])
def test_no_extra_original_stage_or_terminal(sample, name):
    sample["original"][name] = b"{}\n"
    with pytest.raises(ValueError, match=ERROR):
        inspect(sample)


@pytest.mark.parametrize("field,value", [
    ("source_sha256", None), ("source_sha256", True), ("source_sha256", "A" * 64),
    ("source_sha256", "e" * 64), ("source_sha256", "a" * 63),
    ("source_sha256", b"a" * 64), ("input_raw", None), ("input_raw", b"x"),
    ("original", []), ("original", None), ("namespace_raw", b"{}\n"),
    ("namespace_raw", bytearray(b"{}\n")), ("namespace_raw", bytes(4097)),
])
def test_exact_top_level_inputs(sample, field, value):
    sample[field] = value
    with pytest.raises(ValueError, match=ERROR):
        inspect(sample)


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", 2), ("kind", "other"),
    ("namespace_id", "A" * 32), ("namespace_id", "a" * 31), ("namespace_id", None),
    ("root_device", -1), ("root_device", True), ("root_inode", 0),
    ("root_inode", 2**63), ("lock_device", False), ("lock_inode", 0),
    ("unexpected", "secret"), ("namespace_id", ...),
])
def test_namespace_closed_types_and_bounds(sample, field, value):
    namespace = json.loads(sample["namespace_raw"])
    if value is ...:
        del namespace[field]
    else:
        namespace[field] = value
    sample["namespace_raw"] = canonical(namespace)
    with pytest.raises(ValueError, match=ERROR):
        inspect(sample)


@pytest.mark.parametrize("name", ["namespace_raw", "source-preparation.json", "dispatch.json"])
@pytest.mark.parametrize("mutation", ["spaces", "missing_lf", "duplicate", "nan", "invalid"])
def test_original_json_canonical_and_duplicate_free(sample, name, mutation):
    raw = sample[name] if name == "namespace_raw" else sample["original"][name]
    if mutation == "spaces":
        raw = json.dumps(json.loads(raw), sort_keys=True).encode() + b"\n"
    elif mutation == "missing_lf":
        raw = raw[:-1]
    elif mutation == "duplicate":
        raw = raw.replace(b'{', b'{"schema_version":1,', 1)
    elif mutation == "nan":
        raw = raw.replace(b':1,', b':NaN,', 1)
    else:
        raw = b"\xffsecret"
    if name == "namespace_raw":
        sample[name] = raw
    else:
        sample["original"][name] = raw
    with pytest.raises(ValueError, match=ERROR) as failure:
        inspect(sample)
    assert str(failure.value) == ERROR and failure.value.__suppress_context__


@pytest.mark.parametrize("name,field,value", [
    ("source-preparation.json", "schema_version", True),
    ("source-preparation.json", "commit", "f" * 40),
    ("source-preparation.json", "namespace_id", "f" * 32),
    ("source-preparation.json", "source_sha256", "f" * 64),
    ("source-preparation.json", "source_copy_sha256", "f" * 64),
    ("source-preparation.json", "kind", "stock_build_complete"),
    ("source-preparation.json", "extra", True),
    ("source-preparation.json", "completed_clock", ...),
    ("dispatch.json", "schema_version", True),
    ("dispatch.json", "namespace_id", "f" * 32),
    ("dispatch.json", "source_sha256", "f" * 64),
    ("dispatch.json", "source_copy_sha256", "f" * 64),
    ("dispatch.json", "source_preparation_sha256", "f" * 64),
    ("dispatch.json", "engine_sha256", "f" * 64),
    ("dispatch.json", "request_sha256", "f" * 64),
    ("dispatch.json", "kind", "stock_build_complete"),
    ("dispatch.json", "extra", True),
    ("dispatch.json", "producer_deadline_ns", 1_210_000_000_001),
    ("dispatch.json", "producer_deadline_ns", True),
    ("dispatch.json", "build_deadline_ns", True),
    ("dispatch.json", "build_deadline_ns", 13_000_000_000),
    ("dispatch.json", "build_deadline_ns", 913_000_000_001),
    ("dispatch.json", "build_deadline_ns", 1_210_000_000_001),
])
def test_original_semantics_and_hash_links(sample, name, field, value):
    update_document(sample, name, field, value)
    with pytest.raises(ValueError, match=ERROR):
        inspect(sample)


@pytest.mark.parametrize("name,field,value", [
    ("source-preparation.json", "started_clock", clock(9)),
    ("source-preparation.json", "completed_clock", clock(14)),
    ("dispatch.json", "dispatch_clock", clock(11)),
    ("dispatch.json", "origin", {**clock(10), "boot_id": "2" * 36}),
    ("dispatch.json", "origin", {**clock(10), "monotonic_ns": True}),
    ("dispatch.json", "origin", {**clock(10), "utc": "2026-02-30T00:00:10Z"}),
    ("dispatch.json", "origin", {**clock(10), "utc": "2026-10-23 00:00:10Z"}),
    ("dispatch.json", "origin", {**clock(10), "utc": "2026-10-23T00:00:10-01:00"}),
    ("dispatch.json", "origin", {**clock(10), "extra": True}),
    ("source-preparation.json", "started_clock", {**clock(11), "utc": clock(9)["utc"]}),
    ("source-preparation.json", "started_clock", {**clock(11), "boot_id": "2" * 36}),
])
def test_original_clocks_closed_ordered_and_same_boot(sample, name, field, value):
    update_document(sample, name, field, value)
    with pytest.raises(ValueError, match=ERROR):
        inspect(sample)


@pytest.mark.parametrize("name", ["source.tar", "engine.bin", "build-request.http"])
def test_changed_original_bytes_cannot_reuse_profile_or_hash_links(sample, name):
    sample["original"][name] += b" "
    with pytest.raises(ValueError, match=ERROR):
        inspect(sample)


def test_whole_archive_commit_pin_is_independent_of_archive_digest(sample, monkeypatch):
    monkeypatch.setattr(codec, "_SOURCE_COMMIT", "f" * 40)
    with pytest.raises(ValueError, match=ERROR):
        inspect(sample)


@pytest.mark.parametrize("key,value", [
    ("Version", "29.1.2"), ("ApiVersion", "1.53"), ("ApiVersion", "1.51"),
    ("GitCommit", "upstream"), ("Arch", "arm64"), ("Os", "darwin"),
    ("MinAPIVersion", "1.53"),
])
def test_version_policy_is_independent_of_private_fixture_hash(sample, monkeypatch, key, value):
    update_document(sample, "engine.bin", key, value)
    monkeypatch.setattr(codec, "_ENGINE_SHA256", digest(sample["original"]["engine.bin"]))
    update_document(sample, "dispatch.json", "engine_sha256",
                    digest(sample["original"]["engine.bin"]))
    with pytest.raises(ValueError, match=ERROR):
        inspect(sample)


@pytest.mark.parametrize("body", [
    b'', b'{"stream":"sha256:partial\\n"}\r\n', b'{"error":"secret"}\r\n',
    (json.dumps({"stream": IMAGE + "\n"}) + "\r\n{}\r\n").encode(),
    json.dumps({"stream": IMAGE + "\n", "aux": {}}).encode() + b"\r\n",
    json.dumps({"stream": IMAGE}).encode() + b"\r\n",
    json.dumps({"stream": IMAGE + "\n"}).encode() + b"\n",
    b'{"stream":"x","stream":"y"}\r\n',
])
def test_quiet_reply_must_be_one_complete_distinctive_terminal(body, sample):
    sample["original"]["build-response.http"] = (
        b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n" + body
    )
    with pytest.raises(ValueError, match=ERROR):
        inspect(sample)


@pytest.mark.parametrize("mutation", ["status", "length", "chunked", "encoding", "type", "cut"])
def test_quiet_http_framing_is_strict(sample, mutation):
    raw = sample["original"]["build-response.http"]
    if mutation == "status":
        raw = raw.replace(b"200 OK", b"500 ERROR")
    elif mutation == "length":
        raw = raw.replace(b"Content-Length: ", b"Content-Length: 9")
    elif mutation == "chunked":
        raw = raw.replace(b"\r\n\r\n", b"\r\nTransfer-Encoding: chunked\r\n\r\n")
    elif mutation == "encoding":
        raw = raw.replace(b"\r\n\r\n", b"\r\nContent-Encoding: gzip\r\n\r\n")
    elif mutation == "type":
        raw = raw.replace(b"application/json", b"text/plain")
    else:
        raw = raw[:-1]
    sample["original"]["build-response.http"] = raw
    with pytest.raises(ValueError, match=ERROR):
        inspect(sample)


@pytest.mark.parametrize("path,value", [
    ("unexpected", True), ("capacity", ...), ("reconciler_deadline_ns", True),
    ("reconciler_deadline_ns", 140_000_000_001), ("reconciler_origin", clock(13)),
    ("reconciler_origin.monotonic_ns", True), ("reconciler_origin.extra", True),
    ("reconciler_origin.boot_id", "22222222-2222-2222-2222-222222222222"),
    ("reconciled_clock", clock(19)),
    ("reconciled_clock.monotonic_ns", 140_000_000_000),
    ("reconciled_clock.utc", clock(19)["utc"]),
    ("daemon_profile.extra", True), ("daemon_profile.profile_id", "other"),
    ("daemon_profile.binary_sha256", "e" * 64), ("daemon_profile.binary_bytes", True),
    ("daemon_profile.binary_bytes", 83879289), ("daemon_profile.peer_pid", True),
    ("daemon_profile.peer_pid", 950), ("daemon_profile.daemon_pid", 1),
    ("daemon_profile.daemon_pid", True), ("daemon_profile.daemon_pid", 2**63),
    ("daemon_profile.daemon_start_boottime_upper_ns", 10_000_000_000),
    ("daemon_profile.daemon_start_boottime_upper_ns", 10_000_000_001),
    ("daemon_profile.daemon_start_boottime_upper_ns", True),
    ("daemon_profile.daemon_start_boottime_upper_ns", 0),
    ("daemon_profile.boot_id", "22222222-2222-2222-2222-222222222222"),
    ("daemon_profile.observed_clock", clock(19)),
    ("daemon_profile.observed_clock", clock(23)),
    ("daemon_profile.source_profile_id", "other"),
    ("daemon_profile.source_tree", "f" * 40),
    ("daemon_profile.docker_root", "/var/lib/docker/"),
    ("daemon_profile.socket_activation.mode", "direct_peer"),
    ("daemon_profile.socket_activation.service_unit_sha256", "e" * 64),
    ("daemon_profile.socket_activation.socket_unit_sha256", "e" * 64),
    ("daemon_profile.socket_activation.listener_inode", 0),
    ("daemon_profile.socket_activation.listener_inode", True),
    ("daemon_profile.socket_activation.extra", True),
    ("daemon_profile.socket_activation.socket_file_fingerprint", [1, 2]),
    ("daemon_profile.socket_activation.socket_file_fingerprint.2", stat.S_IFREG | 0o600),
    ("daemon_profile.socket_activation.socket_file_fingerprint.2", stat.S_IFSOCK | 0o666),
    ("daemon_profile.socket_activation.socket_file_fingerprint.3", 10001),
    ("daemon_profile.socket_activation.socket_file_fingerprint.5", 2),
    ("daemon_profile.socket_activation.socket_file_fingerprint.8", True),
    ("daemon_profile.socket_activation.socket_file_fingerprint.8", 2**63),
    ("capacity.extra", {}), ("capacity.producer.extra", True),
    ("capacity.producer.path", "/tmp/producer"),
    ("capacity.release_root.path", "/opt/hybrid-stock-research/releases/"),
    ("capacity.docker.path", "/var/lib/other"),
    ("capacity.producer.inode", 11), ("capacity.release_root.device", 2),
    ("capacity.docker.device", True), ("capacity.docker.inode", 0),
    ("capacity.docker.available_bytes", 5 * 1024**3 - 1),
    ("capacity.docker.available_inodes", 4095),
    ("capacity.producer.available_bytes", True),
])
def test_observation_profile_capacity_and_clocks_are_closed(sample, path, value):
    set_path(sample["observation"], path, value)
    with pytest.raises(ValueError, match=ERROR):
        encode(sample)


def test_socket_ctime_strict_pre_origin_uses_integer_nanoseconds(sample):
    update_document(sample, "dispatch.json", "origin",
                    {**clock(10), "utc": "2026-10-23T00:00:10.000000001Z"})
    dispatch = sample["original"]["dispatch.json"]
    sample["files"]["attempt/dispatch.json"]["sha256"] = digest(dispatch)
    sample["files"]["attempt/dispatch.json"]["fingerprint"][6] = len(dispatch)
    stamp = sample["observation"]["daemon_profile"]["socket_activation"]["socket_file_fingerprint"]
    origin_ns = 1_792_713_610_000_000_001
    stamp[8] = origin_ns - 1
    assert encode(sample)
    stamp[8] = origin_ns
    with pytest.raises(ValueError, match=ERROR):
        encode(sample)


@pytest.mark.parametrize("name", ["producer", "inputs", "attempts", "attempt", "release_root"])
@pytest.mark.parametrize("value", [[True, 10], [1, 0], [1, 2**63], [1], (1, 10), None])
def test_directory_identity_types_bounds_and_shape(sample, name, value):
    sample["directories"][name] = value
    with pytest.raises(ValueError, match=ERROR):
        encode(sample)


@pytest.mark.parametrize("mutation", ["extra_dir", "missing_dir", "alias_dir", "namespace_root",
                                     "extra_file", "missing_file", "extra_entry", "hash", "lock"])
def test_closed_file_directory_inventory_and_namespace_binding(sample, mutation):
    if mutation == "extra_dir":
        sample["directories"]["render"] = [1, 15]
    elif mutation == "missing_dir":
        del sample["directories"]["attempts"]
    elif mutation == "alias_dir":
        sample["directories"]["attempts"] = [1, 11]
    elif mutation == "namespace_root":
        sample["directories"]["producer"] = [1, 999]
    elif mutation == "extra_file":
        sample["files"]["image.bin"] = sample["files"]["namespace.json"]
    elif mutation == "missing_file":
        del sample["files"]["producer.lock"]
    elif mutation == "extra_entry":
        sample["files"]["namespace.json"]["extra"] = 1
    elif mutation == "hash":
        sample["files"]["namespace.json"]["sha256"] = "f" * 64
    else:
        sample["files"]["producer.lock"]["fingerprint"][1] = 999
    with pytest.raises(ValueError, match=ERROR):
        encode(sample)


@pytest.mark.parametrize("index,value", [
    (0, True), (0, 2), (1, 0), (1, 21), (1, 10),
    (2, stat.S_IFREG | 0o644), (2, stat.S_IFLNK | 0o600), (3, 10001), (4, 10001),
    (5, 2), (6, 0), (6, True), (7, -1), (8, 2**63), (8, 1.0),
])
def test_original_regular_root_private_single_link_exact_fingerprints(sample, index, value):
    sample["files"]["namespace.json"]["fingerprint"][index] = value
    with pytest.raises(ValueError, match=ERROR):
        encode(sample)


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("kind", "stock_producer_terminal"),
    ("namespace_id", "f" * 32), ("source_sha256", "f" * 64),
    ("source_commit", "f" * 40), ("image_digest", "sha256:" + "f" * 64),
    ("backend_terminal", 1), ("backend_terminal", False), ("producer_success", 0),
    ("producer_success", True), ("release_qualified", True), ("cleanup_qualified", True),
    ("source_replay_permitted", True), ("native_complete", True), ("manifest", "secret"),
    ("original_origin", clock(11)), ("original_dispatch_clock", clock(14)),
    ("original_dispatch_clock", ...), ("directories", {}), ("files", {}),
])
def test_facts_reject_positive_unknown_missing_or_changed_bindings(sample, field, value):
    facts = json.loads(encode(sample))
    if value is ...:
        del facts[field]
    else:
        facts[field] = value
    with pytest.raises(ValueError, match=ERROR):
        validate(canonical(facts), sample)


@pytest.mark.parametrize("mutation", ["spaces", "missing_lf", "duplicate", "nan", "tail",
                                     "oversized", "bytearray", "none", "list"])
def test_facts_are_one_bounded_canonical_object(sample, mutation):
    raw = encode(sample)
    if mutation == "spaces":
        raw = json.dumps(json.loads(raw), sort_keys=True).encode() + b"\n"
    elif mutation == "missing_lf":
        raw = raw[:-1]
    elif mutation == "duplicate":
        raw = raw.replace(b"{", b'{"backend_terminal":true,', 1)
    elif mutation == "nan":
        raw = raw.replace(b'"schema_version":1', b'"schema_version":NaN')
    elif mutation == "tail":
        raw += b"{}\n"
    elif mutation == "oversized":
        raw = bytes(16385)
    elif mutation == "bytearray":
        raw = bytearray(raw)
    elif mutation == "none":
        raw = None
    else:
        raw = b"[]\n"
    with pytest.raises(ValueError, match=ERROR):
        validate(raw, sample)


def test_evidence_is_reinspected_cannot_be_forged_by_dataclass_replace(sample):
    evidence = inspect(sample)
    for forged in (None, {}, replace(evidence, image_digest="sha256:" + "f" * 64),
                   replace(evidence, _origin_raw=canonical(clock(9))),
                   replace(evidence, _original_raw=evidence._original_raw[:-1])):
        with pytest.raises(ValueError, match=ERROR):
            codec.encode_failed_facts(forged, observation=sample["observation"],
                                      directories=sample["directories"], files=sample["files"])


def test_facts_have_a_finite_encoding_bound(sample, monkeypatch):
    raw = encode(sample)
    monkeypatch.setattr(codec, "_FACTS_LIMIT", len(raw) - 1)
    with pytest.raises(ValueError, match=ERROR):
        encode(sample)


def test_pure_apis_cannot_read_write_or_dispatch_and_do_not_mutate_inputs(sample, monkeypatch):
    saved = copy.deepcopy(sample)

    def forbidden(*args, **kwargs):
        raise AssertionError("Pure failed-build codec attempted I/O")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    evidence = inspect(sample)
    raw = encode(sample, evidence)
    assert validate(raw, sample, evidence)["backend_terminal"] is True
    assert sample == saved
    parsed = validate(raw, sample, evidence)
    parsed["files"]["producer.lock"]["fingerprint"][1] = 999
    assert validate(raw, sample, evidence)["files"] == saved["files"]


def test_non_native_socket_mode_bits_cannot_be_encoded(sample):
    socket_data = sample["observation"]["daemon_profile"]["socket_activation"]
    socket_data["socket_file_fingerprint"][2] |= 1 << 40
    with pytest.raises(ValueError, match=ERROR):
        encode(sample)


def test_replaced_evidence_raw_inventory_is_bounded_before_consuming(sample):
    class NotData:
        def __iter__(self):
            raise AssertionError("Non-data iterator consumed before evidence validation")

    evidence = replace(inspect(sample), _original_raw=NotData())
    with pytest.raises(ValueError, match=ERROR):
        encode(sample, evidence)


def test_disposable_file_owner_fixture_does_not_change_qualified_root_socket(sample, monkeypatch):
    monkeypatch.setattr(codec, "_OWNER_UID", 501)
    monkeypatch.setattr(codec, "_OWNER_GID", 20)
    for entry in sample["files"].values():
        entry["fingerprint"][3:5] = [501, 20]
    assert encode(sample)
    socket_data = sample["observation"]["daemon_profile"]["socket_activation"]
    socket_data["socket_file_fingerprint"][3] = 501
    with pytest.raises(ValueError, match=ERROR):
        encode(sample)
