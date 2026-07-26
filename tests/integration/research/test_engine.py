from dataclasses import replace
from datetime import UTC, datetime

import pytest

from tests.unit.research.test_validation import PARAMETER_HASH, policy, report
from trading_bot.research.engine import assess_and_persist
from trading_bot.research.report import build_research_report


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
        policy(),
        observed_at=datetime(2026, 7, 17, tzinfo=UTC),
        store=store,
    )
    assert attestation.eligible
    assert (
        attestation.strategy_version
        == f"momentum:strategy-v1:{PARAMETER_HASH}"
    )
    assert store.values[0][0] is attestation


@pytest.mark.asyncio
async def test_statistically_eligible_dirty_code_stays_nonpromotable() -> None:
    store = Store()
    clean = report()
    dirty = build_research_report(
        replace(clean.run, code_clean=False),
        attempts=clean.attempts,
    )

    attestation = await assess_and_persist(
        dirty,
        policy(),
        observed_at=datetime(2026, 7, 17, tzinfo=UTC),
        store=store,
    )

    assert not store.values[0][1].eligible  # type: ignore[union-attr]
    assert not store.values[0][1].promotable  # type: ignore[union-attr]
    assert "code_identity_not_clean" in store.values[0][1].reason_codes  # type: ignore[union-attr]
    assert not attestation.eligible
