"""Literal SMA expectations independent of the implementation under test."""

import importlib
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

import pytest

from tests.unit.research.test_etf_monthly_protocol import protocol

D = Decimal
EQUAL_CLOSES = (D("100"),) * 10


def api():
    return importlib.import_module("trading_bot.strategies.etf_monthly_trend")


def observations(values=EQUAL_CLOSES):
    m = importlib.import_module("trading_bot.research.etf_monthly_protocol")
    days = protocol().month_end_sessions[:10]
    return tuple(
        m.EtfMonthObservation(
            day.replace(day=1),
            day,
            datetime.combine(day, datetime.min.time(), ZoneInfo("America/New_York"))
            .replace(hour=16)
            .astimezone(UTC),
            value,
            f"{i:064x}",
        )
        for i, (day, value) in enumerate(zip(days, values, strict=True))
    )


def compute(rows):
    return api().compute_etf_monthly_signal(
        rows, decision_at=rows[-1].ends_at + timedelta(microseconds=1)
    )


def test_sma10_equality_is_cash():
    rows = observations()
    s = compute(rows)
    assert s.average_close == D("100") and s.latest_close == D("100")
    assert s.regime == "CASH"
    assert s.month_ends == rows and s.source_hashes == tuple(r.source_hash for r in rows)
    assert len(s.signal_hash) == 64


def test_sma10_ten_consecutive_closes_and_precision():
    rows = observations(tuple(D(i) for i in range(1, 11)))
    s = compute(rows)
    assert s.average_close == D("5.5") and s.regime == "LONG_ELIGIBLE"
    with localcontext() as ctx:
        ctx.prec = 3
        assert compute(rows) == s


@pytest.mark.parametrize(
    "change",
    [
        "short",
        "duplicate",
        "reverse",
        "gap",
        "future",
        "same_close",
        "not_after_close",
        "mutated_average",
    ],
)
def test_missing_reordered_or_future_months_are_not_cash(change):
    rows = observations()
    when = rows[-1].ends_at + timedelta(microseconds=1)
    if change == "short":
        rows = rows[:-1]
    elif change == "duplicate":
        rows = (rows[0], rows[0], *rows[2:])
    elif change == "reverse":
        rows = tuple(reversed(rows))
    elif change == "gap":
        rows = (
            rows[0],
            *rows[2:],
            replace(
                rows[-1],
                month=date(2016, 11, 1),
                session_date=date(2016, 11, 30),
                ends_at=datetime(2016, 11, 30, 21, tzinfo=UTC),
            ),
        )
        when = rows[-1].ends_at + timedelta(microseconds=1)
    elif change == "future":
        when -= timedelta(days=1)
    elif change == "same_close":
        when = rows[-1].ends_at
    elif change == "not_after_close":
        when += timedelta(days=1)
    elif change == "mutated_average":
        s = compute(rows)
        with pytest.raises(ValueError):
            replace(s, average_close=D("101"))
        return
    with pytest.raises(ValueError, match="etf_monthly_invalid"):
        api().compute_etf_monthly_signal(rows, decision_at=when)


def test_month_end_selection_uses_supplied_holiday_calendar_not_weekday_guess():
    m = importlib.import_module("trading_bot.research.etf_monthly_protocol")
    days = (
        date(2016, 2, 26),
        date(2016, 2, 29),
        date(2016, 3, 1),
        date(2016, 3, 30),
        date(2016, 4, 1),
    )  # Declared Mar31 closure.
    assert m.select_etf_month_ends(days) == (date(2016, 2, 29), date(2016, 3, 30), date(2016, 4, 1))
    with pytest.raises(ValueError):
        m.select_etf_month_ends((days[0], days[0]))
    rows = observations()
    assert rows[1].ends_at.hour == 21 and rows[2].ends_at.hour == 20  # NY DST.
