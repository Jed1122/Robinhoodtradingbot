"""Pure current stock assessments; analytical hypotheses, never execution authority."""

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from typing import Literal

from trading_bot.clock import require_utc

type InvestmentHorizon = Literal["long_term", "tactical"]
type InvestmentAction = Literal["enter", "hold", "reduce", "review", "avoid"]
type ContinuationStatus = Literal["active", "inactive", "unknown"]
type CurrentFinancialProfile = Literal["statement_matched_v1", "current_provider_v1"]

_CONTEXT = Context(
    prec=50,
    rounding=ROUND_HALF_EVEN,
    Emin=-999999,
    Emax=999999,
    capitals=1,
    clamp=0,
    flags=[],
    traps=[InvalidOperation, DivisionByZero, Overflow],
)
_NONFINANCIAL = frozenset(
    {
        "Basic Materials",
        "Communication Services",
        "Consumer Cyclical",
        "Consumer Defensive",
        "Energy",
        "Healthcare",
        "Industrials",
        "Real Estate",
        "Technology",
        "Utilities",
    }
)
_FINANCIAL = frozenset({"Financial Services", "Financials"})
_FEATURES = ("roe", "net_margin", "annual_eps_growth", "quarterly_revenue_growth")
_BASE = (
    *_FEATURES,
    "pe_ratio",
    "fcf_per_share",
    "scanner_price",
    "net_income",
    "revenue",
    "reported_debt",
    "closing_equity",
)
_TACTICAL = ("price_return_20", "close_to_sma_50")
_PROVIDER_BASE = (
    *_FEATURES,
    "pe_ratio",
    "fcf_per_share",
    "scanner_price",
    "net_income",
    "revenue",
    "price_to_fcf",
    "total_stockholders_equity",
    "assets_to_equity",
)
_PROVIDER_TACTICAL = ("provider_close_20", "provider_sma_50")
_METRICS = frozenset((*_BASE, *_TACTICAL, *_PROVIDER_BASE, *_PROVIDER_TACTICAL))
_DEBT_METHODS = frozenset(
    {
        "native_total_debt_current_inclusive",
        "reported_noncurrent_plus_all_current_debt",
        "reported_current_inclusive_long_term_plus_short_term",
    }
)
_RISK_CODES = frozenset({"going_concern", "bankruptcy", "financial_reporting_failure"})
_SCAN = frozenset({"preview_scan"})
_FIN = frozenset({"get_financials", "get_sec_filing_facts"})
_RISK = frozenset({"get_equity_fundamentals", "get_sec_filing", "get_sec_filing_facts"})
_LIMITS = (
    "current_analytical_hypotheses_not_forecasts",
    "performance_unproven_not_an_entry_gate",
    "hashes_bind_supplied_evidence_not_provider_authentication",
    "untrusted_notes_do_not_modify_rules",
    "news_coverage_not_supplied",
    "no_execution_or_live_authority",
)

_PROVIDER_LIMITS = (
    *_LIMITS,
    "current_provider_features_not_statement_matched",
    "liability_leverage_proxy_not_debt_equity",
    "balance_sheet_effective_date_unknown_unless_supplied",
    "provider_price_signals_not_completed_close",
)


class StockInvestmentError(ValueError):
    """Malformed current decision input; no repair or inferred values."""


def _check(value: bool) -> None:
    if not value:
        raise StockInvestmentError("stock_investment_decisions_invalid")


def _number(value: object) -> bool:
    if type(value) is not Decimal:
        return False
    parts = value.as_tuple()
    return (
        value.is_finite()
        and value.copy_abs() <= Decimal("1e30")
        and len(parts.digits) <= 80
        and isinstance(parts.exponent, int)
        and -30 <= parts.exponent <= 30
    )


def _computed_number(value: Decimal) -> bool:
    # Calculated 50-digit recurring decimals are valid independently of the
    # stricter native input lexeme/exponent bounds. Never round source inputs.
    return value.is_finite() and 0 < value <= Decimal("1e30")


def _sha(value: object) -> bool:
    return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None


def _instant(value: datetime | None) -> object:
    return None if value is None else (value.isoformat(), value.fold)


def _decimal_wire(value: Decimal | None) -> object:
    return None if value is None else tuple(value.as_tuple())


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class CurrentEvidenceRef:
    tool: str
    observation_sha256: str
    record_ref: str
    received_at: datetime
    expires_at: datetime
    effective_date: date | None = None
    normalized_sha256: str | None = None
    symbol: str | None = None
    instrument_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CurrentMetric:
    name: str
    value: Decimal | None
    unit: str | None
    period_basis: str | None
    refs: tuple[CurrentEvidenceRef, ...]
    currency: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    original_report_id: str | None = None
    debt_method: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CurrentRisk:
    code: str
    refs: tuple[CurrentEvidenceRef, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class CurrentStockEvidence:
    symbol: str
    instrument_id: str | None
    instrument_type: str
    horizon: InvestmentHorizon
    metrics: tuple[CurrentMetric, ...]
    identity_refs: tuple[CurrentEvidenceRef, ...]
    sector: str | None = None
    sector_refs: tuple[CurrentEvidenceRef, ...] = ()
    held: bool = False
    dossier_hash: str | None = None
    sourced_critical_risks: tuple[CurrentRisk, ...] = ()
    untrusted_notes: tuple[str, ...] = ()

    @property
    def evidence_hash(self) -> str:
        _shape(self)
        return _hash(("current-stock-evidence-v1", _evidence_wire(self)))


@dataclass(frozen=True, slots=True, kw_only=True)
class CurrentInvestmentPolicy:
    policy_id: str = "current-stock-investment-v1"
    maximum_pe: Decimal = Decimal(40)
    maximum_debt_equity: Decimal = Decimal(2)
    snapshot_max_age_minutes: int = 120
    financial_receipt_max_age_days: int = 7
    annual_period_max_age_days: int = 550
    quarterly_period_max_age_days: int = 150
    quality_weight: Decimal = Decimal(40)
    growth_weight: Decimal = Decimal(35)
    valuation_weight: Decimal = Decimal(25)
    financial_profile: CurrentFinancialProfile = "statement_matched_v1"
    minimum_assets_equity: Decimal = Decimal(1)
    maximum_assets_equity: Decimal = Decimal(3)

    @property
    def policy_hash(self) -> str:
        _policy(self)
        original = (
            "current-stock-investment-policy-v1",
            self.policy_id,
            _decimal_wire(self.maximum_pe),
            _decimal_wire(self.maximum_debt_equity),
            self.snapshot_max_age_minutes,
            self.financial_receipt_max_age_days,
            self.annual_period_max_age_days,
            self.quarterly_period_max_age_days,
            _decimal_wire(self.quality_weight),
            _decimal_wire(self.growth_weight),
            _decimal_wire(self.valuation_weight),
            sorted(_DEBT_METHODS),
            sorted(_NONFINANCIAL),
            sorted(_FINANCIAL),
            sorted(_RISK_CODES),
        )
        if self.financial_profile == "statement_matched_v1":
            return _hash(original)
        return _hash(
            (
                "current-stock-provider-policy-v1",
                original,
                self.financial_profile,
                _decimal_wire(self.minimum_assets_equity),
                _decimal_wire(self.maximum_assets_equity),
            )
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class StockDecisionReason:
    code: str
    fact_name: str | None
    value: Decimal | None
    refs: tuple[CurrentEvidenceRef, ...]
    basis: str = "reported_current_evidence"


@dataclass(frozen=True, slots=True, kw_only=True)
class StockInvestmentDecision:
    symbol: str
    instrument_id: str | None
    horizon: InvestmentHorizon
    as_of: datetime
    expires_at: datetime | None
    source_received_at: datetime | None
    analytically_eligible: bool
    action: InvestmentAction
    continuation_status: ContinuationStatus | None
    bullish_evidence: tuple[StockDecisionReason, ...]
    bearish_evidence: tuple[StockDecisionReason, ...]
    missing_requirements: tuple[str, ...]
    source_refs: tuple[CurrentEvidenceRef, ...]
    evidence_hash: str
    policy_hash: str
    ordinal_rank: int | None = None
    priority_score: Decimal | None = None
    performance_evidence: Literal["unproven_not_a_gate"] = field(
        default="unproven_not_a_gate", init=False
    )
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    limitations: tuple[str, ...] = field(default=_LIMITS, init=False)
    financial_profile: CurrentFinancialProfile = "statement_matched_v1"

    def __post_init__(self) -> None:
        if self.financial_profile == "current_provider_v1":
            object.__setattr__(self, "limitations", _PROVIDER_LIMITS)

    @property
    def decision_hash(self) -> str:
        _check(
            self.source_qualified is False
            and self.strategy_qualified is False
            and self.execution_authorized is False
            and self.trading_enabled is False
            and self.live_authorized is False
            and self.performance_evidence == "unproven_not_a_gate"
            and self.financial_profile in ("statement_matched_v1", "current_provider_v1")
            and type(self.limitations) is tuple
            and self.limitations
            == (_PROVIDER_LIMITS if self.financial_profile == "current_provider_v1" else _LIMITS)
        )
        original = (
            "current-stock-decision-v1",
            self.symbol,
            self.instrument_id,
            self.horizon,
            _instant(self.as_of),
            _instant(self.expires_at),
            _instant(self.source_received_at),
            self.analytically_eligible,
            self.action,
            self.continuation_status,
            tuple(_reason_wire(x) for x in self.bullish_evidence),
            tuple(_reason_wire(x) for x in self.bearish_evidence),
            self.missing_requirements,
            tuple(_ref_wire(x) for x in self.source_refs),
            self.evidence_hash,
            self.policy_hash,
            self.ordinal_rank,
            _decimal_wire(self.priority_score),
        )
        if self.financial_profile == "current_provider_v1":
            return _hash((original, self.financial_profile, self.limitations))
        return _hash(original)


def _ref_wire(value: CurrentEvidenceRef) -> object:
    return (
        value.tool,
        value.observation_sha256,
        value.normalized_sha256,
        value.record_ref,
        _instant(value.received_at),
        _instant(value.expires_at),
        None if value.effective_date is None else value.effective_date.isoformat(),
        value.symbol,
        value.instrument_id,
    )


def _metric_wire(value: CurrentMetric) -> object:
    return (
        value.name,
        _decimal_wire(value.value),
        value.unit,
        value.currency,
        value.period_basis,
        None if value.period_start is None else value.period_start.isoformat(),
        None if value.period_end is None else value.period_end.isoformat(),
        value.original_report_id,
        value.debt_method,
        tuple(_ref_wire(x) for x in value.refs),
    )


def _reason_wire(value: StockDecisionReason) -> object:
    return (
        value.code,
        value.fact_name,
        _decimal_wire(value.value),
        value.basis,
        tuple(_ref_wire(x) for x in value.refs),
    )


def _evidence_wire(value: CurrentStockEvidence) -> object:
    return (
        value.symbol,
        value.instrument_id,
        value.instrument_type,
        value.horizon,
        value.held,
        value.sector,
        value.dossier_hash,
        tuple(_metric_wire(x) for x in value.metrics),
        tuple(_ref_wire(x) for x in value.identity_refs),
        tuple(_ref_wire(x) for x in value.sector_refs),
        tuple((x.code, tuple(_ref_wire(r) for r in x.refs)) for x in value.sourced_critical_risks),
        value.untrusted_notes,
    )


def _refs_shape(refs: tuple[CurrentEvidenceRef, ...]) -> None:
    _check(type(refs) is tuple and len(refs) <= 32)
    for ref in refs:
        _check(type(ref) is CurrentEvidenceRef)
        _check(type(ref.tool) is str and 0 < len(ref.tool) <= 128)
        _check(type(ref.record_ref) is str and 0 < len(ref.record_ref) <= 2048)
        _check(type(ref.observation_sha256) is str and len(ref.observation_sha256) <= 128)
        _check(
            ref.normalized_sha256 is None
            or (type(ref.normalized_sha256) is str and len(ref.normalized_sha256) <= 128)
        )
        _check(ref.symbol is None or (type(ref.symbol) is str and len(ref.symbol) <= 15))
        _check(
            ref.instrument_id is None
            or (type(ref.instrument_id) is str and 0 < len(ref.instrument_id) <= 128)
        )
        _check(type(ref.received_at) is datetime and type(ref.expires_at) is datetime)
        _check(ref.effective_date is None or type(ref.effective_date) is date)


def _shape(value: CurrentStockEvidence) -> None:
    _check(type(value) is CurrentStockEvidence)
    _check(
        type(value.symbol) is str
        and re.fullmatch(r"[A-Z][A-Z0-9.\-/]{0,14}", value.symbol) is not None
    )
    _check(
        value.instrument_id is None
        or (type(value.instrument_id) is str and 0 < len(value.instrument_id) <= 128)
    )
    _check(type(value.instrument_type) is str and len(value.instrument_type) <= 32)
    _check(value.horizon in ("long_term", "tactical") and type(value.held) is bool)
    _check(value.sector is None or (type(value.sector) is str and len(value.sector) <= 128))
    _check(value.dossier_hash is None or _sha(value.dossier_hash))
    _refs_shape(value.identity_refs)
    _refs_shape(value.sector_refs)
    _check(type(value.metrics) is tuple and len(value.metrics) <= 64)
    for metric in value.metrics:
        _check(
            type(metric) is CurrentMetric and type(metric.name) is str and metric.name in _METRICS
        )
        _check(metric.value is None or type(metric.value) is Decimal)
        _check(metric.unit is None or (type(metric.unit) is str and len(metric.unit) <= 40))
        _check(
            metric.currency is None or (type(metric.currency) is str and len(metric.currency) <= 10)
        )
        _check(
            metric.period_basis is None
            or (type(metric.period_basis) is str and len(metric.period_basis) <= 64)
        )
        _check(metric.period_start is None or type(metric.period_start) is date)
        _check(metric.period_end is None or type(metric.period_end) is date)
        _check(
            metric.original_report_id is None
            or (
                type(metric.original_report_id) is str and 0 < len(metric.original_report_id) <= 256
            )
        )
        _check(
            metric.debt_method is None
            or (type(metric.debt_method) is str and len(metric.debt_method) <= 128)
        )
        _refs_shape(metric.refs)
    _check(type(value.sourced_critical_risks) is tuple and len(value.sourced_critical_risks) <= 16)
    for risk in value.sourced_critical_risks:
        _check(type(risk) is CurrentRisk and type(risk.code) is str and len(risk.code) <= 128)
        _refs_shape(risk.refs)
    _check(
        type(value.untrusted_notes) is tuple
        and len(value.untrusted_notes) <= 16
        and all(type(note) is str and len(note) <= 8192 for note in value.untrusted_notes)
    )


def _policy(value: CurrentInvestmentPolicy) -> None:
    _check(
        type(value) is CurrentInvestmentPolicy
        and type(value.policy_id) is str
        and 0 < len(value.policy_id) <= 128
    )
    numbers = (
        value.maximum_pe,
        value.maximum_debt_equity,
        value.quality_weight,
        value.growth_weight,
        value.valuation_weight,
        value.minimum_assets_equity,
        value.maximum_assets_equity,
    )
    _check(all(_number(number) for number in numbers))
    _check(value.maximum_pe > 0 and value.maximum_debt_equity >= 0)
    _check(value.financial_profile in ("statement_matched_v1", "current_provider_v1"))
    _check(
        value.minimum_assets_equity >= 1
        and value.maximum_assets_equity >= value.minimum_assets_equity
    )
    _check(
        value.financial_profile != "current_provider_v1"
        or value.policy_id == "current-stock-investment-provider-v1"
    )
    with localcontext(_CONTEXT):
        _check(
            value.quality_weight >= 0
            and value.growth_weight >= 0
            and value.valuation_weight >= 0
            and value.quality_weight + value.growth_weight + value.valuation_weight == 100
        )
    _check(
        all(
            type(number) is int and 1 <= number <= 10000
            for number in (
                value.snapshot_max_age_minutes,
                value.financial_receipt_max_age_days,
                value.annual_period_max_age_days,
                value.quarterly_period_max_age_days,
            )
        )
    )


def _allowed_tools(name: str) -> frozenset[str]:
    if name in ("reported_debt", "closing_equity"):
        return frozenset({"get_sec_filing_facts"})
    if name in ("net_income", "revenue"):
        return _FIN
    if name in _TACTICAL:
        return frozenset({"get_equity_historicals"})
    if name == "pe_ratio":
        return frozenset({"preview_scan", "get_equity_fundamentals"})
    return _SCAN


def _use_refs(
    refs: tuple[CurrentEvidenceRef, ...],
    stock: CurrentStockEvidence,
    name: str,
    allowed: frozenset[str],
    as_of: datetime,
    policy: CurrentInvestmentPolicy,
    needs: set[str],
    expiries: list[datetime],
    *,
    financial: bool = False,
    identity: bool = False,
) -> bool:
    if not refs:
        needs.add("missing_source_ref:" + name)
        return False
    valid = True
    for ref in refs:
        reason = None
        if ref.tool not in allowed:
            reason = "source_purpose_incompatible:"
        elif (
            ref.symbol != stock.symbol
            or (ref.instrument_id is not None and ref.instrument_id != stock.instrument_id)
            or (
                identity
                and (stock.instrument_id is None or ref.instrument_id != stock.instrument_id)
            )
        ):
            reason = "source_identity_mismatch:"
        elif not _sha(ref.observation_sha256) or (
            ref.normalized_sha256 is not None and not _sha(ref.normalized_sha256)
        ):
            reason = "source_hash_invalid:"
        else:
            try:
                received, declared = require_utc(ref.received_at), require_utc(ref.expires_at)
                age = (
                    timedelta(days=policy.financial_receipt_max_age_days)
                    if financial
                    else timedelta(minutes=policy.snapshot_max_age_minutes)
                )
                expiry = min(declared, received + age)
                if received > as_of:
                    reason = "future_source:"
                elif declared <= received or as_of >= expiry:
                    reason = "expired_source:"
                elif ref.effective_date is not None and ref.effective_date > as_of.date():
                    reason = "future_effective_date:"
                else:
                    expiries.append(expiry)
            except ValueError:
                reason = "source_clock_invalid:"
        if reason is not None:
            needs.add(reason + name)
            valid = False
    return valid


@dataclass(frozen=True, slots=True)
class _Assessment:
    decision: StockInvestmentDecision
    factors: tuple[tuple[str, Decimal], ...]
    feature_basis: tuple[str, ...]


def _provider_assessment(
    metrics: dict[str, CurrentMetric],
    values: dict[str, Decimal],
    stock: CurrentStockEvidence,
    policy: CurrentInvestmentPolicy,
    as_of: datetime,
    needs: set[str],
    bull: list[StockDecisionReason],
    bear: list[StockDecisionReason],
    factors: dict[str, Decimal],
) -> None:
    """Current scanner hypotheses; no statement debt or completed-close claim."""
    price = metrics.get("scanner_price")
    if price is not None and len(price.refs) != 1:
        needs.add("provider_snapshot_ambiguous:scanner_price")
    if "scanner_price" in values and values["scanner_price"] <= 0:
        needs.add("scanner_price_unusable")
    for name in (
        "price_to_fcf",
        "total_stockholders_equity",
        "assets_to_equity",
        *_PROVIDER_TACTICAL,
    ):
        metric = metrics.get(name)
        if metric is None or name not in values:
            continue
        if price is None or metric.refs != price.refs:
            needs.add("provider_snapshot_mismatch:" + name)
        if metric.period_start is not None:
            needs.add("provider_snapshot_period_incompatible:" + name)
        if metric.period_end is not None and (
            metric.period_end > as_of.date()
            or (as_of.date() - metric.period_end).days > policy.quarterly_period_max_age_days
        ):
            needs.add("provider_effective_date_stale_or_future:" + name)
    equity, leverage = metrics.get("total_stockholders_equity"), metrics.get("assets_to_equity")
    if (
        equity is not None
        and leverage is not None
        and (
            equity.period_end is not None
            and leverage.period_end is not None
            and equity.period_end != leverage.period_end
        )
    ):
        needs.add("provider_balance_effective_date_mismatch")
    multiple = metrics.get("price_to_fcf")
    if multiple is not None and "price_to_fcf" in values:
        positive = values["price_to_fcf"] > 0
        (bull if positive else bear).append(
            StockDecisionReason(
                code="positive_price_to_fcf" if positive else "nonpositive_price_to_fcf",
                fact_name="price_to_fcf",
                value=values["price_to_fcf"],
                refs=multiple.refs,
                basis="current_provider_multiple_not_currency_conversion",
            )
        )
        if positive:
            with localcontext(_CONTEXT):
                factors["pfcf_reciprocal"] = Decimal(1) / values["price_to_fcf"]
    if leverage is not None and "assets_to_equity" in values:
        within = (
            policy.minimum_assets_equity
            <= values["assets_to_equity"]
            <= policy.maximum_assets_equity
        )
        (bull if within else bear).append(
            StockDecisionReason(
                code="assets_equity_proxy_within_policy"
                if within
                else "assets_equity_proxy_outside_policy",
                fact_name="assets_to_equity",
                value=values["assets_to_equity"],
                refs=leverage.refs,
                basis="current_provider_liability_leverage_proxy_not_debt_equity",
            )
        )
    if stock.horizon != "tactical":
        return
    for name in _PROVIDER_TACTICAL:
        metric = metrics.get(name)
        if metric is None or name not in values or "scanner_price" not in values:
            continue
        if values[name] <= 0:
            needs.add("provider_price_denominator_unusable:" + name)
            continue
        if price is None or metric.refs != price.refs:
            needs.add("provider_snapshot_mismatch:" + name)
            continue
        if (
            price.currency is not None
            and metric.currency is not None
            and price.currency != metric.currency
        ):
            needs.add("provider_price_currency_mismatch:" + name)
            continue
        if values["scanner_price"] <= 0:
            continue
        with localcontext(_CONTEXT):
            signal = values["scanner_price"] / values[name] - 1
        (bull if signal > 0 else bear).append(
            StockDecisionReason(
                code=("positive_" if signal > 0 else "nonpositive_") + name,
                fact_name=name,
                value=signal,
                refs=metric.refs,
                basis="current_provider_snapshot_not_completed_close",
            )
        )


def _assess(
    stock: CurrentStockEvidence, policy: CurrentInvestmentPolicy, as_of: datetime
) -> _Assessment:
    _shape(stock)
    _policy(policy)
    provider = policy.financial_profile == "current_provider_v1"
    try:
        as_of = require_utc(as_of)
    except ValueError:
        raise StockInvestmentError("stock_investment_decisions_invalid") from None
    needs: set[str] = set()
    expiries: list[datetime] = []
    bull: list[StockDecisionReason] = []
    bear: list[StockDecisionReason] = []
    if stock.instrument_id is None:
        needs.add("instrument_identity_missing")
    if stock.instrument_type != "stock":
        needs.add("stock_identity_required")
    _use_refs(
        stock.identity_refs, stock, "identity", _SCAN, as_of, policy, needs, expiries, identity=True
    )
    sector_ok = _use_refs(
        stock.sector_refs,
        stock,
        "sector",
        frozenset({"preview_scan", "get_equity_fundamentals"}),
        as_of,
        policy,
        needs,
        expiries,
    )
    nonfinancial = sector_ok and stock.sector in _NONFINANCIAL
    if not nonfinancial:
        needs.add(
            "financial_leverage_profile_required"
            if stock.sector in _FINANCIAL
            else "sector_profile_unknown"
        )
    by_name: dict[str, CurrentMetric] = {}
    duplicates: set[str] = set()
    for supplied_metric in stock.metrics:
        if supplied_metric.name in by_name:
            duplicates.add(supplied_metric.name)
        by_name[supplied_metric.name] = supplied_metric
    base = _PROVIDER_BASE if provider else _BASE
    tactical = _PROVIDER_TACTICAL if provider else _TACTICAL
    required = (*base, *tactical) if stock.horizon == "tactical" else base
    values: dict[str, Decimal] = {}
    for name in required:
        metric = by_name.get(name)
        if name in duplicates:
            needs.add("conflicting_or_duplicate_metric:" + name)
            continue
        if metric is None or metric.value is None:
            needs.add("missing_metric:" + name)
            continue
        financial = name in ("net_income", "revenue", "reported_debt", "closing_equity")
        usable = _use_refs(
            metric.refs,
            stock,
            name,
            _allowed_tools(name),
            as_of,
            policy,
            needs,
            expiries,
            financial=financial,
        )
        if not _number(metric.value):
            needs.add("metric_value_unusable:" + name)
            continue
        if financial:
            if metric.unit != "monetary":
                needs.add("metric_unit_incompatible:" + name)
                usable = False
            if (
                metric.period_end is None
                or metric.period_end > as_of.date()
                or (metric.period_start is not None and metric.period_start > metric.period_end)
            ):
                needs.add("financial_period_unknown_or_future:" + name)
                usable = False
            elif metric.period_basis in ("annual", "quarterly", "instant"):
                maximum = (
                    policy.annual_period_max_age_days
                    if metric.period_basis == "annual"
                    else policy.quarterly_period_max_age_days
                )
                if (as_of.date() - metric.period_end).days > maximum:
                    needs.add("financial_period_stale:" + name)
                    usable = False
            else:
                needs.add("financial_period_basis_unknown:" + name)
                usable = False
        else:
            expected = (
                ("ratio", "percent", "provider_feature")
                if name in _FEATURES
                else ("multiple", "ratio")
                if name == "pe_ratio"
                else ("multiple",)
                if name == "price_to_fcf"
                else ("monetary",)
                if name == "total_stockholders_equity"
                else ("per_share",)
                if name == "fcf_per_share"
                else ("price_per_share",)
                if name == "scanner_price" or name in _PROVIDER_TACTICAL
                else ("ratio",)
            )
            if metric.unit not in expected:
                needs.add("metric_unit_incompatible:" + name)
                usable = False
            expected_basis = (
                "retained_daily_observations" if name in _TACTICAL else "provider_current"
            )
            if metric.period_basis != expected_basis:
                needs.add("metric_period_basis_incompatible:" + name)
                usable = False
        if usable:
            with localcontext(_CONTEXT):
                values[name] = (
                    metric.value / 100
                    if name in _FEATURES and metric.unit == "percent"
                    else metric.value
                )
    for name in (
        "net_income",
        "revenue",
        *_FEATURES,
        "fcf_per_share",
        "closing_equity",
        "total_stockholders_equity",
    ):
        if name in values:
            positive_metric = by_name[name]
            positive = values[name] > 0
            reason = StockDecisionReason(
                code=("positive_" if positive else "nonpositive_") + name,
                fact_name=name,
                value=positive_metric.value,
                refs=positive_metric.refs,
                basis="native_unknown_currency_sign_only"
                if name in ("net_income", "revenue", "fcf_per_share", "total_stockholders_equity")
                and positive_metric.currency is None
                else "reported_current_evidence",
            )
            (bull if positive else bear).append(reason)
    for name in ("net_income", "revenue"):
        metric = by_name.get(name)
        if metric is not None and metric.period_basis not in ("annual", "quarterly"):
            needs.add("reported_financial_duration_required:" + name)
    income, revenue = by_name.get("net_income"), by_name.get("revenue")
    if (
        income is not None
        and revenue is not None
        and (
            income.period_end != revenue.period_end
            or income.period_basis != revenue.period_basis
            or (
                income.period_start is not None
                and revenue.period_start is not None
                and income.period_start != revenue.period_start
            )
            or income.original_report_id != revenue.original_report_id
        )
    ):
        needs.add("reported_financial_period_mismatch")
    factors: dict[str, Decimal] = {name: values[name] for name in _FEATURES if name in values}
    pe = by_name.get("pe_ratio")
    if pe is not None and "pe_ratio" in values:
        if not 0 < values["pe_ratio"] <= policy.maximum_pe:
            bear.append(
                StockDecisionReason(
                    code="valuation_pe_outside_policy",
                    fact_name="pe_ratio",
                    value=pe.value,
                    refs=pe.refs,
                )
            )
        else:
            with localcontext(_CONTEXT):
                factors["earnings_yield"] = Decimal(1) / values["pe_ratio"]
    fcf, price = by_name.get("fcf_per_share"), by_name.get("scanner_price")
    if (
        not provider
        and fcf is not None
        and price is not None
        and "fcf_per_share" in values
        and "scanner_price" in values
    ):
        if fcf.currency is None or price.currency is None:
            needs.add("fcf_price_currency_unknown")
        elif not re.fullmatch("[A-Z]{3}", fcf.currency) or fcf.currency != price.currency:
            needs.add("fcf_price_units_incompatible")
        elif values["scanner_price"] <= 0:
            needs.add("scanner_price_unusable")
        else:
            with localcontext(_CONTEXT):
                factors["fcf_to_price"] = values["fcf_per_share"] / values["scanner_price"]
    debt, equity = by_name.get("reported_debt"), by_name.get("closing_equity")
    if (
        not provider
        and nonfinancial
        and debt is not None
        and equity is not None
        and "reported_debt" in values
        and "closing_equity" in values
    ):
        if debt.debt_method not in _DEBT_METHODS:
            needs.add("debt_definition_unsupported")
        elif (
            debt.period_basis != "instant"
            or equity.period_basis != "instant"
            or debt.period_start is not None
            or equity.period_start is not None
            or debt.period_end != equity.period_end
            or debt.original_report_id is None
            or debt.original_report_id != equity.original_report_id
        ):
            needs.add("debt_equity_report_or_period_mismatch")
        elif (
            debt.currency is None
            or equity.currency is None
            or not re.fullmatch("[A-Z]{3}", debt.currency)
            or debt.currency != equity.currency
        ):
            needs.add("debt_equity_units_incompatible")
        elif values["reported_debt"] < 0:
            bear.append(
                StockDecisionReason(
                    code="reported_debt_negative",
                    fact_name="reported_debt",
                    value=debt.value,
                    refs=debt.refs,
                )
            )
        elif values["closing_equity"] > 0:
            with localcontext(_CONTEXT):
                ratio = values["reported_debt"] / values["closing_equity"]
            reason = StockDecisionReason(
                code="debt_equity_within_policy"
                if ratio <= policy.maximum_debt_equity
                else "debt_equity_above_policy",
                fact_name="reported_debt",
                value=ratio,
                refs=(*debt.refs, *equity.refs),
            )
            (bull if ratio <= policy.maximum_debt_equity else bear).append(reason)
    if provider:
        _provider_assessment(by_name, values, stock, policy, as_of, needs, bull, bear, factors)
    if stock.horizon == "tactical" and not provider:
        for name in _TACTICAL:
            if name in values:
                positive = values[name] > 0
                (bull if positive else bear).append(
                    StockDecisionReason(
                        code=("positive_" if positive else "nonpositive_") + name,
                        fact_name=name,
                        value=values[name],
                        refs=by_name[name].refs,
                    )
                )
    critical = False
    for risk in stock.sourced_critical_risks:
        if risk.code not in _RISK_CODES:
            needs.add("unsupported_critical_risk_code")
        elif _use_refs(
            risk.refs, stock, "critical_risk", _RISK, as_of, policy, needs, expiries, financial=True
        ):
            critical = True
            bear.append(
                StockDecisionReason(
                    code="critical_risk:" + risk.code, fact_name=None, value=None, refs=risk.refs
                )
            )
    eligible = not needs and not bear and len(factors) == 6
    if len(factors) != 6 and not needs and not bear:
        needs.add("valuation_factors_unavailable")
    action: InvestmentAction = (
        "reduce"
        if critical and stock.held
        else "avoid"
        if critical
        else "hold"
        if stock.held and stock.horizon == "tactical"
        else "review"
        if needs or (stock.held and not eligible)
        else "avoid"
        if not eligible
        else "hold"
        if stock.held
        else "enter"
    )
    continuation: ContinuationStatus | None = None
    if stock.horizon == "tactical":
        continuation = "unknown" if needs else "active" if eligible else "inactive"
    all_refs = (
        *stock.identity_refs,
        *stock.sector_refs,
        *(ref for metric in stock.metrics for ref in metric.refs),
        *(ref for risk in stock.sourced_critical_risks for ref in risk.refs),
    )
    received = [
        ref.received_at
        for ref in all_refs
        if ref.received_at.tzinfo is not None
        and ref.received_at.utcoffset() == timedelta(0)
        and ref.received_at <= as_of
    ]
    decision = StockInvestmentDecision(
        symbol=stock.symbol,
        instrument_id=stock.instrument_id,
        horizon=stock.horizon,
        as_of=as_of,
        expires_at=min(expiries) if expiries and not needs else None,
        source_received_at=max(received) if received else None,
        analytically_eligible=eligible,
        action=action,
        continuation_status=continuation,
        bullish_evidence=tuple(bull),
        bearish_evidence=tuple(bear),
        missing_requirements=tuple(sorted(needs)),
        source_refs=tuple(all_refs),
        evidence_hash=stock.evidence_hash,
        policy_hash=policy.policy_hash,
        financial_profile=policy.financial_profile,
    )
    feature_basis = tuple(
        "provider_feature"
        if by_name.get(name) is not None and by_name[name].unit == "provider_feature"
        else "normalized_ratio"
        for name in _FEATURES
    )
    return _Assessment(decision, tuple(sorted(factors.items())), feature_basis)


def assess_current_stock(
    evidence: CurrentStockEvidence, *, policy: CurrentInvestmentPolicy, as_of: datetime
) -> StockInvestmentDecision:
    """Assess present evidence without source I/O, forecasts or execution approval."""
    try:
        with localcontext(_CONTEXT):
            return _assess(evidence, policy, as_of).decision
    except (DecimalException, OverflowError):
        raise StockInvestmentError("stock_investment_arithmetic_invalid") from None


@dataclass(frozen=True, slots=True, kw_only=True)
class CurrentStockRankings:
    as_of: datetime
    policy_hash: str
    assessments: tuple[StockInvestmentDecision, ...]
    long_term: tuple[StockInvestmentDecision, ...]
    tactical: tuple[StockInvestmentDecision, ...]
    status: Literal["ranked", "no_analytical_candidate"]
    peer_basis: Literal["eligible_submitted_same_horizon"] = field(
        default="eligible_submitted_same_horizon", init=False
    )
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)

    @property
    def report_hash(self) -> str:
        _check(
            self.source_qualified is False
            and self.strategy_qualified is False
            and self.execution_authorized is False
            and self.live_authorized is False
            and self.peer_basis == "eligible_submitted_same_horizon"
        )
        return _hash(
            (
                "current-stock-rankings-v1",
                _instant(self.as_of),
                self.policy_hash,
                self.status,
                self.peer_basis,
                tuple(row.decision_hash for row in self.assessments),
                tuple(row.decision_hash for row in self.long_term),
                tuple(row.decision_hash for row in self.tactical),
            )
        )


def _percentiles(values: tuple[Decimal, ...]) -> dict[Decimal, Decimal]:
    ordered = sorted(values)
    if len(ordered) == 1:
        return {ordered[0]: Decimal(".5")}
    result: dict[Decimal, Decimal] = {}
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and ordered[end] == ordered[start]:
            end += 1
        result[ordered[start]] = (Decimal(start) + Decimal(end - start - 1) / 2) / Decimal(
            len(ordered) - 1
        )
        start = end
    return result


def rank_current_stocks(
    evidence_tuple: tuple[CurrentStockEvidence, ...],
    *,
    policy: CurrentInvestmentPolicy,
    as_of: datetime,
) -> CurrentStockRankings:
    """Rank passers only; input scope is observed companies, not a complete universe."""
    _check(type(evidence_tuple) is tuple and len(evidence_tuple) <= 5000)
    _policy(policy)
    try:
        as_of = require_utc(as_of)
        with localcontext(_CONTEXT):
            assessed = tuple(_assess(stock, policy, as_of) for stock in evidence_tuple)
            symbols = tuple((row.decision.horizon, row.decision.symbol) for row in assessed)
            instruments = tuple(
                (row.decision.horizon, row.decision.instrument_id)
                for row in assessed
                if row.decision.instrument_id is not None
            )
            _check(len(set(symbols)) == len(symbols) and len(set(instruments)) == len(instruments))
            updates: dict[tuple[str, str], StockInvestmentDecision] = {}
            groups: dict[str, tuple[StockInvestmentDecision, ...]] = {}
            for horizon in ("long_term", "tactical"):
                eligible = tuple(
                    row
                    for row in assessed
                    if row.decision.horizon == horizon and row.decision.analytically_eligible
                )
                if not eligible:
                    groups[horizon] = ()
                    continue
                if len({row.feature_basis for row in eligible}) != 1:
                    raise StockInvestmentError("current_stock_peer_units_incompatible")
                factors = tuple(dict(row.factors) for row in eligible)
                cash_factor = (
                    "pfcf_reciprocal"
                    if policy.financial_profile == "current_provider_v1"
                    else "fcf_to_price"
                )
                names = (*_FEATURES, "earnings_yield", cash_factor)
                percentiles = {
                    name: _percentiles(tuple(row[name] for row in factors)) for name in names
                }
                scored = []
                for assessed_row, factor_row in zip(eligible, factors, strict=True):
                    ranks = {name: percentiles[name][factor_row[name]] for name in names}
                    quality = (ranks["roe"] + ranks["net_margin"]) / 2
                    growth = (ranks["annual_eps_growth"] + ranks["quarterly_revenue_growth"]) / 2
                    value = (ranks["earnings_yield"] + ranks[cash_factor]) / 2
                    score = (
                        quality * policy.quality_weight
                        + growth * policy.growth_weight
                        + value * policy.valuation_weight
                    )
                    scored.append(replace(assessed_row.decision, priority_score=score))
                scored.sort(
                    key=lambda row: (
                        -(row.priority_score if row.priority_score is not None else Decimal(0)),
                        row.symbol,
                        row.instrument_id or "",
                    )
                )
                ranked = tuple(
                    replace(row, ordinal_rank=index) for index, row in enumerate(scored, 1)
                )
                groups[horizon] = ranked
                updates.update({(row.horizon, row.symbol): row for row in ranked})
            decisions = tuple(
                sorted(
                    (
                        updates.get((row.decision.horizon, row.decision.symbol), row.decision)
                        for row in assessed
                    ),
                    key=lambda row: (row.horizon, row.symbol, row.instrument_id or ""),
                )
            )
            return CurrentStockRankings(
                as_of=as_of,
                policy_hash=policy.policy_hash,
                assessments=decisions,
                long_term=groups["long_term"],
                tactical=groups["tactical"],
                status="ranked"
                if groups["long_term"] or groups["tactical"]
                else "no_analytical_candidate",
            )
    except (DecimalException, OverflowError):
        raise StockInvestmentError("stock_investment_arithmetic_invalid") from None


@dataclass(frozen=True, slots=True, kw_only=True)
class ThreefoldScenarioAssumptions:
    annual_earnings_growth: Decimal
    annual_share_count_growth: Decimal
    terminal_pe: Decimal
    years: int
    earnings_basis: Literal["consistent_with_reported_base_pe"] = "consistent_with_reported_base_pe"


@dataclass(frozen=True, slots=True, kw_only=True)
class ThreefoldScenarioResult:
    status: Literal["defined", "unavailable"]
    as_of: datetime
    expires_at: datetime | None
    assumptions: ThreefoldScenarioAssumptions | None
    price_multiple: Decimal | None
    threefold_reached: bool | None
    source_refs: tuple[CurrentEvidenceRef, ...]
    reason_codes: tuple[str, ...]
    base_evidence_hash: str | None
    policy_hash: str
    scenario_only: Literal[True] = field(default=True, init=False)
    dividends_excluded: Literal[True] = field(default=True, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)


def evaluate_threefold_scenario(
    base_pe_fact: CurrentMetric,
    assumptions: ThreefoldScenarioAssumptions | None,
    *,
    as_of: datetime,
    policy: CurrentInvestmentPolicy | None = None,
) -> ThreefoldScenarioResult:
    """A declared P/E/share-count scenario, with no probability or ranking effect."""
    chosen = CurrentInvestmentPolicy() if policy is None else policy
    _policy(chosen)
    try:
        as_of = require_utc(as_of)
    except ValueError:
        raise StockInvestmentError("stock_investment_decisions_invalid") from None
    needs: set[str] = set()
    expiries: list[datetime] = []
    multiple = None
    base_hash = None
    _check(type(base_pe_fact) is CurrentMetric)
    _refs_shape(base_pe_fact.refs)
    if (
        base_pe_fact.name != "pe_ratio"
        or not _number(base_pe_fact.value)
        or base_pe_fact.value is None
        or base_pe_fact.value <= 0
        or base_pe_fact.unit not in ("multiple", "ratio")
        or base_pe_fact.period_basis != "provider_current"
    ):
        needs.add("scenario_base_pe_unusable")
    else:
        symbols = {ref.symbol for ref in base_pe_fact.refs}
        instruments = {
            ref.instrument_id for ref in base_pe_fact.refs if ref.instrument_id is not None
        }
        if len(symbols) != 1 or None in symbols or len(instruments) > 1:
            needs.add("scenario_base_scope_unusable")
        else:
            symbol = next(iter(symbols))
            if not isinstance(symbol, str):
                raise StockInvestmentError("stock_investment_decisions_invalid")
            scope = CurrentStockEvidence(
                symbol=symbol,
                instrument_id=next(iter(instruments)) if instruments else None,
                instrument_type="stock",
                horizon="long_term",
                metrics=(base_pe_fact,),
                identity_refs=(),
            )
            _shape(scope)
            _use_refs(
                base_pe_fact.refs,
                scope,
                "scenario_base_pe",
                _allowed_tools("pe_ratio"),
                as_of,
                chosen,
                needs,
                expiries,
            )
            base_hash = _hash(("current-scenario-base-v1", _metric_wire(base_pe_fact)))
    if assumptions is None:
        needs.add("scenario_assumptions_missing")
    elif (
        type(assumptions) is not ThreefoldScenarioAssumptions
        or type(assumptions.years) is not int
        or not 1 <= assumptions.years <= 30
        or not all(
            _number(value)
            for value in (
                assumptions.annual_earnings_growth,
                assumptions.annual_share_count_growth,
                assumptions.terminal_pe,
            )
        )
        or assumptions.annual_earnings_growth <= -1
        or assumptions.annual_share_count_growth <= -1
        or assumptions.terminal_pe <= 0
        or assumptions.earnings_basis != "consistent_with_reported_base_pe"
    ):
        needs.add("scenario_assumptions_invalid")
    if not needs and assumptions is not None and base_pe_fact.value is not None:
        try:
            with localcontext(_CONTEXT):
                result = (assumptions.terminal_pe / base_pe_fact.value) * (
                    (
                        (1 + assumptions.annual_earnings_growth)
                        / (1 + assumptions.annual_share_count_growth)
                    )
                    ** assumptions.years
                )
                if _computed_number(result):
                    multiple = result
                else:
                    needs.add("scenario_arithmetic_out_of_bounds")
        except DecimalException:
            needs.add("scenario_arithmetic_invalid")
    return ThreefoldScenarioResult(
        status="unavailable" if needs else "defined",
        as_of=as_of,
        expires_at=min(expiries) if expiries and not needs else None,
        assumptions=assumptions,
        price_multiple=multiple,
        threefold_reached=None if multiple is None else multiple >= 3,
        source_refs=base_pe_fact.refs,
        reason_codes=tuple(sorted(needs)),
        base_evidence_hash=base_hash,
        policy_hash=chosen.policy_hash,
    )
