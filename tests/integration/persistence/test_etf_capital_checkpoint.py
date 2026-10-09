"""Private synthetic prefix checkpoints; no customer records or broker calls."""

import json
import os
import signal
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from tests.unit.research.test_etf_capital_feasibility import loaded
from tests.unit.simulation.test_etf_capital_account import replay, script

REPOSITORY = Path(__file__).resolve().parents[3]
CODE_HASH = "c" * 64  # Declared fixture identity, not verified executable evidence.


def advance(root, count, expected_head=None, **changes):
    from trading_bot.persistence.etf_capital_checkpoint import advance_capital_account_checkpoint

    arguments = dict(
        root=root,
        loaded=loaded(),
        initial_cash=Decimal("100"),
        events=script(),
        code_hash=CODE_HASH,
        repository_root=REPOSITORY,
        through_count=count,
        expected_head=expected_head,
    )
    arguments.update(changes)
    return advance_capital_account_checkpoint(**arguments)


@pytest.fixture
def private_root(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    return root


def test_partial_unsettled_and_final_prefixes_restore_exactly(private_root):
    partial = advance(private_root, 3)
    assert partial.result == replay(script()[:3])
    assert advance(private_root, 3, partial.head_hash) == partial
    unsettled = advance(private_root, 8, partial.head_hash)
    assert unsettled.result.cash == Decimal("100.11")
    assert unsettled.result.unsettled_proceeds == Decimal("10.05")
    assert not unsettled.result.complete
    final = advance(private_root, 10, unsettled.head_hash)
    assert final.result == replay(script())
    assert final.sequence == 3
    assert advance(private_root, 10, final.head_hash) == final


def test_old_head_and_backward_count_cannot_advance(private_root):
    first = advance(private_root, 3)
    advance(private_root, 8, first.head_hash)
    for count, head in ((10, first.head_hash), (2, None)):
        with pytest.raises(ValueError):
            advance(private_root, count, head)


def test_exact_retry_accepts_original_compare_and_swap_head(private_root):
    first = advance(private_root, 3)
    second = advance(private_root, 8, first.head_hash)
    assert advance(private_root, 8, first.head_hash) == second


@pytest.mark.parametrize(
    "payload", [b"not a verified publication", b"[]", b'{"sequence":true,"source_count":8}']
)
def test_unverified_internal_staging_bytes_deny_without_adoption(private_root, payload):
    first = advance(private_root, 3)
    directory = next(private_root.iterdir())
    descriptor = os.open(
        directory / (".tmp-" + "e" * 32), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
    )
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)
    with pytest.raises(ValueError):
        advance(private_root, 8, first.head_hash)
    assert len(tuple(directory.glob("*.capital-account-checkpoint.json"))) == 1


def test_verified_owner_staging_is_retained_without_becoming_state(private_root):
    first = advance(private_root, 3)
    directory = next(private_root.iterdir())
    owner = (directory / "owner.json").read_bytes()
    staging = directory / (".tmp-" + "e" * 32)
    descriptor = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, owner)
    finally:
        os.close(descriptor)
    second = advance(private_root, 8, first.head_hash)
    assert second.sequence == 2
    assert staging.read_bytes() == owner
    assert advance(private_root, 8, first.head_hash) == second


def test_source_code_and_capital_identity_cannot_change_after_publication(private_root):
    first = advance(private_root, 3)
    events = script()
    altered = replace(events[-1], total_fees=Decimal(".08"))
    for change in (
        {"code_hash": "d" * 64},
        {"events": (*events[:-1], altered)},
        {"initial_cash": Decimal("250")},
    ):
        with pytest.raises(ValueError):
            advance(private_root, 8, first.head_hash, **change)


def test_corrupt_checkpoint_cannot_supply_restored_balances(private_root):
    first = advance(private_root, 3)
    files = tuple(private_root.rglob("*.capital-account-checkpoint.json"))
    assert len(files) == 1
    body = json.loads(files[0].read_text())
    body["result"]["cash"] = "999"
    files[0].write_text(json.dumps(body))
    with pytest.raises(ValueError):
        advance(private_root, 8, first.head_hash)


@pytest.mark.parametrize("count", [-1, True, 11, None])
def test_invalid_prefix_bound_denies_before_publication(private_root, count):
    with pytest.raises(ValueError):
        advance(private_root, count)


def test_repository_cannot_be_private_checkpoint_destination():
    with pytest.raises(ValueError):
        advance(REPOSITORY, 3)


def test_checkpoint_external_hardlink_is_not_adopted(private_root, tmp_path):
    first = advance(private_root, 3)
    checkpoint = next(private_root.rglob("*.capital-account-checkpoint.json"))
    os.link(checkpoint, tmp_path / "external-alias")
    with pytest.raises(ValueError):
        advance(private_root, 8, first.head_hash)


def test_unknown_staging_and_symlink_fail_closed(private_root, tmp_path):
    first = advance(private_root, 3)
    directory = next(private_root.iterdir())
    (directory / "unexpected").symlink_to(tmp_path)
    with pytest.raises(ValueError):
        advance(private_root, 8, first.head_hash)


def test_owner_configuration_and_false_flags_cannot_be_rewritten(private_root):
    first = advance(private_root, 3)
    owner = next(private_root.rglob("owner.json"))
    row = json.loads(owner.read_text())
    row["execution_enabled"] = True
    owner.write_text(json.dumps(row))
    with pytest.raises(ValueError):
        advance(private_root, 8, first.head_hash)


@pytest.mark.parametrize("payload", [[], {"source_count": True}])
def test_invalid_persisted_structure_is_not_reconstructed(private_root, payload):
    first = advance(private_root, 3)
    checkpoint = next(private_root.rglob("*.capital-account-checkpoint.json"))
    checkpoint.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        advance(private_root, 8, first.head_hash)


def test_initial_owner_and_checkpoint_capacity_reserved_before_either_write(private_root):
    seed = private_root.parent / "seed"
    seed.mkdir(mode=0o700)
    advance(seed, 3)
    owner = next(seed.rglob("owner.json")).read_bytes()
    directory = private_root / "capital-account-checkpoints-v1"
    directory.mkdir(mode=0o700)
    for index in range(8193):
        path = directory / f".tmp-{index:032x}"
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, owner)
        finally:
            os.close(descriptor)
    with pytest.raises(ValueError):
        advance(private_root, 3)
    assert not (directory / "owner.json").exists()
    assert not tuple(directory.glob("*.capital-account-checkpoint.json"))


def test_checkpoint_private_modes_and_literal_cash_accounting(private_root):
    final = advance(private_root, 10)
    assert final.result.cash == Decimal("100.11")
    assert final.result.available_cash == Decimal("100.11")
    assert final.result.fees == Decimal(".09")
    assert final.result.quantity == Decimal("0")
    assert final.result.unsettled_proceeds == Decimal("0")
    assert final.result.complete
    assert not final.result.execution_enabled
    assert not final.result.evidence_promotable
    for path in private_root.rglob("*"):
        assert path.stat().st_uid == os.getuid()
        assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)


@pytest.mark.parametrize("after_link", [False, True])
def test_real_sigkill_publication_restores_only_complete_prefix(private_root, after_link):
    first = advance(private_root, 3)
    program = """
import os, signal, sys
from pathlib import Path
from tests.integration.persistence.test_etf_capital_checkpoint import advance
import trading_bot.persistence.etf_capital_checkpoint
original = os.link
def interrupt(source, destination, **kwargs):
    if destination.endswith('.capital-account-checkpoint.json'):
        if sys.argv[2] == 'after':
            original(source, destination, **kwargs)
        os.kill(os.getpid(), signal.SIGKILL)
    return original(source, destination, **kwargs)
os.link = interrupt
advance(Path(sys.argv[1]), 8, sys.argv[3])
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
    restored = advance(private_root, 8)
    assert restored.sequence == 2
    assert restored.result.cash == Decimal("100.11")
    assert restored.result.unsettled_proceeds == Decimal("10.05")
    assert restored.result.available_cash == Decimal("90.05")
    assert not restored.result.complete
    assert advance(private_root, 8, restored.head_hash) == restored
