"""Literal reservation expectations; no broker or actual customer records."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal as D
from decimal import Rounded, localcontext

import pytest

from trading_bot.domain import (
    AccountId,
    BrokerOrder,
    BrokerOrderId,
    DataHash,
    InstrumentId,
    OrderId,
    OrderPurpose,
    OrderState,
    OrderType,
    Side,
    TimeInForce,
)


def order(state=OrderState.SUBMISSION_PENDING, filled="0", **changes):
    at = datetime(2026, 10, 8, tzinfo=UTC)
    return replace(
        BrokerOrder(
            OrderId("synthetic:order"),
            BrokerOrderId("synthetic:broker"),
            AccountId("synthetic:account"),
            None,
            None,
            InstrumentId("synthetic:SPY"),
            Side.BUY,
            OrderPurpose.ENTRY,
            OrderType.LIMIT,
            TimeInForce.GOOD_FOR_DAY,
            D(".2"),
            D(filled),
            D("100"),
            None,
            state,
            at,
            at,
            DataHash("a" * 64),
        ),
        **changes,
    )


def reserve(value=None, **changes):
    from trading_bot.simulation.etf_capital_funding import capital_order_reservation

    arguments = dict(
        order=value or order(),
        episode_fee_bound=D(".10"),
        episode_fees=D("0"),
        episode_fees_final=False,
        held_quantity=D("0"),
    )
    arguments.update(changes)
    return capital_order_reservation(**arguments)


def test_pending_entry_reserves_full_notional_and_episode_fee():
    result = reserve()
    assert result.pending_notional == D("20")
    assert result.fee_reservation == D(".10")
    assert result.total_reservation == D("20.10")
    assert result.execution_enabled is False
    assert result.evidence_promotable is False


def test_partial_fill_retains_remaining_limit_notional_and_unused_episode_fees():
    result = reserve(
        order(OrderState.PARTIALLY_FILLED, ".1"), episode_fees=D(".04"), held_quantity=D(".1")
    )
    assert result.pending_notional == D("10")
    assert result.fee_reservation == D(".06")
    assert result.total_reservation == D("10.06")


@pytest.mark.parametrize("state", [OrderState.CANCELED, OrderState.EXPIRED])
def test_terminal_partial_entry_releases_only_unfilled_notional(state):
    result = reserve(order(state, ".1"), episode_fees=D(".04"), held_quantity=D(".1"))
    assert result.pending_notional == D("0")
    assert result.total_reservation == D(".06")


def test_ambiguous_acceptance_preserves_pending_capacity():
    result = reserve(
        order(OrderState.UNKNOWN_REQUIRES_RECONCILIATION, ".1"),
        episode_fees=D(".04"),
        held_quantity=D(".1"),
    )
    assert result.total_reservation == D("10.06")


def test_cancel_pending_race_keeps_unfilled_capacity():
    result = reserve(
        order(OrderState.CANCEL_PENDING, ".1"), episode_fees=D(".04"), held_quantity=D(".1")
    )
    assert result.total_reservation == D("10.06")


def test_explicit_flat_terminal_fee_finality_releases_unused_fee_bound():
    assert reserve(order(OrderState.CANCELED), episode_fees_final=True).total_reservation == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"episode_fees": D(".11")},
        {"episode_fee_bound": None},
        {"episode_fees_final": 1},
        {"episode_fees_final": True},
        {"held_quantity": D("-.1")},
    ],
)
def test_unknown_overrun_or_invalid_fee_state_denies(changes):
    with pytest.raises(ValueError, match="capital_funding_invalid"):
        reserve(**changes)


def test_fee_finality_cannot_release_held_position_capacity():
    with pytest.raises(ValueError, match="capital_funding_invalid"):
        reserve(order(OrderState.FILLED, ".2"), held_quantity=D(".2"), episode_fees_final=True)


def test_unsettled_proceeds_and_remaining_fees_are_not_buying_power():
    from trading_bot.simulation.etf_capital_funding import capital_available_cash

    active = reserve(
        order(OrderState.PARTIALLY_FILLED, ".1"), episode_fees=D(".04"), held_quantity=D(".1")
    )
    assert capital_available_cash(D("90.06"), D("0"), active) == D("80.00")
    canceled = reserve(
        order(OrderState.CANCELED, ".1"), episode_fees=D(".04"), held_quantity=D(".1")
    )
    assert capital_available_cash(D("90.06"), D("0"), canceled) == D("90.00")
    closed = reserve(order(OrderState.FILLED, ".2"), episode_fees=D(".09"))
    assert capital_available_cash(D("100.11"), D("10.05"), closed) == D("90.05")


def test_mutated_original_flags_deny_before_available_cash_is_returned():
    from trading_bot.simulation.etf_capital_funding import capital_available_cash

    value = reserve()
    object.__setattr__(value, "execution_enabled", True)
    with pytest.raises(ValueError, match="capital_funding_invalid"):
        capital_available_cash(D("100"), D("0"), value)


def test_insufficient_cash_or_invalid_unsettled_amount_is_not_clamped():
    from trading_bot.simulation.etf_capital_funding import capital_available_cash

    for cash, unsettled in [(D("20"), D("0")), (D("100"), D("101"))]:
        with pytest.raises(ValueError, match="capital_funding_invalid"):
            capital_available_cash(cash, unsettled, reserve())


def test_reservation_identity_binds_fee_facts_even_when_capacity_matches():
    first = reserve(episode_fee_bound=D(".10"), episode_fees=D(".04"))
    second = reserve(episode_fee_bound=D(".20"), episode_fees=D(".14"))
    assert first.total_reservation == second.total_reservation
    assert first.reservation_hash != second.reservation_hash


def test_held_quantity_is_bound_even_for_equal_cash_reservations():
    assert reserve(held_quantity=D(".1")).reservation_hash != reserve().reservation_hash


def test_active_sell_cannot_reserve_more_shares_than_remain_held():
    sale = order(side=Side.SELL, purpose=OrderPurpose.STRATEGY_EXIT)
    with pytest.raises(ValueError, match="capital_funding_invalid"):
        reserve(sale, held_quantity=D(".1"))


def test_sale_reserves_fees_but_does_not_spend_limit_notional():
    sale = order(side=Side.SELL, purpose=OrderPurpose.STRATEGY_EXIT)
    result = reserve(sale, held_quantity=D(".2"), episode_fees=D(".04"))
    assert result.pending_notional == 0
    assert result.total_reservation == D(".06")


def test_fixed_context_preserves_literal_cash_under_harsh_ambient_context():
    from trading_bot.simulation.etf_capital_funding import capital_available_cash

    with localcontext() as context:
        context.prec = 2
        context.traps[Rounded] = True
        result = reserve()
        assert capital_available_cash(D("100"), D("0"), result) == D("79.90")
        assert len(result.reservation_hash) == 64


def test_inconsistent_output_reservation_cannot_be_constructed():
    with pytest.raises(ValueError, match="capital_funding_invalid"):
        replace(reserve(), total_reservation=D("0"))


@pytest.mark.parametrize("field", ["execution_enabled", "evidence_promotable"])
def test_equality_equivalent_output_flags_deny_at_hash_boundary(field):
    value = reserve()
    object.__setattr__(value, field, 0)
    with pytest.raises(ValueError, match="capital_funding_invalid"):
        _ = value.reservation_hash


def test_only_supported_limit_lifecycle_states_can_produce_capacity():
    for value in [
        order(OrderState.PROPOSED),
        order(OrderState.SUBMISSION_PENDING, ".1"),
        order(order_type=OrderType.MARKET, limit_price=None),
    ]:
        with pytest.raises(ValueError, match="capital_funding_invalid"):
            reserve(value)


def test_nonreservation_input_denies_instead_of_returning_available_cash():
    from trading_bot.simulation.etf_capital_funding import capital_available_cash

    with pytest.raises(ValueError, match="capital_funding_invalid"):
        capital_available_cash(D("100"), D("0"), None)


def test_original_order_mutation_is_validated_not_normalized():
    value = order()
    object.__setattr__(value, "filled_quantity", D(".3"))
    with pytest.raises(ValueError, match="capital_funding_invalid"):
        reserve(value)
