"""Independent synthetic coordinator regressions; no actual-data readiness claim."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from tests.unit.simulation.test_etf_strategy import (
    AT,
    OPEN,
    api,
    bar,
    entry,
    inputs,
    quote,
    session,
    status,
)
from trading_bot.domain import OrderEvent, OrderPurpose, OrderState
from trading_bot.market_data.etf_source import EtfControlEvent, _ceil_time
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation.etf_account import EtfAccountEvent
from trading_bot.simulation.etf_fixture_execution import EtfFixtureAccountObservation

D = Decimal


@pytest.fixture(scope="module")
def base():
    return inputs()


@pytest.fixture(scope="module")
def proposal(base):
    return api().run_etf_fixture_strategy(base)


@pytest.fixture(scope="module")
def filled():
    return entry()


def evaluate(base, *, extra=(), notices=(), events=None, **changes):
    source = (*base.prefix.events, *extra) if events is None else tuple(events)
    req = replace(
        base, prefix=replace(base.prefix, events=source), notices=tuple(notices), **changes
    )
    return api().run_etf_fixture_strategy(req)


def control(ordinal, at, *, available=None, **flags):
    payload = replace(OPEN.payload, observed_at=_ceil_time(at), **flags)
    if not payload.is_open:
        payload = replace(payload, next_open_at=payload.observed_at + timedelta(minutes=30))
    digest = content_hash(("strategy-control", ordinal, at, available, flags))
    return EtfControlEvent(
        digest, ordinal, at, at if available is None else available, "SPY", None, payload
    )


def settlement(result, ordinal, at):
    payload = EtfAccountEvent(
        content_hash(("strategy-settlement", ordinal, at)),
        result.account.last_ordinal + 1,
        at,
        "settlement",
        fill_ids=tuple(i[0] for i in result.account.unsettled),
    )
    return EtfFixtureAccountObservation(ordinal, payload)


@pytest.mark.parametrize(
    "flags",
    [{"halted": True}, {"cancel_only": True}, {"trading_disabled": True}, {"is_open": False}],
)
def test_halt_and_disabled_controls_do_not_fill_or_release_pending_risk(base, proposal, flags):
    ack = status(proposal, 752, AT + 21_000_000, OrderEvent.BROKER_ACCEPTED)
    halt = control(753, AT + 25_000_000, **flags)
    result = evaluate(base, extra=(halt, quote(754, AT + 40_000_000)), notices=(ack,))
    assert result.account.shares == 0 and result.account.cash == 500
    assert result.account.reserved_cash == D("15.1")
    assert result.account.trial.reserved_risk == D("15.1")
    assert result.decisions[-1].reason == "fixture_control_disabled"


def test_equal_native_control_conflict_cannot_be_cleared_by_older_open(base, proposal):
    ack = status(proposal, 752, AT + 21_000_000, OrderEvent.BROKER_ACCEPTED)
    halted = control(753, AT + 25_000_000, halted=True)
    conflicting = control(754, AT + 25_000_000, available=AT + 26_000_000)
    old_open = control(755, AT + 24_000_000, available=AT + 27_000_000)
    result = evaluate(
        base, extra=(halted, conflicting, old_open, quote(756, AT + 40_000_000)), notices=(ack,)
    )
    assert result.account.shares == 0 and result.account.reserved_cash == D("15.1")
    assert result.decisions[-1].reason == "fixture_conflicting_native_observations"


@pytest.mark.parametrize("kind", ["stale", "before-control", "session-gap", "conflicting"])
def test_unusable_quotes_never_create_fills_or_settlement(base, proposal, kind):
    ack = status(proposal, 752, AT + 21_000_000, OrderEvent.BROKER_ACCEPTED)
    if kind == "stale":
        extra = (quote(753, AT + 40_000_000, available=AT + 6_040_000_000),)
    elif kind == "before-control":
        extra = (
            control(753, AT + 45_000_000),
            quote(754, AT + 40_000_000, available=AT + 50_000_000),
        )
    elif kind == "session-gap":
        extra = (quote(753, AT + 86400 * 10**9),)
    else:
        extra = (
            quote(753, AT + 20_000_000, available=AT + 40_000_000, bid=D("98.99"), ask=D("99")),
        )
    result = evaluate(base, extra=extra, notices=(ack,))
    assert result.account.shares == 0 and result.account.cash == 500
    assert result.account.reserved_cash == D("15.1") and not result.account.complete
    assert not result.account.unsettled


def test_stop_before_acknowledgement_preserves_unresolved_reservation(base):
    stop = quote(752, AT + 40_000_000, bid=D("97.99"), ask=D("98"))
    result = evaluate(base, extra=(stop,))
    assert result.account.shares == 0 and result.account.cash == 500
    assert result.account.reserved_cash == D("15.1")
    assert len(result.account.orders) == 1
    assert result.account.orders[0].order.state in (
        OrderState.SUBMISSION_PENDING,
        OrderState.CANCEL_PENDING,
        OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
    )


def test_rejection_does_not_retry_on_same_session_quotes(base, proposal):
    rejected = status(proposal, 752, AT + 21_000_000, OrderEvent.BROKER_REJECTED)
    result = evaluate(
        base, extra=(quote(753, AT + 40_000_000), quote(754, AT + 50_000_000)), notices=(rejected,)
    )
    assert len(result.account.orders) == 1 and len(result.policies) == 1
    assert result.account.orders[0].order.state is OrderState.REJECTED
    assert result.account.reserved_cash == 0 and result.account.shares == 0


def test_pre_ack_stop_latch_requests_cancel_after_ack_even_after_price_recovers(base):
    stop = quote(752, AT + 40_000_000, bid=D("97.99"), ask=D("98"))
    unresolved = evaluate(base, extra=(stop,))
    ack = status(unresolved, 753, AT + 50_000_000, OrderEvent.BROKER_ACCEPTED)
    recovered = quote(754, AT + 60_000_000, size=D("1"))
    result = evaluate(base, extra=(stop, recovered), notices=(ack,))
    assert len(result.account.orders) == 1 and result.account.shares == 0
    assert result.account.orders[0].order.state is OrderState.CANCEL_PENDING
    assert result.account.reserved_cash == D("15.1")


def test_ambiguous_submission_never_allows_protective_replacement(base, proposal):
    ambiguous = status(proposal, 752, AT + 21_000_000, OrderEvent.BROKER_AMBIGUOUS)
    stop = quote(753, AT + 40_000_000, bid=D("97.99"), ask=D("98"))
    result = evaluate(base, extra=(stop, quote(754, AT + 50_000_000)), notices=(ambiguous,))
    assert result.account.shares == 0 and len(result.account.orders) == 1
    assert result.account.orders[0].order.state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION
    assert result.account.reserved_cash == D("15.1")


def test_only_fifth_eligible_session_can_retry_rejected_entry(base, proposal):
    rejected = status(proposal, 752, AT + 21_000_000, OrderEvent.BROKER_REJECTED)
    extra = []
    for index in range(1, 6):
        opened = session(751 + index, 751 + index * 2)
        extra.extend((opened, quote(opened.ordinal + 1, opened.available_at_ns + 20_000_000)))
    result = evaluate(base, extra=extra, notices=(rejected,))
    assert [p.source_ordinal for p in result.policies] == [751, 762]
    assert len(result.account.orders) == 2


@pytest.mark.parametrize("kind", ["missing", "zero"])
def test_no_entry_with_missing_or_zero_atr(base, kind):
    history = tuple(bar(i, D("100"), width=D("0")) for i in range(750))
    if kind == "missing":
        history = history[:99]
    opened = session(751, len(history))
    observed = quote(len(history) + 1, opened.available_at_ns + 20_000_000)
    result = evaluate(base, events=(*history, opened, observed))
    assert not result.account.orders and result.account.cash == 500
    assert result.account.shares == 0 and result.account.reserved_cash == 0


def test_fee_infeasible_admission_is_not_retried_at_better_same_session_quote(base):
    result = evaluate(
        base,
        extra=(quote(752, AT + 40_000_000, bid=D("89.99"), ask=D("90")),),
        episode_fee_bound=D("1"),
    )
    assert not result.account.orders and result.account.cash == 500
    assert sum(d.reason == "fixture_account_admission_denied" for d in result.decisions) == 1


@pytest.mark.parametrize(
    "price,reason",
    [(D("1"), "fixture_stop_nonpositive"), (D("20000"), "fixture_common_sizing_denied")],
)
def test_nonpositive_stop_and_unsizeable_lot_cannot_reserve_an_order(base, price, reason):
    observed = quote(751, AT + 20_000_000, bid=price, ask=price)
    result = evaluate(base, events=(*base.prefix.events[:-1], observed))
    assert not result.account.orders and result.account.cash == 500
    assert result.account.reserved_cash == 0
    assert result.decisions[-1].reason == reason


def test_quote_at_same_nanosecond_as_ack_cannot_fill(base, proposal):
    ack = status(proposal, 752, AT + 40_000_000, OrderEvent.BROKER_ACCEPTED)
    observed = quote(753, AT + 40_000_000, size=D("1"))
    result = evaluate(base, extra=(observed,), notices=(ack,))
    assert result.account.shares == 0 and result.account.reserved_cash == D("15.1")
    assert result.account.orders[0].order.state is OrderState.SUBMITTED


def test_partial_entry_requires_explicit_settlement_before_continuation(base):
    _partial, observed, notices = entry(size=D(".04"))
    denied_quote = quote(754, AT + 50_000_000, size=D(".06"))
    denied = evaluate(base, extra=(*observed, denied_quote), notices=notices)
    assert denied.account.shares == D(".04")
    settled = settlement(denied, 755, AT + 60_000_000)
    continued = evaluate(
        base,
        extra=(*observed, denied_quote, quote(756, AT + 70_000_000, size=D(".06"))),
        notices=(*notices, settled),
    )
    assert continued.account.shares == D(".10")
    assert continued.account.fees == D(".031")
    assert continued.account.orders[0].order.state is OrderState.PARTIALLY_FILLED


def test_stop_gap_does_not_fill_at_stop_or_force_fill_below_sell_limit(base, filled):
    _result, observed, notices = filled
    stop = quote(754, AT + 50_000_000, bid=D("79.99"), ask=D("80"))
    pending = evaluate(base, extra=(*observed, stop), notices=notices)
    assert pending.account.shares == D(".15")
    assert pending.account.orders[-1].intent.limit_price == D("79.99")
    ack = status(pending, 755, AT + 51_000_000, OrderEvent.BROKER_ACCEPTED)
    result = evaluate(
        base,
        extra=(*observed, stop, quote(756, AT + 70_000_000, bid=D("78.99"), ask=D("79"))),
        notices=(*notices, ack),
    )
    assert result.account.shares == D(".15") and not result.account.complete
    assert result.account.orders[-1].order.state is OrderState.SUBMITTED


def test_target_creates_protective_order_without_same_quote_fill(base, filled):
    original, observed, notices = filled
    target = quote(754, AT + 50_000_000, bid=D("104"), ask=D("104.01"))
    result = evaluate(base, extra=(*observed, target), notices=notices)
    assert result.account.shares == D(".15") and result.account.fees == original.account.fees
    assert result.account.orders[-1].intent.purpose is OrderPurpose.PROTECTIVE_EXIT
    assert result.account.orders[-1].order.state is OrderState.SUBMISSION_PENDING
    assert any(d.reason == "fixture_target_triggered" for d in result.decisions)


@pytest.mark.parametrize("event", [OrderEvent.CANCEL_REJECTED, OrderEvent.BROKER_AMBIGUOUS])
def test_ambiguous_entry_cancellation_never_fabricates_exit_authority(base, event):
    _partial, observed, notices = entry(size=D(".04"))
    stop = quote(754, AT + 50_000_000, bid=D("97.99"), ask=D("98"))
    pending = evaluate(base, extra=(*observed, stop), notices=notices)
    unresolved = status(pending, 755, AT + 60_000_000, event)
    result = evaluate(
        base, extra=(*observed, stop, quote(756, AT + 70_000_000)), notices=(*notices, unresolved)
    )
    assert result.account.shares == D(".04") and len(result.account.orders) == 1
    assert result.account.orders[0].order.state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION
    assert result.account.reserved_cash > 0 and result.account.trial.reserved_risk == D("15.1")


def test_future_bar_correction_cannot_rewrite_entry_policy_or_prior_prefix(base, filled):
    original, observed, notices = filled
    correction = bar(
        749,
        D("1"),
        ordinal=754,
        available=AT + 50_000_000,
        revision=base.prefix.events[749].source_record_hash,
        width=D(".1"),
    )
    req = replace(
        base,
        prefix=replace(base.prefix, events=(*base.prefix.events, *observed, correction)),
        notices=notices,
    )
    result = api().run_etf_fixture_strategy(req)
    assert result.policies == original.policies
    assert result.policies[0].stop_price == 98 and result.policies[0].target_price == 104
    assert api().run_etf_fixture_strategy(req, through_ordinal=753) == original


@pytest.mark.parametrize("held,exit_expected", [(99, False), (100, True)])
def test_maximum_holding_counts_only_completed_visible_bars_since_first_fill(
    base, filled, held, exit_expected
):
    original, observed, notices = filled
    completed = tuple(bar(751 + i, D("100"), ordinal=754 + i, width=D(".1")) for i in range(held))
    opened = session(751 + held, 754 + held)
    latest = quote(755 + held, opened.available_at_ns + 20_000_000)
    result = evaluate(base, extra=(*observed, *completed, opened, latest), notices=notices)
    assert result.policies == original.policies
    assert result.account.shares == D(".15")
    assert any(d.reason == "fixture_maximum_holding" for d in result.decisions) == exit_expected
    assert len(result.account.orders) == (2 if exit_expected else 1)


@pytest.mark.parametrize("sessions,exit_expected", [(4, False), (5, True)])
def test_regime_exit_waits_for_new_eligible_cadence_frame(base, filled, sessions, exit_expected):
    original, observed, notices = filled
    correction = bar(
        749,
        D("1"),
        ordinal=754,
        available=AT + 50_000_000,
        revision=base.prefix.events[749].source_record_hash,
        width=D(".1"),
    )
    openings = tuple(session(752 + i, 755 + i) for i in range(sessions))
    latest = quote(755 + sessions, openings[-1].available_at_ns + 20_000_000)
    result = evaluate(base, extra=(*observed, correction, *openings, latest), notices=notices)
    assert result.policies == original.policies
    assert result.account.shares == D(".15")
    assert any(d.reason == "fixture_regime_exit" for d in result.decisions) == exit_expected
    assert len(result.account.orders) == (2 if exit_expected else 1)


def test_pending_order_recovers_after_non_executable_quote_with_fresh_quote(base, proposal):
    ack = status(proposal, 752, AT + 21_000_000, OrderEvent.BROKER_ACCEPTED)
    too_wide = quote(753, AT + 40_000_000, bid=D("90"), ask=D("100"))
    fresh = quote(754, AT + 50_000_000, size=D("1"))
    result = evaluate(base, extra=(too_wide, fresh), notices=(ack,))
    assert result.account.shares == D(".15")
    assert result.account.orders[0].order.state is OrderState.FILLED


def test_previous_session_regime_frame_cannot_trigger_exit_on_control_only_new_day(base, filled):
    _original, observed, notices = filled
    correction = bar(
        749,
        D("1"),
        ordinal=754,
        available=AT + 50_000_000,
        revision=base.prefix.events[749].source_record_hash,
        width=D(".1"),
    )
    openings = tuple(session(752 + i, 755 + i) for i in range(5))
    # No quote follows the day-756 cadence decision. The next day's control
    # establishes a quote epoch, not a new strategy decision frame.
    opening = session(757, 760)
    control_only = EtfControlEvent(
        opening.source_record_hash,
        opening.ordinal,
        opening.event_at_ns,
        opening.available_at_ns,
        "SPY",
        None,
        opening.payload,
    )
    result = evaluate(
        base,
        extra=(
            *observed,
            correction,
            *openings,
            control_only,
            quote(761, control_only.available_at_ns + 20_000_000),
        ),
        notices=notices,
    )
    assert not any(d.reason == "fixture_regime_exit" for d in result.decisions)
    assert len(result.account.orders) == 1 and result.account.shares == D(".15")


@pytest.mark.parametrize("bad", [True, D("NaN"), D("-1"), "0.1"])
def test_hostile_fee_bound_cannot_mutate_account_or_bypass_reservation(base, bad):
    with pytest.raises(ValueError):
        forged = replace(base, episode_fee_bound=bad)
        api().run_etf_fixture_strategy(forged)


def test_corrupted_quote_payload_denies_before_strategy_admission(base):
    observed = replace(base.prefix.events[-1], payload=replace(base.prefix.events[-1].payload))
    object.__setattr__(observed.payload, "bid", D("101"))
    with pytest.raises(ValueError):
        evaluate(base, events=(*base.prefix.events[:-1], observed))


def test_restart_reconstructs_exact_unsettled_partial_fill_and_policy(base):
    partial, observed, notices = entry(size=D(".04"))
    req = replace(
        base, prefix=replace(base.prefix, events=(*base.prefix.events, *observed)), notices=notices
    )
    checkpoint = api().run_etf_fixture_strategy(req, through_ordinal=751)
    assert api().resume_etf_fixture_strategy(req, checkpoint) == partial
    forged = replace(partial, policies=(replace(partial.policies[0], stop_price=D("1")),))
    with pytest.raises(ValueError, match="etf_history_invalid"):
        api().resume_etf_fixture_strategy(req, forged)


def test_partial_buy_cancel_trigger_stays_latched_after_price_recovers(base):
    _partial, observed, notices = entry(size=D(".04"))
    stop = quote(754, AT + 50_000_000, bid=D("97.99"), ask=D("98"))
    pending = evaluate(base, extra=(*observed, stop), notices=notices)
    confirmation = status(pending, 755, AT + 60_000_000, OrderEvent.CANCEL_CONFIRMED)
    recovered = quote(756, AT + 70_000_000, bid=D("100"), ask=D("100.01"))
    result = evaluate(base, extra=(*observed, stop, recovered), notices=(*notices, confirmation))
    assert result.account.orders[-1].intent.purpose is OrderPurpose.PROTECTIVE_EXIT
    assert result.account.orders[-1].intent.quantity == D(".04")
    assert result.account.shares == D(".04")


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_prefix_hash", "0" * 64),
        ("source_count", True),
        ("cost_hash", "0" * 64),
        ("decisions", ()),
        ("policies", ()),
    ],
)
def test_restart_rejects_tampered_coordinator_state(base, proposal, field, value):
    with pytest.raises(ValueError, match="etf_history_invalid"):
        api().resume_etf_fixture_strategy(base, replace(proposal, **{field: value}))


@pytest.mark.parametrize("ordinal", [True, -1, "751", 10000])
def test_hostile_prefix_boundary_denies(base, ordinal):
    with pytest.raises(ValueError, match="etf_history_invalid"):
        api().run_etf_fixture_strategy(base, through_ordinal=ordinal)


def test_hostile_decimal_context_cannot_change_orders_fees_or_risk(base, proposal):
    with localcontext() as context:
        context.prec = 2
        assert api().run_etf_fixture_strategy(base) == proposal


def test_no_end_of_input_exit_or_inferred_settlement(filled):
    result, _observed, _notices = filled
    assert result.account.shares == D(".15")
    assert len(result.account.orders) == 1 and result.account.unsettled
    assert not result.account.complete and result.account.trial.reserved_risk == D("15.1")
    assert result.paused and not result.execution_enabled and not result.evidence_promotable
