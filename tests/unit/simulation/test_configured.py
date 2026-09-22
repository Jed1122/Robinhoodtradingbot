from dataclasses import replace
from decimal import Decimal as D

import pytest

from trading_bot.domain import AssetClass, OrderState, Side, TimeInForce
from trading_bot.simulation.configured import simulate_configured_order
from trading_bot.simulation.lifecycle import replay_order_lifecycle

from ._configured_fixtures import at, cancel, cost_settings, market, request, settings, window
from ._lifecycle_fixtures import make_request


def reasons(result):
    return [decision.reason.value for decision in result.decisions]


def test_full_fill_updates_real_lifecycle_accounting():
    req = request(events=(market(),))
    result = simulate_configured_order(req)
    assert result.lifecycle.snapshot.order.state is OrderState.FILLED
    assert result.lifecycle.snapshot.position.quantity == D(1)
    assert result.lifecycle.snapshot.cash == D("900.2562625")
    assert result.lifecycle.snapshot.fees == D("0.4962375")
    assert result.lifecycle == replay_order_lifecycle(replace(req.initial, events=result.events))
    assert result.source_kind == "synthetic-configured-order-v1"
    assert result.evidence_promotable is False
    assert result.assumptions_validated is False


def test_submission_rejection_prevents_all_later_fills():
    config = settings(rejection_probability_pct=D(100), full_fill_probability_pct=D(0))
    result = simulate_configured_order(request(events=(market(),), simulation=config))
    assert result.lifecycle.snapshot.order.state is OrderState.REJECTED
    assert result.lifecycle.snapshot.cash == D(1000)
    assert reasons(result) == ["submission_rejected", "order_terminal"]


def test_latency_boundary_even_when_next_bar_is_already_open():
    events = (
        market("early", 1, 499, window=window(400, 1000)),
        market("ready", 2, 500, window=window(400, 1000)),
    )
    result = simulate_configured_order(request(events=events, submission_window=window(0, 400)))
    assert reasons(result) == ["submission_pending", "submission_accepted", "full_fill"]
    assert result.events[-1].cursor.occurred_at == at(500)


def test_later_sequence_in_submission_bar_cannot_fill():
    events = (market("same", 1, 700), market("next", 2, 1000))
    result = simulate_configured_order(request(events=events))
    assert reasons(result) == ["submission_accepted", "same_bar_forbidden", "full_fill"]


@pytest.mark.parametrize(
    "field,value,want",
    [
        ("is_open", False, "market_closed"),
        ("halted", True, "market_halted"),
        ("trading_disabled", True, "trading_disabled"),
        ("cancel_only", True, "cancel_only"),
    ],
)
def test_each_session_restriction_blocks_fills(field, value, want):
    event = market()
    event = replace(event, clock=replace(event.clock, **{field: value}))
    result = simulate_configured_order(request(events=(event,)))
    assert reasons(result)[-1] == want
    assert result.lifecycle.snapshot.order.filled_quantity == D(0)


def test_unverified_quote_and_zero_liquidity_do_not_fill():
    event = market()
    for changed, want in (
        (replace(event, quote=replace(event.quote, freshness_verified=False)), "quote_unverified"),
        (replace(event, available_quantity=D(0)), "no_liquidity"),
    ):
        result = simulate_configured_order(request(events=(changed,)))
        assert reasons(result)[-1] == want
        assert result.lifecycle.snapshot.fees == D(0)


@pytest.mark.parametrize("side,bid,ask", [(Side.BUY, "99", "100"), (Side.SELL, "100", "101")])
def test_cost_adjusted_price_must_respect_limit(side, bid, ask):
    initial = make_request(side=side, position_quantity="1", average_price="99")
    event = market()
    event = replace(event, quote=replace(event.quote, bid=D(bid), ask=D(ask)))
    result = simulate_configured_order(request(events=(event,), initial=initial))
    assert reasons(result)[-1] == "limit_price_not_executable"
    assert result.lifecycle.snapshot.fees == D(0)


def test_liquidity_limited_full_outcome_records_actual_partial_then_full():
    events = (market("small", 1, 1000, available_quantity=D("0.3")), market("rest", 2, 2000))
    result = simulate_configured_order(request(events=events))
    assert reasons(result) == ["submission_accepted", "partial_fill", "full_fill"]
    assert result.decisions[1].selected_outcome.value == "full"
    assert result.decisions[1].realized_outcome.value == "partial"
    assert result.events[-1].fill.quantity == D("0.7")


def test_partial_percent_applies_to_remaining_and_does_not_force_completion():
    config = settings(
        full_fill_probability_pct=D(0),
        partial_fill_probability_pct=D(100),
        partial_fill_min_pct=D(50),
        partial_fill_max_pct=D(50),
    )
    result = simulate_configured_order(
        request(simulation=config, events=(market(), market("two", 2, 2000)))
    )
    assert result.lifecycle.snapshot.order.filled_quantity == D("0.75")
    assert result.lifecycle.order_terminal is False
    assert result.decisions[-1].partial_percentage == D(50)


def test_cancel_acknowledgement_wins_at_equal_timestamp():
    events = (cancel(), market("quote", 2, 1500))
    result = simulate_configured_order(request(events=events))
    assert result.lifecycle.snapshot.order.state is OrderState.CANCELED
    assert result.lifecycle.snapshot.order.filled_quantity == D(0)
    assert reasons(result) == [
        "submission_accepted",
        "cancel_requested",
        "cancel_confirmed",
        "order_terminal",
    ]


@pytest.mark.parametrize("prob,want", [(0, OrderState.CANCELED), (100, OrderState.FILLED)])
def test_pending_cancel_race_allowance(prob, want):
    events = (cancel(), market("race", 2, 1200))
    result = simulate_configured_order(
        request(events=events, simulation=settings(cancel_race_probability_pct=D(prob)))
    )
    assert result.lifecycle.snapshot.order.state is want
    if prob == 0:
        assert "cancel_race_suppressed" in reasons(result)
    else:
        assert reasons(result)[-1] == "already_terminal"


def test_race_partial_consumes_allowance_before_cancel_ack():
    config = settings(cancel_race_probability_pct=D(100))
    events = (
        cancel(),
        market("partial", 2, 1100, available_quantity=D("0.25")),
        market("suppressed", 3, 1200),
    )
    result = simulate_configured_order(request(events=events, simulation=config))
    assert result.lifecycle.snapshot.order.state is OrderState.CANCELED
    assert result.lifecycle.snapshot.order.filled_quantity == D("0.25")
    assert reasons(result)[-2:] == ["cancel_race_suppressed", "cancel_confirmed"]


def test_nofill_consumes_the_single_race_opportunity():
    config = settings(
        cancel_race_probability_pct=D(100),
        full_fill_probability_pct=D(0),
        no_fill_probability_pct=D(100),
    )
    events = (cancel(), market("none", 2, 1100), market("suppressed", 3, 1200))
    result = simulate_configured_order(request(events=events, simulation=config))
    assert reasons(result)[2:4] == ["no_fill", "cancel_race_suppressed"]


def test_failed_guards_do_not_consume_race_allowance():
    config = settings(cancel_race_probability_pct=D(100))
    events = (
        cancel(),
        market("dry", 2, 1100, available_quantity=D(0)),
        market("available", 3, 1200),
    )
    result = simulate_configured_order(request(events=events, simulation=config))
    assert result.lifecycle.snapshot.order.state is OrderState.FILLED


def test_zero_latency_has_no_cancel_race_window():
    events = (cancel(), market("same_time", 2, 1000))
    config = settings(latency_milliseconds=0, cancel_race_probability_pct=D(100))
    result = simulate_configured_order(request(events=events, simulation=config))
    assert result.lifecycle.snapshot.order.state is OrderState.CANCELED
    assert result.lifecycle.snapshot.fees == D(0)


def test_expiration_wins_over_fill_and_cancel_ack():
    initial = make_request()
    initial = replace(initial, order=replace(initial.order, time_in_force=TimeInForce.GOOD_FOR_DAY))
    result = simulate_configured_order(
        request(initial=initial, expires_at=at(1500), events=(cancel(), market("equal", 2, 1500)))
    )
    assert result.lifecycle.snapshot.order.state is OrderState.EXPIRED
    assert reasons(result)[-3:] == ["expired", "already_terminal", "order_terminal"]


def test_horizon_before_ack_returns_pending_without_fabricating_completion():
    result = simulate_configured_order(request(end_at=at(499)))
    assert result.lifecycle.snapshot.order.state is OrderState.SUBMISSION_PENDING
    assert result.events == () and result.decisions == ()
    assert not result.lifecycle.order_terminal


def test_terminal_cancel_is_audited_without_scheduling_an_ack():
    result = simulate_configured_order(request(events=(market(), cancel("late", 2, 2000))))
    assert reasons(result) == ["submission_accepted", "full_fill", "already_terminal"]


def test_sell_fill_decreases_inventory_and_credits_cash_net_of_fees():
    initial = make_request(side=Side.SELL, position_quantity="1", average_price="99")
    event = market()
    event = replace(event, quote=replace(event.quote, bid=D(101), ask=D(102)))
    result = simulate_configured_order(request(initial=initial, events=(event,)))
    assert result.lifecycle.snapshot.position.quantity == D(0)
    assert result.lifecycle.snapshot.position.average_price is None
    assert result.lifecycle.snapshot.cash == D("1100.2437625")
    assert result.lifecycle.snapshot.fees == D("0.5037375")


def test_equity_commission_is_charged_per_fill_without_crypto_fee():
    initial = make_request()
    initial = replace(initial, position=replace(initial.position, asset_class=AssetClass.EQUITY))
    events = (market("partial", 1, 1000, available_quantity=D("0.3")), market("rest", 2, 2000))
    events = tuple(
        replace(event, clock=replace(event.clock, asset_class=AssetClass.EQUITY))
        for event in events
    )
    result = simulate_configured_order(
        request(initial=initial, events=events, costs=cost_settings(equity_commission_usd=D(2)))
    )
    assert result.lifecycle.snapshot.fees == D(4)
    assert result.lifecycle.snapshot.cash == D("896.7525")


def test_nominal_hundred_percent_partial_can_realize_full():
    config = settings(
        full_fill_probability_pct=D(0),
        partial_fill_probability_pct=D(100),
        partial_fill_min_pct=D(100),
        partial_fill_max_pct=D(100),
    )
    result = simulate_configured_order(request(events=(market(),), simulation=config))
    assert result.lifecycle.order_terminal
    assert result.decisions[-1].selected_outcome.value == "partial"
    assert result.decisions[-1].realized_outcome.value == "full"


def test_horizon_before_cancel_ack_remains_cancel_pending():
    result = simulate_configured_order(request(events=(cancel(),), end_at=at(1200)))
    assert result.lifecycle.snapshot.order.state is OrderState.CANCEL_PENDING
    assert not result.lifecycle.order_terminal


def test_expiration_after_full_fill_is_audit_only():
    initial = make_request()
    initial = replace(initial, order=replace(initial.order, time_in_force=TimeInForce.GOOD_FOR_DAY))
    result = simulate_configured_order(
        request(initial=initial, expires_at=at(2000), events=(market(),))
    )
    assert result.lifecycle.snapshot.order.state is OrderState.FILLED
    assert reasons(result)[-1] == "already_terminal"


def test_equal_limit_price_is_executable():
    event = market()
    event = replace(event, quote=replace(event.quote, ask=D(100)))
    result = simulate_configured_order(
        request(events=(event,), costs=cost_settings(assumed_slippage_pct=D(0)))
    )
    assert result.lifecycle.snapshot.order.state is OrderState.FILLED


def test_accepted_order_is_never_rejected_by_later_opportunities():
    config = settings(
        rejection_probability_pct=D(50),
        no_fill_probability_pct=D(50),
        full_fill_probability_pct=D(0),
    )
    events = tuple(market(str(index), index, index * 1000) for index in range(1, 6))
    accepted = 0
    for seed in range(20):
        result = simulate_configured_order(request(events=events, simulation=config, seed=seed))
        if reasons(result)[0] == "submission_accepted":
            accepted += 1
            assert result.lifecycle.snapshot.order.state is OrderState.SUBMITTED
            assert reasons(result)[1:] == ["no_fill"] * 5
    assert accepted > 0
