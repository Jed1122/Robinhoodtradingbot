"""Signals cannot grant transport, settlement, or research qualification."""

import importlib
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.unit.simulation.test_etf_account import instrument
from tests.unit.simulation.test_etf_fixture_execution import costs, quote
from tests.unit.simulation.test_etf_history import bar, request, session
from trading_bot.domain import OrderEvent, OrderPurpose, OrderState
from trading_bot.market_data.etf_source import _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation.etf_account import EtfAccountEvent
from trading_bot.simulation.etf_fixture_execution import EtfFixtureAccountObservation

D = Decimal
OPEN = session(751, 750)
AT = OPEN.available_at_ns
CASH = D("500")
WIDTH = D(".5")
FEES = D(".1")
SIZE = D("1")


def api():
    try:
        return importlib.import_module("trading_bot.simulation.etf_strategy")
    except ModuleNotFoundError:
        pytest.fail("ETF signal/account/execution coordinator is missing")


def inputs(*, cash=CASH, width=WIDTH, extra=(), notices=(), fees=FEES):
    history = tuple(bar(i, D("100") + D(i) / 100, width=width) for i in range(750))
    prefix = request((*history, OPEN, quote(751, AT + 20_000_000)), cash=cash)
    prefix = replace(prefix, events=(*prefix.events, *extra))
    package = costs()
    package = replace(
        package,
        intervals=tuple(
            replace(
                i,
                starts_at=OPEN.payload.observed_at - timedelta(days=1),
                ends_at=OPEN.payload.observed_at + timedelta(days=400),
                known_at=OPEN.payload.observed_at - timedelta(days=2),
            )
            for i in package.intervals
        ),
    )
    return api().EtfFixtureStrategyRequest(
        prefix,
        replace(instrument(), observed_at=OPEN.payload.observed_at),
        package,
        tuple(notices),
        fees,
    )


def run(**kwargs):
    return api().run_etf_fixture_strategy(inputs(**kwargs))


def status(result, ordinal, at, event, *, index=-1):
    record = result.account.orders[index]
    payload = EtfAccountEvent(
        content_hash(("strategy-notice", ordinal, at, event)),
        result.account.last_ordinal + 1,
        at,
        "order_status",
        order_id=record.intent.id,
        order_event=event,
    )
    return EtfFixtureAccountObservation(ordinal, payload)


def entry(*, size=SIZE):
    proposal = run()
    ack = status(proposal, 752, AT + 21_000_000, OrderEvent.BROKER_ACCEPTED)
    observed = quote(753, AT + 40_000_000, size=size)
    return run(extra=(observed,), notices=(ack,)), (observed,), (ack,)


def test_fixed_signal_creates_pending_fee_inclusive_reserved_order_not_same_event_fill():
    result = run()
    assert len(result.account.orders) == 1
    order = result.account.orders[0]
    assert order.order.state is OrderState.SUBMISSION_PENDING
    assert order.intent.quantity == D(".15")
    assert result.account.cash == 500 and result.account.shares == 0
    assert result.account.reserved_cash == D("15.1")
    assert result.policies[0].stop_price == 98 and result.policies[0].target_price == 104
    assert not result.execution_enabled and not result.evidence_promotable


def test_hypothetical_cash_does_not_increase_risk_reference_or_fee_infeasible_size():
    assert run(cash=D("1000")).account.orders[0].intent.quantity == D(".15")
    denied = run(width=D("1"))
    assert not denied.account.orders and denied.account.cash == 500
    assert any(d.reason == "fixture_account_admission_denied" for d in denied.decisions)


def test_protective_stop_gap_closes_only_at_later_bid_and_settlement_is_explicit():
    filled, observed, notices = entry()
    assert filled.account.shares == D(".15")
    stop = quote(754, AT + 50_000_000, bid=D("97.99"), ask=D("98"), size=D("1"))
    pending = run(extra=(*observed, stop), notices=notices)
    exit_order = pending.account.orders[-1]
    assert exit_order.intent.purpose is OrderPurpose.PROTECTIVE_EXIT
    assert exit_order.order.state is OrderState.SUBMISSION_PENDING
    assert pending.account.shares == D(".15")
    ack = status(pending, 755, AT + 51_000_000, OrderEvent.BROKER_ACCEPTED)
    closing = quote(756, AT + 70_000_000, bid=D("97.99"), ask=D("98"), size=D("1"))
    closed = run(extra=(*observed, stop, closing), notices=(*notices, ack))
    assert closed.account.shares == 0 and not closed.account.complete
    assert closed.account.cash == D("499.63553015")
    settlement = EtfAccountEvent(
        content_hash("strategy-final-settlement"),
        closed.account.last_ordinal + 1,
        AT + 80_000_000,
        "settlement",
        fill_ids=tuple(i[0] for i in closed.account.unsettled),
    )
    final = run(
        extra=(*observed, stop, closing),
        notices=(*notices, ack, EtfFixtureAccountObservation(757, settlement)),
    )
    assert final.account.complete and final.account.trial.consumed_loss == D(".36446985")
    assert final.account.trial.reserved_risk == 0


def test_partial_entry_stop_requires_explicit_cancel_before_protective_sell():
    _partial, observed, notices = entry(size=D(".04"))
    stop = quote(754, AT + 50_000_000, bid=D("97.99"), ask=D("98"))
    canceled = run(extra=(*observed, stop), notices=notices)
    assert len(canceled.account.orders) == 1
    assert canceled.account.orders[0].order.state is OrderState.CANCEL_PENDING
    assert canceled.account.reserved_cash > 0 and canceled.account.trial.reserved_risk == D("15.1")
    raced = quote(756, AT + 70_000_000)
    waiting = run(extra=(*observed, stop, raced), notices=notices)
    assert waiting.account.shares == D(".04") and len(waiting.account.orders) == 1
    confirmed = status(canceled, 755, AT + 60_000_000, OrderEvent.CANCEL_CONFIRMED)
    ready = run(extra=(*observed, stop, raced), notices=(*notices, confirmed))
    assert len(ready.account.orders) == 2
    assert ready.account.orders[-1].intent.quantity == D(".04")
    assert ready.account.orders[-1].intent.purpose is OrderPurpose.PROTECTIVE_EXIT


def test_prefix_resume_reconstructs_policy_orders_and_rejects_tampered_account():
    result, observed, notices = entry()
    full = inputs(extra=observed, notices=notices)
    partial = api().run_etf_fixture_strategy(full, through_ordinal=751)
    assert api().resume_etf_fixture_strategy(full, partial) == result
    forged = replace(partial, account=replace(partial.account, cash=D("999")))
    with pytest.raises(ValueError):
        api().resume_etf_fixture_strategy(full, forged)


def test_no_ack_no_end_of_input_liquidation_or_settlement():
    result = run(extra=(quote(753, AT + 40_000_000),))
    assert result.account.shares == 0 and result.account.reserved_cash == D("15.1")
    assert not result.account.complete
    assert _ns(result.account.orders[0].intent.created_at) == AT + 20_000_000


def test_stop_before_acknowledgement_waits_without_inventing_a_cancel_transition():
    result = run(extra=(quote(753, AT + 40_000_000, bid=D("97.99"), ask=D("98")),))
    assert result.account.orders[0].order.state is OrderState.SUBMISSION_PENDING
    assert result.account.reserved_cash == D("15.1") and result.account.shares == 0
    assert not result.account.complete
