"""Root release verification with entirely fictional private immutable artifacts."""

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "sha256:" + "b" * 64
CONFIG = "c" * 64
RELEASE = "d" * 64


def module():
    source = ROOT / "infra/hybrid/stock_release.py"
    assert source.is_file(), "Read-only stock release verifier is not implemented"
    spec = importlib.util.spec_from_file_location("stock_release_fixture", source)
    assert spec and spec.loader
    result = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def write(path, value):
    if path.exists():
        path.chmod(0o600)
    path.write_bytes(encoded(value))
    path.chmod(0o444)


@pytest.fixture
def release(tmp_path):
    root = tmp_path.resolve() / "releases"
    root.mkdir(mode=0o700)
    directory = root / RELEASE
    directory.mkdir(mode=0o700)
    attestation = directory / "runtime-image-attestation.json"
    model = yaml.safe_load((ROOT / "compose.stock-research.yml").read_text())

    def expand(value):
        if isinstance(value, dict):
            return {key: expand(item) for key, item in value.items()}
        if isinstance(value, list):
            return [expand(item) for item in value]
        if isinstance(value, str) and value.startswith("${STOCK_IMAGE:"):
            return IMAGE
        if isinstance(value, str) and value.startswith("${STOCK_ATTESTATION_FILE:"):
            return str(attestation)
        return value

    model = expand(model)
    worker = model["services"]["stock-research"]
    worker["mem_limit"] = worker["memswap_limit"] = "536870912"
    observation = {
        "status": "succeeded",
        "schema_version": 1,
        "kind": "stock_research_configuration_identity",
        "config_hash": CONFIG,
        "scan_interval_seconds": 3600,
        "max_run_seconds": 450,
        "max_daily_calls": 512,
        "max_calls_per_cycle": 32,
        "maximum_source_age_seconds": 7200,
        "live_enabled": False,
    }
    manifest = {
        "schema_version": 1,
        "kind": "stock_research_release",
        "release_id": RELEASE,
        "image_digest": IMAGE,
        "config_hash": CONFIG,
        "compose_sha256": "",
        "configuration_observation_sha256": "",
        "max_run_seconds": 450,
        "scan_interval_seconds": 3600,
    }

    def publish():
        manifest["compose_sha256"] = hashlib.sha256(encoded(model)).hexdigest()
        manifest["configuration_observation_sha256"] = hashlib.sha256(
            encoded(observation)
        ).hexdigest()
        write(directory / "stock-compose.resolved.json", model)
        write(directory / "stock-configuration.json", observation)
        write(
            attestation,
            {
                "schema_version": 1,
                "image_digest": manifest["image_digest"],
                "deployment_config_hash": manifest["config_hash"],
                "compose_sha256": manifest["compose_sha256"],
                "release_key": "-".join(
                    [
                        manifest["image_digest"][7:],
                        manifest["config_hash"],
                        manifest["compose_sha256"],
                    ]
                ),
            },
        )
        write(directory / "manifest.json", manifest)

    publish()
    return root, directory, model, observation, manifest, publish


def load(release):
    root, directory, *_ = release
    return module()._load_release(
        directory / "manifest.json", trusted_uid=os.geteuid(), release_root=root
    )


def test_verified_release_binds_the_complete_policy_and_observed_limits(release):
    result = load(release)
    assert result.release_id == RELEASE and result.image_digest == IMAGE
    assert result.config_hash == CONFIG
    assert result.max_run_seconds == 450 and result.scan_interval_seconds == 3600
    assert result.compose_sha256 == release[4]["compose_sha256"]
    assert result.attestation_path == release[1] / "runtime-image-attestation.json"


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_run_seconds", True),
        ("max_run_seconds", 451),
        ("scan_interval_seconds", 3601),
        ("scan_interval_seconds", 60),
        ("schema_version", True),
        ("release_id", "e" * 64),
    ],
)
def test_manifest_rejects_wrong_types_bounds_or_path_identity(release, field, value):
    release[4][field] = value
    release[5]()
    with pytest.raises(ValueError, match="stock_release_unavailable"):
        load(release)


@pytest.mark.parametrize(
    "mutation",
    [
        "writable_root",
        "host_network",
        "extra_mount",
        "ro_control",
        "bool_pid",
        "extra_env",
        "extra_service",
        "changed_command",
        "changed_image",
    ],
)
def test_even_rehashed_unapproved_runtime_policy_is_denied(release, mutation):
    model = release[2]
    worker = model["services"]["stock-research"]
    if mutation == "writable_root":
        worker["read_only"] = False
    elif mutation == "host_network":
        worker["network_mode"] = "host"
    elif mutation == "extra_mount":
        worker["volumes"].append(
            {"source": "/var/run/docker.sock", "target": "/socket", "type": "bind"}
        )
    elif mutation == "ro_control":
        worker["volumes"][2]["read_only"] = True
    elif mutation == "bool_pid":
        worker["pids_limit"] = True
    elif mutation == "extra_env":
        worker["environment"]["HTTPS_PROXY"] = "fictional-invalid-proxy"
    elif mutation == "extra_service":
        model["services"]["unexpected"] = copy.deepcopy(worker)
    elif mutation == "changed_command":
        worker["command"].append("--export-only")
    else:
        worker["image"] = "sha256:" + "e" * 64
    release[5]()  # Identity hashes alone must not bless a changed policy.
    with pytest.raises(ValueError, match="stock_release_unavailable"):
        load(release)


@pytest.mark.parametrize(
    "field,value",
    [
        ("live_enabled", True),
        ("max_run_seconds", 449),
        ("max_calls_per_cycle", 33),
        ("max_daily_calls", True),
        ("config_hash", "e" * 64),
        ("schema_version", True),
    ],
)
def test_observation_requires_closed_types_and_matches_manifest(release, field, value):
    release[3][field] = value
    release[5]()
    with pytest.raises(ValueError, match="stock_release_unavailable"):
        load(release)


@pytest.mark.parametrize(
    "name",
    [
        "manifest.json",
        "stock-compose.resolved.json",
        "stock-configuration.json",
        "runtime-image-attestation.json",
    ],
)
@pytest.mark.parametrize("unsafe", ["writable", "symlink", "hardlink", "noncanonical", "tampered"])
def test_each_release_artifact_is_private_immutable_canonical_and_bound(release, name, unsafe):
    path = release[1] / name
    original = path.read_bytes()
    if unsafe == "writable":
        path.chmod(0o644)
    elif unsafe == "symlink":
        preserved = path.with_name("preserved-" + name)
        path.rename(preserved)
        path.symlink_to(preserved)
    elif unsafe == "hardlink":
        os.link(path, path.with_name("preserved-" + name))
    else:
        path.chmod(0o600)
        path.write_bytes(original + (b" " if unsafe == "noncanonical" else b"invalid"))
        path.chmod(0o444)
    with pytest.raises(ValueError, match="stock_release_unavailable"):
        load(release)


def test_public_loader_cannot_select_a_different_release_root(release):
    with pytest.raises(ValueError, match="stock_release_unavailable"):
        module().load_release(release[1] / "manifest.json")


def test_loading_does_not_mutate_files_and_rejects_missing_companions(release):
    directory = release[1]
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    load(release)
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}
    (directory / "stock-configuration.json").unlink()
    with pytest.raises(ValueError, match="stock_release_unavailable"):
        load(release)
    assert not (directory / "stock-configuration.json").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("read_only", 1),
        ("init", 1),
        ("pids_limit", 128.0),
        ("healthcheck", {"disable": 1}),
        ("cpus", "0.5"),
    ],
)
def test_rehashed_equivalent_python_values_do_not_bypass_exact_policy(release, field, value):
    release[2]["services"]["stock-research"][field] = value
    release[5]()
    with pytest.raises(ValueError, match=r"^stock_release_unavailable$"):
        load(release)


def test_false_equivalent_integer_does_not_replace_bind_creation_policy(release):
    release[2]["services"]["stock-research"]["volumes"][0]["bind"]["create_host_path"] = 0
    release[5]()
    with pytest.raises(ValueError, match=r"^stock_release_unavailable$"):
        load(release)


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_run_seconds", 59),
        ("max_run_seconds", 451),
        ("max_run_seconds", True),
        ("scan_interval_seconds", 899),
        ("scan_interval_seconds", 3601),
        ("scan_interval_seconds", 901),
        ("scan_interval_seconds", 900.0),
    ],
)
def test_matching_observation_cannot_bless_out_of_bounds_manifest(release, field, value):
    release[3][field] = release[4][field] = value
    release[5]()
    with pytest.raises(ValueError, match=r"^stock_release_unavailable$"):
        load(release)


def test_valid_nondefault_limits_are_retained_without_overrides(release):
    release[3]["max_run_seconds"] = release[4]["max_run_seconds"] = 60
    release[3]["scan_interval_seconds"] = release[4]["scan_interval_seconds"] = 900
    release[3]["maximum_source_age_seconds"] = 60
    release[3]["max_daily_calls"] = release[3]["max_calls_per_cycle"] = 1
    release[5]()
    result = load(release)
    assert result.max_run_seconds == 60 and result.scan_interval_seconds == 900


@pytest.mark.parametrize(
    "field,value",
    [
        ("image_digest", "sha256:" + "e" * 64),
        ("deployment_config_hash", "e" * 64),
        ("compose_sha256", "e" * 64),
        ("release_key", "e" * 194),
        ("schema_version", True),
    ],
)
def test_canonical_attestation_must_match_every_release_binding(release, field, value):
    path = release[1] / "runtime-image-attestation.json"
    record = json.loads(path.read_bytes())
    record[field] = value
    write(path, record)
    with pytest.raises(ValueError, match=r"^stock_release_unavailable$"):
        load(release)


@pytest.mark.parametrize(
    "name", list(["manifest.json", "stock-configuration.json", "runtime-image-attestation.json"])
)
@pytest.mark.parametrize("change", ["extra", "missing"])
def test_every_record_schema_is_closed(release, name, change):
    path = release[1] / name
    record = json.loads(path.read_bytes())
    if change == "extra":
        record["unexpected"] = "fictional"
    else:
        del record["schema_version"]
    write(path, record)
    if name == "stock-configuration.json":
        release[4]["configuration_observation_sha256"] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        write(release[1] / "manifest.json", release[4])
    with pytest.raises(ValueError, match=r"^stock_release_unavailable$"):
        load(release)


@pytest.mark.parametrize("selected", [0, 1])
@pytest.mark.parametrize("change", ["world_write", "symlink"])
def test_selected_root_and_release_directory_remain_trusted(release, selected, change):
    path = release[selected]
    if change == "world_write":
        path.chmod(0o777)
    else:
        preserved = path.with_name(path.name + "-preserved")
        path.rename(preserved)
        path.symlink_to(preserved, target_is_directory=True)
    with pytest.raises(ValueError, match=r"^stock_release_unavailable$"):
        load(release)


def test_wrong_owner_is_denied_without_permission_repair(release):
    with pytest.raises(ValueError, match=r"^stock_release_unavailable$"):
        module()._load_release(
            release[1] / "manifest.json", trusted_uid=os.geteuid() + 1, release_root=release[0]
        )
    assert release[0].stat().st_uid == os.geteuid()


@pytest.mark.parametrize(
    "name,limit",
    [
        ("manifest.json", 4096),
        ("stock-compose.resolved.json", 65536),
        ("stock-configuration.json", 4096),
        ("runtime-image-attestation.json", 4096),
    ],
)
@pytest.mark.parametrize("change", ["oversize", "fifo", "duplicate_key", "nonfinite", "non_utf8"])
def test_bounded_regular_strict_json_files_only(release, name, limit, change):
    path = release[1] / name
    path.unlink()
    if change == "fifo":
        os.mkfifo(path, 0o444)  # O_NONBLOCK must prevent any wait for a writer.
    else:
        content = {
            "oversize": b" " * (limit + 1),
            "duplicate_key": b'{"schema_version":1,"schema_version":1}\n',
            "nonfinite": b'{"value":NaN}\n',
            "non_utf8": b"\xff\n",
        }[change]
        path.write_bytes(content)
        path.chmod(0o444)
    with pytest.raises(ValueError, match=r"^stock_release_unavailable$"):
        load(release)


@pytest.mark.parametrize("selected", [0, 1])
def test_replaced_namespace_during_read_is_not_adopted(release, monkeypatch, selected):
    verifier = module()
    original = verifier._read_artifact
    replaced = False

    def replace(*args):
        nonlocal replaced
        result = original(*args)
        if not replaced:
            replaced = True
            path = release[selected]
            preserved = path.with_name(path.name + "-preserved")
            path.rename(preserved)
            shutil.copytree(preserved, path)
        return result

    monkeypatch.setattr(verifier, "_read_artifact", replace)
    with pytest.raises(ValueError, match=r"^stock_release_unavailable$"):
        verifier._load_release(
            release[1] / "manifest.json", trusted_uid=os.geteuid(), release_root=release[0]
        )


def test_file_replaced_after_its_read_is_rejected(release, monkeypatch):
    verifier = module()
    original = verifier._read_artifact

    def replace(directory, name, limit, trusted_uid):
        result = original(directory, name, limit, trusted_uid)
        if name == "runtime-image-attestation.json":
            path = release[1] / "manifest.json"
            content = path.read_bytes()
            path.unlink()
            path.write_bytes(content)
            path.chmod(0o444)
        return result

    monkeypatch.setattr(verifier, "_read_artifact", replace)
    with pytest.raises(ValueError, match=r"^stock_release_unavailable$"):
        verifier._load_release(
            release[1] / "manifest.json", trusted_uid=os.geteuid(), release_root=release[0]
        )


def test_uncertain_parent_close_still_closes_new_child(release, monkeypatch):
    verifier = module()
    original_open, original_close = os.open, os.close
    opened = []
    injected = False

    def tracked_open(*args, **kwargs):
        descriptor = original_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def uncertain_close(descriptor):
        nonlocal injected
        original_close(descriptor)
        if not injected:
            injected = True
            raise OSError("fictional private close error")

    monkeypatch.setattr(verifier.os, "open", tracked_open)
    monkeypatch.setattr(verifier.os, "close", uncertain_close)
    leaked = []
    try:
        with pytest.raises(ValueError, match=r"^stock_release_unavailable$"):
            verifier._load_release(
                release[1] / "manifest.json", trusted_uid=os.geteuid(), release_root=release[0]
            )
    finally:
        for descriptor in set(opened):
            try:
                os.fstat(descriptor)
                leaked.append(descriptor)
                original_close(descriptor)
            except OSError:
                pass
    assert not leaked


def test_final_cleanup_attempts_all_owned_descriptors_and_sanitizes_errors(release, monkeypatch):
    verifier = module()
    original_directory = verifier._open_directory
    original_close = os.close
    anchors = []
    injected = False

    def tracked_directory(*args, **kwargs):
        descriptor = original_directory(*args, **kwargs)
        anchors.append(descriptor)
        return descriptor

    def uncertain_close(descriptor):
        nonlocal injected
        original_close(descriptor)
        if len(anchors) == 4 and descriptor == anchors[1] and not injected:
            injected = True
            raise OSError("fictional private close error")

    monkeypatch.setattr(verifier, "_open_directory", tracked_directory)
    monkeypatch.setattr(verifier.os, "close", uncertain_close)
    leaked = []
    try:
        with pytest.raises(ValueError, match=r"^stock_release_unavailable$"):
            verifier._load_release(
                release[1] / "manifest.json", trusted_uid=os.geteuid(), release_root=release[0]
            )
    finally:
        for descriptor in set(anchors):
            try:
                os.fstat(descriptor)
                leaked.append(descriptor)
                original_close(descriptor)
            except OSError:
                pass
    assert injected and not leaked
