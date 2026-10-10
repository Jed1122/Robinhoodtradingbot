"""Owned daily instructions through shared reducers; fabricated prices only."""

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from tests.unit.research.test_etf_capital_feasibility import instrument, loaded
from tests.unit.research.test_etf_capital_signals import projections
from trading_bot.domain import InstrumentId
from trading_bot.research.etf_capital_signals import CapitalCandidate


def calendar():
    from trading_bot.market_data.etf_calendar import EtfCalendarArchive, EtfCalendarSession

    zone = ZoneInfo("America/New_York")
    day = date(2019, 1, 1)
    sessions = []
    while len(sessions) < 220:
        if day.weekday() < 5:
            sessions.append(
                EtfCalendarSession(
                    day,
                    datetime.combine(day, time(9, 30), zone).astimezone(UTC),
                    datetime.combine(day, time(16), zone).astimezone(UTC),
                )
            )
        day += timedelta(days=1)
    return EtfCalendarArchive("c" * 64, tuple(sessions))


def frames(count=4, *, hold=2):
    from trading_bot.simulation.etf_capital_daily_owner import CapitalDailyFrame

    result = []
    declared = calendar()
    for index in range(count):
        records = projections(tuple(D(100 + i) for i in range(200 + index)))
        records = tuple(
            replace(
                p,
                as_of_session=declared.sessions[199 + index].session_date,
                calendar_hash=declared.archive_hash,
                raw_bars=tuple(
                    replace(b, starts_at=s.opens_at, ends_at=s.closes_at)
                    for b, s in zip(p.raw_bars, declared.sessions, strict=False)
                ),
                feature_bars=tuple(
                    replace(b, starts_at=s.opens_at, ends_at=s.closes_at)
                    for b, s in zip(p.feature_bars, declared.sessions, strict=False)
                ),
            )
            for p in records
        )
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
        loaded(),
        D("100"),
        records or frames(count),
        D(".10"),
        D(".01"),
        D(".02"),
        D(".10"),
        calendar(),
    )
    return replay_capital_daily_owner(replace(value, **changes))


def test_first_close_instruction_cannot_trade_at_its_own_open():
    value = run(1)
    assert value.events == ()
    assert value.account.cash == D("100")
    assert value.points[0].policy.action == "entry"
    assert value.points[0].opening is None


def test_purged_close_cannot_schedule_a_new_entry():
    records = frames(2)
    records = tuple(replace(f, entry_decision_allowed=False) for f in records)
    value = run(records=records)
    assert value.events == ()
    assert value.points[0].policy.action == "wait"
    assert value.points[0].policy.reason == "entry_decision_disabled"


def test_last_valid_training_decision_can_fill_in_exit_only_decision_tail():
    records = frames(2)
    value = run(records=(records[0], replace(records[1], entry_decision_allowed=False)))
    assert value.account.quantity == D(".066")
    assert value.points[-1].opening is not None


def test_disabled_submission_does_not_delay_old_instruction_to_later_open():
    records = frames(3)
    value = run(
        records=(
            records[0],
            replace(records[1], entry_submission_allowed=False, entry_decision_allowed=False),
            replace(records[2], entry_decision_allowed=False),
        )
    )
    assert value.events == ()
    assert value.account.cash == D(100)


def test_exit_only_tail_keeps_holding_deadline_and_next_open_exit_active():
    records = frames(4)
    value = run(
        records=(
            *records[:2],
            *(
                replace(f, entry_submission_allowed=False, entry_decision_allowed=False)
                for f in records[2:]
            ),
        )
    )
    assert value.points[2].policy.reason == "maximum_hold"
    assert value.account.quantity == 0
    assert value.account.cash == D("100.082134")
    assert not value.account.complete


@pytest.mark.parametrize("field", ("entry_decision_allowed", "entry_submission_allowed"))
@pytest.mark.parametrize("invalid", (None, 0, 1, D(1), "true"))
def test_entry_cutoffs_require_real_bools(field, invalid):
    records = frames(1)
    with pytest.raises(ValueError):
        run(records=(replace(records[0], **{field: invalid}),))


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


def test_no_trade_owner_materializes_only_final_complete_risk_identity(monkeypatch):
    from trading_bot.simulation import etf_capital_risk

    original = etf_capital_risk._risk_result
    observations_hashed = []

    def record(*args, **kwargs):
        observations_hashed.append(len(args[3]))
        return original(*args, **kwargs)

    monkeypatch.setattr(etf_capital_risk, "_risk_result", record)
    records = tuple(replace(f, entry_decision_allowed=False) for f in frames(3))
    value = run(records=records)
    assert value.events == ()
    assert observations_hashed == [6]
    # Expectation comes from the independent public reconstruction of originals,
    # not an owner-supplied account or latch snapshot.
    assert value.risk == etf_capital_risk.replay_capital_action_risk(
        loaded=loaded(), initial_cash=D(100), events=value.events, observations=value.observations
    )


def test_v5_owner_binds_calendar_and_ordered_complete_frames_without_aliasing_v3():
    from trading_bot.market_data.recording import content_hash
    from trading_bot.simulation.etf_capital_daily_owner import (
        CapitalDailyOwnerRequest,
        replay_capital_daily_owner,
    )

    request = CapitalDailyOwnerRequest(
        loaded(), D(100), frames(1), D(".10"), D(".01"), D(".02"), D(".10"), calendar()
    )
    value = replay_capital_daily_owner(request)
    assert value.input_hash == content_hash(
        (
            "capital-daily-owner-v5",
            request.loaded.config_hash,
            request.calendar.archive_hash,
            D(100),
            tuple(content_hash(("capital-daily-owner-frame-v1", f)) for f in request.frames),
            D(".10"),
            D(".01"),
            D(".02"),
            D(".10"),
            "filled",
            D(1),
            "filled",
            D(1),
        )
    )
    assert value.input_hash != "daa7634397798cdf8f2fac637dae1c30a930bf84f4b46adc19b4511ed1794183"


@pytest.mark.parametrize(
    "change",
    ("bar_hash", "instrument_metadata", "projection_order", "instrument_order", "reset", "denial"),
)
def test_no_economic_effect_original_fields_remain_identity_bound(change):
    frame = frames(1)[0]
    baseline = run(records=(frame,))
    if change == "bar_hash":
        projection = frame.projections[0]
        feature = replace(projection.feature_bars[0], data_hash="b" * 64)
        changed = replace(projection, feature_bars=(feature, *projection.feature_bars[1:]))
        frame = replace(frame, projections=(changed, *frame.projections[1:]))
    elif change == "instrument_metadata":
        instrument = replace(frame.instruments[0], provider_status="different-assumption")
        frame = replace(frame, instruments=(instrument, *frame.instruments[1:]))
    elif change == "projection_order":
        frame = replace(frame, projections=tuple(reversed(frame.projections)))
    elif change == "instrument_order":
        frame = replace(frame, instruments=tuple(reversed(frame.instruments)))
    elif change == "reset":
        frame = replace(frame, daily_reset_reconciled=False)
    else:
        frame = replace(frame, entry_submission_allowed=False)
    changed_result = run(records=(frame,))
    assert changed_result.account == baseline.account
    assert changed_result.input_hash != baseline.input_hash


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
        replace(
            p,
            raw_bars=(*p.raw_bars[:-1], replace(p.raw_bars[-1], high=D(310), low=D(295))),
            feature_bars=(
                *p.feature_bars[:-1],
                replace(p.feature_bars[-1], high=D(310), low=D(295)),
            ),
        )
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
        replace(
            p,
            raw_bars=(*p.raw_bars[:-1], replace(p.raw_bars[-1], open=D(290), low=D(289))),
            feature_bars=(
                *p.feature_bars[:-1],
                replace(p.feature_bars[-1], open=D(290), low=D(289)),
            ),
        )
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
        replace(
            p,
            raw_bars=(*p.raw_bars[:-1], adjusted(p.raw_bars[-1]))
            if str(p.raw_bars[-1].instrument_id) == "IEF"
            else p.raw_bars,
            feature_bars=(
                *tuple(replace(adjusted(b), volume=b.volume * 2) for b in p.feature_bars[:-1]),
                adjusted(p.feature_bars[-1]),
            )
            if kind == "split" and str(p.raw_bars[-1].instrument_id) == "IEF"
            else (*p.feature_bars[:-1], adjusted(p.feature_bars[-1]))
            if str(p.raw_bars[-1].instrument_id) == "IEF"
            else p.feature_bars,
        )
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
        loaded(), D(100), frames(1), D(".1"), D(".01"), D(".02"), D(".10"), calendar()
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


def test_later_history_cannot_erase_owned_session_and_extend_holding_limit():
    records = frames(7, hold=5)
    altered = tuple(
        replace(
            frame,
            projections=tuple(
                replace(
                    p,
                    raw_bars=(*p.raw_bars[:201], *p.raw_bars[202:]),
                    feature_bars=(*p.feature_bars[:201], *p.feature_bars[202:]),
                )
                for p in frame.projections
            ),
        )
        if index >= 3
        else frame
        for index, frame in enumerate(records)
    )
    with pytest.raises(ValueError):
        run(records=altered)


def test_later_projection_cannot_rewrite_owned_raw_execution_history():
    records = frames(3)
    altered = tuple(
        replace(p, raw_bars=(replace(p.raw_bars[0], volume=D(2000)), *p.raw_bars[1:]))
        for p in records[-1].projections
    )
    records = (*records[:-1], replace(records[-1], projections=altered))
    with pytest.raises(ValueError):
        run(records=records)


def test_owner_cannot_skip_unprocessed_session_ranges():
    records = frames(4, hold=20)
    with pytest.raises(ValueError):
        run(records=(records[0], records[1], records[3]))


def test_raw_history_continuity_allows_declared_split_feature_rebasing():
    records = action_records("split")
    value = run(records=records)
    assert value.account.quantity == D(".132")
    assert value.points[-1].opening.stop_distance == D(2)
    assert value.points[-1].equity == D("100.0461")


@pytest.mark.parametrize("symbol", ("IEF", "SPY"))
def test_split_does_not_authorize_wrong_factor_or_unrelated_symbol_rewrite(symbol):
    records = action_records("split")
    changed = tuple(
        replace(p, feature_bars=(replace(p.feature_bars[0], volume=D(3000)), *p.feature_bars[1:]))
        if str(p.raw_bars[-1].instrument_id) == symbol
        else p
        for p in records[-1].projections
    )
    with pytest.raises(ValueError):
        run(records=(*records[:-1], replace(records[-1], projections=changed)))


def test_undeclared_feature_history_rewrite_denies_before_following_signal():
    records = frames(2)
    changed = tuple(
        replace(p, feature_bars=(replace(p.feature_bars[0], close=D(99)), *p.feature_bars[1:]))
        for p in records[-1].projections
    )
    with pytest.raises(ValueError):
        run(records=(records[0], replace(records[-1], projections=changed)))


def test_flat_overnight_split_rebase_cannot_use_pending_pre_split_stop():
    records = frames(2)
    changed = tuple(
        replace(
            p,
            feature_bars=tuple(
                replace(
                    b,
                    open=b.open / 2,
                    high=b.high / 2,
                    low=b.low / 2,
                    close=b.close / 2,
                    volume=b.volume * 2,
                )
                for b in p.feature_bars
            ),
        )
        for p in records[-1].projections
    )
    with pytest.raises(ValueError):
        run(records=(records[0], replace(records[-1], projections=changed)))


def test_flat_rejected_episode_split_cannot_authorize_pending_feature_rebase():
    from trading_bot.simulation.etf_capital_account import CapitalEpisodeFeesFinal
    from trading_bot.simulation.etf_capital_daily_owner import CapitalDailyOriginalFact
    from trading_bot.simulation.events import EventCursor

    records = action_records("split")
    rejected = run(
        records=records[:2], entry_outcome="rejected", entry_fill_fraction=D(0), entry_fee=D(0)
    )
    assert rejected.account.quantity == 0 and not rejected.account.complete
    buy = rejected.events[0].request.order
    opened = records[-1].projections[0].raw_bars[-1].starts_at
    split = replace(
        records[-1].original_facts[0].event,
        cursor=EventCursor(1000, opened - timedelta(seconds=2)),
        account_id=buy.account_id,
        opening_order_id=buy.id,
    )
    final = CapitalEpisodeFeesFinal(
        "flat-final", EventCursor(1002, opened - timedelta(seconds=1)), D(0), buy.account_id, buy.id
    )
    records = (
        *records[:-1],
        replace(
            records[-1],
            original_facts=(
                CapitalDailyOriginalFact(split, None),
                CapitalDailyOriginalFact(final, None),
            ),
        ),
    )
    with pytest.raises(ValueError):
        run(records=records, entry_outcome="rejected", entry_fill_fraction=D(0), entry_fee=D(0))


def test_original_fill_before_split_in_same_frame_establishes_held_frontier():
    from trading_bot.simulation.etf_capital_daily_owner import CapitalDailyOriginalFact
    from trading_bot.simulation.events import EventCursor
    from trading_bot.simulation.lifecycle_models import LifecycleFillEvent

    records = action_records("split")
    filled = run(records=records[:2])
    fill = next(event for event in filled.events if type(event) is LifecycleFillEvent)
    unfilled = run(
        records=records[:2], entry_outcome="unfilled", entry_fill_fraction=D(0), entry_fee=D(0)
    )
    buy = unfilled.events[0].request.order
    opened = records[-1].projections[0].raw_bars[-1].starts_at
    fill = replace(
        fill,
        cursor=EventCursor(999, opened - timedelta(seconds=2)),
        fill=replace(
            fill.fill,
            broker_order_id=buy.broker_order_id,
            fee=D(0),
            occurred_at=opened - timedelta(seconds=2),
        ),
    )
    last = replace(
        records[-1],
        original_facts=(
            CapitalDailyOriginalFact(fill, D(301)),
            replace(
                records[-1].original_facts[0],
                event=replace(records[-1].original_facts[0].event, opening_order_id=buy.id),
            ),
        ),
    )
    value = run(
        records=(*records[:-1], last),
        entry_outcome="unfilled",
        entry_fill_fraction=D(0),
        entry_fee=D(0),
    )
    assert value.account.quantity == D(".132")
    assert value.account.average_price == D("150.075")
    assert value.account.cash == D("80.1901")
    assert value.points[-1].opening.stop_distance == D(2)


@pytest.mark.parametrize("change", ("remove", "amount", "record", "backdated_addition"))
def test_later_distribution_projection_cannot_revise_prior_asof_facts(change):
    from trading_bot.market_data.etf_capital_actions import CapitalDistribution

    records = frames(2)
    first_date = records[0].projections[0].as_of_session
    old_date = first_date - timedelta(days=2)
    original = CapitalDistribution(old_date, old_date, old_date, D(1), "a" * 64)
    rows = (original,)
    changed = (
        ()
        if change == "remove"
        else (
            (replace(original, amount_per_share=D(2)),)
            if change == "amount"
            else (replace(original, record_hash="f" * 64),)
            if change == "record"
            else (
                original,
                replace(
                    original,
                    ex_date=first_date,
                    record_date=first_date,
                    pay_date=first_date,
                    record_hash="f" * 64,
                ),
            )
        )
    )
    records = tuple(
        replace(
            frame,
            entry_decision_allowed=False,
            projections=tuple(
                replace(p, distributions=rows if i == 0 else changed) for p in frame.projections
            ),
        )
        for i, frame in enumerate(records)
    )
    with pytest.raises(ValueError):
        run(records=records)


def test_new_current_session_distribution_extends_original_history_without_rewriting():
    from trading_bot.market_data.etf_capital_actions import CapitalDistribution

    records = frames(2)
    first_date = records[0].projections[0].as_of_session
    next_date = records[1].projections[0].as_of_session
    old = CapitalDistribution(first_date, first_date, first_date, D(1), "a" * 64)
    new = CapitalDistribution(next_date, next_date, next_date, D(2), "b" * 64)
    records = tuple(
        replace(
            frame,
            entry_decision_allowed=False,
            projections=tuple(
                replace(p, distributions=(old,) if i == 0 else (old, new))
                for p in frame.projections
            ),
        )
        for i, frame in enumerate(records)
    )
    value = run(records=records)
    assert value.account.cash == D(100) and value.events == ()


def test_as_of_feature_hash_regeneration_does_not_rewrite_economic_history():
    from trading_bot.domain import DataHash

    records = frames(2)
    changed = tuple(
        replace(
            p, feature_bars=tuple(replace(b, data_hash=DataHash("f" * 64)) for b in p.feature_bars)
        )
        for p in records[-1].projections
    )
    value = run(records=(records[0], replace(records[-1], projections=changed)))
    assert value.account.quantity == D(".066")
    assert value.account.cash == D("80.1801")


@pytest.mark.parametrize("kind", ("split", "distribution"))
def test_original_action_exactly_at_open_coalesces_its_mark_and_resets(kind):
    records = action_records(kind)
    frame = records[-1]
    fact = frame.original_facts[0]
    fact = replace(
        fact,
        event=replace(
            fact.event,
            cursor=replace(
                fact.event.cursor, occurred_at=frame.projections[0].raw_bars[-1].starts_at
            ),
        ),
    )
    value = run(records=(*records[:-1], replace(frame, original_facts=(fact,))))
    assert value.points[-1].equity == D("100.0461")
    assert value.account.cash == D("80.1801")
    assert value.account.quantity == (D(".132") if kind == "split" else D(".066"))
    at = fact.event.cursor.occurred_at
    assert len([o for o in value.observations if o.cursor.occurred_at == at]) == 1
