"""Owned build plus actual fixed probe/store/socket composition; no native Docker."""

import hashlib
import json
import signal
from contextlib import contextmanager

import pytest
from test_stock_build_engine import Wire, response, terminal
from test_stock_build_engine import scenario as build_scenario
from test_stock_probe_controller import Daemon, module
from test_stock_probe_controller import scenario as probe_scenario
from test_stock_release_producer import opened

from infra.hybrid import stock_release_producer as producer
from infra.hybrid.stock_supervisor import _shutdown


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    build = build_scenario.__wrapped__(tmp_path, monkeypatch)
    probe = probe_scenario.__wrapped__(tmp_path, monkeypatch)
    probe[2]["boot_id"] = build[0][5]["boot_id"]
    from infra.hybrid import stock_probe_engine

    def denied(*args, **kwargs):
        raise AssertionError("Native Docker is forbidden in these fixtures")

    monkeypatch.setattr(stock_probe_engine, "_connection", denied)
    return build, probe


def operation():
    owned = getattr(producer, "_fresh_probe", None)
    assert callable(owned), "Owned fresh probe composition is missing"
    return owned


@contextmanager
def built(scenario, monkeypatch):
    build, _ = scenario
    state, engine, version, metadata = build
    wire = Wire([response(version), response(terminal()), response(metadata)]).install(
        monkeypatch, engine
    )
    with _shutdown() as requested:
        state = (*state[:6], requested)
        with opened(state) as lease:
            result = engine._build(lease)
            wire.join()
            assert result.image_digest.startswith("sha256:")
            yield lease


def test_actual_owned_probe_is_fresh_and_retains_exact_configuration(scenario, monkeypatch):
    run = operation()
    build, probe = scenario
    daemon = Daemon(probe)
    with built(scenario, monkeypatch) as lease:
        daemon.install(monkeypatch, module())
        result = run(lease)
        directory = build[0][1] / "attempts" / build[0][3]
        raw = (directory / "configuration.bin").read_bytes()
        assert raw == result.configuration and json.loads(raw)["live_enabled"] is False
        receipt = json.loads((directory / "probe-result.json").read_bytes())
        assert receipt["probe_id"] == result.probe_id
        assert receipt["container_id"] == result.container_id
        assert receipt["configuration_sha256"] == hashlib.sha256(raw).hexdigest()
        assert receipt["build_complete_sha256"] == lease.hashes["build-complete.json"]
        assert receipt["probe_intent_sha256"] == lease.hashes["probe-intent.json"]
        assert lease.probe_result is result and daemon.store._closed and daemon.gone
        with pytest.raises(ValueError):
            run(lease)
    daemon.join()
    assert daemon.count("/create?") == daemon.count("/start") == daemon.count("/logs?") == 1


@pytest.mark.parametrize("kind", ["bad_output", "bad_exit", "recovery", "shutdown", "late"])
def test_noneligible_or_late_actual_probe_never_advances_producer(scenario, monkeypatch, kind):
    run = operation()
    build, probe = scenario
    daemon = Daemon(probe)
    if kind == "bad_output":
        daemon.bad_output = True
    elif kind == "bad_exit":
        daemon.exit_facts = {"ExitCode": 7}
    elif kind == "recovery":
        from test_stock_probe_admission import admitted
        from test_stock_probe_admission import opened as probe_opened

        with probe_opened(probe) as store:
            admitted(store, probe)

    def interrupt(method, path):
        if method == "DELETE":
            if kind == "late":
                build[0][5]["monotonic_ns"] += 1_200_000_000_000
            elif kind == "shutdown":
                handler = signal.getsignal(signal.SIGINT)
                assert callable(handler)
                handler(signal.SIGINT, None)

    daemon.on_request = interrupt
    with pytest.raises(ValueError), built(scenario, monkeypatch) as lease:
        daemon.install(monkeypatch, module())
        run(lease)
    daemon.join()
    assert lease.probe_result is None
    assert daemon.count("/create?") <= 1 and daemon.count("/start") <= 1
    directory = build[0][1] / "attempts" / build[0][3]
    assert not (directory / "terminal.json").exists()


def test_supplied_source_context_cannot_probe_without_its_owned_build(scenario):
    run = operation()
    build, _ = scenario
    with opened(build[0]) as lease, pytest.raises(ValueError):
        run(lease)


def test_failed_current_probe_is_not_retried_with_readable_closed_history(scenario, monkeypatch):
    run = operation()
    _, probe = scenario
    daemon = Daemon(probe)
    daemon.bad_output = True
    with built(scenario, monkeypatch) as lease:
        daemon.install(monkeypatch, module())
        with pytest.raises(ValueError):
            run(lease)
        requests = tuple(daemon.requests)
        with pytest.raises(ValueError):
            run(lease)
        assert tuple(daemon.requests) == requests and lease.probe_result is None
    daemon.join()
    assert daemon.gone and daemon.count("/create?") == 1


@pytest.mark.parametrize("slot", ["probe-intent.json", "probe-result.json", "configuration.bin"])
@pytest.mark.parametrize("failure", ["fsync", "shutdown"])
def test_probe_durable_boundaries_cannot_yield_a_current_success(
    scenario, monkeypatch, slot, failure
):
    run = operation()
    build, probe = scenario
    daemon = Daemon(probe)
    original = producer.os.fsync
    reached = False
    with pytest.raises(ValueError), built(scenario, monkeypatch) as lease:
        daemon.install(monkeypatch, module())
        target = build[0][1] / "attempts" / build[0][3] / slot

        def interrupted(fd):
            nonlocal reached
            if target.exists():
                info, expected = producer.os.fstat(fd), target.stat()
                if (info.st_dev, info.st_ino) == (expected.st_dev, expected.st_ino):
                    reached = True
                    if failure == "fsync":
                        raise OSError("fixture probe durability failure")
                    lease.shutdown[0] = True
            original(fd)

        monkeypatch.setattr(producer.os, "fsync", interrupted)
        run(lease)
    monkeypatch.setattr(producer.os, "fsync", original)
    daemon.join()
    assert reached and lease.probe_result is None
    if slot == "probe-intent.json":
        assert not daemon.requests
    else:
        assert daemon.gone and daemon.count("/create?") == 1
