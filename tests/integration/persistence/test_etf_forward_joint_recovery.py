"""Real private-filesystem joint commits, restart, fences and injected faults."""

import fcntl
import hashlib
import importlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from tests.unit.runtime.test_etf_forward_paper import tape
from trading_bot.market_data.recording import content_hash
from trading_bot.runtime.etf_forward_paper import ForwardPaperCycle, replay_forward_paper
from trading_bot.simulation.etf_account import EtfAccountEvent
from trading_bot.simulation.etf_history import _policy

GENESIS = "0" * 64
REPO = Path(__file__).parents[3]
NAMESPACE = "etf-forward-paper-owner-v1"


def api():
    try:
        return importlib.import_module("trading_bot.persistence.etf_forward_paper")
    except ModuleNotFoundError:
        pytest.fail("atomic joint forward paper owner is missing")


@pytest.fixture
def private(tmp_path):
    root = tmp_path / "paper"
    root.mkdir(mode=0o700)
    return root


def advance(root, request, head=GENESIS):
    return api().advance_forward_paper(root, request, repository_root=REPO, expected_head=head)


def recover(root, request, head):
    return api().recover_forward_paper(root, request, repository_root=REPO, expected_head=head)


def test_each_prefix_restores_joint_economics_and_source_not_just_cash(private):
    request = tape()
    head = GENESIS
    for count in range(1, len(request.cycles) + 1):
        prefix = replace(request, cycles=request.cycles[:count])
        stored = advance(private, prefix, head)
        restored = recover(private, request, stored.head_hash)
        assert stored.state == restored.state == replay_forward_paper(prefix)
        assert restored.sequence == count
        head = stored.head_hash
    assert (
        stored.state.account.cash.as_tuple()
        == replay_forward_paper(request).account.cash.as_tuple()
    )
    assert stored.state.account.trial.consumed_loss == Decimal(".12")
    assert stored.state.account.complete and not stored.state.qualifying_paper


def test_source_only_cycle_preserves_independent_account_watermark(private):
    request = tape()
    prefix = replace(request, cycles=request.cycles[:2])
    before = advance(private, prefix)
    last = prefix.cycles[-1]
    observed = ForwardPaperCycle(
        last.at_ns + 1,
        last.received_monotonic_ns + 1,
        content_hash("denied-source"),
        last.strategy_state_hash,
        (),
    )
    updated = replace(prefix, cycles=(*prefix.cycles, observed))
    after = advance(private, updated, before.head_hash)
    assert after.state.account == before.state.account
    assert after.state.source_cursor != before.state.source_cursor
    assert recover(private, updated, after.head_hash) == after


def test_idempotent_same_prefix_and_future_suffix_stability(private):
    request = tape()
    prefix = replace(request, cycles=request.cycles[:2])
    before = advance(private, prefix)
    assert advance(private, prefix) == before  # Exact response-loss retry, no new effect.
    changed_future = replace(request.cycles[-1], source_hash=content_hash("later-future"))
    extended = replace(request, cycles=(*request.cycles[:-1], changed_future))
    assert recover(private, extended, before.head_hash) == before
    after = advance(private, extended, before.head_hash)
    assert after.sequence == 2 and before.sequence == 1
    assert recover(private, extended, after.head_hash) == after


def test_shortened_conflicting_stale_or_changed_owner_denies_without_mutation(private):
    request = tape()
    prefix = replace(request, cycles=request.cycles[:2])
    before = advance(private, prefix)
    paths = sorted((private / NAMESPACE).glob("*"))
    original = {p.name: p.read_bytes() for p in paths}
    with pytest.raises(ValueError):
        advance(private, request)  # Genesis is stale for a genuinely new suffix.
    with pytest.raises(ValueError):
        recover(private, prefix, GENESIS)
    with pytest.raises(ValueError):
        advance(private, replace(prefix, cycles=prefix.cycles[:1]), before.head_hash)
    conflict = replace(prefix.cycles[0], strategy_state_hash=content_hash("conflicting-policy"))
    with pytest.raises(ValueError):
        advance(private, replace(prefix, cycles=(conflict, prefix.cycles[1])), before.head_hash)
    with pytest.raises(ValueError):
        advance(
            private,
            replace(prefix, plan=replace(prefix.plan, initial_cash=prefix.plan.initial_cash * 2)),
            before.head_hash,
        )
    assert {p.name: p.read_bytes() for p in paths} == original


def test_pending_pre_effect_claim_is_quarantined_and_not_reclaimed(private, monkeypatch):
    module = api()
    publish = module._publish

    def fail_commit(directory, name, body):
        if name.endswith(".joint.json"):
            raise OSError("fictional disk unavailable")
        publish(directory, name, body)

    monkeypatch.setattr(module, "_publish", fail_commit)
    with pytest.raises(ValueError, match="forward_paper_store_invalid"):
        advance(private, tape())
    monkeypatch.setattr(module, "_publish", publish)
    for operation in (advance, recover):
        with pytest.raises(module.ForwardPaperRecoveryRequired):
            operation(private, tape(), GENESIS)
    assert len(list((private / NAMESPACE).glob("*.claim.json"))) == 1
    assert not list((private / NAMESPACE).glob("*.joint.json"))


def test_fully_published_state_survives_uncertain_sync_response(private, monkeypatch):
    module = api()
    publish = module._publish

    def uncertain(directory, name, body):
        publish(directory, name, body)
        if name.endswith(".joint.json"):
            raise OSError("fictional post-publication sync failure")

    monkeypatch.setattr(module, "_publish", uncertain)
    with pytest.raises(ValueError):
        advance(private, tape())
    monkeypatch.setattr(module, "_publish", publish)
    path = next((private / NAMESPACE).glob("*.joint.json"))
    head = hashlib.sha256(path.read_bytes()).hexdigest()
    restored = recover(private, tape(), head)
    assert advance(private, tape()) == restored
    assert restored.sequence == 1 and restored.state.account.cash == Decimal("499.88")


@pytest.mark.parametrize(
    "damage",
    [
        "corrupt",
        "missing_commit",
        "missing_owner",
        "forged_state",
        "unknown_file",
        "unsafe_mode",
        "hardlink",
    ],
)
def test_joint_restore_rejects_partial_loss_corruption_and_rehashed_cash(private, damage):
    request = tape()
    stored = advance(private, request)
    directory = private / NAMESPACE
    joint = next(directory.glob("*.joint.json"))
    if damage == "corrupt":
        joint.write_bytes(b"{}")
    elif damage == "missing_commit":
        joint.unlink()
    elif damage == "missing_owner":
        (directory / "owner.json").unlink()
    elif damage == "forged_state":
        row = json.loads(joint.read_bytes())
        row["state"]["account"]["cash"] = "999.99"
        joint.write_text(json.dumps(row))
    elif damage == "unknown_file":
        (directory / "unreviewed.json").write_bytes(b"{}")
    elif damage == "unsafe_mode":
        joint.chmod(0o644)
    elif damage == "hardlink":
        os.link(joint, private / "linked")
    with pytest.raises((ValueError, api().ForwardPaperRecoveryRequired)):
        recover(private, request, stored.head_hash)


def test_missing_intermediate_joint_and_claim_deny_against_external_head(private):
    request = tape()
    one = advance(private, replace(request, cycles=request.cycles[:1]))
    two = advance(private, request, one.head_hash)
    (private / NAMESPACE / "00000001.joint.json").unlink()
    (private / NAMESPACE / "00000001.claim.json").unlink()
    with pytest.raises(ValueError):
        recover(private, request, two.head_hash)


def test_nonwaiting_owner_and_escaped_symlink_or_repository_root_deny(private, tmp_path):
    advance(private, tape())
    with (private / NAMESPACE / "writer.lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(api().ForwardPaperWriterBusy):
            advance(private, tape())
    linked = tmp_path / "linked-root"
    linked.symlink_to(private, target_is_directory=True)
    with pytest.raises(ValueError):
        advance(linked, tape())
    with pytest.raises(ValueError):
        api().advance_forward_paper(private, tape(), repository_root=private, expected_head=GENESIS)
    assert (private / NAMESPACE).stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in (private / NAMESPACE).iterdir())


def test_recovery_in_a_new_process_is_paused_and_does_not_advance(private):
    request = tape()
    stored = advance(private, replace(request, cycles=request.cycles[:3]))
    code = """
import sys
from pathlib import Path
from tests.unit.runtime.test_etf_forward_paper import tape
from trading_bot.persistence.etf_forward_paper import recover_forward_paper
r = recover_forward_paper(
    Path(sys.argv[1]), tape(), repository_root=Path.cwd(), expected_head=sys.argv[2]
)
assert r.state.cycle_count == 3 and r.state.paused and not r.state.qualifying_paper
assert str(r.state.account.cash) == '489.99'
print(r.head_hash)
"""
    process = subprocess.run(
        [sys.executable, "-c", code, str(private), stored.head_hash],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert process.stdout.strip() == stored.head_hash
    assert len(list((private / NAMESPACE).glob("*.joint.json"))) == 1


@pytest.mark.parametrize("when", ["before", "after"])
def test_actual_process_kill_preserves_prior_or_complete_joint_publication(private, when):
    code = """
import os, signal, sys
from pathlib import Path
from tests.unit.runtime.test_etf_forward_paper import tape
import trading_bot.persistence.etf_forward_paper as owner
publish = owner._publish
def killed(directory, name, body):
    if name.endswith('.joint.json') and sys.argv[2] == 'before':
        os.kill(os.getpid(), signal.SIGKILL)
    publish(directory, name, body)
    if name.endswith('.joint.json'):
        os.kill(os.getpid(), signal.SIGKILL)
owner._publish = killed
owner.advance_forward_paper(
    Path(sys.argv[1]), tape(), repository_root=Path.cwd(), expected_head='0' * 64
)
"""
    process = subprocess.run(
        [sys.executable, "-c", code, str(private), when],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == -9
    if when == "before":
        with pytest.raises(api().ForwardPaperRecoveryRequired):
            recover(private, tape(), GENESIS)
    else:
        joint = next((private / NAMESPACE).glob("*.joint.json"))
        head = hashlib.sha256(joint.read_bytes()).hexdigest()
        state = recover(private, tape(), head)
        assert state.state.account.cash == Decimal("499.88")
        assert state.state.account.trial.consumed_loss == Decimal(".12")
        assert not state.state.qualifying_paper


@pytest.mark.parametrize("target", ["owner.json", ".claim.json", ".joint.json"])
@pytest.mark.parametrize("synchronized", [False, True])
def test_kill_between_publication_link_and_staging_unlink(private, target, synchronized):
    code = """
import os, signal, sys
from pathlib import Path
from tests.unit.runtime.test_etf_forward_paper import tape
from trading_bot.persistence.etf_forward_paper import advance_forward_paper
original = os.link
def killed(source, destination, **kwargs):
    original(source, destination, **kwargs)
    if destination.endswith(sys.argv[2]):
        if sys.argv[3] == 'True':
            os.fsync(kwargs['dst_dir_fd'])
        os.kill(os.getpid(), signal.SIGKILL)
os.link = killed
advance_forward_paper(
    Path(sys.argv[1]), tape(), repository_root=Path.cwd(), expected_head='0' * 64
)
"""
    process = subprocess.run(
        [sys.executable, "-c", code, str(private), target, str(synchronized)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == -9
    directory = private / NAMESPACE
    aliases = list(directory.glob(".tmp-*"))
    assert len(aliases) == 1 and aliases[0].stat().st_nlink == 2
    if target == ".claim.json":
        for operation in (advance, recover):
            with pytest.raises(api().ForwardPaperRecoveryRequired):
                operation(private, tape(), GENESIS)
        assert not list(directory.glob("*.joint.json"))
    elif target == "owner.json":
        empty = recover(private, tape(), GENESIS)
        assert empty.sequence == 0 and empty.state.paused
        stored = advance(private, tape())
        assert stored.state == replay_forward_paper(tape())
    else:
        joint = next(directory.glob("*.joint.json"))
        head = hashlib.sha256(joint.read_bytes()).hexdigest()
        restored = recover(private, tape(), head)
        assert restored.state == replay_forward_paper(tape())
        assert advance(private, tape()) == restored
    # Recognized aliases are retained, never adopted as independent economic effects.
    assert aliases[0].exists() and aliases[0].stat().st_nlink == 2


@pytest.mark.parametrize("damage", ["extra_alias", "two_final_names", "outside_alias"])
def test_unexplained_multilinks_remain_denied(private, damage):
    stored = advance(private, tape())
    directory = private / NAMESPACE
    joint = next(directory.glob("*.joint.json"))
    if damage != "outside_alias":
        name = ".tmp-" + "a" * 32 if damage == "extra_alias" else "00000002.joint.json"
        os.link(joint, directory / name)
    if damage != "two_final_names":
        os.link(joint, private / "external-link")
    with pytest.raises(ValueError):
        recover(private, tape(), stored.head_hash)


@pytest.mark.parametrize("second", [".tmp-" + "b" * 32, "unrecognized.json"])
def test_two_staging_aliases_or_unrecognized_final_are_never_adopted(private, second):
    directory = private / NAMESPACE
    directory.mkdir(mode=0o700)
    orphan = directory / (".tmp-" + "a" * 32)
    orphan.write_bytes(b"not an economic commit")
    orphan.chmod(0o600)
    os.link(orphan, directory / second)
    with pytest.raises(ValueError):
        advance(private, tape())
    assert not list(directory.glob("*.joint.json"))


def test_legacy_namespaces_are_not_read_or_modified_and_bad_head_is_sanitized(private):
    legacy = private / "paper-cycle-journal-v1"
    legacy.mkdir(mode=0o700)
    marker = legacy / "unresolved-legacy-claim.json"
    marker.write_bytes(b"do not adopt or modify")
    marker.chmod(0o600)
    stored = advance(private, tape())
    assert marker.read_bytes() == b"do not adopt or modify"
    with pytest.raises(ValueError, match="forward_paper_store_invalid"):
        recover(private, tape(), "private-invalid-value")
    assert recover(private, tape(), stored.head_hash) == stored


def test_empty_state_and_current_head_retries_are_not_new_cycles(private):
    request = tape(())
    empty = advance(private, request)
    assert empty.sequence == 0 and empty.head_hash == GENESIS
    assert recover(private, request, GENESIS) == empty
    stored = advance(private, tape(), GENESIS)
    assert advance(private, tape(), stored.head_hash) == stored


def test_interrupted_staging_file_is_verified_but_never_adopted(private):
    directory = private / NAMESPACE
    directory.mkdir(mode=0o700)
    staging = directory / (".tmp-" + "a" * 32)
    staging.write_bytes(b"interrupted private staging")
    staging.chmod(0o600)
    stored = advance(private, tape())
    assert stored.sequence == 1 and staging.read_bytes() == b"interrupted private staging"
    assert recover(private, tape(), stored.head_hash) == stored


def test_retained_crash_aliases_fit_the_whole_owner_lifetime(private, monkeypatch):
    # Scale the journal lifetime to eight commits: all publication/recovery is real.
    # The old 2*N+16 bound fails at 18 final files + 15 recognized aliases = 33.
    monkeypatch.setattr(api(), "MAX_CYCLES", 8)
    request = tape()
    head = GENESIS
    for count in range(1, 9):
        stored = advance(private, replace(request, cycles=request.cycles[:count]), head)
        head = stored.head_hash
    directory = private / NAMESPACE
    final_names = ["owner.json"] + [
        f"{sequence:08d}.{kind}.json"
        for sequence in range(1, 8)
        for kind in ("claim", "joint")
    ]
    aliases = []
    for index, name in enumerate(final_names):
        alias = directory / f".tmp-{index:032x}"
        os.link(directory / name, alias)
        aliases.append(alias)
    assert len(list(directory.iterdir())) == 33
    restored = recover(private, request, head)
    assert restored.sequence == 8 and restored.state.account.cash == Decimal("499.88")
    assert restored.state.account.trial.consumed_loss == Decimal(".12")
    assert not restored.state.qualifying_paper
    assert all(alias.stat().st_nlink == 2 for alias in aliases)


def test_large_admitted_duplicate_tape_roundtrips_without_extra_effects(private):
    request = tape()
    first = request.cycles[0]
    bounded = replace(request, cycles=(replace(first, events=first.events * 4000),))
    stored = advance(private, bounded)
    assert recover(private, bounded, stored.head_hash) == stored
    assert stored.state.account.cash == Decimal("500")
    assert stored.state.account.reserved_cash == Decimal("10.02")
    assert stored.state.account.event_count == 1 and stored.sequence == 1
    assert not stored.state.execution_enabled and not stored.state.evidence_promotable


def test_wire_identity_is_unchanged_by_shared_byte_budget(private):
    stored = advance(private, tape())
    assert stored.head_hash == "fe7f58acfd6e5d790be817667a22801861018350fd9eacbc96b4ffce1b8abe67"


def test_unlinked_staging_entries_remain_resource_bounded(private, monkeypatch):
    monkeypatch.setattr(api(), "MAX_CYCLES", 8)
    stored = advance(private, tape())
    directory = private / NAMESPACE
    for index in range(45):
        staging = directory / f".tmp-{index:032x}"
        staging.write_bytes(b"unlinked interrupted staging")
        staging.chmod(0o600)
    assert len(list(directory.iterdir())) == 49
    with pytest.raises(ValueError, match="forward_paper_store_invalid"):
        recover(private, tape(), stored.head_hash)


@pytest.mark.parametrize("staging_count", [42, 43, 44])
def test_near_capacity_append_denies_before_claim_and_preserves_previous_head(
    private, monkeypatch, staging_count
):
    monkeypatch.setattr(api(), "MAX_CYCLES", 8)
    request = tape()
    first = advance(private, replace(request, cycles=request.cycles[:1]))
    directory = private / NAMESPACE
    for index in range(staging_count):
        staging = directory / f".tmp-{index:032x}"
        staging.write_bytes(b"unlinked interrupted staging")
        staging.chmod(0o600)
    original = {path.name: path.read_bytes() for path in directory.iterdir()}
    assert recover(private, request, first.head_hash) == first
    with pytest.raises(ValueError, match="forward_paper_store_invalid"):
        advance(private, replace(request, cycles=request.cycles[:2]), first.head_hash)
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == original
    assert recover(private, request, first.head_hash) == first


@pytest.mark.parametrize("staging_count", [46, 47])
def test_near_capacity_genesis_denies_before_owner_publication(
    private, monkeypatch, staging_count
):
    monkeypatch.setattr(api(), "MAX_CYCLES", 8)
    directory = private / NAMESPACE
    directory.mkdir(mode=0o700)
    for index in range(staging_count):
        staging = directory / f".tmp-{index:032x}"
        staging.write_bytes(b"unlinked interrupted staging")
        staging.chmod(0o600)
    with pytest.raises(ValueError, match="forward_paper_store_invalid"):
        recover(private, tape(), GENESIS)
    assert not (directory / "owner.json").exists()
    assert not list(directory.glob("*.claim.json"))
    assert len(list(directory.glob(".tmp-*"))) == staging_count


@pytest.mark.parametrize("target", ["owner.json", "00000002.joint.json"])
@pytest.mark.parametrize("synchronized", [False, True])
def test_near_capacity_publication_crash_remains_recoverable(
    private, monkeypatch, target, synchronized
):
    monkeypatch.setattr(api(), "MAX_CYCLES", 8)
    request = tape()
    if target == "owner.json":
        directory = private / NAMESPACE
        directory.mkdir(mode=0o700)
        first_head = GENESIS
        staging_count = 45  # + lock + marker + retained alias = 48
    else:
        first = advance(private, replace(request, cycles=request.cycles[:1]))
        directory = private / NAMESPACE
        first_head = first.head_hash
        staging_count = 41  # + four existing files + claim/joint/alias = 48
    for index in range(staging_count):
        staging = directory / f".tmp-{index:032x}"
        staging.write_bytes(b"unlinked interrupted staging")
        staging.chmod(0o600)
    code = """
import os, signal, sys
from dataclasses import replace
from pathlib import Path
from tests.unit.runtime.test_etf_forward_paper import tape
import trading_bot.persistence.etf_forward_paper as owner
owner.MAX_CYCLES = 8
original = os.link
def killed(source, destination, **kwargs):
    original(source, destination, **kwargs)
    if destination == sys.argv[2]:
        if sys.argv[3] == 'True':
            os.fsync(kwargs['dst_dir_fd'])
        os.kill(os.getpid(), signal.SIGKILL)
os.link = killed
request = tape()
if sys.argv[2] == 'owner.json':
    owner.recover_forward_paper(
        Path(sys.argv[1]), request, repository_root=Path.cwd(), expected_head=sys.argv[4]
    )
else:
    owner.advance_forward_paper(
        Path(sys.argv[1]), replace(request, cycles=request.cycles[:2]),
        repository_root=Path.cwd(), expected_head=sys.argv[4]
    )
"""
    process = subprocess.run(
        [sys.executable, "-c", code, str(private), target, str(synchronized), first_head],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == -9 and len(list(directory.iterdir())) == 48
    if target == "owner.json":
        restored = recover(private, request, GENESIS)
        assert restored.sequence == 0 and restored.state.account.cash == Decimal("500")
    else:
        head = hashlib.sha256((directory / target).read_bytes()).hexdigest()
        restored = recover(private, request, head)
        assert restored.sequence == 2 and restored.state.account.cash == Decimal("489.99")
        assert restored.state.account.trial.reserved_risk == Decimal("10.02")
    assert restored.state.paused and not restored.state.qualifying_paper
    assert len(list(directory.iterdir())) == 48


def test_boolean_cycle_count_in_joint_json_denies(private):
    request = tape()
    stored = advance(private, request)
    joint = next((private / NAMESPACE).glob("*.joint.json"))
    row = json.loads(joint.read_bytes())
    row["cycle_count"] = True
    joint.write_text(json.dumps(row))
    with pytest.raises(ValueError):
        recover(private, request, stored.head_hash)


def test_changed_build_identity_cannot_reuse_owned_economic_state(private):
    request = tape()
    stored = advance(private, request)
    changed_policy = replace(
        request.plan.policy, policy=_policy(request.plan.policy), code_hash="d" * 64
    )
    changed = replace(request, plan=replace(request.plan, policy=changed_policy))
    with pytest.raises(ValueError):
        recover(private, changed, stored.head_hash)


def test_drawdown_and_weekly_latches_reconstruct_across_next_day_restart(private):
    request = tape()
    first = replace(request, cycles=request.cycles[:3])
    last = first.cycles[-1]
    adverse = EtfAccountEvent(
        content_hash("adverse"), 3, last.at_ns + 1_000_000_000, "mark", mark_price=Decimal(".01")
    )
    cycle = ForwardPaperCycle(
        adverse.at_ns,
        last.received_monotonic_ns + 1_000_000_000,
        content_hash("adverse-source"),
        content_hash("held-policy"),
        (adverse,),
    )
    marked = replace(first, cycles=(*first.cycles, cycle))
    stored = advance(private, marked)
    assert stored.state.account.entry_halted and not stored.state.account.complete
    assert stored.state.account.trial.reserved_risk == Decimal("10.02")
    next_day = replace(
        adverse,
        event_id=content_hash("next-day"),
        ordinal=4,
        at_ns=adverse.at_ns + int(timedelta(days=1).total_seconds()) * 1_000_000_000,
        mark_price=Decimal("100"),
    )
    later = replace(
        cycle,
        at_ns=next_day.at_ns,
        received_monotonic_ns=cycle.received_monotonic_ns + 86_400_000_000_000,
        source_hash=content_hash("later-source"),
        events=(next_day,),
    )
    restored = recover(private, replace(marked, cycles=(*marked.cycles, later)), stored.head_hash)
    assert restored == stored
    advanced = advance(private, replace(marked, cycles=(*marked.cycles, later)), stored.head_hash)
    assert advanced.state.account.entry_halted  # Positive mark cannot clear latched losses.
    assert (
        recover(private, replace(marked, cycles=(*marked.cycles, later)), advanced.head_hash)
        == advanced
    )
