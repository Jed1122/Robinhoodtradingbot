from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from tests.unit.domain.test_options import NOW, contract
from trading_bot.domain.options import OptionSession, SettlementKind
from trading_bot.lifecycle.options_expiry import OptionExpiryCalendar, assess_option_expiry


def calendar(**changes):
    return replace(
        OptionExpiryCalendar(
            contract().contract_id,
            date(2026, 10, 15),
            date(2026, 10, 16),
            (
                OptionSession(
                    "thu",
                    datetime(2026, 10, 15, 13, 30, tzinfo=UTC),
                    datetime(2026, 10, 15, 20, tzinfo=UTC),
                    date(2026, 10, 15),
                    "America/New_York",
                ),
                OptionSession(
                    "fri",
                    datetime(2026, 10, 16, 13, 30, tzinfo=UTC),
                    datetime(2026, 10, 16, 20, tzinfo=UTC),
                    date(2026, 10, 16),
                    "America/New_York",
                ),
            ),
            True,
            NOW,
            "b" * 64,
        ),
        **changes,
    )


def assess(**changes):
    args = dict(contract=contract(), calendar=calendar(), as_of=NOW, has_exposure=True)
    args.update(changes)
    return assess_option_expiry(**args)


def test_deadline_is_previous_eligible_session_not_calendar_day():
    result = assess()
    assert result.exit_deadline == datetime(2026, 10, 15, 20, tzinfo=UTC)
    assert not result.action_required and result.reasons == ()
    assert assess(as_of=calendar().sessions[0].opens_at).reasons == ("expiry_exit_session",)
    assert assess(as_of=result.exit_deadline).reasons == ("expiry_exit_deadline_reached",)


def test_weekend_and_early_close_use_supplied_complete_exchange_sessions():
    c = contract(expiration=date(2026, 10, 17))
    cal = calendar(
        coverage_end=date(2026, 10, 17),
        sessions=(
            replace(calendar().sessions[0], closes_at=datetime(2026, 10, 15, 17, tzinfo=UTC)),
            calendar().sessions[1],
        ),
    )
    assert assess(contract=c, calendar=cal).exit_deadline == datetime(2026, 10, 15, 17, tzinfo=UTC)


@pytest.mark.parametrize(
    "changes",
    [
        dict(complete=False),
        dict(contract_id="other"),
        dict(known_at=NOW + timedelta(seconds=1)),
        dict(sessions=(calendar().sessions[1],)),
        dict(coverage_end=date(2026, 10, 15), sessions=(calendar().sessions[0],)),
    ],
)
def test_missing_partial_future_or_wrong_calendar_cannot_clear_exposure(changes):
    result = assess(calendar=calendar(**changes))
    assert result.action_required and result.exit_deadline is None
    assert "expiry_calendar_unverified" in result.reasons
    assert assess(calendar=None).reasons == ("expiry_calendar_unverified",)


def test_calendar_conflicts_with_contract_sessions():
    c = contract(eligible_sessions=(replace(calendar().sessions[1], session_id="conflict"),))
    assert assess(contract=c).reasons == ("expiry_calendar_unverified",)


def test_cash_settlement_is_explicitly_unsupported_not_assumed_safe():
    c = contract(settlement_kind=SettlementKind.CASH, deliverable_units=Decimal("0"))
    assert assess(contract=c).reasons == ("cash_settlement_policy_unverified",)


def test_stricter_deadline_cannot_be_extended_and_deadlines_do_not_flatten_positions():
    strict = datetime(2026, 10, 14, 18, tzinfo=UTC)
    assert assess(strategy_deadline=strict).exit_deadline == strict
    assert "expiry_exit_deadline_reached" in assess(strategy_deadline=strict, as_of=strict).reasons
    with pytest.raises(ValueError):
        assess(strategy_deadline=datetime(2026, 10, 16, 20, tzinfo=UTC))
    result = assess(as_of=contract().settlement_at)
    assert result.action_required
    assert {
        "expiry_exit_deadline_reached",
        "last_trading_cutoff_reached",
        "settlement_reconciliation_required",
    } <= set(result.reasons)
    assert assess(has_exposure=False, calendar=None).reasons == ()


@pytest.mark.parametrize(
    "changes",
    [
        dict(complete=1),
        dict(evidence_hash="bad"),
        dict(sessions=list(calendar().sessions)),
        dict(coverage_start=datetime(2026, 10, 15, tzinfo=UTC)),
        dict(sessions=(calendar().sessions[1], calendar().sessions[0])),
        dict(sessions=(calendar().sessions[0], calendar().sessions[0])),
    ],
)
def test_calendar_is_strict_and_immutable(changes):
    with pytest.raises(ValueError):
        calendar(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        dict(has_exposure=1),
        dict(as_of=NOW.replace(tzinfo=None)),
        dict(contract=None),
        dict(calendar={}),
    ],
)
def test_assessment_boundaries_are_strict(changes):
    with pytest.raises(ValueError):
        assess(**changes)


def test_calendar_empty_or_missing_terminal_session_requires_evidence():
    assert assess(calendar=calendar(sessions=())).reasons == ("expiry_calendar_unverified",)
    assert assess(calendar=calendar(sessions=(calendar().sessions[0],))).reasons == (
        "expiry_calendar_unverified",
    )
    for changes in (
        dict(coverage_start=date(2026, 10, 17)),
        dict(coverage_start=date(2026, 10, 16)),
    ):
        with pytest.raises(ValueError):
            calendar(**changes)


def test_dst_weekend_does_not_move_prior_session_deadline_by_an_hour():
    sessions = (
        OptionSession(
            "fri-before-dst",
            datetime(2026, 10, 30, 13, 30, tzinfo=UTC),
            datetime(2026, 10, 30, 20, tzinfo=UTC),
            date(2026, 10, 30),
            "America/New_York",
        ),
        OptionSession(
            "mon-after-dst",
            datetime(2026, 11, 2, 14, 30, tzinfo=UTC),
            datetime(2026, 11, 2, 21, tzinfo=UTC),
            date(2026, 11, 2),
            "America/New_York",
        ),
    )
    c = contract(
        expiration=date(2026, 11, 2),
        last_trading_at=sessions[1].closes_at,
        settlement_at=datetime(2026, 11, 3, 21, tzinfo=UTC),
    )
    cal = calendar(
        coverage_start=date(2026, 10, 30), coverage_end=date(2026, 11, 2), sessions=sessions
    )
    assert assess(contract=c, calendar=cal).exit_deadline == datetime(2026, 10, 30, 20, tzinfo=UTC)
