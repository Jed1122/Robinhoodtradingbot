"""Original-bound assumed T+2/actions; no broker/customer observations."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from decimal import localcontext

import pytest

from tests.unit.research.test_etf_capital_prepared import long_source
from trading_bot.domain import BarInterval
from trading_bot.market_data.etf_capital_actions import CapitalDistribution, CapitalSplit
from trading_bot.market_data.etf_capital_dataset import capital_dataset_features
from trading_bot.simulation.etf_capital_account import (
    CapitalAccountSubmission,
    CapitalEpisodeFeesFinal,
    CapitalSaleSettlement,
    replay_capital_action_account,
)
from trading_bot.simulation.etf_capital_action_events import (
    CapitalDistributionEntitled,
    CapitalDistributionPaid,
    CapitalSplitApplied,
)
from trading_bot.simulation.events import EventCursor
from trading_bot.simulation.lifecycle_models import LifecycleFillEvent

from .test_etf_capital_account import script


@pytest.fixture(scope="module")
def source():
    return long_source(8)


def retime(event, at, sequence=None):
    old = event.request.submitted if type(event) is CapitalAccountSubmission else event.cursor
    cursor = EventCursor(old.sequence if sequence is None else sequence, at)
    if type(event) is CapitalAccountSubmission:
        request = event.request
        return replace(
            event,
            request=replace(
                request,
                submitted=cursor,
                order=replace(request.order, created_at=at, updated_at=at),
                position=replace(request.position, observed_at=at),
            ),
        )
    if type(event) is LifecycleFillEvent:
        return replace(event, cursor=cursor, fill=replace(event.fill, occurred_at=at))
    return replace(event, cursor=cursor)


def tape(source, count=8):
    # Friday sale, Monday is T+1 and Tuesday T+2 in the original calendar.
    opened = source.calendar.sessions[1].opens_at
    return tuple(retime(e, opened + timedelta(seconds=i)) for i, e in enumerate(script()[:count]))


def due(source, events, index, *, observations=(), actions=None, bars=None):
    from trading_bot.simulation.etf_capital_due_facts import _capital_due_facts

    day = source.calendar.sessions[index].session_date
    raw = tuple(p.raw_bars[-1] for p in capital_dataset_features(source, as_of_session=day))
    return _capital_due_facts(
        initial_cash=D(100),
        events=events,
        observations=observations,
        calendar=source.calendar,
        actions=source.actions if actions is None else actions,
        session=day,
        raw_bars=raw if bars is None else bars,
    )


def applied(events, facts):
    return (*events, *(fact.event for fact in facts))


def replay(events):
    return replay_capital_action_account(initial_cash=D(100), events=events)


def test_t_plus_two_uses_original_sessions_not_weekdays_or_evaluation_frames(source):
    events = tape(source)
    assert source.calendar.sessions[1].session_date.weekday() == 4
    assert due(source, events, 2) == ()
    facts = due(source, events, 3)
    assert tuple(type(f.event) for f in facts) == (CapitalSaleSettlement, CapitalEpisodeFeesFinal)
    settlement, final = (f.event for f in facts)
    assert settlement.fill_id == "sell-fill"
    assert (
        settlement.cursor.occurred_at
        == final.cursor.occurred_at
        == source.calendar.sessions[3].opens_at
    )
    assert settlement.cursor.sequence < final.cursor.sequence
    assert (final.total_fees, final.account_id, final.opening_order_id) == (
        D(".09"),
        events[0].request.order.account_id,
        events[0].request.order.id,
    )
    result = replay(applied(events, facts))
    assert (result.cash, result.available_cash, result.quantity, result.complete) == (
        D("100.11"),
        D("100.11"),
        D(0),
        True,
    )
    assert not result.execution_enabled and not result.evidence_promotable


def test_genesis_and_terminal_unsettled_tail_are_not_completed_by_input_end(source):
    assert due(source, (), 0) == ()
    assert due(source, tape(source), 2) == ()
    assert not replay(tape(source)).complete


def test_duplicate_original_delivery_and_exact_retry_do_not_repeat_cash_flows(source):
    events = tape(source)
    duplicate = (*events[:3], events[2], *events[3:])
    facts = due(source, events, 3)
    assert due(source, duplicate, 3) == facts
    assert due(source, applied(events, facts), 3) == ()
    assert due(source, applied(events, facts), 4) == ()


def test_active_partial_buy_preserves_reservations_without_invented_cancel_or_finality(source):
    events = tape(source, 3)
    assert due(source, events, 3) == ()
    assert replay(events).available_cash == D("80.00")


def test_terminal_flat_unfilled_buy_can_finalize_exact_original_zero_fees(source):
    from trading_bot.domain import OrderEvent

    events = tape(source, 2)
    events = (events[0], replace(events[1], event=OrderEvent.BROKER_REJECTED))
    facts = due(source, events, 2)
    assert len(facts) == 1 and type(facts[0].event) is CapitalEpisodeFeesFinal
    assert facts[0].event.total_fees == 0
    assert replay(applied(events, facts)).complete


def distribution_actions(source, *, pay_index=4):
    ex = source.calendar.sessions[2].session_date
    pay = source.calendar.sessions[pay_index].session_date
    row = CapitalDistribution(ex, ex, pay, D(1), "d" * 64)
    return (replace(source.actions[0], distributions=(row,)), *source.actions[1:])


def test_original_distribution_entitles_held_quantity_but_is_not_spendable(source):
    events = tape(source, 5)
    facts = due(source, events, 2, actions=distribution_actions(source))
    assert len(facts) == 1 and type(facts[0].event) is CapitalDistributionEntitled
    assert facts[0].event.amount_per_share == 1 and facts[0].mark == D(102)
    result = replay(applied(events, facts))
    assert (
        result.cash,
        result.available_cash,
        result.quantity,
        result.distribution_receivable,
    ) == (
        D("90.06"),
        D("90.00"),
        D(".1"),
        D(".1"),
    )
    assert result.marked_equity == D("100.36")


def test_payment_survives_sale_and_binds_original_entitlement_before_finality(source):
    actions = distribution_actions(source)
    events = tape(source, 5)
    events = applied(events, due(source, events, 2, actions=actions))
    sold_at = source.calendar.sessions[2].opens_at + timedelta(minutes=1)
    sell = tuple(
        retime(e, sold_at + timedelta(seconds=i), 20 + i) for i, e in enumerate(script()[5:8])
    )
    events = (*events, *sell)
    assert due(source, events, 3, actions=actions) == ()
    facts = due(source, events, 4, actions=actions)
    assert tuple(type(f.event) for f in facts) == (
        CapitalSaleSettlement,
        CapitalDistributionPaid,
        CapitalEpisodeFeesFinal,
    )
    payment = facts[1].event
    assert payment.entitlement_id == events[5].action_id and payment.amount == D(".1")
    result = replay(applied(events, facts))
    assert (
        result.cash,
        result.available_cash,
        result.distribution_receivable,
        result.complete,
    ) == (
        D("100.21"),
        D("100.21"),
        D(0),
        True,
    )
    assert due(source, applied(events, facts), 5, actions=actions) == ()


def test_split_uses_original_held_episode_and_reciprocal_basis(source):
    day = source.calendar.sessions[2].session_date
    actions = (
        replace(source.actions[0], splits=(CapitalSplit(day, D(2), "a" * 64),)),
        *source.actions[1:],
    )
    events = tape(source, 5)
    facts = due(source, events, 2, actions=actions)
    assert len(facts) == 1 and type(facts[0].event) is CapitalSplitApplied
    result = replay(applied(events, facts))
    assert (result.quantity, result.average_price, result.cash) == (D(".2"), D("49.5"), D("90.06"))
    assert facts[0].event.opening_order_id == events[0].request.order.id


def test_flat_accounts_do_not_generate_fake_position_actions(source):
    assert due(source, (), 2, actions=distribution_actions(source)) == ()


def test_coincident_held_split_distribution_is_denied_not_ordered_by_guess(source):
    actions = distribution_actions(source)
    day = source.calendar.sessions[2].session_date
    actions = (replace(actions[0], splits=(CapitalSplit(day, D(2), "a" * 64),)), *actions[1:])
    with pytest.raises(ValueError):
        due(source, tape(source, 5), 2, actions=actions)


def test_active_order_action_remains_unsupported(source):
    with pytest.raises(ValueError):
        due(source, tape(source, 3), 2, actions=distribution_actions(source))


def test_unknown_action_coverage_is_not_empty_even_when_flat(source):
    actions = (replace(source.actions[0], distributions=None), *source.actions[1:])
    with pytest.raises(ValueError):
        due(source, (), 2, actions=actions)


@pytest.mark.parametrize("change", ("clock", "symbol", "duplicate"))
def test_misaligned_or_duplicate_current_bars_deny_before_any_facts(source, change):
    day = source.calendar.sessions[3].session_date
    bars = tuple(p.raw_bars[-1] for p in capital_dataset_features(source, as_of_session=day))
    if change == "clock":
        bars = (replace(bars[0], starts_at=bars[0].starts_at + timedelta(seconds=1)), *bars[1:])
    elif change == "symbol":
        bars = (replace(bars[0], instrument_id="OTHER"), *bars[1:])
    else:
        bars = (bars[0], bars[0], *bars[2:])
    with pytest.raises(ValueError):
        due(source, tape(source), 3, bars=bars)


def test_low_ambient_precision_does_not_change_exact_events_or_money(source):
    events = tape(source)
    expected = due(source, events, 3)
    with localcontext() as ctx:
        ctx.prec = 3
        assert due(source, events, 3) == expected
        assert replay(applied(events, expected)).cash == D("100.11")


@pytest.mark.parametrize("change", ("minute", "interpolated"))
def test_daily_original_semantics_cannot_be_replaced_with_another_bar_kind(source, change):
    day = source.calendar.sessions[3].session_date
    bars = tuple(p.raw_bars[-1] for p in capital_dataset_features(source, as_of_session=day))
    altered = (
        replace(bars[0], interval=BarInterval.ONE_MINUTE)
        if change == "minute"
        else replace(bars[0], interpolated=True)
    )
    with pytest.raises(ValueError):
        due(source, tape(source), 3, bars=(altered, *bars[1:]))


def test_reused_source_record_identity_cannot_manufacture_another_entitlement(source):
    actions = distribution_actions(source)
    first = actions[0].distributions[0]
    later = source.calendar.sessions[3].session_date
    duplicate_record = replace(first, ex_date=later, record_date=later)
    actions = (replace(actions[0], distributions=(first, duplicate_record)), *actions[1:])
    with pytest.raises(ValueError):
        due(source, tape(source, 5), 2, actions=actions)


def test_observation_frontier_advances_sequences_but_cannot_point_to_future(source):
    from trading_bot.simulation.etf_capital_risk import CapitalRiskObservation

    events = tape(source)
    opened = source.calendar.sessions[3].opens_at
    observation = CapitalRiskObservation(
        EventCursor(100, opened - timedelta(seconds=1)), len(events), None, False, False
    )
    facts = due(source, events, 3, observations=(observation,))
    assert facts[0].event.cursor.sequence == 101 and facts[1].event.cursor.sequence == 102
    with pytest.raises(ValueError):
        due(
            source,
            events,
            3,
            observations=(
                replace(observation, cursor=EventCursor(100, opened + timedelta(seconds=1))),
            ),
        )


def test_same_session_declared_payment_does_not_wait_for_another_frame(source):
    actions = distribution_actions(source, pay_index=2)
    events = tape(source, 5)
    facts = due(source, events, 2, actions=actions)
    assert tuple(type(f.event) for f in facts) == (
        CapitalDistributionEntitled,
        CapitalDistributionPaid,
    )
    result = replay(applied(events, facts))
    assert result.cash == D("90.16") and result.distribution_receivable == 0
    assert result.marked_equity == D("100.36")


def test_missed_settlement_session_denies_instead_of_silently_retiming_it(source):
    with pytest.raises(ValueError):
        due(source, tape(source), 4)
