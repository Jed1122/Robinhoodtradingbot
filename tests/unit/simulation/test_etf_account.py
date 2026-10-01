"""Independent cash conservation and restart contracts; every input is synthetic."""

import importlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

import pytest

from tests.unit.simulation.test_etf_history import study
from trading_bot.domain import (
    AssetClass,
    Fill,
    Instrument,
    OrderEvent,
    OrderIntent,
    OrderPurpose,
    OrderState,
    OrderType,
    Side,
    TimeInForce,
)
from trading_bot.market_data.etf_source import _ns
from trading_bot.market_data.recording import content_hash

D = Decimal
NOW = datetime(2019, 1, 2, 15, tzinfo=UTC)


def api():
    try:
        return importlib.import_module("trading_bot.simulation.etf_account")
    except ModuleNotFoundError:
        pytest.fail("ETF account cash/order/settlement replay is missing")


def instrument():
    return Instrument(
        "SPY",
        "SPY",
        AssetClass.EQUITY,
        "synthetic",
        True,
        True,
        D(".01"),
        D(".001"),
        D(".001"),
        D("1"),
        None,
        "US-equity",
        NOW,
        content_hash("synthetic-instrument"),
    )


def intent(name="entry", side=Side.BUY, quantity=Decimal(".1"), price=Decimal("100"), at=NOW):
    frozen = study()
    return OrderIntent(
        name,
        "etf-offline",
        "SPY",
        AssetClass.EQUITY,
        side,
        OrderPurpose.ENTRY if side is Side.BUY else OrderPurpose.PROTECTIVE_EXIT,
        OrderType.LIMIT,
        TimeInForce.GOOD_FOR_DAY,
        quantity,
        price,
        None,
        at,
        at + timedelta(hours=1),
        "spy-cash-momentum-20-100-v1",
        frozen.config_hash,
        content_hash(("intent", name)),
        "synthetic-exit-v1",
    )


def submit(order, ordinal=0, stop=Decimal("1"), reserve_fee=Decimal(".02")):
    return api().EtfAccountEvent(
        content_hash(("submit", order.id)),
        ordinal,
        _ns(order.created_at),
        "intent",
        intent=order,
        instrument=instrument(),
        stop_distance=stop,
        fee_bound=reserve_fee,
    )


def fill(
    order, name, ordinal, seconds, quantity=Decimal(".1"), price=Decimal("100"), fee=Decimal(".01")
):
    at = NOW + timedelta(seconds=seconds)
    execution = Fill(
        name,
        order.id,
        "etf-offline",
        "SPY",
        order.side,
        quantity,
        price,
        fee,
        at,
        content_hash(("execution", name)),
    )
    return api().EtfAccountEvent(
        content_hash(("fill", name)), ordinal, _ns(at), "fill", fill=execution
    )


def settled(fill_ids, ordinal, seconds):
    return api().EtfAccountEvent(
        content_hash(("settle", fill_ids)),
        ordinal,
        _ns(NOW + timedelta(seconds=seconds)),
        "settlement",
        fill_ids=fill_ids,
    )


def request(events, cash=Decimal("500")):
    return api().EtfAccountRequest(study(), cash, tuple(events))


def episode_events(sell_price=Decimal("101")):
    buy = intent()
    sell = intent("exit", Side.SELL, price=sell_price, at=NOW + timedelta(seconds=5))
    return (
        submit(buy),
        fill(buy, "buy-1", 1, 1),
        settled(("buy-1",), 2, 2),
        api().EtfAccountEvent(
            content_hash("ex"),
            3,
            _ns(NOW + timedelta(seconds=3)),
            "dividend_ex",
            action_id=content_hash("distribution"),
            cash_per_share=D(".2"),
        ),
        api().EtfAccountEvent(
            content_hash("pay"),
            4,
            _ns(NOW + timedelta(seconds=4)),
            "dividend_pay",
            action_id=content_hash("distribution"),
        ),
        submit(sell, 5),
        fill(sell, "sell-1", 6, 6, price=sell_price),
        settled(("sell-1",), 7, 7),
    )


def test_observed_research_mark_updates_equity_losses_without_fabricating_cash_or_fill():
    events = episode_events()[:3]
    mark = api().EtfAccountEvent(
        content_hash("adverse-mark"),
        3,
        _ns(NOW + timedelta(seconds=3)),
        "mark",
        mark_price=D("1"),
    )
    state = api().replay_etf_account(request((*events, mark)))
    assert state.cash == D("489.99") and state.shares == D(".1")
    assert state.position.market_value == D(".1") and state.entry_halted
    assert state.trial.reserved_risk == D("10.02") and not state.complete
    assert api().resume_etf_account(request((*events, mark)), state) == state


def test_flat_mark_is_not_income_and_invalid_mark_fields_deny():
    mark = api().EtfAccountEvent(content_hash("flat-mark"), 0, _ns(NOW), "mark", mark_price=D("2"))
    state = api().replay_etf_account(request((mark,)))
    assert state.cash == D("500") and state.position.market_value == 0 and state.complete
    with pytest.raises(ValueError):
        replace(mark, mark_price=D("NaN"))
    with pytest.raises(ValueError):
        replace(mark, cash_per_share=D("1"))


def test_partial_reservation_properties_do_not_use_ambient_decimal_precision():
    buy = intent()
    partial = fill(buy, "partial", 1, 1, quantity=D(".04"))
    state = api().replay_etf_account(request((submit(buy), partial)))
    expected = state.reserved_cash
    assert expected == D("6.01")
    with localcontext() as context:
        context.prec = 2
        assert state.reserved_cash == expected
        assert state.orders[0].remaining == D(".06")


def test_gains_above_canonical_account_ceiling_block_another_entry():
    state = api().replay_etf_account(request(episode_events(), cash=D("1000")))
    assert state.cash == D("1000.10") and state.entry_halted
    next_buy = intent("next-day", at=NOW + timedelta(days=1))
    with pytest.raises(ValueError, match="etf_account_invalid"):
        api().replay_etf_account(request((*episode_events(), submit(next_buy, 8)), cash=D("1000")))


def test_exact_cash_flows_and_dividend_payability_are_reconciled():
    result = api().replay_etf_account(request(episode_events()))
    assert result.cash == D("500.10")
    assert result.settled_cash == D("500.10")
    assert result.shares == 0 and result.reserved_cash == 0
    assert result.trial.consumed_loss == 0 and result.trial.reserved_risk == 0
    assert result.complete and result.fees == D(".02")
    assert not result.evidence_promotable and not result.execution_enabled


def test_cash_is_not_credited_on_ex_date_and_sale_is_not_spendable_until_settlement():
    events = episode_events()
    ex_only = api().replay_etf_account(request(events[:4]))
    assert ex_only.cash == D("489.99") and ex_only.dividend_receivable == D(".02")
    sold = api().replay_etf_account(request(events[:-1]))
    assert sold.cash == D("500.10") and sold.settled_cash == D("490.01")
    assert not sold.complete and sold.trial.reserved_risk == D("10.02")
    assert sold.reserved_cash == 0


def test_completed_losses_never_get_offset_by_a_previous_profitable_episode():
    first = episode_events()
    buy = intent("entry-2", at=NOW + timedelta(days=1))
    sell = intent("exit-2", Side.SELL, price=D("99"), at=NOW + timedelta(days=1, seconds=3))
    second = (
        submit(buy, 8),
        replace(
            fill(buy, "buy-2", 9, 1),
            at_ns=_ns(NOW + timedelta(days=1, seconds=1)),
            fill=replace(
                fill(buy, "buy-2", 9, 1).fill, occurred_at=NOW + timedelta(days=1, seconds=1)
            ),
        ),
        replace(settled(("buy-2",), 10, 2), at_ns=_ns(NOW + timedelta(days=1, seconds=2))),
        submit(sell, 11),
        replace(
            fill(sell, "sell-2", 12, 4, price=D("99")),
            at_ns=_ns(NOW + timedelta(days=1, seconds=4)),
            fill=replace(
                fill(sell, "sell-2", 12, 4, price=D("99")).fill,
                occurred_at=NOW + timedelta(days=1, seconds=4),
            ),
        ),
        replace(settled(("sell-2",), 13, 5), at_ns=_ns(NOW + timedelta(days=1, seconds=5))),
    )
    result = api().replay_etf_account(request((*first, *second)))
    assert result.cash == D("499.98")
    assert result.trial.consumed_loss == D(".12")
    assert result.trial.remaining(D("50")) == D("49.88")


def test_partial_fill_and_cancel_race_retain_full_trial_reservation():
    buy = intent(quantity=D(".1"))
    cancel = api().EtfAccountEvent(
        content_hash("request-cancel"),
        2,
        _ns(NOW + timedelta(seconds=2)),
        "order_status",
        order_id=buy.id,
        order_event=OrderEvent.REQUEST_CANCEL,
    )
    race = fill(buy, "race", 3, 3, quantity=D(".02"))
    result = api().replay_etf_account(
        request((submit(buy), fill(buy, "partial", 1, 1, quantity=D(".04")), cancel, race))
    )
    assert result.shares == D(".06")
    assert result.orders[0].order.state is OrderState.CANCEL_PENDING
    assert result.reserved_cash == D("4")
    assert result.trial.reserved_risk == D("10.02") and not result.complete


def test_duplicate_fill_is_idempotent_but_conflicting_execution_denies():
    buy = intent()
    execution = fill(buy, "fill", 1, 1)
    result = api().replay_etf_account(request((submit(buy), execution, execution)))
    assert result.cash == D("489.99") and result.shares == D(".1")
    with pytest.raises(ValueError, match="etf_account_invalid"):
        api().replay_etf_account(
            request(
                (
                    submit(buy),
                    execution,
                    replace(execution, fill=replace(execution.fill, fee=D(".02"))),
                )
            )
        )


def test_earlier_or_same_nanosecond_fill_cannot_execute_new_intent():
    buy = intent()
    execution = fill(buy, "too-early", 1, 0)
    with pytest.raises(ValueError, match="etf_account_invalid"):
        api().replay_etf_account(request((submit(buy), execution)))


@pytest.mark.parametrize("cash", [D("500"), D("1000")])
def test_hypothetical_capital_does_not_raise_risk_or_order_limits(cash):
    too_large = intent(quantity=D(".2"))
    with pytest.raises(ValueError, match="etf_account_invalid"):
        api().replay_etf_account(request((submit(too_large),), cash))


def test_open_position_is_incomplete_without_forced_final_sale():
    buy = intent()
    result = api().replay_etf_account(request((submit(buy), fill(buy, "fill", 1, 1))))
    assert result.shares == D(".1") and result.cash == D("489.99")
    assert not result.complete and result.trial.reserved_risk == D("10.02")


def test_prefix_restart_matches_uninterrupted_and_rejects_changed_prefix():
    original = request(episode_events())
    prefix = api().replay_etf_account(original, through_ordinal=1)
    resumed = api().resume_etf_account(original, prefix)
    assert resumed == api().replay_etf_account(original)
    wrong = replace(prefix, cash=D("500"))
    with pytest.raises(ValueError, match="etf_account_invalid"):
        api().resume_etf_account(original, wrong)


def test_fee_reserve_is_part_of_per_trade_risk():
    buy = intent()
    with pytest.raises(ValueError, match="etf_account_invalid"):
        api().replay_etf_account(request((submit(buy, stop=D("5")),)))


def test_episode_fee_limit_cannot_be_spent_again_on_exit():
    events = episode_events()
    excessive_exit_fee = replace(events[6], fill=replace(events[6].fill, fee=D(".02")))
    with pytest.raises(ValueError, match="etf_account_invalid"):
        api().replay_etf_account(request((*events[:6], excessive_exit_fee)))


def test_cancel_confirmation_releases_only_unfilled_cash_not_open_episode_risk():
    buy = intent()
    cancel = api().EtfAccountEvent(
        content_hash("cancel-ask"),
        2,
        _ns(NOW + timedelta(seconds=2)),
        "order_status",
        order_id=buy.id,
        order_event=OrderEvent.REQUEST_CANCEL,
    )
    confirmed = replace(
        cancel,
        event_id=content_hash("cancel-confirmed"),
        ordinal=3,
        at_ns=_ns(NOW + timedelta(seconds=3)),
        order_event=OrderEvent.CANCEL_CONFIRMED,
    )
    result = api().replay_etf_account(
        request((submit(buy), fill(buy, "partial", 1, 1, quantity=D(".04")), cancel, confirmed))
    )
    assert result.reserved_cash == 0 and result.shares == D(".04")
    assert result.trial.reserved_risk == D("10.02") and not result.complete


def test_unfilled_canceled_episode_does_not_consume_trial_loss():
    buy = intent()
    cancel = api().EtfAccountEvent(
        content_hash("cancel-unfilled"),
        1,
        _ns(NOW + timedelta(seconds=1)),
        "order_status",
        order_id=buy.id,
        order_event=OrderEvent.REQUEST_CANCEL,
    )
    canceled = replace(
        cancel,
        event_id=content_hash("canceled"),
        ordinal=2,
        at_ns=_ns(NOW + timedelta(seconds=2)),
        order_event=OrderEvent.CANCEL_CONFIRMED,
    )
    result = api().replay_etf_account(request((submit(buy), cancel, canceled)))
    assert result.complete and result.cash == D("500")
    assert result.trial.remaining(D("50")) == D("50")


def test_weekly_loss_breach_remains_latched_after_daily_restart():
    events = episode_events(sell_price=D("1"))
    prefix = api().replay_etf_account(request(events))
    assert prefix.entry_halted
    next_buy = intent("after-loss", at=NOW + timedelta(days=1))
    with pytest.raises(ValueError, match="etf_account_invalid"):
        api().replay_etf_account(request((*events, submit(next_buy, 8))))


def test_loss_mark_and_fee_accounting_do_not_activate_live_or_replenish_trial():
    events = episode_events(sell_price=D("1"))
    result = api().replay_etf_account(request(events))
    assert result.trial.consumed_loss == D("9.90")
    assert result.trial.remaining(D("50")) == D("40.10")
    assert result.paused and not result.execution_enabled
