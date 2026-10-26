"""Bounded descriptive admission of original daily MCP evidence, never authenticity."""

import hashlib
import json
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Final, Literal, cast
from zoneinfo import ZoneInfo

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.recording import content_hash
from trading_bot.market_data.stock_split_comparison import (
    StockSplitSeries,
    parse_stock_split_series,
)

ROBINHOOD_DAILY_TOOL: Final = "mcp__robinhood_2__get_equity_historicals"
ROBINHOOD_DAILY_METADATA_SHA256: Final = (
    "40b726da941850f2e4911f750ce67758668f9976019beab08126bc6dbdee8c36"
)
_FLAGS = (
    "qualified",
    "source_qualified",
    "strategy_qualified",
    "investment_eligible",
    "trading_enabled",
    "live_authorized",
    "authenticated",
)
_LIMITATIONS = (
    "descriptive_split_price_features_not_total_returns_or_forecasts",
    "source_receipts_and_calendar_not_independently_authenticated",
    "session_dates_derived_from_midnight_utc_labels_not_open_instants",
    "calendar_timezone_is_explicit_external_interpretation",
    "positive_volume_non_synthetic_inference_does_not_change_native_unknown",
    "coverage_and_lag_policy_are_uncalibrated_hypotheses",
    "quote_currency_and_historical_vintage_unverified",
    "no_historical_universe_corporate_action_or_investment_qualification",
)


class StockDailySeriesError(ValueError):
    def __init__(self) -> None:
        super().__init__("stock_daily_series_invalid")


def _check(condition: bool) -> None:
    if not condition:
        raise StockDailySeriesError()


def _utc(value: datetime) -> datetime:
    return require_utc(value)


def _same(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if is_dataclass(left) and not isinstance(left, type):
        return all(_same(getattr(left, f.name), getattr(right, f.name)) for f in fields(left))
    if isinstance(left, tuple) and isinstance(right, tuple):
        return len(left) == len(right) and all(
            _same(a, b) for a, b in zip(left, right, strict=True)
        )
    return bool(left == right)


@dataclass(frozen=True, slots=True, repr=False)
class _DescriptiveScope:
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    authenticated: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True, repr=False)
class StockDailySession:
    session_date: date
    open_wire: str
    close_wire: str
    opens_at: datetime
    closes_at: datetime


@dataclass(frozen=True, slots=True, repr=False)
class StockDailyCalendar(_DescriptiveScope):
    request_start: date
    request_end: date
    received_at: datetime
    original_content_json: bytes
    content_sha256: str
    market_timezone: Literal["America/New_York"]
    sessions: tuple[StockDailySession, ...]


@dataclass(frozen=True, slots=True, repr=False)
class StockDailySeries(_DescriptiveScope):
    series: StockSplitSeries | None
    calendar: StockDailyCalendar | None
    source_tool: str
    source_metadata_sha256: str
    as_of: datetime
    minimum_observations: int
    maximum_closed_session_lag_days: int
    status: Literal["descriptive_admissible", "ineligible"]
    reason_codes: tuple[str, ...]
    session_dates: tuple[date, ...]
    non_synthetic_basis: tuple[Literal["native_false", "positive_volume_contract_inference"], ...]
    quote_currency: None = field(default=None, init=False)
    price_basis: Literal["split"] = field(default="split", init=False)
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)

    @property
    def evidence_hash(self) -> str:
        value = validate_stock_daily_series(self)
        source, calendar = value.series, value.calendar
        return str(
            content_hash(
                {
                    "schema": "stock-daily-descriptive-series-v1",
                    "source": None
                    if source is None
                    else {
                        "request_sha256": source.request.request_sha256,
                        "content_sha256": source.content_sha256,
                        "received_at": source.received_at,
                    },
                    "calendar": None
                    if calendar is None
                    else {
                        "content_sha256": calendar.content_sha256,
                        "received_at": calendar.received_at,
                        "market_timezone": calendar.market_timezone,
                        "sessions": calendar.sessions,
                    },
                    "source_tool": value.source_tool,
                    "source_metadata_sha256": value.source_metadata_sha256,
                    "as_of": value.as_of,
                    "minimum_observations": value.minimum_observations,
                    "maximum_closed_session_lag_days": value.maximum_closed_session_lag_days,
                    "status": value.status,
                    "reason_codes": value.reason_codes,
                    "session_dates": value.session_dates,
                    "non_synthetic_basis": value.non_synthetic_basis,
                    "quote_currency": None,
                    "price_basis": "split",
                    "limitations": value.limitations,
                    "source_qualified": False,
                    "authenticated": False,
                }
            )
        )


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        _check(key not in result)
        result[key] = value
    return result


def _constant(_value: str) -> object:
    raise StockDailySeriesError()


def _object(value: object, keys: set[str]) -> dict[str, object]:
    _check(type(value) is dict)
    result = cast(dict[str, object], value)
    _check(set(result) == keys)
    return result


def _date(value: object) -> date:
    _check(type(value) is str and len(value) == 10)
    result = date.fromisoformat(cast(str, value))
    _check(result.isoformat() == value)
    return result


def parse_stock_daily_calendar(
    original_content_json: bytes,
    *,
    expected_sha256: str,
    received_at: datetime,
    market_timezone: Literal["America/New_York"],
) -> StockDailyCalendar:
    """Parse original Alpaca MCP result-string bytes with an external clock context."""
    try:
        received_at = _utc(received_at)
        _require_sha256_hex(expected_sha256, "daily calendar")
        _check(
            type(original_content_json) is bytes
            and 0 < len(original_content_json) <= 8 * 1024 * 1024
        )
        _check(hashlib.sha256(original_content_json).hexdigest() == expected_sha256)
        _check(type(market_timezone) is str and market_timezone == "America/New_York")
        value = _object(
            json.loads(
                original_content_json,
                object_pairs_hook=_pairs,
                parse_float=Decimal,
                parse_constant=_constant,
            ),
            {"request", "calendar"},
        )
        request = _object(value["request"], {"start_date", "end_date"})
        start, end = _date(request["start_date"]), _date(request["end_date"])
        _check(start <= end)
        native = value["calendar"]
        _check(type(native) is list and len(cast(list[object], native)) <= 10000)
        sessions: list[StockDailySession] = []
        previous: date | None = None
        for item in cast(list[object], native):
            row = _object(item, {"date", "open", "close"})
            day = _date(row["date"])
            _check(start <= day <= end and day.weekday() < 5)
            _check(previous is None or previous < day)
            previous = day
            opening, closing = row["open"], row["close"]
            _check(type(opening) is str and opening == day.isoformat() + "T09:30:00")
            _check(
                type(closing) is str
                and closing
                in {
                    day.isoformat() + "T13:00:00",
                    day.isoformat() + "T16:00:00",
                }
            )
            opens_at = (
                datetime.fromisoformat(cast(str, opening))
                .replace(tzinfo=ZoneInfo(market_timezone))
                .astimezone(UTC)
            )
            closes_at = (
                datetime.fromisoformat(cast(str, closing))
                .replace(tzinfo=ZoneInfo(market_timezone))
                .astimezone(UTC)
            )
            sessions.append(
                StockDailySession(day, cast(str, opening), cast(str, closing), opens_at, closes_at)
            )
        return StockDailyCalendar(
            start,
            end,
            received_at,
            original_content_json,
            expected_sha256,
            market_timezone,
            tuple(sessions),
        )
    except (ValueError, TypeError, AttributeError, ArithmeticError, KeyError, RecursionError):
        raise StockDailySeriesError() from None


def admit_stock_daily_series(
    series: StockSplitSeries | None,
    calendar: StockDailyCalendar | None,
    *,
    source_tool: str,
    source_metadata_sha256: str,
    as_of: datetime,
    minimum_observations: int = 201,
    maximum_closed_session_lag_days: int = 7,
) -> StockDailySeries:
    """Reparse original evidence; apply explicit, uncalibrated descriptive hypotheses."""
    try:
        as_of = _utc(as_of)
        _check(type(source_tool) is str)
        _require_sha256_hex(source_metadata_sha256, "daily source metadata")
        _check(type(minimum_observations) is int and 1 <= minimum_observations <= 10000)
        _check(
            type(maximum_closed_session_lag_days) is int
            and 0 <= maximum_closed_session_lag_days <= 36500
        )
        _check(series is None or type(series) is StockSplitSeries)
        _check(calendar is None or type(calendar) is StockDailyCalendar)
        reasons: list[str] = []
        dates: tuple[date, ...] = ()
        basis: list[Literal["native_false", "positive_volume_contract_inference"]] = []
        if (
            source_tool != ROBINHOOD_DAILY_TOOL
            or source_metadata_sha256 != ROBINHOOD_DAILY_METADATA_SHA256
        ):
            reasons.append("source_contract_mismatch")
        if series is None:
            reasons.append("missing_history")
        else:
            rebuilt = parse_stock_split_series(
                series.original_content_json,
                expected_sha256=series.content_sha256,
                request=series.request,
                received_at=series.received_at,
            )
            _check(_same(rebuilt, series))
            if series.received_at > as_of:
                reasons.append("future_source_receipt")
            if series.request.adjustment_type != "split":
                reasons.append("split_adjustment_required")
            if any(
                _utc(t).time() != time.min
                for t in (
                    series.request.start_time,
                    series.request.end_time,
                )
            ):
                reasons.append("midnight_utc_request_required")
            if (
                not series.bars
                or series.null_bar_indices
                or series.results_missing
                or series.bars_missing
                or series.not_found
            ):
                reasons.append("incomplete_history")
            if any(bar.begins_at.time() != time.min for bar in series.bars):
                reasons.append("midnight_utc_label_required")
            if any(bar.session != "reg" for bar in series.bars):
                reasons.append("regular_session_required")
            if any(bar.interpolated is True or bar.volume <= 0 for bar in series.bars):
                reasons.append("non_synthetic_unresolved")
            else:
                basis = [
                    "native_false"
                    if bar.interpolated is False
                    else "positive_volume_contract_inference"
                    for bar in series.bars
                ]
            if len(series.bars) < minimum_observations:
                reasons.append("insufficient_observations")
        if calendar is None:
            reasons.append("missing_calendar")
        else:
            rebuilt_calendar = parse_stock_daily_calendar(
                calendar.original_content_json,
                expected_sha256=calendar.content_sha256,
                received_at=calendar.received_at,
                market_timezone=calendar.market_timezone,
            )
            _check(_same(rebuilt_calendar, calendar))
            dates = tuple(day.session_date for day in calendar.sessions)
            if calendar.received_at > as_of:
                reasons.append("future_calendar_receipt")
            if not calendar.sessions:
                reasons.append("empty_calendar")
            if any(day.closes_at > as_of for day in calendar.sessions):
                reasons.append("session_not_closed")
            if calendar.sessions and as_of - calendar.sessions[-1].closes_at > timedelta(
                days=maximum_closed_session_lag_days
            ):
                reasons.append("latest_closed_session_stale")
            if series is not None:
                request = series.request
                if (calendar.request_start, calendar.request_end) != (
                    request.start_time.date(),
                    (request.end_time - timedelta(microseconds=1)).date(),
                ):
                    reasons.append("calendar_request_mismatch")
                if tuple(bar.begins_at.date() for bar in series.bars) != dates:
                    reasons.append("calendar_bar_dates_mismatch")
                if any(day.closes_at > series.received_at for day in calendar.sessions):
                    reasons.append("session_not_closed_at_source_receipt")
        return StockDailySeries(
            series,
            calendar,
            source_tool,
            source_metadata_sha256,
            as_of,
            minimum_observations,
            maximum_closed_session_lag_days,
            "ineligible" if reasons else "descriptive_admissible",
            tuple(reasons),
            dates,
            tuple(basis),
        )
    except (ValueError, TypeError, AttributeError, ArithmeticError, KeyError, RecursionError):
        raise StockDailySeriesError() from None


def validate_stock_daily_series(value: StockDailySeries) -> StockDailySeries:
    """Rebuild before any use, including detection of mutations to frozen DTO graphs."""
    try:
        _check(type(value) is StockDailySeries)
        _check(all(getattr(value, name) is False for name in _FLAGS))
        rebuilt = admit_stock_daily_series(
            value.series,
            value.calendar,
            source_tool=value.source_tool,
            source_metadata_sha256=value.source_metadata_sha256,
            as_of=value.as_of,
            minimum_observations=value.minimum_observations,
            maximum_closed_session_lag_days=value.maximum_closed_session_lag_days,
        )
        _check(_same(rebuilt, value))
        return rebuilt
    except (ValueError, TypeError, AttributeError, ArithmeticError, KeyError, RecursionError):
        raise StockDailySeriesError() from None
