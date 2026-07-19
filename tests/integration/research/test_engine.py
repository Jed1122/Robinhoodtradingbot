from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.unit.research.test_validation import report
from trading_bot.research.engine import assess_and_persist
from trading_bot.research.validation import ResearchAcceptancePolicy


class Store:
    def __init__(self) -> None:
        self.values: list[tuple[object, object]] = []


    async def append(self, attestation: object, assessment: object) -> None:
        self.values.append((attestation, assessment))


@pytest.mark.asyncio
async def test_engine_persists_exact_strategy_attestation() -> None:
    store = Store()
    attestation = await assess_and_persist(
        report(),
        ResearchAcceptancePolicy(3, Decimal("50")),
        observed_at=datetime(2026, 7, 17, tzinfo=UTC),
        store=store,
    )
    assert attestation.eligible
    assert attestation.strategy_version == "strategy-v1"
    assert store.values[0][0] is attestation
