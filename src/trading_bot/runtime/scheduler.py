from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True, slots=True)
class ScheduledJob:
    name: str
    interval: timedelta


@dataclass(frozen=True, slots=True)
class Schedule:
    jobs: tuple[ScheduledJob, ...]

    def job(self, name: str) -> ScheduledJob:
        return next(job for job in self.jobs if job.name == name)


def default_schedule() -> Schedule:
    return Schedule(
        (
            ScheduledJob("crypto_reconcile", timedelta(seconds=60)),
            ScheduledJob("equity_reconcile", timedelta(seconds=60)),
            ScheduledJob("heartbeat", timedelta(seconds=30)),
        )
    )


class Scheduler:
    def __init__(self) -> None:
        self._running: set[str] = set()

    async def run(self, job: ScheduledJob, action):  # type: ignore[no-untyped-def]
        if job.name in self._running:
            return False
        self._running.add(job.name)
        try:
            await action()
            return True
        finally:
            self._running.remove(job.name)


__all__ = ["Schedule", "ScheduledJob", "Scheduler", "default_schedule"]
