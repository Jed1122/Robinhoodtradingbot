from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from trading_bot.domain import AccountId, CodeHash, ConfigHash, DataHash
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.persistence.lease import LeaseRepository, LeaseUnavailable, StaleFencingToken
from trading_bot.persistence.models import AccountRow

ROOT = Path(__file__).parents[3]
NOW = datetime(2026, 7, 17, tzinfo=UTC)


@dataclass
class Clock:
    current: datetime = NOW

    def now(self) -> datetime:
        return self.current


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    url = f"sqlite+aiosqlite:///{tmp_path / 'lease.sqlite3'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return url


@pytest.mark.asyncio
async def test_stale_fencing_token_cannot_renew(database_url: str) -> None:
    engine = create_engine(database_url)
    factory = async_session_factory(engine)
    async with factory.begin() as session:
        session.add(
            AccountRow(
                id="account-1",
                provider="fixture",
                provider_account_id="external",
                account_type="cash",
                provider_state="active",
                equity=Decimal("100"),
                cash=Decimal("100"),
                equity_buying_power=Decimal("100"),
                crypto_buying_power=None,
                prediction_buying_power=None,
                restricted=False,
                observed_at=NOW,
                data_hash=DataHash("a" * 64),
                config_hash=ConfigHash("b" * 64),
                code_hash=CodeHash("c" * 64),
            )
        )
    clock = Clock()
    repository = LeaseRepository(factory, clock, timedelta(seconds=1))
    first = await repository.acquire(AccountId("account-1"), owner="one")
    with pytest.raises(LeaseUnavailable):
        await repository.acquire(AccountId("account-1"), owner="other")
    renewed = await repository.renew(first)
    assert renewed.fencing_token == first.fencing_token
    clock.current += timedelta(seconds=2)
    second = await repository.take_over_expired(AccountId("account-1"), owner="two")
    with pytest.raises(StaleFencingToken):
        await repository.renew(first)
    assert second.fencing_token > first.fencing_token
    await repository.release(second)
    third = await repository.acquire(AccountId("account-1"), owner="one")
    assert third.fencing_token > second.fencing_token
    with pytest.raises(StaleFencingToken):
        await repository.renew(first)
    with pytest.raises(StaleFencingToken):
        await repository.release(second)
    await repository.release(third)
    with pytest.raises(StaleFencingToken):
        await repository.renew(third)
    await engine.dispose()
