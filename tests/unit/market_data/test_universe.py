from datetime import UTC, datetime, timedelta

from trading_bot.domain import InstrumentId
from trading_bot.market_data import PointInTimeUniverse, UniverseMembership

NOW = datetime(2026, 7, 17, tzinfo=UTC)


def test_membership_cannot_be_seen_before_announcement_or_effective_time() -> None:
    membership = UniverseMembership(InstrumentId("AAPL"), NOW, NOW - timedelta(days=1), True)
    universe = PointInTimeUniverse((membership,), history_complete=True)
    assert universe.members_at(NOW - timedelta(seconds=1)) == ()
    assert universe.members_at(NOW) == (InstrumentId("AAPL"),)


def test_missing_history_is_explicitly_ineligible() -> None:
    assert PointInTimeUniverse((), history_complete=False).eligibility_reasons == (
        "point_in_time_universe_unavailable",
    )
