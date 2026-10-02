"""Native-shaped records must reach the common owner, never a broker capability."""

import importlib
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.unit.simulation.test_etf_strategy import inputs
from trading_bot.domain import OrderState
from trading_bot.market_data.etf_source import EtfObservedBar, EtfObservedQuote, _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation.etf_native_models import (
    EtfHistoryRequest,
    EtfReplayDataset,
    EtfReplayEvent,
)

D = Decimal


def request(*, partial=False, reasons=(), scenario="base", close=True):
    fixture = inputs()
    events = []
    for event in fixture.prefix.events:
        kw = dict(
            ordinal=event.ordinal,
            event_at_ns=event.event_at_ns,
            available_at_ns=event.available_at_ns,
            source_hash=event.source_record_hash,
        )
        if isinstance(event, EtfObservedBar):
            events.append(EtfReplayEvent(**kw, kind="bar", bar=event.payload))
        elif isinstance(event, EtfObservedQuote):
            events.append(
                EtfReplayEvent(
                    **kw,
                    kind="quote",
                    bid=event.payload.bid,
                    ask=event.payload.ask,
                    bid_size=D("1"),
                    ask_size=D("1"),
                    execution_reasons=reasons,
                )
            )
        else:
            events.append(EtfReplayEvent(**kw, kind="session", clock=event.payload))
    first = events[-1]

    def q(delta, bid, ask, size):
        return replace(
            first,
            ordinal=events[-1].ordinal + 1,
            event_at_ns=first.event_at_ns + delta,
            available_at_ns=first.available_at_ns + delta,
            source_hash=content_hash((delta, bid, ask, size)),
            bid=D(bid),
            ask=D(ask),
            bid_size=D(size),
            ask_size=D(size),
        )

    events.append(q(20_000_000, "99.99", "100", ".04" if partial else "1"))
    if close:
        events.append(q(40_000_000, "97.99", "98", "1"))
        events.append(q(60_000_000, "97.99", "98", "1"))
        events.append(q(80_000_000, "97.99", "98", "1"))
        opening = events[750]
        clock = opening.clock
        assert clock is not None
        next_clock = replace(
            clock,
            observed_at=clock.observed_at + timedelta(days=1),
            next_close_at=clock.next_close_at + timedelta(days=1),
            next_open_at=clock.next_open_at + timedelta(days=1),
        )
        events.append(
            EtfReplayEvent(
                events[-1].ordinal + 1,
                _ns(next_clock.observed_at),
                _ns(next_clock.observed_at),
                content_hash("next-native-session"),
                "session",
                clock=next_clock,
            )
        )
    dataset = EtfReplayDataset(
        tuple(events),
        content_hash("fictional-native-shaped"),
        "synthetic",
        ("synthetic_inputs_only",),
    )
    return EtfHistoryRequest(
        fixture.prefix.study, dataset, fixture.costs, D("500"), scenario, fixture.instrument
    )


def test_native_execution_and_economic_entrypoints_exist():
    module = importlib.import_module("trading_bot.simulation.etf_native_history")
    assert callable(module.run_etf_history)
    assert callable(module.resume_etf_history)


def test_actual_signals_reserve_fill_protect_and_settle_with_shared_risk():
    from trading_bot.simulation.etf_native_history import run_etf_history

    result = run_etf_history(request())
    account = result.candidate.account
    assert account.complete and account.shares == 0
    assert account.cash == D("499.63553015")
    assert account.trial.consumed_loss == D(".36446985")
    assert [o.order.state for o in account.orders] == [OrderState.FILLED, OrderState.FILLED]
    assert account.orders[0].intent.quantity == D(".15")
    assert not result.execution_enabled and not result.evidence_promotable


def test_partial_entry_cancel_confirmation_precedes_protective_order():
    from trading_bot.simulation.etf_native_history import run_etf_history

    result = run_etf_history(request(partial=True))
    account = result.candidate.account
    assert account.complete and account.shares == 0
    assert account.orders[0].order.state is OrderState.CANCELED
    assert account.orders[1].intent.quantity == D(".02")


def test_unknown_market_semantics_cannot_simulate_orders():
    from trading_bot.simulation.etf_native_history import run_etf_history

    result = run_etf_history(request(reasons=("control_coverage_unverified",)))
    assert not result.candidate.account.orders
    assert result.candidate.account.cash == 500


def test_prefix_resume_reconstructs_cash_and_rejects_state_or_input_substitution():
    from trading_bot.simulation.etf_native_history import resume_etf_history, run_etf_history

    source = request()
    prefix = run_etf_history(source, through_ordinal=752)
    assert prefix.candidate.account.shares == D(".15")
    assert not prefix.candidate.account.complete
    assert resume_etf_history(source, prefix) == run_etf_history(source)
    with pytest.raises(ValueError):
        resume_etf_history(replace(source, initial_cash=D("1000")), prefix)
    with pytest.raises(ValueError):
        resume_etf_history(
            source,
            replace(
                prefix,
                candidate=replace(
                    prefix.candidate, account=replace(prefix.candidate.account, cash=D("501"))
                ),
            ),
        )


def test_unknown_acceptance_keeps_reservations_through_end_of_input():
    from trading_bot.simulation.etf_native_history import run_etf_history

    source = request()
    result = run_etf_history(
        replace(source, schedule=replace(source.schedule, acknowledgement="unknown"))
    )
    account = result.candidate.account
    assert account.orders[0].order.state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION
    assert account.reserved_cash == D("15.1") and not account.complete
