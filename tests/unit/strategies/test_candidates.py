import dataclasses
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from trading_bot.domain import ConfigHash, DataHash, ExecutionMode, InstrumentId
from trading_bot.strategies import (
    FeatureSnapshot,
    FeatureVector,
    StrategyAction,
    StrategyContext,
    StrategyDecision,
    StrategyNotAllowed,
    StrategyRegistry,
)

NOW = datetime(2026, 7, 17, tzinfo=UTC)


def context() -> StrategyContext:
    vector = FeatureVector(
        InstrumentId("AAPL"),
        NOW,
        (
            ("total_return_pct", Decimal("10")),
            ("moving_average_short", Decimal("105")),
            ("moving_average_long", Decimal("100")),
            ("breakout_high", Decimal("110")),
        ),
        DataHash("a" * 64),
    )
    snapshot = FeatureSnapshot(NOW, (vector,), DataHash("b" * 64))
    return StrategyContext(NOW, snapshot, ConfigHash("c" * 64), (InstrumentId("AAPL"),))


def test_strategy_emits_no_quantity_or_broker_order() -> None:
    fields = {field.name for field in dataclasses.fields(StrategyDecision)}
    assert "quantity" not in fields
    assert "order" not in fields


def test_momentum_candidate_is_deterministic_and_interpretable() -> None:
    strategy = StrategyRegistry().get("equity_momentum", mode=ExecutionMode.PAPER)
    decision = strategy.decide(context())[0]
    assert decision.action is StrategyAction.ENTER_LONG
    assert decision.reason_codes == ("momentum_confirmed",)


def test_mean_reversion_is_research_only() -> None:
    with pytest.raises(StrategyNotAllowed):
        StrategyRegistry().get("equity_mean_reversion", mode=ExecutionMode.PAPER)
