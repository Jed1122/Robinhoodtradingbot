from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from trading_bot.config.hybrid import HybridSettings
from trading_bot.hybrid.accounting import buy_lot
from trading_bot.hybrid.execution import (
    cancel_order,
    fill_order,
    mark_equity,
    reserve_order,
    settle,
)
from trading_bot.hybrid.models import Account, FillFact, PaperOrder, Quote

NOW = datetime(2026, 10, 21, 14, tzinfo=UTC)
POLICY = HybridSettings()


def quote(**changes):
    data = dict(
        symbol="XYZ",
        bid=D(10),
        ask=D("10.01"),
        as_of=NOW,
        tradable=True,
        fractional=True,
        regular_session=True,
        halted=False,
        average_dollar_volume=D(50000000),
        sector="Technology",
        earnings_clear=True,
    )
    return Quote(**(data | changes))


def order(id="o", **changes):
    return PaperOrder(
        **(
            dict(id=id, symbol="XYZ", side="buy", sleeve="tactical", quantity=D(3), risk_stop=D(9))
            | changes
        )
    )


def test_reservation_prevents_duplicates_and_capital_reuse():
    account = Account(paused=False)
    accepted = reserve_order(account, order(), quote(), NOW, POLICY)
    assert accepted.buying_power < D(970)
    with pytest.raises(ValueError, match="duplicate"):
        reserve_order(accepted, order(), quote(), NOW, POLICY)
    with pytest.raises(ValueError):
        reserve_order(accepted, order("other"), quote(), NOW, POLICY)


@pytest.mark.parametrize(
    "changes",
    [
        dict(regular_session=False),
        dict(halted=True),
        dict(as_of=NOW - timedelta(minutes=1)),
        dict(bid=D("9")),
        dict(tradable=False),
        dict(average_dollar_volume=None),
        dict(earnings_clear=False),
    ],
)
def test_unknown_or_unsafe_quote_blocks(changes):
    with pytest.raises(ValueError):
        reserve_order(Account(paused=False), order(), quote(**changes), NOW, POLICY)


def test_partial_fill_restart_duplicate_and_conflict():
    account = reserve_order(Account(paused=False), order(), quote(), NOW, POLICY)
    fill = FillFact(id="f", order_id="o", quantity=D(1), price=D("10.02"), fee=D(".01"), at=NOW)
    account = fill_order(account, fill, POLICY)
    assert account.orders[0].status == "partial"
    assert account.reserved_cash > 0
    restored = Account.model_validate_json(account.model_dump_json())
    assert fill_order(restored, fill, POLICY) == restored
    with pytest.raises(ValueError):
        fill_order(restored, fill.model_copy(update={"price": D(11)}), POLICY)
    cancelled = cancel_order(restored, "o")
    assert cancelled.reserved_cash == 0
    assert cancelled.lots[0].quantity == 1


def test_sell_proceeds_not_immediately_reinvestable():
    account = reserve_order(Account(paused=False), order(), quote(), NOW, POLICY)
    account = fill_order(
        account,
        FillFact(id="f", order_id="o", quantity=D(3), price=D("10.01"), fee=D(".01"), at=NOW),
        POLICY,
    )
    sell = order("s", side="sell", quantity=D(1), threshold="episode:first")
    account = reserve_order(account, sell, quote(), NOW, POLICY)
    due = NOW + timedelta(days=1)
    account = fill_order(
        account,
        FillFact(id="s1", order_id="s", quantity=D(1), price=D(10), fee=D(".01"), at=NOW),
        POLICY,
        settlement_at=due,
    )
    assert account.settlements[0].amount == D("9.99")
    assert "episode:first" in account.completed_thresholds
    assert settle(account, NOW) == account
    assert settle(account, due).cash == account.cash + D("9.99")


def test_kill_pause_exposure_and_missing_marks_block():
    for account in (Account(kill_switch=True), Account(), Account(cash=D(100))):
        with pytest.raises(ValueError):
            reserve_order(account, order(), quote(), NOW, POLICY)
    with pytest.raises(ValueError):
        reserve_order(Account(paused=False), order(quantity=D(5)), quote(), NOW, POLICY)
    with pytest.raises(ValueError):
        mark_equity(
            Account(
                lots=(
                    __import__("trading_bot.hybrid.accounting", fromlist=["buy_lot"]).buy_lot(
                        "l", "OTHER", "tactical", D(1), D(10), NOW
                    ),
                )
            ),
            {},
        )


def test_unknown_pending_sector_is_not_free_capacity():
    a = reserve_order(
        Account(paused=False),
        order("a", symbol="AAA", sleeve="long_term", quantity=D(9)),
        quote(symbol="AAA"),
        NOW,
        POLICY,
    )
    a = reserve_order(
        a,
        order("b", symbol="BBB", sleeve="long_term", quantity=D(9)),
        quote(symbol="BBB"),
        NOW,
        POLICY,
        exposure_quotes={"AAA": quote(symbol="AAA")},
    )
    with pytest.raises(ValueError):
        reserve_order(
            a,
            order("c", symbol="CCC", sleeve="long_term", quantity=D(9)),
            quote(symbol="CCC"),
            NOW,
            POLICY,
            exposure_quotes={
                "AAA": quote(symbol="AAA", sector=None),
                "BBB": quote(symbol="BBB", sector=None),
            },
        )


def test_cancelled_partial_exit_retains_threshold_progress():
    a = Account(paused=False, lots=(buy_lot("l", "XYZ", "tactical", D(10), D(10), NOW),))
    a = reserve_order(
        a, order("s", side="sell", quantity=D(4), threshold="e:first"), quote(), NOW, POLICY
    )
    a = fill_order(
        a,
        FillFact(id="sf", order_id="s", quantity=D(2), price=D(10), fee=D(0), at=NOW),
        POLICY,
        settlement_at=NOW + timedelta(days=1),
    )
    a = cancel_order(a, "s")
    with pytest.raises(ValueError):
        reserve_order(
            a, order("s2", side="sell", quantity=D(4), threshold="e:first"), quote(), NOW, POLICY
        )


def test_mark_tracks_actual_highwater_and_day_reference():
    from trading_bot.hybrid.execution import mark_account

    a = Account(
        paused=False, cash=D(0), lots=(buy_lot("l", "XYZ", "long_term", D(100), D(10), NOW),)
    )
    a = mark_account(a, {"XYZ": quote(bid=D(12), ask=D("12.01"))}, NOW)
    assert a.high_watermark == 1200
    later = NOW + timedelta(seconds=1)
    a = mark_account(a, {"XYZ": quote(bid=D(10), ask=D("10.01"), as_of=later)}, later)
    assert a.tactical_suspended is True
    assert a.high_watermark == 1200


def test_limit_order_reserves_its_executable_limit():
    a = reserve_order(
        Account(paused=False), order(sleeve="long_term", limit_price=D(11)), quote(), NOW, POLICY
    )
    assert a.reserved_cash >= D("33.01")
