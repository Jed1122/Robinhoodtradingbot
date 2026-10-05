"""Self-killed fictional SQLite worker; no broker or production state access."""

import asyncio
import os
import signal
import sys

from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.persistence.test_owned_economic_journal import execution_event
from tests.integration.persistence.test_unit_of_work import _make_uow
from trading_bot.persistence import create_engine
from trading_bot.persistence.models import OwnedEconomicEventRow, OwnedOrderEventRow


async def run(database_url: str, phase: str) -> None:
    engine = create_engine(database_url)
    flush = AsyncSession.flush

    async def interrupted_flush(self, objects=None):
        await flush(self, objects)
        kind = OwnedOrderEventRow if phase == "owned" else OwnedEconomicEventRow
        if phase != "committed" and objects and any(type(row) is kind for row in objects):
            os.kill(os.getpid(), signal.SIGKILL)

    AsyncSession.flush = interrupted_flush
    async with _make_uow(engine) as uow:
        await uow.economics.append(execution_event())
        await uow.commit()
        os.kill(os.getpid(), signal.SIGKILL)


if __name__ == "__main__":
    asyncio.run(run(sys.argv[1], sys.argv[2]))
