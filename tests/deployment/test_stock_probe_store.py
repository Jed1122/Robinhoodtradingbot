"""Fictional private probe persistence; no daemon, credentials or worker authority."""

import hashlib
import importlib
import json
import os
import stat
from pathlib import Path

import pytest


def module():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_probe_store.py"
    assert path.is_file(), "The dedicated inert stock probe store is missing"
    return importlib.import_module("infra.hybrid.stock_probe_store")


@pytest.fixture
def initialized(tmp_path):
    api = module()
    root = tmp_path.resolve() / "probes"
    api._initialize(root, trusted_uid=os.geteuid())
    return api, root


def opened(initialized):
    api, root = initialized
    return api._open_namespace(root, trusted_uid=os.geteuid())


def test_namespace_is_explicit_private_and_bound_to_its_lock_inode(initialized):
    api, root = initialized
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert {p.name for p in root.iterdir()} == {"namespace.json", "launcher.lock"}
    value = json.loads((root / "namespace.json").read_bytes())
    assert set(value) == {
        "schema_version",
        "kind",
        "namespace_id",
        "root_device",
        "root_inode",
        "lock_device",
        "lock_inode",
    }
    assert value["schema_version"] == 1 and value["kind"] == "stock_probe_namespace"
    assert len(value["namespace_id"]) == 32
    assert (value["root_device"], value["root_inode"]) == (root.stat().st_dev, root.stat().st_ino)
    lock = root / "launcher.lock"
    assert (value["lock_device"], value["lock_inode"]) == (lock.stat().st_dev, lock.stat().st_ino)
    assert lock.stat().st_size == 0
    for entry in root.iterdir():
        assert stat.S_IMODE(entry.stat().st_mode) == 0o600
    with opened(initialized) as namespace:
        assert namespace.namespace_id == value["namespace_id"]
        assert not hasattr(namespace, "start_fence")
    with pytest.raises(ValueError, match=r"^stock_probe_store_unavailable$"):
        api._initialize(root, trusted_uid=os.geteuid())


def test_missing_namespace_is_not_created_on_open(tmp_path):
    api = module()
    root = tmp_path.resolve() / "absent"
    with (
        pytest.raises(ValueError, match=r"^stock_probe_store_unavailable$"),
        api._open_namespace(root, trusted_uid=os.geteuid()),
    ):
        pytest.fail("missing namespace was usable")
    assert not root.exists()


def test_exclusive_lock_is_nonblocking_and_released_once(initialized):
    with (
        opened(initialized),
        pytest.raises(ValueError, match=r"^stock_probe_store_unavailable$"),
        opened(initialized),
    ):
        pytest.fail("second owner acquired namespace")
    with opened(initialized) as namespace:
        assert namespace.namespace_id


@pytest.mark.parametrize(
    "name,mode", [(".", 0o755), ("launcher.lock", 0o644), ("namespace.json", 0o644)]
)
def test_unsafe_modes_fail_closed(initialized, name, mode):
    _, root = initialized
    (root / name).chmod(mode)
    with (
        pytest.raises(ValueError, match=r"^stock_probe_store_unavailable$"),
        opened(initialized),
    ):
        pytest.fail("unsafe namespace was usable")


@pytest.mark.parametrize("name", ["namespace.json", "launcher.lock"])
@pytest.mark.parametrize("kind", ["symlink", "hardlink", "replacement"])
def test_changed_links_and_lock_identity_deny(initialized, tmp_path, name, kind):
    _, root = initialized
    entry = root / name
    if kind == "symlink":
        saved = tmp_path / "saved"
        entry.rename(saved)
        entry.symlink_to(saved)
    elif kind == "hardlink":
        os.link(entry, tmp_path / "link")
    else:
        raw = entry.read_bytes()
        entry.rename(tmp_path / "original")
        entry.write_bytes(raw)
        entry.chmod(0o600)
    # Replacing namespace.json with identical validated bytes does not change pinned
    # root/lock identity; only lock replacement violates that namespace binding.
    if kind == "replacement" and name == "namespace.json":
        with opened(initialized):
            pass
    else:
        with pytest.raises(ValueError), opened(initialized):
            pytest.fail("unsafe link or lock substitution was usable")


@pytest.mark.parametrize(
    "field", ["schema_version", "root_device", "root_inode", "lock_device", "lock_inode"]
)
def test_namespace_scalars_do_not_accept_boolean_aliases(initialized, field):
    _, root = initialized
    path = root / "namespace.json"
    value = json.loads(path.read_bytes())
    value[field] = True
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(ValueError), opened(initialized):
        pytest.fail("boolean identity was usable")


@pytest.mark.parametrize(
    "raw",
    [b"{}", b'{"x":1,"x":2}', b'{"x":NaN}', b"not-json", b"\xff", b" " * 4097],
    ids=["missing", "duplicate", "nan", "text", "utf8", "oversized"],
)
def test_invalid_namespace_metadata_is_sanitized(initialized, raw):
    _, root = initialized
    (root / "namespace.json").write_bytes(raw)
    with (
        pytest.raises(ValueError, match=r"^stock_probe_store_unavailable$"),
        opened(initialized),
    ):
        pytest.fail("invalid metadata was usable")


def test_incomplete_foundation_does_not_admit_unknown_or_history_layout(initialized):
    _, root = initialized
    (root / ("a" * 32)).mkdir(mode=0o700)
    with pytest.raises(ValueError), opened(initialized):
        pytest.fail("unimplemented history was admitted")


@pytest.mark.parametrize("uid", [-1, True])
def test_invalid_trust_uid_denies_before_creation(tmp_path, uid):
    api = module()
    root = tmp_path.resolve() / "absent"
    with pytest.raises(ValueError):
        api._initialize(root, trusted_uid=uid)
    assert not root.exists()


@pytest.fixture
def artifact_directory(tmp_path):
    api = module()
    root = tmp_path.resolve() / "artifacts"
    root.mkdir(mode=0o700)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        yield api, root, descriptor
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    "name,raw",
    [
        ("engine.bin", b'{ "version" : 1 }\n'),
        ("image.bin", b"x" * 1048576),
        ("request.bin", b"request"),
        ("create-response.bin", b"response"),
        ("prestart.bin", b"inspection"),
        ("stopped.bin", b"stopped"),
        ("framed-logs.bin", b"\x01\x00\x00\x00\x00\x00\x00\x01\xff"),
        ("framed-logs.bin", b""),
        ("configuration.bin", b"{}\n"),
    ],
    ids=[
        "original-json",
        "maximum-image",
        "request",
        "create-response",
        "prestart",
        "stopped",
        "binary-logs",
        "empty-logs",
        "config",
    ],
)
def test_original_artifact_bytes_are_exclusively_flushed_rehashed_and_retained(
    artifact_directory, name, raw
):
    api, root, directory = artifact_directory
    digest = api._write_bytes(directory, name, raw, os.geteuid())
    assert digest == hashlib.sha256(raw).hexdigest()
    assert api._read_bytes(directory, name, os.geteuid()) == raw
    assert (root / name).read_bytes() == raw
    assert stat.S_IMODE((root / name).stat().st_mode) == 0o600
    with pytest.raises(ValueError):
        api._write_bytes(directory, name, raw, os.geteuid())


@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        "/tmp/outside",
        "nested/image.bin",
        "unknown.bin",
        "launcher.lock",
        "namespace.json",
        "",
        None,
        True,
    ],
)
def test_artifact_basename_is_from_closed_slots_only(artifact_directory, name):
    api, root, directory = artifact_directory
    with pytest.raises(ValueError, match=r"^stock_probe_store_unavailable$"):
        api._write_bytes(directory, name, b"fictional", os.geteuid())
    assert not list(root.iterdir())


@pytest.mark.parametrize(
    "name,raw",
    [
        ("engine.bin", b""),
        ("create-response.bin", b"x" * 4097),
        ("framed-logs.bin", b"x" * 16385),
        ("configuration.bin", b"x" * 4097),
        ("image.bin", b"x" * 1048577),
        ("request.bin", "text"),
        ("request.bin", None),
    ],
    ids=[
        "empty-json",
        "large-response",
        "large-logs",
        "large-config",
        "large-image",
        "string",
        "none",
    ],
)
def test_artifact_bounds_deny_before_creation(artifact_directory, name, raw):
    api, root, directory = artifact_directory
    with pytest.raises(ValueError):
        api._write_bytes(directory, name, raw, os.geteuid())
    assert not list(root.iterdir())


@pytest.mark.parametrize("operation", ["write", "file-fsync", "dir-fsync", "readback"])
def test_write_failures_never_acknowledge_or_repair_leftover_bytes(
    artifact_directory, monkeypatch, operation
):
    api, root, directory = artifact_directory
    real_write, real_sync, real_read = api.os.write, api.os.fsync, api._read_bytes
    if operation == "write":
        monkeypatch.setattr(api.os, "write", lambda *_: 0)
    elif operation.endswith("fsync"):

        def fail_sync(fd):
            if (fd == directory) == (operation == "dir-fsync"):
                raise OSError("sensitive fictional failure")
            return real_sync(fd)

        monkeypatch.setattr(api.os, "fsync", fail_sync)
    else:
        monkeypatch.setattr(api, "_read_bytes", lambda *_: b"changed")
    with pytest.raises(ValueError, match=r"^stock_probe_store_unavailable$"):
        api._write_bytes(directory, "request.bin", b"fictional request", os.geteuid())
    monkeypatch.setattr(api.os, "write", real_write)
    monkeypatch.setattr(api.os, "fsync", real_sync)
    monkeypatch.setattr(api, "_read_bytes", real_read)
    assert (root / "request.bin").exists()
    with pytest.raises(ValueError):
        api._write_bytes(directory, "request.bin", b"fictional request", os.geteuid())


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "mode", "oversized"])
def test_unsafe_artifact_read_is_denied(artifact_directory, tmp_path, kind):
    api, root, directory = artifact_directory
    api._write_bytes(directory, "request.bin", b"original", os.geteuid())
    path = root / "request.bin"
    if kind == "symlink":
        path.rename(tmp_path / "saved")
        path.symlink_to(tmp_path / "saved")
    elif kind == "hardlink":
        os.link(path, tmp_path / "link")
    elif kind == "mode":
        path.chmod(0o644)
    else:
        path.write_bytes(b"x" * 1048577)
    with pytest.raises(ValueError, match=r"^stock_probe_store_unavailable$"):
        api._read_bytes(directory, "request.bin", os.geteuid())


def test_short_writes_are_completed_without_restarting_the_file(artifact_directory, monkeypatch):
    api, root, directory = artifact_directory
    real_write = api.os.write
    monkeypatch.setattr(api.os, "write", lambda fd, raw: real_write(fd, raw[:2]))
    api._write_bytes(directory, "request.bin", b"many short writes", os.geteuid())
    assert (root / "request.bin").read_bytes() == b"many short writes"


def test_same_lock_cache_does_not_skip_changed_bytes_or_cross_contexts(artifact_directory):
    api, root, directory = artifact_directory
    api._write_bytes(directory, "request.bin", b"original", os.geteuid())
    cache = api._ContentCache()
    assert cache.read(directory, "request.bin", os.geteuid()) == b"original"
    assert cache.read(directory, "request.bin", os.geteuid()) == b"original"
    (root / "request.bin").write_bytes(b"modified")
    assert cache.read(directory, "request.bin", os.geteuid()) == b"modified"
    assert api._ContentCache().read(directory, "request.bin", os.geteuid()) == b"modified"


@pytest.mark.parametrize("mutation", ["truncate", "grow", "same-bytes", "replace-name"])
def test_read_detects_incomplete_or_mutated_original_artifact(
    artifact_directory, monkeypatch, mutation
):
    api, root, directory = artifact_directory
    original = b"x" * 10000
    api._write_bytes(directory, "request.bin", original, os.geteuid())
    real_read = api.os.read
    changed = False

    def changing_read(fd, count):
        nonlocal changed
        result = real_read(fd, count)
        if not changed and result:
            changed = True
            path = root / "request.bin"
            if mutation == "truncate":
                path.write_bytes(b"x")
            elif mutation == "grow":
                with path.open("ab") as stream:
                    stream.write(b"extra")
            elif mutation == "same-bytes":
                path.write_bytes(original)
            else:
                path.rename(root / "saved")
                path.write_bytes(original)
                path.chmod(0o600)
        return result

    monkeypatch.setattr(api.os, "read", changing_read)
    with pytest.raises(ValueError, match=r"^stock_probe_store_unavailable$"):
        api._read_bytes(directory, "request.bin", os.geteuid())


def test_cache_reuses_content_only_for_unchanged_named_file(artifact_directory, monkeypatch):
    api, root, directory = artifact_directory
    api._write_bytes(directory, "request.bin", b"original", os.geteuid())
    real_read = api._read_bytes
    calls = []

    def counted(*args):
        calls.append(args)
        return real_read(*args)

    monkeypatch.setattr(api, "_read_bytes", counted)
    cache = api._ContentCache()
    for _ in range(3):
        assert cache.read(directory, "request.bin", os.geteuid()) == b"original"
    assert len(calls) == 1
    (root / "request.bin").chmod(0o644)
    with pytest.raises(ValueError):
        cache.read(directory, "request.bin", os.geteuid())


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "stock_operations_namespace"),
        ("namespace_id", "A" * 32),
        ("namespace_id", False),
        ("extra", 1),
    ],
)
def test_namespace_schema_is_closed(initialized, field, value):
    _, root = initialized
    path = root / "namespace.json"
    body = json.loads(path.read_bytes())
    body[field] = value
    path.write_text(json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(ValueError), opened(initialized):
        pytest.fail("changed schema was usable")


def test_noncanonical_metadata_and_nonempty_lock_deny(initialized):
    _, root = initialized
    path = root / "namespace.json"
    original = path.read_bytes()
    path.write_text(json.dumps(json.loads(original), indent=2))
    with pytest.raises(ValueError), opened(initialized):
        pytest.fail("noncanonical metadata was usable")
    path.write_bytes(original)
    (root / "launcher.lock").write_bytes(b"unexpected")
    with pytest.raises(ValueError), opened(initialized):
        pytest.fail("nonempty lock was usable")


@pytest.mark.parametrize("stage", [1, 2, 3, 4, 5])
def test_initialization_sync_failure_never_repairs_partial_namespace(tmp_path, monkeypatch, stage):
    api = module()
    root = tmp_path.resolve() / "probes"
    real_sync = api.os.fsync
    calls = 0

    def fail_at(fd):
        nonlocal calls
        calls += 1
        if calls == stage:
            raise OSError("sensitive fictional sync failure")
        return real_sync(fd)

    monkeypatch.setattr(api.os, "fsync", fail_at)
    with pytest.raises(ValueError, match=r"^stock_probe_store_unavailable$"):
        api._initialize(root, trusted_uid=os.geteuid())
    assert root.exists()
    monkeypatch.setattr(api.os, "fsync", real_sync)
    with pytest.raises(ValueError):
        api._initialize(root, trusted_uid=os.geteuid())


def test_symlink_ancestor_and_relative_initialization_deny(tmp_path):
    api = module()
    (tmp_path / "real").mkdir(mode=0o700)
    (tmp_path / "alias").symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(ValueError):
        api._initialize(tmp_path / "alias" / "probes", trusted_uid=os.geteuid())
    with pytest.raises(ValueError):
        api._initialize(Path("relative-probes"), trusted_uid=os.geteuid())
    assert not (tmp_path / "real" / "probes").exists()


@pytest.mark.parametrize("entry", ["initialize_probes", "probes"])
@pytest.mark.parametrize("platform,uid", [("darwin", 0), ("linux", 10001)])
def test_public_entry_denies_nonroot_or_unsupported_host(monkeypatch, entry, platform, uid):
    api = module()
    monkeypatch.setattr(api.sys, "platform", platform)
    monkeypatch.setattr(api.os, "geteuid", lambda: uid)
    with pytest.raises(ValueError, match=r"^stock_probe_store_unavailable$"):
        getattr(api, entry)()


def test_public_entries_select_only_the_fixed_root_and_uid(monkeypatch):
    api = module()
    monkeypatch.setattr(api.sys, "platform", "linux")
    monkeypatch.setattr(api.os, "geteuid", lambda: 0)
    calls = []
    sentinel = object()

    def initialize(root, *, trusted_uid):
        calls.append(("initialize", root, trusted_uid))

    def opened(root, *, trusted_uid):
        calls.append(("open", root, trusted_uid))
        return sentinel

    monkeypatch.setattr(api, "_initialize", initialize)
    monkeypatch.setattr(api, "_open_namespace", opened)
    api.initialize_probes()
    assert api.probes() is sentinel
    assert calls == [
        ("initialize", Path("/var/lib/hybrid-stock-probes"), 0),
        ("open", Path("/var/lib/hybrid-stock-probes"), 0),
    ]
    with pytest.raises(TypeError):
        api.probes(Path("/tmp/alternate"))


def test_artifact_growth_past_closed_cap_is_bounded_and_rejected(artifact_directory, monkeypatch):
    api, root, directory = artifact_directory
    api._write_bytes(directory, "create-response.bin", b"x" * 4096, os.geteuid())
    real_read = api.os.read
    changed = False

    def growing_read(fd, count):
        nonlocal changed
        raw = real_read(fd, count)
        if not changed:
            changed = True
            with (root / "create-response.bin").open("ab") as stream:
                stream.write(b"extra")
        return raw

    monkeypatch.setattr(api.os, "read", growing_read)
    with pytest.raises(ValueError, match=r"^stock_probe_store_unavailable$"):
        api._read_bytes(directory, "create-response.bin", os.geteuid())
