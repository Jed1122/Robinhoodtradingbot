"""Retained-source retrospective views; no fictional asset or broker authority."""

from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass, replace
from datetime import UTC, datetime
from typing import Literal

from trading_bot.market_data.recording import content_hash
from trading_bot.market_data.stock_economic_evidence import StockCashDividendEvent
from trading_bot.research.hybrid_policies import AnnualQuality, CalendarSession, _annual_compact
from trading_bot.research.hybrid_strategies import FAMILIES, PriceBar
from trading_bot.research.stock_annual_quality import revalidate_annual_quality
from trading_bot.research.stock_monetary_admission import (
    MonetaryCaseDependency,
    PreparedRetrospectiveMonetaryInputs,
    revalidate_monetary_inputs,
)
from trading_bot.research.stock_replay_schedule import (
    RetrospectiveReplaySchedule,
    modeled_dividend_availability,
    modeled_settlement_availability,
    revalidate_replay_schedule,
)

SYMBOLS = ("AXP", "AAPL", "BAC", "CVX", "KO", "KHC", "MCO", "OXY", "SPY")
_OMITTED = (
    "sector_cap",
    "historical_market_cap",
    "earnings_avoidance",
    "historical_bid_ask_spread",
    "historical_broker_tradability",
    "complete_lifecycle_coverage",
)


def _check(condition: bool, reason: str = "retrospective_replay_inputs_invalid") -> None:
    if not condition:
        raise ValueError(reason)


def _hash(value: object) -> str:
    return str(content_hash(value))


def _same(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if is_dataclass(left) and not isinstance(left, type):
        return _same(object.__getstate__(left), object.__getstate__(right))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_same(v, right[k]) for k, v in left.items())
    if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)):
        return len(left) == len(right) and all(
            _same(a, b) for a, b in zip(left, right, strict=True)
        )
    return bool(left == right)


@dataclass(frozen=True, slots=True)
class _Unqualified:
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    full_task5_complete: Literal[False] = field(default=False, init=False)


def _flags(value: _Unqualified) -> None:
    _check(
        value.qualified
        is value.source_qualified
        is value.strategy_qualified
        is value.investment_eligible
        is value.trading_enabled
        is value.live_authorized
        is value.full_task5_complete
        is False,
        "unqualified_retrospective_scope_required",
    )


@dataclass(frozen=True, slots=True)
class RetrospectiveReplayConvention:
    profile: str = field(default="conditional_retrospective_observed_cash_replay_v1", init=False)
    risk_profile: str = field(default="observed_cash_conditional_reference_v1", init=False)
    omitted_screens: tuple[str, ...] = field(default=_OMITTED, init=False)
    price_units: str = field(default="raw_accounting_split_signals_no_conversion_v1", init=False)
    membership: str = field(default="reported_public_date_plus_one_UTC_day_v1", init=False)
    membership_available_at: datetime = field(default=datetime(2024, 2, 16, tzinfo=UTC), init=False)
    liquidity: str = field(
        default="prior_20_completed_raw_close_times_native_volume_USD_proxy_v1", init=False
    )
    fractional: str = field(default="modeled_1e_minus_6_and_USD1_minimum_v1", init=False)


@dataclass(frozen=True, slots=True)
class RetrospectiveReplayRequest:
    monetary: PreparedRetrospectiveMonetaryInputs
    schedule: RetrospectiveReplaySchedule
    annual_quality: tuple[AnnualQuality, ...]
    convention: RetrospectiveReplayConvention


@dataclass(frozen=True, slots=True)
class RetrospectiveAssetView:
    symbol: str
    role: Literal["stock_candidate", "passive_comparison"]
    accounting_bars: tuple[PriceBar, ...]
    signal_bars: tuple[PriceBar, ...]
    native_volume: tuple[int, ...]
    native_interpolated: tuple[bool | None, ...]
    native_source_indices: tuple[int, ...]
    raw_source_sha256: str
    split_source_sha256: str
    constraint_status: tuple[tuple[str, str], ...]
    native_quote_currency: None = field(default=None, init=False)
    interpreted_account_currency: Literal["USD"] = field(default="USD", init=False)


@dataclass(frozen=True, slots=True)
class _RetrospectivePanel(_Unqualified):
    assets: tuple[RetrospectiveAssetView, ...]
    calendar: tuple[CalendarSession, ...]
    price_session_count: int
    dividends: tuple[StockCashDividendEvent, ...]
    settlement_at: tuple[datetime | None, ...]
    dividend_available_at: tuple[tuple[str, datetime | None], ...]
    annual_quality: tuple[AnnualQuality, ...]
    annual_hashes: tuple[str, ...]
    convention: RetrospectiveReplayConvention
    source_root: str
    row_hashes: tuple[str, ...]
    prefix_hashes: tuple[str, ...]
    dividend_lookup_hashes: tuple[str, ...] = ()
    annual_context_root: str = ""
    calendar_hashes: tuple[str, ...] = ()
    metadata_hash: str = ""

    @property
    def evidence_hash(self) -> str:
        """Compact root only; the public boundary owns fresh source revalidation."""
        return self.source_root


def _row_leaf(panel: _RetrospectivePanel, index: int) -> str:
    return _hash(
        (
            "retrospective-source-row-v1",
            index,
            panel.calendar[index],
            panel.settlement_at[index],
            panel.annual_context_root,
            panel.metadata_hash,
            tuple(
                (
                    a.symbol,
                    a.role,
                    a.raw_source_sha256,
                    a.split_source_sha256,
                    a.native_source_indices[index],
                    a.accounting_bars[index],
                    a.signal_bars[index],
                    a.native_volume[index],
                    a.native_interpolated[index],
                )
                for a in panel.assets
            ),
        )
    )


def _metadata_leaf(panel: _RetrospectivePanel) -> str:
    """Only descriptors/proof digests; never source bytes or price observations."""
    return _hash(
        (
            "retrospective-panel-metadata-v1",
            panel.source_root,
            panel.convention,
            panel.price_session_count,
            len(panel.calendar),
            panel.calendar_hashes,
            panel.annual_context_root,
            panel.dividend_lookup_hashes,
            tuple(
                (
                    a.symbol,
                    a.role,
                    a.raw_source_sha256,
                    a.split_source_sha256,
                    a.native_quote_currency,
                    a.interpreted_account_currency,
                    a.constraint_status,
                    tuple(
                        (type(v).__qualname__, len(v))
                        for v in (
                            a.accounting_bars,
                            a.signal_bars,
                            a.native_volume,
                            a.native_interpolated,
                            a.native_source_indices,
                        )
                    ),
                )
                for a in panel.assets
            ),
        )
    )


def _check_panel_metadata(panel: _RetrospectivePanel) -> None:
    _check(type(panel) is _RetrospectivePanel, "owned_retrospective_panel_required")
    _flags(panel)
    _check(
        type(panel.convention) is RetrospectiveReplayConvention
        and _same(panel.convention, RetrospectiveReplayConvention()),
        "retrospective_convention_changed",
    )
    _check(
        tuple(a.symbol for a in panel.assets) == SYMBOLS and panel.price_session_count == 706,
        "full_retrospective_cohort_required",
    )
    expected_constraints = tuple(
        (name, "explicitly_omitted_conditional_screen") for name in _OMITTED
    )
    for index, asset in enumerate(panel.assets):
        _check(
            type(asset) is RetrospectiveAssetView
            and asset.role == ("passive_comparison" if index == 8 else "stock_candidate")
            and asset.native_quote_currency is None
            and asset.interpreted_account_currency == "USD"
            and asset.constraint_status == expected_constraints,
            "retrospective_asset_metadata_changed",
        )
        _check(
            all(
                type(v) is tuple and len(v) == 706
                for v in (
                    asset.accounting_bars,
                    asset.signal_bars,
                    asset.native_volume,
                    asset.native_interpolated,
                    asset.native_source_indices,
                )
            ),
            "retrospective_asset_shape_changed",
        )
    _check(
        type(panel.calendar) is tuple
        and type(panel.calendar_hashes) is tuple
        and len(panel.calendar_hashes) == len(panel.calendar),
        "retrospective_calendar_proof_shape_changed",
    )
    _check(
        _metadata_leaf(panel) == panel.metadata_hash, "retrospective_metadata_commitment_changed"
    )


def _calendar_leaf(panel: _RetrospectivePanel, index: int) -> str:
    return _hash(
        ("retrospective-calendar-leaf-v1", panel.source_root, index, panel.calendar[index])
    )


def _check_native_calendar(panel: _RetrospectivePanel, *, first: int, last: int) -> None:
    _check(
        type(first) is int and type(last) is int and 0 <= first <= last < 706,
        "native_calendar_window_required",
    )
    for index in range(first, last + 1):
        _check(type(panel.calendar[index]) is CalendarSession, "typed_native_calendar_row_required")
        _check(
            _calendar_leaf(panel, index) == panel.calendar_hashes[index],
            "retrospective_calendar_leaf_changed",
        )


def _check_panel_window(panel: _RetrospectivePanel, *, first: int, last: int) -> None:
    _check_panel_metadata(panel)
    _check(
        type(first) is int and type(last) is int and 0 <= first <= last < 706,
        "native_price_window_required",
    )
    _check(
        tuple(a.symbol for a in panel.assets) == SYMBOLS and panel.price_session_count == 706,
        "full_retrospective_cohort_required",
    )
    _check(
        len(panel.dividends)
        == len(panel.dividend_available_at)
        == len(panel.dividend_lookup_hashes),
        "dividend_lookup_shape_changed",
    )
    for i, event in enumerate(panel.dividends):
        _check(
            panel.dividend_available_at[i][0] == event.id
            and _hash(
                (
                    "retrospective-dividend-lookup-v1",
                    panel.source_root,
                    event,
                    panel.dividend_available_at[i],
                )
            )
            == panel.dividend_lookup_hashes[i],
            "dividend_funding_lookup_changed",
        )
    for index in range(first, last + 1):
        _check(
            _row_leaf(panel, index) == panel.row_hashes[index], "retrospective_source_leaf_changed"
        )


@dataclass(frozen=True, slots=True)
class _PreparedInputs(_Unqualified):
    request: RetrospectiveReplayRequest
    assets: tuple[RetrospectiveAssetView, ...] = field(init=False)
    calendar: tuple[CalendarSession, ...] = field(init=False)
    full_constrained_cases: tuple[MonetaryCaseDependency, ...] = field(init=False)
    long_term_quality_slots: tuple[tuple[str, str], ...] = field(init=False)
    supplemental_annual_symbols: tuple[str, ...] = field(init=False)
    convention: RetrospectiveReplayConvention = field(init=False)
    families: tuple[str, ...] = field(default=FAMILIES, init=False)
    price_session_count: Literal[706] = field(default=706, init=False)
    _panel: _RetrospectivePanel = field(init=False, repr=False)

    def __post_init__(self) -> None:
        panel = _compile(self.request)
        _check(
            (self.request.schedule.status == "conditionally_prepared")
            == isinstance(self, PreparedRetrospectiveReplayInputs),
            "retrospective_preparation_status_mismatch",
        )
        object.__setattr__(self, "_panel", panel)
        object.__setattr__(self, "assets", panel.assets)
        object.__setattr__(self, "calendar", panel.calendar)
        object.__setattr__(self, "full_constrained_cases", self.request.monetary.cases)
        object.__setattr__(
            self,
            "long_term_quality_slots",
            tuple((s, "quality_stock_allocator_unavailable") for s in SYMBOLS[:8]),
        )
        object.__setattr__(
            self,
            "supplemental_annual_symbols",
            tuple(sorted({a.request.filing.symbol for a in panel.annual_quality})),
        )
        object.__setattr__(self, "convention", panel.convention)

    @property
    def evidence_hash(self) -> str:
        return revalidate_retrospective_replay_inputs(self)._panel.source_root


@dataclass(frozen=True, slots=True)
class PreparedRetrospectiveReplayInputs(_PreparedInputs):
    status: Literal["conditionally_prepared"] = field(default="conditionally_prepared", init=False)


@dataclass(frozen=True, slots=True)
class UnavailableRetrospectiveReplayInputs(_PreparedInputs):
    status: Literal["unavailable"] = field(default="unavailable", init=False)


def _compile(request: RetrospectiveReplayRequest) -> _RetrospectivePanel:
    _check(
        type(request) is RetrospectiveReplayRequest
        and type(request.monetary) is PreparedRetrospectiveMonetaryInputs,
        "retained_monetary_request_required",
    )
    _check(
        type(request.convention) is RetrospectiveReplayConvention
        and _same(request.convention, RetrospectiveReplayConvention()),
        "fixed_retrospective_convention_required",
    )
    monetary = revalidate_monetary_inputs(request.monetary)
    timed = revalidate_replay_schedule(request.schedule)
    _check(
        _same(monetary.request.calendar, timed.native_calendar),
        "retrospective_calendar_source_mismatch",
    )
    _check(
        type(request.annual_quality) is tuple and len(request.annual_quality) <= 64,
        "bounded_annual_inventory_required",
    )
    annual = tuple(revalidate_annual_quality(a) for a in request.annual_quality)
    _check(
        all(a.request.filing.symbol in SYMBOLS[:8] for a in annual), "annual_stock_cohort_required"
    )
    annual_hashes = tuple(a.evidence_hash for a in annual)
    annual_records = {
        digest: _annual_compact(bundle)
        for bundle, digest in zip(annual, annual_hashes, strict=True)
    }
    annual_context_root = _hash(
        (
            "owned-annual-policy-inventory-v1",
            tuple((digest, annual_records[digest]) for digest in sorted(annual_records)),
        )
    )
    assets = tuple(
        RetrospectiveAssetView(
            slot.raw.request.symbol,
            "passive_comparison" if i == 8 else "stock_candidate",
            tuple(
                PriceBar(timed.market_sessions[j].closes_at, b.open_price, b.close_price)
                for j, b in enumerate(slot.raw.bars)
            ),
            tuple(
                PriceBar(timed.market_sessions[j].closes_at, b.open_price, b.close_price)
                for j, b in enumerate(slot.split.bars)
            ),
            tuple(b.volume for b in slot.raw.bars),
            tuple(b.interpolated for b in slot.raw.bars),
            tuple(b.source_index for b in slot.raw.bars),
            slot.raw.content_sha256,
            slot.split.content_sha256,
            tuple((name, "explicitly_omitted_conditional_screen") for name in _OMITTED),
        )
        for i, slot in enumerate(monetary.request.slots)
    )
    dividends = tuple(
        event for symbol in monetary.symbols for event in symbol.holding_dependent_events
    )
    root = _hash(
        (
            "retrospective-replay-inputs-v1",
            monetary.source_graph_sha256,
            timed.source_graph_sha256,
            timed._evidence_hash,
            request.convention,
            tuple(sorted(annual_hashes)),
            annual_context_root,
        )
    )
    panel = _RetrospectivePanel(
        assets,
        timed.market_sessions,
        706,
        dividends,
        tuple(
            None
            if i < 200
            else modeled_settlement_availability(timed, trade_session_index=i).available_at
            for i in range(706)
        ),
        tuple((e.id, modeled_dividend_availability(timed, pay_date=e.pay_date)) for e in dividends),
        annual,
        annual_hashes,
        request.convention,
        root,
        (),
        (),
        annual_context_root=annual_context_root,
    )
    panel = replace(
        panel,
        calendar_hashes=tuple(_calendar_leaf(panel, i) for i in range(len(panel.calendar))),
        dividend_lookup_hashes=tuple(
            _hash(("retrospective-dividend-lookup-v1", root, event, panel.dividend_available_at[i]))
            for i, event in enumerate(dividends)
        ),
    )
    panel = replace(panel, metadata_hash=_metadata_leaf(panel))
    rows = tuple(_row_leaf(panel, i) for i in range(706))
    prefix = [root]
    for i, leaf in enumerate(rows):
        prefix.append(_hash(("retrospective-prefix-v1", prefix[-1], i, leaf)))
    return replace(panel, row_hashes=rows, prefix_hashes=tuple(prefix))


def prepare_retrospective_replay_inputs(
    request: RetrospectiveReplayRequest,
) -> PreparedRetrospectiveReplayInputs | UnavailableRetrospectiveReplayInputs:
    _check(type(request) is RetrospectiveReplayRequest, "retrospective_request_required")
    cls = (
        PreparedRetrospectiveReplayInputs
        if request.schedule.status == "conditionally_prepared"
        else UnavailableRetrospectiveReplayInputs
    )
    return cls(request)


def revalidate_retrospective_replay_inputs(
    value: _PreparedInputs,
) -> PreparedRetrospectiveReplayInputs | UnavailableRetrospectiveReplayInputs:
    _check(
        type(value) in (PreparedRetrospectiveReplayInputs, UnavailableRetrospectiveReplayInputs),
        "retrospective_prepared_type_required",
    )
    _flags(value)
    rebuilt = prepare_retrospective_replay_inputs(value.request)
    _check(_same(value, rebuilt), "retrospective_derived_inputs_changed")
    return rebuilt
