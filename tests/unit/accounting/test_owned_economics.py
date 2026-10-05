"""Independent fixture money; no source qualification or broker transport."""

import importlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

import pytest

from trading_bot.domain import (
    AccountId,
    AssetClass,
    BrokerOrder,
    BrokerOrderId,
    ConfigHash,
    DataHash,
    Fill,
    FillId,
    InstrumentId,
    OrderEvent,
    OrderId,
    OrderIntent,
    OrderIntentId,
    OrderPurpose,
    OrderState,
    OrderType,
    Side,
    TimeInForce,
)
from trading_bot.domain.owned_order_lifecycle import OwnedOrderEvent

NOW = datetime(2026, 10, 5, 14, tzinfo=UTC)
HASH = "a" * 64


def api():
    try:
        return importlib.import_module("trading_bot.accounting")
    except ModuleNotFoundError:
        pytest.fail("independent economic owner API not implemented")


def intent(*, closing=False, index=1, quantity="0.10", limit="101"):
    return OrderIntent(
        OrderIntentId(f"intent-{index}"),
        AccountId("fixture-account"),
        InstrumentId("fixture-spy"),
        AssetClass.EQUITY,
        Side.SELL if closing else Side.BUY,
        OrderPurpose.STRATEGY_EXIT if closing else OrderPurpose.ENTRY,
        OrderType.LIMIT,
        TimeInForce.GOOD_FOR_DAY,
        Decimal(quantity),
        Decimal(limit),
        None,
        NOW,
        NOW + timedelta(days=1),
        "fixed-20-100",
        ConfigHash(HASH),
        DataHash(HASH),
        "fixture-exit-v1",
    )


def order(i):
    return BrokerOrder(
        OrderId(str(i.id).replace("intent", "order")),
        BrokerOrderId(str(i.id).replace("intent", "broker")),
        i.account_id,
        i.id,
        None,
        i.instrument_id,
        i.side,
        i.purpose,
        i.order_type,
        i.time_in_force,
        i.quantity,
        Decimal(0),
        i.limit_price,
        None,
        OrderState.SUBMITTED,
        NOW,
        NOW,
        DataHash(HASH),
    )


def fact(i, *, index, qty=None, price="100", fee="0.02", kind=OrderEvent.PARTIAL_FILL):
    b = order(i)
    at = NOW + timedelta(seconds=index)
    f = (
        None
        if qty is None
        else Fill(
            FillId(f"fill-{index}"),
            b.broker_order_id,
            b.account_id,
            b.instrument_id,
            b.side,
            Decimal(qty),
            Decimal(price),
            Decimal(fee),
            at,
            DataHash(HASH),
        )
    )
    return OwnedOrderEvent(
        f"owned-{index}",
        b.id,
        kind,
        at,
        DataHash(HASH),
        f,
        None if f is None else f"native-{index}",
        None if f is None else 0,
    )


def event(a, payload, index):
    return a.EconomicEvent(
        f"economic-{index}",
        AccountId("fixture-account"),
        NOW + timedelta(seconds=index),
        DataHash(HASH),
        ConfigHash(HASH),
        payload,
    )


def opening(a):
    return event(a, a.Opening(InstrumentId("fixture-spy"), Decimal("500")), 0)


def reserved(a, i=None):
    i = intent() if i is None else i
    return (
        opening(a),
        event(a, a.Reserve(i, "episode-1", Decimal("0.05"), Decimal("10.15")), 1),
        event(a, a.Bind(order(i)), 2),
    )


def partial(a):
    return (*reserved(a), event(a, a.Execution(fact(intent(), index=3, qty="0.04")), 3))


def canceled(a):
    return (
        *partial(a),
        event(a, a.Execution(fact(intent(), index=4, kind=OrderEvent.REQUEST_CANCEL)), 4),
        event(a, a.Execution(fact(intent(), index=5, kind=OrderEvent.CANCEL_CONFIRMED)), 5),
    )


def test_reservation_is_independent_of_opening_cash_and_trial():
    a = api()
    s = a.project_economics(reserved(a))
    assert s.settled_cash == Decimal("500")
    assert s.book_cash == Decimal("500")
    assert s.available_cash == Decimal("489.85")
    assert s.position.quantity == 0
    assert s.trial.reserved_risk == Decimal("10.15")
    assert s.trial.remaining(Decimal("50")) == Decimal("39.85")
    assert not s.source_qualified and not s.cost_qualified
    assert not s.execution_enabled and not s.evidence_promotable


def test_partial_fill_retains_signed_payable_and_reduces_only_actual_hold():
    a = api()
    s = a.project_economics(partial(a))
    assert s.book_cash == Decimal("495.98")
    assert s.settled_cash == Decimal("500")
    assert s.position.quantity == Decimal("0.04")
    assert s.position.average_price == Decimal("100")
    assert s.orders[0].cash_hold == Decimal("6.09")
    assert s.obligations[0].amount == Decimal("-4.02")
    assert s.available_cash == Decimal("489.89")
    assert s.trial.reserved_risk == Decimal("10.15")


def test_cancel_terminal_does_not_release_unsettled_or_unknown_fees():
    a = api()
    events = canceled(a)
    assert a.project_economics(events).orders[0].cash_hold == Decimal("6.09")
    with pytest.raises(a.EconomicError):
        a.project_economics((*events, event(a, a.Release(OrderId("order-1")), 6)))
    final = event(a, a.FinalFees(OrderId("order-1"), Decimal("0.02")), 6)
    with pytest.raises(a.EconomicError):
        a.project_economics((*events, final, event(a, a.Release(OrderId("order-1")), 7)))
    settled = event(a, a.Settlement("fill-3", Decimal("-4.02")), 7)
    s = a.project_economics((*events, final, settled, event(a, a.Release(OrderId("order-1")), 8)))
    assert s.settled_cash == Decimal("495.98")
    assert s.available_cash == Decimal("495.98")
    assert s.position.quantity == Decimal("0.04")
    assert s.trial.reserved_risk == Decimal("10.15")


def test_final_fee_difference_charged_once_and_requires_own_settlement():
    a = api()
    events = (*canceled(a), event(a, a.FinalFees(OrderId("order-1"), Decimal("0.04")), 6))
    s = a.project_economics(events)
    assert s.book_cash == Decimal("495.96")
    assert sorted(x.amount for x in s.obligations) == [Decimal("-4.02"), Decimal("-0.02")]
    with pytest.raises(a.EconomicError):
        a.project_economics(
            (*events, event(a, a.FinalFees(OrderId("order-1"), Decimal("0.04")), 7))
        )
    assert a.project_economics((*events, events[-1])).book_cash == Decimal("495.96")


@pytest.mark.parametrize("change", ["fees", "settlement", "funding", "opening", "side"])
def test_invalid_facts_deny_without_silent_normalization(change):
    a = api()
    events = canceled(a)
    payload = {
        "fees": a.FinalFees(OrderId("order-1"), Decimal("0.06")),
        "settlement": a.Settlement("fill-3", Decimal("4.02")),
        "funding": a.Funding(Decimal("-500")),
        "opening": a.Opening(InstrumentId("fixture-spy"), Decimal("500")),
        "side": a.Reserve(intent(index=2), "episode-2", Decimal("0.05"), Decimal("10.15")),
    }[change]
    with pytest.raises(a.EconomicError, match=r"^owned_economics_invalid$"):
        a.project_economics((*events, event(a, payload, 6)))


def test_codec_requires_canonical_versioned_complete_shape():
    a = api()
    for original in partial(a):
        encoded = a.encode_economic_event(original)
        assert a.decode_economic_event(encoded) == original
        raw = json.loads(encoded)
        raw["unused"] = "ignored?"
        with pytest.raises(a.EconomicError):
            a.decode_economic_event(json.dumps(raw, sort_keys=True, separators=(",", ":")))
    with pytest.raises(a.EconomicError):
        a.decode_economic_event("{}")


def test_projection_is_context_independent_and_rejects_conflicting_identity():
    a = api()
    with localcontext() as context:
        context.prec = 2
        s = a.project_economics(partial(a))
    assert s.book_cash == Decimal("495.98")
    changed = replace(partial(a)[-1], source_hash=DataHash("b" * 64))
    with pytest.raises(a.EconomicError):
        a.project_economics((*partial(a), changed))


def test_flat_terminal_still_requires_explicit_episode_completion():
    a = api()
    i = intent(closing=True, index=2, quantity="0.04", limit="99")
    events = (
        *canceled(a),
        event(a, a.FinalFees(OrderId("order-1"), Decimal("0.02")), 6),
        event(a, a.Settlement("fill-3", Decimal("-4.02")), 7),
        event(a, a.Release(OrderId("order-1")), 8),
        event(a, a.Reserve(i, "episode-1", Decimal("0.02"), Decimal("10.15")), 9),
        event(a, a.Bind(order(i)), 10),
        event(
            a,
            a.Execution(
                fact(i, index=11, qty="0.04", price="99", fee="0.02", kind=OrderEvent.FILL)
            ),
            11,
        ),
        event(a, a.FinalFees(OrderId("order-2"), Decimal("0.02")), 12),
        event(a, a.Settlement("fill-11", Decimal("3.94")), 13),
        event(a, a.Release(OrderId("order-2")), 14),
    )
    s = a.project_economics(events)
    assert s.settled_cash == Decimal("499.92")
    assert s.position.quantity == 0
    assert s.trial.reserved_risk == Decimal("10.15")
    completed = (*events, event(a, a.Complete("episode-1"), 15))
    s = a.project_economics(completed)
    assert s.trial.consumed_loss == Decimal("0.08")
    assert s.trial.remaining(Decimal("50")) == Decimal("49.92")
    s = a.project_economics((*completed, event(a, a.Funding(Decimal("100")), 16)))
    assert s.settled_cash == Decimal("599.92")
    assert s.trial.consumed_loss == Decimal("0.08")


def test_cancel_pending_race_does_not_release_actual_quantity():
    a = api()
    events = (
        *partial(a),
        event(a, a.Execution(fact(intent(), index=4, kind=OrderEvent.REQUEST_CANCEL)), 4),
    )
    race = fact(intent(), index=5, qty="0.01", fee="0.005")
    race = replace(race, occurrence_ordinal=1)
    s = a.project_economics((*events, event(a, a.Execution(race), 5)))
    assert s.book_cash == Decimal("494.975")
    assert s.position.quantity == Decimal("0.05")
    assert s.orders[0].cash_hold == Decimal("5.075")
    assert s.orders[0].order.state is OrderState.CANCEL_PENDING


@pytest.mark.parametrize("quantity", ["0.05", "0.03"])
def test_over_reserved_exit_shares_deny(quantity):
    a = api()
    one = intent(closing=True, index=2, quantity=quantity)
    two = intent(closing=True, index=3, quantity=quantity)
    events = (
        *partial(a),
        event(a, a.Reserve(one, "episode-1", Decimal("0.02"), Decimal("10.15")), 4),
    )
    with pytest.raises(a.EconomicError):
        a.project_economics(
            events
            if quantity == "0.05"
            else (
                *events,
                event(a, a.Reserve(two, "episode-1", Decimal("0.02"), Decimal("10.15")), 5),
            )
        )


@pytest.mark.parametrize(
    "mutation", ["account", "config", "instrument", "risk", "limit", "order", "time"]
)
def test_reservation_binding_or_order_chronology_denies(mutation):
    a = api()
    i = intent()
    events = reserved(a)
    if mutation == "account":
        bad = replace(events[1], account_id=AccountId("foreign"))
    elif mutation == "config":
        bad = replace(events[1], config_hash=ConfigHash("b" * 64))
    elif mutation == "instrument":
        bad = event(
            a,
            a.Reserve(
                replace(i, instrument_id=InstrumentId("foreign")),
                "episode-1",
                Decimal("0.05"),
                Decimal("10.15"),
            ),
            1,
        )
    elif mutation == "risk":
        with pytest.raises(a.EconomicError):
            event(a, a.Reserve(i, "episode-1", Decimal("0.05"), Decimal(0)), 1)
        return
    elif mutation == "limit":
        bad = event(a, a.Bind(replace(order(i), limit_price=Decimal("100"))), 2)
    elif mutation == "order":
        bad = event(a, a.Bind(replace(order(i), intent_id=OrderIntentId("missing"))), 2)
    else:
        bad = replace(events[2], occurred_at=NOW)
    prefix = events[:2] if mutation in {"limit", "order", "time"} else events[:1]
    with pytest.raises(a.EconomicError):
        a.project_economics((*prefix, bad))


@pytest.mark.parametrize("cash", ["10", "0"])
def test_insufficient_cash_reservation_denies(cash):
    a = api()
    start = event(a, a.Opening(InstrumentId("fixture-spy"), Decimal(cash)), 0)
    with pytest.raises(a.EconomicError):
        a.project_economics((start, reserved(a)[1]))


@pytest.mark.parametrize(
    "payload", ["nan", "float", "unknown", "bad_id", "bad_hash", "bad_utc", "bad_kind"]
)
def test_event_validation_sanitizes_untrusted_values(payload):
    a = api()
    changes = {"payload": a.Funding(Decimal(0))}
    if payload == "nan":
        changes["payload"] = a.Funding(Decimal("NaN"))
    elif payload == "float":
        changes["payload"] = a.Funding(1.1)
    elif payload in {"unknown", "bad_kind"}:
        changes["payload"] = object()
    elif payload == "bad_id":
        changes["id"] = " "
    elif payload == "bad_hash":
        changes["source_hash"] = "not-a-hash"
    elif payload == "bad_utc":
        changes["occurred_at"] = NOW.replace(tzinfo=None)
    with pytest.raises(a.EconomicError, match=r"^owned_economics_invalid$"):
        replace(opening(a), **changes)


@pytest.mark.parametrize("text", ["null", "[]", "1", "{", " " * 16385])
def test_decoder_rejects_malformed_bounded_payload(text):
    a = api()
    with pytest.raises(a.EconomicError):
        a.decode_economic_event(text)


@pytest.mark.parametrize("field", ["version", "kind", "amount", "extra"])
def test_decoder_rejects_noncanonical_shapes(field):
    a = api()
    raw = json.loads(a.encode_economic_event(event(a, a.Funding(Decimal("1")), 1)))
    if field == "amount":
        raw["payload"]["amount"] = 1
    elif field == "extra":
        raw["payload"]["extra"] = True
    else:
        raw[field] = "unexpected"
    with pytest.raises(a.EconomicError):
        a.decode_economic_event(json.dumps(raw, sort_keys=True, separators=(",", ":")))


def test_money_that_needs_rounding_denies():
    a = api()
    events = (opening(a), event(a, a.Funding(Decimal("0.000000000000000000000000000001")), 1))
    with pytest.raises(a.EconomicError):
        a.project_economics(events)


def test_unknown_control_keeps_reservations_and_discovered_fill_applies_once():
    a = api()
    events = (
        *partial(a),
        event(a, a.Execution(fact(intent(), index=4, kind=OrderEvent.RECONCILIATION_DRIFT)), 4),
    )
    discovered = replace(
        fact(
            intent(),
            index=5,
            qty="0.06",
            price="100.50",
            fee="0.01",
            kind=OrderEvent.RECONCILE_FILLED,
        ),
        occurrence_ordinal=1,
    )
    final = event(a, a.Execution(discovered), 5)
    s = a.project_economics((*events, final, final))
    assert s.book_cash == Decimal("489.94")
    assert s.position.quantity == Decimal("0.10")
    assert s.position.average_price == Decimal("100.30")
    assert s.trial.reserved_risk == Decimal("10.15")
    with pytest.raises(a.EconomicError):
        a.project_economics((*events, final, replace(final, id="different-receipt")))


def test_bad_completion_and_double_settlement_never_infer_finality():
    a = api()
    with pytest.raises(a.EconomicError):
        a.project_economics((*partial(a), event(a, a.Complete("episode-1"), 4)))
    settled = event(a, a.Settlement("fill-3", Decimal("-4.02")), 4)
    s = a.project_economics((*partial(a), settled, settled))
    assert s.settled_cash == Decimal("495.98")
    with pytest.raises(a.EconomicError):
        a.project_economics((*partial(a), settled, replace(settled, id="second-settlement")))


def test_history_capacity_never_returns_a_truncated_prefix():
    a = api()
    with pytest.raises(a.EconomicError):
        a.project_economics((opening(a),) * 10001)
    with pytest.raises(a.EconomicError):
        a.project_economics(())


def test_every_closed_payload_roundtrips_without_inventing_finality():
    a = api()
    payloads = (
        a.Opening(InstrumentId("fixture-spy"), Decimal(0)),
        a.Reserve(intent(), "episode-1", Decimal(0), Decimal(1)),
        a.Bind(order(intent())),
        a.Execution(fact(intent(), index=3, qty="0.04")),
        a.FinalFees(OrderId("order-1"), Decimal(0)),
        a.Settlement("fill-3", Decimal(0)),
        a.Release(OrderId("order-1")),
        a.Complete("episode-1"),
        a.Funding(Decimal(0)),
    )
    for index, payload in enumerate(payloads):
        original = event(a, payload, 3 if type(payload) is a.Execution else index)
        assert a.decode_economic_event(a.encode_economic_event(original)) == original


@pytest.mark.parametrize("kind", ["intent", "market", "order", "filled", "execution", "clock"])
def test_closed_payload_cannot_replace_typed_ownership(kind):
    a = api()
    if kind == "intent":
        payload = a.Reserve({}, "ep", Decimal(0), Decimal(1))
    elif kind == "market":
        payload = a.Reserve(
            replace(intent(), order_type=OrderType.MARKET, limit_price=None),
            "ep",
            Decimal(0),
            Decimal(1),
        )
    elif kind == "order":
        payload = a.Bind({})
    elif kind == "filled":
        payload = a.Bind(
            replace(order(intent()), state=OrderState.FILLED, filled_quantity=Decimal("0.10"))
        )
    elif kind == "execution":
        payload = a.Execution({})
    else:
        payload = a.Execution(fact(intent(), index=3, qty="0.04"))
    with pytest.raises(a.EconomicError):
        event(a, payload, 2)


@pytest.mark.parametrize("change", ["native", "ordinal"])
def test_partial_fill_identity_cannot_apply_twice(change):
    a = api()
    next_fill = replace(fact(intent(), index=4, qty="0.01", fee="0.005"), occurrence_ordinal=1)
    if change == "native":
        next_fill = replace(next_fill, external_execution_key="native-3")
    else:
        next_fill = replace(next_fill, occurrence_ordinal=9)
    with pytest.raises(a.EconomicError):
        a.project_economics((*partial(a), event(a, a.Execution(next_fill), 4)))


def test_bounded_fee_event_identity_keeps_its_obligation_settleable():
    a = api()
    fee_event = replace(event(a, a.FinalFees(OrderId("order-1"), Decimal("0.04")), 6), id="f" * 255)
    events = (*canceled(a), fee_event)
    state = a.project_economics(events)
    for index, obligation in enumerate(state.obligations, start=7):
        events = (*events, event(a, a.Settlement(obligation.id, obligation.amount), index))
    state = a.project_economics((*events, event(a, a.Release(OrderId("order-1")), 9)))
    assert state.settled_cash == Decimal("495.96")
    assert state.available_cash == Decimal("495.96")
