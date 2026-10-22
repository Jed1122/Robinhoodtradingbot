"""Explicit operator controls; no SDK, broker credential or production ledger."""

import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from trading_bot.code_identity import CodeIdentity
from trading_bot.config import load_config
from trading_bot.domain import CodeHash
from trading_bot.runtime.stock_research_controls import StockResearchControls

ROOT = Path(__file__).resolve().parents[3]
IDENTITY = CodeIdentity(CodeHash("b" * 64), "a" * 40, False, None, False)


def module():
    try:
        return importlib.import_module("trading_bot.runtime.stock_research_control")
    except ModuleNotFoundError:
        pytest.fail("Explicit collector control commands are not implemented")


def args(root, action, state=None):
    result = ["--control-dir", str(root), action]
    if state is not None:
        result += ["--expected-state-sha256", state.sha256]
    return result


def test_initialize_status_and_pause_do_not_load_code_policy_or_credentials(
    tmp_path, monkeypatch, capsys
):
    cli = module()
    worker = importlib.import_module("trading_bot.runtime.stock_research_worker")
    monkeypatch.setattr(
        worker, "resolve_code_identity", lambda *a: pytest.fail("no identity needed")
    )
    root = tmp_path.resolve() / "controls"
    root.mkdir(mode=0o700)
    assert cli.main(args(root, "initialize")) == 0
    state = StockResearchControls(root).read()
    assert json.loads(capsys.readouterr().out)["control_status"] == "paused"
    assert cli.main(args(root, "status")) == 0
    assert json.loads(capsys.readouterr().out)["state_sha256"] == state.sha256
    assert cli.main(args(root, "pause", state)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["control_status"] == "paused" and result["live_enabled"] is False


@pytest.mark.parametrize("action", ["resume", "pause", "kill"])
def test_mutation_requires_explicit_expected_state_without_changing_files(tmp_path, capsys, action):
    cli = module()
    root = tmp_path.resolve() / "controls"
    root.mkdir(mode=0o700)
    owner = StockResearchControls(root)
    state = owner.initialize()
    assert cli.main(args(root, action)) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"
    assert owner.read() == state


def test_resume_uses_verified_current_identity_and_full_canonical_policy(
    tmp_path, monkeypatch, capsys
):
    cli = module()
    worker = importlib.import_module("trading_bot.runtime.stock_research_worker")
    monkeypatch.setattr(worker, "resolve_code_identity", lambda *a: IDENTITY)
    monkeypatch.setattr(worker, "RobinhoodMcpSdkConnection", lambda **kw: pytest.fail("no SDK"))
    root = tmp_path.resolve() / "controls"
    root.mkdir(mode=0o700)
    owner = StockResearchControls(root)
    state = owner.initialize()
    assert cli.main([*args(root, "resume", state), "--config-root", str(ROOT / "configs")]) == 0
    result = json.loads(capsys.readouterr().out)
    expected = load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/hybrid/paper.yaml",
        ROOT / "configs/hybrid/safety-envelope.yaml",
        {},
        hybrid_policy_path=ROOT / "configs/hybrid/policy.yaml",
        stock_research_policy_path=ROOT / "configs/hybrid/stock-research.yaml",
        stock_worker_policy_path=ROOT / "configs/hybrid/stock-worker.yaml",
    )
    assert result["control_status"] == "running"
    assert result["config_hash"] == str(expected.config_hash)
    assert result["code_hash"] == str(IDENTITY.code_hash)
    grant = owner.grant(config_hash=result["config_hash"], code_hash=result["code_hash"])
    with owner.permit(grant):
        pass
    monkeypatch.setattr(
        worker, "resolve_code_identity", lambda *a: pytest.fail("pause across builds")
    )
    assert cli.main(args(root, "kill", owner.read())) == 0
    assert json.loads(capsys.readouterr().out)["control_status"] == "killed"


@pytest.mark.parametrize(
    "changes", [{"dirty": True}, {"non_promotable": True}, {"git_commit": None}]
)
def test_unverified_code_cannot_resume(tmp_path, monkeypatch, capsys, changes):
    cli = module()
    worker = importlib.import_module("trading_bot.runtime.stock_research_worker")
    monkeypatch.setattr(worker, "resolve_code_identity", lambda *a: replace(IDENTITY, **changes))
    root = tmp_path.resolve() / "controls"
    root.mkdir(mode=0o700)
    owner = StockResearchControls(root)
    state = owner.initialize()
    assert cli.main([*args(root, "resume", state), "--config-root", str(ROOT / "configs")]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result == {"status": "blocked", "reason": "stock_control_denied", "live_enabled": False}
    assert owner.read() == state


def test_missing_control_directory_is_not_created_and_error_has_no_private_path(tmp_path, capsys):
    cli = module()
    root = tmp_path.resolve() / "missing"
    assert cli.main(args(root, "status")) == 2
    result = capsys.readouterr().out
    assert str(root) not in result and "live_enabled" in result
    assert not root.exists()
