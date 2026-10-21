"""Pure receipt-visible stock dossiers; structured evidence and questions, no investment view."""

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from trading_bot.clock import require_utc
from trading_bot.market_data.recording import content_hash
from trading_bot.market_data.stock_events import (
    StockEarningsCollection,
    StockEarningsEvent,
    StockEventReceipt,
    StockFiling,
    StockFilingCollection,
)
from trading_bot.market_data.stock_facts import (
    StockFactCollection,
    StockFinancialPeriod,
    StockFundamentals,
    StockObservationReceipt,
)
from trading_bot.market_data.stock_filing_facts import StockFilingEvidence, bind_filing_evidence
from trading_bot.market_data.stock_history_projection import (
    StockHistoryProjectionBatch,
    StockHistoryProjectionContext,
    StockHistorySymbolOutcome,
)

type _Facts = StockFactCollection[StockFundamentals] | StockFactCollection[StockFinancialPeriod]
type _Receipt = StockObservationReceipt | StockEventReceipt
type _Period = Literal["annual", "quarterly"]
type _Pagination = Literal["more", "terminal", "unknown"]


def _check(valid: bool) -> None:
    if not valid:
        raise ValueError("stock_dossiers_invalid")


def _symbol(value: str) -> str:
    _check(
        type(value) is str and re.fullmatch(r"[A-Z0-9][A-Z0-9.$+^=/@_-]{0,31}", value) is not None
    )
    return value


@dataclass(frozen=True, slots=True)
class StockResearchQuestion:
    code: str
    text: str


_QUESTIONS = (
    StockResearchQuestion(
        "reconcile_financial_periods",
        "Which period-matched SEC or issuer records establish financial values and currency?",
    ),
    StockResearchQuestion(
        "verify_history_quality",
        "Which evidence resolves history quality, missing sessions and actual bar completion?",
    ),
    StockResearchQuestion(
        "verify_earnings_publication",
        "Which issuer evidence separates actual earnings, estimates and scheduled publication?",
    ),
    StockResearchQuestion(
        "review_filing_contents",
        "Which filing contents remain unreviewed and which index pages remain uncollected?",
    ),
    StockResearchQuestion(
        "establish_source_coverage",
        "Which independent evidence establishes source coverage, identity and corporate actions?",
    ),
)


@dataclass(frozen=True, slots=True)
class StockDossierSource:
    receipt: _Receipt
    collection_observation_hash: str
    normalized_observation_hash: str | None
    requested_symbols: tuple[str, ...]
    reported_symbols: tuple[str, ...]
    not_found: tuple[str, ...]
    unavailable_symbols: tuple[str, ...]
    null_row_count: int | None
    results_missing: bool | None
    scope_verified: bool | None
    limitations: tuple[str, ...]
    financial_period: _Period | None = None
    projection_context: StockHistoryProjectionContext | None = None
    filing_pagination_state: _Pagination | None = None

    @property
    def tool(self) -> str:
        return self.receipt.tool

    @property
    def is_local_projection(self) -> bool:
        return self.projection_context is not None


@dataclass(frozen=True, slots=True)
class StockDossierHistory:
    outcome: StockHistorySymbolOutcome
    bar_count: int | None
    omitted_interpolated_count: int | None
    null_bar_count: int | None
    completion_unknown_count: int | None
    raw_basis_unknown_count: int | None
    calendar_coverage_verified: Literal[False] = field(default=False, init=False)

    @property
    def status(self) -> Literal["normalized", "unavailable", "quarantined"]:
        return self.outcome.status


@dataclass(frozen=True, slots=True)
class StockDossier:
    symbol: str
    as_of: datetime
    fundamentals: StockFundamentals | None
    financial_periods: tuple[StockFinancialPeriod, ...]
    history: StockDossierHistory | None
    earnings: tuple[StockEarningsEvent, ...]
    filing_index: tuple[StockFiling, ...]
    sources: tuple[StockDossierSource, ...]
    gaps: tuple[str, ...]
    filing_evidence: tuple[StockFilingEvidence, ...] = ()
    questions: tuple[StockResearchQuestion, ...] = field(default=_QUESTIONS, init=False)
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)

    @property
    def dossier_hash(self) -> str:
        version = "stock-dossier-v2" if self.filing_evidence else "stock-dossier-v1"
        return str(content_hash((version, stock_dossier_document(self))))


def _filing_numbers(value: Any) -> Any:
    """Exact filing decimals may exceed the shared portfolio-number display range."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _filing_numbers(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return tuple(_filing_numbers(item) for item in value)
    return value


def stock_dossier_document(
    dossier: StockDossier, *, include_empty_filing_evidence: bool = False
) -> dict[str, Any]:
    """Keep legacy documents exact; expose filing availability and content identities."""
    document = asdict(dossier)
    if dossier.filing_evidence:
        document["filing_evidence"] = tuple(
            {
                **_filing_numbers(asdict(evidence)),
                "available_at": evidence.available_at,
                "evidence_hash": evidence.evidence_hash,
            }
            for evidence in dossier.filing_evidence
        )
    elif not include_empty_filing_evidence:
        document.pop("filing_evidence")
    return document


@dataclass(slots=True)
class _Parts:
    fundamentals: StockFundamentals | None = None
    financials: list[StockFinancialPeriod] = field(default_factory=list)
    history: StockDossierHistory | None = None
    earnings: tuple[StockEarningsEvent, ...] = ()
    filings: tuple[StockFiling, ...] = ()
    sources: list[StockDossierSource] = field(default_factory=list)
    filing_evidence: list[StockFilingEvidence] = field(default_factory=list)


def _visible(receipt: _Receipt, as_of: datetime) -> bool:
    try:
        return require_utc(receipt.received_at) <= as_of
    except ValueError:
        raise ValueError("stock_dossiers_invalid") from None


def _source_key(source: StockDossierSource) -> tuple[str, str, str]:
    return (source.tool, source.financial_period or "", source.collection_observation_hash)


def _gaps(parts: _Parts) -> tuple[str, ...]:
    gaps = {
        "financial_currency_unknown",
        "history_calendar_unknown",
        "history_exact_completion_time_unknown",
        "filing_contents_unreviewed",
        "filing_history_completeness_unknown",
        "exact_publication_times_unknown",
        "source_authenticity_unqualified",
    }
    if parts.filing_evidence:
        gaps.update({"filing_units_unqualified", "filing_entity_mapping_unknown"})
    if parts.fundamentals is None:
        gaps.add("fundamentals_absent")
    elif parts.fundamentals.missing_metrics:
        gaps.add("fundamental_metrics_missing")
    if not parts.financials:
        gaps.add("financials_absent")
    elif any(row.missing_metrics for row in parts.financials):
        gaps.add("financial_metrics_missing")
    if parts.history is None:
        gaps.update({"history_absent", "history_completion_unknown", "raw_price_basis_unknown"})
    else:
        history = parts.history
        if history.status != "normalized":
            gaps.add("history_" + history.status)
        if (
            history.completion_unknown_count is None
            or history.completion_unknown_count > 0
            or not history.bar_count
        ):
            gaps.add("history_completion_unknown")
        if (
            history.raw_basis_unknown_count is None
            or history.raw_basis_unknown_count > 0
            or not history.bar_count
        ):
            gaps.add("raw_price_basis_unknown")
        normalized = history.outcome.normalized
        if normalized is not None and any(row.interpolated is None for row in normalized.records):
            gaps.add("history_interpolation_unknown")
        if normalized is not None and normalized.completed_before is not None:
            gaps.add("history_completion_caller_declared")
        if normalized is not None and normalized.request_adjustment_type == "none":
            gaps.add("raw_price_basis_caller_declared")
    if not parts.earnings:
        gaps.add("earnings_absent")
    if not any(row.eps_actual is not None for row in parts.earnings):
        gaps.add("earnings_actuals_absent")
    filing_sources = [row for row in parts.sources if row.tool == "get_sec_filing_index"]
    if not filing_sources:
        gaps.add("filing_index_absent")
    if not parts.filings:
        gaps.add("filing_records_absent")
    if not filing_sources or any(
        row.filing_pagination_state != "terminal" for row in filing_sources
    ):
        gaps.add("filings_pagination_incomplete")
    for source in parts.sources:
        if source.scope_verified is not True:
            gaps.add("source_scope_unverified")
        if source.results_missing is True:
            gaps.add("source_results_missing")
        if source.null_row_count:
            gaps.add("source_null_rows")
        if source.tool == "get_financials" and source.financial_period is None:
            gaps.add("financial_period_unknown")
    return tuple(sorted(gaps))


def build_stock_dossiers(
    *,
    as_of: datetime,
    facts: tuple[_Facts, ...],
    history: tuple[StockHistoryProjectionBatch, ...],
    earnings: tuple[StockEarningsCollection, ...],
    filings: tuple[StockFilingCollection, ...],
    filing_evidence: tuple[StockFilingEvidence, ...] = (),
) -> tuple[StockDossier, ...]:
    """Join normalized observations by exact symbol, retaining unknowns and receipt visibility."""
    try:
        cutoff = require_utc(as_of)
    except ValueError:
        raise ValueError("stock_dossiers_invalid") from None
    _check(
        all(type(group) is tuple for group in (facts, history, earnings, filings, filing_evidence))
    )
    _check(sum(len(group) for group in (facts, history, earnings, filings, filing_evidence)) <= 256)
    _check(all(isinstance(row, StockFactCollection) for row in facts))
    _check(all(isinstance(row, StockHistoryProjectionBatch) for row in history))
    _check(all(isinstance(row, StockEarningsCollection) for row in earnings))
    _check(all(isinstance(row, StockFilingCollection) for row in filings))
    parts: dict[str, _Parts] = {}
    seen: set[tuple[str, str, str]] = set()
    source_seen: set[tuple[str, str, str]] = set()
    record_count = 0

    def add(symbol: str, source: StockDossierSource, identity: str) -> _Parts:
        nonlocal record_count
        symbol = _symbol(symbol)
        key = (symbol, source.tool, identity)
        source_key = (symbol, source.tool, source.receipt.observation_sha256)
        _check(key not in seen and source_key not in source_seen)
        seen.add(key)
        source_seen.add(source_key)
        company = parts.setdefault(symbol, _Parts())
        _check(len(parts) <= 1000 and record_count <= 100000)
        company.sources.append(source)
        return company

    for collection in facts:
        _check(isinstance(collection, StockFactCollection))
        if not _visible(collection.receipt, cutoff):
            continue
        tool = collection.receipt.tool
        _check(tool in ("get_equity_fundamentals", "get_financials"))
        _check(type(collection.records) is tuple)
        groups = (collection.reported_symbols, collection.not_found, collection.unavailable_symbols)
        _check(all(type(group) is tuple for group in groups))
        requested = collection.requested_symbols or ()
        _check(type(requested) is tuple)
        symbols = set(
            (
                *requested,
                *collection.reported_symbols,
                *collection.not_found,
                *collection.unavailable_symbols,
            )
        )
        _check(all(_symbol(symbol) == symbol for symbol in symbols))
        _check(len(set(collection.reported_symbols)) == len(collection.reported_symbols))
        _check(not set(collection.reported_symbols).intersection(collection.not_found))
        if requested:
            _check(len(set(requested)) == len(requested) and symbols == set(requested))
        record_count += len(collection.records)
        by_symbol: dict[str, list[StockFundamentals | StockFinancialPeriod]] = {}
        financial_keys: set[tuple[str, str, int, str]] = set()
        for record in collection.records:
            _check(
                record.symbol in collection.reported_symbols
                and record.receipt == collection.receipt
            )
            _check(
                isinstance(record, StockFundamentals)
                if tool == "get_equity_fundamentals"
                else isinstance(record, StockFinancialPeriod)
            )
            if isinstance(record, StockFinancialPeriod):
                label = (
                    "annual"
                    if record.period == "annual"
                    else (
                        str(record.fiscal_quarter)
                        if record.fiscal_quarter is not None
                        else record.period_end.isoformat()
                    )
                )
                financial_key = (record.symbol, record.period, record.fiscal_year, label)
                _check(financial_key not in financial_keys)
                financial_keys.add(financial_key)
            by_symbol.setdefault(record.symbol, []).append(record)
        for symbol in sorted(symbols):
            records = by_symbol.get(symbol, [])
            periods = {row.period for row in records if isinstance(row, StockFinancialPeriod)}
            _check(len(periods) <= 1)
            period = next(iter(periods)) if periods else None
            source = StockDossierSource(
                collection.receipt,
                collection.observation_hash,
                collection.observation_hash,
                requested,
                collection.reported_symbols,
                collection.not_found,
                collection.unavailable_symbols,
                collection.null_row_count,
                collection.results_missing,
                collection.scope_verified,
                collection.limitations,
                financial_period=period,
            )
            identity = (
                "snapshot"
                if tool == "get_equity_fundamentals"
                else period or "unknown:" + collection.receipt.observation_sha256
            )
            company = add(symbol, source, identity)
            if tool == "get_equity_fundamentals":
                _check(len(records) <= 1)
                if records:
                    fundamental = records[0]
                    _check(isinstance(fundamental, StockFundamentals))
                    if isinstance(fundamental, StockFundamentals):
                        company.fundamentals = fundamental
            else:
                company.financials.extend(
                    row for row in records if isinstance(row, StockFinancialPeriod)
                )

    for batch in history:
        _check(isinstance(batch, StockHistoryProjectionBatch))
        if not _visible(batch.receipt, cutoff):
            continue
        _check(batch.receipt.tool == "get_equity_historicals")
        _check(type(batch.requested_symbols) is tuple and type(batch.outcomes) is tuple)
        _check(tuple(row.symbol for row in batch.outcomes) == batch.requested_symbols)
        for outcome in batch.outcomes:
            context, normalized = outcome.context, outcome.normalized
            _check(context.original_source_sha256 == batch.receipt.observation_sha256)
            _check(context.original_requested_symbols == batch.requested_symbols)
            _check(
                (context.original_result_index is None)
                != (context.original_not_found_index is None)
            )
            if normalized is None:
                _check(outcome.status == "quarantined")
                counts = StockDossierHistory(outcome, None, None, None, None, None)
            else:
                _check(normalized.receipt.tool == "get_equity_historicals")
                _check(normalized.receipt.received_at == batch.receipt.received_at)
                _check(normalized.receipt.observation_sha256 == context.projected_payload_sha256)
                _check(normalized.requested_symbols == (outcome.symbol,))
                _check(
                    all(
                        row.symbol == outcome.symbol and row.receipt == normalized.receipt
                        for row in normalized.records
                    )
                )
                _check(
                    all(
                        row.symbol == outcome.symbol for row in normalized.omitted_interpolated_bars
                    )
                )
                _check(outcome.status == ("normalized" if normalized.records else "unavailable"))
                record_count += len(normalized.records) + normalized.omitted_interpolated_count
                counts = StockDossierHistory(
                    outcome,
                    len(normalized.records),
                    normalized.omitted_interpolated_count,
                    normalized.null_row_count,
                    sum(row.completion_status == "unknown" for row in normalized.records),
                    sum(row.price_basis == "unknown" for row in normalized.records),
                )
            source = StockDossierSource(
                batch.receipt,
                batch.observation_hash,
                None if normalized is None else normalized.observation_hash,
                batch.requested_symbols,
                () if normalized is None else normalized.reported_symbols,
                () if normalized is None else normalized.not_found,
                () if normalized is None else normalized.unavailable_symbols,
                None if normalized is None else normalized.null_row_count,
                None if normalized is None else normalized.results_missing,
                None if normalized is None else normalized.scope_verified,
                batch.limitations,
                projection_context=context,
            )
            add(outcome.symbol, source, "series").history = counts

    event_collections: tuple[StockEarningsCollection | StockFilingCollection, ...] = (
        *earnings,
        *filings,
    )
    for event_collection in event_collections:
        _check(isinstance(event_collection, (StockEarningsCollection, StockFilingCollection)))
        if not _visible(event_collection.receipt, cutoff):
            continue
        is_earnings = isinstance(event_collection, StockEarningsCollection)
        _check(
            event_collection.receipt.tool
            == ("get_earnings_results" if is_earnings else "get_sec_filing_index")
        )
        symbol = _symbol(event_collection.requested_symbol)
        _check(type(event_collection.records) is tuple)
        _check(
            all(
                row.symbol == symbol and row.receipt == event_collection.receipt
                for row in event_collection.records
            )
        )
        record_count += len(event_collection.records)
        source = StockDossierSource(
            event_collection.receipt,
            event_collection.observation_hash,
            event_collection.observation_hash,
            (symbol,),
            (symbol,) if event_collection.records else (),
            event_collection.not_found
            if isinstance(event_collection, StockEarningsCollection)
            else (),
            (),
            event_collection.null_row_count,
            event_collection.response_results_missing,
            event_collection.scope_verified,
            event_collection.limitations,
            filing_pagination_state=event_collection.pagination_state
            if isinstance(event_collection, StockFilingCollection)
            else None,
        )
        company = add(symbol, source, "collection")
        if isinstance(event_collection, StockEarningsCollection):
            company.earnings = event_collection.records
        else:
            company.filings = event_collection.records

    evidence_seen: set[str] = set()
    for evidence in filing_evidence:
        _check(type(evidence) is StockFilingEvidence)
        try:
            checked = bind_filing_evidence(
                evidence.index, evidence.catalog, evidence.facts, as_of=cutoff
            )
        except (ValueError, TypeError, OverflowError):
            raise ValueError("stock_dossiers_invalid") from None
        _check(checked == evidence)
        _check(sum(collection == checked.index for collection in filings) == 1)
        _check(checked.evidence_hash not in evidence_seen)
        evidence_seen.add(checked.evidence_hash)
        record_count += len(checked.facts.records)
        _check(record_count <= 100000)
        symbol = checked.filing.symbol
        _check(symbol in parts)
        parts[symbol].filing_evidence.append(checked)

    return tuple(
        StockDossier(
            symbol,
            cutoff,
            company.fundamentals,
            tuple(
                sorted(
                    company.financials, key=lambda row: (row.period, -row.period_end.toordinal())
                )
            ),
            company.history,
            company.earnings,
            company.filings,
            tuple(sorted(company.sources, key=_source_key)),
            _gaps(company),
            tuple(company.filing_evidence),
        )
        for symbol, company in sorted(parts.items())
    )
