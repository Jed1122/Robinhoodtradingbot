from datetime import UTC, datetime
from decimal import Decimal

from trading_bot.domain import (
    AccountId,
    ConfigHash,
    DataHash,
    InstrumentId,
    PortfolioSnapshot,
)
from trading_bot.portfolio import ExitPolicy, PortfolioConstructor
from trading_bot.strategies import StrategyAction, StrategyDecision

NOW = datetime(2026, 7, 17, tzinfo=UTC)


def test_portfolio_targets_are_separate_from_orders_and_preserve_exit_policy() -> None:
    decision = StrategyDecision(
        InstrumentId("AAPL"),
        NOW,
        StrategyAction.ENTER_LONG,
        Decimal("2"),
        ("momentum_confirmed",),
        "momentum-v1",
        ConfigHash("a" * 64),
        DataHash("b" * 64),
    )
    snapshot = PortfolioSnapshot(
        AccountId("account"),
        (),
        Decimal("100"),
        Decimal("100"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        NOW,
        DataHash("c" * 64),
    )
    policy = ExitPolicy("atr-exit-v1", "atr", Decimal("2"), Decimal("2"), 20)
    target = PortfolioConstructor().construct(
        (decision,),
        snapshot,
        as_of=NOW,
        config_hash=ConfigHash("a" * 64),
        exposure_multiplier=Decimal("0.5"),
        exit_policy=policy,
    )
    assert target.positions[0].target_notional == Decimal("50")
    assert target.positions[0].exit_policy is policy
    assert not hasattr(target.positions[0], "order_type")
