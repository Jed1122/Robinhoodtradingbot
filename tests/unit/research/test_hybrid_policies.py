from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading_bot.research.hybrid_policies import (
    CalendarSession,
    EventKind,
    PolicyEvent,
    PolicyInput,
    SessionObservation,
    StrategyProposal,
    UnavailablePolicy,
    UniverseMembership,
    evaluate_policies,
)
from trading_bot.research.hybrid_sources import SourceFact
from trading_bot.research.hybrid_strategies import PriceBar

BASE = datetime(2025, 1, 1, tzinfo=UTC)


def inputs(
    symbols: tuple[str, ...] = ("AAA",), closes: tuple[Decimal, ...] | None = None, count: int = 253
) -> PolicyInput:
    sessions = tuple(
        CalendarSession(i, BASE + timedelta(days=i, hours=14), BASE + timedelta(days=i, hours=21))
        for i in range(count + 1)
    )
    values = closes or tuple(Decimal(100 + i) for i in range(count))
    observations = tuple(
        SessionObservation(symbol, i, PriceBar(sessions[i].closes_at, value, value), Decimal(1000))
        for symbol in symbols
        for i, value in enumerate(values)
    )
    return PolicyInput(
        sessions,
        observations,
        tuple(UniverseMembership(s, BASE, BASE, True, f"member-{s}") for s in symbols),
        sessions[count - 1].closes_at,
        calendar_verified=True,
    )


def by_family(
    data: PolicyInput, family: str, symbol: str = "AAA"
) -> StrategyProposal | UnavailablePolicy:
    return next(r for r in evaluate_policies(data) if r.family == family and r.symbol == symbol)


def quality(data: PolicyInput) -> tuple[SourceFact, ...]:
    return tuple(
        SourceFact(
            "AAA",
            metric,
            Decimal(value),
            BASE,
            BASE,
            "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
            metric,
        )
        for metric, value in (("roe", ".2"), ("revenue_growth", ".1"), ("debt_to_equity", ".5"))
    )


def test_cross_section_ties_are_stable_and_recent_month_is_excluded() -> None:
    data = inputs(("BBB", "AAA"))
    results = evaluate_policies(data)
    first = by_family(data, "momentum", "AAA")
    second = by_family(data, "momentum", "BBB")
    assert isinstance(first, StrategyProposal) and first.decision == "enter"
    assert isinstance(second, StrategyProposal) and second.decision == "hold"
    assert results == evaluate_policies(
        replace(data, observations=tuple(reversed(data.observations)))
    )
    assert first.execute_not_before == data.sessions[-1].opens_at
    assert first.execute_not_before > first.information_at
    assert first.qualified is False
    with pytest.raises(FrozenInstanceError):
        first.decision = "exit"  # type: ignore[misc]
    # A last-close shock does not enter the 252/21 ranking window.
    altered = replace(
        data,
        observations=tuple(
            replace(o, bar=PriceBar(o.bar.completed_at, Decimal(1), Decimal(1)))
            if o.session_index >= 232
            else o
            for o in data.observations
        ),
    )
    assert by_family(altered, "momentum", "AAA").decision == "enter"  # type: ignore[union-attr]


def test_missing_competitor_or_unverified_calendar_cannot_shrink_universe() -> None:
    data = inputs(("AAA", "BBB"))
    incomplete = replace(
        data,
        observations=tuple(
            o for o in data.observations if o.symbol == "AAA" or o.session_index > 0
        ),
    )
    assert isinstance(by_family(incomplete, "momentum"), UnavailablePolicy)
    assert isinstance(by_family(replace(data, calendar_verified=False), "trend"), UnavailablePolicy)
    assert isinstance(by_family(inputs(count=10), "trend"), UnavailablePolicy)


def test_trend_breakout_and_quality_have_positive_and_denial_paths() -> None:
    data = inputs()
    assert by_family(data, "trend").decision == "enter"  # type: ignore[union-attr]
    assert by_family(data, "breakout").decision == "hold"  # type: ignore[union-attr]
    confirmed = replace(
        data,
        observations=(
            *data.observations[:-1],
            replace(data.observations[-1], volume=Decimal(1500)),
        ),
    )
    assert by_family(confirmed, "breakout").decision == "enter"  # type: ignore[union-attr]
    assert isinstance(by_family(data, "quality_momentum"), UnavailablePolicy)
    assert by_family(replace(data, facts=quality(data)), "quality_momentum").decision == "enter"  # type: ignore[union-attr]
    weak = tuple(replace(f, value=Decimal(-1)) if f.metric == "roe" else f for f in quality(data))
    assert by_family(replace(data, facts=weak), "quality_momentum").decision == "hold"  # type: ignore[union-attr]
    down = inputs(closes=tuple(Decimal(500 - i) for i in range(253)))
    down = replace(down, held_positions=(("AAA", "trend"),))
    assert by_family(down, "trend").decision == "exit"  # type: ignore[union-attr]


def test_mean_reversion_requires_both_five_session_dip_and_positive_long_trend() -> None:
    closes = (*tuple(Decimal(100 + i) for i in range(248)), *([Decimal(320)] * 5))
    assert by_family(inputs(closes=closes), "mean_reversion").decision == "enter"  # type: ignore[union-attr]
    assert by_family(inputs(), "mean_reversion").decision == "hold"  # type: ignore[union-attr]
    assert (
        by_family(
            inputs(closes=tuple(Decimal(500 - i) for i in range(253))), "mean_reversion"
        ).decision  # type: ignore[union-attr]
        == "hold"
    )


def event(
    data: PolicyInput, kind: EventKind, offset: int, value: str, identity: str
) -> PolicyEvent:
    session = data.sessions[252 - offset]
    return PolicyEvent(
        "AAA", kind, identity, session.index, session.closes_at, session.closes_at, Decimal(value)
    )


def test_pead_has_bounded_next_session_confirmation_and_revision_window() -> None:
    data = inputs()
    assert isinstance(by_family(data, "pead"), UnavailablePolicy)
    earnings = event(data, "earnings", 1, ".1", "earnings-1")
    revisions = (
        event(data, "revision", 1, ".02", "revision-1"),
        event(data, "revision", 2, ".02", "revision-2"),
    )
    enriched = replace(data, events=(earnings, *revisions))
    assert by_family(enriched, "pead").decision == "enter"  # type: ignore[union-attr]
    assert by_family(enriched, "revision_momentum").decision == "enter"  # type: ignore[union-attr]
    expired = replace(
        data,
        events=(
            event(data, "earnings", 4, ".1", "old"),
            event(data, "revision", 31, ".1", "old-revision"),
        ),
    )
    assert by_family(expired, "pead").decision == "hold"  # type: ignore[union-attr]
    assert isinstance(by_family(expired, "revision_momentum"), UnavailablePolicy)
    negative = replace(
        data,
        events=(
            event(data, "earnings", 1, "-.1", "bad"),
            event(data, "revision", 1, "-.1", "rev1"),
            event(data, "revision", 2, "-.1", "rev2"),
        ),
    )
    assert by_family(negative, "pead").decision == "hold"  # type: ignore[union-attr]
    assert by_family(negative, "revision_momentum").decision == "hold"  # type: ignore[union-attr]
    assert evaluate_policies(enriched) == evaluate_policies(
        replace(enriched, events=(*enriched.events, earnings))
    )
    with pytest.raises(ValueError, match="conflicting"):
        evaluate_policies(
            replace(enriched, events=(earnings, replace(earnings, value=Decimal(".2"))))
        )


def test_future_observations_facts_events_and_period_mismatch_fail_closed() -> None:
    data = inputs()
    with pytest.raises(ValueError, match="future"):
        evaluate_policies(
            replace(
                data,
                facts=(
                    replace(
                        quality(data)[0], available_at=data.information_at + timedelta(seconds=1)
                    ),
                ),
            )
        )
    with pytest.raises(ValueError, match="future"):
        evaluate_policies(
            replace(
                data,
                events=(
                    replace(
                        event(data, "earnings", 1, ".1", "e"),
                        available_at=data.information_at + timedelta(seconds=1),
                    ),
                ),
            )
        )
    future = SessionObservation(
        "AAA", 253, PriceBar(data.sessions[-1].closes_at, Decimal(400), Decimal(400)), Decimal(1000)
    )
    with pytest.raises(ValueError, match="future"):
        evaluate_policies(replace(data, observations=(*data.observations, future)))
    mismatched = tuple(
        replace(f, period_end=BASE + timedelta(days=1), available_at=BASE + timedelta(days=1))
        if f.metric == "roe"
        else f
        for f in quality(data)
    )
    assert isinstance(
        by_family(replace(data, facts=mismatched), "quality_momentum"), UnavailablePolicy
    )


def test_after_hours_earnings_wait_for_next_session_confirmation() -> None:
    data = inputs()
    released = event(data, "earnings", 1, ".1", "after-hours")
    released = replace(
        released,
        occurred_at=released.occurred_at + timedelta(hours=1),
        available_at=released.available_at + timedelta(hours=1),
    )
    outcome = by_family(replace(data, events=(released,)), "pead")
    assert isinstance(outcome, StrategyProposal) and outcome.decision == "enter"


def test_missing_volume_and_asof_universe_removal_cannot_propose_entries() -> None:
    data = inputs()
    missing_volume = replace(
        data, observations=(*data.observations[:-1], replace(data.observations[-1], volume=None))
    )
    assert isinstance(by_family(missing_volume, "breakout"), UnavailablePolicy)
    removal = UniverseMembership("AAA", data.information_at, data.information_at, False, "removed")
    assert isinstance(
        by_family(replace(data, universe=(*data.universe, removal)), "trend"), UnavailablePolicy
    )


def test_breakout_and_pead_require_price_confirmation_even_with_positive_evidence() -> None:
    data = inputs()
    last = data.observations[-1]
    failed_close = replace(
        last, bar=PriceBar(last.bar.completed_at, Decimal(340), Decimal(340)), volume=Decimal(2000)
    )
    data = replace(
        data,
        observations=(*data.observations[:-1], failed_close),
        events=(event(data, "earnings", 1, ".1", "good-surprise"),),
    )
    breakout = by_family(data, "breakout")
    pead = by_family(data, "pead")
    assert isinstance(breakout, StrategyProposal) and breakout.decision == "hold"
    assert isinstance(pead, StrategyProposal) and pead.decision == "hold"


def test_invalid_session_identity_and_missing_postclose_window_are_rejected() -> None:
    data = inputs()
    with pytest.raises(ValueError, match="session"):
        replace(data.observations[-1], session_index=True)
    with pytest.raises(ValueError, match="window"):
        evaluate_policies(replace(data, information_at=data.sessions[-1].opens_at))


def test_mixed_duration_metadata_returns_unavailable_without_hash_serialization_failure() -> None:
    data = inputs()
    facts = quality(data)
    duration = replace(facts[0], period_start=BASE - timedelta(days=365), event_id="z-duration")
    outcome = by_family(replace(data, facts=(*facts, duration)), "quality_momentum")
    assert isinstance(outcome, UnavailablePolicy)
