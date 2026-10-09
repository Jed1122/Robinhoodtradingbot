"""Bounded supplied-input inventory, never dataset or execution acceptance."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.alpaca_capital_native import assess_capital_daily_pages
from trading_bot.market_data.etf_calendar import EtfCalendarArchive
from trading_bot.market_data.etf_capital_archive import CapitalDailyArchive
from trading_bot.market_data.etf_source import _ceil_time, _ns
from trading_bot.market_data.recording import content_hash

_SYMBOLS = ("SPY", "QQQ", "IWM", "SHY", "IEF")
_ZONE = ZoneInfo("America/New_York")


@dataclass(frozen=True, slots=True)
class CapitalSymbolInventory:
    symbol: str
    archive_hash: str | None
    expected_session_count: int
    observed_bar_count: int | None
    missing_session_count: int | None
    pagination_complete: bool | None
    split_count: None = None
    distribution_count: None = None
    action_coverage_known: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if (
            type(self.symbol) is not str
            or self.symbol not in _SYMBOLS
            or type(self.expected_session_count) is not int
            or not 0 < self.expected_session_count <= 4000
            or self.action_coverage_known is not False
            or self.split_count is not None
            or self.distribution_count is not None
        ):
            raise ValueError("capital_daily_inventory_invalid")
        if self.archive_hash is None:
            if any(
                value is not None
                for value in (
                    self.observed_bar_count,
                    self.missing_session_count,
                    self.pagination_complete,
                )
            ):
                raise ValueError("capital_daily_inventory_invalid")
        else:
            _require_sha256_hex(self.archive_hash, "inventory archive")
            if (
                type(self.observed_bar_count) is not int
                or not 0 <= self.observed_bar_count <= self.expected_session_count
                or type(self.missing_session_count) is not int
                or self.missing_session_count
                != self.expected_session_count - self.observed_bar_count
                or type(self.pagination_complete) is not bool
            ):
                raise ValueError("capital_daily_inventory_invalid")


@dataclass(frozen=True, slots=True)
class CapitalDailyInventory:
    start: date
    end: date
    calendar_hash: str
    symbols: tuple[CapitalSymbolInventory, ...]
    reasons: tuple[str, ...]
    ready_for_strategy_projection: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_sha256_hex(self.calendar_hash, "inventory calendar")
        if (
            type(self.start) is not date
            or type(self.end) is not date
            or self.start >= self.end
            or type(self.symbols) is not tuple
            or len(self.symbols) != len(_SYMBOLS)
            or self.source_qualified is not False
            or self.evidence_promotable is not False
            or self.ready_for_strategy_projection is not False
            or type(self.reasons) is not tuple
            or len(self.reasons) > 16
            or any(type(reason) is not str for reason in self.reasons)
        ):
            raise ValueError("capital_daily_inventory_invalid")
        for row in self.symbols:
            if type(row) is not CapitalSymbolInventory:
                raise ValueError("capital_daily_inventory_invalid")
            row.__post_init__()
        if tuple(row.symbol for row in self.symbols) != _SYMBOLS:
            raise ValueError("capital_daily_inventory_invalid")

    @property
    def inventory_hash(self) -> str:
        self.__post_init__()
        return content_hash(("capital-daily-inventory-v1", self))


def capital_daily_inventory(
    archives: tuple[CapitalDailyArchive, ...],
    calendar: EtfCalendarArchive,
    *,
    start: date,
    end: date,
) -> CapitalDailyInventory:
    """Missing archives and action records remain unknown, not zero."""
    if (
        type(archives) is not tuple
        or len(archives) > len(_SYMBOLS)
        or type(calendar) is not EtfCalendarArchive
        or type(start) is not date
        or type(end) is not date
        or not date(2016, 1, 1) <= start < end <= date(2026, 1, 1)
    ):
        raise ValueError("capital_daily_inventory_invalid")
    calendar.__post_init__()
    if (
        type(calendar.source_kind) is not str
        or calendar.source_kind != "alpaca-connector-v2-calendar-v1"
        or type(calendar.limitations) is not tuple
        or any(type(value) is not str for value in calendar.limitations)
        or calendar.limitations
        != (
            "connector_payload_not_native_http_receipt",
            "legacy_v2_new_york_timezone_projection",
            "calendar_does_not_prove_quote_control_or_action_coverage",
        )
        or calendar.source_qualified is not False
        or calendar.evidence_promotable is not False
    ):
        raise ValueError("capital_daily_inventory_invalid")
    expected = {row.session_date for row in calendar.sessions if start <= row.session_date < end}
    if not expected:
        raise ValueError("capital_daily_inventory_invalid")
    sources: dict[str, CapitalDailyArchive] = {}
    for archive in archives:
        if type(archive) is not CapitalDailyArchive:
            raise ValueError("capital_daily_inventory_invalid")
        archive.__post_init__()
        request = archive.request
        if (
            request.symbol in sources
            or request.start_ns != _ns(datetime.combine(start, time(), UTC))
            or request.end_ns != _ns(datetime.combine(end, time(), UTC))
        ):
            raise ValueError("capital_daily_inventory_invalid")
        sources[request.symbol] = archive
    rows: list[CapitalSymbolInventory] = []
    reasons = ["corporate_action_and_distribution_inputs_missing", "source_chronology_unqualified"]
    for symbol in _SYMBOLS:
        source = sources.get(symbol)
        if source is None:
            rows.append(CapitalSymbolInventory(symbol, None, len(expected), None, None, None))
            reasons.append(f"{symbol}:archive_missing")
            continue
        observed: set[date] = set()
        for page in source.pages:
            for record in page.records:
                bar = record.bar
                instant = _ceil_time(bar.timestamp_ns).astimezone(_ZONE)
                day = instant.date()
                if (
                    instant.time() != time()
                    or _ns(instant.astimezone(UTC)) != bar.timestamp_ns
                    or day not in expected
                    or day in observed
                ):
                    raise ValueError("capital_daily_inventory_invalid")
                observed.add(day)
        assessment = assess_capital_daily_pages(source.pages)
        rows.append(
            CapitalSymbolInventory(
                symbol,
                source.archive_hash,
                len(expected),
                len(observed),
                len(expected - observed),
                assessment.pagination_complete,
            )
        )
        if expected != observed:
            reasons.append(f"{symbol}:sessions_missing")
        if not assessment.pagination_complete:
            reasons.append(f"{symbol}:pagination_incomplete")
    return CapitalDailyInventory(start, end, calendar.archive_hash, tuple(rows), tuple(reasons))
