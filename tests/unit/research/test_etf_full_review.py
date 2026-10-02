"""Independent review regressions for episode labels and unavailable economics."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from tests.unit.research.test_etf_full_statistics import outcome, package
from tests.unit.simulation.test_etf_account import NOW, episode_events
from tests.unit.simulation.test_etf_history import bar
from trading_bot.market_data.etf_source import _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_full_economics import _episodes, evaluate_etf_economics
from trading_bot.research.etf_full_statistics import describe_etf_economics

D = Decimal


def test_paid_dividend_before_sale_cannot_shorten_completed_episode_settlement():
    _, results, _ = package()
    # Entry fill at +1s, dividend paid at +4s, closing fill at +6s,
    # and final sale settlement at +7s. Payment is not the terminal obligation.
    assert _episodes(results[0]) == (
        (_ns(NOW + timedelta(seconds=1)), _ns(NOW + timedelta(seconds=7))),
    )


def test_ex_date_after_liquidation_creates_no_entitlement_or_label_extension():
    _, results, _ = package()
    facts = episode_events()
    later_action = content_hash("distribution-after-liquidation")
    ex = replace(
        facts[3],
        event_id=content_hash("post-sale-ex"),
        ordinal=7,
        at_ns=_ns(NOW + timedelta(seconds=6, microseconds=500000)),
        action_id=later_action,
    )
    pay = replace(
        facts[4],
        event_id=content_hash("post-sale-pay"),
        ordinal=9,
        at_ns=_ns(NOW + timedelta(seconds=8)),
        action_id=later_action,
    )
    events = (*facts[:-1], ex, replace(facts[-1], ordinal=8), pay)
    source = results[0]
    candidate = outcome(source.initial_cash, events=events)
    source = replace(source, candidate=candidate)
    assert candidate.account.complete and candidate.account.cash == D("500.10")
    assert _episodes(source) == (
        (_ns(NOW + timedelta(seconds=1)), _ns(NOW + timedelta(seconds=7))),
    )


def test_repeated_later_dividend_payment_does_not_extend_cleared_obligation():
    _, results, _ = package()
    facts = episode_events()
    repeated_payment = replace(
        facts[4],
        event_id=content_hash("later-idempotent-payment"),
        ordinal=8,
        at_ns=_ns(NOW + timedelta(seconds=12)),
    )
    source = results[0]
    candidate = outcome(source.initial_cash, events=(*facts, repeated_payment))
    source = replace(source, candidate=candidate)
    assert candidate.account.complete and candidate.account.cash == D("500.10")
    assert _episodes(source) == (
        (_ns(NOW + timedelta(seconds=1)), _ns(NOW + timedelta(seconds=7))),
    )


def test_later_idempotent_settlement_does_not_extend_episode_or_change_account():
    _, results, _ = package()
    facts = episode_events()
    repeated_settlement = replace(
        facts[-1],
        event_id=content_hash("later-idempotent-settlement"),
        ordinal=8,
        at_ns=_ns(NOW + timedelta(seconds=12)),
    )
    source = results[0]
    original = source.candidate.account
    candidate = outcome(source.initial_cash, events=(*facts, repeated_settlement))
    actual = candidate.account
    # Receipt metadata changes, but every reconciled financial obligation is identical.
    assert actual.complete
    assert (actual.cash, actual.settled_cash, actual.fees, actual.reserved_cash) == (
        original.cash,
        original.settled_cash,
        original.fees,
        original.reserved_cash,
    )
    assert actual.position == original.position
    assert actual.orders == original.orders
    assert actual.trial == original.trial
    assert actual.unsettled == original.unsettled
    assert actual.receivables == original.receivables
    # Exactly one opportunity still ends at its first final settlement, +7 seconds.
    assert _episodes(replace(source, candidate=candidate)) == (
        (_ns(NOW + timedelta(seconds=1)), _ns(NOW + timedelta(seconds=7))),
    )


def test_first_session_intraday_episode_counts_once_in_first_purged_fold():
    frozen, results, costs = package(days=tuple(range(250)))
    warmup = tuple(bar(index, D("100")).payload for index in range(750))
    results = tuple(replace(result, bars=warmup) for result in results)
    report = evaluate_etf_economics(frozen, results, costs)
    assert len(report.folds) == 30
    for source in results:
        folds = tuple(
            fold
            for fold in report.folds
            if (fold.initial_cash, fold.fill_scenario)
            == (source.initial_cash, source.fill_scenario)
        )
        assert tuple(fold.test_observations for fold in folds) == (50, 50, 50, 50, 50)
        assert tuple(fold.completed_opportunities for fold in folds) == (1, 0, 0, 0, 0)


def test_reconciliation_incomplete_does_not_publish_mechanically_complete_economics():
    frozen, results, costs = package()
    results = tuple(
        replace(
            source,
            candidate=replace(
                source.candidate,
                reasons=("input_reconciliation_incomplete",),
            ),
        )
        for source in results
    )
    assert all(source.candidate.account.complete for source in results)
    report = describe_etf_economics(frozen, results, costs)
    for scenario in report.scenarios:
        candidate = scenario.candidate
        assert candidate.cash_change == D(".10") and candidate.fees_paid == D(".02")
        assert candidate.trading_pnl is None
        assert candidate.operating_profit is None
        assert candidate.marked_pnl is None
        assert candidate.period_returns is None and candidate.metrics is None
        assert candidate.completed_opportunities is None
        assert candidate.net_episode_pnl == ()
        assert scenario.paired_zero is None and scenario.paired_cash is None
        assert scenario.net_expectancy_risks == ()
        assert "input_reconciliation_incomplete" in scenario.reasons
