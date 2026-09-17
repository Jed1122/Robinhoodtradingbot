from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_bot.domain import (
    AccountId,
    AssetClass,
    BrokerOrder,
    BrokerOrderId,
    DataHash,
    Fill,
    FillId,
    InstrumentId,
    OrderEvent,
    OrderId,
    OrderPurpose,
    OrderState,
    OrderType,
    Position,
    Side,
    TimeInForce,
)
from trading_bot.simulation.events import EventCursor
from trading_bot.simulation.lifecycle_models import (
    LifecycleControlEvent,
    LifecycleEvent,
    LifecycleFillEvent,
    LifecycleRequest,
)

ORIGIN = datetime(2026, 9, 17, tzinfo=UTC)
ACCOUNT = AccountId("synthetic-account")
INSTRUMENT = InstrumentId("SYNTH-USD")
BROKER_ORDER = BrokerOrderId("synthetic-order")


def make_request(
    events: tuple[LifecycleEvent, ...] = (),
    *,
    side: Side = Side.BUY,
    quantity: str = "1",
    cash: str = "1000",
    position_quantity: str = "0",
    average_price: str | None = None,
) -> LifecycleRequest:
    return LifecycleRequest(
        BrokerOrder(
            OrderId("synthetic-local"),
            BROKER_ORDER,
            ACCOUNT,
            None,
            None,
            INSTRUMENT,
            side,
            OrderPurpose.ENTRY if side is Side.BUY else OrderPurpose.STRATEGY_EXIT,
            OrderType.LIMIT,
            TimeInForce.GOOD_TIL_CANCELED,
            Decimal(quantity),
            Decimal("0"),
            Decimal("100"),
            None,
            OrderState.SUBMISSION_PENDING,
            ORIGIN,
            ORIGIN,
            DataHash("a" * 64),
        ),
        Position(
            ACCOUNT,
            INSTRUMENT,
            AssetClass.CRYPTO,
            Decimal(position_quantity),
            None if average_price is None else Decimal(average_price),
            Decimal("0"),
            ORIGIN,
            DataHash("b" * 64),
        ),
        Decimal(cash),
        EventCursor(0, ORIGIN),
        events,
    )


def control(event_id: str, sequence: int, event: OrderEvent) -> LifecycleControlEvent:
    return LifecycleControlEvent(
        event_id,
        EventCursor(sequence, ORIGIN + timedelta(seconds=sequence)),
        ACCOUNT,
        INSTRUMENT,
        BROKER_ORDER,
        event,
    )


def execution(
    event_id: str,
    sequence: int,
    quantity: str,
    *,
    price: str = "100",
    fee: str = "0.01",
    side: Side = Side.BUY,
) -> LifecycleFillEvent:
    timestamp = ORIGIN + timedelta(seconds=sequence)
    return LifecycleFillEvent(
        event_id,
        EventCursor(sequence, timestamp),
        Fill(
            FillId(event_id),
            BROKER_ORDER,
            ACCOUNT,
            INSTRUMENT,
            side,
            Decimal(quantity),
            Decimal(price),
            Decimal(fee),
            timestamp,
            DataHash("c" * 64),
        ),
    )
