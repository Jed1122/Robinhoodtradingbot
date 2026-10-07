"""Bounded saved-input projection; session-close availability is an assumption.

Original receipt bytes remain untouched. Full-window inventory is checked, but
only pre-2024 prices/actions become strategy inputs. None of these checks grant
original-publication, executable-price, corporate-action or cost qualification.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from trading_bot.domain import Bar, BarInterval, InstrumentId
from trading_bot.market_data.alpaca_native import AlpacaStockRequest
from trading_bot.market_data.etf_calendar import EtfCalendarArchive, compare_etf_calendar_bars
from trading_bot.market_data.etf_issuer_distributions import EtfIssuerDistributionArchive
from trading_bot.market_data.etf_native_archive import EtfNativeBarsArchive
from trading_bot.market_data.etf_source import _ceil_time, _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_benchmark import EtfBenchmarkDistribution
from trading_bot.research.etf_daily_protocol import (
    HOLDOUT_START,
    EtfDailyBar,
    EtfDailyError,
    EtfDailyProtocol,
    EtfDailyRequest,
    _check,
)
from trading_bot.research.etf_latest_vintage import (
    EtfLatestVintageRequest,
    latest_vintage_source_plan_hash,
)
from trading_bot.research.etf_study import EtfStudy
from trading_bot.simulation.etf_history import _policy

_NEW_YORK = ZoneInfo("America/New_York")
_PROJECTION = "raw-daily-session-close-assumption-v1"


def etf_daily_source_plan_hash(
    archive: EtfNativeBarsArchive,
    calendar: EtfCalendarArchive,
    issuer: EtfIssuerDistributionArchive,
) -> str:
    return content_hash(
        {
            "schema": "etf-daily-development-intake-v1",
            "bar_archive": archive.archive_hash,
            "calendar": calendar.archive_hash,
            "issuer": issuer.archive_hash,
            "projection": _PROJECTION,
            "price_basis": "unadjusted-no-splits-assumption",
            "evaluation": "before-2024-only",
            "warmup": 100,
            "anchor": "2016-05-26",
            "availability": "calendar-close-assumption-not-publication-evidence",
            "qualification": False,
        }
    )


def make_etf_daily_request(
    study: EtfStudy,
    archive: EtfNativeBarsArchive,
    calendar: EtfCalendarArchive,
    issuer: EtfIssuerDistributionArchive,
) -> EtfDailyRequest:
    try:
        _policy(study)
        _check(type(archive) is EtfNativeBarsArchive)
        _check(type(calendar) is EtfCalendarArchive)
        _check(type(issuer) is EtfIssuerDistributionArchive)
        for record in (archive, calendar, issuer):
            _check(record.source_qualified is False and record.evidence_promotable is False)
        calendar.__post_init__()
        issuer.__post_init__()
        _check(type(archive.request) is AlpacaStockRequest)
        archive.request.__post_init__()
        _check(archive.request.kind == "bars")
        _check(dict(archive.request.query())["adjustment"] == "raw")
        _check(
            archive.request.start_ns == _ns(study.requested_start)
            and archive.request.end_ns == _ns(study.requested_end)
        )
        _check(study.source_plan_hash == etf_daily_source_plan_hash(archive, calendar, issuer))
        coverage = compare_etf_calendar_bars(archive, calendar)
        _check(coverage.dates_match)
        sessions = tuple(row.session_date for row in calendar.sessions)
        _check(sessions[0] <= date(2016, 1, 7) and sessions[-1] >= date(2025, 12, 27))
        _check(
            all(
                240 <= sum(day.year == year for day in sessions) <= 262
                for year in range(2016, 2026)
            )
        )
        _check("requested_window_incomplete" not in issuer.limitations)
        _check(len(issuer.distributions) == 40)
        _check(
            {(r.ex_date.year, (r.ex_date.month - 1) // 3) for r in issuer.distributions}
            == {(year, quarter) for year in range(2016, 2026) for quarter in range(4)}
        )
        _check(all(row.ex_date in sessions for row in issuer.distributions))
        # This invokes the old native *validation*, not its midnight feature
        # projection or 750-bar evaluator. Its admission flags remain unchanged.
        checked = replace(
            study, policy=_policy(study), source_plan_hash=latest_vintage_source_plan_hash(archive)
        )
        EtfLatestVintageRequest(checked, archive)
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
        protocol = EtfDailyProtocol(
            study,
            tuple(day for day in sessions if day < HOLDOUT_START),
            calendar.archive_hash,
            archive.archive_hash,
            issuer.archive_hash,
            Decimal("5"),
            Decimal(".01"),
            Decimal(".10"),
        )
        distributions = tuple(
            EtfBenchmarkDistribution(row.ex_date, row.pay_date, row.amount, row.row_hash)
            for row in issuer.distributions
            if row.ex_date < HOLDOUT_START
        )
        return EtfDailyRequest(protocol, tuple(projected), distributions, Decimal("500"))
    except (ValueError, TypeError, ArithmeticError, AttributeError, KeyError):
        raise EtfDailyError() from None
