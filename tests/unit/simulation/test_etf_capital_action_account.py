"""Literal fictional corporate-action accounting; no provider observations."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from decimal import localcontext

import pytest

from trading_bot.domain import OrderEvent, Side
from trading_bot.simulation.events import EventCursor

from ._lifecycle_fixtures import ORIGIN, control, execution
from .test_etf_capital_account import observation, opening, script


def cursor(n):
    return EventCursor(n, ORIGIN + timedelta(seconds=n))


def action(kind="distribution", n=5, **changes):
    from trading_bot.simulation.etf_capital_account import (
        CapitalDistributionEntitled,
        CapitalDistributionPaid,
        CapitalSplitApplied,
    )

    common = dict(
        event_id=f"action-{n}",
        cursor=cursor(n),
        account_id=opening().request.order.account_id,
        opening_order_id="order-0",
        symbol="SPY",
    )
    if kind == "split":
        value = CapitalSplitApplied(
            **common,
            action_id="split-1",
            record_hash="a" * 64,
            ratio=D("2"),
            post_action_mark=D("49.5"),
        )
    elif kind == "payment":
        value = CapitalDistributionPaid(**common, entitlement_id="distribution-1", amount=D(".1"))
    else:
        value = CapitalDistributionEntitled(
            **common,
            action_id="distribution-1",
            record_hash="b" * 64,
            amount_per_share=D("1"),
            ex_mark=D("98"),
            pay_date=ORIGIN.date(),
        )
    return replace(value, **changes)


def replay(events):
    from trading_bot.simulation.etf_capital_account import replay_capital_action_account

    return replay_capital_action_account(initial_cash=D("100"), events=events)


def test_split_conserves_total_basis_cash_and_marked_equity():
    result = replay((*script()[:5], action("split")))
    assert (result.cash, result.quantity, result.average_price, result.marked_equity) == (
        D("90.06"),
        D(".2"),
        D("49.5"),
        D("99.96"),
    )
    assert result.available_cash == D("90.00")
    assert result.distribution_receivable == 0
    assert not result.complete and not result.execution_enabled and not result.evidence_promotable


def test_entitlement_and_ex_mark_are_atomic_without_spendable_receivable():
    result = replay((*script()[:5], action()))
    assert (
        result.cash,
        result.available_cash,
        result.distribution_receivable,
        result.marked_equity,
    ) == (D("90.06"), D("90.00"), D(".10"), D("99.96"))
    assert result.quantity == D(".1")


def test_payment_transfers_receivable_without_reinvestment_or_second_nav_gain():
    result = replay((*script()[:5], action(), action("payment", 6)))
    assert (
        result.cash,
        result.available_cash,
        result.distribution_receivable,
        result.marked_equity,
        result.quantity,
    ) == (D("90.16"), D("90.10"), D("0"), D("99.96"), D(".1"))
    assert replay((*script()[:5], action(), action("payment", 6), action("payment", 6))) == result


def test_split_can_be_followed_by_original_new_sell_at_adjusted_basis():
    sell = opening(6, Side.SELL, "90.06", ".2")
    sell = replace(
        sell,
        request=replace(
            sell.request,
            order=replace(sell.request.order, limit_price=D("49.5")),
            position=replace(sell.request.position, average_price=D("49.5")),
        ),
    )
    result = replay(
        (
            *script()[:5],
            action("split"),
            sell,
            observation(sell, control("accepted-after-split", 7, OrderEvent.BROKER_ACCEPTED)),
            observation(
                sell, execution("sold-after-split", 8, ".2", price="50", fee=".05", side=Side.SELL)
            ),
        )
    )
    assert (result.cash, result.quantity, result.unsettled_proceeds) == (
        D("100.01"),
        D("0"),
        D("9.95"),
    )
    assert result.marked_equity == D("100.01")


def test_sale_before_payment_preserves_entitlement_and_blocks_finality():
    from trading_bot.simulation.etf_capital_account import (
        CapitalEpisodeFeesFinal,
        CapitalSaleSettlement,
    )

    sell = opening(6, Side.SELL, "90.06", ".1")
    sell = replace(
        sell, request=replace(sell.request, order=replace(sell.request.order, limit_price=D("98")))
    )
    tape = (
        *script()[:5],
        action(),
        sell,
        observation(sell, control("accepted-ex", 7, OrderEvent.BROKER_ACCEPTED)),
        observation(sell, execution("sold-ex", 8, ".1", price="98", fee=".05", side=Side.SELL)),
        CapitalSaleSettlement("settled-ex", cursor(9), "sold-ex"),
    )
    result = replay(tape)
    assert result.cash == D("99.81") and result.distribution_receivable == D(".1")
    assert result.marked_equity == D("99.91") and not result.complete
    final = CapitalEpisodeFeesFinal(
        "fees-ex", cursor(11), D(".09"), opening().request.order.account_id, "order-0"
    )
    with pytest.raises(ValueError):
        replay((*tape, final))
    completed = replay((*tape, action("payment", 10), final))
    assert completed.complete and completed.cash == D("99.91")


@pytest.mark.parametrize(
    "change",
    [
        {"account_id": "wrong"},
        {"opening_order_id": "old"},
        {"symbol": "QQQ"},
        {"ratio": D("0")},
        {"ratio": D("NaN")},
        {"ratio": True},
        {"record_hash": "bad"},
        {"event_id": "x" * 257},
    ],
)
def test_invalid_split_input_denies(change):
    with pytest.raises(ValueError):
        replay((*script()[:5], action("split", **change)))


def test_unknown_wrong_amount_early_or_repeated_action_denies():
    for tape in (
        (*script()[:5], action("payment")),
        (*script()[:5], action(), action("payment", 6, amount=D(".11"))),
        (*script()[:5], action(pay_date=ORIGIN.date() + timedelta(days=1)), action("payment", 6)),
        (*script()[:5], action(), action(n=6)),
        (*script()[:3], action("split")),
    ):
        with pytest.raises(ValueError):
            replay(tape)


def test_missing_mark_remains_unknown_and_legacy_owners_deny_actions():
    from trading_bot.simulation.etf_capital_account import (
        replay_capital_account,
        replay_capital_account_v1,
    )

    assert replay(script()[:5]).marked_equity is None
    assert replay((*script()[:5], action(), action())).distribution_receivable == D(".1")
    for old in (replay_capital_account, replay_capital_account_v1):
        with pytest.raises(ValueError):
            old(initial_cash=D("100"), events=(*script()[:5], action()))


def test_atomic_mark_keeps_real_price_loss_and_ambient_precision_independent():
    tape = (*script()[:5], action(ex_mark=D("97")))
    with localcontext() as context:
        context.prec = 3
        result = replay(tape)
    assert result.marked_equity == D("99.86")


def test_repeating_split_basis_and_unsafe_quantities_are_not_rounded():
    for ratio in (D("7"), D("1e511"), D("1e-510")):
        with pytest.raises(ValueError):
            replay((*script()[:5], action("split", ratio=ratio)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("execution_enabled", True),
        ("source_qualified", True),
        ("evidence_promotable", True),
        ("ratio", D("NaN")),
        ("account_id", "x" * 257),
        ("action_id", " "),
    ],
)
def test_mutated_action_record_is_revalidated_before_hashing(field, value):
    item = action("split")
    object.__setattr__(item, field, value)
    with pytest.raises(ValueError):
        replay((*script()[:5], item))


def test_conflicting_duplicate_split_or_late_event_denies_entire_replay():
    original = action("split")
    for later in (
        replace(original, ratio=D("4")),
        replace(original, event_id="second", cursor=cursor(6)),
        action("payment", n=4),
    ):
        with pytest.raises(ValueError):
            replay((*script()[:5], original, later))


def test_action_cannot_clear_the_fee_reserve_or_claim_authentication():
    result = replay((*script()[:5], action(), action("payment", 6)))
    assert result.available_cash == D("90.10")  # cash90.16 minus remaining fee bound.06
    assert result.source_qualified is False
    assert result.evidence_promotable is False
    assert result.execution_enabled is False


def test_v3_namespace_cannot_reidentify_v2_no_action_history():
    from trading_bot.simulation.etf_capital_account import replay_capital_account

    old = replay_capital_account(initial_cash=D("100"), events=script())
    current = replay(script())
    assert current.cash == old.cash == D("100.11")
    assert current.economic_hash != old.economic_hash


@pytest.mark.parametrize("kind", ["split", "distribution"])
def test_flat_action_observation_never_invents_shares_or_income(kind):
    result = replay((*script(), action(kind, n=10)))
    assert result.cash == result.marked_equity == D("100.11")
    assert result.quantity == result.distribution_receivable == 0
    assert result.average_price is None and result.complete


@pytest.mark.parametrize("date_value", [None, ORIGIN, ORIGIN.date() - timedelta(days=1)])
def test_missing_or_invalid_payment_date_is_not_assumed(date_value):
    with pytest.raises(ValueError):
        replay((*script()[:5], action(pay_date=date_value)))


@pytest.mark.parametrize("clear_mark", [False, True])
def test_aggregate_receivable_is_bounded_even_after_mark_becomes_unknown(clear_mark):
    distributions = tuple(
        action(n=5 + index, action_id=f"dividend-{index}", amount_per_share=D("9e511"))
        for index in range(12)
    )
    sell = opening(17, Side.SELL, "90.06", ".1")
    suffix = (
        (sell, observation(sell, control("accepted-unmarked", 18, OrderEvent.BROKER_ACCEPTED)))
        if clear_mark
        else ()
    )
    with pytest.raises(ValueError):
        replay((*script()[:5], *distributions, *suffix))
