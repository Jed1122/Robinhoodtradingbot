"""Adversarial native-shaped replay inputs preserve the economic owner's gates."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.unit.simulation.test_etf_history import bar as observed_bar
from tests.unit.simulation.test_etf_native_history import request
from trading_bot.domain import AssetClass, BarInterval, OrderState
from trading_bot.market_data.etf_source import _ceil_time, _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation.etf_native_history import resume_etf_history, run_etf_history
from trading_bot.simulation.etf_native_models import EtfReplayEvent

D = Decimal


def with_tail(source, tail):
    """Keep the known 750-bar warmup and resequence only synthetic deliveries."""
    events = (*source.dataset.events[:751], *tail)
    return replace(
        source,
        dataset=replace(
            source.dataset,
            events=tuple(replace(event, ordinal=i) for i, event in enumerate(events)),
        ),
    )


def control(source, at_ns, available_ns, *, halted):
    opening = source.dataset.events[750]
    return EtfReplayEvent(
        999,
        at_ns,
        available_ns,
        content_hash(("adversarial-control", at_ns, available_ns, halted)),
        "control",
        clock=replace(opening.clock, observed_at=_ceil_time(at_ns), halted=halted),
    )


def test_duplicate_quote_delivery_does_not_replenish_consumed_capacity():
    source = request(partial=True, close=False)
    proposal, fill = source.dataset.events[-2:]
    duplicate = replace(fill, available_at_ns=fill.available_at_ns + 1_000_000)
    account = run_etf_history(with_tail(source, (proposal, fill, duplicate))).candidate.account
    # The displayed .04 shares support .02 shares under the base participation limit.
    assert account.shares == D(".02")
    assert account.orders[0].order.filled_quantity == D(".02")


def test_delayed_older_open_cannot_clear_newer_halt():
    source = request(close=False)
    proposal, fill = source.dataset.events[-2:]
    halt = control(
        source,
        proposal.event_at_ns + 10_000_000,
        proposal.available_at_ns + 10_000_000,
        halted=True,
    )
    older_open = control(
        source,
        proposal.event_at_ns + 5_000_000,
        proposal.available_at_ns + 11_000_000,
        halted=False,
    )
    account = run_etf_history(
        with_tail(source, (proposal, halt, older_open, fill))
    ).candidate.account
    assert account.shares == 0
    assert account.reserved_cash == D("15.1")
    assert not account.complete


def test_equal_native_quote_timestamp_conflict_cannot_be_repaired_by_redelivery():
    source = request(close=False)
    proposal, fill = source.dataset.events[-2:]
    unknown = replace(fill, execution_reasons=("condition_unverified",))
    purported_repair = replace(fill, available_at_ns=fill.available_at_ns + 1_000_000)
    repeated = replace(purported_repair, available_at_ns=fill.available_at_ns + 2_000_000)
    result = run_etf_history(with_tail(source, (proposal, unknown, purported_repair, repeated)))
    assert result.candidate.account.shares == 0
    assert "conflicting_native_observations" in result.candidate.reasons


def test_stale_quote_does_not_fill_an_acknowledged_pending_order():
    source = request(close=False)
    proposal, fill = source.dataset.events[-2:]
    stale = replace(fill, available_at_ns=fill.available_at_ns + 60_000_000_000)
    result = run_etf_history(with_tail(source, (proposal, stale)))
    assert result.candidate.account.shares == 0
    assert any(d.reason == "quote_stale" for d in result.candidate.decisions)


def test_missing_cost_window_cannot_be_assumed_zero_cost():
    source = request(close=False)
    proposal, _ = source.dataset.events[-2:]
    costs = replace(
        source.costs,
        intervals=tuple(
            replace(row, ends_at=_ceil_time(proposal.available_at_ns))
            if row.role == "latency"
            else row
            for row in source.costs.intervals
        ),
    )
    result = run_etf_history(replace(source, costs=costs))
    assert result.candidate.account.shares == 0
    assert any(d.reason == "cost_window_unavailable" for d in result.candidate.decisions)


def test_new_fee_epoch_cannot_reprice_an_existing_order():
    source = request(close=False)
    _, fill = source.dataset.events[-2:]
    boundary = _ceil_time(fill.event_at_ns)
    intervals = tuple(
        part
        for row in source.costs.intervals
        for part in (
            replace(row, ends_at=boundary),
            replace(
                row,
                starts_at=boundary,
                value=D(".02") if row.role == "minimum_commission" else row.value,
            ),
        )
    )
    result = run_etf_history(replace(source, costs=replace(source.costs, intervals=intervals)))
    assert result.candidate.account.shares == 0
    assert any(
        d.reason == "fee_or_account_reconciliation_denied" for d in result.candidate.decisions
    )


def test_unknown_cancel_retains_partial_entry_and_never_creates_protective_sell():
    source = request(partial=True)
    result = run_etf_history(
        replace(source, schedule=replace(source.schedule, cancellation="unknown"))
    )
    account = result.candidate.account
    assert len(account.orders) == 1
    assert account.orders[0].order.state is OrderState.CANCEL_PENDING
    assert account.shares == D(".02")
    assert account.reserved_cash > 0 and account.trial.reserved_risk > 0
    assert not account.complete


def test_delayed_acknowledgement_does_not_fill_at_end_of_input():
    source = request(close=False)
    result = run_etf_history(
        replace(source, schedule=replace(source.schedule, acknowledgement_delay_ns=60_000_000_000))
    )
    account = result.candidate.account
    assert account.orders[0].order.state is OrderState.SUBMISSION_PENDING
    assert account.shares == 0 and account.reserved_cash == D("15.1")


def test_rejected_order_releases_reservation_without_creating_cash_flow():
    source = request(close=False)
    result = run_etf_history(
        replace(source, schedule=replace(source.schedule, acknowledgement="reject"))
    )
    account = result.candidate.account
    assert account.orders[0].order.state is OrderState.REJECTED
    assert account.cash == 500 and account.shares == 0
    assert account.reserved_cash == 0 and account.trial.consumed_loss == 0


def test_whole_share_only_instrument_cannot_bypass_fifteen_dollar_entry_cap():
    source = request()
    result = run_etf_history(
        replace(source, instrument=replace(source.instrument, fractional_eligible=False))
    )
    assert not result.candidate.account.orders
    assert result.candidate.account.cash == 500


def test_higher_hypothetical_cash_does_not_raise_fixed_risk_reference():
    source = request(close=False)
    result = run_etf_history(replace(source, initial_cash=D("1000")))
    assert result.candidate.account.orders[0].intent.quantity == D(".15")
    assert result.candidate.account.shares == D(".15")


def test_no_terminal_sale_or_settlement_is_fabricated_for_open_position():
    result = run_etf_history(request(close=False))
    account = result.candidate.account
    assert account.shares == D(".15") and len(account.orders) == 1
    assert account.unsettled and account.trial.reserved_risk == D("15.1")
    assert not account.complete


def test_duplicate_session_cannot_advance_settlement_clock_within_same_session():
    source = request()
    opening = source.dataset.events[750]
    last_quote = source.dataset.events[-2]
    same_session_redelivery = replace(
        opening, available_at_ns=last_quote.available_at_ns + 1_000_000
    )
    # Both fills occurred today; duplicate session identity is invalid input,
    # not evidence that their settlement delay has elapsed.
    with pytest.raises(ValueError):
        run_etf_history(
            with_tail(source, (*source.dataset.events[751:-1], same_session_redelivery))
        )


@pytest.mark.parametrize(("allow_race", "expected_shares"), ((False, ".02"), (True, ".15")))
def test_explicit_inflight_cancel_race_only_fills_remaining_original_order(
    allow_race, expected_shares
):
    source = request(partial=True)
    source = with_tail(source, source.dataset.events[751:-2])
    source = replace(
        source,
        schedule=replace(
            source.schedule,
            cancellation_delay_ns=1_000_000_000,
            allow_inflight_cancel_fill=allow_race,
        ),
    )
    result = run_etf_history(source)
    account = result.candidate.account
    assert account.shares == D(expected_shares)
    assert len(account.orders) == 1
    assert account.orders[0].intent.quantity == D(".15")
    assert account.orders[0].order.state is (
        OrderState.FILLED if allow_race else OrderState.CANCEL_PENDING
    )
    assert not account.complete and not result.execution_enabled


@pytest.mark.parametrize(
    ("owner", "flag", "value"),
    (("dataset", "source_qualified", True), ("costs", "execution_enabled", True)),
)
def test_mutated_input_authority_flags_are_rejected_before_replay(owner, flag, value):
    source = request()
    object.__setattr__(getattr(source, owner), flag, value)
    with pytest.raises(ValueError):
        run_etf_history(source)


def test_holdout_observation_cannot_trigger_protective_exit_or_fill():
    source = request(close=False)
    first_quote = source.dataset.events[-1]
    boundary = _ns(source.study.holdout_start)
    holdout_quote = replace(
        first_quote,
        ordinal=first_quote.ordinal + 1,
        event_at_ns=boundary,
        available_at_ns=boundary,
        source_hash=content_hash("sealed-holdout-crash-quote"),
        bid=D("1"),
        ask=D("1.01"),
    )
    dataset = replace(source.dataset, events=(*source.dataset.events, holdout_quote))
    result = run_etf_history(replace(source, dataset=dataset))
    assert result.candidate.account.shares == D(".15")
    assert len(result.candidate.account.orders) == 1
    assert result.source_count == len(source.dataset.events)


def test_delayed_pre_holdout_event_is_still_excluded_after_holdout_boundary():
    source = request(close=False)
    boundary = _ns(source.study.holdout_start)
    last = source.dataset.events[-1]
    late = replace(
        last,
        ordinal=last.ordinal + 1,
        event_at_ns=boundary - 1,
        available_at_ns=boundary + 1,
        source_hash=content_hash("late-pre-holdout-quote"),
    )
    result = run_etf_history(
        replace(source, dataset=replace(source.dataset, events=(*source.dataset.events, late)))
    )
    assert result.source_count == len(source.dataset.events)
    assert result.candidate.account.shares == D(".15")


@pytest.mark.parametrize("malformation", ("intraday", "interpolated"))
def test_invalid_daily_feature_inputs_are_rejected_before_replay(malformation):
    source = request()
    first = source.dataset.events[0]
    bar = replace(
        first.bar,
        **(
            {"interval": BarInterval.ONE_MINUTE}
            if malformation == "intraday"
            else {"interpolated": True}
        ),
    )
    with pytest.raises(ValueError):
        altered = replace(first, bar=bar)
        run_etf_history(
            replace(
                source,
                dataset=replace(source.dataset, events=(altered, *source.dataset.events[1:])),
            )
        )


@pytest.mark.parametrize("malformation", ("asset_class", "event_time"))
def test_inconsistent_market_control_identity_is_rejected_before_replay(malformation):
    source = request()
    session = source.dataset.events[750]
    clock = replace(
        session.clock,
        **(
            {"asset_class": AssetClass.CRYPTO}
            if malformation == "asset_class"
            else {"observed_at": session.clock.observed_at + timedelta(seconds=1)}
        ),
    )
    with pytest.raises(ValueError):
        altered = replace(session, clock=clock)
        run_etf_history(
            replace(
                source,
                dataset=replace(
                    source.dataset,
                    events=(*source.dataset.events[:750], altered, *source.dataset.events[751:]),
                ),
            )
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("acknowledgement_delay_ns", 0),
        ("acknowledgement_delay_ns", True),
        ("cancellation_delay_ns", -1),
        ("cancellation_delay_ns", 86_400_000_000_001),
        ("acknowledgement", "filled"),
        ("cancellation", "retry"),
        ("settlement_sessions", 0),
        ("settlement_sessions", 11),
        ("settlement_sessions", True),
        ("allow_inflight_cancel_fill", 1),
        ("episode_fee_bound", D("-1")),
    ),
)
def test_unsafe_or_ambiguous_simulation_schedules_are_not_constructible(field, value):
    source = request(close=False)
    with pytest.raises(ValueError):
        replace(source.schedule, **{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    (("initial_cash", D("1001")), ("initial_cash", D("0")), ("fill_scenario", "best-case")),
)
def test_unregistered_capital_and_scenarios_cannot_enter_frozen_study(field, value):
    source = request(close=False)
    with pytest.raises(ValueError):
        replace(source, **{field: value})


@pytest.mark.parametrize(
    ("changes", "expected_reason"),
    (
        ({"bid": D("0")}, "quote_not_two_sided_unlocked"),
        ({"bid": D("100"), "ask": D("100")}, "quote_not_two_sided_unlocked"),
        ({"bid": D("101"), "ask": D("100")}, "quote_not_two_sided_unlocked"),
        ({"bid": D("1"), "ask": D("100")}, "quote_spread_too_wide"),
        ({"ask_size": None}, "quote_capacity_unverified"),
        ({"bid_size": None}, "quote_capacity_unverified"),
    ),
)
def test_unexecutable_quote_cannot_create_an_entry_or_consume_cash(changes, expected_reason):
    source = request(close=False)
    quotes = tuple(replace(q, **changes) for q in source.dataset.events[-2:])
    result = run_etf_history(with_tail(source, quotes))
    assert not result.candidate.account.orders
    assert result.candidate.account.cash == 500
    assert expected_reason in result.candidate.reasons


def test_quote_without_any_session_control_cannot_create_orders():
    source = request(close=False)
    result = run_etf_history(
        replace(
            source,
            dataset=replace(
                source.dataset,
                events=(*source.dataset.events[:750], *source.dataset.events[751:]),
            ),
        )
    )
    assert not result.candidate.account.orders
    assert "market_control_unverified" in result.candidate.reasons


@pytest.mark.parametrize("missing_close", (True, False))
def test_missing_or_elapsed_session_end_prevents_entry(missing_close):
    source = request(close=False)
    session = source.dataset.events[750]
    first = source.dataset.events[751]
    invalid = replace(
        session,
        clock=replace(
            session.clock,
            next_close_at=None if missing_close else _ceil_time(first.available_at_ns),
        ),
    )
    events = (*source.dataset.events[:750], invalid, *source.dataset.events[751:])
    result = run_etf_history(replace(source, dataset=replace(source.dataset, events=events)))
    assert not result.candidate.account.orders
    assert "market_session_unavailable" in result.candidate.reasons


def test_quote_at_control_epoch_is_not_later_executable_evidence():
    source = request(close=False)
    opening = source.dataset.events[750]
    quote = replace(
        source.dataset.events[751],
        event_at_ns=opening.event_at_ns,
        available_at_ns=opening.available_at_ns,
    )
    result = run_etf_history(with_tail(source, (quote,)))
    assert not result.candidate.account.orders
    assert "quote_before_control_epoch" in result.candidate.reasons


def test_same_timestamp_conflicting_control_latches_deny_until_new_epoch():
    source = request(close=False)
    proposal, fill = source.dataset.events[-2:]
    halt = control(source, proposal.event_at_ns + 1, proposal.available_at_ns + 1, halted=True)
    conflict = replace(
        halt, clock=replace(halt.clock, halted=False), available_at_ns=halt.available_at_ns + 1
    )
    result = run_etf_history(with_tail(source, (proposal, halt, conflict, fill)))
    assert result.candidate.account.shares == 0
    assert "conflicting_native_observations" in result.candidate.reasons


def test_later_delivery_of_older_quote_cannot_overwrite_price_frontier():
    source = request(close=False)
    proposal, fill = source.dataset.events[-2:]
    delayed = replace(proposal, available_at_ns=fill.available_at_ns + 1)
    result = run_etf_history(with_tail(source, (proposal, fill, delayed)))
    assert result.candidate.account.shares == D(".15")
    assert any(d.reason == "native_quote_time_regression" for d in result.candidate.decisions)


@pytest.mark.parametrize("capacity", ("0", ".000001"))
def test_zero_or_subincrement_capacity_never_rounds_up_into_a_fill(capacity):
    source = request(close=False)
    proposal, fill = source.dataset.events[-2:]
    result = run_etf_history(with_tail(source, (proposal, replace(fill, ask_size=D(capacity)))))
    assert result.candidate.account.shares == 0
    assert any(d.reason == "capacity_exhausted" for d in result.candidate.decisions)


def test_multiple_partial_fills_charge_one_order_minimum_and_conserve_cash():
    source = request(partial=True, close=False)
    proposal, first = source.dataset.events[-2:]
    second = replace(
        first,
        event_at_ns=first.event_at_ns + 20_000_000,
        available_at_ns=first.available_at_ns + 20_000_000,
        source_hash=content_hash("second-partial-native-quote"),
        ask_size=D("1"),
    )
    account = run_etf_history(with_tail(source, (proposal, first, second))).candidate.account
    assert account.shares == D(".15")
    # .15 shares at $100, one $.03 commission minimum, $.0015 regulatory fee.
    assert account.cash == D("484.9685")
    assert account.fees == D(".0315")
    assert account.orders[0].order.state is OrderState.FILLED


def test_adverse_rounding_and_slippage_cannot_cross_the_original_buy_limit():
    source = request(close=False)
    costs = replace(
        source.costs,
        intervals=tuple(
            replace(row, value=D(".01")) if row.role == "extra_slippage" else row
            for row in source.costs.intervals
        ),
    )
    result = run_etf_history(replace(source, costs=costs))
    assert result.candidate.account.shares == 0
    assert any(d.reason == "limit_not_marketable" for d in result.candidate.decisions)


def test_late_ack_after_day_order_expiry_remains_unknown_not_rejected():
    source = request()
    source = replace(
        source, schedule=replace(source.schedule, acknowledgement_delay_ns=86_400_000_000_000)
    )
    # The final next-day session reaches the acknowledgement timestamp only when
    # shifted past the original proposal's 20 ms offset.
    events = source.dataset.events
    final = replace(events[-1], available_at_ns=events[-1].available_at_ns + 40_000_000)
    result = run_etf_history(
        replace(source, dataset=replace(source.dataset, events=(*events[:-1], final)))
    )
    account = result.candidate.account
    assert account.orders[0].order.state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION
    assert account.reserved_cash == D("15.1") and account.shares == 0


def test_acknowledged_unfilled_day_order_expires_only_at_observed_later_event():
    source = request()
    events = tuple(
        replace(event, ask_size=D("0")) if event.kind == "quote" else event
        for event in source.dataset.events
    )
    # Remove stop-triggering price changes, so the expiry is not a cancel result.
    events = tuple(
        replace(event, bid=D("99.99"), ask=D("100")) if event.kind == "quote" else event
        for event in events
    )
    result = run_etf_history(replace(source, dataset=replace(source.dataset, events=events)))
    assert result.candidate.account.orders[0].order.state is OrderState.EXPIRED
    assert result.candidate.account.cash == 500 and result.candidate.account.reserved_cash == 0


def test_target_exit_uses_later_bid_and_is_not_applied_to_buy_and_hold_reference():
    source = request(close=False)
    last = source.dataset.events[-1]
    target = replace(
        last,
        event_at_ns=last.event_at_ns + 20_000_000,
        available_at_ns=last.available_at_ns + 20_000_000,
        bid=D("104"),
        ask=D("104.01"),
        source_hash=content_hash("target-trigger"),
    )
    closing = replace(
        target,
        event_at_ns=target.event_at_ns + 20_000_000,
        available_at_ns=target.available_at_ns + 20_000_000,
        source_hash=content_hash("target-closing"),
    )
    result = run_etf_history(with_tail(source, (*source.dataset.events[751:], target, closing)))
    assert any(d.reason == "target_triggered" for d in result.candidate.decisions)
    assert result.candidate.account.shares == 0
    assert result.constrained_benchmark.account.shares == D(".15")
    assert result.candidate.account.cash == D("500.53694")


def test_warmup_shortage_never_counts_as_a_flat_strategy_evaluation():
    source = request(close=False)
    dataset = replace(source.dataset, events=source.dataset.events[1:])
    result = run_etf_history(replace(source, dataset=dataset))
    assert not result.candidate.account.orders
    assert not result.candidate.daily
    assert any(d.reason == "warmup_incomplete" for d in result.candidate.decisions)


def test_split_cannot_silently_adjust_holdings_or_unlock_later_execution():
    source = request(close=False)
    proposal, fill = source.dataset.events[-2:]
    split = EtfReplayEvent(
        999,
        proposal.event_at_ns + 1,
        proposal.available_at_ns + 1,
        content_hash("split-source"),
        "split",
        action_id=content_hash("split-id"),
    )
    result = run_etf_history(with_tail(source, (proposal, split, fill)))
    assert result.candidate.account.shares == 0
    assert result.candidate.account.reserved_cash == D("15.1")
    assert "split_accounting_unsupported" in result.candidate.reasons


def test_dividend_entitlement_is_cash_receivable_until_actual_payment_event():
    source = request(close=False)
    fill = source.dataset.events[-1]
    ex = EtfReplayEvent(
        999,
        fill.event_at_ns + 1,
        fill.available_at_ns + 1,
        content_hash("dividend-source-ex"),
        "dividend_ex",
        action_id=content_hash("dividend-id"),
        cash_per_share=D("1"),
    )
    pay = EtfReplayEvent(
        1000,
        fill.event_at_ns + 2,
        fill.available_at_ns + 2,
        content_hash("dividend-source-pay"),
        "dividend_pay",
        action_id=content_hash("dividend-id"),
    )
    receivable = run_etf_history(with_tail(source, (*source.dataset.events[751:], ex)))
    paid = run_etf_history(with_tail(source, (*source.dataset.events[751:], ex, pay)))
    assert receivable.candidate.account.cash == D("484.9685")
    assert receivable.candidate.account.dividend_receivable == D(".15")
    assert paid.candidate.account.cash == D("485.1185")
    assert paid.candidate.account.dividend_receivable == 0


def test_empty_development_result_cannot_be_claimed_as_a_restart_checkpoint():
    source = request(close=False)
    first = source.dataset.events[-1]
    at = _ns(source.study.holdout_start)
    holdout = replace(first, event_at_ns=at, available_at_ns=at)
    source = replace(source, dataset=replace(source.dataset, events=(holdout,)))
    result = run_etf_history(source)
    assert result.source_count == 0 and not result.candidate.account.orders
    with pytest.raises(ValueError):
        resume_etf_history(source, result)


@pytest.mark.parametrize("ordinal", (True, -1, 999999))
def test_invalid_checkpoint_prefix_selector_does_not_fall_back_to_full_run(ordinal):
    with pytest.raises(ValueError):
        run_etf_history(request(close=False), through_ordinal=ordinal)


def later_session(source, days):
    opening = source.dataset.events[750]
    clock = opening.clock
    shifted = replace(
        clock,
        observed_at=clock.observed_at + timedelta(days=days),
        next_open_at=clock.next_open_at + timedelta(days=days),
        next_close_at=clock.next_close_at + timedelta(days=days),
    )
    return replace(
        opening,
        event_at_ns=_ns(shifted.observed_at),
        available_at_ns=_ns(shifted.observed_at),
        source_hash=content_hash(("later-session", days)),
        clock=shifted,
    )


def later_bar(day):
    observed = observed_bar(day, D("100"), width=D(".5"))
    return EtfReplayEvent(
        999,
        observed.event_at_ns,
        observed.available_at_ns,
        observed.source_record_hash,
        "bar",
        bar=observed.payload,
    )


def quote_after_session(source, session, *, offset=20_000_000):
    return replace(
        source.dataset.events[-1],
        event_at_ns=session.event_at_ns + offset,
        available_at_ns=session.available_at_ns + offset,
        source_hash=content_hash(("later-quote", session.event_at_ns, offset)),
    )


def test_maximum_holding_exit_uses_completed_bars_and_keeps_reference_open():
    source = request(close=False)
    session = later_session(source, 100)
    tail = (
        *source.dataset.events[751:],
        *(later_bar(day) for day in range(751, 851)),
        session,
        quote_after_session(source, session),
        quote_after_session(source, session, offset=40_000_000),
    )
    result = run_etf_history(with_tail(source, tail))
    assert any(d.reason == "maximum_holding" for d in result.candidate.decisions)
    assert result.candidate.account.shares == 0
    assert result.constrained_benchmark.account.shares == D(".15")


def test_regime_invalidation_only_closes_on_frozen_five_session_cadence():
    source = request(close=False)
    tail = list(source.dataset.events[751:])
    for days in range(1, 6):
        session = later_session(source, days)
        tail.extend((later_bar(750 + days), session, quote_after_session(source, session)))
        if days == 4:
            before = run_etf_history(with_tail(source, tuple(tail)))
            assert before.candidate.account.shares == D(".15")
            assert len(before.candidate.account.orders) == 1
    tail.append(quote_after_session(source, session, offset=40_000_000))
    result = run_etf_history(with_tail(source, tuple(tail)))
    assert any(d.reason == "regime_exit" for d in result.candidate.decisions)
    assert result.candidate.account.shares == 0
    assert result.constrained_benchmark.account.shares == D(".15")


def test_missing_new_features_do_not_disable_existing_stop_or_dividend_liability():
    source = request(close=False)
    fill = source.dataset.events[-1]
    ex = EtfReplayEvent(
        999,
        fill.event_at_ns + 1,
        fill.available_at_ns + 1,
        content_hash("feature-distribution-ex"),
        "dividend_ex",
        action_id=content_hash("feature-distribution-id"),
        cash_per_share=D("1"),
    )
    session = later_session(source, 1)
    stop = replace(quote_after_session(source, session), bid=D("97.99"), ask=D("98"))
    closing = replace(
        quote_after_session(source, session, offset=40_000_000), bid=D("97.99"), ask=D("98")
    )
    result = run_etf_history(
        with_tail(source, (*source.dataset.events[751:], ex, session, stop, closing))
    )
    assert any(
        d.reason == "completed_previous_session_bar_missing" for d in result.candidate.decisions
    )
    assert result.candidate.account.shares == 0
    assert result.candidate.account.dividend_receivable == D(".15")


def test_corrected_daily_bar_is_flagged_instead_of_silently_becoming_original_vintage():
    source = request(close=False)
    last = source.dataset.events[749]
    revision = replace(
        last,
        available_at_ns=last.available_at_ns + 1,
        source_hash=content_hash("corrected-bar-source"),
        bar=replace(last.bar, volume=last.bar.volume + 1),
    )
    events = (*source.dataset.events[:750], revision, *source.dataset.events[750:])
    events = tuple(replace(event, ordinal=i) for i, event in enumerate(events))
    result = run_etf_history(replace(source, dataset=replace(source.dataset, events=events)))
    assert "bar_revision_timeline_unverified" in result.candidate.reasons
    assert not result.evidence_promotable


@pytest.mark.parametrize(
    ("scenario", "shares"), (("conservative", ".01"), ("base", ".02"), ("optimistic", ".04"))
)
def test_fixed_scenarios_change_participation_without_raising_order_risk(scenario, shares):
    result = run_etf_history(request(partial=True, close=False, scenario=scenario))
    assert result.candidate.account.orders[0].intent.quantity == D(".15")
    assert result.candidate.account.shares == D(shares)


def test_fee_infeasibility_is_denied_by_canonical_account_owner():
    source = request(close=False)
    result = run_etf_history(
        replace(source, schedule=replace(source.schedule, episode_fee_bound=D("50")))
    )
    assert not result.candidate.account.orders
    assert any(d.reason == "canonical_account_admission_denied" for d in result.candidate.decisions)
    assert result.candidate.account.cash == 500


def test_stop_distance_cannot_create_a_nonpositive_protective_price():
    source = request(close=False)
    quotes = tuple(replace(q, bid=D(".9999"), ask=D("1")) for q in source.dataset.events[-2:])
    result = run_etf_history(with_tail(source, quotes))
    assert not result.candidate.account.orders
    assert any(d.reason == "stop_nonpositive" for d in result.candidate.decisions)


def test_first_quote_at_acknowledgement_time_is_not_a_later_eligible_fill():
    source = request(close=False)
    proposal, fill = source.dataset.events[-2:]
    tied = replace(
        fill,
        event_at_ns=proposal.event_at_ns + 1_000_000,
        available_at_ns=proposal.available_at_ns + 1_000_000,
    )
    result = run_etf_history(with_tail(source, (proposal, tied)))
    assert result.candidate.account.shares == 0
    assert result.candidate.account.orders[0].order.state is OrderState.SUBMITTED
    assert any(d.reason == "latency_or_ack_pending" for d in result.candidate.decisions)


def test_submicrosecond_followup_cannot_precede_rounded_account_mutation():
    source = request(close=False)
    first = source.dataset.events[751]
    proposal = replace(
        first, event_at_ns=first.event_at_ns + 1, available_at_ns=first.available_at_ns + 1
    )
    early = replace(
        first,
        event_at_ns=first.event_at_ns + 2,
        available_at_ns=first.available_at_ns + 2,
        source_hash=content_hash("submicrosecond-quote"),
    )
    result = run_etf_history(with_tail(source, (proposal, early)))
    assert result.candidate.account.shares == 0
    assert any(d.reason == "account_time_not_reached" for d in result.candidate.decisions)


def test_whole_share_execution_respects_lot_increment_when_canonical_risk_allows_it():
    source = request(close=False)
    events = []
    for event in source.dataset.events:
        if event.bar is not None:
            event = replace(
                event,
                bar=replace(
                    event.bar, high=event.bar.close + D(".01"), low=event.bar.close - D(".01")
                ),
            )
        elif event.kind == "quote":
            event = replace(event, bid=D("9.99"), ask=D("10"), bid_size=D("4"), ask_size=D("4"))
        events.append(event)
    source = replace(
        source,
        instrument=replace(source.instrument, fractional_eligible=False, quantity_increment=D("1")),
        dataset=replace(source.dataset, events=tuple(events)),
    )
    result = run_etf_history(source)
    assert result.candidate.account.orders[0].intent.quantity == D("1")
    assert result.candidate.account.shares == D("1")
    assert result.candidate.account.cash == D("489.969")
