"""Literal synthetic loss-state controls; no broker or market evidence."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from tests.unit.research.test_etf_capital_feasibility import instrument, loaded
from tests.unit.simulation._lifecycle_fixtures import ORIGIN, control, execution
from tests.unit.simulation.test_etf_capital_account import observation, opening, script
from trading_bot.domain import BrokerOrderId, FillId, OrderEvent, OrderId, OrderPurpose
from trading_bot.simulation.etf_capital_account import (
    CapitalAccountSubmission,
    CapitalEpisodeFeesFinal,
    CapitalSaleSettlement,
)
from trading_bot.simulation.events import EventCursor
from trading_bot.simulation.lifecycle_models import LifecycleFillEvent


def point(sequence, count, mark=None, *, day=0, daily=True, weekly=True):
    from trading_bot.simulation.etf_capital_risk import CapitalRiskObservation

    at = ORIGIN + timedelta(days=day, seconds=(0 if count == 0 else count - 1))
    return CapitalRiskObservation(
        EventCursor(sequence, at), count, None if mark is None else D(mark), daily, weekly
    )


def run(events=(), observations=None, purpose=OrderPurpose.ENTRY):
    from trading_bot.simulation.etf_capital_risk import replay_capital_risk

    return replay_capital_risk(
        loaded=loaded(),
        initial_cash=D("100"),
        events=events,
        observations=observations or (point(0, 0),),
        purpose=purpose,
    )


def test_genesis_cash_is_reconstructed_and_cannot_enable_execution():
    result = run()
    assert result.points[-1].equity == D("100")
    assert result.points[-1].decision.new_entries_allowed
    assert not result.execution_enabled
    assert not result.evidence_promotable


def test_current_risk_cannot_consume_unbound_historical_fee_finality():
    from tests.unit.simulation.test_etf_capital_account_finality import old_script

    with pytest.raises(ValueError):
        run(old_script(), (point(0, 0), point(1, 10)))


def test_partial_fill_mark_loss_blocks_entry_and_preserves_exit_purpose():
    events = script()[:3]
    points = (point(0, 0), point(1, 3, "89"))
    entry = run(events, points).points[-1]
    assert entry.equity == D("98.96")
    assert entry.snapshot.daily_loss_pct == D("1.04")
    assert entry.decision.reason_code == "daily_loss_limit_reached"
    assert not entry.decision.allowed
    assert run(events, points, OrderPurpose.PROTECTIVE_EXIT).points[-1].decision.allowed


def test_daily_breach_latches_until_explicit_reconciled_next_day():
    events = script()[:3]
    points = (point(0, 0), point(1, 3, "89"), point(2, 3, "109", day=1, daily=False))
    denied = run(events, points).points[-1]
    assert denied.decision.reason_code == "daily_reset_reconciliation_required"
    points = (*points[:-1], replace(points[-1], daily_reset_reconciled=True))
    reset = run(events, points).points[-1]
    assert reset.snapshot.daily_loss_pct == D("0")
    assert reset.decision.new_entries_allowed


def test_nonterminating_current_equity_loss_ratio_is_bounded_conservatively():
    points = (point(0, 0), point(1, 3, "99"), point(2, 3, "98", day=1))
    result = run(script()[:3], points).points[-1]
    assert result.equity == D("99.86")
    assert result.snapshot.daily_loss_pct == D("0.100040016006402562")
    assert result.decision.new_entries_allowed


def test_weekly_breach_survives_recovery_and_daily_reset():
    points = (point(0, 0), point(1, 3, "49"), point(2, 3, "199", day=1))
    result = run(script()[:3], points).points[-1]
    assert result.equity == D("109.96")
    assert result.snapshot.weekly_loss_pct == D("5.04")
    assert result.decision.reason_code == "weekly_loss_limit_reached"


def test_drawdown_hard_stop_survives_recovery_and_reviewed_week_reset():
    buy = opening()
    events = (
        buy,
        observation(buy, control("accepted", 1, OrderEvent.BROKER_ACCEPTED)),
        observation(buy, execution("fill", 2, ".2", price="99", fee=".04")),
    )
    points = (point(0, 0), point(1, 3, "49"), point(2, 3, "199", day=7))
    result = run(events, points, OrderPurpose.PROTECTIVE_EXIT).points[-1]
    assert result.snapshot.peak_to_trough_drawdown_pct == D("10.04")
    assert result.decision.reason_code == "drawdown_limit_reached"
    assert result.decision.kill_switch_activation_requested
    assert not result.decision.allowed


def test_sale_settlement_changes_capacity_not_equity():
    result = run(script(), (point(0, 0), point(1, 8), point(2, 9), point(3, 10)))
    assert tuple(p.equity for p in result.points[1:]) == (D("100.11"),) * 3
    assert result.points[1].account.available_cash == D("90.05")
    assert result.points[-1].account.available_cash == D("100.11")


def test_observation_jump_cannot_skip_completed_loss_or_backdate_its_clock():
    events = script()
    buy_fill = replace(events[2], fill=replace(events[2].fill, price=D("100")))
    sell = replace(
        events[5],
        request=replace(
            events[5].request,
            cash=D("89.96"),
            position=replace(events[5].request.position, average_price=D("100")),
        ),
    )
    loss_fill = replace(events[7], fill=replace(events[7].fill, price=D("100")))
    events = (*events[:2], buy_fill, *events[3:5], sell, events[6], loss_fill, *events[8:])
    result = run(events, (point(0, 0), point(1, 10, day=1))).points[-1]
    assert result.equity == D("99.91")
    assert result.snapshot.consecutive_loss_count == 1
    assert result.snapshot.last_loss_at == ORIGIN + timedelta(seconds=9)


def losing_episodes(count):
    result = []
    for episode in range(count):
        cash = D("100") - D(".09") * episode
        for index, event in enumerate(script()):
            sequence = episode * 10 + index
            cursor = EventCursor(sequence, ORIGIN + timedelta(seconds=sequence))
            prefix = f"episode-{episode}-"
            if isinstance(event, CapitalAccountSubmission):
                request = event.request
                value = replace(
                    event,
                    request=replace(
                        request,
                        cash=cash if index == 0 else cash - D("10.04"),
                        submitted=cursor,
                        position=replace(
                            request.position,
                            observed_at=cursor.occurred_at,
                            average_price=None if index == 0 else D("100"),
                        ),
                        order=replace(
                            request.order,
                            id=OrderId(prefix + request.order.id),
                            broker_order_id=BrokerOrderId(prefix + request.order.broker_order_id),
                            created_at=cursor.occurred_at,
                            updated_at=cursor.occurred_at,
                        ),
                    ),
                )
            elif isinstance(event, LifecycleFillEvent):
                value = replace(
                    event,
                    event_id=prefix + event.event_id,
                    cursor=cursor,
                    fill=replace(
                        event.fill,
                        id=FillId(prefix + event.fill.id),
                        broker_order_id=BrokerOrderId(prefix + event.fill.broker_order_id),
                        occurred_at=cursor.occurred_at,
                        price=D("100"),
                    ),
                )
            else:
                value = replace(event, event_id=prefix + event.event_id, cursor=cursor)
                if isinstance(event, CapitalSaleSettlement):
                    value = replace(value, fill_id=prefix + event.fill_id)
                elif isinstance(event, CapitalEpisodeFeesFinal):
                    value = replace(value, opening_order_id=prefix + event.opening_order_id)
                elif index in (1, 3, 4, 6):
                    value = replace(
                        value, broker_order_id=BrokerOrderId(prefix + event.broker_order_id)
                    )
            result.append(value)
    return tuple(result)


def test_three_completed_losses_across_one_observation_jump_pause_once():
    value = point(1, 30)
    result = run(losing_episodes(3), (point(0, 0), value)).points[-1]
    assert result.equity == D("99.73")
    assert result.snapshot.consecutive_loss_count == 3
    assert result.snapshot.last_loss_at == ORIGIN + timedelta(seconds=29)
    assert result.decision.reason_code == "consecutive_loss_pause_active"
    assert result.decision.entry_pause_until == ORIGIN + timedelta(seconds=29, minutes=240)


def test_repeated_observation_does_not_recount_losses_or_extend_pause():
    first = point(1, 30)
    later = replace(first, cursor=EventCursor(2, ORIGIN + timedelta(minutes=1)))
    expired = replace(first, cursor=EventCursor(3, ORIGIN + timedelta(minutes=241)))
    result = run(losing_episodes(3), (point(0, 0), first, later, expired))
    assert tuple(p.snapshot.consecutive_loss_count for p in result.points[1:]) == (3, 3, 3)
    assert (
        tuple(p.snapshot.last_loss_at for p in result.points[1:])
        == (ORIGIN + timedelta(seconds=29),) * 3
    )
    assert result.points[2].decision.entry_pause_until == first.cursor.occurred_at + timedelta(
        minutes=240
    )
    assert result.points[-1].decision.new_entries_allowed


def test_entry_reuses_current_equity_fee_aware_sizing():
    from trading_bot.simulation.etf_capital_risk import evaluate_capital_entry

    decision = evaluate_capital_entry(
        loaded=loaded(),
        initial_cash=D("100"),
        events=(),
        observations=(point(0, 0),),
        instrument=instrument(),
        entry_price=D("10"),
        stop_distance=D(".2"),
        fee_bound=D(".1"),
    )
    assert decision.allowed
    assert decision.quantity == D("2")
    assert decision.notional == D("20")
    assert decision.planned_risk_with_fees == D(".5")


@pytest.mark.parametrize("count", [1, 8])
def test_flat_but_unfinished_episode_cannot_admit_another_entry(count):
    from trading_bot.simulation.etf_capital_risk import evaluate_capital_entry

    value = point(1, count)
    if count == 1:
        value = replace(value, cursor=EventCursor(1, ORIGIN + timedelta(seconds=1)))
    decision = evaluate_capital_entry(
        loaded=loaded(),
        initial_cash=D("100"),
        events=script()[:count],
        observations=(point(0, 0), value),
        instrument=instrument(),
        entry_price=D("10"),
        stop_distance=D(".2"),
        fee_bound=D(".1"),
    )
    assert not decision.allowed
    assert decision.denial_code == "account_episode_incomplete"


@pytest.mark.parametrize(
    "change",
    [{"mark": None}, {"mark": D("0")}, {"daily_reset_reconciled": 1}, {"source_count": True}],
)
def test_invalid_original_observation_denies(change):
    value = point(1, 3, "99")
    for key, item in change.items():
        object.__setattr__(value, key, item)
    with pytest.raises(ValueError):
        run(script()[:3], (point(0, 0), value))


def test_missing_genesis_and_backward_source_deny():
    with pytest.raises(ValueError):
        run(script()[:3], (point(1, 3, "99"),))
    with pytest.raises(ValueError):
        run(script()[:3], (point(0, 0), point(1, 3, "99"), point(2, 2, "99", day=1)))
