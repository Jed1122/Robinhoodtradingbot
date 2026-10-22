"""Bounded local child processes only; no Docker or provider access."""

import importlib
import os
import signal
import sys
import time
from contextlib import suppress
from pathlib import Path

import pytest


def api():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_process.py"
    assert path.is_file(), "Bounded private stock process capture is missing"
    return importlib.import_module("infra.hybrid.stock_process")


def test_capture_preserves_both_bounded_streams_and_returns_after_reaping(tmp_path):
    result = api()._capture(
        (sys.executable, "-c", "import os; os.write(1,b'out'); os.write(2,b'err')"),
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        limit=16,
        deadline=time.monotonic() + 5,
    )
    assert result.stdout == b"out" and result.stderr == b"err"


@pytest.mark.parametrize("kind", ["stdout", "stderr", "nonzero", "timeout"])
def test_failed_or_oversized_child_cannot_return_a_result(tmp_path, kind):
    program = {
        "stdout": "import os; os.write(1,b'x'*17)",
        "stderr": "import os; os.write(2,b'x'*16385)",
        "nonzero": "raise SystemExit(7)",
        "timeout": "import time; time.sleep(10)",
    }[kind]
    with pytest.raises(ValueError):
        api()._capture(
            (sys.executable, "-c", program),
            cwd=tmp_path,
            env={},
            limit=16,
            deadline=time.monotonic() + (0.2 if kind == "timeout" else 5),
        )


def test_shutdown_during_child_cleanup_suppresses_success(tmp_path, monkeypatch):
    module = api()
    original = module.subprocess.Popen
    closing = [False]

    def child(*args, **kwargs):
        process = original(*args, **kwargs)
        close = process.stdout.close

        def interrupted():
            close()
            closing[0] = True

        monkeypatch.setattr(process.stdout, "close", interrupted)
        return process

    def check():
        if closing[0]:
            raise ValueError("fixture shutdown")

    monkeypatch.setattr(module.subprocess, "Popen", child)
    with pytest.raises(ValueError):
        module._capture(
            (sys.executable, "-c", "print('complete')"),
            cwd=tmp_path,
            env={},
            limit=64,
            deadline=time.monotonic() + 5,
            check=check,
        )


def test_exited_launcher_does_not_leave_its_pipe_holding_child_running(tmp_path, monkeypatch):
    module = api()
    original = module.subprocess.Popen
    processes = []
    heartbeat = tmp_path / "heartbeat"
    plugin = (
        "import time; p=" + repr(str(heartbeat)) + "; "
        "f=open(p,'ab',buffering=0)\nwhile True: f.write(b'x'); time.sleep(0.01)"
    )
    launcher = "import subprocess,sys; subprocess.Popen([sys.executable,'-c'," + repr(plugin) + "])"

    def launch(*args, **kwargs):
        child = original(*args, **kwargs)
        processes.append(child)
        return child

    monkeypatch.setattr(module.subprocess, "Popen", launch)
    try:
        with pytest.raises(ValueError):
            module._capture(
                (sys.executable, "-c", launcher),
                cwd=tmp_path,
                env={},
                limit=64,
                deadline=time.monotonic() + 0.5,
            )
        assert heartbeat.exists() and processes[0].poll() == 0
        time.sleep(0.05)
        before = heartbeat.stat().st_size
        time.sleep(0.1)
        assert heartbeat.stat().st_size == before, "The launcher exited but its child survived"
    finally:
        if processes:
            with suppress(ProcessLookupError):
                os.killpg(processes[0].pid, signal.SIGKILL)
            processes[0].wait(timeout=1)


@pytest.mark.parametrize(
    "changes",
    [
        {"argv": ()},
        {"argv": ("relative",)},
        {"cwd": Path("relative")},
        {"env": {"PATH": 7}},
        {"limit": 0},
        {"limit": True},
        {"deadline": float("inf")},
        {"deadline": float("nan")},
        {"deadline": True},
    ],
)
def test_unsafe_process_bounds_are_denied_before_launch(tmp_path, monkeypatch, changes):
    module = api()
    launched = False

    def forbidden(*args, **kwargs):
        nonlocal launched
        launched = True
        raise AssertionError("Invalid process request launched")

    monkeypatch.setattr(module.subprocess, "Popen", forbidden)
    arguments = {
        "argv": (sys.executable, "-c", "print('bounded')"),
        "cwd": tmp_path,
        "env": {},
        "limit": 64,
        "deadline": time.monotonic() + 5,
    }
    arguments.update(changes)
    with pytest.raises(ValueError):
        module._capture(**arguments)
    assert not launched


def test_launch_failure_has_no_provider_diagnostics_or_success(tmp_path, monkeypatch):
    module = api()

    def unavailable(*args, **kwargs):
        raise OSError("private diagnostic sentinel")

    monkeypatch.setattr(module.subprocess, "Popen", unavailable)
    with pytest.raises(module._CaptureFailed, match=r"^stock_process_unavailable$") as error:
        module._capture(
            (sys.executable, "-c", "pass"),
            cwd=tmp_path,
            env={},
            limit=16,
            deadline=time.monotonic() + 5,
        )
    assert error.value.output.stdout == error.value.output.stderr == b""


@pytest.mark.parametrize("fault", ["stdout_missing", "stderr_missing", "read", "selector", "close"])
def test_native_pipe_failures_reap_the_child_and_close_every_available_pipe(
    tmp_path, monkeypatch, fault
):
    module = api()
    original = module.subprocess.Popen
    children, pipes = [], []
    read = module.os.read

    def launch(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        pipes.extend((child.stdout, child.stderr))
        if fault.endswith("_missing"):
            name = fault.removesuffix("_missing")
            getattr(child, name).close()
            setattr(child, name, None)
        elif fault == "close":
            close = child.stdout.close

            def failed_close():
                close()
                raise OSError("fixture pipe close failed")

            monkeypatch.setattr(child.stdout, "close", failed_close)
        elif fault == "read":
            descriptor = child.stdout.fileno()

            def failed_read(fd, size):
                if fd == descriptor:
                    raise OSError("fixture pipe read failed")
                return read(fd, size)

            monkeypatch.setattr(module.os, "read", failed_read)
        return child

    if fault == "selector":

        def unavailable():
            raise OSError("fixture selector unavailable")

        monkeypatch.setattr(module.selectors, "DefaultSelector", unavailable)
    monkeypatch.setattr(module.subprocess, "Popen", launch)
    with pytest.raises(module._CaptureFailed):
        module._capture(
            (sys.executable, "-c", "print('bounded')"),
            cwd=tmp_path,
            env={},
            limit=64,
            deadline=time.monotonic() + 5,
        )
    assert len(children) == 1 and children[0].poll() is not None
    assert all(pipe.closed for pipe in pipes)


def test_closed_pipes_still_wait_with_original_deadline_and_control_checks(tmp_path):
    module = api()
    calls = []
    result = module._capture(
        (sys.executable, "-c", "import os,time; os.close(1); os.close(2); time.sleep(1.2)"),
        cwd=tmp_path,
        env={},
        limit=16,
        deadline=time.monotonic() + 5,
        check=lambda: calls.append(time.monotonic()),
    )
    assert result.stdout == result.stderr == b""
    assert len(calls) > 3
