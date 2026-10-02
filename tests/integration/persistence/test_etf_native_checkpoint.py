"""The native execution owner survives process-equivalent reconstruction."""

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from tests.unit.simulation.test_etf_native_history import request
from trading_bot.persistence.etf_native_checkpoint import advance_etf_native_checkpoint
from trading_bot.simulation.etf_native_history import run_etf_history


@pytest.fixture
def paths(tmp_path):
    root, repo = tmp_path / "private", tmp_path / "repository"
    root.mkdir(mode=0o700)
    repo.mkdir()
    return root, repo


def test_durable_prefix_rebuilds_fills_cash_and_trial_loss(paths):
    root, repo = paths
    source = request()
    prefix = advance_etf_native_checkpoint(root, source, repository_root=repo, through_ordinal=752)
    assert prefix.result.candidate.account.shares == Decimal(".15")
    assert not prefix.result.candidate.account.complete
    complete = advance_etf_native_checkpoint(
        root, source, repository_root=repo, expected_head=prefix.head_hash
    )
    assert complete.result == run_etf_history(source)
    assert complete.result.candidate.account.trial.consumed_loss == Decimal(".36446985")
    assert advance_etf_native_checkpoint(root, source, repository_root=repo) == complete


@pytest.mark.parametrize("change", ["cash", "cursor", "head"])
def test_changed_authority_cursor_or_head_cannot_resume(paths, change):
    root, repo = paths
    source = request()
    advance_etf_native_checkpoint(root, source, repository_root=repo, through_ordinal=752)
    if change == "cash":
        source = replace(source, initial_cash=Decimal("1000"))
    kwargs = (
        {"through_ordinal": 751}
        if change == "cursor"
        else {"expected_head": "f" * 64}
        if change == "head"
        else {}
    )
    with pytest.raises(ValueError):
        advance_etf_native_checkpoint(root, source, repository_root=repo, **kwargs)


@pytest.mark.parametrize("change", ["cash", "gap", "symlink", "unknown"])
def test_corrupt_or_redirected_state_is_not_recovered_as_trading_authority(paths, change):
    root, repo = paths
    source = request()
    advance_etf_native_checkpoint(root, source, repository_root=repo, through_ordinal=752)
    child = root / "etf-native-checkpoints-v1"
    path = child / "00000001.etf-native-checkpoint.json"
    if change == "cash":
        row = json.loads(path.read_bytes())
        row["result"]["candidate"]["account"]["cash"] = "1000"
        path.write_text(json.dumps(row))
    elif change == "gap":
        path.rename(child / "00000002.etf-native-checkpoint.json")
    elif change == "symlink":
        other = root / "redirected"
        path.rename(other)
        path.symlink_to(other)
    else:
        (child / "unexpected").write_text("unknown")
    with pytest.raises(ValueError):
        advance_etf_native_checkpoint(root, source, repository_root=repo)


@pytest.fixture
def package():
    return request()


def api():
    from trading_bot.persistence import etf_native_checkpoint

    return etf_native_checkpoint


def advance(paths, package, **kwargs):
    return advance_etf_native_checkpoint(paths[0], package, repository_root=paths[1], **kwargs)


def test_busy_writer_cannot_change_state(paths, package):
    import fcntl
    import os

    first = advance(paths, package, through_ordinal=753)
    lock = os.open(paths[0] / "etf-native-checkpoints-v1" / "writer.lock", os.O_RDWR)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="etf_native_checkpoint_invalid"):
            advance(paths, package)
    finally:
        os.close(lock)
    assert advance(paths, package, through_ordinal=753) == first


def test_failed_publication_restores_prior_commit_without_replaying_cash_twice(
    paths, package, monkeypatch
):
    module = api()
    first = advance(paths, package, through_ordinal=753)
    original = module._publish

    def fail_before_publish(directory, name, body):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(module, "_publish", fail_before_publish)
    with pytest.raises(ValueError, match="etf_native_checkpoint_invalid"):
        advance(paths, package)
    monkeypatch.setattr(module, "_publish", original)
    assert advance(paths, package, through_ordinal=753) == first
    assert advance(paths, package).result == run_etf_history(package)


def test_failure_after_publication_retains_complete_commit_for_retry(paths, package, monkeypatch):
    module = api()
    advance(paths, package, through_ordinal=753)
    original = module._publish

    def fail_after_publish(directory, name, body):
        original(directory, name, body)
        raise OSError("uncertain fsync result")

    monkeypatch.setattr(module, "_publish", fail_after_publish)
    with pytest.raises(ValueError, match="etf_native_checkpoint_invalid"):
        advance(paths, package)
    monkeypatch.setattr(module, "_publish", original)
    restored = advance(paths, package)
    assert restored.sequence == 2
    assert restored.result == run_etf_history(package)


def test_stale_expected_head_denies_before_new_publication(paths, package):
    first = advance(paths, package, through_ordinal=751)
    advance(paths, package, through_ordinal=753, expected_head=first.head_hash)
    with pytest.raises(ValueError, match="etf_native_checkpoint_invalid"):
        advance(paths, package, expected_head=first.head_hash)


@pytest.mark.parametrize("count", [True, "752"])
def test_checkpoint_source_count_requires_exact_integer_not_coercion(paths, package, count):
    first = advance(paths, package, through_ordinal=752)
    path = paths[0] / "etf-native-checkpoints-v1" / "00000001.etf-native-checkpoint.json"
    row = json.loads(path.read_bytes())
    row["source_count"] = count
    path.write_text(json.dumps(row))
    with pytest.raises(ValueError, match="etf_native_checkpoint_invalid"):
        advance(paths, package, expected_head=first.head_hash)
    assert not (path.parent / "00000002.etf-native-checkpoint.json").exists()


def test_invalid_source_cursor_is_denied_before_opening_checkpoint_root(paths, package):
    with pytest.raises(ValueError, match="etf_native_checkpoint_invalid"):
        advance(paths, package, through_ordinal=-1)
    assert list(paths[0].iterdir()) == []


@pytest.mark.parametrize("stage", ["before_publish", "staged_write", "after_link", "after_publish"])
def test_killed_writer_releases_lock_and_recovers_atomic_prefix(paths, package, stage):
    import os
    import signal

    if not hasattr(os, "fork"):
        pytest.skip("process-crash fixture requires fork")
    first = advance(paths, package, through_ordinal=753)
    module = api()
    child = os.fork()
    if child == 0:
        original = module._publish

        def die():
            os.kill(os.getpid(), signal.SIGKILL)

        if stage == "staged_write":
            write = os.write

            def crash_write(fd, body):
                write(fd, body)
                die()

            os.write = crash_write
        elif stage == "after_link":
            link = os.link

            def crash_link(*args, **kwargs):
                link(*args, **kwargs)
                die()

            os.link = crash_link
        else:

            def crash_publish(directory, name, body):
                if stage == "after_publish":
                    original(directory, name, body)
                die()

            module._publish = crash_publish
        try:
            advance(paths, package)
        finally:
            os._exit(3)
    _, status = os.waitpid(child, 0)
    assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
    if stage in ("before_publish", "staged_write"):
        assert advance(paths, package, through_ordinal=753) == first
    final = advance(paths, package)
    assert final.result == run_etf_history(package)
    assert final.result.candidate.account.trial.consumed_loss == Decimal("0.36446985")
    assert final.sequence == 2
