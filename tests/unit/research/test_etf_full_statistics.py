"""Independent arithmetic for six-scenario descriptive reports, never acceptance."""

import importlib
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, Inexact, localcontext

import pytest

from tests.unit.research.test_etf_costs import evidence
from tests.unit.simulation.test_etf_account import NOW, episode_events, request
from tests.unit.simulation.test_etf_history import study
from trading_bot.domain import OrderEvent
from trading_bot.market_data.etf_source import _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation.etf_account import EtfAccountEvent, replay_etf_account
from trading_bot.simulation.etf_native_models import (
    SCENARIOS,
    EtfDailyAccount,
    EtfHistoryResult,
    EtfReplayOutcome,
)

D = Decimal
SHA = "a" * 64


def api():
    try:
        return importlib.import_module("trading_bot.research.etf_full_statistics")
    except ModuleNotFoundError:
        pytest.fail("six-scenario descriptive economic evaluator is missing")


def costs(**rates):
    values = {"latency": D(".01"), "cash_rate": D("7.3"), "operating_cost": D(".25")}
    values.update(rates)
    old = evidence()
    return replace(
        old,
        intervals=tuple(replace(row, value=values.get(row.role, D(0))) for row in old.intervals),
    )


def outcome(capital, *, days=(0, 3), events=None):
    events = episode_events() if events is None else events
    account = replay_etf_account(request(events, capital))
    rows = []
    cache = {len(events): account}
    for index in days:
        at = NOW.replace(hour=21) + timedelta(days=index)
        visible = tuple(event for event in events if event.at_ns <= _ns(at))
        if len(visible) not in cache:
            cache[len(visible)] = replay_etf_account(request(visible, capital))
        prefix = cache[len(visible)]
        bid = D("100") + D(index)
        rows.append(
            EtfDailyAccount(
                at.date(),
                _ns(at),
                prefix.cash,
                prefix.settled_cash,
                prefix.shares,
                bid,
                prefix.cash + prefix.shares * bid + prefix.dividend_receivable,
                prefix.reserved_cash,
                prefix.fees,
                prefix.dividend_receivable,
                prefix.state_hash,
                account_event_count=len(visible),
            )
        )
    return EtfReplayOutcome(tuple(events), account, tuple(rows), (), (), ())


def package(*, days=(0, 3), partial=False, cost=None):
    frozen = study()
    charge = costs() if cost is None else cost
    results = []
    for capital in frozen.capital_tiers:
        for scenario in SCENARIOS:
            candidate = outcome(
                capital, days=days, events=episode_events()[:2] if partial else None
            )
            benchmark = outcome(capital, days=days, events=())
            results.append(
                EtfHistoryResult(
                    SHA,
                    frozen.study_hash,
                    SHA,
                    charge.cost_hash,
                    SHA,
                    capital,
                    scenario,
                    1000,
                    SHA,
                    candidate,
                    benchmark,
                    (),
                )
            )
    return frozen, tuple(results), charge


def test_calendar_operating_cost_cash_yield_and_fee_attribution_are_exact():
    report = api().describe_etf_economics(*package())
    row = report.scenarios[0]
    # Jan 2 through Jan 5 inclusive: four calendar days, not two observed sessions.
    assert row.candidate.trading_pnl == D(".10")
    assert row.candidate.operating_cost == D("1")
    assert row.candidate.operating_profit == D("-.90")
    assert row.candidate.fees_paid == D(".02")
    assert row.candidate.dividends_received == D(".02")
    assert row.candidate.completed_opportunities == 1
    assert row.candidate.net_nav == (D("499.85"), D("499.10"))
    assert row.zero_cash_nav == (D("500"), D("500"))
    assert row.sourced_cash_nav == (D("500.1"), D("500.4"))
    assert row.candidate.metrics.total_return_pct.value == D("-.18")
    assert row.candidate.metrics.expectancy.value == D("-.90")
    assert row.candidate.metrics.spread_cost.value is None
    assert row.candidate.metrics.slippage_cost.value is None
    assert "operating_cost_unitemized_unverified" in report.reasons
    assert "cash_act_365_simple_attainability_unverified" in report.reasons
    assert report.execution_enabled is False and report.evidence_promotable is False
    assert report.verdict == "ECONOMIC_NO_GO"
    with pytest.raises(FrozenInstanceError):
        report.verdict = "accepted"


def test_partial_account_keeps_marked_money_but_never_realized_profit():
    row = api().describe_etf_economics(*package(partial=True)).scenarios[0]
    assert row.candidate.trading_pnl is None
    assert row.candidate.operating_profit is None
    assert row.candidate.residual_shares == D(".1")
    assert row.candidate.marked_pnl == D(".29")
    assert row.candidate.completed_opportunities == 0
    assert "account_outcome_incomplete" in row.candidate.reasons
    assert row.candidate.metrics.expectancy.value is None


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "dataset",
        "protocol",
        "study",
        "cost",
        "dates",
        "forged_account",
        "forged_daily",
        "holdout",
    ],
)
def test_misaligned_or_forged_scenarios_are_denied_without_truncation(change):
    frozen, results, charge = package()
    first = results[0]
    if change == "missing":
        results = results[:-1]
    elif change == "duplicate":
        results = (*results[:-1], results[0])
    elif change in ("dataset", "protocol", "study", "cost"):
        first = replace(first, **{f"{change}_hash": "b" * 64})
        results = (first, *results[1:])
    else:
        out = first.candidate
        if change == "forged_account":
            out = replace(out, account=replace(out.account, cash=D("500.11")))
        elif change == "forged_daily":
            out = replace(out, daily=(replace(out.daily[0], nav=D("999")), *out.daily[1:]))
        else:
            at = (
                datetime(2024, 1, 2, 21, tzinfo=UTC)
                if change == "holdout"
                else NOW.replace(hour=21) + timedelta(days=1)
            )
            out = replace(
                out,
                daily=(
                    replace(out.daily[0], session_date=at.date(), at_ns=_ns(at)),
                    *out.daily[1:],
                ),
            )
        results = (replace(first, candidate=out), *results[1:])
    with pytest.raises(ValueError, match=r"^etf_full_statistics_invalid$"):
        api().describe_etf_economics(frozen, results, charge)


def test_observed_date_matching_does_not_hide_missing_benchmark_rows():
    frozen, results, charge = package()
    first = results[0]
    changed = replace(first.constrained_benchmark, daily=first.constrained_benchmark.daily[1:])
    with pytest.raises(ValueError, match=r"^etf_full_statistics_invalid$"):
        api().describe_etf_economics(
            frozen, (replace(first, constrained_benchmark=changed), *results[1:]), charge
        )


def test_folds_and_dependent_statistics_are_not_opportunity_counts():
    frozen, results, charge = package(days=tuple(range(251)))
    row = api().describe_etf_economics(frozen, results, charge).scenarios[0]
    assert len(row.folds) == 5
    assert tuple(f.test_observations for f in row.folds) == (51, 50, 50, 50, 50)
    assert row.folds[0].total_return_pct < 0
    assert row.paired_zero is not None and row.paired_cash is not None
    assert (
        row.paired_zero.constrained_lower_bound > 0
    )  # One small entry gain, same operating costs.
    assert row.paired_zero.cash_lower_bound < 0
    assert row.candidate.completed_opportunities == 1
    assert tuple(r.interval.samples for r in row.net_expectancy_risks) == (1000, 1000)
    assert tuple(r.interval.observations for r in row.net_expectancy_risks) == (251, 251)
    assert "independent_opportunities_insufficient" in row.reasons


def test_low_precision_context_and_input_order_do_not_change_reports():
    frozen, results, charge = package()
    baseline = api().describe_etf_economics(frozen, results, charge)
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        repeat = api().describe_etf_economics(frozen, tuple(reversed(results)), charge)
    assert repeat == baseline


def test_full_invested_reference_requires_observed_ask_not_invented_spread():
    row = api().describe_etf_economics(*package()).scenarios[0]
    assert row.full_invested.nav is None
    assert "entry_ask_unavailable" in row.full_invested.reasons


def test_negative_after_operating_nav_preserves_money_and_denies_return_statistics():
    row = api().describe_etf_economics(*package(cost=costs(operating_cost=D("1000")))).scenarios[0]
    assert row.candidate.operating_profit == D("-3999.90")
    assert row.candidate.net_nav == (D("-499.90"), D("-3499.90"))
    assert row.candidate.period_returns is None and row.paired_cash is None
    assert row.candidate.metrics is None
    assert "nonpositive_nav_returns_unavailable" in row.candidate.reasons


def test_duplicate_fill_delivery_cannot_double_dividend_entitlement():
    frozen, results, charge = package()
    events = episode_events()
    duplicate = replace(events[1], event_id=content_hash("redelivery"), ordinal=2)
    delivered = (
        *events[:2],
        duplicate,
        *(replace(event, ordinal=event.ordinal + 1) for event in events[2:]),
    )
    changed = tuple(
        replace(result, candidate=outcome(result.initial_cash, events=delivered))
        for result in results
    )
    row = api().describe_etf_economics(frozen, changed, charge).scenarios[0]
    assert row.candidate.dividends_received == D(".02")
    assert row.candidate.fees_paid == D(".02")
    assert row.candidate.trading_pnl == D(".10")


def test_full_invested_ask_fee_and_bid_mark_are_not_an_executed_sale():
    frozen, results, charge = package(cost=costs(minimum_commission=D(".5")))
    updated = []
    for result in results:
        candidate = replace(
            result.candidate,
            daily=tuple(
                replace(
                    row,
                    bid=D("99") if index == 0 else D("103"),
                    ask=D("100") if index == 0 else D("104"),
                )
                for index, row in enumerate(result.candidate.daily)
            ),
        )
        updated.append(replace(result, candidate=candidate))
    row = api().describe_etf_economics(frozen, tuple(updated), charge).scenarios[0]
    reference = row.full_invested
    assert reference.entry_price == D("100")
    assert reference.shares == D("4.995")
    assert reference.fees_paid == D(".5")
    assert reference.residual_cash == 0
    assert reference.nav == (D("494.505"), D("514.485"))
    assert reference.net_nav == (D("494.255"), D("513.485"))
    assert reference.realized_trading_pnl is None and reference.risk_admission_verified is False


def test_missing_bid_on_open_position_preserves_real_cash_and_disables_returns():
    frozen, results, charge = package(partial=True)
    changed = tuple(
        replace(
            result,
            candidate=replace(
                result.candidate,
                daily=tuple(replace(row, bid=None, nav=None) for row in result.candidate.daily),
            ),
        )
        for result in results
    )
    row = api().describe_etf_economics(frozen, changed, charge).scenarios[0]
    assert row.candidate.cash_change == D("-10.01")
    assert row.candidate.period_returns is None and row.candidate.metrics is None
    assert row.candidate.marked_pnl is None
    assert "unavailable_nav_returns_unavailable" in row.candidate.reasons


def test_full_invested_reference_receives_dividend_once_even_when_candidate_is_flat():
    frozen, results, charge = package()
    ex, pay = episode_events()[3:5]
    events = (
        replace(ex, ordinal=0, at_ns=_ns(NOW + timedelta(days=1))),
        replace(pay, ordinal=1, at_ns=_ns(NOW + timedelta(days=2))),
        replace(
            pay,
            event_id=content_hash("repeat-pay"),
            ordinal=2,
            at_ns=_ns(NOW + timedelta(days=2, seconds=1)),
        ),
    )
    updated = []
    for result in results:
        candidate = outcome(result.initial_cash, days=(0, 1, 3), events=events)
        candidate = replace(
            candidate, daily=tuple(replace(row, ask=row.bid) for row in candidate.daily)
        )
        benchmark = outcome(result.initial_cash, days=(0, 1, 3), events=())
        updated.append(replace(result, candidate=candidate, constrained_benchmark=benchmark))
    row = api().describe_etf_economics(frozen, tuple(updated), charge).scenarios[0]
    assert row.candidate.dividends_received == 0
    assert row.full_invested.shares == D("5")
    assert row.full_invested.nav == (D("500"), D("506"), D("516"))
    assert row.full_invested.dividends_received == D("1")
    assert row.full_invested.dividend_receivable == 0
    assert row.full_invested.residual_cash == D("1")


def test_equal_episode_operating_allocation_reconciles_the_rounding_residual_exactly():
    frozen, results, charge = package()
    events = []
    for day in range(3):
        shift = timedelta(days=day)
        for event in episode_events(sell_price=D("100")):
            intent = event.intent
            fill = event.fill
            events.append(
                replace(
                    event,
                    event_id=content_hash(("day", day, event.event_id)),
                    ordinal=day * 8 + event.ordinal,
                    at_ns=event.at_ns + day * 86400000000000,
                    intent=None
                    if intent is None
                    else replace(
                        intent,
                        id=f"{intent.id}-{day}",
                        created_at=intent.created_at + shift,
                        expires_at=intent.expires_at + shift,
                    ),
                    fill=None
                    if fill is None
                    else replace(
                        fill,
                        id=f"{fill.id}-{day}",
                        broker_order_id=f"{fill.broker_order_id}-{day}",
                        occurred_at=fill.occurred_at + shift,
                    ),
                    fill_ids=tuple(f"{ident}-{day}" for ident in event.fill_ids),
                    action_id=None
                    if event.action_id is None
                    else content_hash(("day", day, event.action_id)),
                )
            )
    changed = tuple(
        replace(result, candidate=outcome(result.initial_cash, events=tuple(events)))
        for result in results
    )
    ledger = api().describe_etf_economics(frozen, changed, charge).scenarios[0].candidate
    assert ledger.completed_opportunities == 3
    with localcontext() as context:
        context.prec = 80
        assert sum(ledger.net_episode_pnl, D(0)) == D("-1")


def test_calendar_cost_arithmetic_retains_small_bounded_coefficient_tail():
    operating = D("10000000000000000000000000000.01")
    ledger = (
        api()
        .describe_etf_economics(*package(cost=costs(operating_cost=operating)))
        .scenarios[0]
        .candidate
    )
    assert ledger.operating_cost == D("40000000000000000000000000000.04")
    assert ledger.operating_profit == D("-39999999999999999999999999999.94")


def test_candidate_net_statistics_remain_available_when_benchmark_mark_is_missing():
    frozen, results, charge = package(days=tuple(range(100)))
    changed = []
    for result in results:
        benchmark = outcome(
            result.initial_cash, days=tuple(range(100)), events=episode_events()[:2]
        )
        benchmark = replace(
            benchmark, daily=tuple(replace(row, bid=None, nav=None) for row in benchmark.daily)
        )
        changed.append(replace(result, constrained_benchmark=benchmark))
    row = api().describe_etf_economics(frozen, tuple(changed), charge).scenarios[0]
    assert row.candidate.period_returns is not None
    assert row.paired_cash is None
    assert len(row.net_expectancy_risks) == 2
    assert row.net_expectancy_risks[1].interval.lower == D("-.249")


@pytest.mark.parametrize(
    "field,value",
    [
        ("cash", 500),
        ("nav", D("NaN")),
        ("bid", D("0")),
        ("ask", D("99")),
        ("at_ns", True),
        ("state_hash", "private/path"),
    ],
)
def test_invalid_daily_domains_are_sanitized(field, value):
    frozen, results, charge = package()
    first = results[0]
    candidate = replace(
        first.candidate,
        daily=(replace(first.candidate.daily[0], **{field: value}), *first.candidate.daily[1:]),
    )
    with pytest.raises(ValueError, match=r"^etf_full_statistics_invalid$"):
        api().describe_etf_economics(
            frozen, (replace(first, candidate=candidate), *results[1:]), charge
        )


def test_effective_date_cash_and_operating_rates_change_on_calendar_day_boundary():
    base = costs()
    boundary = datetime(2019, 1, 4, tzinfo=UTC)
    intervals = []
    for interval in base.intervals:
        if interval.role in ("cash_rate", "operating_cost"):
            intervals.append(replace(interval, ends_at=boundary))
            intervals.append(replace(interval, starts_at=boundary, value=interval.value * 2))
        else:
            intervals.append(interval)
    row = (
        api()
        .describe_etf_economics(*package(cost=replace(base, intervals=tuple(intervals))))
        .scenarios[0]
    )
    assert row.candidate.operating_cost == D("1.50")
    assert row.sourced_cash_nav == (D("500.1"), D("500.6"))


def test_full_invested_reference_does_not_invent_fee_affordability():
    frozen, results, charge = package(cost=costs(minimum_commission=D("1000")))
    changed = tuple(
        replace(
            result,
            candidate=replace(
                result.candidate,
                daily=tuple(replace(row, ask=row.bid) for row in result.candidate.daily),
            ),
        )
        for result in results
    )
    row = api().describe_etf_economics(frozen, changed, charge).scenarios[0]
    assert row.full_invested.nav is None
    assert row.full_invested.shares == 0
    assert "entry_fees_unaffordable" in row.full_invested.reasons


def test_bounded_inputs_cannot_emit_unbounded_accumulated_money():
    values = package(days=(0, 1824), cost=costs(operating_cost=D("9e511")))
    with pytest.raises(ValueError, match=r"^etf_full_statistics_invalid$"):
        api().describe_etf_economics(*values)


def test_equal_timestamp_snapshot_excludes_later_account_fact():
    frozen, results, charge = package()
    changed = []
    for result in results:
        flat = replay_etf_account(request((), result.initial_cash))
        before = replace(
            result.candidate.daily[0],
            at_ns=_ns(NOW),
            cash=flat.cash,
            settled_cash=flat.settled_cash,
            shares=D(0),
            nav=flat.cash,
            reserved_cash=D(0),
            fees=D(0),
            dividend_receivable=D(0),
            state_hash=flat.state_hash,
            account_event_count=0,
        )
        changed.append(
            replace(
                result,
                candidate=replace(result.candidate, daily=(before, *result.candidate.daily[1:])),
            )
        )
    row = api().describe_etf_economics(frozen, tuple(changed), charge).scenarios[0]
    assert row.candidate.net_nav == (D("499.75"), D("499.10"))
    assert row.candidate.trading_pnl == D(".10")


@pytest.mark.parametrize("count", [-1, True, 9, 4])
def test_daily_snapshot_prefix_count_cannot_skip_prior_events_or_overrun(count):
    frozen, results, charge = package()
    first = results[0]
    out = replace(
        first.candidate,
        daily=(
            replace(first.candidate.daily[0], account_event_count=count),
            *first.candidate.daily[1:],
        ),
    )
    with pytest.raises(ValueError, match=r"^etf_full_statistics_invalid$"):
        api().describe_etf_economics(frozen, (replace(first, candidate=out), *results[1:]), charge)


def test_terminal_settlement_after_last_mark_keeps_cash_but_disables_comparisons():
    frozen, results, charge = package()
    events = episode_events()
    events = (
        *events[:-1],
        replace(events[-1], at_ns=_ns(NOW.replace(hour=21) + timedelta(days=3, seconds=1))),
    )
    changed = tuple(
        replace(result, candidate=outcome(result.initial_cash, events=events)) for result in results
    )
    row = api().describe_etf_economics(frozen, changed, charge).scenarios[0]
    assert row.candidate.cash_change == D(".10") and row.candidate.fees_paid == D(".02")
    assert row.candidate.marked_pnl is None and row.candidate.net_nav[-1] is None
    assert row.candidate.metrics is None and row.candidate.period_returns is None
    assert row.candidate.operating_profit is None
    assert "terminal_facts_after_last_mark" in row.reasons


def test_unfilled_rejected_episode_is_not_an_independent_completed_trade():
    frozen, results, charge = package()
    submit = replace(episode_events()[0], kind="pending_intent")
    rejected = EtfAccountEvent(
        content_hash("rejected"),
        1,
        _ns(NOW + timedelta(seconds=1)),
        "order_status",
        order_id="entry",
        order_event=OrderEvent.BROKER_REJECTED,
    )
    changed = tuple(
        replace(result, candidate=outcome(result.initial_cash, events=(submit, rejected)))
        for result in results
    )
    row = api().describe_etf_economics(frozen, changed, charge).scenarios[0]
    assert row.candidate.completed_opportunities == 0
    assert row.candidate.completed_episode_pnl == ()
    assert row.candidate.net_episode_pnl == ()
    assert row.candidate.metrics.expectancy.value is None


def test_empty_post_warmup_window_is_a_complete_six_scenario_diagnostic():
    frozen, results, charge = package(days=())
    report = api().describe_etf_economics(frozen, results, charge)
    assert report.session_dates == () and len(report.scenarios) == 6
    row = report.scenarios[0]
    assert row.candidate.cash_change == D(".10")
    assert row.candidate.operating_cost == 0
    assert row.candidate.operating_profit is None
    assert row.candidate.metrics is None and row.candidate.period_returns is None
    assert row.zero_cash_nav == row.sourced_cash_nav == ()
    assert row.full_invested.nav is None
    assert {"warmup_incomplete", "observation_window_empty"} <= set(row.reasons)


def test_reference_distribution_order_uses_snapshot_prefix_not_timestamp_alone():
    frozen, results, charge = package()
    ex, pay = episode_events()[3:5]
    events = (
        replace(ex, ordinal=0, at_ns=_ns(NOW.replace(hour=21))),
        replace(pay, ordinal=1, at_ns=_ns(NOW + timedelta(days=2))),
    )
    changed = []
    for result in results:
        candidate = outcome(result.initial_cash, events=events)
        flat = replay_etf_account(request((), result.initial_cash))
        first = replace(
            candidate.daily[0], state_hash=flat.state_hash, account_event_count=0, ask=D("100")
        )
        candidate = replace(candidate, daily=(first, *candidate.daily[1:]))
        changed.append(replace(result, candidate=candidate))
    ref = api().describe_etf_economics(frozen, tuple(changed), charge).scenarios[0].full_invested
    assert ref.nav == (D("500"), D("516"))
    assert ref.dividends_received == D("1")
