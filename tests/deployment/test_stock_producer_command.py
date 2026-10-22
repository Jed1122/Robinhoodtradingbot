"""Public producer through real stores/controllers and native-boundary fixtures."""

import importlib
import io
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from test_stock_build_engine import Wire, response, terminal
from test_stock_compose_render import Commands
from test_stock_probe_controller import Daemon, module
from test_stock_release_publication import scenario as publication_scenario

from infra.hybrid import stock_compose_render as renderer
from infra.hybrid import stock_process
from infra.hybrid import stock_release_producer as producer


def api():
    assert callable(getattr(producer, "produce_release", None)), "Public owned producer is missing"
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_producer.py"
    assert path.is_file(), "Source-SHA-only producer CLI is missing"
    return importlib.import_module("infra.hybrid.stock_producer")


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    fixture, release_root = publication_scenario.__wrapped__(tmp_path, monkeypatch)
    native, original, executable = fixture
    state, engine, version, metadata = native[0]
    wire = Wire([response(version), response(terminal()), response(metadata)]).install(
        monkeypatch, engine
    )
    daemon = Daemon(native[1]).install(monkeypatch, module())
    holder, commands = [], []

    @contextmanager
    def namespace(source_sha, requested):
        with producer._lease(
            source_sha,
            requested,
            root=state[1],
            assets_root=state[2],
            trusted_uid=os.geteuid(),
            release_root=release_root,
        ) as lease:
            holder.append(lease)
            yield lease

    # Only the native filesystem namespace, socket peers, clocks and executable
    # process are replaced. The complete owning protocol remains in the path.
    if hasattr(producer, "_production_lease"):
        monkeypatch.setattr(producer, "_production_lease", namespace)
    monkeypatch.setattr(renderer, "_DOCKER", executable)

    def launch(argv, **kwargs):
        if argv[0] == "/usr/bin/git":
            return original(argv, **kwargs)
        assert argv[0] == str(executable), "Native Docker forbidden"
        assert not commands
        command = Commands(fixture, holder[0]).install(monkeypatch)
        commands.append(command)
        return stock_process.subprocess.Popen(argv, **kwargs)

    monkeypatch.setattr(stock_process.subprocess, "Popen", launch)
    wire.fixture, wire.launcher = fixture, launch
    return state, release_root, wire, daemon, holder, commands


def test_public_producer_returns_only_after_all_owned_operations_and_cleanup(scenario):
    api()
    state, release_root, wire, daemon, holder, commands = scenario
    manifest = producer.produce_release(state[3])
    wire.join()
    daemon.join()
    assert manifest == release_root / state[3] / "manifest.json"
    assert holder[0].closed and holder[0].terminal_ack and producer._ACTIVE is None
    assert daemon.gone and daemon.store._closed
    assert len(wire.requests) == 3 and len(commands[0].calls) == 2
    assert daemon.count("/create?") == daemon.count("/start") == 1
    with pytest.raises(ValueError):
        producer.produce_release(state[3])
    assert len(wire.requests) == 3 and len(commands[0].calls) == 2


def test_second_source_runs_every_native_stage_fresh_after_completed_history(scenario, monkeypatch):
    from test_stock_producer_history import next_source

    api()
    state, release_root, wire, first_daemon, holder, commands = scenario
    first = producer.produce_release(state[3])
    first_daemon.join()
    wire.join()
    second_state = next_source((wire.fixture, release_root))
    # This is a new invocation's original clock, not renewal of the first window.
    state[5]["monotonic_ns"] = time.monotonic_ns()
    native = wire.fixture[0]
    wire.replies.extend([response(native[0][2]), response(terminal()), response(native[0][3])])
    second_daemon = Daemon(native[1])
    second_daemon.cid = "e" * 64
    second_daemon.install(monkeypatch, module())
    original = wire.fixture[1]
    executable = wire.fixture[2]

    def next_launch(argv, **kwargs):
        if argv[0] == "/usr/bin/git":
            return original(argv, **kwargs)
        assert argv[0] == str(executable)
        command = Commands(wire.fixture, holder[-1]).install(monkeypatch)
        commands.append(command)
        return stock_process.subprocess.Popen(argv, **kwargs)

    monkeypatch.setattr(stock_process.subprocess, "Popen", next_launch)
    second = producer.produce_release(second_state[3])
    second_daemon.join()
    wire.join()
    assert first != second and first.exists() and second.exists()
    assert len(holder) == 2 and all(lease.closed and lease.terminal_ack for lease in holder)
    assert len(wire.requests) == 6 and all(len(command.calls) == 2 for command in commands)
    assert first_daemon.count("/start") == second_daemon.count("/start") == 1
    bodies = [body for head, body in wire.requests if head.startswith(b"POST ")]
    assert len(bodies) == 2 and bodies[0] != bodies[1]


@pytest.mark.parametrize("kind", ["close_error", "shutdown", "late", "namespace", "file"])
def test_final_descriptor_cleanup_can_suppress_a_complete_readable_release(
    scenario, monkeypatch, kind
):
    api()
    state, release_root, wire, daemon, holder, _ = scenario
    original = producer.os.close
    reached = False

    def failed(fd):
        nonlocal reached
        selected = holder and holder[0].terminal_ack and fd == holder[0].lock_fd and not reached
        original(fd)
        if selected:
            reached = True
            if kind == "close_error":
                raise OSError("fixture final lock close failed")
            if kind == "shutdown":
                holder[0].shutdown[0] = True
            elif kind == "late":
                state[5]["monotonic_ns"] += 1_200_000_000_000
            elif kind == "namespace":
                state[1].rename(state[1].with_name("detached-producer"))
                state[1].mkdir(mode=0o700)
            else:
                path = release_root / state[3] / "manifest.json"
                raw = path.read_bytes()
                path.unlink()
                path.write_bytes(raw)
                path.chmod(0o444)

    monkeypatch.setattr(producer.os, "close", failed)
    with pytest.raises(ValueError):
        producer.produce_release(state[3])
    wire.join()
    daemon.join()
    assert reached and (release_root / state[3] / "manifest.json").exists()
    assert holder[0].closed and producer._ACTIVE is None


def test_handler_restoration_failure_does_not_return_success(scenario, monkeypatch):
    api()
    state, _, wire, daemon, holder, _ = scenario
    original = signal.signal
    before = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    reached = False

    def failed(number, handler):
        nonlocal reached
        result = original(number, handler)
        if holder and holder[0].terminal_ack and not reached:
            reached = True
            raise ValueError("fixture restore failure after actual restoration")
        return result

    monkeypatch.setattr(signal, "signal", failed)
    with pytest.raises(ValueError):
        producer.produce_release(state[3])
    wire.join()
    daemon.join()
    assert reached and all(signal.getsignal(number) is old for number, old in before.items())


def test_cli_emits_only_the_fixed_manifest_after_success(scenario, monkeypatch):
    cli = api()
    state, release_root, wire, daemon, *_ = scenario
    stream = io.StringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    assert cli.main([state[3]]) == 0
    assert json.loads(stream.getvalue()) == {
        "status": "succeeded",
        "manifest": str(release_root / state[3] / "manifest.json"),
    }
    wire.join()
    daemon.join()


@pytest.mark.parametrize("kind", ["late", "shutdown", "wrong_type"])
def test_cli_formatting_is_inside_the_original_final_gate(scenario, monkeypatch, kind):
    cli = api()
    state, _, wire, daemon, holder, _ = scenario
    original = cli._success
    stream = io.StringIO()

    def delayed(path):
        result = original(path)
        if kind == "late":
            state[5]["monotonic_ns"] += 1_200_000_000_000
        elif kind == "shutdown":
            holder[0].shutdown[0] = True
        else:
            return {"status": "succeeded"}
        return result

    monkeypatch.setattr(cli, "_success", delayed)
    monkeypatch.setattr(cli.sys, "stdout", stream)
    assert cli.main([state[3]]) == 1
    assert json.loads(stream.getvalue())["status"] == "blocked"
    wire.join()
    daemon.join()


def test_cli_rejects_path_image_account_and_mode_overrides_before_native_calls(monkeypatch):
    cli = api()
    for option in ("--root", "--image", "--account", "--live"):
        with pytest.raises(SystemExit) as error:
            cli.main(["a" * 64, option, "invented"])
        assert error.value.code == 2


@pytest.mark.parametrize("kind", ["late", "broken"])
def test_stdout_failure_never_produces_a_successful_exit_or_a_second_status(
    scenario, monkeypatch, kind
):
    cli = api()
    state, _, wire, daemon, *_ = scenario

    class Stream(io.StringIO):
        def write(self, text):
            if kind == "broken":
                raise OSError("fixture output unavailable")
            count = super().write(text)
            state[5]["monotonic_ns"] += 1_200_000_000_000
            return count

    stream = Stream()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    assert cli.main([state[3]]) == 1
    assert len(stream.getvalue().splitlines()) <= 1
    wire.join()
    daemon.join()


def test_real_module_entrypoint_fails_closed_without_native_root_runtime():
    api()
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "infra.hybrid.stock_producer", "invalid-source"],
        cwd=root,
        env={"PYTHONPATH": str(root / "src"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "status": "blocked",
        "reason": "stock_producer_unavailable",
    }
