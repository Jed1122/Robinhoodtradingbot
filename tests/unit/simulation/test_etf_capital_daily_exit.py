"""Independent synthetic SELL cash/protection controls, never broker evidence."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from decimal import localcontext

import pytest

from tests.unit.simulation.test_etf_capital_daily_entry import OPEN, request, run
from trading_bot.domain import OrderPurpose
from trading_bot.simulation.etf_capital_risk import CapitalRiskObservation
from trading_bot.simulation.events import EventCursor

AT = OPEN + timedelta(seconds=10)


def exit_request(**changes):
    from trading_bot.simulation.etf_capital_daily_exit import CapitalDailyExitRequest

    entered = run()
    value = CapitalDailyExitRequest(
        loaded=request().loaded,
        initial_cash=D("100"),
        events=entered.events,
        observations=(
            *entered.observations,
            CapitalRiskObservation(EventCursor(5, AT), len(entered.events), D("100"), False, False),
        ),
        instrument=request().instrument,
        submitted=EventCursor(6, AT),
        lifecycle_cursors=(
            EventCursor(7, AT + timedelta(seconds=1)),
            EventCursor(8, AT + timedelta(seconds=2)),
        ),
        source_hash="c" * 64,
        policy_hash="d" * 64,
        raw_base_price=D("100"),
        purpose=OrderPurpose.PROTECTIVE_EXIT,
        side_fee=D(".02"),
        roundtrip_friction_pct=D(".10"),
        outcome="filled",
        fill_fraction=D("1"),
    )
    return replace(value, **changes)


def exit_run(**changes):
    from trading_bot.simulation.etf_capital_daily_exit import simulate_capital_daily_exit

    if changes.get("outcome") in ("rejected", "unfilled"):
        changes.setdefault("lifecycle_cursors", (EventCursor(7, AT + timedelta(seconds=1)),))
    return simulate_capital_daily_exit(exit_request(**changes))


def test_full_exit_exact_cash_retains_unsettled_proceeds_and_final_fee_reserve():
    result = exit_run()
    assert result.assumed_price == D("99.95")
    assert result.account.cash == D("99.95010")
    assert result.account.quantity == 0
    assert result.account.fees == D(".03")
    assert result.account.unsettled_proceeds == D("19.87005")
    assert result.account.available_cash == D("80.01005")
    assert not result.account.complete
    assert len(result.events) == 6
    assert result.risk.points[-1].equity == D("99.95010")
    assert not result.execution_enabled and not result.economic_admitted


def test_partial_exit_keeps_remaining_shares_and_pending_order():
    result = exit_run(outcome="partial", fill_fraction=D(".5"))
    assert result.account.quantity == D(".100")
    assert result.account.cash == D("89.95510")
    assert result.account.unsettled_proceeds == D("9.87505")
    assert not result.account.complete


@pytest.mark.parametrize("outcome", ["rejected", "unfilled"])
def test_explicit_no_fill_exit_never_sells_or_charges_fee(outcome):
    result = exit_run(outcome=outcome, fill_fraction=D("0"), side_fee=D("0"))
    assert result.account.quantity == D(".199")
    assert result.account.cash == D("80.08005")
    assert result.account.fees == D(".01")
    assert result.account.unsettled_proceeds == 0


def test_settlement_and_episode_bound_final_fee_are_explicit_not_automatic():
    from trading_bot.simulation.etf_capital_account import (
        CapitalEpisodeFeesFinal,
        CapitalSaleSettlement,
        replay_capital_action_account,
    )

    result = exit_run()
    events = (
        *result.events,
        CapitalSaleSettlement(
            "settle", EventCursor(10, AT + timedelta(seconds=3)), result.events[-1].fill.id
        ),
        CapitalEpisodeFeesFinal(
            "final",
            EventCursor(11, AT + timedelta(seconds=4)),
            D(".03"),
            result.events[0].request.order.account_id,
            result.events[0].request.order.id,
        ),
    )
    state = replay_capital_action_account(initial_cash=D("100"), events=events)
    assert state.complete
    assert state.available_cash == state.cash == D("99.95010")
    assert state.unsettled_proceeds == 0


def test_daily_entry_halt_does_not_block_shared_authorized_protective_purpose():
    observation = CapitalRiskObservation(EventCursor(5, AT), 3, D("90"), False, False)
    result = exit_run(observations=(*run().observations, observation), raw_base_price=D("90"))
    assert result.account.quantity == 0
    assert result.risk.points[-2].snapshot.daily_loss_pct >= D("2")
    assert not result.risk.points[-2].decision.new_entries_allowed
    assert result.risk.points[-1].decision.allowed


def test_split_adjusted_original_quantity_and_basis_feed_exit_without_history_rewrite():
    from trading_bot.simulation.etf_capital_account import CapitalSplitApplied

    entered = run()
    opening = entered.events[0].request.order
    split = CapitalSplitApplied(
        event_id="split",
        cursor=EventCursor(5, OPEN + timedelta(seconds=3)),
        account_id=opening.account_id,
        opening_order_id=opening.id,
        symbol="SPY",
        action_id="split-action",
        record_hash="e" * 64,
        ratio=D("2"),
        post_action_mark=D("50"),
    )
    result = exit_run(
        events=(*entered.events, split),
        observations=(
            *entered.observations,
            CapitalRiskObservation(EventCursor(6, split.cursor.occurred_at), 4, None, False, False),
            CapitalRiskObservation(EventCursor(7, AT), 4, D("50"), False, False),
        ),
        submitted=EventCursor(8, AT),
        lifecycle_cursors=(
            EventCursor(9, AT + timedelta(seconds=1)),
            EventCursor(10, AT + timedelta(seconds=2)),
        ),
        raw_base_price=D("50"),
    )
    assert result.events[:3] == entered.events
    assert result.events[4].request.position.quantity == D(".398")
    assert result.events[4].request.position.average_price == D("50.025")
    assert result.account.quantity == 0
    assert result.account.cash == D("99.95010")


@pytest.mark.parametrize(
    "changes",
    [
        {"side_fee": D(".10")},
        {"fill_fraction": D(".5")},
        {"outcome": "partial", "fill_fraction": D("0")},
        {"purpose": OrderPurpose.ENTRY},
        {"roundtrip_friction_pct": D(".3")},
        {"source_hash": "bad"},
        {"raw_base_price": D("0")},
        {"submitted": EventCursor(4, AT)},
        {"lifecycle_cursors": (EventCursor(7, AT), EventCursor(8, AT))},
    ],
)
def test_invalid_exit_assumptions_fail_closed(changes):
    with pytest.raises(ValueError):
        exit_run(**changes)


def test_exit_cannot_ignore_original_fill_frontier():
    with pytest.raises(ValueError):
        exit_run(observations=(request().observations[0],))


def test_no_exit_over_pending_entry_and_no_duplicate_sell_over_pending_exit():
    from trading_bot.simulation.etf_capital_daily_exit import simulate_capital_daily_exit

    entered = run(outcome="partial", fill_fraction=D(".5"))
    value = exit_request(
        events=entered.events,
        observations=(
            *entered.observations,
            CapitalRiskObservation(EventCursor(5, AT), 3, D("100"), False, False),
        ),
    )
    with pytest.raises(ValueError):
        simulate_capital_daily_exit(value)
    partial = exit_run(outcome="partial", fill_fraction=D(".5"))
    later = AT + timedelta(seconds=10)
    value = exit_request(
        events=partial.events,
        observations=(
            *partial.observations,
            CapitalRiskObservation(EventCursor(10, later), 6, D("100"), False, False),
        ),
        submitted=EventCursor(11, later),
        lifecycle_cursors=(
            EventCursor(12, later + timedelta(seconds=1)),
            EventCursor(13, later + timedelta(seconds=2)),
        ),
    )
    with pytest.raises(ValueError):
        simulate_capital_daily_exit(value)


def test_precision_and_false_qualification_are_owned():
    from trading_bot.simulation.etf_capital_daily_exit import simulate_capital_daily_exit

    expected = exit_run()
    with localcontext() as ctx:
        ctx.prec = 3
        assert exit_run() == expected
    value = exit_request()
    object.__setattr__(value, "execution_enabled", True)
    with pytest.raises(ValueError):
        simulate_capital_daily_exit(value)


def test_drawdown_kill_and_unknown_ownership_are_not_bypassed_for_exit():
    value = exit_request()
    with pytest.raises(ValueError):
        exit_run(
            observations=(
                *run().observations,
                CapitalRiskObservation(EventCursor(5, AT), 3, D("1"), False, False),
            ),
            raw_base_price=D("1"),
        )
    with pytest.raises(ValueError):
        exit_run(instrument=replace(value.instrument, symbol="QQQ"))
    with pytest.raises(ValueError):
        exit_run(instrument=replace(value.instrument, price_increment=D("1000")))


@pytest.mark.parametrize(
    "changes",
    [
        {"low": D("90")},
        {"high": D("110")},
        {"high": D("99"), "low": D("90")},
        {"stop": D("105")},
        {"raw_open": D("0")},
        {"target": D("NaN")},
    ],
)
def test_invalid_protection_inputs_are_unknown_not_execution(changes):
    from trading_bot.simulation.etf_capital_daily_exit import select_capital_protection

    kwargs = dict(raw_open=D("100"), stop=D("95"), target=D("105"))
    with pytest.raises(ValueError):
        select_capital_protection(**(kwargs | changes))


@pytest.mark.parametrize(
    "opening,high,low,price,reason",
    [
        ("90", None, None, "90", "stop_gap"),
        ("110", None, None, "105", "target_gap_conservative"),
        ("100", "110", "90", "95", "stop_first_ambiguous"),
        ("100", "110", "99", "105", "target"),
        ("100", "101", "94", "95", "stop"),
        ("100", "101", "99", None, None),
        ("100", None, None, None, None),
    ],
)
def test_protection_gap_and_adverse_range_precedence(opening, high, low, price, reason):
    from trading_bot.simulation.etf_capital_daily_exit import select_capital_protection

    result = select_capital_protection(
        raw_open=D(opening),
        stop=D("95"),
        target=D("105"),
        high=None if high is None else D(high),
        low=None if low is None else D(low),
    )
    if price is None:
        assert result is None
    else:
        assert result.base_price == D(price) and result.reason == reason


@pytest.mark.parametrize(
    "price,expected", [("90", "89.955"), ("95", "94.9525"), ("105", "104.9475")]
)
def test_protective_exit_prices_apply_friction_once(price, expected):
    assert exit_run(raw_base_price=D(price)).assumed_price == D(expected)
