"""Conditional observed-event input preparation, without execution or qualification.

Whole native observations are reparsed on every preparation/revalidation. Receipt
hashes/clocks and the handoff pin are caller-declared source bindings, not source
authentication. This module computes no entitlement, strategy or monetary return.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, is_dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal, cast

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.stock_daily_series import (
    StockDailyCalendar,
    StockDailySession,
    parse_stock_daily_calendar,
)
from trading_bot.market_data.stock_economic_evidence import (
    DatedStockIdentity,
    StockCashDividendEvent,
    StockCashDividendEvidence,
    parse_cash_dividend_panel,
    parse_dated_stock_identity,
)
from trading_bot.market_data.stock_split_comparison import (
    StockSplitSeries,
    parse_stock_split_series,
)
from trading_bot.research.hybrid_strategies import FAMILIES

_SYMBOLS = ("AXP", "AAPL", "BAC", "CVX", "KO", "KHC", "MCO", "OXY", "SPY")
_FAMILIES = FAMILIES
_LIMITATIONS = (
    "conditional_usd_mapping_not_native_daily_currency_or_continuous_identity",
    "observed_cash_inventory_not_complete_total_return_or_lifecycle_coverage",
    "retrospective_observations_not_contemporaneous_receipts",
    "receipt_and_manifest_pins_are_caller_declared_not_authenticated",
    "missing_risk_fundamental_event_inputs_are_not_successful_cash_policies",
    "settlement_funding_and_empty_padding_not_admitted_or_generated",
    "no_strategy_entitlement_monetary_result_or_live_authority",
)
_CASE_GAPS = (
    "causal_risk_metadata_unavailable",
    "tradability_and_spread_unavailable",
    "corporate_action_coverage_unavailable",
    "settlement_and_funding_admission_unavailable",
    "operating_cost_admission_unavailable",
)
_PRICE_HISTORY = {"momentum": 253, "trend": 200, "breakout": 21, "mean_reversion": 200}
_FAMILY_GAPS = {
    "quality_momentum": "publication_aware_annual_quality_unavailable",
    "pead": "publication_aware_earnings_unavailable",
    "revision_momentum": "historical_estimate_vintages_unavailable",
}


class StockMonetaryAdmissionError(ValueError):
    """An invalid public result or input outside bounded typed API use."""

    def __init__(self) -> None:
        super().__init__("stock_monetary_admission_invalid")


class _Gap(ValueError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise _Gap(reason)


def _same(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, Decimal) and isinstance(right, Decimal):
        return left.as_tuple() == right.as_tuple()
    if is_dataclass(left) and not isinstance(left, type):
        return _same(object.__getstate__(left), object.__getstate__(right))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _same(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, tuple) and isinstance(right, tuple):
        return len(left) == len(right) and all(
            _same(a, b) for a, b in zip(left, right, strict=True)
        )
    return bool(left == right)


def _digest(value: object) -> str:
    """Exact, context-independent source fingerprint; no arithmetic or global cache."""
    remaining = 2_500_000

    def encode(item: object) -> object:
        nonlocal remaining
        remaining -= 1
        if remaining < 0:
            raise StockMonetaryAdmissionError()
        if type(item) is bytes:
            if len(item) > 8 * 1024 * 1024:
                raise StockMonetaryAdmissionError()
            return {"bytes": len(item), "sha256": hashlib.sha256(item).hexdigest()}
        if type(item) is Decimal:
            native = item.as_tuple()
            return {
                "Decimal": {
                    "sign": native.sign,
                    "digits": native.digits,
                    "exponent": native.exponent,
                }
            }
        if type(item) is datetime:
            return {"datetime": item.isoformat()}
        if type(item) is date:
            return {"date": item.isoformat()}
        if is_dataclass(item) and not isinstance(item, type):
            return {
                "type": type(item).__module__ + "." + type(item).__qualname__,
                "state": encode(object.__getstate__(item)),
            }
        if isinstance(item, dict):
            if not all(type(key) is str for key in item):
                raise StockMonetaryAdmissionError()
            return {"dict": {key: encode(item[key]) for key in sorted(item)}}
        if isinstance(item, (tuple, list)):
            return {type(item).__name__: [encode(x) for x in item]}
        if type(item) in (str, int, bool) or item is None:
            return item
        raise StockMonetaryAdmissionError()

    body = json.dumps(encode(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class StockMonetaryIdentitySource:
    identity: DatedStockIdentity
    original_csv: bytes


@dataclass(frozen=True, slots=True)
class StockMonetarySymbolSources:
    raw: StockSplitSeries
    split: StockSplitSeries
    identities: tuple[StockMonetaryIdentitySource, ...]


@dataclass(frozen=True, slots=True)
class StockMonetarySourceBinding:
    """Declared original receipt identity, distinct from the decoded content hash."""

    role: str
    observation_sha256: str
    receipt_sha256: str
    requested_at: datetime
    received_at: datetime


@dataclass(frozen=True, slots=True)
class StockMonetaryAssumptions:
    currency_mapping: str = field(default="retrospective_usd_ticker_mapping_v1", init=False)
    identity_scope: str = field(default="two_retrospective_endpoint_observations_v1", init=False)
    cash_inventory: str = field(default="observed_native_cash_events_only_v1", init=False)
    price_units: str = field(default="raw_accounting_split_signals_no_conversion_v1", init=False)
    first_execution_session: Literal[200] = field(default=200, init=False)
    membership_not_before: date = field(default=date(2024, 2, 15), init=False)
    historical_receipt_claim: Literal[False] = field(default=False, init=False)
    corporate_action_coverage: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class StockMonetaryRequest:
    slots: tuple[StockMonetarySymbolSources, ...]
    calendar: StockDailyCalendar
    dividends: tuple[StockCashDividendEvidence, ...]
    original_dividend_csv: bytes
    handoff_manifest_sha256: str
    source_bindings: tuple[StockMonetarySourceBinding, ...]
    assumptions: StockMonetaryAssumptions


@dataclass(frozen=True, slots=True)
class _NotQualified:
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class MonetarySymbolPreparation(_NotQualified):
    symbol: str
    role: Literal["stock_candidate", "benchmark"]
    sources: StockMonetarySymbolSources | None
    status: Literal["conditionally_prepared", "unavailable"]
    reason_codes: tuple[str, ...]
    incidental_identity_changes: tuple[str, ...] = ()
    not_earned_events: tuple[StockCashDividendEvent, ...] = ()
    holding_dependent_events: tuple[StockCashDividendEvent, ...] = ()
    unpaid_terminal_events: tuple[StockCashDividendEvent, ...] = ()
    native_quote_currency: None = field(default=None, init=False)
    interpreted_account_currency: Literal["USD"] = field(default="USD", init=False)
    cash_available: Literal[False] = field(default=False, init=False)
    entitlement_calculated: Literal[False] = field(default=False, init=False)
    cash_inventory_complete: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class MonetaryCaseDependency(_NotQualified):
    symbol: str
    family: str
    signal_inputs_status: Literal["conditionally_prepared", "unavailable"]
    reason_codes: tuple[str, ...]
    evaluation_status: Literal["unavailable"] = field(default="unavailable", init=False)


@dataclass(frozen=True, slots=True)
class _Assessment:
    source_graph_sha256: str
    symbols: tuple[MonetarySymbolPreparation, ...]
    cases: tuple[MonetaryCaseDependency, ...]
    reason_codes: tuple[str, ...]


def _source_bindings(
    request: StockMonetaryRequest, expected: dict[str, tuple[str, datetime]]
) -> None:
    try:
        _require(type(request.source_bindings) is tuple, "source_binding_invalid")
        _require(len(request.source_bindings) == 38, "source_binding_invalid")
        seen: set[str] = set()
        for binding in request.source_bindings:
            _require(type(binding) is StockMonetarySourceBinding, "source_binding_invalid")
            _require(
                type(binding.role) is str and binding.role in expected and binding.role not in seen,
                "source_binding_invalid",
            )
            seen.add(binding.role)
            _require_sha256_hex(binding.observation_sha256, "observation")
            _require_sha256_hex(binding.receipt_sha256, "original receipt")
            require_utc(binding.requested_at)
            require_utc(binding.received_at)
            _require(binding.requested_at <= binding.received_at, "source_binding_invalid")
            _require(
                (binding.observation_sha256, binding.received_at) == expected[binding.role],
                "source_binding_invalid",
            )
        _require(seen == set(expected), "source_binding_invalid")
    except (ValueError, TypeError, AttributeError):
        raise _Gap("source_binding_invalid") from None


def _calendar(request: StockMonetaryRequest) -> StockDailyCalendar:
    try:
        calendar = request.calendar
        _require(type(calendar) is StockDailyCalendar, "calendar_source_graph_invalid")
        rebuilt = parse_stock_daily_calendar(
            calendar.original_content_json,
            expected_sha256=calendar.content_sha256,
            received_at=calendar.received_at,
            market_timezone=calendar.market_timezone,
        )
        _require(_same(calendar, rebuilt), "calendar_source_graph_invalid")
        _require(202 <= len(calendar.sessions) <= 10000, "calendar_source_graph_invalid")
        _require(
            calendar.sessions[200].session_date >= request.assumptions.membership_not_before,
            "membership_not_public_at_activation",
        )
        return calendar
    except (ValueError, TypeError, AttributeError, ArithmeticError):
        raise _Gap("calendar_source_graph_invalid") from None


def _prices(source: StockSplitSeries, calendar: StockDailyCalendar) -> None:
    try:
        _require(type(source) is StockSplitSeries, "price_source_graph_invalid")
        rebuilt = parse_stock_split_series(
            source.original_content_json,
            expected_sha256=source.content_sha256,
            request=source.request,
            received_at=source.received_at,
        )
        _require(_same(rebuilt, source), "price_source_graph_invalid")
        _require(
            not (
                source.null_bar_indices
                or source.results_missing
                or source.bars_missing
                or source.not_found
            ),
            "price_source_graph_invalid",
        )
        _require(
            source.request.start_time == datetime.combine(calendar.request_start, time.min, UTC)
            and source.request.end_time
            == datetime.combine(calendar.request_end + timedelta(days=1), time.min, UTC),
            "price_source_graph_invalid",
        )
        _require(len(source.bars) == len(calendar.sessions), "price_source_graph_invalid")
        for bar, session in zip(source.bars, calendar.sessions, strict=True):
            _require(
                bar.begins_at == datetime.combine(session.session_date, time.min, UTC)
                and bar.session == "reg"
                and bar.volume > 0
                and bar.interpolated is not True
                and session.closes_at <= source.received_at,
                "price_source_graph_invalid",
            )
    except (ValueError, TypeError, AttributeError, ArithmeticError):
        raise _Gap("price_source_graph_invalid") from None


def _identities(
    sources: StockMonetarySymbolSources,
    symbol: str,
    calendar: StockDailyCalendar,
    bindings: dict[str, tuple[str, datetime]],
) -> tuple[str, ...]:
    try:
        _require(
            type(sources.identities) is tuple and len(sources.identities) == 2,
            "identity_source_graph_invalid",
        )
        dates = (calendar.sessions[0].session_date, calendar.sessions[-1].session_date)
        for label, source, day in zip(("start", "end"), sources.identities, dates, strict=True):
            _require(type(source) is StockMonetaryIdentitySource, "identity_source_graph_invalid")
            native = source.identity
            _require(type(native) is DatedStockIdentity, "identity_source_graph_invalid")
            rebuilt = parse_dated_stock_identity(
                source.original_csv,
                expected_sha256=native.original_csv_sha256,
                symbol=symbol,
                requested_date=day,
                received_at=native.received_at,
            )
            _require(_same(native, rebuilt), "identity_source_graph_invalid")
            _require(
                native.cik is not None
                and native.composite_figi is not None
                and native.share_class_figi is not None
                and native.security_type is not None,
                "identity_source_graph_invalid",
            )
            bindings[f"identity:{symbol}:{label}"] = (
                native.original_csv_sha256,
                native.received_at,
            )
        start, end = (source.identity for source in sources.identities)
        _require(
            (
                start.symbol,
                start.market,
                start.locale,
                start.currency,
                start.cik,
                start.composite_figi,
                start.share_class_figi,
                start.security_type,
                start.active,
            )
            == (
                end.symbol,
                end.market,
                end.locale,
                end.currency,
                end.cik,
                end.composite_figi,
                end.share_class_figi,
                end.security_type,
                end.active,
            )
            and start.active is True
            and start.security_type == ("ETF" if symbol == "SPY" else "CS"),
            "identity_core_conflict",
        )
        return tuple(
            name
            for name, before, after in (
                ("name", start.name, end.name),
                ("primary_exchange", start.primary_exchange, end.primary_exchange),
                ("list_date", start.list_date, end.list_date),
            )
            if before != after
        )
    except _Gap:
        raise
    except (ValueError, TypeError, AttributeError, ArithmeticError):
        raise _Gap("identity_source_graph_invalid") from None


def _inventory(
    request: StockMonetaryRequest,
    calendar: StockDailyCalendar,
    bindings: dict[str, tuple[str, datetime]],
) -> None:
    try:
        _require(
            type(request.dividends) is tuple and len(request.dividends) == 9,
            "cash_panel_source_graph_invalid",
        )
        first = request.dividends[0]
        _require(type(first) is StockCashDividendEvidence, "cash_panel_source_graph_invalid")
        # The complete original is globally validated before per-symbol projections.
        rebuilt = parse_cash_dividend_panel(
            request.original_dividend_csv,
            expected_sha256=first.original_csv_sha256,
            symbols=_SYMBOLS,
            ex_start=calendar.sessions[0].session_date,
            ex_end=calendar.sessions[-1].session_date,
            received_at=first.received_at,
        )
        _require(_same(rebuilt, request.dividends), "cash_panel_source_graph_invalid")
        bindings["dividends"] = (first.original_csv_sha256, first.received_at)
    except (ValueError, TypeError, AttributeError, ArithmeticError):
        raise _Gap("cash_panel_source_graph_invalid") from None


def _validate(request: StockMonetaryRequest) -> tuple[tuple[str, ...], ...]:
    _require(type(request.slots) is tuple and len(request.slots) == 9, "cohort_slots_invalid")
    _require(
        type(request.assumptions) is StockMonetaryAssumptions
        and _same(request.assumptions, StockMonetaryAssumptions()),
        "assumptions_invalid",
    )
    try:
        _require_sha256_hex(request.handoff_manifest_sha256, "handoff manifest")
    except (ValueError, TypeError):
        raise _Gap("handoff_pin_invalid") from None
    calendar = _calendar(request)
    bindings = {"calendar": (calendar.content_sha256, calendar.received_at)}
    changes = []
    for symbol, sources in zip(_SYMBOLS, request.slots, strict=True):
        _require(type(sources) is StockMonetarySymbolSources, "cohort_slots_invalid")
        for adjustment, series in (("none", sources.raw), ("split", sources.split)):
            _prices(series, calendar)
            _require(
                series.request.symbol == symbol and series.request.adjustment_type == adjustment,
                "cohort_slots_invalid",
            )
            bindings[f"price:{symbol}:{adjustment}"] = (series.content_sha256, series.received_at)
        _require(
            all(
                (
                    raw.begins_at,
                    raw.open_price,
                    raw.high_price,
                    raw.low_price,
                    raw.close_price,
                    raw.volume,
                )
                == (
                    split.begins_at,
                    split.open_price,
                    split.high_price,
                    split.low_price,
                    split.close_price,
                    split.volume,
                )
                for raw, split in zip(sources.raw.bars, sources.split.bars, strict=True)
            ),
            "raw_split_units_not_supported",
        )
        changes.append(_identities(sources, symbol, calendar, bindings))
    _inventory(request, calendar, bindings)
    _source_bindings(request, bindings)
    return tuple(changes)


def _case_dependencies(ready: bool, count: int) -> tuple[MonetaryCaseDependency, ...]:
    cases = []
    for symbol in _SYMBOLS[:-1]:
        for family in _FAMILIES:
            gap = _FAMILY_GAPS.get(family)
            enough = family in _PRICE_HISTORY and count >= _PRICE_HISTORY[family]
            reasons: tuple[str, ...] = _CASE_GAPS
            if not ready:
                reasons = ("source_graph_unavailable", *reasons)
            if gap is not None:
                reasons = (gap, *reasons)
            elif not enough:
                reasons = ("insufficient_history", *reasons)
            cases.append(
                MonetaryCaseDependency(
                    symbol,
                    family,
                    "conditionally_prepared" if ready and enough else "unavailable",
                    reasons,
                )
            )
    return tuple(cases)


def _assess(request: StockMonetaryRequest) -> _Assessment:
    if type(request) is not StockMonetaryRequest:
        raise StockMonetaryAdmissionError()
    fingerprint = _digest(request)
    reasons: tuple[str, ...] = ()
    changes: tuple[tuple[str, ...], ...] = ()
    try:
        changes = _validate(request)
    except _Gap as error:
        reasons = (str(error),)
    except (ValueError, TypeError, AttributeError, ArithmeticError, KeyError):
        reasons = ("source_graph_invalid",)
    ready = not reasons
    symbols = []
    count = len(request.calendar.sessions) if ready else 0
    for i, symbol in enumerate(_SYMBOLS):
        before: tuple[StockCashDividendEvent, ...] = ()
        active: tuple[StockCashDividendEvent, ...] = ()
        unpaid: tuple[StockCashDividendEvent, ...] = ()
        if ready:
            activation = request.calendar.sessions[200].session_date
            horizon = request.calendar.sessions[-1].session_date
            events = request.dividends[i].events
            before = tuple(event for event in events if event.ex_date <= activation)
            active = tuple(event for event in events if event.ex_date > activation)
            unpaid = tuple(
                event for event in active if event.pay_date is None or event.pay_date >= horizon
            )
        symbols.append(
            MonetarySymbolPreparation(
                symbol,
                "benchmark" if symbol == "SPY" else "stock_candidate",
                request.slots[i] if ready else None,
                "conditionally_prepared" if ready else "unavailable",
                reasons,
                changes[i] if ready else (),
                before,
                active,
                unpaid,
            )
        )
    return _Assessment(fingerprint, tuple(symbols), _case_dependencies(ready, count), reasons)


@dataclass(frozen=True, slots=True)
class _Result(_NotQualified):
    request: StockMonetaryRequest
    source_graph_sha256: str = field(init=False)
    symbols: tuple[MonetarySymbolPreparation, ...] = field(init=False)
    cases: tuple[MonetaryCaseDependency, ...] = field(init=False)
    reason_codes: tuple[str, ...] = field(init=False)
    families: tuple[str, ...] = field(default=_FAMILIES, init=False)
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)
    source_profile: str = field(default="retrospective_observed_cash_inputs_v1", init=False)
    complete_action_coverage: Literal[False] = field(default=False, init=False)
    full_constrained_portfolio_status: Literal["unavailable"] = field(
        default="unavailable", init=False
    )
    calendar_padding: tuple[StockDailySession, ...] = field(default=(), init=False)
    calendar_padding_status: Literal["unavailable"] = field(default="unavailable", init=False)
    receipt_bindings_are_caller_declared: Literal[True] = field(default=True, init=False)

    def _populate(self, *, require_ready: bool) -> None:
        assessment = _assess(self.request)
        if bool(assessment.reason_codes) == require_ready:
            raise StockMonetaryAdmissionError()
        object.__setattr__(self, "source_graph_sha256", assessment.source_graph_sha256)
        object.__setattr__(self, "symbols", assessment.symbols)
        object.__setattr__(self, "cases", assessment.cases)
        object.__setattr__(self, "reason_codes", assessment.reason_codes)

    @property
    def evidence_hash(self) -> str:
        value = revalidate_monetary_inputs(self)
        return _digest(
            (
                value.source_graph_sha256,
                value.status,
                value.symbols,
                value.cases,
                value.reason_codes,
                value.families,
                value.limitations,
                value.source_profile,
            )
        )


@dataclass(frozen=True, slots=True)
class PreparedRetrospectiveMonetaryInputs(_Result):
    status: Literal["conditionally_prepared_observed_event_inputs"] = field(
        default="conditionally_prepared_observed_event_inputs", init=False
    )

    def __post_init__(self) -> None:
        self._populate(require_ready=True)


@dataclass(frozen=True, slots=True)
class UnavailableRetrospectiveMonetaryInputs(_Result):
    status: Literal["unavailable_source_graph"] = field(
        default="unavailable_source_graph", init=False
    )

    def __post_init__(self) -> None:
        self._populate(require_ready=False)


def prepare_retrospective_monetary_inputs(
    request: StockMonetaryRequest,
) -> PreparedRetrospectiveMonetaryInputs | UnavailableRetrospectiveMonetaryInputs:
    """Bind conditional native inputs; unavailable cases never become cash success."""
    try:
        return PreparedRetrospectiveMonetaryInputs(request)
    except StockMonetaryAdmissionError:
        return UnavailableRetrospectiveMonetaryInputs(request)


def revalidate_monetary_inputs(
    value: _Result,
) -> PreparedRetrospectiveMonetaryInputs | UnavailableRetrospectiveMonetaryInputs:
    """Reparse all originals afresh, including unused text, and reject forged state."""
    try:
        if type(value) not in (
            PreparedRetrospectiveMonetaryInputs,
            UnavailableRetrospectiveMonetaryInputs,
        ):
            raise StockMonetaryAdmissionError()
        rebuilt = prepare_retrospective_monetary_inputs(value.request)
        if not _same(value, rebuilt):
            raise StockMonetaryAdmissionError()
        return cast(
            "PreparedRetrospectiveMonetaryInputs | UnavailableRetrospectiveMonetaryInputs", value
        )
    except (ValueError, TypeError, AttributeError, ArithmeticError, RecursionError):
        raise StockMonetaryAdmissionError() from None
