"""Independent-review reproductions remain regression requirements."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.unit.simulation.test_etf_native_adversarial import (
    control,
    later_bar,
    later_session,
    with_tail,
)
from tests.unit.simulation.test_etf_native_history import request
from trading_bot.domain import OrderPurpose
from trading_bot.market_data.etf_source import _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation.etf_native_history import run_etf_history
from trading_bot.simulation.etf_native_models import EtfReplayEvent


def test_stop_gap_below_initial_stop_distance_does_not_block_reducing_exit():
    source = request(close=False)
    proposal, filled = source.dataset.events[-2:]
    crashed = replace(
        filled,
        event_at_ns=filled.event_at_ns + 20_000_000,
        available_at_ns=filled.available_at_ns + 20_000_000,
        bid=Decimal(".99"),
        ask=Decimal(".991"),
    )
    result = run_etf_history(with_tail(source, (proposal, filled, crashed)))
    assert not any(d.reason == "stop_nonpositive" for d in result.candidate.decisions)
    assert result.candidate.account.orders[-1].intent.purpose is OrderPurpose.PROTECTIVE_EXIT
    assert result.candidate.account.orders[-1].intent.quantity == Decimal(".15")


def test_equal_native_control_cannot_ignore_new_unknown_execution_semantics():
    source = request(close=False)
    proposal, filled = source.dataset.events[-2:]
    known = control(
        source, proposal.event_at_ns + 5_000_000, proposal.available_at_ns + 5_000_000, halted=False
    )
    unknown = replace(
        known,
        available_at_ns=known.available_at_ns + 1_000_000,
        execution_reasons=("control_coverage_unverified",),
    )
    result = run_etf_history(with_tail(source, (proposal, known, unknown, filled)))
    assert result.candidate.account.shares == 0
    assert "conflicting_native_observations" in result.candidate.reasons


def test_delayed_ex_date_cannot_give_dividends_to_later_buyers():
    source = request(close=False)
    proposal, filled = source.dataset.events[-2:]
    dividend = EtfReplayEvent(
        999,
        source.dataset.events[750].event_at_ns,
        filled.available_at_ns + 10_000_000,
        content_hash("delayed-ex"),
        "dividend_ex",
        action_id=content_hash("action"),
        cash_per_share=Decimal("1"),
    )
    result = run_etf_history(with_tail(source, (proposal, filled, dividend)))
    assert result.candidate.account.dividend_receivable == 0
    assert "input_reconciliation_incomplete" in result.candidate.reasons


def test_halted_quote_is_not_an_executable_liquidation_mark_at_close():
    source = request(close=False)
    proposal, filled = source.dataset.events[-2:]
    close = _ns(source.dataset.events[750].clock.next_close_at)
    halt = control(
        source, filled.event_at_ns + 10_000_000, filled.available_at_ns + 10_000_000, halted=True
    )
    last = replace(filled, event_at_ns=close - 1_000_000_000, available_at_ns=close - 1_000_000_000)
    closing = control(source, close, close, halted=True)
    result = run_etf_history(with_tail(source, (proposal, filled, halt, last, closing)))
    assert result.candidate.daily[-1].bid is None
    assert result.candidate.daily[-1].nav is None


def delayed_prior_session(source, after_ns):
    opening = source.dataset.events[750]
    old_clock = replace(
        opening.clock,
        observed_at=opening.clock.observed_at - timedelta(days=1),
        next_close_at=opening.clock.next_close_at - timedelta(days=1),
        next_open_at=opening.clock.next_open_at - timedelta(days=1),
    )
    return replace(
        opening,
        event_at_ns=_ns(old_clock.observed_at),
        available_at_ns=after_ns,
        source_hash=content_hash("delayed-previous-session"),
        clock=old_clock,
    )


def test_previously_unseen_older_session_does_not_settle_completed_sales_or_replace_day():
    source = request()
    tail = source.dataset.events[751:-1]
    old = delayed_prior_session(source, tail[-1].available_at_ns + 1)
    baseline = run_etf_history(with_tail(source, tail))
    result = run_etf_history(with_tail(source, (*tail, old)))
    # Sales are finished, but both cash flows still need the NEXT genuine session.
    assert result.candidate.account.shares == 0
    assert result.candidate.account.unsettled
    assert result.candidate.account == baseline.candidate.account
    assert len(result.candidate.daily) == 1
    assert (
        result.candidate.daily[0].session_date
        == source.dataset.events[750].clock.observed_at.date()
    )
    assert not result.candidate.account.complete


def test_delayed_older_session_does_not_accelerate_the_five_session_entry_cadence():
    source = request()
    tail = list(source.dataset.events[751:-1])
    tail.append(delayed_prior_session(source, tail[-1].available_at_ns + 1))
    for day in range(1, 5):
        session = later_session(source, day)
        # Preserve a positive momentum history, so cadence is the reason not to enter.
        bar = later_bar(750 + day)
        price = Decimal("108") + Decimal(day) / 100
        bar = replace(
            bar,
            bar=replace(
                bar.bar,
                open=price,
                high=price + Decimal(".5"),
                low=price - Decimal(".5"),
                close=price,
            ),
        )
        quote = replace(
            source.dataset.events[751],
            event_at_ns=session.event_at_ns + 20_000_000,
            available_at_ns=session.available_at_ns + 20_000_000,
            source_hash=content_hash(("cadence-session-quote", day)),
            bid=Decimal("99.99"),
            ask=Decimal("100"),
        )
        tail.extend((bar, session, quote))
    result = run_etf_history(with_tail(source, tuple(tail)))
    assert len(result.candidate.policies) == 1
    assert len(result.candidate.account.orders) == 2
    assert result.candidate.account.shares == 0


def test_unknown_equal_control_semantics_remain_latched_until_strictly_newer_epoch():
    source = request(close=False)
    proposal, filled = source.dataset.events[-2:]
    known = control(
        source, proposal.event_at_ns + 5_000_000, proposal.available_at_ns + 5_000_000, halted=False
    )
    unknown = replace(
        known,
        available_at_ns=known.available_at_ns + 1_000_000,
        execution_reasons=("control_coverage_unverified",),
    )
    same_known = replace(known, available_at_ns=known.available_at_ns + 2_000_000)
    older_known = control(
        source, known.event_at_ns - 1_000_000, known.available_at_ns + 3_000_000, halted=False
    )
    prefix = (proposal, known, unknown, same_known, older_known, filled)
    denied = run_etf_history(with_tail(source, prefix))
    assert denied.candidate.account.shares == 0
    assert denied.candidate.account.reserved_cash == Decimal("15.1")
    newer = control(
        source, filled.event_at_ns + 5_000_000, filled.available_at_ns + 5_000_000, halted=False
    )
    fresh = replace(
        filled,
        event_at_ns=filled.event_at_ns + 20_000_000,
        available_at_ns=filled.available_at_ns + 20_000_000,
        source_hash=content_hash("post-control-reset-quote"),
    )
    recovered = run_etf_history(with_tail(source, (*prefix, newer, fresh)))
    assert recovered.candidate.account.shares == Decimal(".15")
    assert len(recovered.candidate.account.orders) == 1


def test_delayed_ex_date_followed_by_payment_never_credits_receipt_time_shares():
    source = request(close=False)
    proposal, filled = source.dataset.events[-2:]
    action_id = content_hash("delayed-and-paid-dividend")
    ex = EtfReplayEvent(
        999,
        source.dataset.events[750].event_at_ns,
        filled.available_at_ns + 10_000_000,
        content_hash("delayed-paid-ex-source"),
        "dividend_ex",
        action_id=action_id,
        cash_per_share=Decimal("1"),
    )
    pay_at = filled.available_at_ns + 20_000_000
    pay = EtfReplayEvent(
        1000,
        pay_at,
        pay_at,
        content_hash("delayed-paid-pay-source"),
        "dividend_pay",
        action_id=action_id,
    )
    result = run_etf_history(with_tail(source, (proposal, filled, ex, pay)))
    account = result.candidate.account
    assert account.shares == Decimal(".15")
    assert account.cash == Decimal("484.9685")
    assert account.dividend_receivable == 0
    assert "input_reconciliation_incomplete" in result.candidate.reasons
    assert not result.evidence_promotable


@pytest.mark.parametrize("cause", ("halt", "control-conflict", "reset", "split"))
def test_daily_liquidation_mark_requires_quote_valid_under_current_control_epoch(cause):
    source = request(close=False)
    proposal, filled = source.dataset.events[-2:]
    close = _ns(source.dataset.events[750].clock.next_close_at)
    tail = [proposal, filled]
    invalid_at = filled.event_at_ns + 10_000_000
    if cause == "halt":
        tail.append(control(source, invalid_at, invalid_at, halted=True))
    elif cause == "control-conflict":
        known = control(source, invalid_at, invalid_at, halted=False)
        conflict = replace(
            known,
            available_at_ns=invalid_at + 1,
            execution_reasons=("control_coverage_unverified",),
        )
        tail.extend((known, conflict))
    elif cause == "split":
        tail.append(
            EtfReplayEvent(
                999,
                invalid_at,
                invalid_at,
                content_hash("mark-split-source"),
                "split",
                action_id=content_hash("mark-split-id"),
            )
        )
    fresh_at_close = replace(
        filled,
        event_at_ns=close - 1_000_000_000,
        available_at_ns=close - 1_000_000_000,
        source_hash=content_hash(("closing-quote", cause)),
    )
    tail.append(fresh_at_close)
    if cause == "reset":
        # No quote after this reset: the otherwise fresh prior quote is not evidence
        # about the newly observed market-control epoch.
        tail.append(control(source, close - 500_000_000, close - 500_000_000, halted=False))
    tail.append(control(source, close, close, halted=cause == "halt"))
    result = run_etf_history(with_tail(source, tuple(tail)))
    assert result.candidate.account.shares == Decimal(".15")
    assert result.candidate.daily[-1].bid is None
    assert result.candidate.daily[-1].ask is None
    assert result.candidate.daily[-1].nav is None


def test_valid_recent_quote_can_supply_a_close_mark_without_forced_liquidation():
    source = request(close=False)
    proposal, filled = source.dataset.events[-2:]
    close = _ns(source.dataset.events[750].clock.next_close_at)
    recent = replace(
        filled,
        event_at_ns=close - 1_000_000_000,
        available_at_ns=close - 1_000_000_000,
        source_hash=content_hash("valid-close-mark"),
    )
    end = control(source, close, close, halted=False)
    result = run_etf_history(with_tail(source, (proposal, filled, recent, end)))
    assert result.candidate.account.shares == Decimal(".15")
    assert result.candidate.daily[-1].bid == Decimal("99.99")
    assert result.candidate.daily[-1].nav == Decimal("499.9670")
    assert len(result.candidate.account.orders) == 1


@pytest.mark.parametrize("late_open_day", (1, 2))
def test_late_session_behind_control_and_fill_frontier_cannot_settle_new_sale(late_open_day):
    source = request(close=False)
    proposal, entry_fill = source.dataset.events[-2:]
    current = later_session(source, 2)
    # Day 2's opening record was absent. Day 3's control and quotes are present,
    # so an existing frozen stop still has to close the owned position.
    native_control = replace(current, kind="control")
    stop = replace(
        entry_fill,
        event_at_ns=current.event_at_ns + 20_000_000,
        available_at_ns=current.available_at_ns + 20_000_000,
        source_hash=content_hash("missing-open-stop"),
        bid=Decimal("97.99"),
        ask=Decimal("98"),
    )
    sale = replace(
        stop,
        event_at_ns=stop.event_at_ns + 20_000_000,
        available_at_ns=stop.available_at_ns + 20_000_000,
        source_hash=content_hash("missing-open-sale"),
    )
    prefix = (proposal, entry_fill, native_control, stop, sale)
    before = run_etf_history(with_tail(source, prefix))
    assert before.candidate.account.shares == 0
    assert len(before.candidate.account.orders) == 2
    sale_fill = next(
        fact.fill.id
        for fact in before.candidate.account_events
        if fact.fill is not None
        and fact.fill.broker_order_id == before.candidate.account.orders[-1].intent.id
    )
    late_open = replace(
        later_session(source, late_open_day),
        available_at_ns=sale.available_at_ns + 1,
        source_hash=content_hash(("missing-open-late-session", late_open_day)),
    )
    result = run_etf_history(with_tail(source, (*prefix, late_open)))
    assert sale_fill in {row[0] for row in result.candidate.account.unsettled}
    assert not result.candidate.account.complete
    assert result.candidate.account.trial.reserved_risk > 0
    assert result.candidate.account.trial.consumed_loss == 0
