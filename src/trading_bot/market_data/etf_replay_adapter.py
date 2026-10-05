"""Native latest-vintage observations for the source-neutral offline replay.

This pure adapter does not read files or certify the supplied provenance. Archive
readers own receipt verification. Native hashes and false qualification flags are
preserved; no native record is turned into a synthetic market-data record.

The hash-bound projection assumes daily completion at the following New York
midnight, quote replay availability at its native timestamp, calendar open/close
at supplied schedule times, and distribution ex/pay events at that date's exact
calendar opening. These are exploratory timing assumptions, not historical
publication, broker settlement, or verified controls. Missing in-window action
dates deny rather than roll forward. A payable date after the calendar horizon
retains its entitlement without inventing a payment. No split history is inferred.
The dataset retains the holdout; the owning runner must exclude it from development
evaluation.
"""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from trading_bot.clock import require_utc
from trading_bot.domain import AssetClass, MarketClock
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.alpaca_native import (
    MAX_PAGES,
    AlpacaBarRecord,
    AlpacaQuoteRecord,
    AlpacaStockRequest,
)
from trading_bot.market_data.alpaca_quote_semantics import interpret_alpaca_quote
from trading_bot.market_data.etf_calendar import EtfCalendarArchive
from trading_bot.market_data.etf_issuer_distributions import EtfIssuerDistributionArchive
from trading_bot.market_data.etf_native_archive import EtfNativeBarsArchive
from trading_bot.market_data.etf_quote_catalog_models import CatalogQuoteOccurrence
from trading_bot.market_data.etf_source import _ceil_time, _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_latest_vintage import _bar
from trading_bot.simulation.etf_native_models import EtfReplayDataset, EtfReplayEvent

_NEW_YORK = ZoneInfo("America/New_York")
_START = _ns(datetime(2016, 1, 1, tzinfo=UTC))
_END = _ns(datetime(2026, 1, 1, tzinfo=UTC))
_ASSUMPTIONS = (
    "latest_vintage_bar_completion_following_new_york_midnight",
    "native_quote_timestamp_replay_availability_unverified",
    "calendar_session_times_not_observed_controls",
    "distribution_date_to_session_open_assumption",
    "source_coverage_unverified",
    "split_history_unverified",
    "holdout_retained_not_evaluated_by_adapter",
)
_PRIORITY = {"dividend_ex": 0, "dividend_pay": 1, "bar": 2, "session": 3, "control": 4, "quote": 5}


class EtfReplayAdapterError(ValueError):
    def __init__(self) -> None:
        super().__init__("etf_replay_adapter_invalid")


def _check(value: bool) -> None:
    if not value:
        raise EtfReplayAdapterError()


def _validate_bars(bars: EtfNativeBarsArchive) -> None:
    _check(type(bars) is EtfNativeBarsArchive and replace(bars) == bars)
    _require_sha256_hex(bars.manifest_hash, "manifest")
    _check(type(bars.request) is AlpacaStockRequest)
    bars.request.__post_init__()
    _check(bars.request.kind == "bars")
    _check(_START <= bars.request.start_ns < bars.request.end_ns <= _END)
    require_utc(bars.captured_at)
    _check(type(bars.receipt_hashes) is tuple and 0 < len(bars.receipt_hashes) <= MAX_PAGES)
    _check(len(set(bars.receipt_hashes)) == len(bars.receipt_hashes))
    for digest in bars.receipt_hashes:
        _require_sha256_hex(digest, "receipt")
    _check(type(bars.bars) is tuple and 0 < len(bars.bars) <= 10000)
    previous = -1
    for row in bars.bars:
        _check(type(row) is AlpacaBarRecord)
        row.__post_init__()
        _check(replace(row) == row)
        _check(bars.request.start_ns <= row.timestamp_ns < bars.request.end_ns)
        _check(previous < row.timestamp_ns)
        _check(row.page_index < len(bars.receipt_hashes) and row.row_index < bars.request.limit)
        start = _ceil_time(row.timestamp_ns).astimezone(_NEW_YORK)
        _check(start.time() == time() and _ns(start.astimezone(UTC)) == row.timestamp_ns)
        previous = row.timestamp_ns


def native_etf_dataset(
    bars: EtfNativeBarsArchive,
    quotes: tuple[AlpacaQuoteRecord, ...],
    calendar: EtfCalendarArchive,
    distributions: EtfIssuerDistributionArchive,
    quote_provenance_hash: str,
) -> EtfReplayDataset:
    """Project bounded immutable inputs without approving execution or controls.

    Equal-time/repeated native quotes remain separate observations in their input
    order; the sole execution owner must enforce conflicts and shared capacity.
    Unknown round-lot or transition capacity stays ``None``. Even descriptive
    share sizes retain every unverified eligibility reason from the interpreter.
    """
    return _project_dataset(
        bars, quotes, calendar, distributions, quote_provenance_hash, allow_empty=False
    )


def native_etf_baseline(
    bars: EtfNativeBarsArchive,
    calendar: EtfCalendarArchive,
    distributions: EtfIssuerDistributionArchive,
    *,
    catalog_hash: str,
) -> EtfReplayDataset:
    """Quote-free incremental projection; the legacy API still denies empty quotes."""
    return _project_dataset(bars, (), calendar, distributions, catalog_hash, allow_empty=True)


def _project_dataset(
    bars: EtfNativeBarsArchive,
    quotes: tuple[AlpacaQuoteRecord, ...],
    calendar: EtfCalendarArchive,
    distributions: EtfIssuerDistributionArchive,
    quote_provenance_hash: str,
    *,
    allow_empty: bool,
) -> EtfReplayDataset:
    try:
        _validate_bars(bars)
        _check(type(calendar) is EtfCalendarArchive)
        calendar.__post_init__()
        _check(replace(calendar) == calendar)
        _check(type(distributions) is EtfIssuerDistributionArchive)
        distributions.__post_init__()
        _check(replace(distributions) == distributions)
        _require_sha256_hex(quote_provenance_hash, "quote provenance")
        _check(type(quotes) is tuple and len(quotes) <= MAX_PAGES * 1000)
        _check(bool(quotes) or allow_empty)

        events: list[EtfReplayEvent] = []
        by_day = {session.session_date: session for session in calendar.sessions}
        for row in bars.bars:
            payload = _bar(row)
            _check(payload.starts_at.astimezone(_NEW_YORK).date() in by_day)
            _check(payload.ends_at <= bars.captured_at)
            events.append(
                EtfReplayEvent(
                    0,
                    _ns(payload.ends_at),
                    _ns(payload.ends_at),
                    row.record_hash,
                    "bar",
                    bar=payload,
                )
            )

        for index, session in enumerate(calendar.sessions):
            following = calendar.sessions[index + 1] if index + 1 < len(calendar.sessions) else None
            for is_open, at, kind in (
                (True, session.opens_at, "session"),
                (False, session.closes_at, "control"),
            ):
                clock = MarketClock(
                    AssetClass.EQUITY,
                    "XNYS",
                    at,
                    is_open,
                    False,
                    False,
                    False,
                    None if following is None else following.opens_at,
                    session.closes_at
                    if is_open
                    else None
                    if following is None
                    else following.closes_at,
                )
                events.append(
                    EtfReplayEvent(
                        0,
                        _ns(at),
                        _ns(at),
                        content_hash(
                            (
                                "etf-native-calendar-projection-v1",
                                calendar.source_hash,
                                session,
                                kind,
                            )
                        ),
                        "session" if is_open else "control",
                        clock=clock,
                        execution_reasons=("control_coverage_unverified",),
                    )
                )

        payable_after_horizon = False
        for distribution in distributions.distributions:
            _check(distribution.ex_date in by_day)
            after_horizon = distribution.pay_date > calendar.sessions[-1].session_date
            _check(after_horizon or distribution.pay_date in by_day)
            payable_after_horizon |= after_horizon
            for is_ex, day in ((True, distribution.ex_date), (False, distribution.pay_date)):
                if not is_ex and after_horizon:
                    continue
                action_ns = _ns(by_day[day].opens_at)
                events.append(
                    EtfReplayEvent(
                        0,
                        action_ns,
                        action_ns,
                        distribution.row_hash,
                        "dividend_ex" if is_ex else "dividend_pay",
                        action_id=distribution.row_hash,
                        cash_per_share=distribution.amount if is_ex else None,
                    )
                )

        previous = -1
        for quote in quotes:
            _check(type(quote) is AlpacaQuoteRecord)
            _check(_START <= quote.timestamp_ns < _END)
            _check(previous <= quote.timestamp_ns)
            events.append(_quote_event(quote))
            previous = quote.timestamp_ns

        events.sort(key=lambda event: (event.available_at_ns, _PRIORITY[event.kind]))
        provenance = content_hash(
            (
                "etf-native-replay-projection-v1",
                bars.archive_hash,
                quote_provenance_hash,
                calendar.archive_hash,
                distributions.archive_hash,
                _ASSUMPTIONS,
            )
        )
        limitations = tuple(
            sorted(
                set(
                    (
                        *bars.limitations,
                        *calendar.limitations,
                        *distributions.limitations,
                        *_ASSUMPTIONS,
                        *(("payable_after_input_horizon",) if payable_after_horizon else ()),
                    )
                )
            )
        )
        return EtfReplayDataset(
            tuple(replace(event, ordinal=index) for index, event in enumerate(events)),
            provenance,
            "native-latest-vintage",
            limitations,
        )
    except (ValueError, TypeError, ArithmeticError, AttributeError, KeyError, RecursionError):
        raise EtfReplayAdapterError() from None


def _quote_event(quote: AlpacaQuoteRecord) -> EtfReplayEvent:
    interpreted = interpret_alpaca_quote(quote)
    return EtfReplayEvent(
        0,
        quote.timestamp_ns,
        quote.timestamp_ns,
        quote.record_hash,
        "quote",
        bid=quote.bid,
        ask=quote.ask,
        bid_size=interpreted.bid_size_shares,
        ask_size=interpreted.ask_size_shares,
        execution_reasons=interpreted.reasons,
    )


def iter_native_etf_events(
    baseline: EtfReplayDataset, quotes: Iterator[CatalogQuoteOccurrence]
) -> Iterator[EtfReplayEvent]:
    """Lazy stable projection; original execution denials are never stripped."""
    try:
        _check(type(baseline) is EtfReplayDataset)
        replace(baseline)
        _check(baseline.source_kind == "native-latest-vintage")
        _check(not any(event.kind == "quote" for event in baseline.events))
        baseline_events = iter(baseline.events)
        event = next(baseline_events, None)
        previous = -1
        exhausted = object()

        def next_quote() -> EtfReplayEvent | None:
            nonlocal previous
            occurrence = next(quotes, exhausted)
            if occurrence is exhausted:
                return None
            _check(type(occurrence) is CatalogQuoteOccurrence)
            if not isinstance(occurrence, CatalogQuoteOccurrence):
                raise EtfReplayAdapterError()
            replace(occurrence)
            _check(_START <= occurrence.record.timestamp_ns < _END)
            _check(previous <= occurrence.record.timestamp_ns)
            previous = occurrence.record.timestamp_ns
            return _quote_event(occurrence.record)

        quote_event = next_quote()
        ordinal = 0
        while event is not None or quote_event is not None:
            use_baseline = event is not None and (
                quote_event is None
                or (event.available_at_ns, _PRIORITY[event.kind])
                <= (quote_event.available_at_ns, _PRIORITY[quote_event.kind])
            )
            selected = event if use_baseline else quote_event
            if selected is None:
                raise EtfReplayAdapterError()
            yield replace(selected, ordinal=ordinal)
            ordinal += 1
            if use_baseline:
                event = next(baseline_events, None)
            else:
                quote_event = next_quote()
    except (ValueError, TypeError, ArithmeticError, AttributeError, OSError, RuntimeError):
        raise EtfReplayAdapterError() from None
