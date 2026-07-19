"""Ordered durable shutdown without blanket liquidation."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from trading_bot.clock import Clock, require_utc
from trading_bot.domain import RuntimeState


@dataclass(frozen=True, slots=True)
class ShutdownResult:
    reason: str
    final_state: RuntimeState
    new_intents_blocked: bool
    state_persisted: bool
    reconciliation_complete: bool
    deadline_exceeded: bool


class ShutdownCoordinator:
    def __init__(
        self,
        *,
        clock: Clock,
        block_new_intents: Callable[[], None],
        stop_lease_renewal: Callable[[], Awaitable[None]],
        finish_transactions: Callable[[], Awaitable[None]],
        reconcile_inflight: Callable[[], Awaitable[bool]],
        persist_state: Callable[[RuntimeState, str], Awaitable[None]],
    ) -> None:
        self._clock = clock
        self._block = block_new_intents
        self._stop_lease = stop_lease_renewal
        self._finish_transactions = finish_transactions
        self._reconcile = reconcile_inflight
        self._persist = persist_state

    async def shutdown(self, reason: str, deadline: datetime) -> ShutdownResult:
        if not reason:
            raise ValueError("shutdown reason is required")
        require_utc(deadline)
        self._block()
        await self._stop_lease()
        await self._finish_transactions()
        reconciliation_complete = False
        if self._clock.now() < deadline:
            reconciliation_complete = await self._reconcile()
        await self._persist(RuntimeState.PAUSED, reason)
        exceeded = self._clock.now() >= deadline
        return ShutdownResult(
            reason,
            RuntimeState.PAUSED,
            True,
            True,
            reconciliation_complete,
            exceeded,
        )


__all__ = ["ShutdownCoordinator", "ShutdownResult"]
