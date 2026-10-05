"""Fictional forward cycles exercise real account rules, never provider data."""

import importlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

import pytest

from tests.unit.simulation.test_etf_account import NOW, episode_events
from tests.unit.simulation.test_etf_history import study
from trading_bot.domain import OrderEvent, OrderState
from trading_bot.market_data.etf_source import _ns
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.simulation.etf_account import EtfAccountEvent, EtfAccountRequest

D = Decimal
DEFAULT_CASH = D("500")
START = datetime(2026, 10, 1, 15, tzinfo=UTC)


def api():
    try:
        return importlib.import_module("trading_bot.runtime.etf_forward_paper")
    except ModuleNotFoundError:
        pytest.fail("versioned forward paper economic owner is missing")


def forward_events(price="99"):
    # Explicitly new fictional fixture dates, not a native observation conversion.
    offset = START - NOW
    changed = []
    for event in episode_events(sell_price=D(price)):
        intent = event.intent
        instrument = event.instrument
        fill = event.fill
        changed.append(
            replace(
                event,
                at_ns=event.at_ns + _ns(START) - _ns(NOW),
                intent=None
                if intent is None
                else replace(
                    intent,
                    created_at=intent.created_at + offset,
                    expires_at=intent.expires_at + offset,
                ),
                instrument=None if instrument is None else replace(instrument, observed_at=START),
                fill=None if fill is None else replace(fill, occurred_at=fill.occurred_at + offset),
                cash_per_share=D("0") if event.kind == "dividend_ex" else None,
            )
        )
    return tuple(changed)


def tape(events=None, cash=DEFAULT_CASH):
    owner = api()
    facts = forward_events() if events is None else events
    plan = owner.ForwardPaperPlan(study(), START, START + timedelta(days=7), cash)
    cycles = tuple(
        owner.ForwardPaperCycle(
            event.at_ns,
            (index + 1) * 1_000_000_000,
            content_hash(("fictional-source", index)),
            content_hash(("fictional-strategy", index)),
            (event,),
        )
        for index, event in enumerate(facts)
    )
    return owner.ForwardPaperTape(plan, cycles)


def test_forward_cash_and_trial_loss_use_common_owner_not_sealed_window():
    request = tape()
    state = api().replay_forward_paper(request)
    assert state.account.cash == D("499.88")
    assert state.account.settled_cash == D("499.88")
    assert state.account.fees == D(".02")
    assert state.account.shares == 0 and state.account.complete
    assert state.account.trial.consumed_loss == D(".12")
    assert state.account.trial.remaining(D("50")) == D("49.88")
    assert state.cycle_count == 8 and state.account.event_count == 8
    assert state.paused and not state.execution_enabled and not state.evidence_promotable
    assert not state.qualifying_paper and not state.source_qualified and not state.costs_qualified
    with pytest.raises(ValueError):
        EtfAccountRequest(request.plan.policy, D("500"), forward_events())


def test_empty_and_source_only_cycle_do_not_manufacture_economic_progress():
    request = tape(())
    original = api().replay_forward_paper(request)
    cycle = api().ForwardPaperCycle(
        _ns(START), 1, content_hash("unverified-receipt"), content_hash("no-signal"), ()
    )
    observed = api().replay_forward_paper(replace(request, cycles=(cycle,)))
    assert observed.cycle_count == 1 and observed.account.event_count == 0
    assert observed.account.last_at_ns is None and observed.account.last_ordinal is None
    assert observed.account.cash == original.account.cash == D("500")
    assert observed.source_cursor == (_ns(START), 1, cycle.source_hash)
    assert observed.strategy_state_hash == cycle.strategy_state_hash
    assert observed.prefix_hash != original.prefix_hash and not observed.qualifying_paper


def test_pending_partial_cancel_uncertainty_and_unsettled_reservations_survive_replay():
    events = forward_events()
    pending = replace(events[0], kind="pending_intent")
    initial = api().replay_forward_paper(tape((pending,)))
    assert initial.account.orders[0].order.state is OrderState.SUBMISSION_PENDING
    assert initial.account.reserved_cash == D("10.02")
    assert initial.account.trial.reserved_risk == D("10.02")
    ack = EtfAccountEvent(
        content_hash("ack"),
        1,
        _ns(START) + 1,
        "order_status",
        order_id=pending.intent.id,
        order_event=OrderEvent.BROKER_ACCEPTED,
    )
    partial = replace(events[1], ordinal=2, fill=replace(events[1].fill, quantity=D(".04")))
    cancel = EtfAccountEvent(
        content_hash("cancel"),
        3,
        partial.at_ns + 1,
        "order_status",
        order_id=pending.intent.id,
        order_event=OrderEvent.REQUEST_CANCEL,
    )
    state = api().replay_forward_paper(tape((pending, ack, partial, cancel)))
    assert state.account.orders[0].order.state is OrderState.CANCEL_PENDING
    assert state.account.cash == D("495.99") and state.account.shares == D(".04")
    assert state.account.reserved_cash == D("6.01")
    assert state.account.trial.reserved_risk == D("10.02") and not state.account.complete
    sold = api().replay_forward_paper(tape(events[:-1]))
    assert sold.account.cash == D("499.88") and sold.account.settled_cash == D("489.99")
    assert sold.account.trial.reserved_risk == D("10.02") and not sold.account.complete


def test_future_suffix_and_ambient_precision_cannot_change_consumed_prefix():
    full = tape()
    prefix = replace(full, cycles=full.cycles[:2])
    state = api().replay_forward_paper(prefix)
    future = replace(full.cycles[-1], source_hash=content_hash("other-future"))
    extended = replace(full, cycles=(*full.cycles[:-1], future))
    with localcontext() as context:
        context.prec = 2
        assert api().replay_forward_paper(replace(extended, cycles=extended.cycles[:2])) == state
    assert prefix.plan.plan_hash == full.plan.plan_hash == extended.plan.plan_hash


def test_larger_cash_cannot_increase_risk_reference_or_allow_excess_size():
    request = tape(cash=D("1000"))
    state = api().replay_forward_paper(request)
    assert request.plan.policy.risk_equity_reference == D("100")
    assert state.account.cash == D("999.88")
    entry = forward_events()[0]
    excessive = replace(entry, intent=replace(entry.intent, quantity=D(".6")))
    with pytest.raises(ValueError, match="forward_paper_invalid"):
        api().replay_forward_paper(tape((excessive,), cash=D("1000")))


def test_identical_fill_redelivery_is_once_and_conflicting_economics_deny():
    events = forward_events()
    duplicate = replace(events[1], event_id=content_hash("duplicate"), ordinal=2)
    duplicate = replace(duplicate, fill=replace(duplicate.fill))
    state = api().replay_forward_paper(tape((events[0], events[1], duplicate)))
    assert state.account.cash == D("489.99") and state.account.fees == D(".01")
    conflict = replace(duplicate, fill=replace(duplicate.fill, fee=D(".02")))
    with pytest.raises(ValueError, match="forward_paper_invalid"):
        api().replay_forward_paper(tape((events[0], events[1], conflict)))


@pytest.mark.parametrize(
    "change",
    [
        {"starts_at": datetime(2025, 12, 31, tzinfo=UTC)},
        {"ends_at": START},
        {"ends_at": START + timedelta(days=32)},
        {"starts_at": START.replace(tzinfo=None)},
        {"initial_cash": D("1001")},
        {"initial_cash": D("NaN")},
        {"initial_cash": 500},
    ],
)
def test_invalid_plan_cannot_become_forward_authority(change):
    with pytest.raises(ValueError):
        replace(tape().plan, **change)


@pytest.mark.parametrize(
    "change",
    [
        {"at_ns": True},
        {"received_monotonic_ns": 0},
        {"received_monotonic_ns": 1.0},
        {"source_hash": "unknown"},
        {"strategy_state_hash": "unknown"},
        {"events": []},
        {"at_ns": _ns(START) - 1},
    ],
)
def test_invalid_cycles_deny_before_economic_effects(change):
    request = tape()
    with pytest.raises(ValueError):
        invalid = replace(request.cycles[0], **change)
        replace(request, cycles=(invalid,))


def test_clock_regression_prefix_conflict_and_forged_flags_deny():
    request = tape()
    with pytest.raises(ValueError):
        replace(request, cycles=(request.cycles[1], request.cycles[0]))
    with pytest.raises(ValueError):
        replace(request, cycles=(request.cycles[0], request.cycles[0]))
    forged = replace(request)
    object.__setattr__(forged.plan, "initial_cash", D("2000"))
    with pytest.raises(ValueError, match="forward_paper_invalid"):
        api().replay_forward_paper(forged)


@pytest.mark.parametrize("target", ["plan", "tape"])
def test_forged_version_or_source_label_cannot_cross_owner(target):
    request = tape()
    if target == "plan":
        object.__setattr__(request.plan, "schema", "actual-forward")
    else:
        object.__setattr__(request, "source_kind", "qualified-native")
    with pytest.raises(ValueError, match="forward_paper_invalid"):
        api().replay_forward_paper(request)


def test_exact_event_duplicate_is_receipt_only_and_conflict_denies():
    request = tape()
    first = request.cycles[0]
    again = replace(first, received_monotonic_ns=first.received_monotonic_ns + 1)
    state = api().replay_forward_paper(replace(request, cycles=(first, again)))
    assert state.account.event_count == 1 and state.account.reserved_cash == D("10.02")
    assert first.cycle_id != again.cycle_id
    conflict = replace(again, events=(replace(first.events[0], fee_bound=D(".03")),))
    with pytest.raises(ValueError):
        replace(request, cycles=(first, conflict))


def test_old_account_hash_and_origin_are_unchanged():
    from trading_bot.simulation.etf_account import replay_etf_account

    events = episode_events(sell_price=D("99"))
    legacy = replay_etf_account(EtfAccountRequest(study(), D("500"), events))
    assert legacy.cash == D("499.90") and legacy.trial.consumed_loss == D(".10")
    assert '"paused":true' in canonical_json(legacy)
    assert study().requested_end == datetime(2026, 1, 1, tzinfo=UTC)


def test_oversized_exact_redeliveries_deny_at_tape_construction():
    request = tape()
    first = request.cycles[0]
    # Event count alone admits this 12 MiB tape, beyond the durable 8 MiB envelope.
    repeated = replace(first, events=first.events * 10000)
    with pytest.raises(ValueError, match="forward_paper_invalid"):
        replace(request, cycles=(repeated,))


def test_budget_includes_reconstructed_state_and_envelope_not_only_tape(monkeypatch):
    request = tape()
    # A smaller resource budget exercises the same boundary without huge fixtures.
    budget = len(canonical_json(request).encode()) + 1024
    monkeypatch.setattr(api(), "MAX_JOINT_BYTES", budget, raising=False)
    with pytest.raises(ValueError, match="forward_paper_invalid"):
        replace(request)
