"""Fabricated original-account consumer transactions; no performance inference."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from tests.unit.research.test_etf_capital_prepared import long_source
from tests.unit.simulation.test_etf_capital_due_facts import (
    applied,
    distribution_actions,
    due,
    retime,
    tape,
)
from tests.unit.simulation.test_etf_capital_owned_entry import facts
from tests.unit.simulation.test_etf_capital_owned_entry import value as entry
from tests.unit.simulation.test_etf_capital_owned_exit import facts_tuple
from tests.unit.simulation.test_etf_capital_owned_exit import value as exit_value
from trading_bot.market_data.etf_capital_dataset import capital_dataset_features
from trading_bot.simulation import etf_capital_account as account
from trading_bot.simulation import etf_capital_daily_entry as entries
from trading_bot.simulation import etf_capital_daily_exit as exits
from trading_bot.simulation import etf_capital_due_facts as scheduler
from trading_bot.simulation import etf_capital_risk as risk
from trading_bot.simulation.events import EventCursor

from .test_etf_capital_account import script


@pytest.fixture(scope="module")
def source():
    return long_source(8)


def scheduled(source, events, index, progress, **changes):
    day = source.calendar.sessions[index].session_date
    values = dict(
        initial_cash=D(100),
        events=events,
        observations=(),
        calendar=source.calendar,
        actions=source.actions,
        session=day,
        raw_bars=tuple(p.raw_bars[-1] for p in capital_dataset_features(source, as_of_session=day)),
        _progress=progress,
    )
    values.update(changes)
    return scheduler._capital_due_facts(**values)


def test_owned_due_t_plus_two_keeps_literal_cash_and_avoids_old_lifecycle(source, monkeypatch):
    events = tape(source)
    progress = scheduler._CapitalDueProgress()
    actual = scheduled(source, events, 2, progress)
    assert actual == due(source, events, 2) == ()
    calls = []
    real = account.replay_order_lifecycle

    def replay(request):
        calls.append(request.order.id)
        return real(request)

    monkeypatch.setattr(account, "replay_order_lifecycle", replay)
    facts = scheduled(source, events, 3, progress)
    assert calls == []  # settlement/finality do not reprocess old order transitions
    assert facts == due(source, events, 3)
    final = account.replay_capital_action_account(
        initial_cash=D(100), events=applied(events, facts)
    )
    assert (final.cash, final.fees, final.complete) == (D("100.11"), D(".09"), True)
    assert scheduled(source, applied(events, facts), 4, progress) == ()


@pytest.mark.parametrize("kind", ("old_fill", "shorter", "duplicate"))
def test_changed_originals_reconstruct_and_duplicate_delivery_stays_aligned(source, kind):
    events = tape(source)
    progress = scheduler._CapitalDueProgress()
    scheduled(source, events, 2, progress)
    if kind == "old_fill":
        events = (*events[:7], replace(events[7], fill=replace(events[7].fill, fee=D(".04"))))
    elif kind == "shorter":
        events = events[:3]
    else:
        events = (*events[:3], events[2], *events[3:])
    assert scheduled(source, events, 3, progress) == due(source, events, 3)
    assert len(progress.accounts.prefixes) == len(progress.accounts.originals) + 1


@pytest.mark.parametrize("kind", ("observation", "missed_settlement", "action_after_split"))
def test_failed_whole_due_call_does_not_publish_candidate(source, kind):
    events = tape(source, 5) if kind == "action_after_split" else tape(source)
    progress = scheduler._CapitalDueProgress()
    scheduled(source, events, 2, progress)
    before = progress.accounts
    snapshot = deepcopy(before)
    changes = {}
    index = 3
    if kind == "observation":
        changes["observations"] = (
            risk.CapitalRiskObservation(
                EventCursor(100, source.calendar.sessions[index].opens_at + timedelta(seconds=1)),
                len(events),
                None,
                False,
                False,
            ),
        )
    elif kind == "missed_settlement":
        index = 4
    else:
        from trading_bot.market_data.etf_capital_actions import CapitalSplit

        index = 2
        actions = distribution_actions(source)
        changes["actions"] = (
            replace(
                actions[0],
                splits=(
                    CapitalSplit(source.calendar.sessions[index].session_date, D(2), "a" * 64),
                ),
            ),
            *actions[1:],
        )
    with pytest.raises(ValueError, match="capital_due_facts_invalid"):
        scheduled(source, events, index, progress, **changes)
    assert progress.accounts is before and progress.accounts == snapshot
    assert scheduled(source, events, 3 if kind != "action_after_split" else 2, progress) == due(
        source, events, 3 if kind != "action_after_split" else 2
    )


def test_returned_and_original_mutation_cannot_poison_due_progress(source):
    events = tape(source)
    original = deepcopy(events)
    progress = scheduler._CapitalDueProgress()
    facts = scheduled(source, events, 3, progress)
    expected = due(source, original, 3)
    object.__setattr__(facts[0].event, "fill_id", "tampered")
    object.__setattr__(events[2].fill, "fee", D(1))
    assert scheduled(source, original, 3, progress) == expected


@pytest.mark.parametrize("kind", ("split", "entitlement", "same_day_payment"))
def test_owned_action_results_equal_original_batch_with_literal_atomic_nav(source, kind):
    from trading_bot.market_data.etf_capital_actions import CapitalSplit

    events = tape(source, 5)
    progress = scheduler._CapitalDueProgress()
    scheduled(source, events, 2, progress)
    bars = None
    if kind == "split":
        actions = (
            replace(
                source.actions[0],
                splits=(CapitalSplit(source.calendar.sessions[2].session_date, D(2), "a" * 64),),
            ),
            *source.actions[1:],
        )
        original_bars = tuple(
            p.raw_bars[-1]
            for p in capital_dataset_features(
                source, as_of_session=source.calendar.sessions[2].session_date
            )
        )
        bars = (
            replace(
                original_bars[0],
                open=original_bars[0].open / 2,
                high=original_bars[0].high / 2,
                low=original_bars[0].low / 2,
                close=original_bars[0].close / 2,
            ),
            *original_bars[1:],
        )
    else:
        actions = distribution_actions(source, pay_index=2 if kind == "same_day_payment" else 4)
    changes = {} if bars is None else {"raw_bars": bars}
    actual = scheduled(source, events, 2, progress, actions=actions, **changes)
    assert actual == due(source, events, 2, actions=actions, bars=bars)
    final = account.replay_capital_action_account(
        initial_cash=D(100), events=applied(events, actual)
    )
    assert final.marked_equity == D("100.26" if kind == "split" else "100.36")
    if kind == "split":
        assert (final.quantity, final.average_price) == (D(".2"), D("49.5"))
    elif kind == "entitlement":
        assert (final.cash, final.distribution_receivable) == (D("90.06"), D(".1"))
    else:
        assert (final.cash, final.distribution_receivable) == (D("90.16"), D(0))


def test_late_payment_failure_after_staged_settlement_keeps_prior_transaction(source, monkeypatch):
    actions = distribution_actions(source, pay_index=3)
    events = tape(source, 5)
    progress = scheduler._CapitalDueProgress()
    events = applied(events, scheduled(source, events, 2, progress, actions=actions))
    sold_at = source.calendar.sessions[2].opens_at + timedelta(minutes=1)
    events = (
        *events,
        *(retime(e, sold_at + timedelta(seconds=i), 20 + i) for i, e in enumerate(script()[5:8])),
    )
    before = progress.accounts
    snapshot = deepcopy(before)
    real = scheduler._account_prefixes_owned
    staged = []

    def prepare(*args, **kwargs):
        result = real(*args, **kwargs)
        staged.append(type(kwargs["events"][-1]).__name__)
        return result

    monkeypatch.setattr(scheduler, "_account_prefixes_owned", prepare)
    with pytest.raises(ValueError, match="capital_due_facts_invalid"):
        scheduled(source, events, 4, progress, actions=actions)
    assert staged[-1] == "CapitalSaleSettlement"
    assert progress.accounts is before and progress.accounts == snapshot
    # An explicit changed declaration with a timely payment must reconstruct,
    # not inherit the settlement from the failed whole call.
    timely = distribution_actions(source, pay_index=4)
    old_entitlement = events[5]
    corrected = (
        *events[:5],
        replace(old_entitlement, pay_date=source.calendar.sessions[4].session_date),
        *events[6:],
    )
    assert scheduled(source, corrected, 4, progress, actions=timely) == due(
        source, corrected, 4, actions=timely
    )


@pytest.mark.parametrize("kind", ("flag", "subclass", "progress_subclass"))
def test_whole_original_admission_cannot_be_replaced_by_cached_hashes(source, kind):
    events = tape(source)
    progress = scheduler._CapitalDueProgress()
    scheduled(source, events, 2, progress)
    if kind == "flag":
        events = deepcopy(events)
        object.__setattr__(events[0], "execution_enabled", True)
    elif kind == "subclass":

        class Submission(account.CapitalAccountSubmission):
            pass

        events = (
            Submission(events[0].symbol, events[0].request, events[0].episode_fee_bound),
            *events[1:],
        )
    else:

        class Progress(scheduler._CapitalDueProgress):
            pass

        progress = Progress()
    with pytest.raises(ValueError, match="capital_due_facts_invalid"):
        scheduled(source, events, 3, progress)


@pytest.mark.parametrize("outcome", ("filled", "partial", "unfilled", "rejected", "denied"))
def test_owned_entry_uses_canonical_continuation_not_full_public_batch(outcome, monkeypatch):
    request = entry("filled" if outcome == "denied" else outcome)
    if outcome == "denied":
        request = replace(request, episode_fee_bound=None)
    expected = entries.simulate_capital_daily_entry(request)
    calls = []
    real = entries.replay_capital_action_account

    def full(**kwargs):
        calls.append(1)
        return real(**kwargs)

    monkeypatch.setattr(entries, "replay_capital_action_account", full)
    actual = entries._simulate_owned_capital_daily_entry(request, progress=risk._RiskProgress())
    assert calls == []
    assert facts(actual) == facts(expected)


@pytest.mark.parametrize("outcome", ("filled", "partial", "unfilled", "rejected"))
def test_owned_exit_uses_canonical_continuation_not_full_public_batch(outcome, monkeypatch):
    request = exit_value(outcome)
    expected = exits.simulate_capital_daily_exit(request)
    calls = []
    real = exits.replay_capital_action_account

    def full(**kwargs):
        calls.append(1)
        return real(**kwargs)

    monkeypatch.setattr(exits, "replay_capital_action_account", full)
    actual = exits._simulate_owned_capital_daily_exit(request, progress=risk._RiskProgress())
    assert calls == []
    assert facts_tuple(actual) == facts_tuple(expected)
