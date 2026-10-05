"""Incremental owner must retain the legacy cash/risk/hash contract."""

from dataclasses import replace
from decimal import Decimal, getcontext

import pytest

from tests.unit.simulation.test_etf_account import api, episode_events, request


def stepper(events=()):
    owner = getattr(api(), "EtfAccountStepper", None)
    assert owner is not None, "shared incremental account owner is missing"
    return owner(request(events))


def test_each_prefix_matches_legacy_and_independent_final_cash():
    events = episode_events()
    owner = stepper()
    assert owner.state == api().replay_etf_account(request(()))
    for index, event in enumerate(events):
        assert owner.apply(event) == api().replay_etf_account(request(events[: index + 1]))
    assert owner.state.cash == Decimal("500.10")
    assert str(owner.state.fees) == "0.02"
    assert owner.state.complete
    assert owner.state.trial.consumed_loss == 0
    assert owner.events == events


def test_reconstructed_owner_retains_duplicate_identity_and_loss_history():
    events = episode_events(sell_price=Decimal("99"))
    owner = stepper(events)
    before = owner.state
    assert owner.apply(events[0]) == before
    assert before.cash == Decimal("499.90")
    assert before.trial.consumed_loss == Decimal("0.10")
    assert len(owner.events) == len(events) + 1


def test_conflicting_duplicate_poisons_without_exposing_new_committed_state():
    events = episode_events()
    owner = stepper(events[:1])
    before = owner.state
    with pytest.raises(api().EtfAccountError):
        owner.apply(replace(events[0], ordinal=20))
    assert owner.failed and owner.state == before
    with pytest.raises(api().EtfAccountError):
        owner.apply(events[1])
    assert owner.events == events[:1]


def test_suspension_does_not_change_caller_decimal_context():
    previous = getcontext().copy()
    getcontext().prec = 9
    try:
        owner = stepper()
        owner.apply(episode_events()[0])
        assert getcontext().prec == 9
    finally:
        getcontext().prec = previous.prec


def test_advancement_does_not_rehash_prior_event(monkeypatch):
    events = episode_events()
    owner = stepper(events[:1])
    original = api().EtfAccountEvent.event_hash.fget

    def digest(event):
        assert event.event_id != events[0].event_id, "previous fact was reapplied"
        return original(event)

    monkeypatch.setattr(api().EtfAccountEvent, "event_hash", property(digest))
    owner.apply(events[1])
    assert str(owner.state.cash) == "489.99"


@pytest.mark.parametrize("value", [None, object(), True])
def test_invalid_fact_denies_and_latches(value):
    owner = stepper()
    with pytest.raises(api().EtfAccountError):
        owner.apply(value)
    assert owner.failed and owner.state.event_count == 0
