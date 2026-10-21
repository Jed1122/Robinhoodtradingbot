"""Durable bounded research/report scheduling, with no brokerage transport."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from trading_bot.clock import require_utc
from trading_bot.config.hybrid import HybridSettings
from trading_bot.hybrid.inputs import ResearchInputs, present_research
from trading_bot.hybrid.models import Account, JobRecord, ReportRecord


class Journal(Protocol):
    async def read(self) -> Account: ...

    async def change(
        self,
        event_id: str,
        kind: str,
        request: dict[str, object],
        transition: Callable[[Account], Account],
    ) -> Account: ...


async def run_due_jobs(owner: Journal, policy: HybridSettings, now: datetime) -> int:
    require_utc(now)
    state = await owner.read()
    if state.paused or state.kill_switch:
        return 0
    buckets = {
        "market_screen": int(now.timestamp()) // (policy.screening_minutes * 60),
        "daily_report": now.date().isoformat(),
        "weekly_fundamentals": f"{now.isocalendar().year}-{now.isocalendar().week}",
        "monthly_review": f"{now.year}-{now.month}",
    }
    for name, bucket in buckets.items():

        def transition(account: Account, job_name: str = name) -> Account:
            if account.paused or account.kill_switch:
                return account
            research = (
                present_research(ResearchInputs.model_validate_json(account.research_json), now)
                if account.research_json
                else None
            )
            # Descriptive analysis is deliberately distinct from strategy qualification.
            record = JobRecord(
                name=job_name,
                status="completed" if research is not None else "blocked",
                updated_at=now,
                reason=(
                    "Descriptive analysis completed; sources remain unqualified"
                    if research is not None
                    else "Research inputs unavailable; no order proposed"
                ),
            )
            jobs = (
                *(job for job in account.jobs if job.name != job_name),
                record,
            )
            reports = account.reports
            if job_name == "daily_report":
                reports = (
                    *reports[-89:],
                    ReportRecord(
                        name=f"Daily report {now.date()}",
                        created_at=now,
                        status="insufficient_evidence",
                        detail="Experimental account only. "
                        "No qualified signals or benchmark series. "
                        "Operating cost is declared separately; taxes remain estimates.",
                    ),
                )
            return Account.model_validate(account.model_dump() | {"jobs": jobs, "reports": reports})

        await owner.change(
            f"job:{name}:{bucket}", "job", {"name": name, "bucket": bucket}, transition
        )
    return len(buckets)


async def worker_loop(owner: Journal, policy: HybridSettings) -> None:
    while True:
        await run_due_jobs(owner, policy, datetime.now(UTC))
        await asyncio.sleep(30)
