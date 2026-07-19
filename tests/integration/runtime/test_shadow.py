from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest

from trading_bot.app import DecisionCycleRequest, DecisionCycleResult
from trading_bot.brokers.fake import FakeBroker
from trading_bot.domain import AccountId, AccountSnapshot, DataHash
from trading_bot.runtime.shadow import ShadowConfig, ShadowCycleEvidence, build_shadow_application


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self.value = now

    def now(self) -> datetime:
        return self.value


class Reads:
    def __init__(self, account: AccountSnapshot) -> None:
        self.account = account

    async def get_accounts(self):  # type: ignore[no-untyped-def]
        return (self.account,)

    async def get_account_state(self, account_id):  # type: ignore[no-untyped-def]
        return self.account

    async def get_positions(self, account_id):  # type: ignore[no-untyped-def]
        return ()

    async def get_open_orders(self, account_id):  # type: ignore[no-untyped-def]
        return ()


class Cycle:
    async def run_cycle(self, request):  # type: ignore[no-untyped-def]
        return cast(
            DecisionCycleResult,
            SimpleNamespace(
                market=SimpleNamespace(data_hash="d" * 64),
                order_outcomes=("simulated",),
            ),
        )


class Store:
    def __init__(self) -> None:
        self.items: list[ShadowCycleEvidence] = []

    async def append_shadow(self, evidence: ShadowCycleEvidence) -> None:
        self.items.append(evidence)


@pytest.mark.asyncio
async def test_fixture_shadow_records_nonpromotable_simulated_result() -> None:
    now = datetime(2026, 7, 17, tzinfo=UTC)
    account = AccountSnapshot(
        AccountId("allowed"), "active", Decimal("100"), Decimal("50"), (), False, now,
        DataHash("a" * 64),
    )
    fake = FakeBroker(account, FixedClock(now))
    store = Store()
    app = build_shadow_application(
        ShadowConfig(AccountId("allowed"), "200", "c" * 64, "e" * 64, True, True, True),
        Reads(account),  # type: ignore[arg-type]
        Cycle(),  # type: ignore[arg-type]
        fake,
        store,
        FixedClock(now),
    )
    request = cast(DecisionCycleRequest, SimpleNamespace(as_of=now))
    result = await app.run_cycle(request)
    assert result.simulated_outcomes == ("simulated",)
    assert not result.evidence_eligible
    assert store.items == [result]
