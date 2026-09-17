from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from decimal import Decimal

import pytest

from trading_bot.domain import AssetClass, OrderEvent, OrderState, OrderType, TimeInForce
from trading_bot.simulation.lifecycle_models import LifecycleValidationError

from ._lifecycle_fixtures import ORIGIN, control, execution, make_request


@pytest.mark.parametrize(
    "changes",
    [
        {"events": []},
        {"cash": 1.0},
        {"cash": Decimal("-1")},
        {"order": object()},
        {"position": object()},
        {"submitted": object()},
        {"cash": Decimal("NaN")},
        {"cash": Decimal("1e600")},
    ],
)
def test_request_rejects_invalid_shapes(changes):
    with pytest.raises(LifecycleValidationError):
        replace(make_request(), **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"state": OrderState.SUBMITTED},
        {"filled_quantity": Decimal("0.5")},
        {"order_type": OrderType.MARKET, "limit_price": None},
        {"time_in_force": TimeInForce.IMMEDIATE_OR_CANCEL},
        {"updated_at": ORIGIN + timedelta(seconds=1)},
        {"requested_quantity": Decimal("1e600")},
    ],
)
def test_request_rejects_unsupported_initial_orders(changes):
    request = make_request()
    with pytest.raises(LifecycleValidationError):
        replace(request, order=replace(request.order, **changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"account_id": "other-synthetic"},
        {"instrument_id": "OTHER"},
        {"asset_class": AssetClass.PREDICTION},
        {"quantity": Decimal("1"), "average_price": None},
        {"average_price": Decimal("100")},
        {"market_value": Decimal("1")},
        {"observed_at": ORIGIN + timedelta(seconds=1)},
    ],
)
def test_request_rejects_inconsistent_initial_position(changes):
    request = make_request()
    with pytest.raises(LifecycleValidationError):
        replace(request, position=replace(request.position, **changes))


@pytest.mark.parametrize(
    "event",
    [
        OrderEvent.FILL,
        OrderEvent.PARTIAL_FILL,
        OrderEvent.CANCEL_REJECTED,
        OrderEvent.BROKER_AMBIGUOUS,
        OrderEvent.RECONCILE_FILLED,
    ],
)
def test_controls_cannot_invent_fill_or_reconciliation(event):
    with pytest.raises(LifecycleValidationError):
        control("event", 1, event)


def test_fill_time_must_match_cursor():
    event = execution("fill", 2, "1")
    with pytest.raises(LifecycleValidationError):
        replace(event, fill=replace(event.fill, occurred_at=ORIGIN))


def test_request_and_events_are_immutable():
    request = make_request((control("accept", 1, OrderEvent.BROKER_ACCEPTED),))
    with pytest.raises(FrozenInstanceError):
        request.cash = Decimal("0")
    with pytest.raises(FrozenInstanceError):
        request.events[0].event_id = "changed"


def test_invalid_input_errors_do_not_render_objects():
    class Unsafe:
        def __repr__(self):
            raise AssertionError("representation must not be called")

    with pytest.raises(LifecycleValidationError) as caught:
        replace(make_request(), cash=Unsafe())
    assert str(caught.value) == "lifecycle_input_invalid"
    assert caught.value.__suppress_context__
