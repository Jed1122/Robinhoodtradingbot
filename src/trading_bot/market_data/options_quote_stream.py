"""Reverified, bounded quote observations with explicit book invalidation and ns order."""

from __future__ import annotations

import heapq
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading_bot.config import LoadedConfig
from trading_bot.domain import InstrumentId, Quote
from trading_bot.domain.enums import TimestampSource
from trading_bot.domain.options import OptionContract, OptionQuote, executable_quote_reasons
from trading_bot.market_data.databento_native_rows import _rows
from trading_bot.market_data.databento_quote_models import NativeQuoteRow, VerifiedQuoteStage
from trading_bot.market_data.databento_quote_store import quote_snapshots
from trading_bot.market_data.databento_quote_wire import COLUMNS, decode_row
from trading_bot.market_data.options_quote_stream_models import (
    EventState,
    OptionsMarketEvent,
    QuoteFeedBinding,
    QuoteStreamRequest,
)
from trading_bot.market_data.options_records import OptionsDataRecord
from trading_bot.market_data.options_session_inputs import _fact, _ns
from trading_bot.market_data.options_source_models import SourceEvidenceError, check
from trading_bot.market_data.options_source_verify import ceil_available_at, verify_source_bundle
from trading_bot.market_data.recording import content_hash

__all__ = ["OptionsMarketEvent", "QuoteFeedBinding", "QuoteStreamRequest", "iter_quote_events"]
NS = 10**9


def _native_rows(
    dataset: VerifiedQuoteStage,
    paths: tuple[Path, ...],
    connection: Any,
) -> Iterator[NativeQuoteRow]:
    for path in paths:
        for value in _rows(connection, path, COLUMNS):
            yield decode_row(value)


@dataclass(slots=True)
class _Book:
    feed: QuoteFeedBinding
    symbol: str
    contract: OptionContract | None
    initialized: bool = False
    row: NativeQuoteRow | None = None
    deadline: int | None = None

    def clear(self) -> None:
        self.initialized = False
        self.row = None
        self.deadline = None

    def event(
        self,
        at: int,
        state: EventState,
        *,
        row: NativeQuoteRow | None = None,
        record: OptionsDataRecord | None = None,
        reasons: tuple[str, ...] = (),
    ) -> OptionsMarketEvent:
        return OptionsMarketEvent(
            at if row is None else row.ts_event,
            at,
            self.feed.source_id,
            self.feed.manifest.sha256,
            None if row is None else row.record_ordinal,
            self.symbol,
            self.feed.quote_scope,
            state,
            record,
            tuple(sorted(set(reasons))),
        )


def _verify_references(request: QuoteStreamRequest, loaded: LoadedConfig, root: Path) -> None:
    verified = verify_source_bundle(
        request.source_bundle,
        context=request.context,
        loaded=loaded,
        repository_root=root,
    )
    check(verified.status == "verified")
    check(
        len(request.contracts) + len(request.sessions)
        <= loaded.config.options.research_shortlist.max_input_records
    )
    for feed in request.feeds:
        check(feed.manifest in request.source_bundle.manifests)
        check(_fact(verified, "quote_semantics", feed.fact))
    for contract in request.contracts:
        check(_ns(contract.available_at) <= request.start_ns)
        check(
            _fact(
                verified,
                "contract_terms",
                {
                    "kind": "quote-stream-contract-v1",
                    "contract": contract,
                },
            )
        )
        check(
            all(
                s in request.sessions
                for s in contract.eligible_sessions
                if _ns(s.opens_at) < request.end_ns and _ns(s.closes_at) > request.start_ns
            )
        )
    for session in request.sessions:
        check(_fact(verified, "calendar", {"kind": "quote-stream-session-v1", "session": session}))


def _book_record(
    book: _Book,
    row: NativeQuoteRow,
    underlying: _Book,
    loaded: LoadedConfig,
) -> tuple[OptionsDataRecord | None, tuple[str, ...]]:
    age = loaded.config.freshness.max_executable_quote_age_seconds
    skew = loaded.config.market_data.max_cross_response_timestamp_skew_seconds
    if Decimal(row.ts_recv - row.ts_event) > age * NS:
        return None, ("stale_quote",)
    source = book.feed.source_id + ":" + book.feed.quote_scope
    digest = content_hash(
        {"raw_hash": row.raw_hash, "ordinal": row.record_ordinal, "record_hash": row.record_hash}
    )
    value: Quote | OptionQuote
    reasons: tuple[str, ...] = ()
    if book.contract is None:
        if row.bid_px <= 0:
            return None, ("zero_bid",)
        if row.bid_px == row.ask_px and not loaded.config.options.allow_locked_quotes:
            return None, ("locked_quote",)
        value = Quote(
            InstrumentId(book.symbol),
            ceil_available_at(row.ts_event),
            Decimal(row.bid_px) / NS,
            Decimal(row.ask_px) / NS,
            None,
            source,
            digest,
            False,
            TimestampSource.SIMULATED
            if book.feed.source_kind == "synthetic"
            else TimestampSource.PROVIDER,
        )
    else:
        underlying_row = underlying.row
        if not underlying.initialized or underlying_row is None:
            return None, ("underlying_unavailable",)
        if Decimal(row.ts_recv - underlying_row.ts_event) > age * NS:
            return None, ("underlying_stale",)
        if Decimal(abs(row.ts_event - underlying_row.ts_event)) > skew * NS:
            return None, ("underlying_skew",)
        value = OptionQuote(
            book.contract.contract_id,
            Decimal(row.bid_px) / NS,
            Decimal(row.ask_px) / NS,
            row.bid_sz,
            row.ask_sz,
            ceil_available_at(row.ts_event),
            ceil_available_at(row.ts_recv),
            ceil_available_at(underlying_row.ts_event),
            source,
            content_hash(
                (
                    digest,
                    underlying_row.raw_hash,
                    underlying_row.record_ordinal,
                    underlying_row.record_hash,
                )
            ),
            (),
            book.contract.underlying,
        )
        reasons = executable_quote_reasons(
            book.contract,
            value,
            as_of=ceil_available_at(row.ts_recv),
            max_age_seconds=age,
            max_underlying_skew_seconds=skew,
            allow_locked=loaded.config.options.allow_locked_quotes,
        )
    return OptionsDataRecord(
        source,
        book.feed.source_kind,
        row.raw_hash,
        ceil_available_at(row.ts_event),
        ceil_available_at(row.ts_recv),
        value,
    ), reasons


def _run(
    request: QuoteStreamRequest,
    loaded: LoadedConfig,
    streams: list[Iterator[tuple[int, int, int, NativeQuoteRow]]],
    books: dict[str, _Book],
) -> Iterator[OptionsMarketEvent]:
    # Two bounded source cursors, one deadline per symbol, no all-history materialization.
    age_ns = int(loaded.config.freshness.max_executable_quote_age_seconds * NS)
    underlying = books["SPY"]
    boundaries = sorted(
        {request.start_ns, request.end_ns}
        | {
            at
            for s in request.sessions
            for at in (_ns(s.opens_at), _ns(s.closes_at))
            if request.start_ns <= at <= request.end_ns
        }
    )
    boundary_index = 0

    def controls(until: int) -> Iterator[OptionsMarketEvent]:
        nonlocal boundary_index
        while True:
            boundary = boundaries[boundary_index] if boundary_index < len(boundaries) else None
            deadlines = [b.deadline for b in books.values() if b.deadline is not None]
            deadline = min(deadlines) if deadlines else None
            candidates = [v for v in (boundary, deadline) if v is not None and v <= until]
            if not candidates:
                return
            at = min(candidates)
            if at == boundary:
                boundary_index += 1
                for book in books.values():
                    book.clear()
                    yield book.event(at, "session_boundary", reasons=("uninitialized",))
            else:
                for book in books.values():
                    if book.deadline == at:
                        book.clear()
                        yield book.event(at, "gap", reasons=("stale_feed",))

    for at, _, _, row in heapq.merge(*streams):
        if at < request.start_ns:
            continue  # No invisible warmup; initialization is explicit within the window.
        if at >= request.end_ns:
            break
        yield from controls(at)
        book = books[row.raw_symbol]
        if row.action == "R":
            book.clear()
            yield book.event(at, "reset", row=row, reasons=row.reasons)
            continue
        if row.reasons:
            book.clear()
            yield book.event(at, "gap", row=row, reasons=row.reasons)
            continue
        if not any(_ns(s.opens_at) <= at < _ns(s.closes_at) for s in request.sessions):
            book.clear()
            yield book.event(at, "gap", row=row, reasons=("outside_session",))
            continue
        # Requires a separately verified protocol assertion, not merely flag names.
        if row.flags & 32 and row.flags & 128:
            book.initialized = True
        if not book.initialized:
            yield book.event(at, "gap", row=row, reasons=("uninitialized",))
            continue
        # Feed continuity ages independently of cross-feed projection readiness.
        book.row = row
        book.deadline = row.ts_event + age_ns + 1
        record, reasons = _book_record(book, row, underlying, loaded)
        if record is None:
            # Missing underlying does not discard the option's own initialized state,
            # but it can never produce a canonical option quote or a new fill event.
            if book.contract is None or reasons == ("stale_quote",):
                book.clear()
            yield book.event(at, "gap", row=row, reasons=reasons)
            continue
        yield book.event(at, "quote", row=row, record=record, reasons=reasons)
    yield from controls(request.end_ns)


def _stream_rows(
    dataset: VerifiedQuoteStage,
    paths: tuple[Path, ...],
    connection: Any,
    index: int,
) -> Iterator[tuple[int, int, int, NativeQuoteRow]]:
    previous: tuple[int, int] | None = None
    for row in _native_rows(dataset, paths, connection):
        check(row.raw_hash == dataset.profile.raw_hash)
        check(row.raw_symbol in dataset.request.symbols)
        key = row.ts_recv, row.record_ordinal
        check(previous is None or key > previous)
        previous = key
        yield row.ts_recv, index, row.record_ordinal, row


def iter_quote_events(
    request: QuoteStreamRequest,
    *,
    loaded: LoadedConfig,
    repository_root: Path,
) -> Iterator[OptionsMarketEvent]:
    """Validate all archives before the first event; reopening always revalidates.

    Native flags alone do not qualify real providers. Installed reviewed source
    rules remain mandatory and currently empty. No halt or gap coverage is inferred
    from silence or a successfully decoded file. Staleness emits an explicit gap.
    """
    try:
        check(type(request) is QuoteStreamRequest)
        _verify_references(request, loaded, repository_root)
        with ExitStack() as stack:
            streams = []
            books: dict[str, _Book] = {}
            for index, feed in enumerate(
                sorted(request.feeds, key=lambda f: f.quote_scope, reverse=True)
            ):
                dataset, paths, connection = stack.enter_context(
                    quote_snapshots(
                        feed.manifest.path,
                        loaded=loaded,
                        repository_root=repository_root,
                    )
                )
                check(dataset.manifest_hash == feed.manifest.sha256)
                check(dataset.config_hash == loaded.config_hash)
                check(
                    dataset.request.start_ns
                    <= request.start_ns
                    < request.end_ns
                    <= dataset.request.end_ns
                )
                is_underlying = feed.quote_scope == "exchange_specific"
                check(dataset.request.dataset == ("XNAS.ITCH" if is_underlying else "OPRA.PILLAR"))
                expected = (
                    ("SPY",)
                    if is_underlying
                    else tuple(sorted(c.standardized_id for c in request.contracts))
                )
                check(dataset.request.symbols == expected)
                # Preserved provider warnings are not cured by rows being present.
                # Check both feeds before yielding even the first boundary event.
                for session in request.sessions:
                    if _ns(session.opens_at) < request.end_ns and request.start_ns < _ns(
                        session.closes_at
                    ):
                        conditions = tuple(
                            c for c in dataset.conditions if c.trading_date == session.trading_date
                        )
                        check(len(conditions) == 1 and conditions[0].state == "available")
                if is_underlying:
                    books["SPY"] = _Book(feed, "SPY", None)
                else:
                    books.update(
                        {
                            c.standardized_id: _Book(feed, c.standardized_id, c)
                            for c in request.contracts
                        }
                    )
                streams.append(_stream_rows(dataset, paths, connection, index))
            yield from _run(request, loaded, streams, books)
    except GeneratorExit:
        raise
    except Exception:
        raise SourceEvidenceError() from None
