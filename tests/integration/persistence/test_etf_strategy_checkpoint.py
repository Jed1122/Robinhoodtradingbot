"""A restarted process must reconstruct the same sole account owner."""

import importlib
import json
from dataclasses import replace
from decimal import Decimal

import pytest

from tests.unit.simulation.test_etf_history import study
from trading_bot.domain import OrderState
from trading_bot.simulation.etf_strategy import run_etf_fixture_strategy
from trading_bot.simulation.etf_strategy_fixtures import synthetic_etf_strategy_request


def api():
    try:
        return importlib.import_module("trading_bot.persistence.etf_strategy_checkpoint")
    except ModuleNotFoundError:
        pytest.fail("durable strategy checkpoint store is missing")


@pytest.fixture
def paths(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    repo = tmp_path / "repo"
    repo.mkdir()
    return root, repo


@pytest.fixture
def package():
    from decimal import Decimal

    return synthetic_etf_strategy_request(study(), Decimal("500"))


def advance(paths, package, **kwargs):
    root, repo = paths
    return api().advance_etf_strategy_checkpoint(root, package, repository_root=repo, **kwargs)


def test_partial_fill_restart_reconstructs_reserved_cash_and_completed_loss(paths, package):
    partial = advance(paths, package, through_ordinal=753)
    assert partial.result.account.shares == Decimal("0.15")
    assert partial.result.account.trial.reserved_risk > 0
    assert partial.result.paused
    complete = advance(paths, package)
    assert complete.result == run_etf_fixture_strategy(package)
    assert complete.result.account.cash == Decimal("499.63553015")
    assert complete.result.account.trial.consumed_loss == Decimal("0.36446985")
    assert complete.sequence == 2
    assert advance(paths, package) == complete
    assert not complete.result.execution_enabled and not complete.result.evidence_promotable


def test_pending_cancellation_survives_restart_without_liberating_trial_capacity(paths):
    from decimal import Decimal

    package = synthetic_etf_strategy_request(study(), Decimal("500"), "partial_cancel")
    first = advance(paths, package)
    assert first.result.account.orders[0].order.state is OrderState.CANCEL_PENDING
    assert first.result.account.reserved_cash == Decimal("11.0696")
    assert first.result.account.trial.reserved_risk == Decimal("15.1")
    assert advance(paths, package) == first


def test_store_rejects_changed_inputs_and_cursor_regression(paths, package):
    advance(paths, package, through_ordinal=753)
    changed = replace(package, episode_fee_bound=package.episode_fee_bound * 2)
    for candidate, kwargs in ((changed, {}), (package, {"through_ordinal": 751})):
        with pytest.raises(ValueError, match="etf_strategy_checkpoint_invalid"):
            advance(paths, candidate, **kwargs)


@pytest.mark.parametrize("mode", ["bytes", "gap", "symlink", "unknown"])
def test_restore_rejects_corrupt_or_redirected_journal(paths, package, mode):
    advance(paths, package, through_ordinal=753)
    child = paths[0] / "etf-strategy-checkpoints-v1"
    path = child / "00000001.etf-strategy-checkpoint.json"
    if mode == "bytes":
        row = json.loads(path.read_bytes())
        row["result"]["account"]["cash"] = "999"
        path.write_text(json.dumps(row))
    elif mode == "gap":
        path.rename(child / "00000002.etf-strategy-checkpoint.json")
    elif mode == "symlink":
        moved = paths[0] / "moved.json"
        path.rename(moved)
        path.symlink_to(moved)
    else:
        (child / "unrecognized").write_text("unexpected")
    with pytest.raises(ValueError, match="etf_strategy_checkpoint_invalid"):
        advance(paths, package)


def test_busy_writer_cannot_change_state(paths, package):
    import fcntl
    import os

    first = advance(paths, package, through_ordinal=753)
    lock = os.open(paths[0] / "etf-strategy-checkpoints-v1" / "writer.lock", os.O_RDWR)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="etf_strategy_checkpoint_invalid"):
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
    with pytest.raises(ValueError, match="etf_strategy_checkpoint_invalid"):
        advance(paths, package)
    monkeypatch.setattr(module, "_publish", original)
    assert advance(paths, package, through_ordinal=753) == first
    assert advance(paths, package).result == run_etf_fixture_strategy(package)


def test_failure_after_publication_retains_complete_commit_for_retry(paths, package, monkeypatch):
    module = api()
    advance(paths, package, through_ordinal=753)
    original = module._publish

    def fail_after_publish(directory, name, body):
        original(directory, name, body)
        raise OSError("uncertain fsync result")

    monkeypatch.setattr(module, "_publish", fail_after_publish)
    with pytest.raises(ValueError, match="etf_strategy_checkpoint_invalid"):
        advance(paths, package)
    monkeypatch.setattr(module, "_publish", original)
    restored = advance(paths, package)
    assert restored.sequence == 2
    assert restored.result == run_etf_fixture_strategy(package)


def test_stale_expected_head_denies_before_new_publication(paths, package):
    first = advance(paths, package, through_ordinal=751)
    advance(paths, package, through_ordinal=753, expected_head=first.head_hash)
    with pytest.raises(ValueError, match="etf_strategy_checkpoint_invalid"):
        advance(paths, package, expected_head=first.head_hash)


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
    assert final.result == run_etf_fixture_strategy(package)
    assert final.result.account.trial.consumed_loss == Decimal("0.36446985")
    assert final.sequence == 2
