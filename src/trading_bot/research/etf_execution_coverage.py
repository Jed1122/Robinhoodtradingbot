"""Pure native SPY request-coverage inventory, never executable source admission.

The caller supplies already-read native archives, not paths or credentials. This
diagnostic revalidates their in-memory shape but does not reread receipts or certify
provenance. Session counts concern calendar sessions after a fixed 750-session
warmup and before 2024. Holdout observations are counted only as archive inventory.

``fully_requested_session_count`` means the union of retained half-open REST
request intervals spans a recorded session's open/close interval. It does not
prove record completeness, continuous monitoring, controls, liquidity or exits.
Overlapping acquisitions retain every observation; no exchange sequence or
deduplication is invented. Every report is permanently blocked/nonpromotable.
"""

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.alpaca_native import (
    MAX_PAGES,
    AlpacaQuoteRecord,
    AlpacaStockRequest,
    parse_timestamp_ns,
)
from trading_bot.market_data.etf_calendar import (
    EtfCalendarArchive,
    compare_etf_calendar_bars,
)
from trading_bot.market_data.etf_native_archive import EtfNativeBarsArchive, EtfNativeQuotesArchive
from trading_bot.market_data.etf_source import _ceil_time, _ns
from trading_bot.market_data.recording import content_hash

_START = parse_timestamp_ns("2016-01-01T00:00:00Z")
_END = parse_timestamp_ns("2026-01-01T00:00:00Z")
_HOLDOUT = date(2024, 1, 1)
_NEW_YORK = ZoneInfo("America/New_York")
_REASONS = (
    "source_qualification_unverified",
    "archive_receipts_not_reverified_by_diagnostic",
    "development_session_counts_are_calendar_projections",
    "transport_requests_do_not_prove_record_completeness",
    "historical_controls_and_gaps_unqualified",
    "native_quote_conditions_and_size_conversion_unverified",
    "fractional_terms_and_action_continuity_unqualified",
    "execution_costs_and_calibration_unqualified",
    "native_quotes_not_executable",
    "holdout_not_evaluated",
)


class EtfExecutionCoverageError(ValueError):
    def __init__(self) -> None:
        super().__init__("etf_execution_coverage_invalid")


def _check(condition: bool) -> None:
    if not condition:
        raise EtfExecutionCoverageError()


@dataclass(frozen=True, slots=True)
class EtfExecutionCoverageReport:
    bar_archive_hash: str
    quote_archive_hashes: tuple[str, ...]
    calendar_archive_hash: str
    bar_count: int
    calendar_session_count: int
    calendar_dates_match: bool
    missing_bar_session_count: int
    unexpected_bar_count: int
    development_sessions_after750: int
    quoted_session_count: int
    fully_requested_session_count: int
    missing_requested_sessions: tuple[date, ...]
    total_quote_observations: int
    reasons: tuple[str, ...]
    status: Literal["BLOCKED_INPUTS"] = field(default="BLOCKED_INPUTS", init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    @property
    def report_hash(self) -> str:
        return content_hash({"schema": "etf-execution-request-coverage-v1", "report": self})


def _native_identity(archive: EtfNativeBarsArchive | EtfNativeQuotesArchive) -> None:
    _require_sha256_hex(archive.manifest_hash, "manifest")
    _check(type(archive.receipt_hashes) is tuple and 0 < len(archive.receipt_hashes) <= MAX_PAGES)
    _check(len(set(archive.receipt_hashes)) == len(archive.receipt_hashes))
    for digest in archive.receipt_hashes:
        _require_sha256_hex(digest, "receipt")
    _check(type(archive.request) is AlpacaStockRequest)
    replace(archive.request)
    _check(
        _START <= archive.request.start_ns < archive.request.end_ns <= _END
        and archive.request.limit <= 1000
        and archive.request.end_ns <= _ns(require_utc(archive.captured_at))
        and archive.source_qualified is False
        and archive.evidence_promotable is False
    )


def _quote_intervals(
    quotes: tuple[EtfNativeQuotesArchive, ...],
) -> tuple[tuple[tuple[int, int], ...], bool]:
    """Merge exact request bounds, including adjacent intervals; retain overlap fact."""
    merged: list[tuple[int, int]] = []
    overlapping = False
    for start, end in sorted((item.request.start_ns, item.request.end_ns) for item in quotes):
        if merged and start <= merged[-1][1]:
            overlapping |= start < merged[-1][1]
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged), overlapping


def audit_etf_execution_coverage(
    bars: EtfNativeBarsArchive,
    quotes: tuple[EtfNativeQuotesArchive, ...],
    calendar: EtfCalendarArchive,
) -> EtfExecutionCoverageReport:
    """Report transport request spans/observations without granting any readiness."""
    try:
        _check(type(bars) is EtfNativeBarsArchive and type(calendar) is EtfCalendarArchive)
        _check(type(quotes) is tuple and len(quotes) > 0)
        _native_identity(bars)
        _check(
            bars.source_kind == "alpaca-sip-latest-vintage-v1"
            and bars.request.kind == "bars"
            and bars.request.start_ns == _START
            and bars.request.end_ns == _END
            and type(bars.bars) is tuple
            and 0 < len(bars.bars) <= 10000
        )
        _check(
            all(
                bars.request.start_ns <= row.timestamp_ns < bars.request.end_ns for row in bars.bars
            )
        )
        _check(
            calendar.source_kind == "alpaca-connector-v2-calendar-v1"
            and calendar.source_qualified is False
            and calendar.evidence_promotable is False
        )
        replace(calendar)
        coverage = compare_etf_calendar_bars(bars, calendar)
        quote_hashes = []
        for archive in quotes:
            _check(type(archive) is EtfNativeQuotesArchive)
            _native_identity(archive)
            _check(
                archive.source_kind == "alpaca-sip-latest-vintage-quotes-v1"
                and archive.request.kind == "quotes"
                and archive.request.end_ns - archive.request.start_ns <= 86400 * 10**9
                and archive.execution_enabled is False
                and type(archive.quotes) is tuple
                and 0 < len(archive.quotes) <= 10000
            )
            previous = -1
            for row in archive.quotes:
                _check(type(row) is AlpacaQuoteRecord)
                replace(row)
                _check(
                    archive.request.start_ns <= row.timestamp_ns < archive.request.end_ns
                    and previous <= row.timestamp_ns
                )
                previous = row.timestamp_ns
            quote_hashes.append(archive.archive_hash)
        _check(len(set(quote_hashes)) == len(quote_hashes))
        _check(len({archive.manifest_hash for archive in quotes}) == len(quotes))
        development = {
            session.session_date: (_ns(session.opens_at), _ns(session.closes_at))
            for session in calendar.sessions[750:]
            if session.session_date < _HOLDOUT
        }
        intervals, overlapping = _quote_intervals(quotes)
        missing = tuple(
            day
            for day, (opened, closed) in development.items()
            if not any(start <= opened and closed <= end for start, end in intervals)
        )
        quoted = set()
        for archive in quotes:
            for row in archive.quotes:
                day = _ceil_time(row.timestamp_ns).astimezone(_NEW_YORK).date()
                bounds = development.get(day)
                if bounds is not None and bounds[0] <= row.timestamp_ns < bounds[1]:
                    quoted.add(day)
        reasons = list(_REASONS)
        if not coverage.dates_match:
            reasons.append("bar_calendar_dates_mismatch")
        if not development:
            reasons.append("development_history_after_warmup_empty")
        if missing:
            reasons.append("quote_requests_do_not_cover_development_sessions")
        if set(development) - set(missing) - quoted:
            reasons.append("requested_sessions_without_quote_observations")
        if overlapping:
            reasons.append("overlapping_requests_observations_not_deduplicated")
        return EtfExecutionCoverageReport(
            bars.archive_hash,
            tuple(sorted(quote_hashes)),
            calendar.archive_hash,
            coverage.bar_count,
            coverage.session_count,
            coverage.dates_match,
            coverage.missing_session_count,
            coverage.unexpected_bar_count,
            len(development),
            len(quoted),
            len(development) - len(missing),
            missing,
            sum(len(archive.quotes) for archive in quotes),
            tuple(reasons),
        )
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise EtfExecutionCoverageError() from None
