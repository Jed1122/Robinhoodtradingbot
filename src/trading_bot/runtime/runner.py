"""Runtime state holder that always begins paused."""

from dataclasses import dataclass

from trading_bot.domain import RuntimeState


@dataclass(slots=True)
class RuntimeRunner:
    state: RuntimeState = RuntimeState.PAUSED

    def pause(self) -> None:
        self.state = RuntimeState.PAUSED


__all__ = ["RuntimeRunner"]
