"""Literal synthetic next-open economics; no market or execution evidence."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from decimal import localcontext

import pytest

from tests.unit.research.test_etf_capital_feasibility import instrument, loaded
from trading_bot.simulation.etf_capital_risk import CapitalRiskObservation
from trading_bot.simulation.events import EventCursor

OPEN = datetime(2026, 10, 9, 13, 30, tzinfo=UTC)


def request(**changes):
    from trading_bot.simulation.etf_capital_daily_entry import CapitalDailyEntryRequest

    value = CapitalDailyEntryRequest(
        loaded=loaded(),
        initial_cash=D("100"),
        events=(),
        observations=(CapitalRiskObservation(EventCursor(0, OPEN), 0, None, True, True),),
        instrument=instrument(observed_at=OPEN, price_increment=D(".000001")),
        decision_at=OPEN - timedelta(days=1),
        opened=EventCursor(1, OPEN),
        lifecycle_cursors=(
            EventCursor(2, OPEN + timedelta(seconds=1)),
            EventCursor(3, OPEN + timedelta(seconds=2)),
        ),
        decision_hash="a" * 64,
        source_hash="b" * 64,
        raw_open=D("100"),
        stop_distance=D("2"),
        episode_fee_bound=D(".10"),
        side_fee=D(".01"),
        roundtrip_friction_pct=D(".10"),
        outcome="filled",
        fill_fraction=D("1"),
    )
    return replace(value, **changes)


def run(**changes):
    from trading_bot.simulation.etf_capital_daily_entry import simulate_capital_daily_entry

    if changes.get("outcome") in ("rejected", "unfilled"):
        changes.setdefault("lifecycle_cursors", (EventCursor(2, OPEN + timedelta(seconds=1)),))
    return simulate_capital_daily_entry(request(**changes))


@pytest.mark.parametrize("seconds_before_open", [1, 3600])
def test_same_utc_date_decision_cannot_create_daily_entry(seconds_before_open):
    with pytest.raises(ValueError):
        run(decision_at=OPEN - timedelta(seconds=seconds_before_open))


def test_literal_full_fill_uses_adverse_price_shared_sizing_and_cash():
    result = run()
    assert result.assumed_price == D("100.05")
    assert result.admission.quantity == D(".199")
    assert result.account.quantity == D(".199")
    assert result.account.cash == D("80.08005")
    assert result.account.available_cash == D("79.99005")
    assert result.account.fees == D(".01")
    assert not result.account.complete
    assert len(result.events) == 3
    assert result.risk.points[-1].equity == D("99.98005")
    assert not result.source_qualified
    assert not result.cost_qualified
    assert not result.execution_enabled
    assert not result.economic_admitted
    assert not result.evidence_promotable


def test_literal_partial_fill_retains_whole_pending_reservation():
    result = run(outcome="partial", fill_fraction=D(".5"))
    assert result.account.quantity == D(".099")
    assert result.account.cash == D("90.08505")
    assert result.account.available_cash == D("79.99005")
    assert not result.account.complete


def test_partial_cancel_race_keeps_late_fill_and_unfinal_fee_reserve():
    from trading_bot.domain import Fill, FillId, OrderEvent, Side
    from trading_bot.simulation.etf_capital_account import replay_capital_action_account
    from trading_bot.simulation.lifecycle_models import LifecycleControlEvent, LifecycleFillEvent

    partial = run(outcome="partial", fill_fraction=D(".5"))
    order = partial.events[0].request.order
    pending = LifecycleControlEvent(
        "synthetic-cancel",
        EventCursor(5, OPEN + timedelta(seconds=3)),
        order.account_id,
        order.instrument_id,
        order.broker_order_id,
        OrderEvent.REQUEST_CANCEL,
    )
    late = LifecycleFillEvent(
        "synthetic-late-fill",
        EventCursor(6, OPEN + timedelta(seconds=4)),
        Fill(
            FillId("synthetic-late-fill"),
            order.broker_order_id,
            order.account_id,
            order.instrument_id,
            Side.BUY,
            D(".05"),
            D("100.05"),
            D(".02"),
            OPEN + timedelta(seconds=4),
            order.data_hash,
        ),
    )
    cancelled = replace(
        pending,
        event_id="synthetic-cancelled",
        event=OrderEvent.CANCEL_CONFIRMED,
        cursor=EventCursor(7, OPEN + timedelta(seconds=5)),
    )
    state = replay_capital_action_account(
        initial_cash=D("100"),
        events=(*partial.events, pending, late, cancelled),
    )
    assert state.quantity == D(".149")
    assert state.cash == D("85.06255")
    assert state.available_cash == D("84.99255")
    assert state.fees == D(".03")
    assert not state.complete
    assert state.mark is None


def test_unfilled_order_is_not_implicitly_cancelled_or_released():
    result = run(outcome="unfilled", fill_fraction=D("0"), side_fee=D("0"))
    assert result.account.cash == D("100")
    assert result.account.quantity == 0
    assert result.account.available_cash == D("79.99005")
    assert len(result.events) == 2
    assert not result.account.complete


def test_rejection_is_recorded_without_a_fill_or_forced_fee_finality():
    result = run(outcome="rejected", fill_fraction=D("0"), side_fee=D("0"))
    assert len(result.events) == 2
    assert result.account.cash == D("100")
    assert result.account.quantity == 0
    assert result.account.fees == 0


def test_fee_budget_denial_emits_no_order_or_fill():
    result = run(episode_fee_bound=D(".5"))
    assert not result.admission.allowed
    assert result.admission.denial_code == "fee_exhausts_planned_risk"
    assert result.events == ()
    assert result.account.cash == D("100")


def test_unknown_fee_bound_does_not_become_zero_or_emit_an_order():
    result = run(episode_fee_bound=None)
    assert result.admission.denial_code == "unknown_fee_bound"
    assert not result.admission.allowed
    assert result.events == ()


def test_current_open_rounds_up_not_down_to_declared_tick():
    result = run(instrument=instrument(observed_at=OPEN), raw_open=D("100.001"))
    assert result.assumed_price == D("100.06")


@pytest.mark.parametrize(
    "changes",
    [
        {"decision_at": OPEN},
        {"decision_at": OPEN + timedelta(seconds=1)},
        {"instrument": instrument(observed_at=OPEN + timedelta(seconds=1))},
        {
            "observations": (
                CapitalRiskObservation(
                    EventCursor(0, OPEN - timedelta(seconds=1)), 0, None, True, True
                ),
            )
        },
        {"fill_fraction": D("1.1")},
        {"fill_fraction": D("0")},
        {"outcome": "partial", "fill_fraction": D("1")},
        {"outcome": "partial", "fill_fraction": D(".000001")},
        {"outcome": "unfilled", "fill_fraction": D("0")},
        {"side_fee": D(".11")},
        {"raw_open": D("NaN")},
        {"roundtrip_friction_pct": D(".01")},
        {"decision_hash": "not-a-hash"},
        {"opened": True},
        {"lifecycle_cursors": (EventCursor(2, OPEN), EventCursor(3, OPEN))},
    ],
)
def test_invalid_declared_inputs_deny_without_a_result(changes):
    with pytest.raises(ValueError):
        run(**changes)


def test_low_precision_does_not_change_price_sizing_or_original_hash():
    baseline = run()
    with localcontext() as context:
        context.prec = 3
        assert run() == baseline


def test_tampered_false_marker_cannot_construct_execution_authority():
    from trading_bot.simulation.etf_capital_daily_entry import simulate_capital_daily_entry

    value = request()
    object.__setattr__(value, "execution_enabled", True)
    with pytest.raises(ValueError):
        simulate_capital_daily_entry(value)


def test_pending_originals_block_second_entry_without_overwriting_history():
    from trading_bot.simulation.etf_capital_daily_entry import simulate_capital_daily_entry

    first = run(outcome="unfilled", fill_fraction=D("0"), side_fee=D("0"))
    later = OPEN + timedelta(days=1)
    original = first.events
    value = request(
        events=original,
        observations=(
            *first.observations,
            CapitalRiskObservation(EventCursor(50, later), len(original), None, True, True),
        ),
        decision_at=OPEN,
        opened=EventCursor(100, later),
        lifecycle_cursors=(
            EventCursor(101, later + timedelta(seconds=1)),
            EventCursor(102, later + timedelta(seconds=2)),
        ),
        instrument=instrument(observed_at=later, price_increment=D(".000001")),
    )
    result = simulate_capital_daily_entry(value)
    assert result.events == original
    assert not result.admission.allowed
    assert result.admission.denial_code == "account_episode_incomplete"
    assert result.account.available_cash == D("79.99005")


@pytest.mark.parametrize(
    "account_id,opened_sequence,allowed",
    [
        ("capital-daily-assumed", 100, True),
        ("other-assumed-account", 100, False),
        ("capital-daily-assumed", 5, False),
    ],
)
def test_completed_original_episode_reconstructs_before_readmission(
    account_id,
    opened_sequence,
    allowed,
):
    from tests.unit.simulation._lifecycle_fixtures import ORIGIN
    from tests.unit.simulation.test_etf_capital_account import script
    from trading_bot.domain import AccountId
    from trading_bot.simulation.etf_capital_account import (
        CapitalAccountSubmission,
        CapitalEpisodeFeesFinal,
    )
    from trading_bot.simulation.etf_capital_daily_entry import simulate_capital_daily_entry
    from trading_bot.simulation.lifecycle_models import LifecycleControlEvent, LifecycleFillEvent

    events = []
    for event in script():
        if isinstance(event, CapitalAccountSubmission):
            event = replace(
                event,
                request=replace(
                    event.request,
                    order=replace(event.request.order, account_id=AccountId(account_id)),
                    position=replace(event.request.position, account_id=AccountId(account_id)),
                ),
            )
        elif isinstance(event, LifecycleFillEvent):
            event = replace(event, fill=replace(event.fill, account_id=AccountId(account_id)))
        elif isinstance(event, (LifecycleControlEvent, CapitalEpisodeFeesFinal)):
            event = replace(event, account_id=AccountId(account_id))
        events.append(event)
    value = request(
        events=tuple(events),
        observations=(
            CapitalRiskObservation(EventCursor(0, ORIGIN), 0, None, True, True),
            CapitalRiskObservation(EventCursor(1, OPEN), len(events), None, True, True),
        ),
        opened=EventCursor(opened_sequence, OPEN),
        lifecycle_cursors=(
            EventCursor(101, OPEN + timedelta(seconds=1)),
            EventCursor(102, OPEN + timedelta(seconds=2)),
        ),
    )
    if not allowed:
        with pytest.raises(ValueError):
            simulate_capital_daily_entry(value)
    else:
        result = simulate_capital_daily_entry(value)
        assert result.events[:10] == tuple(events)
        assert result.admission.quantity == D(".200")
        assert result.account.cash == D("80.09")
        assert result.account.available_cash == D("80.00")
