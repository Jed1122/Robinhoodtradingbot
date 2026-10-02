"""Immutable paper claims cannot turn unknown effects into retry authority."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trading_bot.persistence.paper_cycle_journal import (
    PaperCycleClaim,
    PaperCycleJournal,
    PaperCycleJournalError,
    PaperCycleRecoveryRequired,
)

ROOT = Path(__file__).parents[3]
NOW = datetime(2026, 10, 2, tzinfo=UTC)


def journal(tmp_path):
    tmp_path.chmod(0o700)
    return PaperCycleJournal(tmp_path, repository_root=ROOT)


def test_pending_and_completed_claims_reconstruct_with_exact_hashes(tmp_path):
    first = journal(tmp_path)
    assert first.inspect("a" * 64, "b" * 64) == (None, None)
    claim = first.begin("a" * 64, "b" * 64, NOW)
    assert first.inspect(claim.cycle_id, claim.context_hash) == (claim, None)
    with pytest.raises(PaperCycleRecoveryRequired):
        first.begin(claim.cycle_id, claim.context_hash, NOW)
    first.complete(claim, "c" * 64)
    first.complete(claim, "c" * 64)
    fresh = journal(tmp_path)
    assert fresh.inspect("a" * 64, "b" * 64) == (claim, "c" * 64)
    with pytest.raises(PaperCycleJournalError):
        fresh.complete(claim, "d" * 64)


@pytest.mark.parametrize(
    "field,value",
    [
        ("cycle_id", "not-a-digest"),
        ("context_hash", True),
        ("started_at", NOW.replace(tzinfo=None)),
    ],
)
def test_invalid_claims_fail_before_persistence(tmp_path, field, value):
    store = journal(tmp_path)
    args = {"cycle_id": "a" * 64, "context_hash": "b" * 64, "started_at": NOW}
    args[field] = value
    with pytest.raises((ValueError, PaperCycleJournalError)):
        store.begin(**args)
    assert list((tmp_path / "paper-cycle-journal-v1").iterdir()) == []


@pytest.mark.parametrize(
    "name,body",
    [
        ("claim", b"{}"),
        ("claim", b"{"),
        ("claim", b""),
        ("complete", b"{}"),
        ("complete", b"x" * 4097),
    ],
)
def test_corrupt_or_partial_claims_and_completions_fail_closed(tmp_path, name, body):
    store = journal(tmp_path)
    store.begin("a" * 64, "b" * 64, NOW)
    path = tmp_path / "paper-cycle-journal-v1" / ("a" * 64 + f".{name}.json")
    path.write_bytes(body)
    path.chmod(0o600)
    with pytest.raises(PaperCycleJournalError):
        store.inspect("a" * 64, "b" * 64)


def test_completion_without_claim_cannot_create_a_new_execution_permission(tmp_path):
    store = journal(tmp_path)
    store.inspect("a" * 64, "b" * 64)
    path = tmp_path / "paper-cycle-journal-v1" / ("a" * 64 + ".complete.json")
    path.write_bytes(b"{}")
    path.chmod(0o600)
    with pytest.raises(PaperCycleJournalError):
        store.inspect("a" * 64, "b" * 64)


def test_mismatched_or_missing_claim_denies_completion(tmp_path):
    store = journal(tmp_path)
    claimed = store.begin("a" * 64, "b" * 64, NOW)
    for wrong in (replace(claimed, cycle_id="d" * 64), replace(claimed, context_hash="e" * 64)):
        with pytest.raises(PaperCycleJournalError):
            store.complete(wrong, "c" * 64)


def test_context_identity_cannot_be_changed_after_claim(tmp_path):
    store = journal(tmp_path)
    store.begin("a" * 64, "b" * 64, NOW)
    with pytest.raises(PaperCycleJournalError):
        store.inspect("a" * 64, "e" * 64)


def test_unsafe_mutation_cannot_bypass_completion_claim_validation(tmp_path):
    store = journal(tmp_path)
    claim = store.begin("a" * 64, "b" * 64, NOW)
    object.__setattr__(claim, "started_at", "not-a-time")
    with pytest.raises(PaperCycleJournalError):
        store.complete(claim, "c" * 64)


def test_unclaimed_completion_is_rejected(tmp_path):
    store = journal(tmp_path)
    with pytest.raises(PaperCycleJournalError):
        store.complete(PaperCycleClaim("a" * 64, "b" * 64, NOW), "c" * 64)


@pytest.mark.parametrize("boundary", ["write", "file_fsync", "directory_fsync"])
def test_failed_claim_durability_is_never_reclaimed(tmp_path, monkeypatch, boundary):
    import os
    import stat

    store = journal(tmp_path)
    store.inspect("a" * 64, "b" * 64)
    fsync = os.fsync
    fired = False

    def fail_sync(descriptor):
        nonlocal fired
        is_directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
        if not fired and (
            (boundary == "file_fsync" and not is_directory)
            or (boundary == "directory_fsync" and is_directory)
        ):
            # Do not intercept namespace-parent synchronization before claim creation.
            path = tmp_path / "paper-cycle-journal-v1" / ("a" * 64 + ".claim.json")
            if path.exists():
                fired = True
                raise OSError("injected durability failure")
        fsync(descriptor)

    with monkeypatch.context() as scoped:
        if boundary == "write":
            scoped.setattr(os, "write", lambda *args: 0)
        else:
            scoped.setattr(os, "fsync", fail_sync)
        with pytest.raises(PaperCycleJournalError):
            store.begin("a" * 64, "b" * 64, NOW)
    # A partial reservation is corrupt/unknown; a complete one is pending. Both deny.
    with pytest.raises((PaperCycleJournalError, PaperCycleRecoveryRequired)):
        journal(tmp_path).begin("a" * 64, "b" * 64, NOW)


def test_exclusive_claim_race_cannot_grant_two_execution_owners(tmp_path, monkeypatch):
    import os

    store = journal(tmp_path)
    store.inspect("a" * 64, "b" * 64)
    original_open = os.open

    def concurrent_creation(path, flags, *args, **kwargs):
        if str(path).endswith(".claim.json") and flags & os.O_EXCL:
            raise FileExistsError("injected concurrent claim")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", concurrent_creation)
    with pytest.raises(PaperCycleRecoveryRequired):
        store.begin("a" * 64, "b" * 64, NOW)


def test_completion_digest_wrong_type_is_corruption_not_observation_authority(tmp_path):
    import json

    store = journal(tmp_path)
    claim = store.begin("a" * 64, "b" * 64, NOW)
    store.complete(claim, "c" * 64)
    path = tmp_path / "paper-cycle-journal-v1" / ("a" * 64 + ".complete.json")
    body = json.loads(path.read_text())
    body["observation_hash"] = True
    path.write_text(json.dumps(body))
    with pytest.raises(PaperCycleJournalError):
        store.inspect("a" * 64, "b" * 64)
