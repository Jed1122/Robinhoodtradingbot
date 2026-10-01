"""Hash-bound legacy Alpaca connector calendars and date-level bar comparison.

The connector returns naive exchange-local v2 times, not native HTTP receipts or
v3 timezone metadata. This narrow projection uses the documented New York market
zone, retains that limitation, and never qualifies quotes, controls or execution.
Dates must match, not merely row counts. No credentials or provider calls occur.
"""

import hashlib
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.alpaca_native import AlpacaBarRecord
from trading_bot.market_data.bundle_codec import _array, _date, _json, _mapping
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.etf_native_archive import EtfNativeBarsArchive
from trading_bot.market_data.etf_source import _ceil_time, _ns
from trading_bot.market_data.recording import content_hash

_NEW_YORK = ZoneInfo("America/New_York")
_LIMITS = BundleLimits(1048576, 1048576, 1048576, 4000, 8)


class EtfCalendarError(ValueError):
    def __init__(self) -> None:
        super().__init__("etf_calendar_invalid")


def _check(value: bool) -> None:
    if not value:
        raise EtfCalendarError()


@dataclass(frozen=True, slots=True)
class EtfCalendarSession:
    session_date: date
    opens_at: datetime
    closes_at: datetime

    def __post_init__(self) -> None:
        _check(type(self.session_date) is date)
        _check(date(2016, 1, 1) <= self.session_date <= date(2025, 12, 31))
        _check(self.session_date.weekday() < 5)
        opened = require_utc(self.opens_at).astimezone(_NEW_YORK)
        closed = require_utc(self.closes_at).astimezone(_NEW_YORK)
        _check(opened.date() == closed.date() == self.session_date)
        _check(opened.time() == time(9, 30) and time(9, 30) < closed.time() <= time(16))


@dataclass(frozen=True, slots=True)
class EtfCalendarArchive:
    source_hash: str
    sessions: tuple[EtfCalendarSession, ...]
    source_kind: Literal["alpaca-connector-v2-calendar-v1"] = field(
        default="alpaca-connector-v2-calendar-v1", init=False
    )
    limitations: tuple[str, ...] = field(
        default=(
            "connector_payload_not_native_http_receipt",
            "legacy_v2_new_york_timezone_projection",
            "calendar_does_not_prove_quote_control_or_action_coverage",
        ),
        init=False,
    )
    source_qualified: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_sha256_hex(self.source_hash, "calendar")
        _check(type(self.sessions) is tuple and 0 < len(self.sessions) <= 4000)
        for item in self.sessions:
            _check(type(item) is EtfCalendarSession)
            replace(item)
        days = tuple(row.session_date for row in self.sessions)
        _check(days == tuple(sorted(set(days))))

    @property
    def archive_hash(self) -> str:
        return content_hash(("etf-calendar-archive-v1", self))


def _time(value: object) -> datetime:
    _check(
        type(value) is str
        and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:00", value) is not None
    )
    parsed = datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=_NEW_YORK).astimezone(UTC)


def parse_etf_calendar(body: bytes, expected_sha256: str) -> EtfCalendarArchive:
    try:
        _check(type(body) is bytes)
        _require_sha256_hex(expected_sha256, "calendar")
        _check(hashlib.sha256(body).hexdigest() == expected_sha256)
        payload = _mapping(_json(body, max_bytes=1048576, limits=_LIMITS), {"request", "calendar"})
        request = _mapping(payload["request"], {"start_date", "end_date"})
        _check(request == {"start_date": "2016-01-01", "end_date": "2025-12-31"})
        sessions = []
        for item in _array(payload["calendar"]):
            row = _mapping(item, {"date", "open", "close"})
            _check(type(row["date"]) is str)
            sessions.append(
                EtfCalendarSession(_date(str(row["date"])), _time(row["open"]), _time(row["close"]))
            )
        return EtfCalendarArchive(expected_sha256, tuple(sessions))
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise EtfCalendarError() from None


@dataclass(frozen=True, slots=True)
class EtfCalendarCoverage:
    calendar_hash: str
    bars_hash: str
    session_count: int
    bar_count: int
    missing_session_count: int
    unexpected_bar_count: int
    source_qualified: Literal[False] = field(default=False, init=False)

    @property
    def dates_match(self) -> bool:
        return self.missing_session_count == self.unexpected_bar_count == 0


def compare_etf_calendar_bars(
    bars: EtfNativeBarsArchive, calendar: EtfCalendarArchive
) -> EtfCalendarCoverage:
    try:
        _check(type(bars) is EtfNativeBarsArchive and type(calendar) is EtfCalendarArchive)
        replace(calendar)
        replace(bars.request)
        _check(bars.request.kind == "bars")
        _check(type(bars.bars) is tuple and 0 < len(bars.bars) <= 10000)
        days = []
        for row in bars.bars:
            _check(type(row) is AlpacaBarRecord)
            replace(row)
            start = _ceil_time(row.timestamp_ns).astimezone(_NEW_YORK)
            _check(start.time() == time(0) and _ns(start.astimezone(UTC)) == row.timestamp_ns)
            days.append(start.date())
        _check(tuple(days) == tuple(sorted(set(days))))
        expected = {row.session_date for row in calendar.sessions}
        observed = set(days)
        return EtfCalendarCoverage(
            calendar.archive_hash,
            bars.archive_hash,
            len(expected),
            len(days),
            len(expected - observed),
            len(observed - expected),
        )
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise EtfCalendarError() from None
