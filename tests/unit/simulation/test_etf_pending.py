"""Synthetic pending-submission facts cannot imply broker acceptance or cash flows."""

from dataclasses import replace
from datetime import timedelta

import pytest

from tests.unit.simulation.test_etf_account import (
    NOW,
    D,
    api,
    fill,
    intent,
    request,
    settled,
    submit,
)
from trading_bot.domain import OrderEvent, OrderState
from trading_bot.market_data.etf_source import _ns
from trading_bot.market_data.recording import content_hash


def pending(order=None):
    return replace(submit(intent() if order is None else order), kind="pending_intent")


def status(event, ordinal=1, seconds=1, order="entry"):
    return api().EtfAccountEvent(
        content_hash(("pending-status", event, ordinal, seconds, order)),
        ordinal,
        _ns(NOW + timedelta(seconds=seconds)),
        "order_status",
        order_id=order,
        order_event=event,
    )


def test_pending_order_reserves_cash_and_trial_without_implicit_acceptance():
    state = api().replay_etf_account(request((pending(),)))
    assert state.orders[0].order.state is OrderState.SUBMISSION_PENDING
    assert state.cash == state.settled_cash == D("500") and state.shares == 0
    assert state.reserved_cash == state.trial.reserved_risk == D("10.02")
    assert not state.complete and state.paused and not state.execution_enabled


def test_pending_order_cannot_fill_before_acceptance():
    order = intent()
    with pytest.raises(ValueError, match="etf_account_invalid"):
        api().replay_etf_account(request((pending(order), fill(order, "too-soon", 1, 1))))
    accepted = status(OrderEvent.BROKER_ACCEPTED)
    execution = fill(order, "after-ack", 2, 2)
    state = api().replay_etf_account(request((pending(order), accepted, execution)))
    assert state.cash == D("489.99") and state.shares == D(".1")
    assert state.trial.reserved_risk == D("10.02") and not state.complete


def test_ambiguous_pending_order_restores_reservations_and_blocks_another_entry():
    original = request((pending(), status(OrderEvent.BROKER_AMBIGUOUS)))
    state = api().replay_etf_account(original)
    assert state.orders[0].order.state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION
    assert state.reserved_cash == state.trial.reserved_risk == D("10.02")
    assert api().resume_etf_account(original, state) == state
    with pytest.raises(ValueError, match="etf_account_invalid"):
        retry = intent("retry", at=NOW + timedelta(seconds=3))
        api().replay_etf_account(request((*original.events, replace(pending(retry), ordinal=2))))


def test_reconciled_submission_requires_later_explicit_fill_and_settlement():
    order = intent()
    facts = (
        pending(order),
        status(OrderEvent.BROKER_AMBIGUOUS),
        status(OrderEvent.RECONCILE_SUBMITTED, 2, 2),
        fill(order, "observed", 3, 3),
        settled(("observed",), 4, 4),
    )
    state = api().replay_etf_account(request(facts))
    assert state.shares == D(".1") and state.cash == D("489.99")
    assert state.settled_cash == state.cash and not state.complete


@pytest.mark.parametrize("event", [OrderEvent.RECONCILE_PARTIAL, OrderEvent.RECONCILE_FILLED])
def test_reconciliation_status_cannot_invent_unobserved_fills_or_release_risk(event):
    with pytest.raises(ValueError, match="etf_account_invalid"):
        api().replay_etf_account(
            request((pending(), status(OrderEvent.BROKER_AMBIGUOUS), status(event, 2, 2)))
        )


@pytest.mark.parametrize("ambiguous", [False, True])
def test_confirmed_rejection_releases_only_an_unfilled_episode(ambiguous):
    facts = (pending(),)
    rejection = OrderEvent.BROKER_REJECTED
    if ambiguous:
        facts += (status(OrderEvent.BROKER_AMBIGUOUS),)
        rejection = OrderEvent.RECONCILE_REJECTED
    state = api().replay_etf_account(request((*facts, status(rejection, len(facts), len(facts)))))
    assert state.cash == D("500") and state.shares == 0 and state.complete
    assert state.trial.consumed_loss == state.trial.reserved_risk == state.reserved_cash == 0


def test_partial_fill_cannot_be_reconciled_as_unfilled_rejection_or_submission():
    order = intent()
    facts = (
        pending(order),
        status(OrderEvent.BROKER_ACCEPTED),
        fill(order, "partial", 2, 2, quantity=D(".04")),
        status(OrderEvent.RECONCILIATION_DRIFT, 3, 3),
    )
    for event in (OrderEvent.RECONCILE_REJECTED, OrderEvent.RECONCILE_SUBMITTED):
        with pytest.raises(ValueError, match="etf_account_invalid"):
            api().replay_etf_account(request((*facts, status(event, 4, 4))))
    resumed = api().replay_etf_account(
        request((*facts, status(OrderEvent.RECONCILE_PARTIAL, 4, 4)))
    )
    assert resumed.orders[0].order.state is OrderState.PARTIALLY_FILLED
    assert resumed.shares == D(".04") and resumed.trial.reserved_risk == D("10.02")


def test_late_ack_cannot_reopen_an_expired_submission():
    with pytest.raises(ValueError, match="etf_account_invalid"):
        api().replay_etf_account(
            request((pending(), status(OrderEvent.BROKER_ACCEPTED, seconds=3600)))
        )


def test_legacy_accepted_fixture_contract_and_hash_are_unchanged():
    state = api().replay_etf_account(request((submit(intent()),)))
    assert state.orders[0].order.state is OrderState.SUBMITTED
    # Captured from the exact pre-change implementation, not recomputed as an oracle.
    assert state.state_hash == "9430f702bed5c96f2dbc5b1ff5a6ff55c8fcde1f049ff572bff1338bccf9e0a2"


def test_account_admission_is_zero_effect_when_canonical_limit_denies():
    original = request(())
    allowed = api().admit_etf_pending_intent(original, pending())
    assert allowed.allowed and allowed.state.orders[0].order.state is OrderState.SUBMISSION_PENDING
    assert allowed.scope == "synthetic-account-limits-only-v1"
    assert not allowed.production_pretrade_eligible and not allowed.execution_enabled
    oversized = pending(intent(quantity=D("1")))
    denied = api().admit_etf_pending_intent(original, oversized)
    assert not denied.allowed and denied.reason == "canonical_account_admission_denied"
    assert denied.state == api().replay_etf_account(original)
    assert denied.state.orders == () and denied.state.reserved_cash == 0


def test_account_admission_refuses_invalid_history_or_an_already_accepted_event():
    with pytest.raises(ValueError, match="etf_account_invalid"):
        api().admit_etf_pending_intent(request(()), submit(intent()))
    wrong_history = request((settled(("unknown",), 0, 1),))
    with pytest.raises(ValueError, match="etf_account_invalid"):
        api().admit_etf_pending_intent(wrong_history, pending())


def test_pending_admission_uses_common_activity_gate_without_legacy_hash_changes(monkeypatch):
    from types import SimpleNamespace

    calls = []

    def deny_activity(snapshot, *, settings):
        calls.append((snapshot, settings))
        return SimpleNamespace(allowed=False)

    monkeypatch.setattr(api(), "evaluate_activity_limits", deny_activity, raising=False)
    result = api().admit_etf_pending_intent(request(()), pending())
    assert calls and not result.allowed and result.state.orders == ()
    assert calls[0][0].new_orders_today == calls[0][0].new_orders_for_symbol_today == 0
    assert calls[0][0].last_new_order_at is None
    legacy = api().replay_etf_account(request((submit(intent()),)))
    assert legacy.state_hash == "9430f702bed5c96f2dbc5b1ff5a6ff55c8fcde1f049ff572bff1338bccf9e0a2"


def test_pending_exit_does_not_apply_entry_activity_gate(monkeypatch):
    from tests.unit.simulation.test_etf_account import episode_events

    def forbidden(*args, **kwargs):
        raise AssertionError("entry activity must not gate protective exit")

    monkeypatch.setattr(api(), "evaluate_activity_limits", forbidden, raising=False)
    facts = episode_events()
    candidate = replace(facts[5], kind="pending_intent")
    result = api().admit_etf_pending_intent(request(facts[:5]), candidate)
    assert result.allowed and result.state.shares == D(".1")
    assert result.state.orders[-1].order.state is OrderState.SUBMISSION_PENDING


@pytest.mark.parametrize("lifecycle", ["pending", "unknown", "accepted", "partial", "rejected"])
def test_duplicate_pending_identity_never_regrants_submission_permission(lifecycle):
    order = intent()
    candidate = pending(order)
    facts = (candidate,)
    if lifecycle == "unknown":
        facts += (status(OrderEvent.BROKER_AMBIGUOUS),)
    elif lifecycle == "rejected":
        facts += (status(OrderEvent.BROKER_REJECTED),)
    elif lifecycle in ("accepted", "partial"):
        facts += (status(OrderEvent.BROKER_ACCEPTED),)
        if lifecycle == "partial":
            facts += (fill(order, "already-filled", 2, 2, quantity=D(".04")),)
    original = request(facts)
    state = api().replay_etf_account(original)
    result = api().admit_etf_pending_intent(original, candidate)
    assert not result.allowed and result.reason == "duplicate_pending_identity"
    assert result.state == state
    assert api().replay_etf_account(request((*facts, candidate))) == state


def test_changed_event_id_cannot_regrant_an_existing_order_identity():
    candidate = pending()
    original = request((candidate,))
    changed = replace(candidate, event_id=content_hash("different-event"), ordinal=1)
    result = api().admit_etf_pending_intent(original, changed)
    assert not result.allowed and result.reason == "duplicate_pending_identity"
    assert result.state == api().replay_etf_account(original)
