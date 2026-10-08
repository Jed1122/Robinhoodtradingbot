"""Shared bounded saved-input validation/projection, not source qualification."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from trading_bot.clock import require_utc
from trading_bot.domain import Bar, BarInterval, InstrumentId
from trading_bot.market_data.alpaca_native import AlpacaBarRecord, AlpacaStockRequest
from trading_bot.market_data.etf_calendar import EtfCalendarArchive, compare_etf_calendar_bars
from trading_bot.market_data.etf_issuer_distributions import EtfIssuerDistributionArchive
from trading_bot.market_data.etf_native_archive import EtfNativeBarsArchive
from trading_bot.market_data.etf_source import _ceil_time, _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_benchmark import EtfBenchmarkDistribution
from trading_bot.research.etf_daily_protocol import HOLDOUT_START, EtfDailyBar

_NEW_YORK = ZoneInfo("America/New_York")
_PROJECTION = "raw-daily-session-close-assumption-v1"


def _check(ok: bool) -> None:
    if not ok:
        raise ValueError("etf_exploratory_input_invalid")


def validate_etf_exploratory_archive(
    archive: EtfNativeBarsArchive,
    *,
    start: datetime,
    end: datetime,
) -> None:
    """Preserve latest-vintage row/window checks without constructing a study."""
    _check(type(archive) is EtfNativeBarsArchive)
    _check(type(archive.bars) is tuple and 0 < len(archive.bars) <= 10000)
    require_utc(start)
    require_utc(end)
    require_utc(archive.captured_at)
    replace(archive.request)
    _check(archive.request.kind == "bars")
    previous = -1
    for row in archive.bars:
        _check(type(row) is AlpacaBarRecord)
        replace(row)
        local = _ceil_time(row.timestamp_ns).astimezone(_NEW_YORK)
        _check(row.timestamp_ns > previous and min(row.open, row.high, row.low, row.close) > 0)
        _check((local.hour, local.minute, local.second, local.microsecond) == (0, 0, 0, 0))
        _check(_ns(local.astimezone(UTC)) == row.timestamp_ns)
        _check(_ns(start) <= row.timestamp_ns < _ns(end))
        previous = row.timestamp_ns


def project_etf_exploratory_inputs(
    archive: EtfNativeBarsArchive,
    calendar: EtfCalendarArchive,
    issuer: EtfIssuerDistributionArchive,
) -> tuple[tuple[date, ...], tuple[EtfDailyBar, ...], tuple[EtfBenchmarkDistribution, ...]]:
    """Full inventory remains required; price/outcome projections exclude 2024+."""
    _check(
        type(archive) is EtfNativeBarsArchive
        and type(calendar) is EtfCalendarArchive
        and type(issuer) is EtfIssuerDistributionArchive
    )
    for record in (archive, calendar, issuer):
        _check(record.source_qualified is False and record.evidence_promotable is False)
    calendar.__post_init__()
    issuer.__post_init__()
    _check(type(archive.request) is AlpacaStockRequest)
    archive.request.__post_init__()
    _check(archive.request.kind == "bars" and dict(archive.request.query())["adjustment"] == "raw")
    start, end = datetime(2016, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)
    _check(archive.request.start_ns == _ns(start) and archive.request.end_ns == _ns(end))
    validate_etf_exploratory_archive(archive, start=start, end=end)
    _check(compare_etf_calendar_bars(archive, calendar).dates_match)
    sessions = tuple(row.session_date for row in calendar.sessions)
    _check(sessions[0] <= date(2016, 1, 7) and sessions[-1] >= date(2025, 12, 27))
    _check(
        all(240 <= sum(day.year == year for day in sessions) <= 262 for year in range(2016, 2026))
    )
    _check("requested_window_incomplete" not in issuer.limitations)
    _check(len(issuer.distributions) == 40)
    _check(
        {(r.ex_date.year, (r.ex_date.month - 1) // 3) for r in issuer.distributions}
        == {(year, quarter) for year in range(2016, 2026) for quarter in range(4)}
    )
    _check(all(row.ex_date in sessions for row in issuer.distributions))
    by_day = {row.session_date: row for row in calendar.sessions}
    projected = []
    for row in archive.bars:
        day = _ceil_time(row.timestamp_ns).astimezone(_NEW_YORK).date()
        if day >= HOLDOUT_START:
            continue
        session = by_day[day]
        bar = Bar(
            InstrumentId("SPY"),
            BarInterval.ONE_DAY,
            session.opens_at,
            session.closes_at,
            row.open,
            row.high,
            row.low,
            row.close,
            Decimal(row.volume),
            _PROJECTION,
            content_hash((_PROJECTION, row.record_hash, session)),
        )
        projected.append(EtfDailyBar(day, bar, bar))
    distributions = tuple(
        EtfBenchmarkDistribution(r.ex_date, r.pay_date, r.amount, r.row_hash)
        for r in issuer.distributions
        if r.ex_date < HOLDOUT_START
    )
    return tuple(day for day in sessions if day < HOLDOUT_START), tuple(projected), distributions
