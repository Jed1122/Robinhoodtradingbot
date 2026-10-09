"""Owned daily instructions through shared reducers; fabricated prices only."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from tests.unit.research.test_etf_capital_feasibility import instrument, loaded
from tests.unit.research.test_etf_capital_signals import projections
from trading_bot.domain import InstrumentId
from trading_bot.research.etf_capital_signals import CapitalCandidate


def frames(count=4, *, hold=2):
    from trading_bot.simulation.etf_capital_daily_owner import CapitalDailyFrame

    result = []
    for index in range(count):
        records = projections(tuple(D(100 + i) for i in range(200 + index)))
        terms = tuple(
            instrument(
                id=InstrumentId("fixture-" + str(p.raw_bars[-1].instrument_id)),
                symbol=str(p.raw_bars[-1].instrument_id),
                observed_at=p.raw_bars[-1].starts_at,
                price_increment=D(".000001"),
            )
            for p in records
        )
        result.append(
            CapitalDailyFrame(
                CapitalCandidate("momentum", 20, 100, hold),
                records,
                terms,
                daily_reset_reconciled=True,
                weekly_reset_reviewed=True,
            )
        )
    return tuple(result)


def run(count=4, *, records=None, **changes):
    from trading_bot.simulation.etf_capital_daily_owner import (
        CapitalDailyOwnerRequest,
        replay_capital_daily_owner,
    )

    value = CapitalDailyOwnerRequest(
        loaded(), D("100"), records or frames(count), D(".10"), D(".01"), D(".02"), D(".10")
    )
    return replay_capital_daily_owner(replace(value, **changes))


def test_first_close_instruction_cannot_trade_at_its_own_open():
    value = run(1)
    assert value.events == ()
    assert value.account.cash == D("100")
    assert value.points[0].policy.action == "entry"
    assert value.points[0].opening is None


def test_next_open_owns_literal_sizing_fees_cash_and_opening_policy():
    value = run(2)
    assert value.account.quantity == D(".066")
    assert value.account.cash == D("80.1801")
    assert value.account.fees == D(".01")
    assert value.points[-1].equity == D("99.9801")
    assert value.points[-1].opening.symbol == "IEF"
    assert value.points[-1].opening.stop_distance == D("4")
    assert not value.account.complete


def test_terminal_holding_deadline_schedules_but_does_not_force_sale():
    value = run(3)
    assert value.account.quantity == D(".066")
    assert value.points[-1].policy.reason == "maximum_hold"
    assert len(value.events) == 3


def test_scheduled_exit_preserves_literal_unsettled_and_fee_obligations():
    value = run(4)
    assert value.account.quantity == 0
    # 80.1801 + (302 * .9995 * .066) - .02 = 100.082134.
    assert value.account.cash == D("100.082134")
    assert value.account.unsettled_proceeds == D("19.902034")
    assert value.account.available_cash == D("80.1101")
    assert value.account.fees == D(".03")
    assert not value.account.complete


def test_unfilled_original_order_cannot_be_replaced_by_later_signal():
    value = run(entry_outcome="unfilled", entry_fill_fraction=D(0), entry_fee=D(0))
    assert len(value.events) == 2
    assert value.account.quantity == 0
    assert value.account.cash == 100
    assert not value.account.complete
    assert all(point.opening is None for point in value.points)


def test_partial_original_order_keeps_policy_and_blocks_competing_orders():
    value = run(entry_outcome="partial", entry_fill_fraction=D(".5"))
    assert len(value.events) == 3
    assert value.account.quantity == D(".033")
    assert value.account.cash == D("90.08505")
    assert not value.account.complete


def test_fold_candidate_change_cannot_replace_owned_opening_policy():
    records = frames(3, hold=20)
    records = (
        *records[:2],
        replace(records[2], candidate=CapitalCandidate("mean_reversion", 5, 0, 2)),
    )
    value = run(records=records)
    assert value.points[-1].opening.candidate == CapitalCandidate("momentum", 20, 100, 20)
    assert value.points[-1].policy.action == "hold"


def test_owned_replay_is_deterministic_and_permanently_non_promotable():
    first, second = run(2), run(2)
    assert first == second
    assert all(
        flag is False
        for flag in (
            first.source_qualified,
            first.cost_qualified,
            first.execution_enabled,
            first.economic_admitted,
            first.evidence_promotable,
        )
    )


def test_reversed_session_input_denies_instead_of_replaying_future_signal():
    with pytest.raises(ValueError):
        run(records=tuple(reversed(frames(2))))


def test_explicit_original_settlement_and_bound_finality_release_obligations():
    from trading_bot.simulation.etf_capital_account import (
        CapitalEpisodeFeesFinal,
        CapitalSaleSettlement,
    )
    from trading_bot.simulation.etf_capital_daily_owner import CapitalDailyOriginalFact
    from trading_bot.simulation.events import EventCursor

    prior = run(4)
    records = frames(5)
    opened = records[-1].projections[0].raw_bars[-1].starts_at
    sale, buy = prior.events[-1], prior.events[0]
    settlement = CapitalSaleSettlement(
        "settled", EventCursor(1000, opened - timedelta(seconds=2)), sale.fill.id
    )
    final = CapitalEpisodeFeesFinal(
        "final",
        EventCursor(1002, opened - timedelta(seconds=1)),
        D(".03"),
        buy.request.order.account_id,
        buy.request.order.id,
    )
    records = (
        *records[:-1],
        replace(
            records[-1],
            original_facts=(
                CapitalDailyOriginalFact(settlement, None),
                CapitalDailyOriginalFact(final, None),
            ),
        ),
    )
    value = run(records=records)
    # New signal cannot reuse unsettled funds at the fourth-session close.
    # Fifth-session opening may enter only after the explicit original facts.
    assert value.points[-2].equity == D("100.082134")
    assert value.account.unsettled_proceeds == 0
    assert value.events[6:8] == (settlement, final)


def test_outside_submission_cannot_supply_owner_preapproved_entry():
    from trading_bot.simulation.etf_capital_daily_owner import CapitalDailyOriginalFact

    submission = run(2).events[0]
    records = frames(1)
    records = (replace(records[0], original_facts=(CapitalDailyOriginalFact(submission, None),)),)
    with pytest.raises(ValueError):
        run(records=records)


def test_completed_range_uses_adverse_stop_first_not_optimistic_target():
    records = frames(2)
    altered = tuple(
        replace(p, raw_bars=(*p.raw_bars[:-1], replace(p.raw_bars[-1], high=D(310), low=D(295))))
        for p in records[-1].projections
    )
    records = (records[0], replace(records[-1], projections=altered))
    value = run(records=records)
    assert value.account.quantity == 0
    assert value.account.cash == D("99.69622705")
    assert not value.account.complete


def test_adverse_opening_stop_gap_precedes_scheduled_strategy_exit():
    records = frames(4)
    altered = tuple(
        replace(p, raw_bars=(*p.raw_bars[:-1], replace(p.raw_bars[-1], open=D(290), low=D(289))))
        for p in records[-1].projections
    )
    records = (*records[:-1], replace(records[-1], projections=altered))
    value = run(records=records)
    # 80.1801 + (290 * .9995 * .066) - .02 = 99.29053.
    assert value.account.cash == D("99.29053")
    assert value.account.quantity == 0


def action_records(kind, *, duplicate=False):
    from trading_bot.simulation.etf_capital_action_events import (
        CapitalDistributionEntitled,
        CapitalSplitApplied,
    )
    from trading_bot.simulation.etf_capital_daily_owner import CapitalDailyOriginalFact
    from trading_bot.simulation.events import EventCursor

    records = frames(3, hold=20)
    buy = run(records=records[:2]).events[0]
    opened = records[-1].projections[0].raw_bars[-1].starts_at
    identity = (
        "action",
        EventCursor(1000, opened - timedelta(seconds=1)),
        buy.request.order.account_id,
        buy.request.order.id,
        "IEF",
    )
    if kind == "split":
        event = CapitalSplitApplied(*identity, "split", "e" * 64, D(2), D("150.5"))
        mark = D("150.5")

        def adjusted(bar):
            return replace(
                bar, open=bar.open / 2, high=bar.high / 2, low=bar.low / 2, close=bar.close / 2
            )
    else:
        event = CapitalDistributionEntitled(
            *identity, "dividend", "f" * 64, D(2), D(299), opened.date() + timedelta(days=2)
        )
        mark = D(299)

        def adjusted(bar):
            return replace(
                bar, open=bar.open - 2, high=bar.high - 2, low=bar.low - 2, close=bar.close - 2
            )

    projected = tuple(
        replace(p, raw_bars=(*p.raw_bars[:-1], adjusted(p.raw_bars[-1])))
        for p in records[-1].projections
    )
    fact = CapitalDailyOriginalFact(event, mark)
    return (
        *records[:-1],
        replace(
            records[-1],
            projections=projected,
            original_facts=(fact, fact) if duplicate else (fact,),
        ),
    )


def test_split_scales_owned_quantity_basis_and_protection_once():
    value = run(records=action_records("split"))
    assert value.account.quantity == D(".132")
    assert value.account.average_price == D("150.075")
    assert value.points[-1].opening.stop_distance == D(2)
    assert value.account.cash == D("80.1801")
    assert value.points[-1].equity == D("100.0461")


def test_duplicate_split_does_not_rescale_owned_protection_twice():
    value = run(records=action_records("split", duplicate=True))
    assert value.account.quantity == D(".132")
    assert value.points[-1].opening.stop_distance == D(2)


def test_distribution_entitlement_is_nav_once_and_never_spendable_cash():
    value = run(records=action_records("distribution"))
    assert value.account.quantity == D(".066")
    assert value.account.distribution_receivable == D(".132")
    assert value.account.cash == D("80.1801")
    assert value.points[-1].equity == D("100.0461")
    assert value.points[-1].opening.stop_distance == D(4)


def test_duplicate_distribution_cannot_manufacture_receivable():
    value = run(records=action_records("distribution", duplicate=True))
    assert value.account.distribution_receivable == D(".132")
    assert value.points[-1].equity == D("100.0461")


def test_owned_action_trajectory_recovers_shared_joint_risk_from_originals(tmp_path):
    from pathlib import Path

    from trading_bot.persistence.etf_capital_checkpoint import advance_capital_joint_checkpoint

    value = run(records=action_records("split"))
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    arguments = dict(
        root=root,
        loaded=loaded(),
        initial_cash=D(100),
        events=value.events,
        observations=value.observations,
        code_hash="c" * 64,
        repository_root=Path(__file__).resolve().parents[3],
    )
    first = advance_capital_joint_checkpoint(**arguments, through_observation_count=2)
    final = advance_capital_joint_checkpoint(
        **arguments,
        through_observation_count=len(value.observations),
        expected_head=first.head_hash,
    )
    assert final.result == value.risk
    assert (
        advance_capital_joint_checkpoint(
            **arguments,
            through_observation_count=len(value.observations),
            expected_head=first.head_hash,
        )
        == final
    )
    # This certifies original account/risk reconstruction, not a growing live
    # journal or durable candidate/worker recovery.
    assert run(records=action_records("split")) == value


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_qualified", True),
        ("execution_enabled", True),
        ("economic_admitted", True),
        ("evidence_promotable", True),
        ("cost_qualified", True),
    ],
)
def test_owner_never_accepts_promotable_request_flags(field, value):
    from trading_bot.simulation.etf_capital_daily_owner import (
        CapitalDailyOwnerRequest,
        replay_capital_daily_owner,
    )

    request = CapitalDailyOwnerRequest(
        loaded(), D(100), frames(1), D(".1"), D(".01"), D(".02"), D(".10")
    )
    object.__setattr__(request, field, value)
    with pytest.raises(ValueError):
        replay_capital_daily_owner(request)


def test_declared_action_mark_conflict_fails_closed():
    records = action_records("distribution")
    fact = replace(records[-1].original_facts[0], mark=D(300))
    records = (*records[:-1], replace(records[-1], original_facts=(fact,)))
    with pytest.raises(ValueError):
        run(records=records)


def test_current_session_future_range_cannot_resize_prior_close_entry():
    records = frames(2)
    original = run(records=records)
    changed = tuple(
        replace(
            p,
            raw_bars=(*p.raw_bars[:-1], replace(p.raw_bars[-1], high=D(500), close=D(400))),
            feature_bars=(
                *p.feature_bars[:-1],
                replace(p.feature_bars[-1], high=D(500), close=D(400)),
            ),
        )
        for p in records[-1].projections
    )
    future = run(records=(*records[:-1], replace(records[-1], projections=changed)))
    assert future.events[:3] == original.events
    assert future.events[2].fill.quantity == D(".066")


def test_rejected_entry_cannot_invent_fill_or_fees():
    value = run(2, entry_outcome="rejected", entry_fill_fraction=D(0), entry_fee=D(0))
    assert len(value.events) == 2
    assert value.account.quantity == 0
    assert value.account.cash == D(100)
    assert value.account.fees == 0
    assert value.points[-1].opening is None


def test_missing_fee_bound_denies_entry_instead_of_relaxing_reserve():
    value = run(2, episode_fee_bound=None)
    assert value.events == ()
    assert value.account.cash == D(100)


def test_partial_exit_retains_remaining_position_and_pending_reservations():
    value = run(5, exit_outcome="partial", exit_fill_fraction=D(".5"))
    assert value.account.quantity == D(".033")
    assert value.account.cash == D("90.121117")
    assert value.account.unsettled_proceeds == D("9.941017")
    assert len(value.events) == 6
    assert not value.account.complete
    assert value.points[-1].opening.candidate.hold_sessions == 2


def test_unfilled_exit_cannot_be_resubmitted_while_pending():
    value = run(5, exit_outcome="unfilled", exit_fill_fraction=D(0), exit_fee=D(0))
    assert value.account.quantity == D(".066")
    assert value.account.cash == D("80.1801")
    assert len(value.events) == 5
    assert not value.account.complete
