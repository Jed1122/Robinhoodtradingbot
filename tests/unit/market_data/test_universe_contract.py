"""Deterministic contract tests for point-in-time universe membership."""

from datetime import UTC, datetime

import pytest

from trading_bot.domain import InstrumentId
from trading_bot.market_data import PointInTimeUniverse, UniverseMembership

ALPHA = InstrumentId("SYNTH-ALPHA")
BETA = InstrumentId("SYNTH-BETA")
GAMMA = InstrumentId("SYNTH-GAMMA")

MEMBERSHIPS = (
    UniverseMembership(
        instrument_id=ALPHA,
        announced_at=datetime(2024, 1, 5, 12, 0, tzinfo=UTC),
        effective_at=datetime(2024, 1, 10, 14, 30, tzinfo=UTC),
        included=True,
    ),
    # This event is effective before it is announced and must remain invisible
    # until the announcement timestamp.
    UniverseMembership(
        instrument_id=BETA,
        announced_at=datetime(2024, 1, 12, 14, 30, tzinfo=UTC),
        effective_at=datetime(2024, 1, 8, 14, 30, tzinfo=UTC),
        included=True,
    ),
    UniverseMembership(
        instrument_id=GAMMA,
        announced_at=datetime(2024, 1, 10, 14, 30, tzinfo=UTC),
        effective_at=datetime(2024, 1, 10, 14, 30, tzinfo=UTC),
        included=True,
    ),
    UniverseMembership(
        instrument_id=ALPHA,
        announced_at=datetime(2024, 1, 13, 14, 30, tzinfo=UTC),
        effective_at=datetime(2024, 1, 15, 14, 30, tzinfo=UTC),
        included=False,
    ),
    UniverseMembership(
        instrument_id=ALPHA,
        announced_at=datetime(2024, 1, 18, 14, 30, tzinfo=UTC),
        effective_at=datetime(2024, 1, 20, 14, 30, tzinfo=UTC),
        included=True,
    ),
)


@pytest.mark.parametrize(
    ("as_of", "expected"),
    (
        (datetime(2024, 1, 5, 11, 59, 59, tzinfo=UTC), ()),
        (datetime(2024, 1, 5, 12, 0, tzinfo=UTC), ()),
        (datetime(2024, 1, 8, 14, 30, tzinfo=UTC), ()),
        (datetime(2024, 1, 10, 14, 29, 59, tzinfo=UTC), ()),
        (datetime(2024, 1, 10, 14, 30, tzinfo=UTC), (ALPHA, GAMMA)),
        (datetime(2024, 1, 12, 14, 29, 59, tzinfo=UTC), (ALPHA, GAMMA)),
        (datetime(2024, 1, 12, 14, 30, tzinfo=UTC), (ALPHA, BETA, GAMMA)),
        (datetime(2024, 1, 15, 14, 29, 59, tzinfo=UTC), (ALPHA, BETA, GAMMA)),
        (datetime(2024, 1, 15, 14, 30, tzinfo=UTC), (BETA, GAMMA)),
        (datetime(2024, 1, 18, 14, 30, tzinfo=UTC), (BETA, GAMMA)),
        (datetime(2024, 1, 20, 14, 30, tzinfo=UTC), (ALPHA, BETA, GAMMA)),
        (datetime(2024, 1, 21, 0, 0, tzinfo=UTC), (ALPHA, BETA, GAMMA)),
    ),
)
def test_membership_boundaries_removal_reentry_and_late_announcement(
    as_of: datetime, expected: tuple[InstrumentId, ...]
) -> None:
    universe = PointInTimeUniverse(MEMBERSHIPS, history_complete=True)

    assert universe.members_at(as_of) == expected
    assert universe.members_at(as_of) == expected


def test_distinct_time_input_reordering_does_not_change_sorted_results() -> None:
    chronological = PointInTimeUniverse(MEMBERSHIPS, history_complete=True)
    reordered = PointInTimeUniverse(
        (MEMBERSHIPS[4], MEMBERSHIPS[2], MEMBERSHIPS[0], MEMBERSHIPS[3], MEMBERSHIPS[1]),
        history_complete=True,
    )
    as_of = datetime(2024, 1, 20, 14, 30, tzinfo=UTC)

    assert chronological.members_at(as_of) == (ALPHA, BETA, GAMMA)
    assert reordered.members_at(as_of) == (ALPHA, BETA, GAMMA)


def test_independent_instrument_removal_does_not_change_other_members() -> None:
    universe = PointInTimeUniverse(MEMBERSHIPS, history_complete=True)

    assert universe.members_at(datetime(2024, 1, 15, 14, 30, tzinfo=UTC)) == (BETA, GAMMA)


def test_empty_complete_history_has_no_members_and_no_ineligibility_reason() -> None:
    universe = PointInTimeUniverse((), history_complete=True)
    as_of = datetime(2024, 6, 1, 0, 0, tzinfo=UTC)

    assert universe.members_at(as_of) == ()
    assert universe.members_at(as_of) == ()
    assert universe.eligibility_reasons == ()


def test_empty_incomplete_history_is_explicitly_ineligible() -> None:
    universe = PointInTimeUniverse((), history_complete=False)

    assert universe.members_at(datetime(2024, 6, 1, 0, 0, tzinfo=UTC)) == ()
    assert universe.eligibility_reasons == ("point_in_time_universe_unavailable",)
