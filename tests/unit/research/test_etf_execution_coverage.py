"""Invented native observations diagnose requests, never executable continuity."""

import hashlib
import importlib
from dataclasses import FrozenInstanceError, asdict, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from trading_bot.market_data.alpaca_native import (
    AlpacaBarRecord,
    AlpacaQuoteRecord,
    AlpacaStockRequest,
    parse_timestamp_ns,
)
from trading_bot.market_data.etf_calendar import EtfCalendarArchive, EtfCalendarSession
from trading_bot.market_data.etf_native_archive import EtfNativeBarsArchive, EtfNativeQuotesArchive

NEW_YORK = ZoneInfo("America/New_York")
START = parse_timestamp_ns("2016-01-01T00:00:00Z")
END = parse_timestamp_ns("2026-01-01T00:00:00Z")
CAPTURED = datetime(2026, 10, 1, 12, tzinfo=UTC)


def api():
    try:
        return importlib.import_module("trading_bot.research.etf_execution_coverage")
    except ModuleNotFoundError:
        pytest.fail("ETF execution request coverage diagnostic is missing")


def digest(label):
    return hashlib.sha256(label.encode()).hexdigest()


def ns(instant):
    return parse_timestamp_ns(instant.isoformat())


def inputs(days=(date(2019, 3, 8),), *, early_close=None, warmup=750):
    # Deliberately invented weekday-only calendar; it is never source-qualified.
    previous = []
    day = date(2016, 1, 4)
    while len(previous) < warmup:
        if day.weekday() < 5:
            previous.append(day)
        day += timedelta(days=1)
    sessions = tuple(
        EtfCalendarSession(
            day,
            datetime.combine(day, time(9, 30), NEW_YORK).astimezone(UTC),
            datetime.combine(
                day, time(13) if day == early_close else time(16), NEW_YORK
            ).astimezone(UTC),
        )
        for day in (*previous, *days)
    )
    calendar = EtfCalendarArchive(digest("calendar"), sessions)
    rows = tuple(
        AlpacaBarRecord(
            digest("bars"),
            0,
            index,
            ns(datetime.combine(session.session_date, time(0), NEW_YORK)),
            Decimal("100"),
            Decimal("102"),
            Decimal("99"),
            Decimal("101"),
            1000,
            10,
            Decimal("100.5"),
        )
        for index, session in enumerate(sessions)
    )
    bars = EtfNativeBarsArchive(
        digest("bar-manifest"),
        AlpacaStockRequest("bars", START, END),
        (digest("bar-receipt"),),
        rows,
        CAPTURED,
    )
    return bars, calendar


def quotes(label, start, end, stamps=None):
    rows = tuple(
        AlpacaQuoteRecord(
            digest(label + "-body"),
            0,
            index,
            stamp,
            Decimal("100"),
            Decimal("100.1"),
            2,
            3,
            "P",
            "N",
            ("R", "Y"),
            "B",
        )
        for index, stamp in enumerate((start,) if stamps is None else stamps)
    )
    return EtfNativeQuotesArchive(
        digest(label + "-manifest"),
        AlpacaStockRequest("quotes", start, end),
        (digest(label + "-receipt"),),
        rows,
        CAPTURED,
    )


def audit(bars, quote_archives, calendar):
    return api().audit_etf_execution_coverage(bars, quote_archives, calendar)


def test_partial_quote_request_cannot_claim_full_session_or_execution_coverage():
    bars, calendar = inputs()
    opened = ns(calendar.sessions[-1].opens_at)
    archive = quotes("partial", opened, opened + 60 * 10**9, (opened, opened))
    report = audit(bars, (archive,), calendar)
    assert report.bar_archive_hash == bars.archive_hash
    assert report.calendar_archive_hash == calendar.archive_hash
    assert report.quote_archive_hashes == (archive.archive_hash,)
    assert report.calendar_dates_match is True
    assert (report.bar_count, report.calendar_session_count) == (751, 751)
    assert report.development_sessions_after750 == 1
    assert report.quoted_session_count == 1
    assert report.fully_requested_session_count == 0
    assert report.missing_requested_sessions == (date(2019, 3, 8),)
    assert report.total_quote_observations == 2
    assert "quote_requests_do_not_cover_development_sessions" in report.reasons
    assert "transport_requests_do_not_prove_record_completeness" in report.reasons
    assert "historical_controls_and_gaps_unqualified" in report.reasons
    assert report.status == "BLOCKED_INPUTS"
    assert report.source_qualified is False
    assert report.execution_enabled is False
    assert report.evidence_promotable is False
    serialized = asdict(report)
    assert "quotes" not in serialized and "bars" not in serialized
    assert "100.1" not in str(serialized)
    with pytest.raises(FrozenInstanceError):
        report.quoted_session_count = 99


def test_full_request_without_regular_session_observations_stays_blocked():
    bars, calendar = inputs()
    session = calendar.sessions[-1]
    opened, closed = ns(session.opens_at), ns(session.closes_at)
    archive = quotes("no-daytime-events", opened - 1, closed, (opened - 1,))
    report = audit(bars, (archive,), calendar)
    assert report.fully_requested_session_count == 1
    assert report.quoted_session_count == 0
    assert report.missing_requested_sessions == ()
    assert "requested_sessions_without_quote_observations" in report.reasons
    assert "native_quotes_not_executable" in report.reasons
    assert report.status == "BLOCKED_INPUTS" and not report.execution_enabled


def test_adjacent_request_intervals_cover_session_without_double_counting():
    bars, calendar = inputs()
    opened, closed = ns(calendar.sessions[-1].opens_at), ns(calendar.sessions[-1].closes_at)
    midpoint = opened + 3 * 3600 * 10**9
    left = quotes("left", opened, midpoint)
    right = quotes("right", midpoint, closed)
    report = audit(bars, (right, left), calendar)
    assert report.fully_requested_session_count == report.quoted_session_count == 1
    assert report.missing_requested_sessions == ()
    assert report.total_quote_observations == 2
    assert audit(bars, (left, right), calendar) == report
    assert report.report_hash == audit(bars, (left, right), calendar).report_hash


def test_overlapping_requests_preserve_observation_count_but_count_session_once():
    bars, calendar = inputs()
    opened, closed = ns(calendar.sessions[-1].opens_at), ns(calendar.sessions[-1].closes_at)
    midpoint = opened + 3 * 3600 * 10**9
    left = quotes("left", opened, midpoint + 1, (opened, midpoint))
    right = quotes("right", midpoint, closed, (midpoint, midpoint, midpoint + 1))
    report = audit(bars, (left, right), calendar)
    assert report.fully_requested_session_count == 1
    assert report.total_quote_observations == 5
    assert "overlapping_requests_observations_not_deduplicated" in report.reasons


def test_one_nanosecond_request_gap_is_not_continuous_requested_coverage():
    bars, calendar = inputs()
    opened, closed = ns(calendar.sessions[-1].opens_at), ns(calendar.sessions[-1].closes_at)
    midpoint = opened + 3 * 3600 * 10**9
    report = audit(
        bars,
        (quotes("left", opened, midpoint), quotes("right", midpoint + 1, closed)),
        calendar,
    )
    assert report.fully_requested_session_count == 0
    assert report.missing_requested_sessions == (date(2019, 3, 8),)


def test_dst_and_early_close_use_recorded_utc_session_bounds():
    bars, calendar = inputs(
        (date(2019, 3, 8), date(2019, 3, 11), date(2019, 11, 29)),
        early_close=date(2019, 11, 29),
    )
    archives = (
        quotes(
            "winter",
            parse_timestamp_ns("2019-03-08T14:30:00Z"),
            parse_timestamp_ns("2019-03-08T21:00:00Z"),
        ),
        quotes(
            "summer",
            parse_timestamp_ns("2019-03-11T13:30:00Z"),
            parse_timestamp_ns("2019-03-11T20:00:00Z"),
        ),
        quotes(
            "early",
            parse_timestamp_ns("2019-11-29T14:30:00Z"),
            parse_timestamp_ns("2019-11-29T18:00:00Z"),
        ),
    )
    report = audit(bars, archives, calendar)
    assert report.development_sessions_after750 == 3
    assert report.quoted_session_count == report.fully_requested_session_count == 3
    assert report.missing_requested_sessions == ()


def test_750_bar_warmup_and_holdout_are_excluded_from_session_counts():
    bars, calendar = inputs((date(2019, 3, 8), date(2024, 1, 2)))
    first, last = calendar.sessions[0], calendar.sessions[-1]
    archives = (
        quotes("warmup", ns(first.opens_at), ns(first.closes_at)),
        quotes("holdout", ns(last.opens_at), ns(last.closes_at)),
    )
    report = audit(bars, archives, calendar)
    assert report.development_sessions_after750 == 1
    assert report.quoted_session_count == report.fully_requested_session_count == 0
    assert report.missing_requested_sessions == (date(2019, 3, 8),)
    assert report.total_quote_observations == 2
    assert "holdout_not_evaluated" in report.reasons


def test_short_development_history_does_not_invent_evaluation_sessions():
    bars, calendar = inputs((), warmup=749)
    session = calendar.sessions[-1]
    report = audit(bars, (quotes("short", ns(session.opens_at), ns(session.closes_at)),), calendar)
    assert report.development_sessions_after750 == 0
    assert report.quoted_session_count == report.fully_requested_session_count == 0
    assert report.missing_requested_sessions == ()
    assert "development_history_after_warmup_empty" in report.reasons


def test_equal_bar_calendar_counts_do_not_hide_wrong_dates():
    bars, calendar = inputs()
    replacement = replace(bars.bars[-1], timestamp_ns=parse_timestamp_ns("2019-03-07T05:00:00Z"))
    changed = replace(bars, bars=(*bars.bars[:-1], replacement))
    session = calendar.sessions[-1]
    report = audit(
        changed, (quotes("complete", ns(session.opens_at), ns(session.closes_at)),), calendar
    )
    assert report.calendar_dates_match is False
    assert report.missing_bar_session_count == report.unexpected_bar_count == 1
    assert "bar_calendar_dates_mismatch" in report.reasons
    assert report.status == "BLOCKED_INPUTS"


@pytest.mark.parametrize("target", ["bars", "quotes", "calendar", "quote-list", "quote-item"])
def test_wrong_input_types_fail_closed(target):
    bars, calendar = inputs()
    session = calendar.sessions[-1]
    archives = (quotes("complete", ns(session.opens_at), ns(session.closes_at)),)
    args = [bars, archives, calendar]
    if target == "bars":
        args[0] = object()
    elif target == "calendar":
        args[2] = object()
    elif target == "quote-list":
        args[1] = list(archives)
    elif target == "quote-item":
        args[1] = (object(),)
    else:
        args[1] = ()
    with pytest.raises(ValueError, match="etf_execution_coverage_invalid"):
        audit(*args)


def test_duplicate_quote_archive_is_denied_instead_of_inflating_coverage():
    bars, calendar = inputs()
    session = calendar.sessions[-1]
    archive = quotes("complete", ns(session.opens_at), ns(session.closes_at))
    with pytest.raises(ValueError, match="etf_execution_coverage_invalid"):
        audit(bars, (archive, replace(archive)), calendar)


def test_same_capture_manifest_with_conflicting_rows_is_not_a_second_archive():
    bars, calendar = inputs()
    session = calendar.sessions[-1]
    archive = quotes("complete", ns(session.opens_at), ns(session.closes_at))
    conflicting = replace(
        archive, quotes=(replace(archive.quotes[0], bid_size=archive.quotes[0].bid_size + 1),)
    )
    with pytest.raises(ValueError, match="etf_execution_coverage_invalid"):
        audit(bars, (archive, conflicting), calendar)


@pytest.mark.parametrize(
    "change",
    [
        "bar-kind",
        "bar-window",
        "quote-kind",
        "quote-window",
        "quote-duration",
        "quote-limit",
        "empty-bars",
        "empty-quotes",
        "bar-outside-request",
        "quote-outside-request",
        "bar-nonmidnight",
        "quote-order",
        "quote-size",
        "bar-source",
        "quote-source",
        "bar-qualified",
        "quote-executable",
        "calendar-qualified",
        "bad-manifest",
        "bad-receipt",
    ],
)
def test_nested_native_archive_semantics_are_revalidated(change):
    bars, calendar = inputs()
    session = calendar.sessions[-1]
    opened, closed = ns(session.opens_at), ns(session.closes_at)
    archive = quotes("complete", opened, closed, (opened, opened + 1))
    if change == "bar-kind":
        bars = replace(bars, request=replace(bars.request, kind="quotes"))
    elif change == "bar-window":
        bars = replace(bars, request=replace(bars.request, end_ns=END - 1))
    elif change == "quote-kind":
        archive = replace(archive, request=replace(archive.request, kind="bars"))
    elif change == "quote-window":
        archive = replace(archive, request=replace(archive.request, end_ns=END + 1))
    elif change == "quote-duration":
        archive = replace(
            archive, request=replace(archive.request, end_ns=opened + 86400 * 10**9 + 1)
        )
    elif change == "quote-limit":
        archive = replace(archive, request=replace(archive.request, limit=1001))
    elif change == "empty-bars":
        bars = replace(bars, bars=())
    elif change == "empty-quotes":
        archive = replace(archive, quotes=())
    elif change == "bar-outside-request":
        bars = replace(bars, bars=(replace(bars.bars[0], timestamp_ns=END),))
    elif change == "quote-outside-request":
        archive = replace(archive, quotes=(replace(archive.quotes[0], timestamp_ns=closed),))
    elif change == "bar-nonmidnight":
        bars = replace(
            bars, bars=(replace(bars.bars[0], timestamp_ns=bars.bars[0].timestamp_ns + 1),)
        )
    elif change == "quote-order":
        archive = replace(archive, quotes=tuple(reversed(archive.quotes)))
    elif change == "quote-size":
        object.__setattr__(archive.quotes[0], "bid_size", -1)
    elif change == "bar-source":
        object.__setattr__(bars, "source_kind", "iex")
    elif change == "quote-source":
        object.__setattr__(archive, "source_kind", "iex")
    elif change == "bar-qualified":
        object.__setattr__(bars, "source_qualified", True)
    elif change == "quote-executable":
        object.__setattr__(archive, "execution_enabled", True)
    elif change == "calendar-qualified":
        object.__setattr__(calendar, "source_qualified", True)
    elif change == "bad-manifest":
        archive = replace(archive, manifest_hash="secret-untrusted-text")
    else:
        archive = replace(archive, receipt_hashes=("invalid",))
    with pytest.raises(ValueError, match="etf_execution_coverage_invalid") as caught:
        audit(bars, (archive,), calendar)
    assert "secret-untrusted-text" not in str(caught.value)


def test_report_identity_binds_all_archive_and_request_evidence():
    bars, calendar = inputs()
    session = calendar.sessions[-1]
    archive = quotes("complete", ns(session.opens_at), ns(session.closes_at))
    baseline = audit(bars, (archive,), calendar)
    other = audit(bars, (replace(archive, manifest_hash=digest("other")),), calendar)
    assert baseline.report_hash != other.report_hash
    narrower = replace(archive, request=replace(archive.request, end_ns=archive.request.end_ns - 1))
    assert audit(bars, (narrower,), calendar).fully_requested_session_count == 0
    assert audit(bars, (narrower,), calendar).report_hash != baseline.report_hash


def test_diagnostic_does_not_open_paths_credentials_or_construct_http(monkeypatch):
    module = api()
    bars, calendar = inputs()
    session = calendar.sessions[-1]
    archive = quotes("complete", ns(session.opens_at), ns(session.closes_at))

    def forbidden(*args, **kwargs):
        pytest.fail("coverage diagnostic attempted filesystem or transport access")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr("os.open", forbidden)
    monkeypatch.setattr("httpx.AsyncClient", forbidden)
    report = module.audit_etf_execution_coverage(bars, (archive,), calendar)
    assert report.fully_requested_session_count == 1
    assert (
        report.source_qualified is report.execution_enabled is report.evidence_promotable is False
    )
