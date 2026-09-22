"""Primary regression cases for ambiguous or malformed membership inputs."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from trading_bot.clock import DomainValidationError
from trading_bot.domain import InstrumentId
from trading_bot.market_data.universe import PointInTimeUniverse, UniverseMembership

AT = datetime(2026, 1, 5, tzinfo=UTC)


def membership() -> UniverseMembership:
    return UniverseMembership(InstrumentId("SYNTH-ALPHA"), AT, AT, True)


@pytest.mark.parametrize("reverse", [False, True])
def test_conflicting_membership_cannot_depend_on_input_order(reverse: bool) -> None:
    added = membership()
    records = (added, replace(added, included=False))
    with pytest.raises(DomainValidationError):
        PointInTimeUniverse(records[::-1] if reverse else records, history_complete=True)


@pytest.mark.parametrize("field", ["effective_at", "announced_at"])
@pytest.mark.parametrize(
    "at", [AT.replace(tzinfo=None), AT.astimezone(timezone(timedelta(hours=1)))]
)
def test_membership_rejects_non_utc_times(field: str, at: datetime) -> None:
    with pytest.raises(DomainValidationError):
        replace(membership(), **{field: at})


def test_empty_universe_still_rejects_naive_lookup() -> None:
    universe = PointInTimeUniverse((), history_complete=True)
    with pytest.raises(DomainValidationError):
        universe.members_at(AT.replace(tzinfo=None))


def test_identical_duplicates_and_late_announcements_remain_visible_at_boundary() -> None:
    record = replace(membership(), announced_at=AT + timedelta(days=1))
    universe = PointInTimeUniverse((record, record), history_complete=False)
    assert universe.members_at(AT) == ()
    assert universe.members_at(AT + timedelta(days=1)) == ("SYNTH-ALPHA",)
    assert universe.eligibility_reasons == ("point_in_time_universe_unavailable",)


def test_truthy_history_mutation_cannot_remove_eligibility_reason() -> None:
    universe = PointInTimeUniverse((), history_complete=False)
    universe.history_complete = "false"  # type: ignore[assignment]
    with pytest.raises(DomainValidationError):
        _ = universe.eligibility_reasons


@pytest.mark.parametrize("field", ["effective_at", "announced_at"])
def test_opposite_inclusion_with_only_one_distinct_timestamp_is_not_a_conflict(field: str) -> None:
    added = membership()
    later = AT + timedelta(days=1)
    removed = replace(added, included=False, **{field: later})
    for records in ((added, removed), (removed, added)):
        universe = PointInTimeUniverse(records, history_complete=True)
        assert universe.members_at(AT) == ("SYNTH-ALPHA",)
        assert universe.members_at(later) == ()
