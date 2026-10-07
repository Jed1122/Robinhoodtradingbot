"""Commit local execution/accounting facts before their private cost projection.

This seam has no broker capability, provider mapper, authentication or operational
lease. A trusted execution owner must supply those separately. Financial facts
and optional diagnostic receipts cannot be made atomic across SQLite and files:
the journal is authoritative, and missing receipts remain missing after restart.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Literal, Protocol

from trading_bot.accounting import (
    EconomicEvent,
    Execution,
    decode_economic_event,
    encode_economic_event,
)
from trading_bot.domain import AccountId
from trading_bot.domain.owned_order_lifecycle import OwnedOrderEvent
from trading_bot.execution.service import UnitOfWorkFactory


class OwnedExecutionObserver(Protocol):
    async def observed(self, event: OwnedOrderEvent) -> None: ...


class CommittedCostRecordingError(ValueError):
    def __init__(self) -> None:
        super().__init__("committed_cost_recording_invalid")


@dataclass(frozen=True, slots=True)
class CommittedCostOutcome:
    committed_new: bool
    receipt_status: Literal["recorded", "duplicate_not_resampled", "receipt_unavailable"]
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)


class CommittedCostRecording:
    """Single-process serialization, not a multi-process execution writer lease.

    Accounting commit uncertainty latches this instance for reconciliation. A
    receipt failure disables this observer but never rolls back committed fills
    or prevents later valid financial facts from reaching the economic journal.
    Already committed events are never assigned new execution receipt clocks.
    """

    def __init__(
        self,
        *,
        account_id: AccountId,
        uow_factory: UnitOfWorkFactory,
        observer: OwnedExecutionObserver,
    ) -> None:
        if type(account_id) is not str or not account_id.strip() or len(account_id) > 255:
            raise CommittedCostRecordingError()
        self._account_id = account_id
        self._uow_factory = uow_factory
        self._observer = observer
        self._uncertain = False
        self._receipt_failed = False
        self._lock = asyncio.Lock()

    async def publish(self, event: EconomicEvent) -> CommittedCostOutcome:
        try:
            # Freeze before even waiting for another publisher's lock. Caller
            # mutation while queued must not substitute a different local fact.
            event = decode_economic_event(encode_economic_event(event))
            if event.account_id != self._account_id or type(event.payload) is not Execution:
                raise CommittedCostRecordingError()
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            self._uncertain = True
            raise CommittedCostRecordingError() from None
        async with self._lock:
            if self._uncertain:
                raise CommittedCostRecordingError()
            try:
                async with self._uow_factory() as uow:
                    changed = await uow.economics.append(event)
                    await uow.commit()
            except BaseException as error:
                self._uncertain = True
                if not isinstance(error, Exception):
                    raise
                raise CommittedCostRecordingError() from None
            if not changed:
                return CommittedCostOutcome(False, "duplicate_not_resampled")
            if self._receipt_failed:
                return CommittedCostOutcome(True, "receipt_unavailable")
            try:
                await self._observer.observed(event.payload.event)
            except BaseException as error:
                self._receipt_failed = True
                if not isinstance(error, Exception):
                    raise
                return CommittedCostOutcome(True, "receipt_unavailable")
            return CommittedCostOutcome(True, "recorded")
