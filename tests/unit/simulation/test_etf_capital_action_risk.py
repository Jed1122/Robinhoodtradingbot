"""Literal synthetic action-aware loss state; not operational evidence."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from tests.unit.research.test_etf_capital_feasibility import instrument, loaded
from tests.unit.simulation._lifecycle_fixtures import ORIGIN, control, execution
from tests.unit.simulation.test_etf_capital_account import observation, opening, script
from tests.unit.simulation.test_etf_capital_action_account import action, cursor
from tests.unit.simulation.test_etf_capital_risk import losing_episodes, point
from trading_bot.domain import OrderEvent, Side
from trading_bot.simulation.etf_capital_account import (
    CapitalEpisodeFeesFinal,
    CapitalSaleSettlement,
)
from trading_bot.simulation.events import EventCursor


def run(events=(), observations=None):
    from trading_bot.simulation.etf_capital_risk import replay_capital_action_risk

    return replay_capital_action_risk(
        loaded=loaded(),
        initial_cash=D("100"),
        events=events,
        observations=observations or (point(0, 0),),
    )


@pytest.mark.parametrize("count", [0, 5])
def test_entry_cannot_ignore_supplied_action_tape_suffix(count):
    from trading_bot.simulation.etf_capital_risk import evaluate_capital_action_entry

    events = (*script()[:5], action())
    observations = (point(0, 0),) if count == 0 else (point(0, 0), point(1, 5, "99"))
    with pytest.raises(ValueError):
        evaluate_capital_action_entry(
            loaded=loaded(),
            initial_cash=D("100"),
            events=events,
            observations=observations,
            instrument=instrument(),
            entry_price=D("100"),
            stop_distance=D("2"),
            fee_bound=D(".1"),
        )


@pytest.mark.parametrize("kind", ["split", "distribution"])
def test_atomic_action_mark_prevents_phantom_peak_or_loss(kind):
    result = run((*script()[:5], action(kind)), (point(0, 0), point(1, 6)))
    current = result.points[-1]
    assert current.equity == D("99.96")
    assert current.snapshot.daily_loss_pct == D(".04")
    assert current.snapshot.peak_to_trough_drawdown_pct == D(".04")
    assert not result.execution_enabled and not result.evidence_promotable


def test_real_exmark_loss_remains_visible_including_entitlement_once():
    current = run((*script()[:5], action(ex_mark=D("80"))), (point(0, 0), point(1, 6))).points[-1]
    assert current.equity == D("98.16")
    assert current.snapshot.daily_loss_pct == D("1.84")
    assert not current.decision.new_entries_allowed


def test_conflicting_atomic_mark_cannot_erase_actual_exmark_loss():
    with pytest.raises(ValueError, match="capital_risk_invalid"):
        run((*script()[:5], action(ex_mark=D("80"))), (point(0, 0), point(1, 6, "100")))


def test_equal_atomic_mark_is_accepted():
    current = run((*script()[:5], action()), (point(0, 0), point(1, 6, "98"))).points[-1]
    assert current.equity == D("99.96")


def test_later_held_observation_needs_new_explicit_mark():
    later = replace(point(2, 6), cursor=EventCursor(2, ORIGIN + timedelta(seconds=9)))
    with pytest.raises(ValueError, match="capital_risk_invalid"):
        run((*script()[:5], action()), (point(0, 0), point(1, 6), later))
    current = run(
        (*script()[:5], action()), (point(0, 0), point(1, 6), replace(later, mark=D("97")))
    ).points[-1]
    assert current.equity == D("99.86")


def test_payment_does_not_double_count_receivable_or_refresh_price():
    events = (*script()[:5], action(), action("payment", n=6))
    current = run(events, (point(0, 0), point(1, 6), point(2, 7, "98"))).points[-1]
    assert current.equity == D("99.96")
    assert current.account.available_cash == D("90.10")
    with pytest.raises(ValueError, match="capital_risk_invalid"):
        run(events, (point(0, 0), point(1, 6), point(2, 7)))


def test_old_duplicate_cannot_backdate_action_state():
    events = (*script()[:5], action(), script()[0])
    early = replace(point(1, 7, "98"), cursor=EventCursor(1, ORIGIN + timedelta(seconds=1)))
    with pytest.raises(ValueError, match="capital_risk_invalid"):
        run(events, (point(0, 0), early))
    current = replace(point(1, 7), cursor=EventCursor(1, ORIGIN + timedelta(seconds=5)))
    assert run(events, (point(0, 0), current)).points[-1].equity == D("99.96")


def test_entry_cannot_spend_unpaid_distribution_or_open_episode():
    from trading_bot.simulation.etf_capital_risk import evaluate_capital_action_entry

    result = evaluate_capital_action_entry(
        loaded=loaded(),
        initial_cash=D("100"),
        events=(*script()[:5], action()),
        observations=(point(0, 0), point(1, 6)),
        instrument=instrument(),
        entry_price=D("100"),
        stop_distance=D("2"),
        fee_bound=D(".1"),
    )
    assert not result.allowed and result.denial_code == "account_episode_incomplete"


def test_flat_unpaid_receivable_survives_sale_until_true_completion_clock():
    sell = opening(6, Side.SELL, "90.06", ".1")
    sell = replace(
        sell, request=replace(sell.request, order=replace(sell.request.order, limit_price=D("98")))
    )
    tape = (
        *script()[:5],
        action(),
        sell,
        observation(sell, control("accepted-ex", 7, OrderEvent.BROKER_ACCEPTED)),
        observation(sell, execution("sold-ex", 8, ".1", price="98", fee=".05", side=Side.SELL)),
        CapitalSaleSettlement("settled-ex", cursor(9), "sold-ex"),
        action("payment", 10),
        CapitalEpisodeFeesFinal(
            "fees-ex", cursor(11), D(".09"), opening().request.order.account_id, "order-0"
        ),
    )
    values = run(tape, (point(0, 0), point(1, 6), point(2, 10), point(3, 12))).points
    assert values[2].equity == D("99.91") and not values[2].account.complete
    assert values[2].snapshot.consecutive_loss_count == 0
    assert values[3].equity == D("99.91") and values[3].account.complete
    assert values[3].snapshot.consecutive_loss_count == 1
    assert values[3].snapshot.last_loss_at == ORIGIN + timedelta(seconds=11)


def test_distinct_equal_time_actions_each_have_their_own_original_mark_observation():
    second = action(
        n=6,
        action_id="distribution-2",
        amount_per_share=D("0"),
        cursor=EventCursor(6, ORIGIN + timedelta(seconds=5)),
    )
    events = (*script()[:5], action(ex_mark=D("80")), second)
    last = replace(point(2, 7), cursor=EventCursor(2, ORIGIN + timedelta(seconds=5)))
    result = run(events, (point(0, 0), point(1, 6), last)).points[-1]
    assert result.equity == D("99.96") and result.snapshot.daily_loss_pct == D("1.84")


def test_shared_entry_allows_only_admissible_genesis_size_and_risk_denies_loss():
    from trading_bot.simulation.etf_capital_risk import evaluate_capital_action_entry

    kwargs = dict(
        loaded=loaded(),
        initial_cash=D("100"),
        instrument=instrument(),
        entry_price=D("10"),
        stop_distance=D(".2"),
        fee_bound=D(".1"),
    )
    allowed = evaluate_capital_action_entry(events=(), observations=(point(0, 0),), **kwargs)
    assert allowed.allowed and allowed.quantity == D("2")
    denied = evaluate_capital_action_entry(
        events=(*script()[:5], action(ex_mark=D("80"))),
        observations=(point(0, 0), point(1, 6)),
        **kwargs,
    )
    assert not denied.allowed and denied.denial_code == "daily_loss_limit_reached"


def test_action_owner_restores_shared_three_loss_pause_without_recounting():
    late = replace(point(2, 30), cursor=EventCursor(2, ORIGIN + timedelta(minutes=1)))
    result = run(losing_episodes(3), (point(0, 0), point(1, 30), late))
    assert result.points[-1].snapshot.consecutive_loss_count == 3
    assert result.points[-1].decision.entry_pause_until == ORIGIN + timedelta(
        seconds=29, minutes=240
    )


def test_legacy_v2_hashes_match_exact_prechange_source():
    from tests.unit.simulation.test_etf_capital_risk import run as legacy

    assert (
        legacy().result_hash == "eb9942dd8aadae2b4c310a3dc7e5c1f44008d7e28fbe7f85d3fafa3ec7c3fb28"
    )
    assert legacy(script(), (point(0, 0), point(1, 10))).result_hash == (
        "716e50c7e70c06e5bcb508a91eb0026dfa23a5f15ac81dcded72793c6ee40a51"
    )


def test_observation_jump_cannot_hide_intermediate_action_loss():
    events = (
        *script()[:5],
        action(ex_mark=D("80")),
        action(n=6, action_id="distribution-2", amount_per_share=D("0")),
    )
    with pytest.raises(ValueError, match="capital_risk_invalid"):
        run(events, (point(0, 0), point(1, 7)))
    result = run(events, (point(0, 0), point(1, 6), point(2, 7))).points[-1]
    assert result.equity == D("99.96")
    assert result.snapshot.daily_loss_pct == D("1.84")
    assert not result.decision.new_entries_allowed
