"""Bounded supplied-input inventory, never dataset or execution acceptance."""

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

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

    @property
    def inventory_hash(self) -> str:
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
    replace(calendar)
    if calendar.source_qualified is not False or calendar.evidence_promotable is not False:
        raise ValueError("capital_daily_inventory_invalid")
    expected = {row.session_date for row in calendar.sessions if start <= row.session_date < end}
    if not expected:
        raise ValueError("capital_daily_inventory_invalid")
    sources: dict[str, CapitalDailyArchive] = {}
    for archive in archives:
        if type(archive) is not CapitalDailyArchive:
            raise ValueError("capital_daily_inventory_invalid")
        replace(archive)
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
