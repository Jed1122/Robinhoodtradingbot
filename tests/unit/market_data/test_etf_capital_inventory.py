"""No absent-source or absent-action evidence becomes an explicit zero."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from tests.unit.market_data.test_alpaca_capital_native import page, request
from trading_bot.market_data.etf_calendar import EtfCalendarArchive, EtfCalendarSession
from trading_bot.market_data.etf_capital_archive import CapitalDailyArchive
from trading_bot.market_data.etf_capital_inventory import capital_daily_inventory


def calendar():
    return EtfCalendarArchive(
        "b" * 64,
        tuple(
            EtfCalendarSession(
                date(2023, 1, day),
                datetime(2023, 1, day, 14, 30, tzinfo=UTC),
                datetime(2023, 1, day, 21, tzinfo=UTC),
            )
            for day in (3, 4, 5)
        ),
    )


def archive(symbol):
    return CapitalDailyArchive(
        "a" * 64, request(symbol), (page(symbol),), (datetime(2026, 10, 8, tzinfo=UTC),)
    )


def test_declared_session_inventory_distinguishes_absent_from_missing():
    result = capital_daily_inventory(
        (archive("QQQ"),), calendar(), start=date(2023, 1, 3), end=date(2023, 1, 6)
    )
    assert tuple(row.symbol for row in result.symbols) == ("SPY", "QQQ", "IWM", "SHY", "IEF")
    spy, qqq = result.symbols[:2]
    assert spy.observed_bar_count is None
    assert spy.missing_session_count is None
    assert qqq.observed_bar_count == 1 and qqq.missing_session_count == 2
    assert qqq.expected_session_count == 3
    assert qqq.split_count is qqq.distribution_count is None
    assert result.source_qualified is result.evidence_promotable is False
    assert result.ready_for_strategy_projection is False


def test_calendar_count_match_does_not_imply_action_or_source_acceptance():
    result = capital_daily_inventory(
        tuple(archive(symbol) for symbol in ("SPY", "QQQ", "IWM", "SHY", "IEF")),
        calendar(),
        start=date(2023, 1, 3),
        end=date(2023, 1, 6),
    )
    assert all(row.action_coverage_known is False for row in result.symbols)
    assert result.ready_for_strategy_projection is False
    assert "corporate_action_and_distribution_inputs_missing" in result.reasons


def test_duplicate_symbols_are_not_resolved_by_input_order():
    with pytest.raises(ValueError):
        capital_daily_inventory(
            (archive("QQQ"), archive("QQQ")),
            calendar(),
            start=date(2023, 1, 3),
            end=date(2023, 1, 6),
        )


def test_intraday_aggregation_stamp_is_not_a_daily_session():
    value = CapitalDailyArchive(
        "a" * 64,
        request("QQQ"),
        (page("QQQ", "2023-01-03T15:00:00Z"),),
        (datetime(2026, 10, 8, tzinfo=UTC),),
    )
    with pytest.raises(ValueError):
        capital_daily_inventory((value,), calendar(), start=date(2023, 1, 3), end=date(2023, 1, 6))


def test_window_mismatch_and_empty_calendar_selection_are_denied():
    with pytest.raises(ValueError):
        capital_daily_inventory(
            (archive("QQQ"),), calendar(), start=date(2023, 1, 4), end=date(2023, 1, 6)
        )
    with pytest.raises(ValueError):
        capital_daily_inventory((), calendar(), start=date(2023, 2, 1), end=date(2023, 2, 3))


def test_inventory_identity_is_input_order_independent():
    values = (archive("SPY"), archive("QQQ"))
    left = capital_daily_inventory(values, calendar(), start=date(2023, 1, 3), end=date(2023, 1, 6))
    right = capital_daily_inventory(
        tuple(reversed(values)), calendar(), start=date(2023, 1, 3), end=date(2023, 1, 6)
    )
    assert left.inventory_hash == right.inventory_hash


def test_supplied_empty_response_is_zero_not_absent():
    value = archive("QQQ")
    value = replace(value, pages=(replace(value.pages[0], records=()),))
    result = capital_daily_inventory(
        (value,), calendar(), start=date(2023, 1, 3), end=date(2023, 1, 6)
    )
    row = result.symbols[1]
    assert row.observed_bar_count == 0
    assert row.missing_session_count == 3
    assert row.pagination_complete is True
    assert row.distribution_count is None


def test_incomplete_pagination_remains_incomplete():
    value = archive("QQQ")
    value = replace(value, pages=(replace(value.pages[0], next_page_token="next"),))
    result = capital_daily_inventory(
        (value,), calendar(), start=date(2023, 1, 3), end=date(2023, 1, 6)
    )
    assert result.symbols[1].pagination_complete is False
    assert "QQQ:pagination_incomplete" in result.reasons
