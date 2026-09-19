import asyncio
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from tests.unit.domain.test_options import NOW
from tests.unit.lifecycle.test_options_expiry import calendar
from tests.unit.reconciliation._options_fixtures import ACCOUNT, owned, snapshot
from tests.unit.reconciliation._options_fixtures import (
    offline_observation_boundary as offline_observation_boundary,
)
from trading_bot.config import load_config
from trading_bot.domain import ExecutionMode
from trading_bot.runtime.options_monitor import OptionsMonitorInput, PausedOptionsMonitor


class Clock:
    at = NOW

    def now(self):
        return self.at


class Source:
    async def read(self, account_id):
        assert account_id == ACCOUNT
        return OptionsMonitorInput(snapshot(), snapshot(), (owned(),), (calendar(),))


class Store:
    def __init__(self):
        self.rows = []

    async def persist(self, result):
        self.rows.append(result)


class Alerts:
    def __init__(self):
        self.sent = []

    async def send(self, alert):
        self.sent.append(alert)


def loaded():
    return load_config(
        Path("configs/base.yaml"),
        Path("configs/options/simulation.yaml"),
        Path("configs/safety-envelope.yaml"),
        environ={},
    )


def monitor(**changes):
    args = dict(
        account_id=ACCOUNT,
        loaded=loaded(),
        source=Source(),
        store=Store(),
        alerts=Alerts(),
        clock=Clock(),
    )
    args.update(changes)
    return PausedOptionsMonitor(**args)


async def test_cycle_persists_comparison_but_startup_restart_and_clean_status_stay_paused():
    store = Store()
    m = monitor(store=store)
    assert m.status().reasons == ("not_observed",)
    result = await m.cycle()
    assert result.reconciliation_clean and result.reasons == ()
    assert result.paused and not result.entry_enabled and not result.live_supported
    assert len(store.rows) == 1 and store.rows[0].clean
    from trading_bot.market_data.recording import content_hash

    data = await Source().read(ACCOUNT)
    assert store.rows[0].reconciliation_id.startswith(
        f"options-observation-v1-{content_hash(data)}-"
    )
    assert monitor(store=store).status().reasons == ("not_observed",)


async def test_expiry_incident_is_persisted_and_alerted_without_orders():
    class NoCalendar(Source):
        async def read(self, account_id):
            return replace(await super().read(account_id), calendars=())

    store, alerts = Store(), Alerts()
    result = await monitor(source=NoCalendar(), store=store, alerts=alerts).cycle()
    assert not result.reconciliation_clean
    assert "expiry_calendar_unverified" in result.reasons
    assert not store.rows[0].clean and len(alerts.sent) == 1
    assert alerts.sent[0].details == ()


async def test_stale_result_cannot_remain_healthy_between_ticks():
    clock = Clock()
    m = monitor(clock=clock)
    await m.cycle()
    clock.at += timedelta(days=1)
    assert "monitor_observation_stale" in m.status().reasons
    clock.at = NOW - timedelta(seconds=1)
    assert "monitor_clock_regressed" in m.status().reasons


@pytest.mark.parametrize(
    "where,code",
    [
        ("source", "monitor_observation_failed"),
        ("store", "monitor_persistence_failed"),
        ("alerts", "monitor_alert_failed"),
    ],
)
async def test_io_failure_is_redacted_and_never_reports_readiness(where, code):
    class Broken:
        async def read(self, account_id):
            raise RuntimeError("do-not-leak-provider-payload")

        async def persist(self, result):
            raise OSError("do-not-leak-provider-payload")

        async def send(self, alert):
            raise RuntimeError("do-not-leak-provider-payload")

    class Bad(Source):
        async def read(self, account_id):
            return replace(await super().read(account_id), calendars=())

    args = dict(source=Bad())
    args[where] = Broken()
    result = await monitor(**args).cycle()
    assert code in result.reasons
    assert "do-not-leak" not in repr(result)
    assert result.paused and not result.entry_enabled


async def test_concurrent_cycle_does_not_duplicate_reads_or_persistence():
    entered, release = asyncio.Event(), asyncio.Event()

    class Slow(Source):
        async def read(self, account_id):
            entered.set()
            await release.wait()
            return await super().read(account_id)

    store = Store()
    m = monitor(source=Slow(), store=store)
    task = asyncio.create_task(m.cycle())
    await entered.wait()
    assert "monitor_cycle_running" in (await m.cycle()).reasons
    release.set()
    await task
    assert len(store.rows) == 1


async def test_stop_before_start_does_not_read_and_continuous_loop_stops_promptly():
    stop = asyncio.Event()
    stop.set()
    m = monitor()
    await m.run(stop)
    assert m.status().last_persisted_at is None
    stop.clear()

    class StopAfterOne(Store):
        async def persist(self, result):
            await super().persist(result)
            stop.set()

    store = StopAfterOne()
    await asyncio.wait_for(monitor(store=store).run(stop), 1)
    assert len(store.rows) == 1


def test_forged_config_and_disabled_options_are_rejected():
    with pytest.raises(ValueError):
        monitor(loaded=replace(loaded(), config_hash="0" * 64))
    with pytest.raises(ValueError):
        monitor(
            loaded=replace(
                loaded(),
                config=loaded().config.model_copy(update={"mode": ExecutionMode.NORMAL_LIVE}),
            )
        )


async def test_read_timeout_cancels_read_without_persisting_or_leaking():
    cancelled = asyncio.Event()

    class Stalled(Source):
        async def read(self, account_id):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    short = load_config(
        Path("configs/base.yaml"),
        Path("configs/options/simulation.yaml"),
        Path("configs/safety-envelope.yaml"),
        environ={"TRADING_BOT__RUNTIME__BROKER_TIMEOUT_SECONDS": "0.02"},
    )
    store = Store()
    m = monitor(source=Stalled(), store=store, loaded=short)
    result = await asyncio.wait_for(m.cycle(), 1)
    assert cancelled.is_set() and store.rows == []
    assert result.reasons == ("monitor_observation_failed",)


async def test_external_cancellation_remains_paused_and_releases_cycle_lock():
    entered = asyncio.Event()

    class Stalled(Source):
        async def read(self, account_id):
            entered.set()
            await asyncio.Event().wait()

    m = monitor(source=Stalled())
    task = asyncio.create_task(m.cycle())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert m.status().paused and not m.status().reconciliation_clean
    # A second read reaches the source: the scheduler lock was released.
    entered.clear()
    task = asyncio.create_task(m.cycle())
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_flat_account_needs_no_expiry_calendar_but_open_orders_do():
    from tests.unit.reconciliation._options_fixtures import order
    from trading_bot.domain import OrderState

    class Flat(Source):
        async def read(self, account_id):
            flat = snapshot(positions=(), orders=(), fills=())
            return OptionsMonitorInput(flat, flat, (), ())

    assert (await monitor(source=Flat()).cycle()).reconciliation_clean

    class Pending(Flat):
        async def read(self, account_id):
            pending = replace(
                (await super().read(account_id)).local,
                orders=(order(filled_quantity=0, state=OrderState.CANCEL_PENDING),),
            )
            return OptionsMonitorInput(pending, pending, (), ())

    assert "expiry_calendar_unverified" in (await monitor(source=Pending()).cycle()).reasons


async def test_bad_source_shape_and_backward_clock_are_denied():
    class Invalid(Source):
        async def read(self, account_id):
            return {}

    assert "monitor_observation_failed" in (await monitor(source=Invalid()).cycle()).reasons
    clock = Clock()
    m = monitor(clock=clock)
    await m.cycle()
    clock.at = NOW - timedelta(seconds=1)
    assert "monitor_clock_regressed" in (await m.cycle()).reasons


def test_input_validation_rejects_duplicates_wrong_types_and_noncanonical_modes():
    for args in (
        (None, snapshot(), (), ()),
        (snapshot(), snapshot(), (), (calendar(), calendar())),
    ):
        with pytest.raises(ValueError):
            OptionsMonitorInput(*args)
    with pytest.raises(ValueError):
        monitor(loaded=None)
    equity = load_config(
        Path("configs/base.yaml"),
        Path("configs/paper.yaml"),
        Path("configs/safety-envelope.yaml"),
        environ={},
    )
    with pytest.raises(ValueError):
        monitor(loaded=equity)


async def test_scheduler_repeats_after_configured_cadence_and_stops():
    stop = asyncio.Event()

    class TwoCycles(Store):
        async def persist(self, result):
            await super().persist(result)
            if len(self.rows) == 2:
                stop.set()

    fast = load_config(
        Path("configs/base.yaml"),
        Path("configs/options/simulation.yaml"),
        Path("configs/safety-envelope.yaml"),
        environ={"TRADING_BOT__SCHEDULER__EQUITY_RECONCILIATION_CADENCE_SECONDS": "1"},
    )
    store = TwoCycles()
    await asyncio.wait_for(monitor(store=store, loaded=fast).run(stop), 3)
    assert (
        len(store.rows) == 2 and store.rows[0].reconciliation_id != store.rows[1].reconciliation_id
    )


async def test_status_ages_source_time_not_the_time_of_last_poll():
    clock = Clock()
    age = loaded().config.freshness.max_account_snapshot_age_seconds

    class Aging(Source):
        async def read(self, account_id):
            old = snapshot(observed_at=NOW - timedelta(seconds=float(age) - 1), orders=(), fills=())
            return OptionsMonitorInput(old, old, (owned(),), (calendar(),))

    m = monitor(source=Aging(), clock=clock)
    assert (await m.cycle()).reconciliation_clean
    clock.at += timedelta(seconds=2)
    assert not m.status().reconciliation_clean
    assert "monitor_observation_stale" in m.status().reasons


async def test_clock_rollback_after_observation_is_detected_above_source_timestamp():
    clock, store = Clock(), Store()
    clock.at = NOW + timedelta(seconds=10)
    m = monitor(clock=clock, store=store)
    assert (await m.cycle()).reconciliation_clean
    clock.at = NOW + timedelta(seconds=5)
    assert "monitor_clock_regressed" in m.status().reasons
    assert not (await m.cycle()).reconciliation_clean
    assert not store.rows[-1].clean
    # Catching up alone cannot remove an already-observed clock incident.
    clock.at = NOW + timedelta(seconds=10)
    assert "monitor_clock_regressed" in m.status().reasons


async def test_clock_rollback_during_persistence_is_a_durable_incident():
    clock = Clock()
    clock.at = NOW + timedelta(seconds=10)

    class RegressingStore(Store):
        async def persist(self, result):
            await super().persist(result)
            clock.at = NOW + timedelta(seconds=5)

    store = RegressingStore()
    result = await monitor(clock=clock, store=store).cycle()
    assert not result.reconciliation_clean
    assert "monitor_clock_regressed" in result.reasons
    assert len(store.rows) == 2 and not store.rows[-1].clean
