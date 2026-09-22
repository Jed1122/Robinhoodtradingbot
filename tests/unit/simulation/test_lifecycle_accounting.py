from dataclasses import replace
from decimal import ROUND_UP, Decimal, Inexact, localcontext

import pytest

from trading_bot.domain import DataHash, Side
from trading_bot.simulation.lifecycle_accounting import apply_lifecycle_fill
from trading_bot.simulation.lifecycle_codec import lifecycle_hash
from trading_bot.simulation.lifecycle_models import LifecycleSnapshot, LifecycleValidationError

from ._lifecycle_fixtures import execution, make_request


def snapshot(request=None):
    request = request or make_request()
    return LifecycleSnapshot(
        request.order,
        request.position,
        request.cash,
        Decimal("0"),
        request.order.requested_quantity,
        request.submitted,
        DataHash("d" * 64),
    )


def test_buy_accounting_uses_actual_quantity_and_fee():
    result = apply_lifecycle_fill(snapshot(), execution("fill", 2, "0.25").fill)
    assert result.position.quantity == Decimal("0.25")
    assert result.position.average_price == Decimal("100")
    assert result.position.market_value == Decimal("25")
    assert result.cash == Decimal("974.99")
    assert result.fees == Decimal("0.01")
    assert result.filled_quantity == Decimal("0.25")
    assert result.remaining_quantity == Decimal("0.75")


def test_sell_closes_position_and_credits_net_cash():
    initial = snapshot(
        make_request(
            side=Side.SELL,
            quantity="0.25",
            position_quantity="0.25",
            average_price="90",
        )
    )
    result = apply_lifecycle_fill(initial, execution("fill", 2, "0.25", side=Side.SELL).fill)
    assert result.position.quantity == 0
    assert result.position.average_price is None
    assert result.position.market_value == 0
    assert result.cash == Decimal("1024.99")
    assert result.remaining_quantity == 0


@pytest.mark.parametrize(
    "initial_request,event",
    [
        (make_request(cash="1"), execution("fill", 2, "1")),
        (make_request(), execution("fill", 2, "2")),
        (make_request(side=Side.SELL), execution("fill", 2, "1", side=Side.SELL)),
        (make_request(), execution("fill", 2, "1", price="101")),
        (
            make_request(side=Side.SELL, position_quantity="1", average_price="100"),
            execution("fill", 2, "1", price="99", side=Side.SELL),
        ),
        (make_request(cash="1e30"), execution("fill", 2, "0.25")),
    ],
)
def test_invalid_economics_fail_before_effects(initial_request, event):
    initial = snapshot(initial_request)
    with pytest.raises(LifecycleValidationError):
        apply_lifecycle_fill(initial, event.fill)
    assert initial.cash == initial_request.cash
    assert initial.position is initial_request.position


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_id", "other"),
        ("instrument_id", "other"),
        ("broker_order_id", "other"),
        ("side", Side.SELL),
    ],
)
def test_fill_identity_must_match_snapshot(field, value):
    fill = replace(execution("fill", 2, "0.25").fill, **{field: value})
    with pytest.raises(LifecycleValidationError):
        apply_lifecycle_fill(snapshot(), fill)


def test_average_rounding_is_fixed_and_money_remains_exact():
    initial = snapshot(make_request(position_quantity="2", average_price="1"))
    fill = execution("fill", 2, "1", price="2").fill
    with localcontext() as context:
        context.prec = 4
        context.rounding = ROUND_UP
        context.traps[Inexact] = True
        context.clear_flags()
        result = apply_lifecycle_fill(initial, fill)
        assert not any(context.flags.values())
    assert result.position.average_price == Decimal("1.333333333333333333333333333")
    assert result.cash == Decimal("997.99")
    assert result.position.market_value == Decimal("6")


def test_hashes_are_canonical_and_domain_separated():
    assert lifecycle_hash("event", Decimal("1.00")) == lifecycle_hash("event", Decimal("1"))
    assert lifecycle_hash("event", Decimal("1")) != lifecycle_hash("snapshot", Decimal("1"))
    assert lifecycle_hash("event", Decimal("1")) != lifecycle_hash("event", Decimal("2"))


def test_hash_rejects_unencodable_input_without_rendering():
    class Unsafe:
        def __repr__(self):
            raise AssertionError("do not render")

    with pytest.raises(LifecycleValidationError) as caught:
        lifecycle_hash("event", Unsafe())
    assert str(caught.value) == "lifecycle_hash_invalid"
