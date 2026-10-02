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
@pytest.mark.parametrize("change", ["as_of", "portfolio", "identity"])
async def test_unknown_effects_quarantine_changed_cycle_requests(tmp_path, change):
    from datetime import timedelta
    from decimal import Decimal

    tmp_path.chmod(0o700)
    first, _ = application(tmp_path, FailingStore())
    cycle_request = replace(request(), universe=(InstrumentId("TEST"),))
    with pytest.raises(OSError):
        await first.run_cycle(cycle_request)
    context = promotion_context()
    if change == "as_of":
        changed = replace(cycle_request, as_of=cycle_request.as_of + timedelta(seconds=1))
    elif change == "portfolio":
        changed = replace(
            cycle_request, portfolio=replace(cycle_request.portfolio, cash=Decimal(99))
        )
    else:
        changed = replace(cycle_request, as_of=cycle_request.as_of + timedelta(seconds=1))
        context = replace(
            context, identity=replace(context.identity, provider_evidence_hash="e" * 64)
        )
    restarted, service = application(tmp_path, PromotionStore(), context=context)
    with pytest.raises(RuntimeError, match="paper_cycle_recovery_required"):
        await restarted.run_cycle(changed)
    assert service.execution.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("incomplete", ["outcome", "reconciliation"])
async def test_recorded_but_unresolved_outcome_keeps_owner_quarantined(tmp_path, incomplete):
    from datetime import timedelta

    from trading_bot.domain import OrderState

    tmp_path.chmod(0o700)
    store = PromotionStore()
    context = promotion_context()
    if incomplete == "reconciliation":
        context = replace(context, reconciliation_clean=False)
    app, _ = application(tmp_path, store, context=context)
    if incomplete == "outcome":
        original = app._paper.run_cycle

        async def pending(cycle_request):
            cycle = await original(cycle_request)
            result = replace(
                cycle.result,
                order_outcomes=tuple(
                    replace(outcome, state=OrderState.SUBMITTED)
                    for outcome in cycle.result.order_outcomes
                ),
            )
            return replace(cycle, result=result, research_cycle_eligible=False)

        app._paper.run_cycle = pending
    cycle_request = replace(request(), universe=(InstrumentId("TEST"),))
    recorded = await app.run_cycle(cycle_request)
    assert not recorded.observation.eligible
    restarted, service = application(tmp_path, store)
    changed = replace(cycle_request, as_of=cycle_request.as_of + timedelta(seconds=1))
    with pytest.raises(RuntimeError, match="paper_cycle_recovery_required"):
        await restarted.run_cycle(changed)
    assert service.execution.calls == 0


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
@pytest.mark.parametrize("change", ["time", "identity"])
async def test_missing_completed_history_blocks_a_new_request(tmp_path, change):
    from datetime import timedelta

    tmp_path.chmod(0o700)
    cycle_request = replace(request(), universe=(InstrumentId("TEST"),))
    first, service = application(tmp_path, PromotionStore())
    await first.run_cycle(cycle_request)
    assert service.execution.calls == 1
    context = promotion_context()
    if change == "identity":
        context = replace(
            context, identity=replace(context.identity, provider_evidence_hash="e" * 64)
        )
    restarted, new_service = application(tmp_path, PromotionStore(), context=context)
    with pytest.raises(RuntimeError, match="paper_cycle_recovery_required"):
        await restarted.run_cycle(
            replace(cycle_request, as_of=cycle_request.as_of + timedelta(seconds=1))
        )
    assert new_service.execution.calls == 0


@pytest.mark.asyncio
async def test_old_eligible_cycle_cannot_escape_another_pending_claim(tmp_path):
    from datetime import timedelta

    tmp_path.chmod(0o700)
    store = PromotionStore()
    cycle_request = replace(request(), universe=(InstrumentId("TEST"),))
    first, _ = application(tmp_path, store)
    assert (await first.run_cycle(cycle_request)).observation.eligible
    failing = FailingStore()
    failing.observations[:] = store.observations
    other, service = application(tmp_path, failing)
    with pytest.raises(OSError):
        await other.run_cycle(
            replace(cycle_request, as_of=cycle_request.as_of + timedelta(seconds=1))
        )
    assert service.execution.calls == 1
    restarted, new_service = application(tmp_path, store)
    with pytest.raises(RuntimeError, match="paper_cycle_recovery_required"):
        await restarted.run_cycle(cycle_request)
    assert new_service.execution.calls == 0


@pytest.mark.asyncio
async def test_promotion_snapshot_holds_owner_until_consumer_finishes(tmp_path):
    from datetime import timedelta

    tmp_path.chmod(0o700)
    store = PromotionStore()
    first, _ = application(tmp_path, store)
    cycle_request = replace(request(), universe=(InstrumentId("TEST"),))
    await first.run_cycle(cycle_request)
    other, service = application(tmp_path, store)
    changed = replace(cycle_request, as_of=cycle_request.as_of + timedelta(seconds=1))
    async with first.promotion_observations() as observations:
        assert observations == tuple(store.observations)
        with pytest.raises(RuntimeError, match="paper_cycle_writer_busy"):
            await other.run_cycle(changed)
        assert service.execution.calls == 0
    assert (await other.run_cycle(changed)).executed


@pytest.mark.asyncio
async def test_promotion_snapshot_denies_incomplete_observation_history(tmp_path):
    from trading_bot.monitoring.promotion import PromotionStage

    tmp_path.chmod(0o700)
    store = PromotionStore()
    app, _ = application(tmp_path, store)
    cycle_request = replace(request(), universe=(InstrumentId("TEST"),))
    recorded = await app.run_cycle(cycle_request)
    args = {
        field.name: getattr(recorded.observation, field.name)
        for field in fields(recorded.observation)
        if field.name not in ("eligible", "reason_codes", "evidence_hash")
    }
    args.update(cycle_id="e" * 64, stage=PromotionStage.PAPER, outcomes_complete=False)
    store.observations.append(PromotionObservation.create(**args))
    with pytest.raises(RuntimeError, match="paper_cycle_recovery_required"):
        async with app.promotion_observations():
            pytest.fail("unresolved history produced a promotion snapshot")


@pytest.mark.asyncio
async def test_failure_after_observation_append_recovers_without_execution(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    store = PromotionStore()
    cycle_request = replace(request(), universe=(InstrumentId("TEST"),))
    first, service = application(tmp_path, store)

    def fail_completion(*args):
        raise RuntimeError("injected completion publication failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(type(first._journal), "complete", fail_completion)
        with pytest.raises(RuntimeError, match="injected completion"):
            await first.run_cycle(cycle_request)
    assert service.execution.calls == 1 and len(store.observations) == 1
    restarted, new_service = application(tmp_path, store)
    recovered = await restarted.run_cycle(cycle_request)
    assert recovered.observation == store.observations[0] and not recovered.executed
    assert new_service.execution.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_field", ["fixture_data", "data_hash"])
async def test_pending_observation_cannot_be_replaced_by_another_self_valid_body(
    tmp_path, monkeypatch, changed_field
):
    tmp_path.chmod(0o700)
    store = PromotionStore()
    context = replace(promotion_context(), fixture_data=True)
    app, _ = application(tmp_path, store, context=context)
    cycle_request = replace(request(), universe=(InstrumentId("TEST"),))

    def fail_completion(*args):
        raise RuntimeError("injected completion failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(type(app._journal), "complete", fail_completion)
        with pytest.raises(RuntimeError):
            await app.run_cycle(cycle_request)
    observation = store.observations[0]
    args = {
        field.name: getattr(observation, field.name)
        for field in fields(observation)
        if field.name not in ("eligible", "reason_codes", "evidence_hash")
    }
    args[changed_field] = False if changed_field == "fixture_data" else "e" * 64
    store.observations[0] = PromotionObservation.create(**args)
    restarted, service = application(tmp_path, store, context=context)
    with pytest.raises(RuntimeError, match="paper_cycle_journal_invalid"):
        await restarted.run_cycle(cycle_request)
    assert service.execution.calls == 0


@pytest.mark.asyncio
async def test_prepared_hash_failure_never_appends_an_observation_or_retries(tmp_path, monkeypatch):
    from datetime import timedelta

    tmp_path.chmod(0o700)
    store = PromotionStore()
    app, service = application(tmp_path, store)
    cycle_request = replace(request(), universe=(InstrumentId("TEST"),))

    def fail(*args):
        raise RuntimeError("injected prepared hash persistence failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(type(app._journal), "prepare_observation", fail)
        with pytest.raises(RuntimeError, match="injected prepared"):
            await app.run_cycle(cycle_request)
    assert service.execution.calls == 1 and store.observations == []
    restarted, new_service = application(tmp_path, store)
    with pytest.raises(RuntimeError, match="paper_cycle_recovery_required"):
        await restarted.run_cycle(
            replace(cycle_request, as_of=cycle_request.as_of + timedelta(seconds=1))
        )
    assert new_service.execution.calls == 0


@pytest.mark.asyncio
async def test_writer_lock_spans_async_execution_and_blocks_different_requests(tmp_path):
    import asyncio
    from datetime import timedelta

    tmp_path.chmod(0o700)
    store = PromotionStore()
    first, service = application(tmp_path, store)
    original = service.run_cycle
    entered, released = asyncio.Event(), asyncio.Event()

    async def wait(cycle_request):
        entered.set()
        await released.wait()
        return await original(cycle_request)

    service.run_cycle = wait
    cycle_request = replace(request(), universe=(InstrumentId("TEST"),))
    task = asyncio.create_task(first.run_cycle(cycle_request))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        other, other_service = application(tmp_path, store)
        changed = replace(cycle_request, as_of=cycle_request.as_of + timedelta(seconds=1))
        with pytest.raises(RuntimeError, match="paper_cycle_writer_busy"):
            await other.run_cycle(changed)
        assert other_service.execution.calls == 0
    finally:
        released.set()
        await asyncio.wait_for(task, 5)
    assert (await other.run_cycle(changed)).executed
    assert other_service.execution.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["account", "configuration"])
async def test_unknown_request_identity_denies_before_simulated_effects(tmp_path, field):
    tmp_path.chmod(0o700)
    app, service = application(tmp_path, PromotionStore())
    cycle_request = replace(request(), universe=(InstrumentId("TEST"),))
    if field == "account":
        cycle_request = replace(
            cycle_request, portfolio=replace(cycle_request.portfolio, account_id="unknown-account")
        )
    else:
        cycle_request = replace(cycle_request, strategy_context_config_hash="e" * 64)
    with pytest.raises(RuntimeError, match="paper_cycle_journal_invalid"):
        await app.run_cycle(cycle_request)
    assert service.execution.calls == 0
    assert not list((tmp_path / "paper-cycle-journal-v1").glob("*.claim.json"))


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
    assert {path.name for path in (tmp_path / "paper-cycle-journal-v1").iterdir()} == {
        "writer.lock"
    }


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
