"""Snapshot-only stock cash ceilings; no order, reservation or broker authority.

The initial profile requires equity == broker cash + owned stock market values.
Unexplained claims or valuation-timing differences block new entries; a later
source-bound context must explicitly model them instead of guessing adjustments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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

from trading_bot.clock import require_utc
from trading_bot.domain.accounts import AccountSnapshot, PortfolioSnapshot, Position
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.domain.enums import AssetClass
from trading_bot.market_data.recording import content_hash

_ZERO = Decimal(0)
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
_VERSION = "current-stock-new-entry-allocation-v1"
Sleeve = Literal["long_term", "tactical"]


def _check(value: bool, reason: str) -> None:
    if not value:
        raise ValueError(reason)


def _text(value: str) -> None:
    _check(
        type(value) is str and 0 < len(value) <= 128 and value.isprintable(),
        "stock_allocation_identifier_invalid",
    )


def _hash(value: object) -> str:
    with localcontext(_CONTEXT):
        return str(content_hash(value))


def _optional_money(value: Decimal | None, name: str) -> None:
    if value is not None:
        require_bounded_decimal(value, name, nonnegative=True)


def _metadata(
    instrument_id: str,
    symbol: str,
    issuer_id: str | None,
    sleeve: Sleeve,
    sector: str | None,
    kind: str | None,
    source_hash: str | None,
) -> None:
    _text(instrument_id)
    _text(symbol)
    _check(
        symbol == symbol.upper()
        and symbol[0].isalpha()
        and all(c.isascii() and (c.isalnum() or c in ".-/") for c in symbol),
        "stock_allocation_symbol_invalid",
    )
    _check(sleeve in ("long_term", "tactical"), "stock_allocation_sleeve_invalid")
    for text in (issuer_id, sector):
        if text is not None:
            _text(text)
    _check(kind in ("stock", "unsupported", None), "stock_allocation_kind_invalid")
    if source_hash is not None:
        _require_sha256_hex(source_hash, "allocation_source")


@dataclass(frozen=True, slots=True)
class StockAllocationLimits:
    long_term_target: Decimal = Decimal(".75")
    tactical_target: Decimal = Decimal(".15")
    strategic_reserve: Decimal = Decimal(".10")
    company_cap: Decimal = Decimal(".10")
    tactical_position_cap: Decimal = Decimal(".04")
    sector_cap: Decimal = Decimal(".25")

    def __post_init__(self) -> None:
        for name, value, ceiling in (
            ("long_term", self.long_term_target, Decimal(".75")),
            ("tactical", self.tactical_target, Decimal(".15")),
            ("company", self.company_cap, Decimal(".10")),
            ("tactical_position", self.tactical_position_cap, Decimal(".04")),
            ("sector", self.sector_cap, Decimal(".25")),
        ):
            require_bounded_decimal(value, name, nonnegative=True)
            _check(value <= ceiling, "stock_allocation_hard_cap_cannot_increase")
        require_bounded_decimal(self.strategic_reserve, "reserve", nonnegative=True)
        with localcontext(_CONTEXT):
            _check(
                Decimal(".10") <= self.strategic_reserve <= 1
                and self.long_term_target + self.tactical_target + self.strategic_reserve <= 1,
                "stock_allocation_reserve_or_targets_invalid",
            )

    @property
    def evidence_hash(self) -> str:
        self.__post_init__()
        return _hash((_VERSION, self))


@dataclass(frozen=True, slots=True)
class StockAllocationExposure:
    reference_id: str
    origin: Literal["position", "broker_pending", "local_reserved"]
    instrument_id: str
    symbol: str
    issuer_id: str | None
    sleeve: Sleeve
    sector: str | None
    instrument_kind: Literal["stock", "unsupported"] | None
    remaining_notional: Decimal | None
    local_cash_reservation: Decimal | None
    source_hash: str | None

    def __post_init__(self) -> None:
        _text(self.reference_id)
        _check(
            self.origin in ("position", "broker_pending", "local_reserved"),
            "stock_allocation_exposure_origin_invalid",
        )
        _metadata(
            self.instrument_id,
            self.symbol,
            self.issuer_id,
            self.sleeve,
            self.sector,
            self.instrument_kind,
            self.source_hash,
        )
        _optional_money(self.remaining_notional, "pending_exposure")
        _optional_money(self.local_cash_reservation, "local_cash_reservation")
        if self.local_cash_reservation is not None:
            _check(
                self.origin == "local_reserved" or self.local_cash_reservation == 0,
                "broker_reflected_hold_cannot_be_locally_subtracted",
            )
        if self.origin == "local_reserved" and self.remaining_notional is not None:
            _check(
                self.local_cash_reservation is None
                or self.local_cash_reservation >= self.remaining_notional,
                "local_cash_reservation_below_exposure",
            )


@dataclass(frozen=True, slots=True)
class StockAllocationCandidate:
    instrument_id: str
    symbol: str
    issuer_id: str | None
    sleeve: Sleeve
    sector: str | None
    instrument_kind: Literal["stock", "unsupported"] | None
    priority: int
    decision_status: Literal["eligible", "ineligible", "unknown"]
    decision_hash: str | None
    source_hash: str | None
    as_of: datetime | None
    expires_at: datetime | None

    def __post_init__(self) -> None:
        _metadata(
            self.instrument_id,
            self.symbol,
            self.issuer_id,
            self.sleeve,
            self.sector,
            self.instrument_kind,
            self.source_hash,
        )
        _check(
            type(self.priority) is int and 0 <= self.priority <= 1000000,
            "stock_allocation_priority_invalid",
        )
        _check(
            self.decision_status in ("eligible", "ineligible", "unknown"),
            "stock_allocation_candidate_status_invalid",
        )
        if self.decision_hash is not None:
            _require_sha256_hex(self.decision_hash, "allocation_decision")
        for stamp in (self.as_of, self.expires_at):
            if stamp is not None:
                require_utc(stamp)
        if self.as_of is not None and self.expires_at is not None:
            _check(self.as_of < self.expires_at, "candidate_expiry_invalid")


@dataclass(frozen=True, slots=True)
class StockAllocationContext:
    account: AccountSnapshot
    portfolio: PortfolioSnapshot
    account_type: Literal["cash", "margin"] | None
    currency: Literal["USD"] | None
    unleveraged_buying_power: Decimal | None
    tax_reserve: Decimal | None
    reconciliation_hash: str | None
    exposures: tuple[StockAllocationExposure, ...]
    as_of: datetime
    expires_at: datetime
    source_hash: str | None

    def __post_init__(self) -> None:
        _check(
            type(self.account) is AccountSnapshot and type(self.portfolio) is PortfolioSnapshot,
            "exact_current_account_and_portfolio_required",
        )
        self.account.__post_init__()
        self.portfolio.__post_init__()
        _check(self.account_type in ("cash", "margin", None), "account_type_invalid")
        _check(self.currency in ("USD", None), "allocation_currency_invalid")
        _optional_money(self.unleveraged_buying_power, "unleveraged_buying_power")
        _optional_money(self.tax_reserve, "allocation_tax_reserve")
        for value in (self.reconciliation_hash, self.source_hash):
            if value is not None:
                _require_sha256_hex(value, "allocation_context_source")
        require_utc(self.as_of)
        require_utc(self.expires_at)
        _check(self.as_of < self.expires_at, "allocation_context_expiry_invalid")
        _check(
            type(self.exposures) is tuple and len(self.exposures) <= 10000,
            "immutable_allocation_exposures_required",
        )
        for row in self.exposures:
            _check(type(row) is StockAllocationExposure, "typed_allocation_exposure_required")
            row.__post_init__()

    @property
    def evidence_hash(self) -> str:
        self.__post_init__()
        return _hash(("stock-allocation-context-v1", self))


@dataclass(frozen=True, slots=True)
class StockAllocationProposal:
    instrument_id: str
    symbol: str
    issuer_id: str
    sleeve: Sleeve
    sector: str
    priority: int
    decision_hash: str
    cash_ceiling: Decimal


@dataclass(frozen=True, slots=True)
class StockAllocationDenial:
    instrument_id: str
    symbol: str
    sleeve: Sleeve
    decision_hash: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class StockAllocationPlan:
    status: Literal["planned", "blocked"]
    reason_codes: tuple[str, ...]
    proposals: tuple[StockAllocationProposal, ...]
    denials: tuple[StockAllocationDenial, ...]
    cash_cap: Decimal | None
    remaining_cash_cap: Decimal | None
    total_proposed: Decimal
    context_hash: str
    limits_hash: str
    input_evidence_hash: str
    execution_authorized: Literal[False] = field(default=False, init=False)
    reservations_created: Literal[False] = field(default=False, init=False)
    orders_created: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    global_concurrency_authority: Literal[False] = field(default=False, init=False)

    @property
    def evidence_hash(self) -> str:
        _check(
            self.execution_authorized
            is self.reservations_created
            is self.orders_created
            is self.live_authorized
            is self.global_concurrency_authority
            is False,
            "stock_allocation_scope_changed",
        )
        return _hash((_VERSION, self))


def _context_reasons(context: StockAllocationContext, now: datetime) -> tuple[str, ...]:
    account, portfolio = context.account, context.portfolio
    _check(
        account.account_id == portfolio.account_id
        and account.cash == portfolio.cash
        and account.equity == portfolio.equity,
        "current_portfolio_account_mismatch",
    )
    _check(
        account.observed_at <= context.as_of and portfolio.observed_at <= context.as_of,
        "future_account_or_portfolio_snapshot",
    )
    reasons = []
    if not context.as_of <= now < context.expires_at:
        reasons.append("context_stale_or_future")
    if context.account_type != "cash":
        reasons.append(
            "cash_account_type_unknown" if context.account_type is None else "margin_account_denied"
        )
    if context.currency is None:
        reasons.append("account_currency_unknown")
    if context.source_hash is None or context.reconciliation_hash is None:
        reasons.append("current_reconciliation_or_source_unknown")
    if context.unleveraged_buying_power is None:
        reasons.append("unleveraged_buying_power_unknown")
    if context.tax_reserve is None:
        reasons.append("tax_reserve_unknown")
    if account.restricted or account.provider_state != "active":
        reasons.append("account_not_active")
    powers = tuple(x.amount for x in account.buying_power if x.asset_class is AssetClass.EQUITY)
    if len(powers) != 1:
        reasons.append("equity_buying_power_unknown_or_ambiguous")
    elif (
        context.unleveraged_buying_power is not None
        and context.unleveraged_buying_power > powers[0]
    ):
        reasons.append("contradictory_buying_power")
    for position in portfolio.positions:
        position.__post_init__()
        _check(position.observed_at <= context.as_of, "future_nested_position_snapshot")
    positions: dict[str, Position] = {p.instrument_id: p for p in portfolio.positions}
    _check(len(positions) == len(portfolio.positions), "duplicate_current_position")
    held = tuple(x for x in context.exposures if x.origin == "position")
    _check(
        len({x.instrument_id for x in held}) == len(held)
        and {x.instrument_id for x in held} == set(positions),
        "position_metadata_join_mismatch",
    )
    references = set()
    owned_sleeves: dict[str, str] = {}
    for row in context.exposures:
        _check(row.reference_id not in references, "duplicate_allocation_exposure_reference")
        references.add(row.reference_id)
        for identity in ("instrument:" + row.instrument_id, "symbol:" + row.symbol):
            if identity in owned_sleeves and owned_sleeves[identity] != row.sleeve:
                reasons.append("existing_cross_sleeve_symbol")
            owned_sleeves[identity] = row.sleeve
        if (
            row.issuer_id is None
            or row.sector is None
            or row.source_hash is None
            or row.remaining_notional is None
            or row.local_cash_reservation is None
        ):
            reasons.append("owned_or_pending_exposure_unknown")
        if row.instrument_kind != "stock":
            reasons.append("unsupported_owned_or_pending_exposure")
        if row.origin == "position":
            position = positions[row.instrument_id]
            _check(
                row.remaining_notional is None or row.remaining_notional == position.market_value,
                "position_value_metadata_mismatch",
            )
            if (
                position.asset_class is not AssetClass.EQUITY
                or position.quantity <= 0
                or position.market_value <= 0
            ):
                reasons.append("unsupported_current_position")
    total = sum((p.market_value for p in portfolio.positions), _ZERO)
    if portfolio.cash + total < portfolio.equity:
        reasons.append("unexplained_portfolio_equity")
    if (
        total != portfolio.gross_exposure
        or portfolio.net_exposure != portfolio.gross_exposure
        or portfolio.crypto_exposure != 0
        or portfolio.cash + total > portfolio.equity
    ):
        reasons.append("unsupported_or_leveraged_portfolio")
    return tuple(sorted(set(reasons)))


def _candidate_inventory(
    context: StockAllocationContext,
    candidates: tuple[StockAllocationCandidate, ...],
) -> tuple[StockAllocationCandidate, ...]:
    _check(
        type(candidates) is tuple and len(candidates) <= 10000,
        "immutable_bounded_allocation_candidates_required",
    )
    deduplicated: dict[tuple[str, str], StockAllocationCandidate] = {}
    for row in candidates:
        _check(type(row) is StockAllocationCandidate, "typed_allocation_candidate_required")
        row.__post_init__()
        key = row.instrument_id, row.sleeve
        old = deduplicated.get(key)
        _check(old is None or _hash(old) == _hash(row), "conflicting_duplicate_candidate")
        deduplicated[key] = row
    instruments: dict[str, tuple[str, str | None]] = {}
    symbols: dict[str, str] = {}
    sectors: dict[str, str] = {}
    inventory: tuple[StockAllocationExposure | StockAllocationCandidate, ...] = (
        *context.exposures,
        *deduplicated.values(),
    )
    for item in inventory:
        previous = instruments.get(item.instrument_id)
        if previous is not None:
            _check(
                previous[0] == item.symbol
                and (
                    previous[1] is None or item.issuer_id is None or previous[1] == item.issuer_id
                ),
                "allocation_instrument_identity_conflict",
            )
        _check(
            item.symbol not in symbols or symbols[item.symbol] == item.instrument_id,
            "allocation_symbol_identity_conflict",
        )
        instruments[item.instrument_id] = item.symbol, item.issuer_id
        symbols[item.symbol] = item.instrument_id
        if item.issuer_id is not None and item.sector is not None:
            _check(
                item.issuer_id not in sectors or sectors[item.issuer_id] == item.sector,
                "allocation_issuer_sector_conflict",
            )
            sectors[item.issuer_id] = item.sector
    return tuple(
        sorted(
            deduplicated.values(),
            key=lambda row: (
                row.sleeve != "long_term",
                row.priority,
                row.symbol,
                row.instrument_id,
            ),
        )
    )


def plan_stock_allocations(
    context: StockAllocationContext,
    candidates: tuple[StockAllocationCandidate, ...],
    *,
    now: datetime,
    limits: StockAllocationLimits | None = None,
) -> StockAllocationPlan:
    """Propose debit ceilings once; runtime must atomically reserve/recheck them."""
    with localcontext(_CONTEXT):
        _check(type(context) is StockAllocationContext, "typed_allocation_context_required")
        context.__post_init__()
        require_utc(now)
        policy = StockAllocationLimits() if limits is None else limits
        _check(type(policy) is StockAllocationLimits, "typed_manual_allocation_limits_required")
        policy.__post_init__()
        rows = _candidate_inventory(context, candidates)
        reasons = _context_reasons(context, now)
        identity = _hash((_VERSION, context, candidates, now, policy))
        if reasons:
            return StockAllocationPlan(
                "blocked",
                reasons,
                (),
                (),
                None,
                None,
                _ZERO,
                context.evidence_hash,
                policy.evidence_hash,
                identity,
            )
        bp, tax = context.unleveraged_buying_power, context.tax_reserve
        if bp is None or tax is None:
            raise ValueError("known_allocation_cash_inputs_required")
        equity = context.portfolio.equity
        local = sum(
            (
                row.local_cash_reservation or _ZERO
                for row in context.exposures
                if row.origin == "local_reserved"
            ),
            _ZERO,
        )
        cash_cap = max(
            _ZERO, min(bp, context.account.cash) - equity * policy.strategic_reserve - tax - local
        ).quantize(Decimal(".01"), rounding=ROUND_DOWN)
        available = cash_cap
        sleeves = {"long_term": _ZERO, "tactical": _ZERO}
        companies: dict[str, Decimal] = {}
        sectors: dict[str, Decimal] = {}
        held_symbols, held_instruments = set(), set()
        for owned in context.exposures:
            if owned.issuer_id is None or owned.sector is None or owned.remaining_notional is None:
                raise ValueError("known_allocation_exposure_required")
            sleeves[owned.sleeve] += owned.remaining_notional
            companies[owned.issuer_id] = (
                companies.get(owned.issuer_id, _ZERO) + owned.remaining_notional
            )
            sectors[owned.sector] = sectors.get(owned.sector, _ZERO) + owned.remaining_notional
            held_symbols.add(owned.symbol)
            held_instruments.add(owned.instrument_id)
        proposed_symbols, proposed_instruments = set(), set()
        proposals, denials = [], []
        for row in rows:
            reason = ""
            if row.decision_status != "eligible":
                reason = "decision_not_eligible"
            elif row.decision_hash is None or row.source_hash is None:
                reason = "candidate_decision_source_unknown"
            elif row.issuer_id is None or row.sector is None:
                reason = "candidate_metadata_unknown"
            elif row.instrument_kind != "stock":
                reason = "unsupported_candidate_instrument"
            elif (
                row.as_of is None or row.expires_at is None or not row.as_of <= now < row.expires_at
            ):
                reason = "candidate_stale_or_future"
            elif row.symbol in held_symbols or row.instrument_id in held_instruments:
                reason = "held_or_pending_symbol"
            elif row.symbol in proposed_symbols or row.instrument_id in proposed_instruments:
                reason = "proposed_symbol_overlap"
            if not reason:
                if row.issuer_id is None or row.sector is None or row.decision_hash is None:
                    raise ValueError("known_eligible_allocation_candidate_required")
                target = (
                    policy.long_term_target if row.sleeve == "long_term" else policy.tactical_target
                )
                rooms = [
                    ("cash_reserve_or_local_reservations", available),
                    ("sleeve_target_reached", equity * target - sleeves[row.sleeve]),
                    (
                        "company_cap_reached",
                        equity * policy.company_cap - companies.get(row.issuer_id, _ZERO),
                    ),
                    (
                        "sector_cap_reached",
                        equity * policy.sector_cap - sectors.get(row.sector, _ZERO),
                    ),
                ]
                if row.sleeve == "tactical":
                    rooms.append(
                        ("tactical_position_cap_reached", equity * policy.tactical_position_cap)
                    )
                budget = max(_ZERO, min(value for _, value in rooms)).quantize(
                    Decimal(".01"), rounding=ROUND_DOWN
                )
                if budget <= 0:
                    reason = next(
                        (label for label, value in rooms if value <= 0), "below_cent_cash_ceiling"
                    )
                else:
                    proposals.append(
                        StockAllocationProposal(
                            row.instrument_id,
                            row.symbol,
                            row.issuer_id,
                            row.sleeve,
                            row.sector,
                            row.priority,
                            row.decision_hash,
                            budget,
                        )
                    )
                    available -= budget
                    sleeves[row.sleeve] += budget
                    companies[row.issuer_id] = companies.get(row.issuer_id, _ZERO) + budget
                    sectors[row.sector] = sectors.get(row.sector, _ZERO) + budget
                    proposed_symbols.add(row.symbol)
                    proposed_instruments.add(row.instrument_id)
            if reason:
                denials.append(
                    StockAllocationDenial(
                        row.instrument_id, row.symbol, row.sleeve, row.decision_hash, reason
                    )
                )
        return StockAllocationPlan(
            "planned",
            (),
            tuple(proposals),
            tuple(denials),
            cash_cap,
            available,
            cash_cap - available,
            context.evidence_hash,
            policy.evidence_hash,
            identity,
        )
