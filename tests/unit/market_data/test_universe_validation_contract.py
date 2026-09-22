"""Synthetic boundary tests for strict point-in-time universe inputs."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from trading_bot.clock import DomainValidationError
from trading_bot.domain import InstrumentId
from trading_bot.market_data import PointInTimeUniverse, UniverseMembership

EFFECTIVE_AT = datetime(2035, 2, 10, 14, 30, tzinfo=UTC)
ANNOUNCED_AT = datetime(2035, 2, 5, 12, 0, tzinfo=UTC)


class DerivedId(str):
    pass


class DerivedTuple(tuple):
    pass


class DerivedMembership(UniverseMembership):
    pass


def membership(
    *,
    instrument_id: object = "SYNTH-ALPHA",
    effective_at: object = EFFECTIVE_AT,
    announced_at: object = ANNOUNCED_AT,
    included: object = True,
) -> UniverseMembership:
    """Call the public constructor while permitting deliberately invalid inputs."""
    return UniverseMembership(  # type: ignore[arg-type]
        instrument_id=instrument_id,
        effective_at=effective_at,
        announced_at=announced_at,
        included=included,
    )


@pytest.mark.parametrize(
    "instrument_id", ("", "   ", "\t\n", 7, None, b"SYNTH", DerivedId("SYNTH-ALPHA"))
)
def test_membership_rejects_instrument_ids_that_are_not_nonblank_exact_strings(
    instrument_id: object,
) -> None:
    with pytest.raises(DomainValidationError):
        membership(instrument_id=instrument_id)


@pytest.mark.parametrize(
    ("field_name", "invalid_timestamp"),
    (
        ("effective_at", datetime(2035, 2, 10, 14, 30)),
        ("effective_at", datetime(2035, 2, 10, 14, 30, tzinfo=timezone(timedelta(hours=1)))),
        ("effective_at", "2035-02-10T14:30:00Z"),
        ("announced_at", datetime(2035, 2, 5, 12, 0)),
        ("announced_at", datetime(2035, 2, 5, 12, 0, tzinfo=timezone(timedelta(hours=-5)))),
        ("announced_at", None),
    ),
)
def test_membership_rejects_timestamps_that_are_not_aware_utc_datetimes(
    field_name: str,
    invalid_timestamp: object,
) -> None:
    arguments = {field_name: invalid_timestamp}

    with pytest.raises(DomainValidationError):
        membership(**arguments)


@pytest.mark.parametrize("included", (0, 1, "true", None))
def test_membership_rejects_included_values_that_are_not_exact_booleans(
    included: object,
) -> None:
    with pytest.raises(DomainValidationError):
        membership(included=included)


@pytest.mark.parametrize(
    "memberships",
    (
        [],
        [membership()],
        ("not-a-membership",),
        (object(),),
        DerivedTuple((membership(),)),
        (DerivedMembership(InstrumentId("SYNTH-ALPHA"), EFFECTIVE_AT, ANNOUNCED_AT, True),),
    ),
)
def test_universe_rejects_non_tuple_or_non_membership_collections(
    memberships: object,
) -> None:
    with pytest.raises(DomainValidationError):
        PointInTimeUniverse(memberships, history_complete=True)  # type: ignore[arg-type]


@pytest.mark.parametrize("history_complete", (0, 1, "false", None))
def test_universe_rejects_history_complete_values_that_are_not_exact_booleans(
    history_complete: object,
) -> None:
    with pytest.raises(DomainValidationError):
        PointInTimeUniverse((), history_complete=history_complete)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "as_of",
    (
        datetime(2035, 2, 10, 14, 30),
        datetime(2035, 2, 10, 14, 30, tzinfo=timezone(timedelta(minutes=30))),
        "2035-02-10T14:30:00Z",
        None,
    ),
)
@pytest.mark.parametrize("memberships", ((), (membership(),)))
def test_lookup_rejects_non_utc_as_of_even_for_an_empty_universe(
    memberships: tuple[UniverseMembership, ...],
    as_of: object,
) -> None:
    universe = PointInTimeUniverse(memberships, history_complete=True)

    with pytest.raises(DomainValidationError):
        universe.members_at(as_of)  # type: ignore[arg-type]


@pytest.mark.parametrize("reverse_order", (False, True))
def test_universe_rejects_contradictory_duplicate_events_in_either_order(
    reverse_order: bool,
) -> None:
    included = membership(
        effective_at=datetime(2040, 1, 10, 14, 30, tzinfo=UTC),
        announced_at=datetime(2040, 1, 5, 12, 0, tzinfo=UTC),
        included=True,
    )
    excluded = membership(
        effective_at=datetime(2040, 1, 10, 14, 30, tzinfo=UTC),
        announced_at=datetime(2040, 1, 5, 12, 0, tzinfo=UTC),
        included=False,
    )
    events = (excluded, included) if reverse_order else (included, excluded)

    with pytest.raises(DomainValidationError):
        PointInTimeUniverse(events, history_complete=True)


def test_identical_duplicates_remain_allowed() -> None:
    duplicate = membership()
    universe = PointInTimeUniverse((duplicate, duplicate), history_complete=True)

    assert universe.members_at(datetime(2035, 2, 10, 14, 30, tzinfo=UTC)) == (
        InstrumentId("SYNTH-ALPHA"),
    )


def test_distinct_timestamps_and_late_announcements_remain_valid_and_order_invariant() -> None:
    initial = membership(
        instrument_id=" SYNTH-mixed ",
        effective_at=datetime(2035, 2, 10, 14, 30, tzinfo=UTC),
        announced_at=datetime(2035, 2, 5, 12, 0, tzinfo=UTC),
        included=True,
    )
    late = membership(
        instrument_id="SYNTH-BETA",
        effective_at=datetime(2035, 2, 8, 14, 30, tzinfo=UTC),
        announced_at=datetime(2035, 2, 12, 12, 0, tzinfo=UTC),
        included=True,
    )
    removal = membership(
        instrument_id=" SYNTH-mixed ",
        effective_at=datetime(2035, 2, 15, 14, 30, tzinfo=UTC),
        announced_at=datetime(2035, 2, 13, 12, 0, tzinfo=UTC),
        included=False,
    )
    chronological = PointInTimeUniverse((initial, late, removal), history_complete=False)
    reordered = PointInTimeUniverse((removal, initial, late), history_complete=False)

    before_late_announcement = datetime(2035, 2, 12, 11, 59, 59, tzinfo=UTC)
    at_late_announcement = datetime(2035, 2, 12, 12, 0, tzinfo=UTC)
    at_removal = datetime(2035, 2, 15, 14, 30, tzinfo=UTC)
    assert chronological.members_at(before_late_announcement) == (InstrumentId(" SYNTH-mixed "),)
    assert chronological.members_at(at_late_announcement) == (
        InstrumentId(" SYNTH-mixed "),
        InstrumentId("SYNTH-BETA"),
    )
    assert chronological.members_at(at_removal) == (InstrumentId("SYNTH-BETA"),)
    assert reordered.members_at(at_late_announcement) == (
        InstrumentId(" SYNTH-mixed "),
        InstrumentId("SYNTH-BETA"),
    )
    assert chronological.eligibility_reasons == ("point_in_time_universe_unavailable",)
    assert reordered.eligibility_reasons == ("point_in_time_universe_unavailable",)


def test_complete_empty_universe_keeps_valid_boundary_behavior() -> None:
    universe = PointInTimeUniverse((), history_complete=True)

    assert universe.members_at(datetime(2035, 2, 10, 14, 30, tzinfo=UTC)) == ()
    assert universe.eligibility_reasons == ()
