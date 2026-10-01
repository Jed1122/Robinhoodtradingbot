"""Observed fixture liquidity cannot create transport or fresh scheduling authority."""

import importlib
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from tests.unit.research.test_etf_execution_charges import cost_evidence
from tests.unit.simulation.test_etf_account import NOW, intent, request, submit
from trading_bot.domain import (
    AssetClass,
    MarketClock,
    OrderEvent,
    OrderState,
    Quote,
    TimestampSource,
)
from trading_bot.market_data.etf_source import (
    EtfControlEvent,
    EtfObservedQuote,
    EtfSessionEvent,
    _ceil_time,
    _ns,
)
from trading_bot.market_data.recording import content_hash

D = Decimal
ORIGIN = _ns(NOW)
DEFAULT_BID = D("99.99")
DEFAULT_ASK = D("100")
DEFAULT_SIZE = D(".1")


def api():
    try:
        return importlib.import_module("trading_bot.simulation.etf_fixture_execution")
    except ModuleNotFoundError:
        pytest.fail("causal ETF fixture execution seam is missing")


def costs(**kwargs):
    result = cost_evidence(extra_slippage=D("0"), **kwargs)
    return replace(
        result,
        intervals=tuple(
            replace(
                i,
                starts_at=NOW - timedelta(days=1),
                ends_at=NOW + timedelta(days=2),
                known_at=NOW - timedelta(days=2),
            )
            for i in result.intervals
        ),
    )


def account(*, accepted=True, canceled=False):
    order = intent(price=D("100.1"))
    pending = replace(submit(order, reserve_fee=D(".1")), kind="pending_intent")
    facts = (pending,)
    if accepted:
        facts += (api_account_event(1, ORIGIN + 1_000_000, OrderEvent.BROKER_ACCEPTED),)
    if canceled:
        facts += (api_account_event(2, ORIGIN + 1_500_000, OrderEvent.REQUEST_CANCEL),)
    return request(facts)


def api_account_event(ordinal, at_ns, event):
    from trading_bot.simulation.etf_account import EtfAccountEvent

    return EtfAccountEvent(
        content_hash((ordinal, at_ns, event)),
        ordinal,
        at_ns,
        "order_status",
        order_id="entry",
        order_event=event,
    )


def clock(ordinal=0, at_ns=ORIGIN + 2_000_000, *, control=False, **flags):
    digest = content_hash(("execution-clock", ordinal, at_ns, control, flags))
    cls = EtfControlEvent if control else EtfSessionEvent
    payload = MarketClock(
        AssetClass.EQUITY,
        "XNYS",
        _ceil_time(at_ns),
        flags.get("is_open", True),
        flags.get("halted", False),
        flags.get("trading_disabled", False),
        flags.get("cancel_only", False),
        NOW + (timedelta(days=1) if flags.get("is_open", True) else timedelta(minutes=30)),
        NOW + timedelta(hours=1),
    )
    return cls(digest, ordinal, at_ns, at_ns, "SPY", None, payload)


def quote(
    ordinal=1,
    at_ns=ORIGIN + 10_000_000,
    *,
    available=None,
    bid=DEFAULT_BID,
    ask=DEFAULT_ASK,
    size=DEFAULT_SIZE,
):
    receipt = at_ns if available is None else available
    digest = content_hash(("execution-quote", ordinal, at_ns, receipt, bid, ask, size))
    payload = Quote(
        "SPY",
        _ceil_time(at_ns),
        bid,
        ask,
        None,
        "synthetic",
        digest,
        False,
        TimestampSource.SIMULATED,
    )
    return EtfObservedQuote(digest, ordinal, at_ns, receipt, "SPY", None, payload, size, size)


def run(observations, *, prefix=None, cost_package=None, through=None):
    inputs = api().EtfFixtureExecutionRequest(
        account() if prefix is None else prefix,
        tuple(observations),
        costs() if cost_package is None else cost_package,
        "entry",
    )
    return api().run_etf_fixture_execution(inputs, through_ordinal=through), inputs


def observed_account_fact(payload, ordinal):
    factory = getattr(api(), "EtfFixtureAccountObservation", None)
    if factory is None:
        pytest.fail("explicit account observation seam is missing")
    return factory(ordinal, payload)


def test_next_eligible_quote_fills_exact_ask_and_keeps_open_episode_and_unsettled_facts():
    result, _ = run((clock(), quote()))
    assert result.account.cash == D("489.969")
    assert result.account.shares == D(".1") and result.account.fees == D(".031")
    assert result.account.reserved_cash == 0 and result.account.trial.reserved_risk == D("10.11")
    assert not result.account.complete and len(result.account.unsettled) == 1
    assert result.source_count == 2 and result.fill_count == 1
    assert result.account.orders[0].order.state is OrderState.FILLED
    assert not result.execution_enabled and not result.evidence_promotable


@pytest.mark.parametrize("offset, fills", [(9_999_999, 0), (10_000_000, 1)])
def test_exact_nanosecond_latency_boundary(offset, fills):
    result, _ = run((clock(), quote(at_ns=ORIGIN + offset)))
    assert result.fill_count == fills
    assert (result.account.shares > 0) == bool(fills)


@pytest.mark.parametrize("accepted,canceled", [(False, False), (True, True)])
def test_pending_or_cancel_pending_quotes_cannot_grant_acceptance_or_race_permission(
    accepted,
    canceled,
):
    result, _ = run((clock(), quote()), prefix=account(accepted=accepted, canceled=canceled))
    assert result.fill_count == 0 and result.account.cash == D("500")
    assert result.account.reserved_cash == result.account.trial.reserved_risk == D("10.11")


@pytest.mark.parametrize("flag", ["halted", "cancel_only", "trading_disabled", "is_open"])
def test_unknown_and_disabled_session_deny_without_releasing_reservations(flag):
    flags = {flag: flag != "is_open"}
    result, _ = run((clock(**flags), quote()))
    assert result.fill_count == 0 and result.account.shares == 0
    assert result.account.reserved_cash == D("10.11")
    absent, _ = run((quote(0),))
    assert absent.fill_count == 0


@pytest.mark.parametrize("bid,ask", [(D("0"), D("100")), (D("101"), D("100"))])
def test_corrupted_zero_bid_and_crossed_quote_payloads_fail_closed(bid, ask):
    observed = quote()
    object.__setattr__(observed.payload, "bid", bid)
    object.__setattr__(observed.payload, "ask", ask)
    with pytest.raises(ValueError):
        run((clock(), observed))


def test_locked_positive_quote_is_explicitly_usable_only_in_unverified_fixture():
    result, inputs = run((clock(), quote(bid=D("100"))))
    assert result.fill_count == 1 and not result.evidence_promotable
    assert inputs.observations[-1].payload.freshness_verified is False


def test_partial_liquidity_uses_one_commission_minimum_and_never_reuses_native_quote_capacity():
    first = quote(size=D(".04"))
    repeated = quote(2, first.event_at_ns, available=first.available_at_ns + 1_000_000, size=D("1"))
    fresh = quote(3, first.event_at_ns + 2_000_000, size=D(".06"))
    partial, _ = run((clock(), first, repeated))
    assert partial.fill_count == 1 and partial.account.shares == D(".04")
    # The common account gate halts further entry execution while settlement is
    # unresolved. An explicit synthetic settlement, not an invented time rule,
    # must re-establish the gate before a second fill is considered.
    from trading_bot.simulation.etf_account import EtfAccountEvent

    settlement = EtfAccountEvent(
        content_hash("partial-settlement"),
        partial.account.last_ordinal + 1,
        ORIGIN + 11_500_000,
        "settlement",
        fill_ids=(partial.decisions[0].fill_id,),
    )
    observed = observed_account_fact(settlement, 3)
    fresh = replace(fresh, ordinal=4)
    complete, _ = run((clock(), first, repeated, observed, fresh))
    assert complete.fill_count == 2 and complete.account.shares == D(".1")
    assert complete.account.fees == D(".031") and complete.account.cash == D("489.969")


def test_sub_increment_capacity_is_not_rounded_up_to_fabricate_shares():
    result, _ = run((clock(), quote(size=D(".0009"))))
    assert result.fill_count == 0 and result.account.shares == 0


def test_delayed_old_quote_after_control_reset_cannot_reestablish_liquidity():
    first = quote(size=D(".04"))
    stopped = clock(2, ORIGIN + 11_000_000, control=True, halted=True)
    restarted = clock(3, ORIGIN + 12_000_000, control=True)
    old = quote(4, first.event_at_ns, available=ORIGIN + 13_000_000)
    result, _ = run((clock(), first, stopped, restarted, old))
    assert result.fill_count == 1 and result.account.shares == D(".04")


def test_spread_slippage_is_charged_once_and_adverse_ticks_respect_the_limit():
    package = costs()
    package = replace(
        package,
        intervals=tuple(
            replace(i, value=D("5")) if i.role == "extra_slippage" else i for i in package.intervals
        ),
    )
    result, _ = run((clock(), quote()), cost_package=package)
    assert result.account.cash == D("489.9639995")
    assert result.account.fees == D(".0310005")
    assert result.account.orders[0].fees_paid == D(".0310005")
    adverse, _ = run((clock(), quote(ask=D("100.1"))), cost_package=package)
    assert adverse.fill_count == 0


def test_expired_and_stale_quotes_never_force_a_fill_at_end_of_input():
    expired, _ = run((clock(), quote(at_ns=ORIGIN + 3_600_000_000_000)))
    assert expired.fill_count == 0 and not expired.account.complete
    old = quote(available=ORIGIN + 60_000_000_000)
    stale, _ = run((clock(), old))
    assert stale.fill_count == 0 and stale.account.reserved_cash == D("10.11")


def test_restart_reconstructs_source_capacity_and_cannot_duplicate_partial_fees():
    observations = (clock(), quote(size=D(".04")), quote(2, ORIGIN + 12_000_000, size=D(".06")))
    uninterrupted, inputs = run(observations)
    for ordinal in (0, 1, 2):
        prefix = api().run_etf_fixture_execution(inputs, through_ordinal=ordinal)
        assert api().resume_etf_fixture_execution(inputs, prefix) == uninterrupted
    changed = replace(
        inputs,
        observations=(
            *observations[:-1],
            quote(2, ORIGIN + 12_000_000, bid=D("98.99"), ask=D("99")),
        ),
    )
    checkpoint = api().run_etf_fixture_execution(inputs, through_ordinal=2)
    with pytest.raises(ValueError):
        api().resume_etf_fixture_execution(changed, checkpoint)


def test_hostile_decimal_context_cannot_change_cash_or_liquidity():
    expected, inputs = run((clock(), quote(size=D(".04"))))
    with localcontext() as context:
        context.prec = 2
        assert api().run_etf_fixture_execution(inputs) == expected


def test_future_only_cost_changes_do_not_rewrite_consumed_fill_or_account_state():
    original = costs()
    future = tuple(
        replace(
            i,
            starts_at=NOW + timedelta(days=2),
            ends_at=NOW + timedelta(days=3),
            known_at=NOW + timedelta(days=1),
        )
        for i in original.intervals
    )
    first = replace(original, intervals=(*original.intervals, *future))
    second = replace(
        original,
        intervals=(
            *original.intervals,
            *tuple(replace(i, value=D("99")) for i in future),
        ),
    )
    before, _ = run((clock(), quote()), cost_package=first)
    after, _ = run((clock(), quote()), cost_package=second)
    assert before.account == after.account and before.account_events == after.account_events
    assert before.cost_hash != after.cost_hash


def test_denied_fee_bound_does_not_append_an_invalid_fill_or_poison_later_observations():
    from trading_bot.simulation.etf_account import replay_etf_account

    expensive = costs(minimum_commission=D(".5"))
    observations = (clock(), quote(), quote(2, ORIGIN + 12_000_000))
    result, inputs = run(observations, cost_package=expensive)
    assert result.fill_count == 0 and result.account.shares == 0
    assert all(event.kind != "fill" for event in result.account_events)
    reconstructed = replay_etf_account(replace(inputs.account, events=result.account_events))
    assert reconstructed == result.account
    assert result.account.cash == D("500") and result.account.reserved_cash == D("10.11")


def test_later_acknowledgement_is_explicit_and_cannot_fill_at_the_same_market_event():
    ack = api_account_event(2, ORIGIN + 11_000_000, OrderEvent.BROKER_ACCEPTED)
    result, inputs = run(
        (clock(), quote(), observed_account_fact(ack, 2), quote(3, ORIGIN + 12_000_000)),
        prefix=account(accepted=False),
    )
    assert result.fill_count == 1
    assert result.decisions[0].fill_id is None
    assert result.account.orders[0].order.updated_at == _ceil_time(ORIGIN + 12_000_000)
    prefix = api().run_etf_fixture_execution(inputs, through_ordinal=2)
    assert prefix.fill_count == 0 and prefix.account.reserved_cash == D("10.11")
    assert api().resume_etf_fixture_execution(inputs, prefix) == result


def test_same_day_next_open_is_not_a_consistent_session_boundary():
    control = clock()
    control = replace(
        control, payload=replace(control.payload, next_open_at=NOW + timedelta(hours=2))
    )
    result, _ = run((control, quote()))
    assert result.fill_count == 0 and result.account.reserved_cash == D("10.11")


def test_pre_submission_market_time_and_wide_spread_are_denied():
    earlier = clock(at_ns=ORIGIN - 1_000_000_000)
    earlier = replace(earlier, available_at_ns=ORIGIN + 2_000_000)
    old = quote(at_ns=ORIGIN - 500_000_000, available=ORIGIN + 10_000_000)
    result, _ = run((earlier, old))
    assert result.decisions[0].reason == "fixture_quote_before_submission"
    wide, _ = run((clock(), quote(bid=D("98"))))
    assert wide.decisions[0].reason == "fixture_spread_too_wide"


def test_order_expiry_is_independent_of_later_session_close():
    control = clock()
    control = replace(
        control, payload=replace(control.payload, next_close_at=NOW + timedelta(hours=2))
    )
    result, _ = run((control, quote(at_ns=ORIGIN + 3_600_000_000_000)))
    assert result.fill_count == 0 and result.decisions[0].reason == "fixture_order_expired"


def test_fee_epoch_changes_before_first_fill_do_not_reprice_the_reserved_order():
    package = costs()
    boundary = NOW + timedelta(microseconds=5000)
    old = tuple(replace(i, ends_at=boundary) for i in package.intervals)
    new = tuple(
        replace(i, starts_at=boundary, known_at=boundary, source_hash="d" * 64)
        for i in package.intervals
    )
    result, _ = run((clock(), quote()), cost_package=replace(package, intervals=(*old, *new)))
    assert result.fill_count == 0 and result.decisions[0].reason == "fixture_fee_schedule_changed"


def test_sell_uses_bid_capacity_and_preserves_unsettled_exit_cash():
    from tests.unit.simulation.test_etf_account import episode_events
    from trading_bot.domain import Side

    facts = episode_events()[:3]
    facts = (replace(facts[0], fee_bound=D(".1")), *facts[1:])
    sell = intent("exit", Side.SELL, price=D("99"), at=NOW + timedelta(seconds=10))
    pending = replace(submit(sell, 3, reserve_fee=D(".1")), kind="pending_intent")
    ack = replace(
        api_account_event(4, ORIGIN + 10_001_000_000, OrderEvent.BROKER_ACCEPTED), order_id="exit"
    )
    inputs = api().EtfFixtureExecutionRequest(
        request((*facts, pending, ack)),
        (clock(at_ns=ORIGIN + 10_002_000_000), quote(at_ns=ORIGIN + 10_010_000_000)),
        costs(),
        "exit",
    )
    result = api().run_etf_fixture_execution(inputs)
    assert result.fill_count == 1 and result.account.shares == 0
    assert result.account.cash == D("499.9580001")
    assert result.account.fees == D(".0409999")
    assert result.account.unsettled and not result.account.complete


@pytest.mark.parametrize("through", [True, -1, 99, "1"])
def test_invalid_source_cursor_is_not_a_resume_or_fill_permission(through):
    _, inputs = run((clock(), quote()))
    with pytest.raises(ValueError, match="etf_fixture_execution_invalid"):
        api().run_etf_fixture_execution(inputs, through_ordinal=through)


def test_corrupted_checkpoint_and_source_identity_cannot_restore_authority():
    checkpoint, inputs = run((clock(), quote()))
    object.__setattr__(checkpoint, "execution_enabled", True)
    with pytest.raises(ValueError, match="etf_fixture_execution_invalid"):
        api().resume_etf_fixture_execution(inputs, checkpoint)
    observed = quote()
    object.__setattr__(observed.payload, "freshness_verified", True)
    with pytest.raises(ValueError):
        run((clock(), observed))


def test_delayed_open_control_cannot_override_a_newer_native_halt():
    stopped = clock(1, ORIGIN + 10_000_000, control=True, halted=True)
    old_open = replace(
        clock(2, ORIGIN + 5_000_000, control=True), available_at_ns=ORIGIN + 15_000_000
    )
    result, _ = run((clock(), stopped, old_open, quote(3, ORIGIN + 20_000_000)))
    assert result.fill_count == 0 and result.account.shares == 0
    assert result.account.reserved_cash == D("10.11")
    assert result.decisions[0].reason == "fixture_control_disabled"


def test_conflicting_equal_native_controls_stay_blocked_until_a_newer_control_and_quote():
    stopped = clock(1, ORIGIN + 5_000_000, control=True, halted=True)
    same_time_open = replace(
        clock(2, stopped.event_at_ns, control=True), available_at_ns=ORIGIN + 6_000_000
    )
    observations = (clock(), stopped, same_time_open, quote(3, ORIGIN + 10_000_000))
    blocked, _ = run(observations)
    assert blocked.fill_count == 0 and blocked.account.shares == 0
    reestablished = (
        *observations,
        clock(4, ORIGIN + 11_000_000, control=True),
        quote(5, ORIGIN + 12_000_000),
    )
    result, _ = run(reestablished)
    assert result.fill_count == 1 and result.decisions[0].fill_id is None


def test_valid_narrow_spread_does_not_require_a_terminating_percentage_quotient():
    result, _ = run((clock(), quote(bid=D("100.02"), ask=D("100.03"))))
    assert result.fill_count == 1 and result.account.shares == D(".1")
    assert result.account.cash == D("489.9659997")
    assert result.account.fees == D(".0310003")


def test_delayed_older_quote_cannot_revive_liquidity_after_newer_unfilled_quote():
    new = quote(1, ORIGIN + 20_000_000, bid=D("124.99"), ask=D("125"))
    old = quote(2, ORIGIN + 10_000_000, available=ORIGIN + 30_000_000)
    result, _ = run((clock(), new, old))
    assert result.fill_count == 0 and result.account.shares == 0
    assert result.account.reserved_cash == D("10.11")


def test_conflicting_equal_native_quote_does_not_select_later_cheaper_price():
    first = quote(1, ORIGIN + 20_000_000, bid=D("124.99"), ask=D("125"))
    conflict = quote(2, first.event_at_ns, available=ORIGIN + 30_000_000)
    blocked, _ = run((clock(), first, conflict))
    assert blocked.fill_count == 0 and blocked.account.shares == 0
    result, _ = run((clock(), first, conflict, quote(3, ORIGIN + 40_000_000)))
    assert result.fill_count == 1 and result.decisions[1].fill_id is None
