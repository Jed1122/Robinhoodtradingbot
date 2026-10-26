"""Small fictional session/accounting kernel; no actual-data admission or broker.

The only input factory is explicitly fictional. Prices and risk annotations are
caller-supplied fixture observations, never generated financial evidence. Existing
experimental accounting and the dividend book own cash/lots. Pending dollar
intents are encumbrances, not another balance. This slice makes no strategy-edge,
quality-selection, full-Task5 or live-operation claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    Underflow,
    localcontext,
)
from typing import Literal
from zoneinfo import ZoneInfo

from trading_bot.config.hybrid import HybridSettings
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.hybrid.accounting import dispose
from trading_bot.hybrid.execution import cancel_order, fill_order, settle
from trading_bot.hybrid.exits import propose_exit
from trading_bot.hybrid.models import Account, ExitProgress, FillFact, PaperOrder
from trading_bot.market_data.recording import content_hash
from trading_bot.market_data.stock_economic_evidence import StockCashDividendEvent
from trading_bot.research.hybrid_policies import CalendarSession
from trading_bot.research.hybrid_strategies import PriceBar
from trading_bot.research.stock_dividend_book import (
    DividendBook,
    adopt_dividend_account,
    create_dividend_book,
    credit_due_dividends,
    receivable_value,
    record_dividend_entitlement,
)
from trading_bot.research.stock_economic_policies import (
    EconomicPolicyClose,
    EconomicPolicyFrame,
    KnownPolicyCondition,
    OwnedPolicyEpisode,
    evaluate_economic_policy_close,
    validate_policy_assets,
)
from trading_bot.research.stock_operating_costs import (
    ModeledOperatingCostPlan,
    OperatingCostPhaseBinding,
    OperatingCostUpdate,
    apply_stock_operating_costs,
    bind_stock_operating_phase,
    net_equity_after_operating_costs,
    stock_operating_phase_hash,
    validate_stock_operating_phase_bindings,
)

_ZERO, _ONE = Decimal(0), Decimal(1)
_INCREMENT = Decimal(".000001")
_NY = ZoneInfo("America/New_York")
_CONTEXT = Context(
    prec=50,
    rounding=ROUND_HALF_EVEN,
    Emin=-999999,
    Emax=999999,
    capitals=1,
    clamp=0,
    flags=[],
    traps=[InvalidOperation, DivisionByZero, Overflow, Underflow],
)
_INCOMPLETE = (
    "actual_purpose_specific_source_admission_unavailable",
    "seven_family_selection_and_quality_fundamental_event_vintages_not_implemented",
    "corporate_action_conversion_volatility_and_quarterly_rebalance_not_implemented",
    "operating_expense_and_statistical_edge_qualification_not_implemented",
    "fixture_window_has_no_actual_or_unseen_holdout_authority",
)
_PROTOCOL_CONVENTIONS = (
    "resume_owned_partial_profit_rung_before_testing_a_fresh_profit_trigger",
    "principal_resume_is_capped_by_known_close_surplus_over_original_episode_cash",
    "pre_entry_gross_equity_risk_budget_includes_both_fees_and_stop_sale_slippage",
    "allocate_among_causally_eligible_unencumbered_new_signal_names",
    "dividend_funding_support_is_explicit_and_separate_from_cns_settlement_support",
    "static_fixture_annotations_are_scenarios_not_fresh_market_attestations",
)
ExitMethod = Literal["principal", "partial", "trailing", "full_target", "fixed_holding"]
_COST_RISK_PHASE = "explicit-cost-preopen-gross-risk-v1"


def _check(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _utc(value: datetime) -> None:
    _check(
        type(value) is datetime and value.tzinfo is not None and value.utcoffset() == timedelta(0),
        "utc_timestamp_required",
    )


def _hash(value: object) -> str:
    return str(content_hash(value))


def _down(value: Decimal) -> Decimal:
    return max(_ZERO, value).quantize(_INCREMENT, rounding=ROUND_DOWN)


@dataclass(frozen=True, slots=True)
class ModeledAsset:
    """Static fixture annotations with causal availability, not freshness attestations."""

    symbol: str
    role: Literal["stock_candidate", "passive_comparison"]
    sector: str | None
    average_dollar_volume: Decimal | None
    earnings_clear: bool | None
    available_at: datetime
    bars: tuple[PriceBar, ...]
    signals: tuple[bool, ...]


@dataclass(frozen=True, slots=True)
class SettlementDay:
    day: date
    status: Literal["ordinary_supported", "closed", "limited", "unknown"]
    source_hash: str


@dataclass(frozen=True, slots=True)
class DividendFundingDay:
    """Explicit fixture support for dividend funding, independent of CNS service."""

    day: date
    status: Literal["supported", "unavailable", "unknown", "contradictory"]
    source_hash: str


@dataclass(frozen=True, slots=True)
class ModeledExecutionDirective:
    session_index: int
    symbol: str
    fill_fraction: Decimal = _ONE
    reject: bool = False


@dataclass(frozen=True, slots=True)
class StockEconomicReplayInputs:
    assets: tuple[ModeledAsset, ...]
    calendar: tuple[CalendarSession, ...]
    settlement_days: tuple[SettlementDay, ...]
    long_term_allocations: tuple[tuple[str, Decimal], ...]
    dividends: tuple[StockCashDividendEvent, ...]
    execution_directives: tuple[ModeledExecutionDirective, ...]
    calendar_source_hash: str
    dividend_funding_days: tuple[DividendFundingDay, ...] = ()
    source_profile: Literal["fictional_stock_economic_fixture_v1"] = field(
        default="fictional_stock_economic_fixture_v1", init=False
    )
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)

    @property
    def evidence_hash(self) -> str:
        return _hash(("stock-economic-fixture-input-v2", self))


@dataclass(frozen=True, slots=True)
class StockEconomicReplayProtocol:
    exit_method: ExitMethod = "principal"
    slippage_bps: Decimal = Decimal(5)
    fee_usd: Decimal = Decimal(".01")
    tax_rate: Decimal | None = None
    first_execution_session: Literal[200] = field(default=200, init=False)
    starting_capital: Decimal = field(default=Decimal(1000), init=False)
    cooldown_sessions: Literal[5] = field(default=5, init=False)
    maximum_holding_sessions: Literal[40] = field(default=40, init=False)

    def __post_init__(self) -> None:
        _check(
            self.exit_method
            in ("principal", "partial", "trailing", "full_target", "fixed_holding"),
            "unsupported_exit_method",
        )
        require_bounded_decimal(self.slippage_bps, "slippage_bps", nonnegative=True)
        require_bounded_decimal(self.fee_usd, "fee_usd", nonnegative=True)
        _check(self.slippage_bps <= 100, "modeled_slippage_out_of_bounds")
        if self.tax_rate is not None:
            require_bounded_decimal(self.tax_rate, "tax_rate", nonnegative=True)
            _check(self.tax_rate <= 1, "tax_rate_out_of_bounds")

    @property
    def evidence_hash(self) -> str:
        return _hash(
            ("stock-economic-kernel-protocol-v3", self, _PROTOCOL_CONVENTIONS, _INCOMPLETE)
        )


@dataclass(frozen=True, slots=True)
class PendingEconomicIntent:
    symbol: str
    side: Literal["buy", "sell"]
    sleeve: Literal["long_term", "tactical"]
    signal_session: int
    cash_budget: Decimal = _ZERO
    exit_order: PaperOrder | None = None
    reason: str = "new_signal"


@dataclass(frozen=True, slots=True)
class EpisodeRuntime:
    episode_id: str
    entered_session: int
    entry_price: Decimal
    peak_close: Decimal


@dataclass(frozen=True, slots=True)
class EconomicReplayRecord:
    session_index: int
    at: datetime
    symbol: str
    side: str
    outcome: Literal["filled", "cancelled", "rejected", "denied"]
    reason: str
    order_id: str | None = None
    quantity: Decimal = _ZERO
    price: Decimal = _ZERO
    fee: Decimal = _ZERO
    settlement_at: datetime | None = None
    proceeds: Decimal = _ZERO
    disposed_basis: Decimal = _ZERO
    realized_gain: Decimal = _ZERO


@dataclass(frozen=True, slots=True)
class EconomicReplaySnapshot:
    session_index: int
    at: datetime
    gross_equity: Decimal
    cash: Decimal
    reserved_cash: Decimal
    tax_reserve: Decimal
    unsettled: Decimal
    receivable: Decimal
    long_term_value: Decimal
    tactical_value: Decimal


@dataclass(frozen=True, slots=True)
class EconomicReplayCostMark:
    session_index: int
    at: datetime
    phase: Literal["open", "close"]
    gross_before_payment: Decimal
    gross_equity: Decimal
    net_equity: Decimal | None
    paid_total: Decimal
    unpaid_known: Decimal
    unpaid_unknown_ids: tuple[str, ...]
    investable_cash: Decimal
    daily_reference: Decimal
    weekly_reference: Decimal
    closed_high_watermark: Decimal
    tactical_suspended: bool
    weekly_review_required: bool
    plan_hash: str
    cost_update_hash: str
    ledger_sequence: int | None = None
    ledger_step_sha256: str | None = None
    risk_phase: str = field(default=_COST_RISK_PHASE, init=False)
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    full_task5_complete: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _utc(self.at)
        _check(
            type(self.session_index) is int
            and self.session_index >= 200
            and self.phase in ("open", "close")
            and self.risk_phase == _COST_RISK_PHASE
            and self.qualified
            is self.source_qualified
            is self.strategy_qualified
            is self.investment_eligible
            is self.trading_enabled
            is self.live_authorized
            is self.full_task5_complete
            is False,
            "operating_cost_mark_scope_invalid",
        )
        for number in (
            self.gross_before_payment,
            self.gross_equity,
            self.paid_total,
            self.unpaid_known,
            self.investable_cash,
            self.daily_reference,
            self.weekly_reference,
            self.closed_high_watermark,
        ):
            require_bounded_decimal(number, "operating_cost_mark", nonnegative=True)
        if self.net_equity is not None:
            require_bounded_decimal(self.net_equity, "operating_cost_net_equity")
        _check(
            type(self.unpaid_unknown_ids) is tuple
            and all(type(identity) is str for identity in self.unpaid_unknown_ids)
            and len(set(self.unpaid_unknown_ids)) == len(self.unpaid_unknown_ids)
            and type(self.tactical_suspended) is type(self.weekly_review_required) is bool,
            "operating_cost_mark_liabilities_invalid",
        )
        _require_sha256_hex(self.plan_hash, "operating_cost_plan")
        _require_sha256_hex(self.cost_update_hash, "operating_cost_update")
        _check(
            (self.ledger_sequence is None and self.ledger_step_sha256 is None)
            or (
                type(self.ledger_sequence) is int
                and self.ledger_sequence > 0
                and type(self.ledger_step_sha256) is str
            ),
            "operating_cost_phase_anchor_invalid",
        )
        if self.ledger_step_sha256 is not None:
            _require_sha256_hex(self.ledger_step_sha256, "operating_cost_phase_anchor")
        with localcontext(_CONTEXT):
            _check(
                self.net_equity
                == (None if self.unpaid_unknown_ids else self.gross_equity - self.unpaid_known),
                "operating_cost_mark_net_equity_invalid",
            )

    @property
    def payload_hash(self) -> str:
        """Anchor fields are excluded to avoid a self-referential phase commitment."""
        self.__post_init__()
        return _hash(
            (
                "stock-economic-cost-mark-payload-v2",
                replace(self, ledger_sequence=None, ledger_step_sha256=None),
            )
        )


@dataclass(frozen=True, slots=True)
class EconomicReplayCostReport:
    plan_hash: str
    plan_label: str
    marks: tuple[EconomicReplayCostMark, ...]
    book: DividendBook = field(repr=False)
    plan: ModeledOperatingCostPlan = field(repr=False)
    risk_phase: str = field(default=_COST_RISK_PHASE, init=False)
    observed_spending: Literal[False] = field(default=False, init=False)
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    full_task5_complete: Literal[False] = field(default=False, init=False)

    @property
    def evidence_hash(self) -> str:
        _require_sha256_hex(self.plan_hash, "operating_cost_plan")
        _check(
            type(self.marks) is tuple
            and self.risk_phase == _COST_RISK_PHASE
            and self.observed_spending
            is self.qualified
            is self.source_qualified
            is self.strategy_qualified
            is self.investment_eligible
            is self.trading_enabled
            is self.live_authorized
            is self.full_task5_complete
            is False,
            "operating_cost_report_scope_invalid",
        )
        for mark in self.marks:
            _check(type(mark) is EconomicReplayCostMark, "operating_cost_mark_required")
            mark.__post_init__()
            _check(mark.plan_hash == self.plan_hash, "operating_cost_report_plan_mismatch")
        _check(
            type(self.plan) is ModeledOperatingCostPlan
            and self.plan.evidence_hash == self.plan_hash
            and self.plan.label == self.plan_label,
            "operating_cost_report_plan_mismatch",
        )
        _validate_owned_cost_marks(self.book, self.plan, self.marks)
        return _hash(
            (
                "stock-economic-cost-report-v2",
                self.plan_hash,
                self.plan_label,
                self.marks,
                self.book.evidence_hash,
                self.risk_phase,
                self.observed_spending,
                self.qualified,
                self.source_qualified,
                self.strategy_qualified,
                self.investment_eligible,
                self.trading_enabled,
                self.live_authorized,
                self.full_task5_complete,
            )
        )


@dataclass(frozen=True, slots=True)
class StockEconomicReplayState:
    inputs: StockEconomicReplayInputs
    protocol: StockEconomicReplayProtocol
    book: DividendBook
    next_session: int
    pending: tuple[PendingEconomicIntent, ...]
    episodes: tuple[EpisodeRuntime, ...]
    previous_signals: tuple[tuple[str, bool], ...]
    last_exits: tuple[tuple[str, int], ...]
    snapshots: tuple[EconomicReplaySnapshot, ...]
    records: tuple[EconomicReplayRecord, ...]
    policy_family: str | None = None
    policy_closes: tuple[EconomicPolicyClose, ...] = ()
    policy_episodes: tuple[OwnedPolicyEpisode, ...] = ()
    operating_cost_plan: ModeledOperatingCostPlan | None = None
    operating_cost_plan_hash: str | None = None
    cost_marks: tuple[EconomicReplayCostMark, ...] = ()
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    quality_selection_implemented: Literal[False] = field(default=False, init=False)

    @property
    def evidence_hash(self) -> str:
        intents = tuple(
            (
                p.symbol,
                p.side,
                p.sleeve,
                p.signal_session,
                p.cash_budget,
                None if p.exit_order is None else p.exit_order.model_dump(),
                p.reason,
            )
            for p in self.pending
        )
        legacy = (
            "stock-economic-state-v3",
            self.inputs.evidence_hash,
            self.protocol.evidence_hash,
            self.book.evidence_hash,
            self.next_session,
            intents,
            self.episodes,
            self.previous_signals,
            self.last_exits,
            self.snapshots,
            self.records,
        )
        base = (
            _hash(legacy)
            if self.policy_family is None
            else _hash(
                (
                    "stock-economic-policy-state-v1",
                    legacy,
                    self.policy_family,
                    self.policy_closes,
                    self.policy_episodes,
                )
            )
        )
        _validate_cost_history(self)
        if self.operating_cost_plan is None:
            return base
        return _hash(
            (
                "stock-economic-cost-state-v2",
                base,
                _COST_RISK_PHASE,
                self.operating_cost_plan_hash,
                self.cost_marks,
            )
        )


@dataclass(frozen=True, slots=True)
class StockEconomicReplayResult:
    book: DividendBook
    snapshots: tuple[EconomicReplaySnapshot, ...]
    records: tuple[EconomicReplayRecord, ...]
    pending_final_intents: tuple[PendingEconomicIntent, ...]
    evidence_hash: str
    incomplete_features: tuple[str, ...] = field(default=_INCOMPLETE, init=False)
    full_task5_complete: Literal[False] = field(default=False, init=False)
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class StockCostedEconomicReplayResult(StockEconomicReplayResult):
    operating_costs: EconomicReplayCostReport = field(kw_only=True)
    incomplete_features: tuple[str, ...] = field(
        default=(
            *(
                item
                for item in _INCOMPLETE
                if item != "operating_expense_and_statistical_edge_qualification_not_implemented"
            ),
            "modeled_budget_not_observed_spending_or_statistical_edge_qualification",
        ),
        init=False,
    )


def make_fictional_replay_inputs(
    assets: tuple[ModeledAsset, ...],
    calendar: tuple[CalendarSession, ...],
    settlement_days: tuple[SettlementDay, ...],
    *,
    long_term_allocations: tuple[tuple[str, Decimal], ...] = (),
    dividends: tuple[StockCashDividendEvent, ...] = (),
    execution_directives: tuple[ModeledExecutionDirective, ...] = (),
    dividend_funding_days: tuple[DividendFundingDay, ...] = (),
    calendar_source_hash: str,
) -> StockEconomicReplayInputs:
    """Bind explicitly fictional observations; this factory never admits real evidence."""
    value = StockEconomicReplayInputs(
        assets,
        calendar,
        settlement_days,
        long_term_allocations,
        dividends,
        execution_directives,
        calendar_source_hash,
        dividend_funding_days,
    )
    _validate_inputs(value)
    return value


def _validate_inputs(inputs: StockEconomicReplayInputs) -> None:
    _check(
        type(inputs) is StockEconomicReplayInputs
        and inputs.source_profile == "fictional_stock_economic_fixture_v1"
        and inputs.qualified
        is inputs.source_qualified
        is inputs.investment_eligible
        is inputs.trading_enabled
        is inputs.live_authorized
        is False,
        "fictional_scope_required",
    )
    _check(
        all(
            type(v) is tuple
            for v in (
                inputs.assets,
                inputs.calendar,
                inputs.settlement_days,
                inputs.long_term_allocations,
                inputs.dividends,
                inputs.execution_directives,
                inputs.dividend_funding_days,
            )
        ),
        "immutable_replay_inputs_required",
    )
    _require_sha256_hex(inputs.calendar_source_hash, "calendar_source_hash")
    _check(
        1 <= len(inputs.assets) <= 32 and 202 <= len(inputs.calendar) <= 10000,
        "bounded_replay_panel_required",
    )
    symbols = tuple(asset.symbol for asset in inputs.assets)
    _check(len(set(symbols)) == len(symbols), "duplicate_asset")
    count = len(inputs.assets[0].bars)
    _check(201 <= count <= len(inputs.calendar), "complete_warmup_and_study_rows_required")
    previous = None
    for i, session in enumerate(inputs.calendar):
        _check(
            type(session) is CalendarSession and session.index == i, "consecutive_calendar_required"
        )
        _utc(session.opens_at)
        _utc(session.closes_at)
        _check(
            session.opens_at < session.closes_at
            and (previous is None or previous.closes_at < session.opens_at),
            "calendar_overlap",
        )
        previous = session
    for asset in inputs.assets:
        _check(
            type(asset) is ModeledAsset
            and type(asset.symbol) is str
            and bool(asset.symbol)
            and asset.role in ("stock_candidate", "passive_comparison"),
            "invalid_modeled_asset",
        )
        _utc(asset.available_at)
        _check(
            type(asset.bars) is tuple
            and type(asset.signals) is tuple
            and len(asset.bars) == len(asset.signals) == count,
            "matched_immutable_observations_required",
        )
        _check(
            asset.earnings_clear is None or type(asset.earnings_clear) is bool,
            "exact_modeled_earnings_state_required",
        )
        if asset.average_dollar_volume is not None:
            require_bounded_decimal(asset.average_dollar_volume, "modeled_adv", nonnegative=True)
        for i, bar in enumerate(asset.bars):
            _check(
                type(bar) is PriceBar
                and bar.completed_at == inputs.calendar[i].closes_at
                and type(asset.signals[i]) is bool,
                "causal_aligned_close_rows_required",
            )
            for price in (bar.open, bar.close):
                require_bounded_decimal(price, "price", positive=True)
                _check(Decimal("1e-30") <= price <= Decimal("1e30"), "price_bounds")
    seen_dates: set[date] = set()
    for day in inputs.settlement_days:
        _check(
            type(day) is SettlementDay
            and type(day.day) is date
            and day.status in ("ordinary_supported", "closed", "limited", "unknown")
            and day.day not in seen_dates,
            "invalid_settlement_day",
        )
        _require_sha256_hex(day.source_hash, "settlement_source_hash")
        seen_dates.add(day.day)
    _check(
        tuple(sorted(seen_dates)) == tuple(day.day for day in inputs.settlement_days),
        "ordered_settlement_days_required",
    )
    funding_dates: set[date] = set()
    _check(len(inputs.dividend_funding_days) <= 10000, "bounded_dividend_funding_days_required")
    for funding in inputs.dividend_funding_days:
        _check(
            type(funding) is DividendFundingDay
            and type(funding.day) is date
            and funding.status in ("supported", "unavailable", "unknown", "contradictory")
            and funding.day not in funding_dates,
            "invalid_dividend_funding_day",
        )
        _require_sha256_hex(funding.source_hash, "dividend_funding_source_hash")
        funding_dates.add(funding.day)
    _check(
        tuple(sorted(funding_dates)) == tuple(day.day for day in inputs.dividend_funding_days),
        "ordered_dividend_funding_days_required",
    )
    seen_targets: set[str] = set()
    for symbol, weight in inputs.long_term_allocations:
        require_bounded_decimal(weight, "long_term_weight", positive=True)
        _check(symbol in symbols and symbol not in seen_targets, "invalid_long_term_slot")
        seen_targets.add(symbol)
    with localcontext(_CONTEXT):
        _check(
            sum((w for _, w in inputs.long_term_allocations), _ZERO) <= Decimal(".75"),
            "long_term_target_cap",
        )
    ids: set[str] = set()
    for event in inputs.dividends:
        _check(
            type(event) is StockCashDividendEvent
            and event.symbol in symbols
            and event.id not in ids,
            "invalid_dividend_event_identity",
        )
        event.__post_init__()
        _check(
            inputs.calendar[200].opens_at.astimezone(_NY).date()
            <= event.ex_date
            <= inputs.calendar[count - 1].opens_at.astimezone(_NY).date(),
            "dividend_outside_activated_fixture_window",
        )
        ids.add(event.id)
    seen_directives: set[tuple[int, str]] = set()
    for instruction in inputs.execution_directives:
        _check(
            type(instruction) is ModeledExecutionDirective
            and type(instruction.session_index) is int
            and 200 <= instruction.session_index < count
            and instruction.symbol in symbols
            and type(instruction.reject) is bool,
            "invalid_execution_directive",
        )
        require_bounded_decimal(instruction.fill_fraction, "fill_fraction", nonnegative=True)
        key = (instruction.session_index, instruction.symbol)
        _check(
            instruction.fill_fraction <= 1 and key not in seen_directives,
            "conflicting_execution_directive",
        )
        seen_directives.add(key)


def _asset(state: StockEconomicReplayState, symbol: str) -> ModeledAsset:
    return next(item for item in state.inputs.assets if item.symbol == symbol)


def _prices(state: StockEconomicReplayState, index: int, *, opening: bool) -> dict[str, Decimal]:
    return {
        asset.symbol: asset.bars[index].open if opening else asset.bars[index].close
        for asset in state.inputs.assets
    }


def _values(
    state: StockEconomicReplayState, prices: dict[str, Decimal], at: datetime
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    account = state.book.account
    long = sum(
        (lot.quantity * prices[lot.symbol] for lot in account.lots if lot.sleeve == "long_term"),
        _ZERO,
    )
    tactical = sum(
        (lot.quantity * prices[lot.symbol] for lot in account.lots if lot.sleeve == "tactical"),
        _ZERO,
    )
    unsettled = sum((claim.amount for claim in account.settlements), _ZERO)
    rights = receivable_value(state.book, at=at)
    return account.cash + unsettled + rights + long + tactical, long, tactical, unsettled, rights


def _snapshot(state: StockEconomicReplayState, index: int) -> EconomicReplaySnapshot:
    at = state.inputs.calendar[index].closes_at
    equity, long, tactical, unsettled, rights = _values(
        state, _prices(state, index, opening=False), at
    )
    return EconomicReplaySnapshot(
        index,
        at,
        equity,
        state.book.account.cash,
        state.book.account.reserved_cash,
        state.book.account.tax_reserve,
        unsettled,
        rights,
        long,
        tactical,
    )


def _validate_cost_configuration(state: StockEconomicReplayState) -> None:
    plan = state.operating_cost_plan
    if plan is None:
        _check(
            state.operating_cost_plan_hash is None
            and state.cost_marks == ()
            and not any(
                step.action in {"operating_expense", "operating_cost_phase"}
                for step in state.book.trace
            ),
            "operating_cost_mode_history_mismatch",
        )
        return
    _check(type(plan) is ModeledOperatingCostPlan, "operating_cost_plan_required")
    plan.__post_init__()
    _check(plan.evidence_hash == state.operating_cost_plan_hash, "operating_cost_plan_changed")
    _check(
        all(charge.due_at >= state.inputs.calendar[200].opens_at for charge in plan.charges),
        "operating_cost_before_activation",
    )


def _validate_cost_history(state: StockEconomicReplayState) -> None:
    _validate_cost_configuration(state)
    if state.operating_cost_plan is None:
        return
    expected = tuple(
        (index, phase) for index in range(200, state.next_session) for phase in ("open", "close")
    )
    _check(
        type(state.cost_marks) is tuple and len(state.cost_marks) == len(expected),
        "operating_cost_history_incomplete",
    )
    for mark, (index, phase) in zip(state.cost_marks, expected, strict=True):
        _check(type(mark) is EconomicReplayCostMark, "operating_cost_mark_required")
        mark.__post_init__()
        at = (
            state.inputs.calendar[index].opens_at
            if phase == "open"
            else state.inputs.calendar[index].closes_at
        )
        _check(
            mark.session_index == index
            and mark.phase == phase
            and mark.at == at
            and mark.plan_hash == state.operating_cost_plan_hash,
            "operating_cost_mark_history_mismatch",
        )
    _validate_owned_cost_marks(state.book, state.operating_cost_plan, state.cost_marks)


def _validate_owned_cost_marks(
    book: DividendBook,
    plan: ModeledOperatingCostPlan,
    marks: tuple[EconomicReplayCostMark, ...],
) -> None:
    bindings = []
    for mark in marks:
        mark.__post_init__()
        _check(
            mark.ledger_sequence is not None and mark.ledger_step_sha256 is not None,
            "operating_cost_owned_phase_anchor_required",
        )
        if mark.ledger_sequence is None or mark.ledger_step_sha256 is None:
            raise ValueError("operating_cost_owned_phase_anchor_required")
        bindings.append(
            OperatingCostPhaseBinding(
                mark.ledger_sequence,
                mark.ledger_step_sha256,
                f"{mark.session_index}:{mark.phase}",
                mark.at,
                mark.paid_total,
                mark.unpaid_known,
                mark.unpaid_unknown_ids,
                mark.investable_cash,
                mark.cost_update_hash,
                mark.payload_hash,
            )
        )
    validate_stock_operating_phase_bindings(book, plan, tuple(bindings))


def _bind_cost_mark(
    state: StockEconomicReplayState, mark: EconomicReplayCostMark, costs: OperatingCostUpdate
) -> tuple[StockEconomicReplayState, EconomicReplayCostMark]:
    _check(costs.book is state.book, "operating_cost_current_book_required")
    book, sequence, digest = bind_stock_operating_phase(
        costs,
        phase_id=f"{mark.session_index}:{mark.phase}",
        update_hash=mark.cost_update_hash,
        mark_payload_hash=mark.payload_hash,
    )
    return replace(state, book=book), replace(
        mark, ledger_sequence=sequence, ledger_step_sha256=digest
    )


def _cost_phase(
    state: StockEconomicReplayState, index: int, phase: Literal["open", "close"]
) -> StockEconomicReplayState:
    plan = state.operating_cost_plan
    if plan is None:
        return state
    _validate_cost_configuration(state)
    at = (
        state.inputs.calendar[index].opens_at
        if phase == "open"
        else state.inputs.calendar[index].closes_at
    )
    prices = _prices(state, index, opening=phase == "open")
    before, _, _, _, _ = _values(state, prices, at)
    costs = apply_stock_operating_costs(state.book, plan, at=at)
    state = replace(state, book=costs.book)
    gross, _, _, _, _ = _values(state, prices, at)
    _check(gross > 0, "operating_cost_gross_equity_depleted")
    daily = state.snapshots[-1].gross_equity
    prior_day = state.snapshots[-1].at.astimezone(_NY).date()
    day = at.astimezone(_NY).date()
    account = state.book.account
    weekly = (
        account.weekly_reference if day.isocalendar()[:2] == prior_day.isocalendar()[:2] else daily
    )
    if phase == "open":
        # Every explicit budget, including zero, uses this same versioned phase.
        # Only sticky flags change here: the high watermark remains close-based.
        updated = Account.model_validate(
            account.model_dump()
            | {
                "tactical_suspended": account.tactical_suspended
                or gross <= daily * Decimal(".99")
                or gross <= account.high_watermark * Decimal(".90"),
                "weekly_review_required": account.weekly_review_required
                or gross <= weekly * Decimal(".97"),
            }
        )
        if updated != account:
            state = replace(state, book=adopt_dividend_account(state.book, updated, at=at))
            costs = apply_stock_operating_costs(state.book, plan, at=at)
        account = state.book.account
    mark = EconomicReplayCostMark(
        index,
        at,
        phase,
        before,
        gross,
        net_equity_after_operating_costs(gross, costs),
        costs.paid_total,
        costs.unpaid_known,
        costs.unpaid_unknown_ids,
        costs.investable_cash,
        daily,
        weekly,
        account.high_watermark,
        account.tactical_suspended,
        account.weekly_review_required,
        plan.evidence_hash,
        stock_operating_phase_hash(costs),
    )
    if phase == "open":
        state, mark = _bind_cost_mark(state, mark, costs)
    return replace(state, cost_marks=(*state.cost_marks, mark))


def _cost_buy_block(state: StockEconomicReplayState, at: datetime) -> str | None:
    if state.operating_cost_plan is None or at < state.inputs.calendar[200].opens_at:
        return None
    _check(bool(state.cost_marks), "operating_cost_current_phase_required")
    mark = state.cost_marks[-1]
    _check(mark.at == at, "operating_cost_current_phase_required")
    if mark.unpaid_unknown_ids:
        return "operating_cost_unknown_liability"
    if mark.net_equity is None or mark.net_equity <= 0:
        return "operating_cost_nonpositive_net_equity"
    if mark.unpaid_known >= state.book.account.buying_power and mark.unpaid_known > 0:
        return "operating_cost_unpaid_liability"
    return None


def _spendable(state: StockEconomicReplayState, at: datetime) -> Decimal:
    power = state.book.account.buying_power
    if state.operating_cost_plan is None or at < state.inputs.calendar[200].opens_at:
        return power
    if _cost_buy_block(state, at) is not None:
        return _ZERO
    return max(_ZERO, power - state.cost_marks[-1].unpaid_known)


def stock_economic_cost_report(state: StockEconomicReplayState) -> EconomicReplayCostReport:
    """Return the cost-only sidecar; the no-plan result/snapshot schema stays intact."""
    _validate_cost_history(state)
    plan = state.operating_cost_plan
    _check(plan is not None, "operating_cost_mode_required")
    if plan is None:
        raise ValueError("operating_cost_mode_required")
    return EconomicReplayCostReport(
        plan.evidence_hash, plan.label, state.cost_marks, state.book, plan
    )


def _deny(
    state: StockEconomicReplayState, index: int, intent: PendingEconomicIntent, reason: str
) -> StockEconomicReplayState:
    record = EconomicReplayRecord(
        index, state.inputs.calendar[index].opens_at, intent.symbol, intent.side, "denied", reason
    )
    return replace(state, records=(*state.records, record))


def _eligible(asset: ModeledAsset, at: datetime, price: Decimal) -> bool:
    return (
        asset.available_at <= at
        and asset.average_dollar_volume is not None
        and asset.average_dollar_volume >= 20000000
        and asset.earnings_clear is True
        and price >= 10
        and (asset.role == "passive_comparison" or bool(asset.sector))
    )


def _resume_profit_rung(
    account: Account,
    episode_id: str,
    quantity: Decimal,
    current_close: Decimal,
) -> PaperOrder | None:
    thresholds = (
        episode_id + ":principal",
        episode_id + ":partial_first",
        episode_id + ":partial_second",
    )
    progress = next(
        (
            item
            for item in account.exit_progress
            if item.threshold in thresholds
            and item.threshold not in account.completed_thresholds
            and 0 < item.filled < item.target
        ),
        None,
    )
    if progress is None:
        return None
    remaining = min(quantity, progress.target - progress.filled)
    if progress.threshold == episode_id + ":principal":
        allocation = next(
            episode.original_cash for episode in account.episodes if episode.id == episode_id
        )
        # Preserve the activated rung cap without knowingly selling the value
        # designated to remain. A subsequent next-open gap is still unguaranteed.
        remaining = min(remaining, max(_ZERO, quantity - allocation / current_close))
    remaining = _down(remaining)
    if remaining <= 0:
        return None
    attempts = sum(order.threshold == progress.threshold for order in account.orders)
    return PaperOrder(
        id=f"exit:{progress.threshold}:{attempts}",
        symbol=progress.symbol,
        side="sell",
        sleeve="tactical",
        quantity=remaining,
        threshold=progress.threshold,
        episode_id=episode_id,
        reason="resume_owned_profit_rung",
    )


def _plan(
    state: StockEconomicReplayState, index: int, policy_frame: EconomicPolicyFrame | None = None
) -> StockEconomicReplayState:
    account, prices = state.book.account, _prices(state, index, opening=False)
    at = state.inputs.calendar[index].closes_at
    conditions: dict[str, bool | None] = {}
    if state.policy_family is None:
        _check(policy_frame is None, "policy_mode_cannot_change")
    else:
        _check(type(policy_frame) is EconomicPolicyFrame, "policy_frame_required")
        if policy_frame is None:
            raise ValueError("policy_frame_required")
        _check(policy_frame.family == state.policy_family, "owned_policy_family_cannot_change")
        policy_frame.__post_init__()
        for session in policy_frame.request.sessions:
            _check(
                type(session) is CalendarSession
                and 0 <= session.index < len(state.inputs.calendar)
                and session == state.inputs.calendar[session.index],
                "policy_calendar_scope_mismatch",
            )
        policy_assets = {asset.symbol: asset for asset in state.inputs.assets}
        for observation in policy_frame.request.observations:
            asset = policy_assets.get(observation.symbol)
            _check(
                asset is not None
                and 0 <= observation.session_index < len(asset.bars)
                and observation.bar == asset.bars[observation.session_index],
                "policy_observation_scope_mismatch",
            )
        held_positions = tuple(
            sorted(
                {
                    (lot.symbol, state.policy_family)
                    for lot in account.lots
                    if lot.sleeve == "tactical" and lot.quantity > 0
                }
            )
        )
        following = (
            state.inputs.calendar[index + 1].opens_at
            if index + 1 < len(state.inputs.assets[0].bars)
            else None
        )
        policy_close = evaluate_economic_policy_close(
            policy_frame,
            session_index=index,
            information_at=at,
            next_open=following,
            held_positions=held_positions,
        )
        state = replace(state, policy_closes=(*state.policy_closes, policy_close))
        conditions = {
            row.symbol: row.active if isinstance(row, KnownPolicyCondition) else None
            for row in policy_close.conditions
        }
    previous_defined = dict(state.previous_signals)
    if state.policy_family is None:
        next_signals = tuple((a.symbol, a.signals[index]) for a in state.inputs.assets)
    else:
        previous_defined.update(
            {symbol: active for symbol, active in conditions.items() if active is not None}
        )
        next_signals = tuple(sorted(previous_defined.items()))
    equity, long, tactical, _, _ = _values(state, prices, at)
    if account.kill_switch:
        return replace(
            state,
            pending=(),
            previous_signals=next_signals,
        )
    pending: list[PendingEconomicIntent] = []
    settings = HybridSettings(
        tax_rate=state.protocol.tax_rate,
        simulation_slippage_bps=state.protocol.slippage_bps,
        simulation_fee_usd=state.protocol.fee_usd,
    )
    runtime = {item.episode_id: item for item in state.episodes}
    for episode in account.episodes:
        if episode.sleeve != "tactical":
            continue
        lots = tuple(lot for lot in account.lots if lot.episode_id == episode.id)
        if not lots:
            continue
        quantity = sum((lot.quantity for lot in lots), _ZERO)
        record = runtime[episode.id]
        close = prices[episode.symbol]
        entry = record.entry_price
        age = index - record.entered_session + 1
        active = (
            _asset(state, episode.symbol).signals[index]
            if state.policy_family is None
            else conditions[episode.symbol]
        )
        maximum_age = 40
        if state.policy_family is not None:
            owned = next(
                (rule for rule in state.policy_episodes if rule.episode_id == episode.id), None
            )
            _check(
                owned is not None and owned.family == state.policy_family,
                "owned_entry_policy_rule_required",
            )
            if owned is None:
                raise ValueError("owned_entry_policy_rule_required")
            owned.__post_init__()
            maximum_age = owned.maximum_holding_sessions
        full_reason = ""
        if close <= entry * Decimal(".95"):
            full_reason = "initial_stop"
        elif active is False:
            full_reason = "family_signal_exit"
        elif age >= maximum_age or (state.protocol.exit_method == "fixed_holding" and age >= 20):
            full_reason = "holding_time_exit"
        elif (
            state.protocol.exit_method == "full_target"
            and quantity * close >= episode.original_cash * Decimal("1.20")
        ):
            full_reason = "full_target_exit"
        order = None
        if full_reason:
            order = PaperOrder(
                id=f"model-exit:{episode.id}:{index}",
                symbol=episode.symbol,
                side="sell",
                sleeve="tactical",
                quantity=quantity,
                episode_id=episode.id,
                reason=full_reason,
            )
        elif quantity * close > equity * Decimal(".04"):
            amount = _down(quantity - equity * Decimal(".04") / close)
            if amount:
                order = PaperOrder(
                    id=f"model-trim:{episode.id}:{index}",
                    symbol=episode.symbol,
                    side="sell",
                    sleeve="tactical",
                    quantity=amount,
                    episode_id=episode.id,
                    reason="position_cap_reduction",
                )
        else:
            completed = any(
                threshold.startswith(episode.id + ":") for threshold in account.completed_thresholds
            )
            if state.protocol.exit_method == "trailing" or (
                state.protocol.exit_method in ("principal", "partial") and completed
            ):
                order = propose_exit(
                    account, episode.id, "trend", close, record.peak_close, settings
                )
            if order is None:
                order = _resume_profit_rung(account, episode.id, quantity, close)
            if order is None and state.protocol.exit_method == "principal":
                order = propose_exit(
                    account, episode.id, "principal", close, record.peak_close, settings
                )
            if order is None and state.protocol.exit_method == "partial":
                method: Literal["partial_first", "partial_second"] = (
                    "partial_second"
                    if episode.id + ":partial_first" in account.completed_thresholds
                    else "partial_first"
                )
                order = propose_exit(
                    account, episode.id, method, close, record.peak_close, settings
                )
        if order is not None:
            pending.append(
                PendingEconomicIntent(
                    episode.symbol, "sell", "tactical", index, exit_order=order, reason=order.reason
                )
            )
    claimed: set[str] = {intent.symbol for intent in pending}
    available = max(_ZERO, _spendable(state, at) - equity * Decimal(".10"))
    long_budget = max(_ZERO, equity * Decimal(".75") - long)
    for symbol, weight in state.inputs.long_term_allocations:
        if not _eligible(_asset(state, symbol), at, prices[symbol]):
            state = replace(
                state,
                records=(
                    *state.records,
                    EconomicReplayRecord(
                        index, at, symbol, "buy", "denied", "modeled_risk_inputs_unavailable"
                    ),
                ),
            )
            continue
        held = sum(
            (lot.quantity * prices[symbol] for lot in account.lots if lot.symbol == symbol), _ZERO
        )
        budget = min(available, long_budget, max(_ZERO, equity * weight - held))
        if budget >= 1 and symbol not in claimed:
            pending.append(PendingEconomicIntent(symbol, "buy", "long_term", index, budget))
            available -= budget
            long_budget -= budget
            claimed.add(symbol)
    previous = dict(state.previous_signals)
    exits = dict(state.last_exits)
    signaled = tuple(
        asset
        for asset in state.inputs.assets
        if asset.role == "stock_candidate"
        and (
            asset.signals[index]
            if state.policy_family is None
            else conditions.get(asset.symbol) is True
        )
        and not previous.get(asset.symbol, False)
    )
    candidates = []
    for asset in signaled:
        reason = ""
        if not _eligible(asset, at, prices[asset.symbol]):
            reason = "modeled_risk_inputs_unavailable"
        elif any(lot.symbol == asset.symbol for lot in account.lots) or asset.symbol in claimed:
            reason = "overlapping_symbol"
        elif any(
            o.symbol == asset.symbol and o.status in ("open", "partial") for o in account.orders
        ):
            reason = "pending_symbol"
        elif index - exits.get(asset.symbol, -10000) < 5:
            reason = "cooldown_not_elapsed"
        if reason:
            state = replace(
                state,
                records=(
                    *state.records,
                    EconomicReplayRecord(index, at, asset.symbol, "buy", "denied", reason),
                ),
            )
        else:
            candidates.append(asset)
    if not account.tactical_suspended and not account.weekly_review_required and candidates:
        budget = min(available, max(_ZERO, equity * Decimal(".15") - tactical))
        each = min(budget / len(candidates), equity * Decimal(".04"))
        for asset in sorted(candidates, key=lambda item: item.symbol):
            if each >= 1:
                pending.append(PendingEconomicIntent(asset.symbol, "buy", "tactical", index, each))
                claimed.add(asset.symbol)
    return replace(
        state,
        pending=tuple(pending),
        previous_signals=next_signals,
    )


def begin_stock_economic_replay(
    inputs: StockEconomicReplayInputs,
    protocol: StockEconomicReplayProtocol,
    *,
    policy_frame: EconomicPolicyFrame | None = None,
    operating_cost_plan: ModeledOperatingCostPlan | None = None,
) -> StockEconomicReplayState:
    with localcontext(_CONTEXT):
        _validate_inputs(inputs)
        _check(type(protocol) is StockEconomicReplayProtocol, "typed_replay_protocol_required")
        protocol.__post_init__()
        initial = Account(starting_capital=Decimal(1000), cash=Decimal(1000), paused=True)
        book = create_dividend_book(
            initial,
            account_at=inputs.calendar[199].closes_at,
            sessions=inputs.calendar,
            calendar_source_hash=inputs.calendar_source_hash,
            tax_rate=protocol.tax_rate,
        )
        state = StockEconomicReplayState(inputs, protocol, book, 200, (), (), (), (), (), ())
        if operating_cost_plan is not None:
            _check(
                type(operating_cost_plan) is ModeledOperatingCostPlan,
                "operating_cost_plan_required",
            )
            state = replace(
                state,
                operating_cost_plan=operating_cost_plan,
                operating_cost_plan_hash=operating_cost_plan.evidence_hash,
            )
        _validate_cost_configuration(state)
        if policy_frame is not None:
            _check(type(policy_frame) is EconomicPolicyFrame, "typed_policy_frame_required")
            validate_policy_assets(inputs)
            state = replace(state, policy_family=policy_frame.family)
        state = replace(state, snapshots=(_snapshot(state, 199),))
        return _plan(state, 199, policy_frame)


def _settlement_at(state: StockEconomicReplayState, index: int) -> datetime | None:
    trade_day = state.inputs.calendar[index].opens_at.astimezone(_NY).date()
    by_day = {row.day: row for row in state.inputs.settlement_days}
    day = trade_day + timedelta(days=1)
    last = state.inputs.calendar[-1].opens_at.astimezone(_NY).date()
    while day <= last:
        row = by_day.get(day)
        if row is None or row.status in ("limited", "unknown"):
            return None
        if row.status == "ordinary_supported":
            return next(
                (
                    session.opens_at
                    for session in state.inputs.calendar
                    if session.opens_at.astimezone(_NY).date() > day
                ),
                None,
            )
        day += timedelta(days=1)
    return None


def _reserve(
    state: StockEconomicReplayState, order: PaperOrder, at: datetime
) -> StockEconomicReplayState:
    account = state.book.account
    progress = account.exit_progress
    if order.threshold and not any(p.threshold == order.threshold for p in progress):
        progress = (
            *progress,
            ExitProgress(
                threshold=order.threshold,
                symbol=order.symbol,
                sleeve=order.sleeve,
                target=order.quantity,
            ),
        )
    updated = Account.model_validate(
        account.model_dump() | {"orders": (*account.orders, order), "exit_progress": progress}
    )
    return replace(state, book=adopt_dividend_account(state.book, updated, at=at))


def _execute(
    state: StockEconomicReplayState, intent: PendingEconomicIntent, index: int
) -> StockEconomicReplayState:
    at = state.inputs.calendar[index].opens_at
    account = state.book.account
    if account.kill_switch:
        return _deny(state, index, intent, "kill_switch")
    if any(
        order.symbol == intent.symbol and order.status in ("open", "partial")
        for order in account.orders
    ):
        return _deny(state, index, intent, "pending_symbol")
    prices, asset = _prices(state, index, opening=True), _asset(state, intent.symbol)
    rate = state.protocol.slippage_bps / 10000
    price = prices[intent.symbol] * (1 + rate if intent.side == "buy" else 1 - rate)
    settlement_at = None
    if intent.side == "buy":
        cost_block = _cost_buy_block(state, at)
        if cost_block is not None:
            return _deny(state, index, intent, cost_block)
        if not _eligible(
            asset, state.inputs.calendar[intent.signal_session].closes_at, prices[intent.symbol]
        ):
            return _deny(state, index, intent, "modeled_risk_inputs_unavailable")
        if intent.sleeve == "tactical" and any(lot.symbol == intent.symbol for lot in account.lots):
            return _deny(state, index, intent, "overlapping_symbol")
        if intent.sleeve == "tactical" and (
            account.tactical_suspended or account.weekly_review_required
        ):
            return _deny(state, index, intent, "sticky_tactical_suspension")
        equity, long, tactical, _, _ = _values(state, prices, at)
        held = sum(
            (
                lot.quantity * prices[lot.symbol]
                for lot in account.lots
                if lot.symbol == intent.symbol
            ),
            _ZERO,
        )
        cap = Decimal(".75") if asset.role == "passive_comparison" else Decimal(".10")
        if intent.sleeve == "tactical":
            cap = min(cap, Decimal(".04"))
        sleeve_room = equity * (
            Decimal(".75") if intent.sleeve == "long_term" else Decimal(".15")
        ) - (long if intent.sleeve == "long_term" else tactical)
        sector = sum(
            (
                lot.quantity * prices[lot.symbol]
                for lot in account.lots
                if _asset(state, lot.symbol).role != "passive_comparison"
                and _asset(state, lot.symbol).sector == asset.sector
            ),
            _ZERO,
        )
        sector_room = (
            equity if asset.role == "passive_comparison" else equity * Decimal(".25") - sector
        )
        budget = min(
            intent.cash_budget,
            _spendable(state, at) - equity * Decimal(".10"),
            equity * cap - held,
            sleeve_room,
            sector_room,
        )
        quantity = _down((budget - state.protocol.fee_usd) / price)
        if intent.sleeve == "tactical":
            risk_budget = equity * Decimal(".005")
            modeled_stop_sale_price = price * Decimal(".95") * (1 - rate)
            quantity = min(
                quantity,
                _down(
                    (risk_budget - 2 * state.protocol.fee_usd) / (price - modeled_stop_sale_price)
                ),
            )
        if quantity <= 0 or quantity * price < 1:
            return _deny(state, index, intent, "cash_risk_or_minimum_limit")
        order = PaperOrder(
            id=f"model-entry:{intent.symbol}:{index}:{intent.sleeve}",
            symbol=intent.symbol,
            side="buy",
            sleeve=intent.sleeve,
            quantity=quantity,
            risk_stop=price * Decimal(".95") if intent.sleeve == "tactical" else None,
            reserved_cash=quantity * price + state.protocol.fee_usd,
        )
    else:
        settlement_at = _settlement_at(state, index)
        if settlement_at is None:
            return _deny(state, index, intent, "settlement_support_unavailable")
        if intent.exit_order is None:
            raise ValueError("owned_exit_order_required")
        order = intent.exit_order
        if order.quantity * price < 1 or order.quantity * price <= state.protocol.fee_usd:
            return _deny(state, index, intent, "below_modeled_sale_minimum")
        selected = tuple(
            lot
            for lot in account.lots
            if lot.symbol == order.symbol
            and lot.sleeve == order.sleeve
            and lot.episode_id == order.episode_id
        )
        if sum((lot.quantity for lot in selected), _ZERO) < order.quantity:
            return _deny(state, index, intent, "insufficient_owned_shares")
    state = _reserve(state, order, at)
    directive = next(
        (
            v
            for v in state.inputs.execution_directives
            if v.session_index == index and v.symbol == intent.symbol
        ),
        ModeledExecutionDirective(index, intent.symbol),
    )
    quantity = _down(order.quantity * directive.fill_fraction)
    if directive.reject or quantity <= 0:
        updated = cancel_order(state.book.account, order.id)
        state = replace(state, book=adopt_dividend_account(state.book, updated, at=at))
        outcome: Literal["rejected", "cancelled"] = "rejected" if directive.reject else "cancelled"
        record = EconomicReplayRecord(
            index,
            at,
            order.symbol,
            order.side,
            outcome,
            "modeled_rejection" if directive.reject else "modeled_no_fill",
            order.id,
        )
        return replace(state, records=(*state.records, record))
    if quantity * price < 1 or (
        order.side == "sell" and quantity * price <= state.protocol.fee_usd
    ):
        updated = cancel_order(state.book.account, order.id)
        state = replace(state, book=adopt_dividend_account(state.book, updated, at=at))
        record = EconomicReplayRecord(
            index, at, order.symbol, order.side, "cancelled", "below_modeled_fill_minimum", order.id
        )
        return replace(state, records=(*state.records, record))
    sale = None
    if order.side == "sell":
        selected = tuple(
            lot
            for lot in state.book.account.lots
            if lot.symbol == order.symbol
            and lot.sleeve == order.sleeve
            and lot.episode_id == order.episode_id
        )
        sale = dispose(
            selected,
            quantity,
            price,
            at,
            fee=state.protocol.fee_usd,
            tax_rate=state.protocol.tax_rate,
        )
    fill = FillFact(
        id=f"model-fill:{order.id}",
        order_id=order.id,
        quantity=quantity,
        price=price,
        fee=state.protocol.fee_usd,
        at=at,
    )
    settings = HybridSettings(
        tax_rate=state.protocol.tax_rate,
        simulation_slippage_bps=state.protocol.slippage_bps,
        simulation_fee_usd=state.protocol.fee_usd,
    )
    updated = fill_order(state.book.account, fill, settings, settlement_at=settlement_at)
    state = replace(state, book=adopt_dividend_account(state.book, updated, at=at))
    if quantity < order.quantity:
        updated = cancel_order(state.book.account, order.id)
        state = replace(state, book=adopt_dividend_account(state.book, updated, at=at))
    records = (
        *state.records,
        EconomicReplayRecord(
            index,
            at,
            order.symbol,
            order.side,
            "filled",
            intent.reason,
            order.id,
            quantity,
            price,
            state.protocol.fee_usd,
            settlement_at,
            _ZERO if sale is None else sale.proceeds,
            _ZERO if sale is None else sale.disposed_basis,
            _ZERO if sale is None else sale.gain,
        ),
    )
    episodes = state.episodes
    policy_episodes = state.policy_episodes
    if order.side == "buy":
        episodes = (*episodes, EpisodeRuntime(order.episode_id or order.id, index, price, price))
        if state.policy_family is not None and order.sleeve == "tactical":
            close = next(
                close
                for close in reversed(state.policy_closes)
                if close.session_index == intent.signal_session
            )
            condition = next(row for row in close.conditions if row.symbol == order.symbol)
            _check(
                isinstance(condition, KnownPolicyCondition) and condition.active,
                "known_owned_entry_policy_required",
            )
            if not isinstance(condition, KnownPolicyCondition):
                raise ValueError("known_owned_entry_policy_required")
            policy_episodes = (
                *policy_episodes,
                OwnedPolicyEpisode(
                    order.episode_id or order.id,
                    state.policy_family,
                    min(40, condition.proposal.maximum_holding_sessions),
                ),
            )
    exits = dict(state.last_exits)
    if order.side == "sell" and not any(
        lot.symbol == order.symbol for lot in state.book.account.lots
    ):
        exits[order.symbol] = index
    return replace(
        state,
        records=records,
        episodes=episodes,
        policy_episodes=policy_episodes,
        last_exits=tuple(sorted(exits.items())),
    )


def _dividend_available_at(
    inputs: StockEconomicReplayInputs,
    event: StockCashDividendEvent,
) -> datetime | None:
    if event.pay_date is None:
        return None
    candidate = next(
        (
            session.opens_at
            for session in inputs.calendar
            if session.opens_at.astimezone(_NY).date() > event.pay_date
        ),
        None,
    )
    if candidate is None:
        return None
    funding = {row.day: row.status for row in inputs.dividend_funding_days}
    if (
        funding.get(event.pay_date) != "supported"
        or funding.get(candidate.astimezone(_NY).date()) != "supported"
    ):
        return None
    return candidate


def advance_stock_economic_session(
    state: StockEconomicReplayState,
    *,
    session_index: int,
    policy_frame: EconomicPolicyFrame | None = None,
) -> StockEconomicReplayState:
    with localcontext(_CONTEXT):
        _check(
            type(state) is StockEconomicReplayState
            and type(session_index) is int
            and session_index == state.next_session
            and session_index < len(state.inputs.assets[0].bars),
            "next_retained_session_required",
        )
        _validate_cost_history(state)
        if state.policy_family is None:
            _check(
                not state.policy_closes and not state.policy_episodes,
                "policy_state_family_history_mismatch",
            )
        else:
            _check(
                bool(state.policy_closes)
                and state.policy_closes[0].session_index == 199
                and state.policy_closes[-1].session_index == state.next_session - 1
                and all(close.family == state.policy_family for close in state.policy_closes),
                "policy_state_family_history_mismatch",
            )
            state.policy_closes[-1].__post_init__()
        index = session_index
        opened, closed = (
            state.inputs.calendar[index].opens_at,
            state.inputs.calendar[index].closes_at,
        )
        for event in state.inputs.dividends:
            if event.ex_date != opened.astimezone(_NY).date():
                continue
            book = record_dividend_entitlement(
                state.book,
                event,
                snapshot_at=state.inputs.calendar[index - 1].closes_at,
                ex_opens_at=opened,
                modeled_pay_available_at=_dividend_available_at(state.inputs, event),
            )
            state = replace(state, book=book)
        book = credit_due_dividends(state.book, at=opened)
        settled = settle(book.account, opened)
        state = replace(state, book=adopt_dividend_account(book, settled, at=opened))
        state = _cost_phase(state, index, "open")
        pending = state.pending
        state = replace(state, pending=())
        for intent in pending:
            state = _execute(state, intent, index)
        state = replace(state, book=credit_due_dividends(state.book, at=closed))
        state = _cost_phase(state, index, "close")
        equity, _, _, _, _ = _values(state, _prices(state, index, opening=False), closed)
        account = state.book.account
        daily = state.snapshots[-1].gross_equity
        prior_day = state.snapshots[-1].at.astimezone(_NY).date()
        day = closed.astimezone(_NY).date()
        weekly = (
            account.weekly_reference
            if day.isocalendar()[:2] == prior_day.isocalendar()[:2]
            else daily
        )
        high = max(account.high_watermark, equity)
        updated = Account.model_validate(
            account.model_dump()
            | {
                "high_watermark": high,
                "last_equity": equity,
                "daily_reference": daily,
                "weekly_reference": weekly,
                "valuation_at": closed,
                "tactical_suspended": account.tactical_suspended
                or equity <= daily * Decimal(".99")
                or equity <= high * Decimal(".90"),
                "weekly_review_required": account.weekly_review_required
                or equity <= weekly * Decimal(".97"),
            }
        )
        state = replace(state, book=adopt_dividend_account(state.book, updated, at=closed))
        if state.operating_cost_plan is not None:
            costs = apply_stock_operating_costs(state.book, state.operating_cost_plan, at=closed)
            # The close sidecar reports the completed closed-risk state, unlike
            # the pretrade opening observation which preserves the prior HWM.
            finalized_mark = replace(
                state.cost_marks[-1],
                closed_high_watermark=updated.high_watermark,
                tactical_suspended=updated.tactical_suspended,
                weekly_review_required=updated.weekly_review_required,
                cost_update_hash=stock_operating_phase_hash(costs),
            )
            state, finalized_mark = _bind_cost_mark(state, finalized_mark, costs)
            state = replace(state, cost_marks=(*state.cost_marks[:-1], finalized_mark))
        prices = _prices(state, index, opening=False)
        state = replace(
            state,
            episodes=tuple(
                replace(
                    e,
                    peak_close=max(
                        e.peak_close,
                        prices[next(a.symbol for a in updated.episodes if a.id == e.episode_id)],
                    ),
                )
                for e in state.episodes
            ),
            next_session=index + 1,
        )
        state = replace(state, snapshots=(*state.snapshots, _snapshot(state, index)))
        return _plan(state, index, policy_frame)


def halt_stock_economic_replay(state: StockEconomicReplayState) -> StockEconomicReplayState:
    with localcontext(_CONTEXT):
        _validate_cost_history(state)
        account = Account.model_validate(state.book.account.model_dump() | {"kill_switch": True})
        for order in account.orders:
            account = cancel_order(account, order.id)
        return replace(
            state,
            book=adopt_dividend_account(state.book, account, at=state.book.through_at),
            pending=(),
        )


def finish_stock_economic_replay(state: StockEconomicReplayState) -> StockEconomicReplayResult:
    _check(state.next_session == len(state.inputs.assets[0].bars), "retained_study_not_finished")
    _validate_cost_history(state)
    if state.operating_cost_plan is not None:
        return StockCostedEconomicReplayResult(
            state.book,
            state.snapshots,
            state.records,
            state.pending,
            state.evidence_hash,
            operating_costs=stock_economic_cost_report(state),
        )
    return StockEconomicReplayResult(
        state.book, state.snapshots, state.records, state.pending, state.evidence_hash
    )
