"""Independent hand accounting only; fabricated fills are not policy admission."""

import importlib
from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from tests.unit.domain.test_options import NOW, intent
from tests.unit.market_data.test_databento_batch import no_network  # noqa: F401
from tests.unit.research.test_options_study_registration import config
from tests.unit.simulation.test_options_historical_execution import scenario
from trading_bot.domain.enums import OrderEvent, Side
from trading_bot.domain.options import OptionLeg, OptionStructure, PositionEffect
from trading_bot.market_data.options_session_inputs import _ns
from trading_bot.market_data.options_source_verify import ceil_available_at
from trading_bot.market_data.recording import content_hash

D = Decimal


def api():
    try:
        return importlib.import_module("trading_bot.research.options_account_journal")
    except ModuleNotFoundError:
        pytest.fail("historical account journal is not implemented")


class Journal:
    def __init__(self):
        self.api = api()
        self.loaded = config()
        self.scenario = scenario()
        self.initial = self.api.initial_account_path(
            study_hash=content_hash("fabricated-study"),
            capital=D("10000"),
            start_ns=_ns(NOW),
            loaded=self.loaded,
            scenario=self.scenario,
        )
        self.state = self.initial
        self.entries = ()
        self.at = _ns(NOW)

    def add(self, fact, *, at=None):
        self.at = self.at + 1000 if at is None else at
        event = self.api.AccountJournalEntry(
            "event-" + str(len(self.entries)), self.at, self.state.journal_hash, fact
        )
        following = (*self.entries, event)
        state = self.replay(following)
        self.entries, self.state = following, state
        return event

    def replay(self, entries=None, **changes):
        values = dict(loaded=self.loaded, scenario=self.scenario)
        values.update(changes)
        return self.api.reconstruct_account_journal(
            self.initial, self.entries if entries is None else entries, **values
        )

    def submit(self, episode="episode-1", *, close=False, premium="0.25", units=1):
        template = intent()
        order = replace(
            template,
            intent_id=f"order-{len(self.entries)}",
            account_scope=self.initial.path_id,
            created_at=ceil_available_at(self.at + 1000),
            quantity=units,
            limit_price=D(premium),
            config_hash=self.loaded.config_hash,
            net_effect="credit" if close else "debit",
            structure=OptionStructure(
                template.structure.kind,
                (
                    OptionLeg(
                        template.structure.legs[0].contract,
                        Side.SELL if close else Side.BUY,
                        PositionEffect.CLOSE if close else PositionEffect.OPEN,
                        1,
                    ),
                ),
            ),
        )
        self.add(self.api.JournalIntent(episode, "session-1", order))
        self.add(self.api.JournalOrderUpdate(order.intent_id, OrderEvent.BROKER_ACCEPTED))
        return order.intent_id

    def fill(self, order_id, *, price="0.25", units=1, partial=False):
        return self.add(
            self.api.JournalOrderUpdate(
                order_id,
                OrderEvent.PARTIAL_FILL if partial else OrderEvent.FILL,
                units,
                D(price),
                D("0.50") * units,
            )
        )

    def settle(self):
        for obligation in tuple(self.state.unsettled):
            self.add(
                self.api.JournalSettlement(obligation.event_id),
                at=max(self.at + 1000, obligation.due_ns),
            )

    def round_trip(self, episode="episode-1", *, buy="0.25", sell="0.20", finish=True):
        self.fill(self.submit(episode, premium=buy), price=buy)
        self.fill(self.submit(episode, close=True, premium=sell), price=sell)
        if finish:
            self.settle()
            self.add(self.api.JournalComplete(episode))


def test_cash_quantity_fees_and_reservations_reconstruct_independently():
    j = Journal()
    j.round_trip(finish=False)
    assert j.state.cash == D("9994.00")
    assert j.state.fees == D("1.00")
    assert j.state.positions == ()
    assert j.state.available_cash == D("9974.50")
    assert sum((o.amount for o in j.state.unsettled), D(0)) == D("-6.00")
    assert j.state.trial.reserved_risk == D("26.00")
    assert j.state.trial.consumed_loss == 0
    assert j.state.trial.episodes[0].orders_terminal is True
    assert j.state.trial.episodes[0].settlement_and_fees_final is False
    with pytest.raises(ValueError):
        j.add(j.api.JournalComplete("episode-1"))
    j.settle()
    j.add(j.api.JournalComplete("episode-1"))
    assert j.state.trial.consumed_loss == D("6.00")
    assert j.state.trial.reserved_risk == 0
    assert j.state.available_cash == D("9994.00")
    assert j.replay() == j.state
    assert j.state.production_eligible is False and j.state.evidence_promotable is False


def test_profits_deposits_and_restart_do_not_replenish_consumed_trial_loss():
    j = Journal()
    j.round_trip()
    j.round_trip("episode-2", buy="0.25", sell="0.36")
    assert j.state.cash == D("10004.00")
    assert j.state.trial.consumed_loss == D("6.00")
    assert j.state.risk_capital == D("10000")
    j.add(j.api.JournalExternalFlow(D("500")))
    assert j.state.cash == D("10504.00")
    assert j.state.risk_capital == D("10000")
    assert j.replay().trial.remaining(D("50")) == D("44")


def test_deposit_cannot_hide_losses_or_increase_sizing_base():
    j = Journal()
    j.round_trip()
    j.add(j.api.JournalExternalFlow(D("500")))
    assert j.state.risk_capital == D("9994")


def test_withdrawal_cannot_leave_sizing_capital_above_actual_equity():
    j = Journal()
    j.round_trip()
    j.add(j.api.JournalExternalFlow(D("-500")))
    assert j.state.cash == D("9494")
    assert j.state.risk_capital == D("9494")
    assert j.state.trial.consumed_loss == D("6")


def test_duplicate_event_is_idempotent_but_conflicting_or_truncated_chain_denies():
    j = Journal()
    j.round_trip()
    assert j.replay((*j.entries, j.entries[2])) == j.state
    with pytest.raises(ValueError):
        j.replay((*j.entries, replace(j.entries[2], available_ns=j.at + 1)))
    with pytest.raises(ValueError):
        j.replay(j.entries[1:])
    with pytest.raises(ValueError):
        j.replay((*j.entries, replace(j.entries[-1], event_id="replacement")))


def test_pending_unknown_order_retains_reservation_after_restart():
    j = Journal()
    template = intent()
    order = replace(
        template,
        account_scope=j.initial.path_id,
        config_hash=j.loaded.config_hash,
        created_at=ceil_available_at(j.at + 1000),
    )
    j.add(j.api.JournalIntent("episode-1", "session-1", order))
    j.add(j.api.JournalOrderUpdate(order.intent_id, OrderEvent.BROKER_AMBIGUOUS))
    assert j.replay().trial.reserved_risk == D("26")
    with pytest.raises(ValueError):
        j.add(j.api.JournalComplete("episode-1"))


def test_rejected_unfilled_order_can_complete_without_creating_a_loss():
    j = Journal()
    template = intent()
    order = replace(
        template,
        account_scope=j.initial.path_id,
        config_hash=j.loaded.config_hash,
        created_at=ceil_available_at(j.at + 1000),
    )
    j.add(j.api.JournalIntent("episode-1", "session-1", order))
    j.add(j.api.JournalOrderUpdate(order.intent_id, OrderEvent.BROKER_REJECTED))
    j.add(j.api.JournalComplete("episode-1"))
    assert j.state.trial.reserved_risk == 0 and j.state.trial.consumed_loss == 0
    assert j.state.cash == D("10000")


def test_partial_fill_cancel_preserves_owned_quantity_and_full_reservation():
    j = Journal()
    order = j.submit(units=2)
    j.fill(order, partial=True)
    j.add(j.api.JournalOrderUpdate(order, OrderEvent.REQUEST_CANCEL))
    j.add(j.api.JournalOrderUpdate(order, OrderEvent.CANCEL_CONFIRMED))
    j.settle()
    assert j.state.positions[0].units == 1
    assert j.state.trial.reserved_risk == D("52")
    with pytest.raises(ValueError):
        j.add(j.api.JournalComplete("episode-1"))


def test_weekly_drawdown_halts_and_incidents_remain_latched():
    j = Journal()
    for reason in ("weekly_loss_limit", "maximum_drawdown", "unexpected_shares"):
        j.add(j.api.JournalIncident(reason))
    j.add(j.api.JournalExternalFlow(D("500")))
    assert j.replay().latched_halts == (
        "maximum_drawdown",
        "unexpected_shares",
        "weekly_loss_limit",
    )
    assert j.state.incidents == j.state.latched_halts


def test_independent_reconciliation_detects_fabricated_aggregate_cash():
    j = Journal()
    j.round_trip()
    assert (
        j.api.reconcile_account_journal(
            j.initial, j.entries, j.state, loaded=j.loaded, scenario=j.scenario
        )
        == ()
    )
    forged = replace(j.state, cash=j.state.cash + 1)
    assert "account_state_mismatch" in j.api.reconcile_account_journal(
        j.initial, j.entries, forged, loaded=j.loaded, scenario=j.scenario
    )


def test_replay_rejects_wrong_scenario_or_non_genesis_state():
    j = Journal()
    j.round_trip()
    with pytest.raises(ValueError):
        j.replay(scenario=scenario(entry_fee=D("0")))
    with pytest.raises(ValueError):
        j.api.reconstruct_account_journal(j.state, j.entries, loaded=j.loaded, scenario=j.scenario)


def test_journal_arithmetic_is_independent_of_ambient_decimal_precision():
    with localcontext() as context:
        context.prec = 2
        j = Journal()
        j.round_trip()
        assert j.state.cash == D("9994.00")
        assert j.state.trial.consumed_loss == D("6.00")


def test_journal_cannot_invent_reconciled_fills_without_cash_facts():
    j = Journal()
    order = j.submit()
    j.add(j.api.JournalOrderUpdate(order, OrderEvent.RECONCILIATION_DRIFT))
    with pytest.raises(ValueError):
        j.add(j.api.JournalOrderUpdate(order, OrderEvent.RECONCILE_FILLED))


def test_fill_cannot_share_acceptance_timestamp():
    j = Journal()
    order = j.submit()
    with pytest.raises(ValueError):
        j.add(j.api.JournalOrderUpdate(order, OrderEvent.FILL, 1, D("0.25"), D("0.50")), at=j.at)


def test_expiration_cannot_release_an_order_before_its_deadline():
    j = Journal()
    order = j.submit()
    with pytest.raises(ValueError):
        j.add(j.api.JournalOrderUpdate(order, OrderEvent.BROKER_EXPIRED))


def test_marking_unknown_ownership_and_negative_cash_are_not_silent():
    j = Journal()
    with pytest.raises(ValueError):
        j.add(j.api.JournalMark("missing-episode", D("0.01")))
    j.fill(j.submit())
    assert j.state.marked_equity == D("9974.50")  # unavailable mark contributes zero
    j.add(j.api.JournalMark("episode-1", D("0.20")))
    assert j.state.marked_equity == D("9994.50")
    j.add(j.api.JournalMark("episode-1", None))
    assert j.state.marked_equity == D("9974.50")
    j.add(j.api.JournalExternalFlow(D("-20000")))
    assert j.state.cash == D("-10025.50")
    assert j.state.incidents == ("negative_cash",)
    assert j.replay().latched_halts == ("negative_cash",)


@pytest.mark.parametrize(
    "changes",
    [
        {"fee": D("0.51")},
        {"price": D("0.26")},
        {"price": D("0.249")},
        {"fill_units": 2},
        {"event": OrderEvent.PARTIAL_FILL},
        {"order_id": "unknown"},
    ],
)
def test_bad_fill_facts_deny_instead_of_changing_cash(changes):
    j = Journal()
    order = j.submit()
    fact = j.api.JournalOrderUpdate(order, OrderEvent.FILL, 1, D("0.25"), D("0.50"))
    original = j.state
    with pytest.raises((ValueError, RuntimeError)):
        j.add(replace(fact, **changes))
    assert j.state == original and j.state.cash == D("10000")


def test_unknown_or_early_settlement_and_unowned_close_deny():
    j = Journal()
    with pytest.raises(ValueError):
        j.submit(close=True)
    order = j.submit()
    fill = j.fill(order)
    with pytest.raises(ValueError):
        j.add(j.api.JournalSettlement(fill.event_id), at=j.at)
    with pytest.raises(ValueError):
        j.add(j.api.JournalSettlement("unknown"))


def test_no_completion_after_assignment_incident_and_no_duplicate_completion():
    j = Journal()
    j.round_trip()
    with pytest.raises(ValueError):
        j.add(j.api.JournalComplete("episode-1"))
    j.round_trip("episode-2", finish=False)
    j.settle()
    j.add(j.api.JournalIncident("assignment"))
    with pytest.raises(ValueError):
        j.add(j.api.JournalComplete("episode-2"))
    assert j.state.trial.reserved_risk == D("26")


def test_expired_unfilled_order_releases_only_at_expiry_and_explicit_completion():
    j = Journal()
    order = j.submit()
    j.add(j.api.JournalOrderUpdate(order, OrderEvent.BROKER_EXPIRED), at=_ns(intent().expires_at))
    assert j.state.trial.reserved_risk == D("26")
    j.add(j.api.JournalComplete("episode-1"))
    assert j.state.trial.reserved_risk == 0


def test_chain_cannot_rewind_clock_or_use_changed_configuration():
    j = Journal()
    j.add(j.api.JournalIncident("weekly_loss_limit"))
    event = j.api.AccountJournalEntry(
        "new", j.at - 1, j.state.journal_hash, j.api.JournalExternalFlow(D("1"))
    )
    with pytest.raises(ValueError):
        j.replay((*j.entries, event))
    with pytest.raises(ValueError):
        j.replay(loaded=replace(j.loaded, config_hash="a" * 64))


@pytest.mark.parametrize(
    "factory,args",
    [
        ("JournalExternalFlow", (0.5,)),
        ("JournalExternalFlow", (D("0"),)),
        ("JournalMark", ("episode-1", D("NaN"))),
        ("JournalOrderUpdate", ("order-1", OrderEvent.BROKER_ACCEPTED, 1)),
        ("JournalOrderUpdate", ("order-1", OrderEvent.FILL, True, D("1"))),
        ("JournalOrderUpdate", ("order-1", OrderEvent.FILL, 1, None)),
        ("JournalIncident", ("",)),
    ],
)
def test_invalid_journal_payloads_are_closed(factory, args):
    with pytest.raises(ValueError):
        getattr(api(), factory)(*args)
