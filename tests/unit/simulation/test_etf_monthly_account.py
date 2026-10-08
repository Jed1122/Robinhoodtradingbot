"""Literal economic expectations; no broker observations."""

import importlib
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.unit.research.test_etf_monthly_study import study
from tests.unit.simulation.test_etf_account import episode_events, intent, submit
from trading_bot.market_data.etf_source import _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation.etf_account import EtfAccountRequest, EtfAccountStepper

D = Decimal


def api():
    return importlib.import_module("trading_bot.simulation.etf_monthly_account")


def events():
    # Old fixture includes .02 dividend; remove it for independent .22 loss.
    source = episode_events(D("98"))
    kept = tuple(e for e in source if e.kind not in ("dividend_ex", "dividend_pay"))
    return tuple(
        replace(
            e,
            ordinal=i,
            intent=replace(e.intent, config_hash=study().config_hash) if e.intent else None,
        )
        for i, e in enumerate(kept)
    )


def test_monthly_reuses_cash_trial_and_settlement_reducer_but_not_old_identity():
    req = api().EtfMonthlyAccountRequest(study(), D("500"), events())
    out = api().replay_etf_monthly_account(req)
    assert out.cash == out.settled_cash == D("499.78")
    assert out.fees == D(".02") and out.trial.consumed_loss == D(".22")
    assert out.trial.reserved_risk == 0 and out.complete
    pending = api().replay_etf_monthly_account(replace(req, events=req.events[:-1]))
    assert pending.trial.consumed_loss == 0 and pending.trial.reserved_risk == D("10.02")
    owner = api().EtfMonthlyAccountStepper(replace(req, events=()))
    for event in req.events:
        owner.apply(event)
    assert owner.state == out
    with pytest.raises(ValueError):
        EtfAccountRequest(study(), D("500"), ())
    with pytest.raises(ValueError):
        EtfAccountStepper(req)


def test_monthly_admission_duplicate_fee_bound_and_failed_owner_are_closed():
    req = api().EtfMonthlyAccountRequest(study(), D("500"), ())
    order = replace(intent(), config_hash=study().config_hash)
    event = replace(submit(order, stop=D("5"), reserve_fee=D(".1")), kind="pending_intent")
    denied = api().admit_etf_monthly_pending_intent(req, event)
    assert not denied.allowed and denied.state.cash == D("500")
    good = replace(event, stop_distance=D("1"))
    accepted = api().admit_etf_monthly_pending_intent(req, good)
    assert accepted.allowed and accepted.state.reserved_cash == D("10.1")
    repeated = api().admit_etf_monthly_pending_intent(replace(req, events=(good,)), good)
    assert not repeated.allowed and repeated.reason == "duplicate_pending_identity"
    owner = api().EtfMonthlyAccountStepper(req)
    with pytest.raises(ValueError):
        owner.apply(event)
    assert owner.failed
    with pytest.raises(ValueError):
        owner.apply(good)


def test_profit_never_replenishes_previous_trial_loss_and_ceiling_stays_binding():
    first = events()
    profitable = tuple(
        replace(
            e,
            ordinal=e.ordinal + len(first),
            event_id=content_hash(("second", e.event_id)),
            at_ns=e.at_ns + 86400 * 10**9,
            intent=replace(
                e.intent,
                id="second-" + e.intent.id,
                created_at=e.intent.created_at + timedelta(days=1),
                expires_at=e.intent.expires_at + timedelta(days=1),
            )
            if e.intent
            else None,
            fill=replace(
                e.fill,
                id="second-" + e.fill.id,
                broker_order_id="second-" + e.fill.broker_order_id,
                occurred_at=e.fill.occurred_at + timedelta(days=1),
            )
            if e.fill
            else None,
            fill_ids=tuple("second-" + f for f in e.fill_ids),
        )
        for e in events_for_price(D("102"))
    )
    result = api().replay_etf_monthly_account(
        api().EtfMonthlyAccountRequest(study(), D("500"), (*first, *profitable))
    )
    assert result.cash == D("499.96") and result.fees == D(".04")
    assert result.trial.consumed_loss == D(".22") and result.complete
    ceiling = api().replay_etf_monthly_account(
        api().EtfMonthlyAccountRequest(study(), D("1000"), events_for_price(D("102")))
    )
    assert ceiling.cash == D("1000.18") and ceiling.entry_halted


def events_for_price(price):
    source = episode_events(price)
    kept = tuple(e for e in source if e.kind not in ("dividend_ex", "dividend_pay"))
    return tuple(
        replace(
            e,
            ordinal=i,
            intent=replace(e.intent, config_hash=study().config_hash) if e.intent else None,
        )
        for i, e in enumerate(kept)
    )


def test_monthly_request_and_stepper_reject_invalid_inputs_and_windows():
    req = api().EtfMonthlyAccountRequest(study(), D("500"), ())
    for changes in (
        {"initial_cash": D("100")},
        {"events": []},
        {"events": (None,)},
        {"events": (replace(events()[2], at_ns=_ns(study().requested_end)),)},
    ):
        with pytest.raises(ValueError):
            replace(req, **changes)
    with pytest.raises(ValueError):
        api().replay_etf_monthly_account(None)
    with pytest.raises(ValueError):
        api().EtfMonthlyAccountStepper(None)


def test_pending_admission_cannot_escape_study_end_window():
    req = api().EtfMonthlyAccountRequest(study(), D("500"), ())
    order = replace(intent(at=study().requested_end), config_hash=study().config_hash)
    candidate = replace(submit(order), kind="pending_intent")
    denied = api().admit_etf_monthly_pending_intent(req, candidate)
    assert not denied.allowed and denied.state.cash == D("500")
