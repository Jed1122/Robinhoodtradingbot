"""Bounded read-only options monitoring; clean observations never enable entries.

No broker adapter, authentication, migration or order-changing operation is created.
Sources must supply complete normalized observations; the only provided composition
is credential-free. Existing durable reconciliation storage and scheduler are reused.
"""

import asyncio
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal, Protocol
from uuid import uuid4

from trading_bot.clock import Clock, require_utc
from trading_bot.config import LoadedConfig
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.config.loader import enforce_safety_envelope
from trading_bot.config.models import AppConfig
from trading_bot.domain import AccountId, ExecutionMode, OrderState
from trading_bot.domain.decimal_utils import DomainValidationError
from trading_bot.domain.options_account import (
    OptionsAccountSnapshot,
    OwnedOptionPosition,
    observation_id,
    observation_rows,
)
from trading_bot.lifecycle.options_expiry import OptionExpiryCalendar, assess_option_expiry
from trading_bot.market_data.recording import content_hash
from trading_bot.monitoring.alerts import Alert, AlertSink, AlertType
from trading_bot.reconciliation.models import ReconciliationDifference, ReconciliationResult
from trading_bot.reconciliation.options import reconcile_options
from trading_bot.reconciliation.service import ReconciliationStore
from trading_bot.runtime.scheduler import ScheduledJob, Scheduler


@dataclass(frozen=True, slots=True)
class OptionsMonitorInput:
    local: OptionsAccountSnapshot
    broker: OptionsAccountSnapshot
    owned_positions: tuple[OwnedOptionPosition, ...]
    calendars: tuple[OptionExpiryCalendar, ...]

    def __post_init__(self) -> None:
        if (
            type(self.local) is not OptionsAccountSnapshot
            or type(self.broker) is not OptionsAccountSnapshot
        ):
            raise DomainValidationError("exact options snapshots required")
        observation_rows(self.owned_positions, OwnedOptionPosition)
        observation_rows(self.calendars, OptionExpiryCalendar)
        if len({item.contract_id for item in self.calendars}) != len(self.calendars):
            raise DomainValidationError("duplicate expiry calendar")


class OptionsObservationSource(Protocol):
    async def read(self, account_id: AccountId) -> OptionsMonitorInput: ...


@dataclass(frozen=True, slots=True)
class OptionsMonitorStatus:
    reconciliation_clean: bool
    reasons: tuple[str, ...]
    last_observed_at: datetime | None
    last_persisted_at: datetime | None
    paused: Literal[True] = field(default=True, init=False)
    entry_enabled: Literal[False] = field(default=False, init=False)
    live_supported: Literal[False] = field(default=False, init=False)


def _with_expiry(data: OptionsMonitorInput, result: ReconciliationResult) -> ReconciliationResult:
    calendars = {item.contract_id: item for item in data.calendars}
    active = {
        leg.contract.contract_id
        for position in data.owned_positions
        for leg in position.structure.legs
    }
    for snapshot in (data.local, data.broker):
        active.update(
            row.contract_id
            for row in snapshot.positions
            if row.quantity
            or row.pending_exercise
            or row.pending_assignment
            or row.pending_expiration
        )
        for order in snapshot.orders:
            if order.state not in (
                OrderState.FILLED,
                OrderState.CANCELED,
                OrderState.REJECTED,
                OrderState.RISK_REJECTED,
                OrderState.EXPIRED,
            ):
                active.update(leg.contract_id for leg in order.legs)
        active.update(row.contract_id for row in snapshot.settlements if not row.completed)
    differences = list(result.differences)
    # Evaluate both contracts when their identities conflict; don't choose the one
    # with the later deadline merely because it arrived last.
    contracts = {row for snapshot in (data.local, data.broker) for row in snapshot.contracts}
    for contract in sorted(contracts, key=lambda row: (row.contract_id, row.data_hash)):
        if contract.contract_id not in active:
            continue
        assessment = assess_option_expiry(
            contract=contract,
            calendar=calendars.get(contract.contract_id),
            as_of=result.observed_at,
            has_exposure=True,
        )
        differences.extend(
            ReconciliationDifference(reason, contract.contract_id, None, None)
            for reason in assessment.reasons
        )
    return replace(result, clean=not differences, differences=tuple(differences))


class PausedOptionsMonitor:
    """One serialized observation cycle per instance, with bounded I/O and alerts.

    This is not the execution owner and holds no execution lease or write capability.
    The shared equity reconciliation cadence is reused for this options-underlying
    monitor until a separately reviewed production schedule is configured.
    """

    def __init__(
        self,
        *,
        account_id: AccountId,
        loaded: LoadedConfig,
        source: OptionsObservationSource,
        store: ReconciliationStore,
        alerts: AlertSink,
        clock: Clock,
    ) -> None:
        observation_id(account_id)
        if type(loaded) is not LoadedConfig:
            raise DomainValidationError("canonical loaded configuration required")
        config = AppConfig.model_validate(loaded.config.model_dump())
        enforce_safety_envelope(config, loaded.safety_envelope)
        canonical, digest = hash_loaded_config(config, loaded.safety_envelope)
        if (canonical, digest) != (loaded.canonical_json, loaded.config_hash):
            raise DomainValidationError("configuration identity mismatch")
        if not config.options.enabled or config.mode not in (
            ExecutionMode.BACKTEST,
            ExecutionMode.SIMULATION,
            ExecutionMode.PAPER,
        ):
            raise DomainValidationError("only offline options monitoring is implemented")
        self._account, self._config = account_id, config
        self._source, self._store, self._alerts, self._clock = source, store, alerts, clock
        self._scheduler = Scheduler()
        self._job = ScheduledJob(
            "options_observation",
            timedelta(seconds=config.scheduler.equity_reconciliation_cadence_seconds),
        )
        self._status = OptionsMonitorStatus(False, ("not_observed",), None, None)
        self._clock_high_water = require_utc(clock.now())
        self._clock_regressed = False

    def _read_clock(self) -> datetime:
        now = require_utc(self._clock.now())
        if now < self._clock_high_water:
            # Latched for this observer's lifetime. Reaching the old time again is
            # not evidence that the clock fault was investigated or repaired.
            self._clock_regressed = True
        self._clock_high_water = max(self._clock_high_water, now)
        return now

    def status(self) -> OptionsMonitorStatus:
        now = self._read_clock()
        result = self._status
        if self._clock_regressed:
            result = replace(
                result,
                reconciliation_clean=False,
                reasons=tuple(dict.fromkeys((*result.reasons, "monitor_clock_regressed"))),
            )
        if result.last_observed_at is not None:
            age = Decimal(str((now - result.last_observed_at).total_seconds()))
            if age < 0:
                result = replace(
                    result,
                    reconciliation_clean=False,
                    reasons=(*result.reasons, "monitor_clock_regressed"),
                )
            elif age > self._config.freshness.max_account_snapshot_age_seconds:
                result = replace(
                    result,
                    reconciliation_clean=False,
                    reasons=(*result.reasons, "monitor_observation_stale"),
                )
        return result

    async def _observe(self) -> None:
        previous = self._status
        self._status = replace(
            previous, reconciliation_clean=False, reasons=("monitor_cycle_running",)
        )
        reasons: tuple[str, ...]
        observed_at, persisted_at = previous.last_observed_at, previous.last_persisted_at
        clean = False
        stage = "observation"
        try:
            async with asyncio.timeout(float(self._config.runtime.broker_timeout_seconds)):
                data = await self._source.read(self._account)
                if type(data) is not OptionsMonitorInput:
                    raise DomainValidationError("exact options monitor input required")
                evaluated_at = self._read_clock()
                observed_at = min(data.local.observed_at, data.broker.observed_at)
                result = reconcile_options(
                    account_id=self._account,
                    local=data.local,
                    broker=data.broker,
                    owned_positions=data.owned_positions,
                    as_of=evaluated_at,
                    max_age_seconds=self._config.freshness.max_account_snapshot_age_seconds,
                    # Versioned input binding preserves legacy result/store schemas.
                    # Callers must retain the corresponding immutable source artifacts.
                    reconciliation_id=f"options-observation-v1-{content_hash(data)}-{uuid4().hex}",
                )
                if self._clock_regressed:
                    result = replace(
                        result,
                        clean=False,
                        differences=(
                            *result.differences,
                            ReconciliationDifference(
                                "monitor_clock_regressed", "clock", None, None
                            ),
                        ),
                    )
                result = _with_expiry(data, result)
                stage = "persistence"
                await self._store.persist(result)
                persisted_at = self._read_clock()
                if self._clock_regressed and not any(
                    item.code == "monitor_clock_regressed" for item in result.differences
                ):
                    # The initial result is immutable. Append a distinct incident
                    # if the fault happened during its write, bounded by this cycle.
                    result = replace(
                        result,
                        clean=False,
                        reconciliation_id=f"{result.reconciliation_id}-clock-{uuid4().hex}",
                        observed_at=persisted_at,
                        differences=(
                            *result.differences,
                            ReconciliationDifference(
                                "monitor_clock_regressed", "clock", None, None
                            ),
                        ),
                    )
                    await self._store.persist(result)
                    persisted_at = self._read_clock()
                clean = result.clean
                reasons = tuple(dict.fromkeys(item.code for item in result.differences))
        except Exception:  # Provider/DB exceptions can contain secrets; never echo them.
            reasons = (f"monitor_{stage}_failed",)
        self._status = OptionsMonitorStatus(clean, reasons, observed_at, persisted_at)
        self._status = self.status()
        if self._status.reasons:
            try:
                async with asyncio.timeout(float(self._config.monitoring.webhook_timeout_seconds)):
                    await self._alerts.send(
                        Alert(
                            AlertType.BROKER_DISAGREEMENT,
                            "options_monitor_requires_attention",
                            require_utc(self._clock.now()),
                        )
                    )
            except Exception:
                self._status = replace(
                    self._status,
                    reconciliation_clean=False,
                    reasons=(*self._status.reasons, "monitor_alert_failed"),
                )

    async def cycle(self) -> OptionsMonitorStatus:
        ran = await self._scheduler.run(self._job, self._observe)
        if not ran:
            return replace(
                self.status(), reconciliation_clean=False, reasons=("monitor_cycle_running",)
            )
        return self.status()

    async def run(self, stop: asyncio.Event) -> None:
        """Continuous monitor; cancellable between bounded cycles, never starts entries."""
        while not stop.is_set():
            await self.cycle()
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._job.interval.total_seconds())
            except TimeoutError:
                continue
