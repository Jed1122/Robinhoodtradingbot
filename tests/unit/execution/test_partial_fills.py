from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from trading_bot.domain import (
    AccountId,
    AssetClass,
    BrokerOrder,
    BrokerOrderId,
    DataHash,
    Fill,
    FillId,
    InstrumentId,
    OrderId,
    OrderPurpose,
    OrderState,
    OrderType,
    Position,
    Side,
    TimeInForce,
)
from trading_bot.execution.partial_fills import apply_fill


def test_partial_fill_updates_actual_not_requested_quantity() -> None:
    now = datetime(2026, 7, 17, tzinfo=UTC)
    position = Position(
        AccountId("a"),
        InstrumentId("BTC-USD"),
        AssetClass.CRYPTO,
        Decimal("0"),
        None,
        Decimal("0"),
        now,
        DataHash("a" * 64),
    )
    order = BrokerOrder(
        OrderId("o"),
        BrokerOrderId("bo"),
        AccountId("a"),
        None,
        None,
        InstrumentId("BTC-USD"),
        Side.BUY,
        OrderPurpose.ENTRY,
        OrderType.LIMIT,
        TimeInForce.GOOD_TIL_CANCELED,
        Decimal("1"),
        Decimal("0"),
        Decimal("100"),
        None,
        OrderState.SUBMITTED,
        now,
        now,
        DataHash("b" * 64),
    )
    fill = Fill(
        FillId("f"),
        BrokerOrderId("bo"),
        AccountId("a"),
        InstrumentId("BTC-USD"),
        Side.BUY,
        Decimal("0.25"),
        Decimal("100"),
        Decimal("0.01"),
        now,
        DataHash("c" * 64),
    )
    result = apply_fill(position=position, order=order, fill=fill)
    assert result.position.quantity == Decimal("0.25")
    assert result.remaining_quantity == Decimal("0.75")
    duplicate = apply_fill(
        position=position,
        order=order,
        fill=fill,
        applied_fill_ids=frozenset({"f"}),
    )
    assert not duplicate.applied
    with pytest.raises(ValueError, match="does not belong"):
        apply_fill(
            position=position,
            order=order,
            fill=replace(fill, broker_order_id=BrokerOrderId("other")),
        )
    with pytest.raises(ValueError, match="exceeds"):
        apply_fill(
            position=position,
            order=replace(
                order,
                filled_quantity=Decimal("0.9"),
                state=OrderState.PARTIALLY_FILLED,
            ),
            fill=fill,
        )
    sell_order = replace(
        order,
        side=Side.SELL,
        purpose=OrderPurpose.STRATEGY_EXIT,
        requested_quantity=Decimal("0.25"),
    )
    sell = replace(fill, side=Side.SELL, quantity=Decimal("0.25"))
    closed = apply_fill(position=result.position, order=sell_order, fill=sell)
    assert closed.position.quantity == 0
    assert closed.position.average_price is None
    assert closed.cash_delta == Decimal("24.99")
    with pytest.raises(ValueError, match="short position"):
        apply_fill(position=position, order=sell_order, fill=sell)
