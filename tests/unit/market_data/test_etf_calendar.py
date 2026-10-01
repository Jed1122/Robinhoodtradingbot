"""Provider calendar identity and exact daily-price coverage, not executable trust."""

import hashlib
import importlib
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from tests.unit.research.test_etf_latest_vintage import archive


def api():
    try:
        return importlib.import_module("trading_bot.market_data.etf_calendar")
    except ModuleNotFoundError:
        pytest.fail("ETF calendar comparison is missing")


def wire(rows=None):
    return json.dumps(
        {
            "request": {"start_date": "2016-01-01", "end_date": "2025-12-31"},
            "calendar": rows
            if rows is not None
            else [
                {
                    "date": "2016-01-04",
                    "open": "2016-01-04T09:30:00",
                    "close": "2016-01-04T16:00:00",
                }
            ],
        },
        separators=(",", ":"),
    ).encode()


def parse(body):
    return api().parse_etf_calendar(body, hashlib.sha256(body).hexdigest())


def test_calendar_uses_new_york_dst_and_retains_false_trust_flags():
    result = parse(wire())
    assert result.sessions[0].opens_at == datetime(2016, 1, 4, 14, 30, tzinfo=UTC)
    assert result.sessions[0].closes_at == datetime(2016, 1, 4, 21, tzinfo=UTC)
    assert not result.source_qualified and not result.evidence_promotable
    summer = parse(
        wire(
            [{"date": "2016-07-01", "open": "2016-07-01T09:30:00", "close": "2016-07-01T13:00:00"}]
        )
    )
    assert summer.sessions[0].opens_at == datetime(2016, 7, 1, 13, 30, tzinfo=UTC)
    assert summer.sessions[0].closes_at == datetime(2016, 7, 1, 17, tzinfo=UTC)


@pytest.mark.parametrize(
    "row",
    [
        {"date": "2016-01-02", "open": "2016-01-02T09:30:00", "close": "2016-01-02T16:00:00"},
        {"date": "2016-01-04", "open": "2016-01-05T09:30:00", "close": "2016-01-04T16:00:00"},
        {"date": "2016-01-04", "open": "2016-01-04T09:30:00Z", "close": "2016-01-04T16:00:00"},
        {"date": "2016-01-04", "open": "2016-01-04T09:31:00", "close": "2016-01-04T16:00:00"},
        {"date": "2016-01-04", "open": "2016-01-04T09:30:00", "close": "2016-01-04T09:30:00"},
        {"date": "2016-01-04", "open": "2016-01-04T09:30:00", "close": "2016-01-04T17:00:00"},
        {"date": "2026-01-02", "open": "2026-01-02T09:30:00", "close": "2026-01-02T16:00:00"},
    ],
)
def test_invalid_clock_identity_denies(row):
    with pytest.raises(ValueError, match="etf_calendar_invalid"):
        parse(wire([row]))


def test_duplicate_order_scope_hash_and_json_fields_fail_closed():
    row = {"date": "2016-01-04", "open": "2016-01-04T09:30:00", "close": "2016-01-04T16:00:00"}
    bodies = [
        wire([row, row]),
        wire().replace(b'"2016-01-01"', b'"2017-01-01"'),
        wire().replace(b'"request":', b'"unknown":'),
        b'{"request":{},"request":{},"calendar":[]}',
        wire([]),
    ]
    for body in bodies:
        with pytest.raises(ValueError, match="etf_calendar_invalid"):
            parse(body)
    with pytest.raises(ValueError, match="etf_calendar_invalid"):
        api().parse_etf_calendar(wire(), "f" * 64)


def test_exact_date_coverage_not_equal_counts_or_constructed_trust():
    source = archive(1)
    calendar = parse(wire())
    result = api().compare_etf_calendar_bars(source, calendar)
    assert result.dates_match and result.missing_session_count == result.unexpected_bar_count == 0
    assert not result.source_qualified
    changed = replace(
        source,
        bars=(replace(source.bars[0], timestamp_ns=source.bars[0].timestamp_ns + 86400 * 10**9),),
    )
    result = api().compare_etf_calendar_bars(changed, calendar)
    assert not result.dates_match
    assert result.missing_session_count == result.unexpected_bar_count == 1


def test_nested_unsafe_calendar_record_is_revalidated():
    result = parse(wire())
    object.__setattr__(result.sessions[0], "closes_at", result.sessions[0].opens_at)
    with pytest.raises(ValueError, match="etf_calendar_invalid"):
        api().compare_etf_calendar_bars(archive(1), result)


def test_daily_bar_kind_and_exact_nanosecond_midnight_are_required():
    source = archive(1)
    calendar = parse(wire())
    wrong_kind = replace(source, request=replace(source.request, kind="quotes"))
    almost_midnight = replace(
        source, bars=(replace(source.bars[0], timestamp_ns=source.bars[0].timestamp_ns - 1),)
    )
    for altered in (wrong_kind, almost_midnight):
        with pytest.raises(ValueError, match="etf_calendar_invalid"):
            api().compare_etf_calendar_bars(altered, calendar)
