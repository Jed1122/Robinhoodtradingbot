"""Actual private namespace/lock/file lifecycle; native operations are denied."""

import hashlib
import importlib
import json
import os
from pathlib import Path

import pytest
from test_stock_failed_build_inputs import fixture as evidence_fixture

from infra.hybrid import stock_failed_build_inputs as codec
from infra.hybrid import stock_release_producer as producer


def api():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_failed_build.py"
    assert path.is_file(), "Negative-only failed-build owner is missing"
    return importlib.import_module("infra.hybrid.stock_failed_build")


def failed_case(tmp_path, monkeypatch, *, root=None, release=None, offset_ns=0):
    data = evidence_fixture(monkeypatch)
    module = api()
    monkeypatch.setattr(codec, "_OWNER_UID", os.geteuid())
    monkeypatch.setattr(codec, "_OWNER_GID", os.getegid())
    if root is None:
        root = tmp_path / "producer"
        producer._initialize(root, trusted_uid=os.geteuid())
    if release is None:
        release = tmp_path / "releases"
        release.mkdir(mode=0o700)
    source = data["source_sha256"]
    namespace = json.loads((root / "namespace.json").read_bytes())
    originals = dict(data["original"])
    preparation = json.loads(originals["source-preparation.json"])
    for name in ("started_clock", "completed_clock"):
        preparation[name]["monotonic_ns"] += offset_ns
    preparation["namespace_id"] = namespace["namespace_id"]
    originals["source-preparation.json"] = producer._canonical(preparation)
    dispatch = json.loads(originals["dispatch.json"])
    for name in ("origin", "dispatch_clock"):
        dispatch[name]["monotonic_ns"] += offset_ns
    for name in ("build_deadline_ns", "producer_deadline_ns"):
        dispatch[name] += offset_ns
    dispatch["namespace_id"] = namespace["namespace_id"]
    dispatch["source_preparation_sha256"] = hashlib.sha256(
        originals["source-preparation.json"]
    ).hexdigest()
    originals["dispatch.json"] = producer._canonical(dispatch)
    target = root / "inputs" / (source + ".tar")
    target.write_bytes(data["input_raw"])
    target.chmod(0o600)
    attempt = root / "attempts" / source
    attempt.mkdir(mode=0o700)
    for name, raw in originals.items():
        target = attempt / name
        target.write_bytes(raw)
        target.chmod(0o600)
    current = dict(data["observation"]["reconciler_origin"])
    current["monotonic_ns"] += offset_ns
    monkeypatch.setattr(producer, "_clock", lambda: dict(current))
    monkeypatch.setattr(module, "_clock", lambda: dict(current))

    def observe(commit, engine, origin, *, not_after_ns):
        assert commit == preparation["commit"] and engine == originals["engine.bin"]
        assert origin == dispatch["origin"]
        profile = dict(data["observation"]["daemon_profile"])
        profile["observed_clock"] = dict(current)
        profile["socket_activation"] = dict(profile["socket_activation"])
        capacity = {key: dict(value) for key, value in data["observation"]["capacity"].items()}
        for key, directory in (("producer", root), ("release_root", release)):
            info = directory.stat()
            capacity[key].update(device=info.st_dev, inode=info.st_ino)
        return {"daemon_profile": profile, "capacity": capacity}

    monkeypatch.setattr(module, "observe_build_profile", observe)
    from infra.hybrid import stock_engine

    monkeypatch.setattr(
        stock_engine, "_connection", lambda *a: pytest.fail("Native Docker reached")
    )
    return module, root, release, source, attempt, current


@pytest.fixture
def failed(tmp_path, monkeypatch):
    return failed_case(tmp_path, monkeypatch)


def reconcile(failed):
    module, root, release, source, *_ = failed
    return module._reconciliation(
        source, [False], root=root, release_root=release, trusted_uid=os.geteuid()
    )


def test_owner_adds_only_negative_facts_and_never_replays(failed):
    _, root, release, source, attempt, _ = failed
    before = {p.name: (p.read_bytes(), producer._fingerprint(p.stat())) for p in attempt.iterdir()}
    with reconcile(failed) as finished:
        assert finished.facts == attempt / "failed-build-terminal.json"
    finished.check()
    facts = json.loads(finished.facts.read_bytes())
    assert facts["backend_terminal"] is True and facts["producer_success"] is False
    assert facts["release_qualified"] is facts["cleanup_qualified"] is False
    assert not (release / source).exists()
    assert set(p.name for p in attempt.iterdir()) == set(before) | {"failed-build-terminal.json"}
    assert before == {
        name: ((attempt / name).read_bytes(), producer._fingerprint((attempt / name).stat()))
        for name in before
    }
    with pytest.raises(ValueError), reconcile(failed):
        pytest.fail("Original incident closure repeated")
    with (
        pytest.raises(ValueError),
        producer._lease(
            source,
            [False],
            root=root,
            assets_root=root,
            trusted_uid=os.geteuid(),
            release_root=release,
        ),
    ):
        pytest.fail("Spent source replayed")


def test_supplied_record_cannot_replace_fresh_observer(failed, monkeypatch):
    module, _, _, _, attempt, _ = failed

    def denied(*args, **kwargs):
        raise ValueError("profile unavailable")

    monkeypatch.setattr(module, "observe_build_profile", denied)
    with pytest.raises(ValueError), reconcile(failed):
        pytest.fail("Unobserved incident admitted")
    assert not (attempt / "failed-build-terminal.json").exists()


def test_permanent_lock_contention_does_not_write(failed):
    import fcntl

    _, root, _, _, attempt, _ = failed
    with (root / "producer.lock").open("r+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError), reconcile(failed):
            pytest.fail("Permanent lock bypassed")
    assert not (attempt / "failed-build-terminal.json").exists()


@pytest.mark.parametrize("kind", ["unknown", "release", "extra", "replaced", "mode", "link"])
def test_ambiguous_or_substituted_history_never_writes(failed, kind):
    _, root, release, source, attempt, _ = failed
    path = attempt / "engine.bin"
    if kind == "unknown":
        (root / "attempts" / ("f" * 64)).mkdir(mode=0o700)
    elif kind == "release":
        (release / source).mkdir(mode=0o700)
    elif kind == "extra":
        (attempt / "probe-intent.json").write_text("{}")
    elif kind == "replaced":
        path.unlink()
        path.symlink_to(root / "namespace.json")
    elif kind == "mode":
        path.chmod(0o644)
    else:
        os.link(path, root.parent / "linked")
    with pytest.raises(ValueError), reconcile(failed):
        pytest.fail("Ambiguous history admitted")
    assert not (attempt / "failed-build-terminal.json").exists()


def test_expiry_or_shutdown_after_observation_cannot_publish(failed, monkeypatch):
    module, _, _, _, attempt, clock = failed
    original = module.observe_build_profile

    def late(*args, **kwargs):
        result = original(*args, **kwargs)
        clock["monotonic_ns"] += 120_000_000_000
        return result

    monkeypatch.setattr(module, "observe_build_profile", late)
    with pytest.raises(ValueError), reconcile(failed):
        pytest.fail("Expired incident owner published")
    assert not (attempt / "failed-build-terminal.json").exists()


def test_cleanup_failure_does_not_acknowledge_facts(failed, monkeypatch):
    module, _, _, _, attempt, _ = failed
    original = module._close_all

    def closing(descriptors):
        original(descriptors)
        raise OSError("fixture close failed")

    monkeypatch.setattr(module, "_close_all", closing)
    with pytest.raises(ValueError), reconcile(failed):
        pytest.fail("Cleanup failure became acknowledged success")
    assert (attempt / "failed-build-terminal.json").is_file()


def test_original_durability_failure_prevents_negative_publication(failed, monkeypatch):
    _, _, _, _, attempt, _ = failed
    target = (attempt / "engine.bin").stat()
    original = os.fsync

    def failed_flush(fd):
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) == (target.st_dev, target.st_ino):
            raise OSError("fixture original flush failure")
        return original(fd)

    monkeypatch.setattr(os, "fsync", failed_flush)
    with pytest.raises(ValueError), reconcile(failed):
        pytest.fail("Unacknowledged original durability allowed facts")
    assert not (attempt / "failed-build-terminal.json").exists()


def test_public_entry_rejects_non_linux_root_without_native_io(monkeypatch):
    module = api()
    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setattr(
        module, "observe_build_profile", lambda *a, **k: pytest.fail("Native reached")
    )
    with pytest.raises(ValueError):
        module.reconcile_failed_build("a" * 64)


def fresh_state(failed, tmp_path, monkeypatch):
    from test_stock_release_publication import scenario as publication_scenario

    tmp_path.mkdir(mode=0o700)
    created = publication_scenario.__wrapped__(tmp_path, monkeypatch)
    fixture, _ = created
    old_state, engine, version, metadata = fixture[0][0]
    _, root, release, _, _, _ = failed
    state = (old_state[0], root, *old_state[2:])
    state[5].update(boot_id="22222222-2222-2222-2222-222222222222", utc="2026-10-24T12:00:00+00:00")
    fixture[0][1][2].update(state[5])
    target = root / "inputs" / (state[3] + ".tar")
    target.write_bytes(state[4])
    target.chmod(0o600)
    build = (state, engine, version, metadata)
    fixture = ((build, fixture[0][1]), fixture[1], fixture[2])
    return fixture, release


def test_later_boot_mixed_history_requires_every_fresh_stage(failed, tmp_path, monkeypatch):
    from test_stock_release_producer import opened
    from test_stock_release_producer_probe import built
    from test_stock_release_publication import render

    from infra.hybrid import stock_build_profile
    from infra.hybrid.stock_producer_history import _seal
    from infra.hybrid.stock_release_publication import _publish_files

    with reconcile(failed) as closed:
        pass
    closed.check()
    old_facts = closed.facts.read_bytes()
    source = failed[3]
    seen = []

    def capacity(value):
        assert value["docker"]["path"] == "/var/lib/docker"
        seen.append(value["producer"]["inode"])

    monkeypatch.setattr(stock_build_profile, "check_failed_capacity", capacity)
    scenario = fresh_state(failed, tmp_path / "next", monkeypatch)
    fixture, release = scenario
    with built(fixture[0], monkeypatch, release_root=release) as lease:
        assert lease.history_sources == {source} and lease.completed_sources == set()
        assert lease.built_image is not None
        assert lease.probe_result is lease.compose_bytes is lease.published_manifest is None
        render(scenario, monkeypatch, lease)
        _publish_files(lease)
        _seal(lease)
        assert lease.terminal_ack and lease.probe_result is not None
    assert seen and closed.facts.read_bytes() == old_facts
    assert set(p.name for p in release.iterdir()) == {lease.source.digest}
    from test_stock_producer_history import next_source

    third = next_source(scenario)
    with opened(third, release_root=release) as fresh:
        assert fresh.completed_sources == {lease.source.digest}
        assert fresh.history_sources == {source, lease.source.digest}
        assert fresh.built_image is fresh.probe_result is fresh.compose_bytes is None
        assert fresh.published_manifest is None
    assert len(seen) == 2


@pytest.mark.parametrize("kind", ["both", "partial", "file", "capacity", "future", "fsync"])
def test_invalid_negative_history_denies_before_next_attempt(failed, tmp_path, monkeypatch, kind):
    from test_stock_release_producer import opened

    from infra.hybrid import stock_build_profile

    with reconcile(failed) as closed:
        pass
    monkeypatch.setattr(stock_build_profile, "check_failed_capacity", lambda value: None)
    scenario = fresh_state(failed, tmp_path / "next", monkeypatch)
    fixture, release = scenario
    state = fixture[0][0][0]
    attempt = failed[4]
    if kind == "both":
        (attempt / "terminal.json").write_text("{}")
    elif kind == "partial":
        closed.facts.write_bytes(b"{}\n")
    elif kind == "file":
        target = attempt / "engine.bin"
        raw = target.read_bytes()
        target.unlink()
        target.write_bytes(raw)
        target.chmod(0o600)
    elif kind == "capacity":

        def denied(value):
            raise ValueError("current Docker root unavailable")

        monkeypatch.setattr(stock_build_profile, "check_failed_capacity", denied)
    elif kind == "future":
        state[5]["utc"] = "2026-10-22T00:00:00+00:00"
    else:
        target = closed.facts.stat()
        original = os.fsync

        def denied_flush(fd):
            info = os.fstat(fd)
            if (info.st_dev, info.st_ino) == (target.st_dev, target.st_ino):
                raise OSError("fixture history flush failure")
            return original(fd)

        monkeypatch.setattr(os, "fsync", denied_flush)
    with pytest.raises(ValueError), opened(state, release_root=release):
        pytest.fail("Invalid negative history admitted")
    assert not (failed[1] / "attempts" / state[3]).exists()


def test_existing_success_is_validated_before_incident_closure(tmp_path, monkeypatch):
    from test_stock_producer_history import complete
    from test_stock_release_publication import scenario as publication_scenario

    positive = publication_scenario.__wrapped__(tmp_path, monkeypatch)
    old = complete(positive, monkeypatch)
    case = failed_case(
        tmp_path,
        monkeypatch,
        root=old.root,
        release=positive[1],
        offset_ns=old.last_clock["monotonic_ns"],
    )
    terminal = old.root / "attempts" / old.source.digest / "terminal.json"
    before = terminal.read_bytes()
    with reconcile(case) as finished:
        assert finished.facts.is_file()
    finished.check()
    assert terminal.read_bytes() == before
    assert set(p.name for p in positive[1].iterdir()) == {old.source.digest}


def test_same_boot_historical_closure_obeys_original_monotonic_order(failed, tmp_path, monkeypatch):
    from test_stock_release_producer import opened

    from infra.hybrid import stock_build_profile

    with reconcile(failed):
        pass
    monkeypatch.setattr(stock_build_profile, "check_failed_capacity", lambda value: None)
    fixture, release = fresh_state(failed, tmp_path / "next", monkeypatch)
    state = fixture[0][0][0]
    state[5]["boot_id"] = "11111111-1111-1111-1111-111111111111"
    with opened(state, release_root=release) as lease:
        assert lease.history_sources == {failed[3]}


def test_public_owner_requires_cleanup_before_returning_path(monkeypatch):
    from contextlib import contextmanager

    module = api()
    order = []

    class Final:
        facts = Path("/fixture/failed-build-terminal.json")

        def check(self):
            order.append("check")

    @contextmanager
    def owned(source, shutdown):
        assert source == "a" * 64 and shutdown == [False]
        order.append("entered")
        yield Final()
        order.append("closed")

    monkeypatch.setattr(module, "_reconciliation", owned)
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    assert module.reconcile_failed_build("a" * 64) == Path("/fixture/failed-build-terminal.json")
    assert order == ["entered", "closed", "check", "check"]


@pytest.mark.parametrize("fault", ["partial_write", "file_fsync", "readback"])
def test_partial_or_unacknowledged_facts_never_succeed(failed, monkeypatch, fault):
    _, _, _, _, attempt, _ = failed
    facts = attempt / "failed-build-terminal.json"
    if fault == "readback":
        original = producer._read_binary

        def read(directory, name, *args, **kwargs):
            if name == "failed-build-terminal.json":
                raise OSError("fixture readback failure")
            return original(directory, name, *args, **kwargs)

        monkeypatch.setattr(producer, "_read_binary", read)
    else:
        name = "write" if fault == "partial_write" else "fsync"
        original = getattr(os, name)

        def interrupted(fd, *args):
            if facts.exists():
                info, target = os.fstat(fd), facts.stat()
                if (info.st_dev, info.st_ino) == (target.st_dev, target.st_ino):
                    if fault == "partial_write":
                        original(fd, args[0][:1])
                        return 0
                    raise OSError("fixture facts durability failure")
            return original(fd, *args)

        monkeypatch.setattr(os, name, interrupted)
    with pytest.raises(ValueError), reconcile(failed):
        pytest.fail("Incomplete facts acknowledged")
    assert facts.exists()


def test_shutdown_after_observation_cannot_publish(failed, monkeypatch):
    module, root, release, source, attempt, _ = failed
    original = module.observe_build_profile
    shutdown = [False]

    def interrupted(*args, **kwargs):
        result = original(*args, **kwargs)
        shutdown[0] = True
        return result

    monkeypatch.setattr(module, "observe_build_profile", interrupted)
    with (
        pytest.raises(ValueError),
        module._reconciliation(
            source, shutdown, root=root, release_root=release, trusted_uid=os.geteuid()
        ),
    ):
        pytest.fail("Shutdown ignored")
    assert not (attempt / "failed-build-terminal.json").exists()
