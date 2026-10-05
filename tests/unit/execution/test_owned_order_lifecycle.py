"""Owned lifecycle tests use fictional identities and independently checked quantities."""

import importlib
import importlib.util
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

import pytest

from trading_bot.domain import (
    AccountId,
    BrokerOrder,
    BrokerOrderId,
    DataHash,
    Fill,
    FillId,
    InstrumentId,
    OrderEvent,
    OrderId,
    OrderIntentId,
    OrderPurpose,
    OrderState,
    OrderType,
    Side,
    TimeInForce,
)

NOW = datetime(2026, 10, 5, 14, tzinfo=UTC)
HASH = "a" * 64


def api():  # type: ignore[no-untyped-def]
    name = "trading_bot.domain.owned_order_lifecycle"
    assert importlib.util.find_spec(name) is not None, "owned lifecycle API not implemented"
    return importlib.import_module(name)


def order(**changes):  # type: ignore[no-untyped-def]
    return replace(
        BrokerOrder(
            id=OrderId("order-1"),
            broker_order_id=BrokerOrderId("broker-1"),
            account_id=AccountId("account-1"),
            intent_id=OrderIntentId("intent-1"),
            client_order_id=None,
            instrument_id=InstrumentId("instrument-1"),
            side=Side.BUY,
            purpose=OrderPurpose.ENTRY,
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.GOOD_FOR_DAY,
            requested_quantity=Decimal("1.25"),
            filled_quantity=Decimal("0"),
            limit_price=Decimal("10.50"),
            stop_price=None,
            state=OrderState.SUBMITTED,
            created_at=NOW,
            updated_at=NOW,
            data_hash=DataHash(HASH),
        ),
        **changes,
    )


def fill(**changes):  # type: ignore[no-untyped-def]
    return replace(
        Fill(
            id=FillId("fill-1"),
            broker_order_id=BrokerOrderId("broker-1"),
            account_id=AccountId("account-1"),
            instrument_id=InstrumentId("instrument-1"),
            side=Side.BUY,
            quantity=Decimal("0.25"),
            price=Decimal("10"),
            fee=Decimal("0.01"),
            occurred_at=NOW + timedelta(seconds=1),
            data_hash=DataHash(HASH),
        ),
        **changes,
    )


def fact(kind=OrderEvent.PARTIAL_FILL, **changes):  # type: ignore[no-untyped-def]
    fields = dict(
        id="event-1",
        order_id=OrderId("order-1"),
        event=kind,
        occurred_at=NOW + timedelta(seconds=1),
        data_hash=DataHash(HASH),
        fill=fill() if kind in {OrderEvent.PARTIAL_FILL, OrderEvent.FILL} else None,
        external_execution_key="native-1"
        if kind in {OrderEvent.PARTIAL_FILL, OrderEvent.FILL}
        else None,
        occurrence_ordinal=0 if kind in {OrderEvent.PARTIAL_FILL, OrderEvent.FILL} else None,
    )
    fields.update(changes)
    return api().OwnedOrderEvent(**fields)


def test_partial_full_and_codec_preserve_exact_facts() -> None:
    module = api()
    event = fact()
    first = module.advance_owned_order(order(), event)
    assert first.filled_quantity == Decimal("0.25")
    assert first.state is OrderState.PARTIALLY_FILLED
    final = fact(
        OrderEvent.FILL,
        id="event-2",
        fill=fill(
            id=FillId("fill-2"), quantity=Decimal("1"), occurred_at=NOW + timedelta(seconds=2)
        ),
        occurred_at=NOW + timedelta(seconds=2),
        external_execution_key="native-2",
        occurrence_ordinal=1,
    )
    result = module.advance_owned_order(first, final)
    assert result.filled_quantity == Decimal("1.25")
    assert result.state is OrderState.FILLED
    assert order().filled_quantity == Decimal("0")
    encoded = module.encode_owned_event(event)
    assert '"fee":"0.01"' in encoded
    assert module.decode_owned_event(encoded) == event
    assert module.encode_owned_event(module.decode_owned_event(encoded)) == encoded


def test_pending_cancel_fill_and_confirmation_preserve_quantity() -> None:
    module = api()
    pending = module.advance_owned_order(order(), fact(OrderEvent.REQUEST_CANCEL))
    raced = module.advance_owned_order(pending, fact())
    assert raced.state is OrderState.CANCEL_PENDING
    assert raced.filled_quantity == Decimal("0.25")
    canceled = module.advance_owned_order(raced, fact(OrderEvent.CANCEL_CONFIRMED))
    assert canceled.state is OrderState.CANCELED
    assert canceled.filled_quantity == Decimal("0.25")
    with pytest.raises(ValueError, match="owned_order_event_invalid"):
        module.advance_owned_order(canceled, fact())


@pytest.mark.parametrize(
    "changes",
    [
        {"order_id": OrderId("other")},
        {"fill": fill(account_id=AccountId("other"))},
        {"fill": fill(instrument_id=InstrumentId("other"))},
        {"fill": fill(broker_order_id=BrokerOrderId("other"))},
        {"fill": fill(side=Side.SELL)},
        {"fill": fill(price=Decimal("10.51"))},
        {"fill": fill(quantity=Decimal("2"))},
        {"occurred_at": NOW - timedelta(seconds=1)},
        {"fill": fill(occurred_at=NOW + timedelta(seconds=2))},
    ],
)
def test_invalid_owned_fact_denies_without_changing_order(changes: dict[str, object]) -> None:
    original = order()
    with pytest.raises(ValueError, match="owned_order_event_invalid"):
        api().advance_owned_order(original, fact(**changes))
    assert original.state is OrderState.SUBMITTED
    assert original.filled_quantity == Decimal("0")


@pytest.mark.parametrize("kind,qty", [(OrderEvent.FILL, "0.25"), (OrderEvent.PARTIAL_FILL, "1.25")])
def test_fill_event_must_match_actual_complete_quantity(kind: OrderEvent, qty: str) -> None:
    with pytest.raises(ValueError, match="owned_order_event_invalid"):
        api().advance_owned_order(order(), fact(kind, fill=fill(quantity=Decimal(qty))))


@pytest.mark.parametrize("quantity", [Decimal("0.25"), Decimal("1.25")])
def test_reconciliation_cannot_turn_any_actual_fill_into_rejection(quantity: Decimal) -> None:
    original = order(state=OrderState.UNKNOWN_REQUIRES_RECONCILIATION, filled_quantity=quantity)
    with pytest.raises(ValueError, match="owned_order_event_invalid"):
        api().advance_owned_order(original, fact(OrderEvent.RECONCILE_REJECTED))
    assert original.filled_quantity == quantity
    assert original.state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION


def test_zero_fill_unknown_order_may_reconcile_to_rejection() -> None:
    restored = api().advance_owned_order(
        order(state=OrderState.UNKNOWN_REQUIRES_RECONCILIATION), fact(OrderEvent.RECONCILE_REJECTED)
    )
    assert restored.state is OrderState.REJECTED
    assert restored.filled_quantity == Decimal("0")


@pytest.mark.parametrize(
    "changes",
    [
        {"fill": None},
        {"external_execution_key": None},
        {"occurrence_ordinal": None},
        {"occurrence_ordinal": True},
        {"occurrence_ordinal": -1},
        {"id": ""},
        {"external_execution_key": "x" * 256},
        {"data_hash": "bad"},
        {"event": OrderEvent.BROKER_ACCEPTED},
        {"occurred_at": NOW.replace(tzinfo=None)},
    ],
)
def test_invalid_envelopes_are_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="owned_order_event_invalid"):
        fact(**changes)


def test_missing_fee_and_mutated_values_do_not_serialize() -> None:
    module = api()
    invalid = fill()
    object.__setattr__(invalid, "fee", None)
    with pytest.raises(ValueError, match="owned_order_event_invalid"):
        fact(fill=invalid)
    event = fact()
    object.__setattr__(event, "data_hash", "bad")
    with pytest.raises(ValueError, match="owned_order_event_invalid"):
        module.encode_owned_event(event)


@pytest.mark.parametrize("payload", ["{}", "[]", "null", "{", '{"id":"a","id":"b"}'])
def test_invalid_codecs_are_sanitized(payload: str) -> None:
    with pytest.raises(ValueError, match="owned_order_event_invalid"):
        api().decode_owned_event(payload)


def test_reconciliation_cannot_invent_filled_quantity() -> None:
    module = api()
    unknown = module.advance_owned_order(order(), fact(OrderEvent.RECONCILIATION_DRIFT))
    with pytest.raises(ValueError, match="owned_order_event_invalid"):
        module.advance_owned_order(unknown, fact(OrderEvent.RECONCILE_FILLED))
    restored = module.advance_owned_order(unknown, fact(OrderEvent.RECONCILE_SUBMITTED))
    assert restored.state is OrderState.SUBMITTED
    assert restored.filled_quantity == Decimal("0")


def test_exact_quantity_arithmetic_is_independent_of_ambient_context() -> None:
    module = api()
    with localcontext() as context:
        context.prec = 1
        projected = module.advance_owned_order(order(), fact())
        assert projected.filled_quantity == Decimal("0.25")
        assert context.prec == 1
    huge = order(requested_quantity=Decimal("10000000000000000000000000000"))
    tiny = fill(quantity=Decimal("0.1"))
    with pytest.raises(ValueError, match="owned_order_event_invalid"):
        module.advance_owned_order(huge, fact(fill=tiny))


def test_deep_json_is_sanitized_before_it_can_escape_the_boundary() -> None:
    with pytest.raises(ValueError, match="owned_order_event_invalid"):
        api().decode_owned_event("[" * 7500 + "0" + "]" * 7500)


@pytest.mark.parametrize("bad", [None, "partial_fill", object()])
def test_event_type_and_control_payloads_are_exact(bad: object) -> None:
    with pytest.raises(ValueError, match="owned_order_event_invalid"):
        fact(event=bad)
    with pytest.raises(ValueError, match="owned_order_event_invalid"):
        fact(OrderEvent.REQUEST_CANCEL, fill=fill())


def test_codecs_deny_noncanonical_and_oversized_values() -> None:
    module = api()
    with pytest.raises(ValueError, match="owned_order_event_invalid"):
        module.encode_owned_event(object())
    with pytest.raises(ValueError, match="owned_order_event_invalid"):
        module.advance_owned_order(object(), fact())
    with pytest.raises(ValueError, match="owned_order_event_invalid"):
        module.decode_owned_event("x" * 16385)
    data = json.loads(module.encode_owned_event(fact()))
    for changes in ({"fill": []}, {"version": "unknown"}, {"extra": True}):
        with pytest.raises(ValueError, match="owned_order_event_invalid"):
            module.decode_owned_event(
                json.dumps(data | changes, sort_keys=True, separators=(",", ":"))
            )
    huge_fill = fill(
        id=FillId("😀" * 255),
        account_id=AccountId("😀" * 255),
        broker_order_id=BrokerOrderId("😀" * 255),
        instrument_id=InstrumentId("😀" * 255),
    )
    huge = fact(
        id="😀" * 255,
        order_id=OrderId("😀" * 255),
        external_execution_key="😀" * 255,
        fill=huge_fill,
    )
    with pytest.raises(ValueError, match="owned_order_event_invalid"):
        module.encode_owned_event(huge)


def test_reconcile_partial_and_canceled_cannot_clear_recorded_fills() -> None:
    module = api()
    partial = module.advance_owned_order(order(), fact())
    unknown = module.advance_owned_order(partial, fact(OrderEvent.RECONCILIATION_DRIFT))
    restored = module.advance_owned_order(unknown, fact(OrderEvent.RECONCILE_PARTIAL))
    assert restored.filled_quantity == Decimal("0.25")
    assert restored.state is OrderState.PARTIALLY_FILLED
    with pytest.raises(ValueError, match="owned_order_event_invalid"):
        module.advance_owned_order(unknown, fact(OrderEvent.RECONCILE_SUBMITTED))
    canceled = module.advance_owned_order(unknown, fact(OrderEvent.RECONCILE_CANCELED))
    assert canceled.state is OrderState.CANCELED
    assert canceled.filled_quantity == Decimal("0.25")
