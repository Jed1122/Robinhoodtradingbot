from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.unit.execution._fixtures import make_intent
from tests.unit.execution.test_neutral_order_helpers import _make_submission
from trading_bot.brokers import FakeBroker
from trading_bot.domain import AccountId, AccountSnapshot, AssetBuyingPower, AssetClass, DataHash
from trading_bot.simulation import SimulatedClock

NOW = datetime(2026, 7, 16, 18, 0, tzinfo=UTC)


def account() -> AccountSnapshot:
    return AccountSnapshot(
        AccountId("paper-account"),
        "active",
        Decimal("100"),
        Decimal("100"),
        tuple(AssetBuyingPower(asset, Decimal("100")) for asset in AssetClass),
        False,
        NOW,
        DataHash("a" * 64),
    )


@pytest.mark.asyncio
async def test_fake_broker_placement_is_idempotent_by_persisted_key() -> None:
    broker = FakeBroker(account(), SimulatedClock(NOW))
    submission = _make_submission(make_intent())
    first = await broker.place_order(submission)
    second = await broker.place_order(submission)
    assert first == second
    assert len(await broker.get_open_orders(AccountId("paper-account"))) == 1
