"""Original joint fixture recovery, never broker or deployed-runtime evidence."""

import hashlib
import json
import os
import signal
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path

import pytest

from tests.unit.research.test_etf_capital_feasibility import loaded
from tests.unit.simulation.test_etf_capital_account import script
from tests.unit.simulation.test_etf_capital_action_account import action
from tests.unit.simulation.test_etf_capital_action_risk import run
from tests.unit.simulation.test_etf_capital_risk import point
from trading_bot.domain import OrderPurpose

REPOSITORY = Path(__file__).resolve().parents[3]


@pytest.fixture
def private_root(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    return root


def originals():
    events = (
        *script()[:5],
        action(ex_mark=D("80")),
        action(n=6, action_id="distribution-2", amount_per_share=D("0")),
    )
    return events, (point(0, 0), point(1, 6), point(2, 7))


def advance(root, count, expected_head=None, **changes):
    from trading_bot.persistence.etf_capital_checkpoint import advance_capital_joint_checkpoint

    events, observations = originals()
    arguments = dict(
        root=root,
        loaded=loaded(),
        initial_cash=D("100"),
        events=events,
        observations=observations,
        code_hash="c" * 64,
        repository_root=REPOSITORY,
        through_observation_count=count,
        expected_head=expected_head,
    )
    arguments.update(changes)
    return advance_capital_joint_checkpoint(**arguments)


def test_joint_restart_restores_atomic_nav_and_latched_original_loss(private_root):
    first = advance(private_root, 2)
    assert first.result.points[-1].equity == D("98.16")
    second = advance(private_root, 3, first.head_hash)
    current = second.result.points[-1]
    assert current.equity == D("99.96")
    assert current.account.distribution_receivable == D(".1")
    assert current.snapshot.daily_loss_pct == D("1.84")
    assert not current.decision.new_entries_allowed
    assert advance(private_root, 3, first.head_hash) == second
    assert second.result == run(*originals())
    assert second.sequence == 2
    assert not second.result.execution_enabled and not second.result.evidence_promotable


@pytest.mark.parametrize("change", ["mark", "reset", "code", "purpose", "capital"])
def test_altered_original_joint_owner_denies_without_publication(private_root, change):
    first = advance(private_root, 2)
    _events, observations = originals()
    changes = {
        "mark": {"observations": (*observations[:2], replace(observations[2], mark=D("97")))},
        "reset": {
            "observations": (
                replace(observations[0], weekly_reset_reviewed=False),
                *observations[1:],
            )
        },
        "code": {"code_hash": "d" * 64},
        "purpose": {"purpose": OrderPurpose.PROTECTIVE_EXIT},
        "capital": {"initial_cash": D("250")},
    }[change]
    directory = private_root / "capital-joint-checkpoints-v3"
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    with pytest.raises(ValueError):
        advance(private_root, 3, first.head_hash, **changes)
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before


def test_saved_loss_approval_or_cash_never_becomes_authority(private_root):
    first = advance(private_root, 2)
    path = next(private_root.rglob("*.capital-account-checkpoint.json"))
    row = json.loads(path.read_bytes())
    row["result"]["points"][-1]["equity"] = "1000"
    path.write_text(json.dumps(row))
    with pytest.raises(ValueError):
        advance(private_root, 3, first.head_hash)


def test_joint_schemas_private_modes_and_legacy_store_separation(private_root):
    legacy = private_root / "capital-account-checkpoints-v1"
    legacy.mkdir(mode=0o700)
    original = legacy / "owner.json"
    original.write_bytes(b"untouched historical evidence")
    original.chmod(0o600)
    advance(private_root, 2)
    directory = private_root / "capital-joint-checkpoints-v3"
    owner = json.loads((directory / "owner.json").read_bytes())
    row = json.loads(next(directory.glob("*.capital-account-checkpoint.json")).read_bytes())
    assert owner["schema"] == "capital-joint-owner-v3"
    assert row["schema"] == "capital-joint-checkpoint-v3"
    assert row["source_count"] == 2
    assert original.read_bytes() == b"untouched historical evidence"
    for path in directory.rglob("*"):
        assert path.stat().st_uid == os.getuid()
        assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)


@pytest.mark.parametrize("count", [0, True, 4, None])
def test_invalid_joint_prefix_denies_before_any_file_write(private_root, count):
    with pytest.raises(ValueError):
        advance(private_root, count)
    assert not tuple(private_root.iterdir())


def test_joint_stale_writer_and_backward_prefix_deny(private_root):
    first = advance(private_root, 1)
    advance(private_root, 2, first.head_hash)
    with pytest.raises(ValueError):
        advance(private_root, 3, first.head_hash)
    with pytest.raises(ValueError):
        advance(private_root, 1)


def test_verified_staging_is_retained_never_adopted(private_root):
    first = advance(private_root, 2)
    directory = private_root / "capital-joint-checkpoints-v3"
    owner = (directory / "owner.json").read_bytes()
    staging = directory / (".tmp-" + "e" * 32)
    staging.write_bytes(owner)
    staging.chmod(0o600)
    assert advance(private_root, 3, first.head_hash).sequence == 2
    assert staging.read_bytes() == owner


def test_external_alias_denies_joint_recovery(private_root, tmp_path):
    first = advance(private_root, 2)
    checkpoint = next(private_root.rglob("*.capital-account-checkpoint.json"))
    os.link(checkpoint, tmp_path / "external")
    with pytest.raises(ValueError):
        advance(private_root, 3, first.head_hash)


@pytest.mark.parametrize("after_link", [False, True])
def test_real_sigkill_joint_publication_reconstructs_original_latched_loss(
    private_root, after_link
):
    first = advance(private_root, 2)
    program = """
import os, signal, sys
from pathlib import Path
from tests.integration.persistence.test_etf_capital_joint_checkpoint import advance
import trading_bot.persistence.etf_capital_checkpoint
original = os.link
def interrupt(source, destination, **kwargs):
    if destination.endswith('.capital-account-checkpoint.json'):
        if sys.argv[2] == 'after':
            original(source, destination, **kwargs)
        os.kill(os.getpid(), signal.SIGKILL)
    return original(source, destination, **kwargs)
os.link = interrupt
advance(Path(sys.argv[1]), 3, sys.argv[3])
"""
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            program,
            str(private_root),
            "after" if after_link else "before",
            first.head_hash,
        ],
        cwd=REPOSITORY,
        check=False,
        capture_output=True,
        timeout=20,
    )
    assert process.returncode == -signal.SIGKILL, process.stderr.decode()
    restored = advance(private_root, 3)
    assert restored.sequence == 2
    assert restored.result.points[-1].equity == D("99.96")
    assert restored.result.points[-1].snapshot.daily_loss_pct == D("1.84")
    assert not restored.result.points[-1].decision.new_entries_allowed
    assert advance(private_root, 3, first.head_hash) == restored


def test_unknown_staging_never_becomes_joint_state(private_root):
    first = advance(private_root, 2)
    directory = private_root / "capital-joint-checkpoints-v3"
    staging = directory / (".tmp-" + "e" * 32)
    staging.write_bytes(b"unverified joint state")
    staging.chmod(0o600)
    with pytest.raises(ValueError):
        advance(private_root, 3, first.head_hash)
    assert len(tuple(directory.glob("*.capital-account-checkpoint.json"))) == 1


def test_bounded_joint_input_denies_before_storage_mutation(private_root, monkeypatch):
    import trading_bot.persistence.etf_capital_checkpoint as module

    monkeypatch.setattr(module, "_MAX_BYTES", 1024)
    with pytest.raises(ValueError):
        advance(private_root, 2)
    assert not tuple(private_root.iterdir())


def test_legacy_v2_envelope_hash_remains_equal_to_certified_original():
    from trading_bot.persistence.etf_capital_checkpoint import _body
    from trading_bot.simulation.etf_capital_account import replay_capital_account

    result = replay_capital_account(initial_cash=D("100"), events=script()[:3])
    original = _body("a" * 64, 1, "0" * 64, 3, result)
    assert hashlib.sha256(original).hexdigest() == (
        "9b968e7826cbf63578be4e61605e07a4110999c3104322781e6af6e09eab7d07"
    )
