"""Unknown paper effects survive fresh composition instead of being reexecuted."""

from dataclasses import fields, replace

import pytest

from tests.integration.runtime.test_paper import (
    FixedClock,
    PromotionStore,
    accepted,
    promotable_service,
    promotion_context,
)
from tests.integration.simulation.test_decision_cycle import request
from trading_bot.domain import CodeHash, InstrumentId
from trading_bot.monitoring.promotion import PromotionObservation
from trading_bot.runtime.paper import InMemoryPaperCycleStore, build_paper_application
from trading_bot.runtime.paper_promotion import PaperCycleMutex, PaperPromotionApplication


def application(directory, store, *, context=None, service=None):
    cycle_service = promotable_service() if service is None else service
    paper = build_paper_application(
        cycle_service,
        store=InMemoryPaperCycleStore(),
        eligibility=accepted(),
        strategy_version="strategy-v1",
        code_hash=CodeHash("f" * 64),
    )
    return (
        PaperPromotionApplication(
            paper=paper,
            context=promotion_context() if context is None else context,
            observations=store,
            mutex=PaperCycleMutex(directory),
            clock=FixedClock(),
        ),
        cycle_service,
    )


class FailingStore(PromotionStore):
    async def append(self, observation):
        raise OSError("injected observation failure")


@pytest.mark.asyncio
async def test_observation_failure_blocks_fresh_same_cycle_before_execution(tmp_path):
    tmp_path.chmod(0o700)
    first, service = application(tmp_path, FailingStore())
    cycle_request = replace(request(), universe=(InstrumentId("TEST"),))
    with pytest.raises(OSError, match="injected"):
        await first.run_cycle(cycle_request)
    assert service.execution.calls == 1
    restarted, new_service = application(tmp_path, PromotionStore())
    with pytest.raises(RuntimeError, match="paper_cycle_recovery_required"):
        await restarted.run_cycle(cycle_request)
    assert new_service.execution.calls == 0


@pytest.mark.asyncio
async def test_missing_durable_observation_after_completion_is_not_permission_to_repeat(tmp_path):
    tmp_path.chmod(0o700)
    store = PromotionStore()
    cycle_request = replace(request(), universe=(InstrumentId("TEST"),))
    first, service = application(tmp_path, store)
    await first.run_cycle(cycle_request)
    assert service.execution.calls == 1
    restarted, new_service = application(tmp_path, PromotionStore())
    with pytest.raises(RuntimeError, match="paper_cycle_recovery_required"):
        await restarted.run_cycle(cycle_request)
    assert new_service.execution.calls == 0


@pytest.mark.asyncio
async def test_failure_after_observation_append_recovers_without_execution(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    store = PromotionStore()
    cycle_request = replace(request(), universe=(InstrumentId("TEST"),))
    first, service = application(tmp_path, store)

    def fail_completion(*args):
        raise RuntimeError("injected completion publication failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(first._journal, "complete", fail_completion)
        with pytest.raises(RuntimeError, match="injected completion"):
            await first.run_cycle(cycle_request)
    assert service.execution.calls == 1 and len(store.observations) == 1
    restarted, new_service = application(tmp_path, store)
    recovered = await restarted.run_cycle(cycle_request)
    assert recovered.observation == store.observations[0] and not recovered.executed
    assert new_service.execution.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["symlink_root", "hardlink_claim", "symlink_claim"])
async def test_unsafe_journal_paths_deny_before_reexecution(tmp_path, kind):
    tmp_path.chmod(0o700)
    store = FailingStore()
    cycle_request = replace(request(), universe=(InstrumentId("TEST"),))
    first, _ = application(tmp_path, store)
    with pytest.raises(OSError):
        await first.run_cycle(cycle_request)
    journal = tmp_path / "paper-cycle-journal-v1"
    claim = next(journal.glob("*.claim.json"))
    if kind == "symlink_root":
        moved = tmp_path / "moved-journal"
        journal.rename(moved)
        journal.symlink_to(moved, target_is_directory=True)
    elif kind == "hardlink_claim":
        import os

        os.link(claim, tmp_path / "shared-claim.json")
    else:
        moved = tmp_path / "moved-claim.json"
        claim.rename(moved)
        claim.symlink_to(moved)
    restarted, service = application(tmp_path, PromotionStore())
    with pytest.raises(RuntimeError, match="paper_cycle_journal_invalid"):
        await restarted.run_cycle(cycle_request)
    assert service.execution.calls == 0


@pytest.mark.asyncio
async def test_invalid_mutex_directory_cannot_create_lock_files(tmp_path):
    tmp_path.chmod(0o700)
    target = tmp_path / "real"
    target.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises((ValueError, RuntimeError, PermissionError)):
        mutex = PaperCycleMutex(alias)
        async with mutex.acquire("a" * 64):
            pytest.fail("symlink mutex directory accepted")
    assert list(target.iterdir()) == []


@pytest.mark.asyncio
async def test_unknown_effects_are_not_released_when_context_flags_change(tmp_path):
    tmp_path.chmod(0o700)
    first, _ = application(tmp_path, FailingStore())
    cycle_request = replace(request(), universe=(InstrumentId("TEST"),))
    with pytest.raises(OSError):
        await first.run_cycle(cycle_request)
    changed = replace(promotion_context(), reconciliation_clean=False)
    restarted, service = application(tmp_path, PromotionStore(), context=changed)
    with pytest.raises(RuntimeError, match="paper_cycle_journal_invalid"):
        await restarted.run_cycle(cycle_request)
    assert service.execution.calls == 0


@pytest.mark.asyncio
async def test_cycle_exception_also_retains_unknown_claim(tmp_path):
    tmp_path.chmod(0o700)
    service = promotable_service()

    async def fail_cycle(_request):
        raise RuntimeError("injected execution failure")

    service.run_cycle = fail_cycle
    cycle_request = replace(request(), universe=(InstrumentId("TEST"),))
    first, _ = application(tmp_path, PromotionStore(), service=service)
    with pytest.raises(RuntimeError, match="injected execution failure"):
        await first.run_cycle(cycle_request)
    restarted, new_service = application(tmp_path, PromotionStore())
    with pytest.raises(RuntimeError, match="paper_cycle_recovery_required"):
        await restarted.run_cycle(cycle_request)
    assert new_service.execution.calls == 0


@pytest.mark.asyncio
async def test_sigkill_after_simulated_effects_keeps_durable_unknown_claim(tmp_path):
    import os
    import signal
    import subprocess
    import sys
    from pathlib import Path

    tmp_path.chmod(0o700)
    code = """
import asyncio, os, signal, sys
from dataclasses import replace
from pathlib import Path
from tests.integration.runtime.test_paper_claim_recovery import application
from tests.integration.runtime.test_paper import PromotionStore
from tests.integration.simulation.test_decision_cycle import request
from trading_bot.domain import InstrumentId
class KillAfterEffects(PromotionStore):
    async def append(self, observation):
        os.kill(os.getpid(), signal.SIGKILL)
app, service = application(Path(sys.argv[1]), KillAfterEffects())
asyncio.run(app.run_cycle(replace(request(), universe=(InstrumentId('TEST'),))))
"""
    root = Path(__file__).parents[3]
    child = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        capture_output=True,
        timeout=20,
    )
    assert child.returncode == -signal.SIGKILL, child.stderr.decode()
    restarted, service = application(tmp_path, PromotionStore())
    with pytest.raises(RuntimeError, match="paper_cycle_recovery_required"):
        await restarted.run_cycle(replace(request(), universe=(InstrumentId("TEST"),)))
    assert service.execution.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("cycle_id", ["bad", "A" * 64, "g" * 64])
async def test_bad_cycle_key_never_creates_a_mutex_lock(tmp_path, cycle_id):
    tmp_path.chmod(0o700)
    mutex = PaperCycleMutex(tmp_path)
    with pytest.raises(ValueError):
        async with mutex.acquire(cycle_id):
            pytest.fail("invalid lock identity accepted")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["symlink", "hardlink", "nonempty"])
async def test_unsafe_lock_file_denies_before_journal_or_execution(tmp_path, kind):
    import os

    tmp_path.chmod(0o700)
    app, service = application(tmp_path, PromotionStore())
    cycle_request = replace(request(), universe=(InstrumentId("TEST"),))
    lock = tmp_path / ("paper-" + app._paper.cycle_id(cycle_request) + ".lock")
    if kind == "symlink":
        lock.symlink_to(tmp_path / "uncreated-target")
    else:
        lock.write_bytes(b"unsafe" if kind == "nonempty" else b"")
        lock.chmod(0o600)
        if kind == "hardlink":
            os.link(lock, tmp_path / "linked-lock")
    with pytest.raises((ValueError, OSError)):
        await app.run_cycle(cycle_request)
    assert service.execution.calls == 0
    assert not (tmp_path / "paper-cycle-journal-v1").exists()


@pytest.mark.asyncio
async def test_distinct_mutex_objects_cannot_own_one_cycle_simultaneously(tmp_path):
    from trading_bot.runtime.paper_promotion import PaperCycleAlreadyInProgress

    tmp_path.chmod(0o700)
    first, other = PaperCycleMutex(tmp_path), PaperCycleMutex(tmp_path)
    async with first.acquire("a" * 64):
        with pytest.raises(PaperCycleAlreadyInProgress):
            async with other.acquire("a" * 64):
                pytest.fail("overlapping writer acquired mutex")


@pytest.mark.asyncio
async def test_legacy_observation_still_blocks_without_creating_new_claim(tmp_path):
    tmp_path.chmod(0o700)
    store = PromotionStore()
    source = tmp_path / "earlier-runtime"
    source.mkdir(mode=0o700)
    original, _ = application(source, store)
    cycle_request = replace(request(), universe=(InstrumentId("TEST"),))
    await original.run_cycle(cycle_request)
    app, service = application(tmp_path, store)
    result = await app.run_cycle(cycle_request)
    assert not result.executed and service.execution.calls == 0
    assert list((tmp_path / "paper-cycle-journal-v1").iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["duplicate", "changed"])
async def test_conflicting_durable_observations_never_complete_or_reexecute(tmp_path, kind):
    tmp_path.chmod(0o700)
    store = PromotionStore()
    app, _ = application(tmp_path, store)
    cycle_request = replace(request(), universe=(InstrumentId("TEST"),))
    original = (await app.run_cycle(cycle_request)).observation
    if kind == "duplicate":
        store.observations.append(original)
    else:
        args = {
            field.name: getattr(original, field.name)
            for field in fields(original)
            if field.name not in ("eligible", "reason_codes", "evidence_hash")
        }
        args["data_hash"] = "d" * 64
        store.observations[0] = PromotionObservation.create(**args)
    restarted, service = application(tmp_path, store)
    with pytest.raises(RuntimeError):
        await restarted.run_cycle(cycle_request)
    assert service.execution.calls == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("identity", None),
        ("expected_account_id", ""),
        ("fixture_data", "false"),
    ],
)
def test_context_remains_strictly_typed(field, value):
    with pytest.raises((TypeError, ValueError)):
        replace(promotion_context(), **{field: value})


@pytest.mark.asyncio
async def test_changed_cycle_identity_after_execution_keeps_unknown_claim(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    store = PromotionStore()
    app, _ = application(tmp_path, store)
    run = app._paper.run_cycle

    async def changed(request):
        return replace(await run(request), cycle_id="d" * 64)

    monkeypatch.setattr(app._paper, "run_cycle", changed)
    cycle_request = replace(request(), universe=(InstrumentId("TEST"),))
    with pytest.raises(RuntimeError, match="identity changed"):
        await app.run_cycle(cycle_request)
    assert store.observations == []
    restarted, service = application(tmp_path, store)
    with pytest.raises(RuntimeError, match="paper_cycle_recovery_required"):
        await restarted.run_cycle(cycle_request)
    assert service.execution.calls == 0
