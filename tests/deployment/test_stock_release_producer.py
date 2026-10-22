"""Real private filesystem lease; no native build, daemon or credentials."""

import hashlib
import importlib
import os
import time
from pathlib import Path

import pytest
from test_stock_build_inputs import FILES, archive

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ("Dockerfile", ".docker-base-image", "compose.stock-research.yml")


def api():
    path = ROOT / "infra/hybrid/stock_release_producer.py"
    assert path.is_file(), "Exclusive stock producer lease is missing"
    return importlib.import_module("infra.hybrid.stock_release_producer")


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    module = api()
    from infra.hybrid import stock_engine

    def denied(*args, **kwargs):
        raise AssertionError("Native Docker is forbidden in these fixtures")

    monkeypatch.setattr(stock_engine, "_connection", denied)
    clock = {
        "boot_id": "11111111-1111-1111-1111-111111111111",
        "utc": "2026-10-22T12:00:00+00:00",
        "monotonic_ns": time.monotonic_ns(),
    }
    monkeypatch.setattr(module, "_clock", lambda: dict(clock))
    assets = tmp_path / "assets"
    assets.mkdir(mode=0o700)
    for name in ASSETS:
        raw = (ROOT / name).read_bytes()
        (assets / name).write_bytes(raw)
        (assets / name).chmod(0o644)
        monkeypatch.setitem(FILES, name, raw)
    raw = archive()
    sha = hashlib.sha256(raw).hexdigest()
    root = tmp_path / "producer"
    module._initialize(root, trusted_uid=os.geteuid())
    source = root / "inputs" / (sha + ".tar")
    source.write_bytes(raw)
    source.chmod(0o600)
    return module, root, assets, sha, raw, clock, [False]


def opened(scenario, **kwargs):
    module, root, assets, sha, _, _, shutdown = scenario
    return module._lease(
        sha, shutdown, root=root, assets_root=assets, trusted_uid=os.geteuid(), **kwargs
    )


def test_initialize_is_explicit_exclusive_and_private(tmp_path):
    module = api()
    root = tmp_path / "producer"
    with (
        pytest.raises(ValueError),
        module._lease("a" * 64, [False], root=root, assets_root=tmp_path, trusted_uid=os.geteuid()),
    ):
        pytest.fail("Uninitialized namespace admitted")
    assert not root.exists()
    module._initialize(root, trusted_uid=os.geteuid())
    assert set(p.name for p in root.iterdir()) == {
        "inputs",
        "attempts",
        "producer.lock",
        "namespace.json",
    }
    assert root.stat().st_mode & 0o777 == 0o700
    assert (root / "producer.lock").stat().st_mode & 0o777 == 0o600
    assert (root / "producer.lock").read_bytes() == b""
    with pytest.raises(ValueError):
        module._initialize(root, trusted_uid=os.geteuid())


def test_owned_context_retains_original_source_and_excludes_nested_lease(scenario):
    module, root, _, sha, raw, _, _ = scenario
    with opened(scenario) as lease:
        assert lease.source.digest == sha
        assert (root / "attempts" / sha / "source.tar").read_bytes() == raw
        with pytest.raises(ValueError), opened(scenario):
            pytest.fail("Contended lock admitted")
        lease.check()
    with pytest.raises(ValueError):
        lease.check()
    with pytest.raises(ValueError), opened(scenario):
        pytest.fail("Unfinished build attempt replayed")
    assert module._ACTIVE is None


@pytest.mark.parametrize("sha", [None, True, b"a" * 64, "A" * 64, "a" * 63, "../x"])
def test_invalid_source_identity_never_creates_attempt(scenario, sha):
    module, root, assets, _, _, _, shutdown = scenario
    with (
        pytest.raises(ValueError),
        module._lease(sha, shutdown, root=root, assets_root=assets, trusted_uid=os.geteuid()),
    ):
        pytest.fail("Invalid identity admitted")
    assert not list((root / "attempts").iterdir())


@pytest.mark.parametrize(
    "kind",
    [
        "source_mode",
        "source_link",
        "source_symlink",
        "source_changed",
        "root_mode",
        "lock_link",
        "namespace_extra",
        "attempt",
        "input_extra",
    ],
)
def test_invalid_or_unfinished_namespace_fails_before_new_attempt(scenario, kind):
    _, root, _, sha, _, _, _ = scenario
    source = root / "inputs" / (sha + ".tar")
    if kind == "source_mode":
        source.chmod(0o644)
    elif kind == "source_link":
        os.link(source, root.parent / "linked")
    elif kind == "source_symlink":
        source.unlink()
        source.symlink_to(root / "namespace.json")
    elif kind == "source_changed":
        source.write_bytes(b"not the source")
    elif kind == "root_mode":
        root.chmod(0o755)
    elif kind == "lock_link":
        os.link(root / "producer.lock", root.parent / "linked")
    elif kind == "namespace_extra":
        (root / "unexpected").write_text("x")
    elif kind == "attempt":
        (root / "attempts" / ("f" * 64)).mkdir(mode=0o700)
    else:
        (root / "inputs" / "extra").write_text("x")
    with pytest.raises(ValueError), opened(scenario):
        pytest.fail("Unsafe namespace admitted")
    assert not (root / "attempts" / sha).exists()


@pytest.mark.parametrize("name", ASSETS)
def test_recipe_drift_denies_source_even_when_valid_tar(scenario, name):
    _, root, assets, sha, _, _, _ = scenario
    (assets / name).write_bytes((assets / name).read_bytes() + b"\n")
    with pytest.raises(ValueError), opened(scenario):
        pytest.fail("Unreviewed recipe admitted")
    assert not (root / "attempts" / sha).exists()


@pytest.mark.parametrize(
    "kind",
    [
        "source_replace",
        "asset_replace",
        "attempt_replace",
        "extra_file",
        "input_extra",
        "lock_replace",
        "root_replace",
    ],
)
def test_current_inode_or_inventory_substitution_invalidates_context(scenario, kind):
    _, root, assets, sha, _, _, _ = scenario
    with pytest.raises(ValueError), opened(scenario) as lease:
        if kind == "source_replace":
            path = root / "inputs" / (sha + ".tar")
        elif kind == "asset_replace":
            path = assets / "Dockerfile"
        elif kind == "lock_replace":
            path = root / "producer.lock"
        elif kind == "root_replace":
            root.rename(root.with_name("old-root"))
            root.mkdir(mode=0o700)
            lease.check()
            pytest.fail("Root replacement admitted")
        elif kind == "attempt_replace":
            path = root / "attempts" / sha
            path.rename(path.with_name("old-attempt"))
            path.mkdir(mode=0o700)
            lease.check()
            pytest.fail("Attempt replacement admitted")
        else:
            parent = root / "attempts" / sha if kind == "extra_file" else root / "inputs"
            (parent / "unexpected").write_bytes(b"x")
            lease.check()
            pytest.fail("Inventory substitution admitted")
        raw, mode = path.read_bytes(), path.stat().st_mode & 0o777
        path.unlink()
        path.write_bytes(raw)
        path.chmod(mode)
        lease.check()
        pytest.fail("Identical-byte replacement admitted")


@pytest.mark.parametrize("kind", ["boot", "utc", "mono", "deadline", "shutdown", "shutdown_shape"])
def test_original_clock_and_shutdown_cannot_be_renewed(scenario, kind):
    _, _, _, _, _, clock, shutdown = scenario
    with pytest.raises(ValueError), opened(scenario) as lease:
        if kind == "boot":
            clock["boot_id"] = "22222222-2222-2222-2222-222222222222"
        elif kind == "utc":
            clock["utc"] = "2026-10-22T11:59:59+00:00"
        elif kind == "mono":
            clock["monotonic_ns"] -= 1
        elif kind == "deadline":
            clock["monotonic_ns"] += 1_200_000_000_000
        elif kind == "shutdown":
            shutdown[0] = True
        else:
            shutdown[0] = 0
        lease.check()
        pytest.fail("Expired or interrupted producer admitted")


def test_fsync_failure_leaves_incident_and_never_creates_dispatch(scenario, monkeypatch):
    module, root, _, sha, _, _, _ = scenario
    original = module.os.fsync
    calls = 0

    def fail_second(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("fixture fsync failure")
        original(fd)

    monkeypatch.setattr(module.os, "fsync", fail_second)
    with pytest.raises(ValueError), opened(scenario):
        pytest.fail("Failed source durability admitted")
    assert not (root / "attempts" / sha / "dispatch.json").exists()
    monkeypatch.setattr(module.os, "fsync", original)
    with pytest.raises(ValueError), opened(scenario):
        pytest.fail("Incident resumed")


@pytest.mark.parametrize("kind", ["source", "asset", "inputs_inventory"])
def test_admission_pins_the_files_actually_read_not_later_replacements(scenario, monkeypatch, kind):
    module, root, assets, sha, _, _, _ = scenario
    original = module._read_binary
    replaced = False

    def substitute(directory, name, *args, **kwargs):
        nonlocal replaced
        raw = original(directory, name, *args, **kwargs)
        target = sha + ".tar" if kind != "asset" else "Dockerfile"
        if name == target and not replaced:
            replaced = True
            if kind == "inputs_inventory":
                (root / "inputs" / "unexpected").write_bytes(b"x")
            else:
                path = root / "inputs" / name if kind == "source" else assets / name
                mode = path.stat().st_mode & 0o777
                path.rename(path.with_name(path.name + ".old"))
                path.write_bytes(raw)
                path.chmod(mode)
        return raw

    monkeypatch.setattr(module, "_read_binary", substitute)
    with pytest.raises(ValueError), opened(scenario):
        pytest.fail("Admission adopted a post-read replacement")


def test_real_nonblocking_flock_prevents_a_second_process_owner(scenario):
    import fcntl

    _, root, _, sha, _, _, _ = scenario
    descriptor = os.open(root / "producer.lock", os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError), opened(scenario):
            pytest.fail("Already locked namespace admitted")
    finally:
        os.close(descriptor)
    assert not (root / "attempts" / sha).exists()


def test_public_initializer_has_fixed_root_and_no_native_build(monkeypatch):
    module = api()
    calls = []
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module, "_initialize", lambda root, **kwargs: calls.append((root, kwargs)))
    assert module.initialize_producer() is None
    assert calls == [(Path("/var/lib/hybrid-stock-producer"), {"trusted_uid": 0})]


@pytest.mark.parametrize("platform,uid", [("darwin", 0), ("linux", 1000)])
def test_public_initializer_fails_closed_without_root_linux(monkeypatch, platform, uid):
    module = api()
    monkeypatch.setattr(module.sys, "platform", platform)
    monkeypatch.setattr(module.os, "geteuid", lambda: uid)
    with pytest.raises(ValueError):
        module.initialize_producer()


@pytest.mark.parametrize("kind", ["namespace", "lock"])
def test_namespace_and_lock_keep_the_identity_actually_admitted(scenario, monkeypatch, kind):
    module, root, _, _, _, _, _ = scenario
    original = module._read
    changed = False

    def substitute(directory, name, uid):
        nonlocal changed
        result = original(directory, name, uid)
        if name == "namespace.json" and not changed:
            changed = True
            path = root / ("namespace.json" if kind == "namespace" else "producer.lock")
            raw = path.read_bytes()
            path.rename(root.parent / "old-admission-file")
            path.write_bytes(raw)
            path.chmod(0o600)
        return result

    monkeypatch.setattr(module, "_read", substitute)
    with pytest.raises(ValueError), opened(scenario):
        pytest.fail("Namespace admitted a replacement instead of the locked/read inode")


@pytest.mark.parametrize("slot", ["engine.bin", "dispatch.json"])
def test_current_durable_ack_does_not_adopt_identical_readback_replacement(
    scenario, monkeypatch, slot
):
    module, root, _, sha, _, _, _ = scenario
    original = module._read_binary
    changed = False
    with pytest.raises(ValueError), opened(scenario) as lease:

        def substitute(directory, name, *args, **kwargs):
            nonlocal changed
            raw = original(directory, name, *args, **kwargs)
            if name == slot and not changed:
                changed = True
                path = root / "attempts" / sha / slot
                path.rename(root.parent / "old-durable-file")
                path.write_bytes(raw)
                path.chmod(0o600)
            return raw

        monkeypatch.setattr(module, "_read_binary", substitute)
        if slot == "dispatch.json":
            # Existing _write_new uses its JSON reader, so intercept that same boundary.
            from infra.hybrid import stock_attempts

            json_read = stock_attempts._read

            def replaced_json(directory, name, uid):
                result = json_read(directory, name, uid)
                if name == slot and not changed:
                    substitute(directory, name, uid, 1, 4096)
                return result

            monkeypatch.setattr(stock_attempts, "_read", replaced_json)
            lease.record(slot, {"kind": "fixture"})
        else:
            lease.retain(slot, b"original build metadata")
        pytest.fail("Durability adopted a different inode")
