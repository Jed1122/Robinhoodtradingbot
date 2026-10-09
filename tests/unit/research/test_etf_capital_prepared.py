"""Compact preparation from fabricated originals; never qualified evidence."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from tests.unit.config.test_capital_research import capital_loaded
from tests.unit.market_data.test_alpaca_capital_native import body
from tests.unit.market_data.test_etf_capital_dataset import dataset
from trading_bot.market_data.alpaca_capital_native import parse_capital_daily_page
from trading_bot.market_data.etf_calendar import EtfCalendarSession
from trading_bot.market_data.etf_capital_dataset import (
    build_capital_dataset,
    capital_dataset_features,
)
from trading_bot.market_data.etf_source import _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_daily_policy import capital_daily_policy
from trading_bot.research.etf_capital_signals import capital_candidates, capital_strategy_signal


def prepare(source, sessions):
    from trading_bot.research.etf_capital_prepared import _prepare_capital_days

    return _prepare_capital_days(source, sessions=sessions)


def long_source(count=301, *, ancient=False, flat=False):
    source = dataset()
    days = []
    day = date(2020, 1, 2)
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    zone = ZoneInfo("America/New_York")
    sessions = tuple(
        EtfCalendarSession(
            day,
            datetime.combine(day, time(9, 30), zone).astimezone(UTC),
            datetime.combine(day, time(16), zone).astimezone(UTC),
        )
        for day in days
    )
    end = days[-1] + timedelta(days=1)
    archives = []
    for archive in source.archives:
        request = replace(
            archive.request,
            start_ns=_ns(datetime.combine(days[0], time(), UTC)),
            end_ns=_ns(datetime.combine(end, time(), UTC)),
        )
        wire = json.loads(body(request.symbol))
        prototype = wire["bars"][0]
        wire["bars"] = [
            dict(
                prototype,
                t=datetime.combine(day, time(), zone)
                .astimezone(UTC)
                .isoformat()
                .replace("+00:00", "Z"),
                o=100 if flat else 100 + i,
                h=100 if flat else 102 + i,
                l=100 if flat else 98 + i,
                c=100 if flat else 100 + i,
                vw=100 if flat else 100 + i,
            )
            for i, day in enumerate(days)
        ]
        if ancient:
            wire["bars"][0].update(o=1e200, h=1e200, l=1e200, c=1e200, vw=1e200)
        raw = json.dumps(wire).encode()
        page = parse_capital_daily_page(
            raw, request=request, expected_sha256=hashlib.sha256(raw).hexdigest()
        )
        archives.append(replace(archive, request=request, pages=(page,)))
    actions = tuple(replace(row, start=days[0], end=end) for row in source.actions)
    return build_capital_dataset(
        loaded=capital_loaded(),
        archives=tuple(archives),
        actions=actions,
        calendar=replace(source.calendar, sessions=sessions),
        start=days[0],
        end=end,
    )


def test_two_days_keep_only_current_raw_and_bind_full_original_provenance():
    source = dataset()
    dates = tuple(row.session_date for row in source.calendar.sessions)
    value = prepare(source, dates)
    assert tuple(day.session_ordinal for day in value.days) == (0, 1)
    assert tuple(day.raw_bars[0].close for day in value.days) == (D(22), D(11))
    assert all(len(day.raw_bars) == 5 and len(day.signals) == 28 for day in value.days)
    assert all(signal.entry_symbol is None for day in value.days for signal in day.signals)
    assert all(distance is None for day in value.days for _, distance in day.stop_distances)
    for day in value.days:
        full = capital_dataset_features(source, as_of_session=day.session)
        hashes = tuple(sorted((str(p.raw_bars[-1].instrument_id), p.projection_hash) for p in full))
        assert day.input_hash == content_hash(
            (
                "capital-prepared-day-v1",
                value.source_hash,
                source.config_hash,
                day.session,
                day.as_of,
                day.session_ordinal,
                hashes,
                day.raw_bars,
                day.signals,
                day.stop_distances,
            )
        )
        assert (
            not day.source_qualified and not day.execution_enabled and not day.evidence_promotable
        )
    assert value.input_hash == content_hash(
        (
            "capital-prepared-input-v1",
            value.source_hash,
            tuple(day.input_hash for day in value.days),
        )
    )


def test_shared_original_entry_distance_kernel_keeps_literal_atr_window():
    from trading_bot.research.etf_capital_daily_policy import _capital_entry_distance

    source = long_source(200)
    full = capital_dataset_features(source, as_of_session=source.calendar.sessions[-1].session_date)
    assert _capital_entry_distance(
        full[0], as_of=full[0].raw_bars[-1].ends_at, multiplier=D(2), signal_hash="f" * 64
    ) == D(8)


def test_zero_original_atr_is_unknown_entry_distance_not_zero_risk():
    source = long_source(200, flat=True)
    last = source.calendar.sessions[-1].session_date
    result = prepare(source, (last,)).days[0]
    assert all(distance is None for _, distance in result.stop_distances)
    assert all(signal.entry_symbol is None for signal in result.signals)


@pytest.mark.parametrize("count", (199, 200, 201, 301))
def test_compact_values_and_all_original_signal_hashes_match_full_public_kernels(count):
    source = long_source(count)
    last = source.calendar.sessions[-1].session_date
    value = prepare(source, (last,)).days[0]
    full = capital_dataset_features(source, as_of_session=last)
    expected = tuple(
        capital_strategy_signal(c, full, config_hash=source.config_hash, as_of=value.as_of)
        for c in capital_candidates()
    )
    assert value.signals == expected
    assert value.session_ordinal == count - 1
    assert value.stop_distances == tuple(
        (str(p.raw_bars[-1].instrument_id), D(8) if count >= 200 else None) for p in full
    )
    if count >= 200:
        policy = capital_daily_policy(
            loaded=capital_loaded(),
            candidate=capital_candidates()[0],
            projections=full,
            as_of=value.as_of,
        )
        assert policy.stop_distance == D(8)
        if count == 200:
            assert (
                policy.policy_hash
                == "42d9e6f2a8fd9deb1c95afdf94796482475c22cdc3b8df80f75ec05256b84995"
            )


@pytest.mark.parametrize(
    "sessions",
    (
        (),
        [],
        (date(2023, 1, 4), date(2023, 1, 3)),
        (date(2023, 1, 3), date(2023, 1, 3)),
        (date(2023, 1, 5),),
        ("2023-01-03",),
    ),
)
def test_invalid_or_missing_original_session_schedule_denies_whole_preparation(sessions):
    with pytest.raises(ValueError):
        prepare(dataset(), sessions)


def test_intermediate_ancient_split_basis_is_validated_outside_compact_window():
    from trading_bot.market_data.etf_capital_actions import CapitalSplit

    source = long_source(350, ancient=True)
    days = tuple(row.session_date for row in source.calendar.sessions)
    actions = tuple(
        replace(
            row,
            splits=(
                CapitalSplit(days[299], D("1e-400"), "d" * 64),
                CapitalSplit(days[329], D("1e400"), "e" * 64),
            ),
        )
        for row in source.actions
    )
    source = replace(source, actions=actions)
    # Terminal normalization is bounded; requested earlier basis is not.
    capital_dataset_features(source, as_of_session=days[-1])
    with pytest.raises(ValueError):
        prepare(source, (days[0], days[309]))


def test_new_call_never_adopts_previous_prepared_source_or_mutated_flags():
    source = dataset()
    dates = tuple(row.session_date for row in source.calendar.sessions)
    value = prepare(source, dates)
    original = value.input_hash
    object.__setattr__(source.archives[0], "manifest_hash", "f" * 64)
    changed = prepare(source, dates)
    assert changed.input_hash != original and value.input_hash == original
    object.__setattr__(source.actions[0], "source_qualified", True)
    with pytest.raises(ValueError):
        prepare(source, dates)


def test_prepared_input_is_not_a_supported_source_argument():
    source = dataset()
    dates = tuple(row.session_date for row in source.calendar.sessions)
    with pytest.raises(ValueError):
        prepare(prepare(source, dates), dates)
