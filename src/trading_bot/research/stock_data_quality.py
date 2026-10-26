"""Pure dossier diagnostics; policy thresholds are hypotheses, never qualification."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.market_data.recording import content_hash
from trading_bot.market_data.stock_events import StockEventReceipt
from trading_bot.market_data.stock_facts import StockObservationReceipt
from trading_bot.market_data.stock_filing_facts import StockFilingReceipt
from trading_bot.research.stock_dossiers import StockDossier, StockDossierSource

type _Receipt = StockObservationReceipt | StockEventReceipt | StockFilingReceipt
type _ReceiptOrigin = Literal[
    "dossier_source", "linked_local_projection", "unverified_additional_receipt"
]
type _Use = Literal[
    "current_descriptive_research",
    "daily_price_features",
    "financial_comparison",
    "source_qualification",
    "historical_strategy",
    "investment_selection",
    "live_trading",
]


def _check(valid: bool) -> None:
    if not valid:
        raise ValueError("stock_data_quality_invalid")


def _utc(value: datetime) -> datetime:
    try:
        return require_utc(value)
    except (TypeError, ValueError):
        raise ValueError("stock_data_quality_invalid") from None


@dataclass(frozen=True, slots=True)
class StockDataQualityPolicy:
    """Finite investigation thresholds, not calibrated investment criteria."""

    max_receipt_age_seconds: int = 86400
    max_latest_bar_lag_days: int = 7
    max_financial_period_age_days: int = 550
    minimum_history_bars: int = 201

    def __post_init__(self) -> None:
        for value, minimum, maximum in (
            (self.max_receipt_age_seconds, 1, 31536000),
            (self.max_latest_bar_lag_days, 0, 3650),
            (self.max_financial_period_age_days, 0, 36500),
            (self.minimum_history_bars, 1, 100000),
        ):
            _check(type(value) is int and minimum <= value <= maximum)


_DEFAULT_POLICY = StockDataQualityPolicy()


@dataclass(frozen=True, slots=True)
class StockSourceQuality:
    tool: str
    observation_sha256: str
    received_at: datetime
    receipt_age_seconds: Decimal
    collection_observation_hash: str | None
    normalized_observation_hash: str | None
    collection_null_row_count: int | None
    results_missing: bool | None
    scope_verified: bool | None
    reason_codes: tuple[str, ...]
    receipt_origin: _ReceiptOrigin
    original_source_observation_sha256: str | None


@dataclass(frozen=True, slots=True)
class StockHistoryQuality:
    status: Literal["absent", "normalized", "unavailable", "quarantined"]
    bar_count: int | None
    null_bar_count: int | None
    omitted_interpolated_count: int | None
    interpolation_unknown_count: int | None
    session_unknown_count: int | None
    completion_unknown_count: int | None
    raw_basis_unknown_count: int | None
    latest_bar_at: datetime | None
    latest_bar_lag_days: int | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StockFinancialPeriodQuality:
    period: Literal["annual", "quarterly"]
    period_end: date
    receipt_age_seconds: Decimal
    period_age_days: int
    missing_metrics: tuple[str, ...]
    missing_metric_count: int
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StockDataUseRestriction:
    use: _Use
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StockDataQualityAssessment:
    symbol: str
    as_of: datetime
    dossier_hash: str
    policy: StockDataQualityPolicy
    sources: tuple[StockSourceQuality, ...]
    history: StockHistoryQuality
    financial_periods: tuple[StockFinancialPeriodQuality, ...]
    fundamentals_missing_metrics: tuple[str, ...] | None
    fundamentals_market_date: date | None
    fundamentals_market_lag_days: int | None
    financial_currency_unknown_count: int
    filing_fact_count: int
    filing_numeric_missing_count: int
    filing_unit_unknown_count: int
    filing_period_start_unknown_count: int
    filing_entity_unverified_count: int
    descriptive_observations_present: bool
    blocked_uses: tuple[StockDataUseRestriction, ...]
    reason_codes: tuple[str, ...]
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)

    @property
    def assessment_hash(self) -> str:
        return str(content_hash(("stock-data-quality-v1", self)))


def _age(receipt: _Receipt, as_of: datetime) -> Decimal:
    elapsed = as_of - _utc(receipt.received_at)
    _check(elapsed >= timedelta(0))
    # Integer microseconds avoid float rounding at the freshness boundary.
    microseconds = elapsed // timedelta(microseconds=1)
    return Decimal(f"{microseconds // 1000000}.{microseconds % 1000000:06d}")


def _receipts(dossier: StockDossier) -> tuple[_Receipt, ...]:
    receipts: list[_Receipt] = [source.receipt for source in dossier.sources]
    if dossier.fundamentals is not None:
        receipts.append(dossier.fundamentals.receipt)
    receipts.extend(row.receipt for row in dossier.financial_periods)
    receipts.extend(row.receipt for row in dossier.earnings)
    receipts.extend(row.receipt for row in dossier.filing_index)
    if dossier.history is not None and dossier.history.outcome.normalized is not None:
        collection = dossier.history.outcome.normalized
        receipts.append(collection.receipt)
        receipts.extend(row.receipt for row in collection.records)
    for evidence in dossier.filing_evidence:
        _utc(evidence.as_of)
        receipts.extend((evidence.index.receipt, evidence.catalog.receipt, evidence.facts.receipt))
        receipts.append(evidence.filing.receipt)
        receipts.extend(row.receipt for row in evidence.index.records)
        receipts.extend(row.receipt for row in evidence.catalog.records)
        receipts.extend(row.receipt for row in evidence.facts.records)
        for concept in evidence.catalog.records:
            receipts.extend(row.receipt for row in concept.periods)
    return tuple(receipts)


def _source_quality(
    receipt: _Receipt,
    source: StockDossierSource | None,
    dossier: StockDossier,
    as_of: datetime,
    policy: StockDataQualityPolicy,
) -> StockSourceQuality:
    age = _age(receipt, as_of)
    reasons = []
    if age > policy.max_receipt_age_seconds:
        reasons.append("receipt_stale")
    if source is not None:
        if source.scope_verified is not True:
            reasons.append("request_scope_unknown")
        if source.results_missing is True:
            reasons.append("source_results_missing")
        if dossier.symbol in source.not_found:
            reasons.append("symbol_not_found")
        if dossier.symbol in source.unavailable_symbols:
            reasons.append("symbol_unavailable")
    else:
        reasons.append("request_scope_unknown")
    origin, original_hash = _receipt_origin(receipt, source, dossier)
    return StockSourceQuality(
        receipt.tool,
        receipt.observation_sha256,
        receipt.received_at,
        age,
        None if source is None else source.collection_observation_hash,
        None if source is None else source.normalized_observation_hash,
        None if source is None else source.null_row_count,
        None if source is None else source.results_missing,
        None if source is None else source.scope_verified,
        tuple(reasons),
        origin,
        original_hash,
    )


def _receipt_origin(
    receipt: _Receipt, source: StockDossierSource | None, dossier: StockDossier
) -> tuple[_ReceiptOrigin, str | None]:
    if source is not None:
        return "dossier_source", receipt.observation_sha256
    history = dossier.history
    if history is not None and history.outcome.normalized is not None:
        outcome = history.outcome
        context = outcome.context
        if (
            receipt == history.outcome.normalized.receipt
            and receipt.tool == "get_equity_historicals"
            and receipt.observation_sha256 == context.projected_payload_sha256
            and any(
                original.projection_context == context
                and original.receipt.tool == receipt.tool
                and original.receipt.received_at == receipt.received_at
                and original.receipt.observation_sha256 == context.original_source_sha256
                for original in dossier.sources
            )
        ):
            return "linked_local_projection", context.original_source_sha256
    return "unverified_additional_receipt", None


def _history_quality(
    dossier: StockDossier,
    as_of: datetime,
    policy: StockDataQualityPolicy,
) -> StockHistoryQuality:
    history = dossier.history
    status = "absent" if history is None else history.status
    normalized = None if history is None else history.outcome.normalized
    bars = None if normalized is None else normalized.records
    reasons = [
        "calendar_coverage_unknown",
        "corporate_action_coverage_unknown",
        "quote_currency_unknown",
        "exact_completion_time_unknown",
    ]
    if status != "normalized":
        reasons.append("history_" + status)
    if normalized is not None and _age(normalized.receipt, as_of) > policy.max_receipt_age_seconds:
        reasons.append("receipt_stale")
    latest = None if not bars else max(_utc(bar.begins_at) for bar in bars)
    lag = None if latest is None else (as_of.date() - latest.date()).days
    if lag is not None and lag > policy.max_latest_bar_lag_days:
        reasons.append("latest_bar_stale")
    if bars is not None and len(bars) < policy.minimum_history_bars:
        reasons.append("insufficient_history_bars")
    interpolation = None if bars is None else sum(bar.interpolated is None for bar in bars)
    sessions = None if bars is None else sum(bar.session is None for bar in bars)
    if interpolation:
        reasons.append("interpolation_unknown")
    if sessions:
        reasons.append("session_unknown")
    if bars and any(bar.interpolated is True for bar in bars):
        reasons.append("interpolated_bars_present")
    if bars and any(bar.session not in (None, "reg") for bar in bars):
        reasons.append("non_regular_session_bars")
    if history is not None:
        for count, reason in (
            (history.null_bar_count, "history_null_bars"),
            (history.omitted_interpolated_count, "interpolated_bars_omitted"),
            (history.completion_unknown_count, "completion_unknown"),
            (history.raw_basis_unknown_count, "raw_basis_unknown"),
        ):
            if count:
                reasons.append(reason)
    return StockHistoryQuality(
        status,
        None if bars is None else len(bars),
        None if history is None else history.null_bar_count,
        None if history is None else history.omitted_interpolated_count,
        interpolation,
        sessions,
        None if history is None else history.completion_unknown_count,
        None if history is None else history.raw_basis_unknown_count,
        latest,
        lag,
        tuple(reasons),
    )


def assess_stock_data_quality(
    dossier: StockDossier,
    *,
    as_of: datetime,
    policy: StockDataQualityPolicy = _DEFAULT_POLICY,
) -> StockDataQualityAssessment:
    """Assess retained observations without fetching, repairing, scoring or promoting them.

    A compiled dossier containing future information is rejected rather than filtered;
    its values, gaps and membership must not leak into a historical assessment.
    """
    _check(type(dossier) is StockDossier and type(policy) is StockDataQualityPolicy)
    cutoff = _utc(as_of)
    _check(_utc(dossier.as_of) <= cutoff)
    receipts = _receipts(dossier)
    for receipt in receipts:
        _age(receipt, cutoff)
    history = _history_quality(dossier, cutoff, policy)
    sources = [
        _source_quality(source.receipt, source, dossier, cutoff, policy)
        for source in dossier.sources
    ]
    known = {(source.tool, source.received_at, source.observation_sha256) for source in sources}
    for receipt in receipts:
        key = (receipt.tool, receipt.received_at, receipt.observation_sha256)
        if key not in known:
            sources.append(_source_quality(receipt, None, dossier, cutoff, policy))
            known.add(key)
    periods = []
    for row in dossier.financial_periods:
        age = (cutoff.date() - row.period_end).days
        reasons = [
            "financial_currency_unknown",
            "financial_period_start_unknown",
            "point_in_time_availability_unknown",
        ]
        if age < 0:
            reasons.append("financial_period_after_as_of")
        if age > policy.max_financial_period_age_days:
            reasons.append("financial_period_stale")
        if row.missing_metrics:
            reasons.append("financial_metrics_missing")
        if _age(row.receipt, cutoff) > policy.max_receipt_age_seconds:
            reasons.append("receipt_stale")
        periods.append(
            StockFinancialPeriodQuality(
                row.period,
                row.period_end,
                _age(row.receipt, cutoff),
                age,
                row.missing_metrics,
                len(row.missing_metrics),
                tuple(reasons),
            )
        )
    facts = tuple(row for evidence in dossier.filing_evidence for row in evidence.facts.records)
    global_reasons = [
        "source_authenticity_unknown",
        "entity_mapping_unknown",
        "point_in_time_availability_unknown",
        "historical_universe_unknown",
    ]
    if not dossier.filing_evidence:
        global_reasons.append("filing_evidence_absent")
    else:
        global_reasons.append("filing_units_unqualified")
    if not dossier.financial_periods:
        global_reasons.append("financial_periods_absent")
    if dossier.fundamentals is None:
        global_reasons.append("fundamentals_absent")
    observations = (
        *(() if dossier.fundamentals is None else (dossier.fundamentals,)),
        *dossier.financial_periods,
        *dossier.earnings,
        *dossier.filing_index,
        *facts,
        *(
            ()
            if dossier.history is None or dossier.history.outcome.normalized is None
            else dossier.history.outcome.normalized.records
        ),
    )
    descriptive = any(
        _age(row.receipt, cutoff) <= policy.max_receipt_age_seconds for row in observations
    )
    restrictions = [
        StockDataUseRestriction("daily_price_features", history.reason_codes),
        StockDataUseRestriction(
            "financial_comparison",
            tuple(
                sorted(
                    {
                        "financial_currency_unknown",
                        "entity_mapping_unknown",
                        "point_in_time_availability_unknown",
                        *(reason for row in periods for reason in row.reason_codes),
                        *(() if periods else ("financial_periods_absent",)),
                    }
                )
            ),
        ),
        StockDataUseRestriction("source_qualification", ("source_authenticity_unknown",)),
        StockDataUseRestriction(
            "historical_strategy",
            (
                "calendar_coverage_unknown",
                "corporate_action_coverage_unknown",
                "point_in_time_availability_unknown",
                "historical_universe_unknown",
            ),
        ),
        StockDataUseRestriction("investment_selection", ("investment_inputs_unqualified",)),
        StockDataUseRestriction("live_trading", ("live_trading_not_authorized",)),
    ]
    if not descriptive:
        restrictions.append(
            StockDataUseRestriction(
                "current_descriptive_research",
                ("observations_absent_or_stale",),
            )
        )
    fundamental = dossier.fundamentals
    market_date = None if fundamental is None else fundamental.market_date
    return StockDataQualityAssessment(
        dossier.symbol,
        cutoff,
        dossier.dossier_hash,
        policy,
        tuple(sources),
        history,
        tuple(periods),
        None if fundamental is None else fundamental.missing_metrics,
        market_date,
        None if market_date is None else (cutoff.date() - market_date).days,
        sum(row.currency is None for row in dossier.financial_periods),
        len(facts),
        sum(row.numeric_value is None for row in facts),
        sum(not row.unit_raw for row in facts),
        sum(row.start_date is None for row in facts),
        len(facts),
        descriptive,
        tuple(restrictions),
        tuple(global_reasons),
    )
