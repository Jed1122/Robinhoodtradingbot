from dataclasses import dataclass
from datetime import datetime

from trading_bot.domain import ExecutionMode, RuntimeState


@dataclass(frozen=True, slots=True)
class Heartbeat:
    process_id: int
    instance_id: str
    mode: ExecutionMode
    runtime_state: RuntimeState
    code_hash: str
    config_hash: str
    observed_at: datetime


class HeartbeatService:
    def __init__(self, store, clock):  # type: ignore[no-untyped-def]
        self._store, self._clock = store, clock

    async def tick(self, heartbeat: Heartbeat) -> None:
        await self._store.append(heartbeat)


__all__ = ["Heartbeat", "HeartbeatService"]
