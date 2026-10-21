"""Collector authority uses only private fictional files, never brokerage state."""

import importlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest

NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)
CONFIG = "b" * 64
CODE = "c" * 64


def module():
    try:
        return importlib.import_module("trading_bot.runtime.stock_research_controls")
    except ModuleNotFoundError:
        pytest.fail("Dedicated stock collector control authority is not implemented")


def store(tmp_path, *, clock=lambda: NOW):
    root = tmp_path.resolve() / "controls"
    root.mkdir(mode=0o700)
    return module().StockResearchControls(root, clock=clock), root


def active(owner):
    paused = owner.initialize()
    current = owner.change(
        "resume", expected_sha256=paused.sha256, config_hash=CONFIG, code_hash=CODE
    )
    return current, owner.grant(config_hash=CONFIG, code_hash=CODE)


def test_initialization_is_explicit_paused_private_and_cannot_replace(tmp_path):
    owner, root = store(tmp_path)
    with pytest.raises(ValueError):
        owner.read()
    assert list(root.iterdir()) == []
    state = owner.initialize()
    assert state.record.status == "paused" and state.record.generation == 0
    assert state.record.config_hash is state.record.code_hash is None
    assert (root / "stock-control.json").stat().st_mode & 0o777 == 0o600
    assert len(state.sha256) == 64
    assert owner.read() == state
    with pytest.raises(ValueError):
        owner.initialize()
    assert owner.read() == state
    with pytest.raises(ValueError):
        owner.grant(config_hash=CONFIG, code_hash=CODE)


def test_resume_binds_exact_code_and_configuration_with_compare_and_swap(tmp_path):
    owner, _ = store(tmp_path)
    state, grant = active(owner)
    assert state.record.status == "running" and state.record.generation == 1
    with owner.permit(grant):
        pass
    for values in ({"config_hash": "d" * 64}, {"code_hash": "d" * 64}):
        with pytest.raises(ValueError):
            owner.grant(**({"config_hash": CONFIG, "code_hash": CODE} | values))
    with pytest.raises(ValueError):
        owner.change("pause", expected_sha256="0" * 64)
    assert owner.read() == state


def test_pause_then_resume_never_revives_an_old_cycle(tmp_path):
    owner, _ = store(tmp_path)
    state, old = active(owner)
    paused = owner.change("pause", expected_sha256=state.sha256)
    resumed = owner.change(
        "resume", expected_sha256=paused.sha256, config_hash=CONFIG, code_hash=CODE
    )
    assert resumed.record.generation == 3
    assert resumed.record.control_id == state.record.control_id
    assert resumed.record.previous_sha256 == paused.sha256
    with pytest.raises(ValueError), owner.permit(old):
        pytest.fail("Old admitted generation must stay fenced")
    with owner.permit(owner.grant(config_hash=CONFIG, code_hash=CODE)):
        pass


def test_kill_survives_restart_and_cannot_be_cleared_by_pause_or_resume(tmp_path):
    owner, root = store(tmp_path)
    state, old = active(owner)
    killed = owner.change("kill", expected_sha256=state.sha256)
    restarted = module().StockResearchControls(root, clock=lambda: NOW)
    assert restarted.read() == killed
    for action in ("pause", "resume"):
        with pytest.raises(ValueError):
            restarted.change(
                action, expected_sha256=killed.sha256, config_hash=CONFIG, code_hash=CODE
            )
    with pytest.raises(ValueError), owner.permit(old):
        pytest.fail("Killed control cannot admit work")
    assert restarted.read() == killed


def test_transition_cannot_acknowledge_while_an_operation_holds_the_permit(tmp_path):
    owner, root = store(tmp_path)
    state, grant = active(owner)
    controller = module().StockResearchControls(root, clock=lambda: NOW)
    with owner.permit(grant):
        with pytest.raises(ValueError, match="stock_control_busy"):
            controller.change("pause", expected_sha256=state.sha256)
        assert controller.read().record.status == "running"
    paused = controller.change("pause", expected_sha256=state.sha256)
    assert paused.record.status == "paused"
    with pytest.raises(ValueError), owner.permit(grant):
        pytest.fail("Pause acknowledged before this new dispatch")


@pytest.mark.parametrize("kind", ["public", "symlink", "hardlink", "noncanonical", "oversized"])
def test_unsafe_state_blocks_without_repair(tmp_path, kind):
    owner, root = store(tmp_path)
    _, grant = active(owner)
    path = root / "stock-control.json"
    if kind == "public":
        path.chmod(0o644)
    elif kind == "symlink":
        path.rename(root / "unrelated")
        path.symlink_to(root / "unrelated")
    elif kind == "hardlink":
        os.link(path, root / "unrelated")
    elif kind == "noncanonical":
        path.write_bytes(path.read_bytes() + b" ")
    else:
        path.write_bytes(b"x" * 8193)
    with pytest.raises(ValueError):
        owner.read()
    with pytest.raises(ValueError), owner.permit(grant):
        pytest.fail("Unsafe state cannot admit a call")
    if kind == "public":
        assert path.stat().st_mode & 0o777 == 0o644


def test_clock_rollback_and_future_state_block(tmp_path):
    now = [NOW]
    owner, root = store(tmp_path, clock=lambda: now[0])
    state, grant = active(owner)
    now[0] -= timedelta(seconds=1)
    with pytest.raises(ValueError):
        owner.change("pause", expected_sha256=state.sha256)
    with pytest.raises(ValueError), owner.permit(grant):
        pass
    assert json.loads((root / "stock-control.json").read_text())["status"] == "running"


def test_failed_replacement_retains_previous_state_and_releases_mutex(tmp_path, monkeypatch):
    owner, _ = store(tmp_path)
    state, grant = active(owner)

    def fail(*args, **kwargs):
        raise OSError("private failure detail")

    with monkeypatch.context() as patch:
        patch.setattr(module().os, "replace", fail)
        with pytest.raises(ValueError) as denied:
            owner.change("pause", expected_sha256=state.sha256)
        assert str(denied.value) == "stock_control_denied"
    assert owner.read() == state
    with owner.permit(grant):
        pass
    assert owner.change("pause", expected_sha256=state.sha256).record.status == "paused"


def test_replaced_control_namespace_fences_captured_grant(tmp_path):
    owner, root = store(tmp_path)
    _, grant = active(owner)
    retained = root.with_name("retained")
    root.rename(retained)
    root.mkdir(mode=0o700)
    (root / "stock-control.json").write_bytes((retained / "stock-control.json").read_bytes())
    (root / "stock-control.json").chmod(0o600)
    (root / ".stock-control.lock").touch(mode=0o600)
    with pytest.raises(ValueError), owner.permit(grant):
        pytest.fail("New namespace must not inherit the old grant")


def test_unrelated_control_directory_entries_are_preserved_and_deny_initialization(tmp_path):
    owner, root = store(tmp_path)
    file = root / "unrelated"
    file.write_bytes(b"preserve")
    file.chmod(0o600)
    with pytest.raises(ValueError):
        owner.initialize()
    assert list(root.iterdir()) == [file]
    assert file.read_bytes() == b"preserve"


def test_failed_initialization_cannot_recreate_a_lost_running_control_anchor(tmp_path):
    owner, root = store(tmp_path)
    active(owner)
    anchor = root / ".stock-control.lock"
    anchor.unlink()
    with pytest.raises(ValueError):
        owner.initialize()
    assert not anchor.exists()
    with pytest.raises(ValueError):
        owner.read()
    with pytest.raises(ValueError):
        owner.grant(config_hash=CONFIG, code_hash=CODE)


def test_rejected_initialization_cannot_split_an_existing_dispatch_barrier(tmp_path):
    owner, root = store(tmp_path)
    state, grant = active(owner)
    with pytest.raises(ValueError), owner.permit(grant):
        anchor = root / ".stock-control.lock"
        anchor.unlink()
        with pytest.raises(ValueError):
            owner.initialize()
        assert not anchor.exists()
        with pytest.raises(ValueError):
            owner.change("pause", expected_sha256=state.sha256)


def test_permit_preserves_operation_failure_and_releases_the_barrier(tmp_path):
    owner, _ = store(tmp_path)
    state, grant = active(owner)
    with pytest.raises(RuntimeError, match="fictional operation failure"), owner.permit(grant):
        raise RuntimeError("fictional operation failure")
    assert owner.change("pause", expected_sha256=state.sha256).record.status == "paused"


def test_separate_process_cannot_acknowledge_pause_until_dispatch_barrier_releases(tmp_path):
    owner, root = store(tmp_path)
    state, grant = active(owner)
    script = """
import sys
from datetime import datetime
from pathlib import Path
from trading_bot.runtime import stock_research_controls as controls
owner = controls.StockResearchControls(
    Path(sys.argv[1]), clock=lambda: datetime.fromisoformat(sys.argv[3])
)
try:
    result = owner.change('pause', expected_sha256=sys.argv[2])
except controls.StockResearchControlError as exc:
    print(str(exc))
    raise SystemExit(2)
print(result.record.status)
"""
    with owner.permit(grant):
        busy = subprocess.run(
            [sys.executable, "-c", script, str(root), state.sha256, NOW.isoformat()],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    assert busy.returncode == 2 and busy.stdout.strip() == "stock_control_busy"
    paused = subprocess.run(
        [sys.executable, "-c", script, str(root), state.sha256, NOW.isoformat()],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert paused.returncode == 0 and paused.stdout.strip() == "paused"
    assert owner.read().record.status == "paused"


def test_failed_directory_fsync_never_acknowledges_a_transition(tmp_path, monkeypatch):
    import stat

    owner, _ = store(tmp_path)
    state, _ = active(owner)
    original = module().os.fsync

    def fail_directory(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("private filesystem failure")
        return original(descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(module().os, "fsync", fail_directory)
        with pytest.raises(ValueError, match="stock_control_denied"):
            owner.change("pause", expected_sha256=state.sha256)
    # Rename may have completed. Inspect actual state; never retry the old CAS blindly.
    assert owner.read().record.status == "paused"
    with pytest.raises(ValueError):
        owner.grant(config_hash=CONFIG, code_hash=CODE)
