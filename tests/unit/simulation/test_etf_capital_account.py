"""Independent synthetic cash/settlement expectations, never customer evidence."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from trading_bot.domain import AssetClass, BrokerOrderId, InstrumentId, OrderEvent, OrderId, Side
from trading_bot.simulation.events import EventCursor
from trading_bot.simulation.lifecycle_models import LifecycleFillEvent

from ._lifecycle_fixtures import ORIGIN, control, execution, make_request


def opening(sequence=0, side=Side.BUY, cash="100", held="0", symbol="SPY"):
    from trading_bot.simulation.etf_capital_account import CapitalAccountSubmission

    at = ORIGIN + timedelta(seconds=sequence)
    request = make_request(
        side=side,
        quantity=".2" if side is Side.BUY else held,
        cash=cash,
        position_quantity=held,
        average_price="99" if held != "0" else None,
    )
    instrument = InstrumentId("capital-research:" + symbol)
    order = replace(
        request.order,
        id=OrderId(f"order-{sequence}"),
        broker_order_id=BrokerOrderId(f"broker-{sequence}"),
        instrument_id=instrument,
        created_at=at,
        updated_at=at,
    )
    position = replace(
        request.position, instrument_id=instrument, asset_class=AssetClass.EQUITY, observed_at=at
    )
    return CapitalAccountSubmission(
        symbol,
        replace(request, order=order, position=position, submitted=EventCursor(sequence, at)),
        D(".10"),
    )


def observation(submit, event):
    identity = dict(
        instrument_id=submit.request.order.instrument_id,
        broker_order_id=submit.request.order.broker_order_id,
    )
    if isinstance(event, LifecycleFillEvent):
        return replace(event, fill=replace(event.fill, **identity))
    return replace(event, **identity)


def script():
    from trading_bot.simulation.etf_capital_account import CapitalFeesFinal, CapitalSaleSettlement

    buy = opening()
    sell = opening(5, Side.SELL, "90.06", ".1")
    return (
        buy,
        observation(buy, control("accepted-buy", 1, OrderEvent.BROKER_ACCEPTED)),
        observation(buy, execution("buy-fill", 2, ".1", price="99", fee=".04")),
        observation(buy, control("cancel-buy", 3, OrderEvent.REQUEST_CANCEL)),
        observation(buy, control("cancelled-buy", 4, OrderEvent.CANCEL_CONFIRMED)),
        sell,
        observation(sell, control("accepted-sell", 6, OrderEvent.BROKER_ACCEPTED)),
        observation(sell, execution("sell-fill", 7, ".1", price="101", fee=".05", side=Side.SELL)),
        CapitalSaleSettlement(
            "settle-sale", EventCursor(8, ORIGIN + timedelta(seconds=8)), "sell-fill"
        ),
        CapitalFeesFinal("final-fees", EventCursor(9, ORIGIN + timedelta(seconds=9)), D(".09")),
    )


def replay(events, capital=D("100")):
    from trading_bot.simulation.etf_capital_account import replay_capital_account

    return replay_capital_account(initial_cash=capital, events=events)


@pytest.mark.parametrize(
    "length,cash,available,quantity,fees,unsettled,complete",
    [
        (0, "100", "100", "0", "0", "0", True),
        (1, "100", "79.90", "0", "0", "0", False),
        (3, "90.06", "80.00", ".1", ".04", "0", False),
        (5, "90.06", "90.00", ".1", ".04", "0", False),
        (8, "100.11", "90.05", "0", ".09", "10.05", False),
        (9, "100.11", "100.10", "0", ".09", "0", False),
        (10, "100.11", "100.11", "0", ".09", "0", True),
    ],
)
def test_literal_cash_reservations_and_finality(
    length, cash, available, quantity, fees, unsettled, complete
):
    result = replay(script()[:length])
    assert (
        result.cash,
        result.available_cash,
        result.quantity,
        result.fees,
        result.unsettled_proceeds,
    ) == tuple(map(D, (cash, available, quantity, fees, unsettled)))
    assert result.complete is complete
    assert result.execution_enabled is False
    assert result.evidence_promotable is False


def test_duplicate_delivery_is_not_a_second_cash_flow():
    events = script()
    result = replay((*events[:3], events[2], *events[3:]))
    assert result.cash == D("100.11")
    assert result.economic_hash == replay(events).economic_hash


def test_restart_reconstruction_and_full_prefix_identity():
    events = script()
    for index in range(len(events) + 1):
        assert replay(events[:index]) == replay(tuple(events[:index]))
        assert replay((*events[:index], *events[index:])) == replay(events)


@pytest.mark.parametrize(
    "events",
    [
        lambda: (opening(), opening(1, symbol="QQQ")),
        lambda: (*script()[:5], opening(5, symbol="QQQ", cash="90.06")),
        lambda: (*script()[:3], replace(script()[2], fill=replace(script()[2].fill, fee=D(".05")))),
        lambda: (*script()[:8], script()[9]),
        lambda: (*script()[:9], replace(script()[9], total_fees=D("0"))),
        lambda: (*script()[:3], replace(script()[1], event_id="stale-new-event")),
    ],
)
def test_conflicting_or_incomplete_history_denies(events):
    with pytest.raises(ValueError):
        replay(events())


def test_new_symbol_requires_completed_previous_episode():
    result = replay((*script(), opening(10, cash="100.11", symbol="QQQ")))
    assert result.cash == D("100.11")
    assert result.quantity == 0
    assert not result.complete


def test_original_submission_invariants_are_not_reset_by_copying():
    value = opening()
    object.__setattr__(value, "execution_enabled", True)
    with pytest.raises(ValueError):
        replay((value,))


@pytest.mark.parametrize(
    "field,value",
    [
        ("symbol", "BAD"),
        ("symbol", 1),
        ("request", None),
        ("episode_fee_bound", None),
    ],
)
def test_invalid_original_submission_denies(field, value):
    item = opening()
    object.__setattr__(item, field, value)
    with pytest.raises(ValueError):
        replay((item,))


@pytest.mark.parametrize("case", ["embedded-events", "instrument", "asset", "cash", "quantity"])
def test_submission_cannot_invent_initial_facts(case):
    item = opening()
    request = item.request
    if case == "embedded-events":
        request = replace(
            request, events=(observation(item, control("accept", 1, OrderEvent.BROKER_ACCEPTED)),)
        )
    elif case == "instrument":
        request = replace(
            request,
            order=replace(request.order, instrument_id=InstrumentId("QQQ")),
            position=replace(request.position, instrument_id=InstrumentId("QQQ")),
        )
    elif case == "asset":
        request = replace(
            request, position=replace(request.position, asset_class=AssetClass.CRYPTO)
        )
    elif case == "cash":
        request = replace(request, cash=D("101"))
    else:
        request = replace(
            request, position=replace(request.position, quantity=D(".1"), average_price=D("99"))
        )
    object.__setattr__(item, "request", request)
    with pytest.raises(ValueError):
        replay((item,))


@pytest.mark.parametrize("kind", ["account", "basis", "symbol", "fee", "oversell", "reused-order"])
def test_exit_requires_same_current_account_position_and_fee_bound(kind):
    events = script()
    item = events[5]
    request = item.request
    if kind == "account":
        request = replace(
            request,
            order=replace(request.order, account_id="other"),
            position=replace(request.position, account_id="other"),
        )
    elif kind == "basis":
        request = replace(request, position=replace(request.position, average_price=D("98")))
    elif kind == "symbol":
        item = opening(5, Side.SELL, "90.06", ".1", "QQQ")
        request = item.request
    elif kind == "fee":
        object.__setattr__(item, "episode_fee_bound", D(".2"))
    elif kind == "oversell":
        request = replace(request, order=replace(request.order, requested_quantity=D(".2")))
    else:
        request = replace(
            request,
            order=replace(request.order, broker_order_id=events[0].request.order.broker_order_id),
        )
    object.__setattr__(item, "request", request)
    with pytest.raises(ValueError):
        replay((*events[:5], item))


def test_invalid_envelopes_and_observations_deny():
    from trading_bot.simulation.etf_capital_account import CapitalFeesFinal, CapitalSaleSettlement

    cursor = EventCursor(0, ORIGIN)
    for events, capital in [
        ((), D("101")),
        ([], D("100")),
        ((None,), D("100")),
        ((opening(),) * 4097, D("100")),
        ((script()[1],), D("100")),
        ((CapitalSaleSettlement("unknown", cursor, "absent"),), D("100")),
    ]:
        with pytest.raises(ValueError):
            replay(events, capital)
    for constructor, args in [
        (CapitalFeesFinal, ("", cursor, D("0"))),
        (CapitalSaleSettlement, ("id", cursor, "")),
    ]:
        with pytest.raises(ValueError):
            constructor(*args)


def test_second_sale_fill_id_cannot_reuse_prior_execution_identity():
    events = script()
    changed = replace(events[7], fill=replace(events[7].fill, id="buy-fill"))
    with pytest.raises(ValueError):
        replay((*events[:7], changed))


def test_fee_overrun_and_negative_available_cash_deny_entire_prefix():
    events = script()
    changed = replace(events[2], fill=replace(events[2].fill, fee=D(".11")))
    with pytest.raises(ValueError):
        replay((*events[:2], changed))
    huge = opening()
    object.__setattr__(
        huge,
        "request",
        replace(huge.request, order=replace(huge.request.order, requested_quantity=D("2"))),
    )
    with pytest.raises(ValueError):
        replay((huge,))


def test_out_of_process_reconstruction_matches_partial_and_completed_prefixes():
    import json
    import subprocess
    import sys

    for length in (3, 8, 10):
        body = (
            "import json; "
            "from tests.unit.simulation.test_etf_capital_account import replay, script; "
            f"r=replay(script()[:{length}]); "
            "print(json.dumps([str(r.cash),str(r.available_cash),r.economic_hash,r.complete]))"
        )
        child = subprocess.run(
            [sys.executable, "-c", body], capture_output=True, text=True, check=True, timeout=30
        )
        result = replay(script()[:length])
        assert json.loads(child.stdout) == [
            str(result.cash),
            str(result.available_cash),
            result.economic_hash,
            result.complete,
        ]
