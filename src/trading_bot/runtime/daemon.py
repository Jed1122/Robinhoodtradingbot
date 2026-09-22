from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RunClaim:
    acquired: bool
    fencing_token: int | None


class RunCoordinator:
    def __init__(self) -> None:
        self._claimed = False

    async def try_start(self) -> RunClaim:
        if self._claimed:
            return RunClaim(False, None)
        self._claimed = True
        return RunClaim(True, 1)


class DaemonApplication:
    def __init__(self, *, paused: bool = True) -> None:
        self.paused = paused

    async def run(self) -> None:
        return None


def build_daemon_application(*, paused: bool = True) -> DaemonApplication:
    return DaemonApplication(paused=paused)


__all__ = ["DaemonApplication", "RunClaim", "RunCoordinator", "build_daemon_application"]
