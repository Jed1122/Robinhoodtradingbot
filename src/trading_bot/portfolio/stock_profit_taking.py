"""Source-bound tactical reduction estimates, never orders or an account ledger."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    Underflow,
    localcontext,
)
from typing import Any, Literal
from zoneinfo import ZoneInfo

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.hybrid.accounting import exit_quantity
from trading_bot.portfolio.stock_holding import (
    StockHoldingLot,
    StockHoldingMandate,
    StockHoldingPrice,
    StockSaleCostAssumptions,
)

type ProfitMethod = Literal["principal", "partial_first", "partial_second", "trend"]
_METHODS = ("principal", "partial_first", "partial_second", "trend")
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
_NY = ZoneInfo("America/New_York")
_POLICY = "stock-tactical-profit-reduction-v1"
_LIMITS = (
    "indicative_price_not_executable_quote",
    "fifo_estimate_not_broker_lot_selection",
    "tax_provision_assumption_not_final_tax_liability",
    "remaining_unrealized_gain_excludes_future_sale_costs_and_tax",
    "supplied_peak_not_verified_continuous_high_water_mark",
    "supplied_basis_price_cash_units_assumed_compatible",
    "fresh_pending_fill_lot_reconciliation_required_before_any_execution",
    "does_not_override_protective_or_terminal_exit",
    "source_hashes_bind_supplied_facts_not_broker_authentication",
)


def _check(value: bool) -> None:
    if not value:
        raise ValueError("stock_profit_reduction_invalid")


def _text(value: object) -> None:
    _check(type(value) is str and 0 < len(value) <= 128 and value.isprintable())


def _num(value: object, *, positive: bool = False, nonnegative: bool = False) -> None:
    _check(type(value) is Decimal)
    if not isinstance(value, Decimal):
        raise ValueError("stock_profit_reduction_invalid")
    parts = value.as_tuple()
    _check(
        value.is_finite()
        and len(parts.digits) <= 50
        and isinstance(parts.exponent, int)
        and -30 <= parts.exponent <= 30
        and value.copy_abs() <= Decimal("1e30")
    )
    _check(not positive or value > 0)
    _check(not nonnegative or value >= 0)


def _wire(value: object) -> Any:
    if type(value) is Decimal:
        return ("decimal", tuple(value.as_tuple()))
    if type(value) is datetime:
        return (value.isoformat(), value.fold)
    if is_dataclass(value) and not isinstance(value, type):
        return _wire(asdict(value))
    if isinstance(value, dict):
        return {key: _wire(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_wire(item) for item in value]
    if value is None or type(value) in (str, int, bool):
        return value
    raise ValueError("stock_profit_reduction_invalid")


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(_wire(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class StockProfitOrigin:
    episode_id: str
    instrument_id: str
    symbol: str
    designated_cash: Decimal
    original_quantity: Decimal
    information_at: datetime
    source_hash: str

    @property
    def evidence_hash(self) -> str:
        for x in (self.episode_id, self.instrument_id, self.symbol):
            _text(x)
        _num(self.designated_cash, positive=True)
        _num(self.original_quantity, positive=True)
        require_utc(self.information_at)
        _require_sha256_hex(self.source_hash, "profit_origin")
        return _hash(("stock-profit-origin-v1", self))


@dataclass(frozen=True, slots=True, kw_only=True)
class StockProfitMethodProgress:
    method: ProfitMethod
    target_quantity: Decimal
    filled_quantity: Decimal
    fill_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class StockProfitExitState:
    episode_id: str
    instrument_id: str
    symbol: str
    origin_hash: str
    information_at: datetime
    received_at: datetime
    expires_at: datetime
    source_hash: str
    pending_exit_quantity: Decimal | None
    progress: tuple[StockProfitMethodProgress, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class StockProfitPolicy:
    policy_id: str = _POLICY
    principal_trigger_pct: Decimal = Decimal(15)
    trailing_pct: Decimal = Decimal(5)
    price_max_age_minutes: int = 120
    state_max_age_minutes: int = 120

    @property
    def evidence_hash(self) -> str:
        _check(self.policy_id == _POLICY)
        for value in (self.principal_trigger_pct, self.trailing_pct):
            _num(value, positive=True)
            _check(value <= 100)
        _check(
            all(
                type(x) is int and 1 <= x <= 10000
                for x in (self.price_max_age_minutes, self.state_max_age_minutes)
            )
        )
        return _hash((_POLICY, self))


@dataclass(frozen=True, slots=True, kw_only=True)
class StockProfitLotSlice:
    lot_id: str
    quantity: Decimal
    disposed_basis: Decimal
    acquired_at: datetime
    source_hash: str
    calendar_holding_days: int


@dataclass(frozen=True, slots=True, kw_only=True)
class StockProfitReduction:
    mandate: StockHoldingMandate
    method: ProfitMethod
    status: Literal["proposed", "hold", "unavailable"]
    reason_codes: tuple[str, ...]
    reviewed_at: datetime
    quantity: Decimal | None
    lot_slices: tuple[StockProfitLotSlice, ...]
    estimated_gross_proceeds: Decimal | None
    estimated_net_proceeds: Decimal | None
    disposed_basis: Decimal | None
    estimated_realized_gain: Decimal | None
    remaining_quantity: Decimal | None
    remaining_basis: Decimal | None
    remaining_unrealized_gain: Decimal | None
    estimated_tax_reserve: Decimal | None
    tax_rate: Decimal | None
    disposal_method: Literal["unknown", "fifo_estimate"]
    input_evidence_hash: str
    policy_hash: str
    indicative_estimates_only: Literal[True] = field(default=True, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    order_created: Literal[False] = field(default=False, init=False)
    cash_credited: Literal[False] = field(default=False, init=False)
    completed_threshold_created: Literal[False] = field(default=False, init=False)
    global_concurrency_authority: Literal[False] = field(default=False, init=False)
    performance_proven: Literal[False] = field(default=False, init=False)
    limitations: tuple[str, ...] = field(default=_LIMITS, init=False)

    @property
    def evidence_hash(self) -> str:
        _check(
            self.indicative_estimates_only is True
            and self.execution_authorized
            is self.live_authorized
            is self.order_created
            is self.cash_credited
            is self.completed_threshold_created
            is self.global_concurrency_authority
            is self.performance_proven
            is False
            and self.limitations == _LIMITS
        )
        return _hash(("stock-profit-reduction-v1", self))


def _owner(
    row: StockProfitOrigin | StockProfitExitState | StockHoldingLot | StockHoldingPrice,
    mandate: StockHoldingMandate,
) -> None:
    _check(row.instrument_id == mandate.instrument_id and row.symbol == mandate.symbol)
    if not isinstance(row, StockHoldingPrice):
        _check(row.episode_id == mandate.episode_id)


def _validate(
    mandate: StockHoldingMandate,
    lots: tuple[StockHoldingLot, ...] | None,
    origin: StockProfitOrigin | None,
    state: StockProfitExitState | None,
    price: StockHoldingPrice | None,
    peak: StockHoldingPrice | None,
    costs: StockSaleCostAssumptions | None,
    now: datetime,
    policy: StockProfitPolicy,
) -> None:
    _check(type(mandate) is StockHoldingMandate)
    mandate.__post_init__()
    require_utc(now)
    _check(mandate.first_fill_at <= now)
    if origin is not None:
        _check(type(origin) is StockProfitOrigin)
        _owner(origin, mandate)
        _ = origin.evidence_hash
        _check(mandate.first_fill_at <= origin.information_at <= now)
    quantity = None
    if lots is not None:
        _check(type(lots) is tuple and len(lots) <= 10000)
        ids = set()
        quantity = _ZERO
        for lot in lots:
            _check(type(lot) is StockHoldingLot)
            lot.__post_init__()
            _owner(lot, mandate)
            _num(lot.quantity, positive=True)
            _num(lot.basis, nonnegative=True)
            _check(lot.lot_id not in ids and mandate.first_fill_at <= lot.acquired_at <= now)
            ids.add(lot.lot_id)
            quantity += lot.quantity
            if origin is not None:
                _check(lot.acquired_at <= origin.information_at)
        if origin is not None:
            _check(quantity <= origin.original_quantity)
    if state is not None:
        _check(type(state) is StockProfitExitState)
        _owner(state, mandate)
        for digest in (state.origin_hash, state.source_hash):
            _require_sha256_hex(digest, "profit_exit_state")
        for stamp in (state.information_at, state.received_at, state.expires_at):
            require_utc(stamp)
        _check(
            mandate.first_fill_at
            <= state.information_at
            <= state.received_at
            <= now
            < state.expires_at
        )
        _check((now - state.information_at).total_seconds() <= policy.state_max_age_minutes * 60)
        if origin is not None:
            _check(
                state.origin_hash == origin.evidence_hash
                and origin.information_at <= state.information_at
            )
        if state.pending_exit_quantity is not None:
            _num(state.pending_exit_quantity, nonnegative=True)
        _check(type(state.progress) is tuple and len(state.progress) <= 4)
        methods = set()
        fills = set()
        filled = _ZERO
        for progress in state.progress:
            _check(
                type(progress) is StockProfitMethodProgress
                and progress.method in _METHODS
                and progress.method not in methods
            )
            methods.add(progress.method)
            _num(progress.target_quantity, positive=True)
            _num(progress.filled_quantity, nonnegative=True)
            _check(
                progress.filled_quantity <= progress.target_quantity
                and type(progress.fill_ids) is tuple
                and len(progress.fill_ids) <= 10000
            )
            _check(bool(progress.fill_ids) == (progress.filled_quantity > 0))
            for identity in progress.fill_ids:
                _text(identity)
                _check(identity not in fills)
                fills.add(identity)
            if origin is not None:
                _check(progress.target_quantity <= origin.original_quantity)
            filled += progress.filled_quantity
        if quantity is not None and origin is not None:
            _check(filled <= origin.original_quantity - quantity)
    for point in (price, peak):
        if point is None:
            continue
        _check(type(point) is StockHoldingPrice)
        point.__post_init__()
        _owner(point, mandate)
        _num(point.value, positive=True)
        _check(mandate.first_fill_at <= point.at <= point.received_at <= now)
    if price is not None:
        _check((now - price.at).total_seconds() <= policy.price_max_age_minutes * 60)
        if lots is not None:
            _check(all(x.acquired_at <= price.at for x in lots))
        if origin is not None:
            _check(origin.information_at <= price.at)
        if state is not None:
            _check(state.information_at <= price.at)
        if peak is not None:
            _check(peak.at <= price.at)
    if costs is not None:
        _check(type(costs) is StockSaleCostAssumptions)
        costs.__post_init__()
        _num(costs.fee, nonnegative=True)
        _num(costs.adverse_slippage_bps, nonnegative=True)


def _fifo(
    lots: tuple[StockHoldingLot, ...], quantity: Decimal, price: StockHoldingPrice
) -> tuple[tuple[StockProfitLotSlice, ...], Decimal]:
    needed = quantity
    basis = _ZERO
    slices = []
    for lot in sorted(lots, key=lambda x: (x.acquired_at, x.lot_id)):
        if needed <= 0:
            break
        taken = min(needed, lot.quantity)
        cost = lot.basis if taken == lot.quantity else lot.basis * taken / lot.quantity
        slices.append(
            StockProfitLotSlice(
                lot_id=lot.lot_id,
                quantity=taken,
                disposed_basis=cost,
                acquired_at=lot.acquired_at,
                source_hash=lot.source_hash,
                calendar_holding_days=(
                    price.at.astimezone(_NY).date() - lot.acquired_at.astimezone(_NY).date()
                ).days,
            )
        )
        basis += cost
        needed -= taken
    _check(needed == 0)
    return tuple(slices), basis


def propose_stock_profit_reduction(
    mandate: StockHoldingMandate,
    *,
    method: ProfitMethod,
    remaining_lots: tuple[StockHoldingLot, ...] | None,
    origin: StockProfitOrigin | None,
    state: StockProfitExitState | None,
    price: StockHoldingPrice | None,
    costs: StockSaleCostAssumptions | None,
    fractional_eligible: bool | None,
    reviewed_at: datetime,
    tax_rate: Decimal | None = None,
    disposal_method: Literal["unknown", "fifo_estimate"] = "unknown",
    peak_price: StockHoldingPrice | None = None,
    policy: StockProfitPolicy | None = None,
) -> StockProfitReduction:
    """Estimate one optional tactical reduction; final lot/tax choice belongs to broker owner."""
    try:
        with localcontext(_CONTEXT):
            chosen = StockProfitPolicy() if policy is None else policy
            _check(type(chosen) is StockProfitPolicy)
            policy_hash = chosen.evidence_hash
            _check(method in _METHODS and disposal_method in ("unknown", "fifo_estimate"))
            _check(fractional_eligible is None or type(fractional_eligible) is bool)
            if tax_rate is not None:
                _num(tax_rate, nonnegative=True)
                _check(tax_rate <= 1)
            _validate(
                mandate,
                remaining_lots,
                origin,
                state,
                price,
                peak_price,
                costs,
                reviewed_at,
                chosen,
            )
            identity = _hash(
                (
                    _POLICY,
                    mandate,
                    method,
                    remaining_lots,
                    origin,
                    state,
                    price,
                    costs,
                    fractional_eligible,
                    reviewed_at,
                    tax_rate,
                    disposal_method,
                    peak_price,
                    policy_hash,
                )
            )

            def result(
                status: Literal["proposed", "hold", "unavailable"],
                reasons: tuple[str, ...],
                quantity: Decimal | None = None,
                slices: tuple[StockProfitLotSlice, ...] = (),
                estimates: tuple[Decimal, ...] | None = None,
            ) -> StockProfitReduction:
                gross = net = basis = gain = remaining = remaining_basis = unrealized = None
                if estimates is not None:
                    gross, net, basis, gain, remaining, remaining_basis, unrealized = estimates
                return StockProfitReduction(
                    mandate=mandate,
                    method=method,
                    status=status,
                    reason_codes=reasons,
                    reviewed_at=reviewed_at,
                    quantity=quantity,
                    lot_slices=slices,
                    estimated_gross_proceeds=gross,
                    estimated_net_proceeds=net,
                    disposed_basis=basis,
                    estimated_realized_gain=gain,
                    remaining_quantity=remaining,
                    remaining_basis=remaining_basis,
                    remaining_unrealized_gain=unrealized,
                    estimated_tax_reserve=None
                    if gain is None or tax_rate is None
                    else max(gain, _ZERO) * tax_rate,
                    tax_rate=tax_rate,
                    disposal_method=disposal_method,
                    input_evidence_hash=identity,
                    policy_hash=policy_hash,
                )

            if mandate.sleeve == "long_term":
                return result("hold", ("long_term_no_automatic_profit_cut",), _ZERO)
            if remaining_lots == ():
                return result("hold", ("no_remaining_owned_shares",), _ZERO)
            missing = []
            for name, value in (
                ("remaining_lots", remaining_lots),
                ("origin", origin),
                ("state", state),
                ("price", price),
                ("costs", costs),
                ("fractional_eligible", fractional_eligible),
            ):
                if value is None:
                    missing.append(name + "_unknown")
            if method == "trend" and peak_price is None:
                missing.append("sourced_peak_unknown")
            if disposal_method == "unknown":
                missing.append("disposal_method_unknown")
            if missing:
                return result("unavailable", tuple(missing))
            if (
                remaining_lots is None
                or origin is None
                or state is None
                or price is None
                or costs is None
                or fractional_eligible is None
            ):
                raise ValueError("stock_profit_reduction_invalid")
            if state.pending_exit_quantity is None:
                return result("unavailable", ("pending_exit_state_unknown",))
            if state.pending_exit_quantity > 0:
                return result("hold", ("actual_exit_pending",), _ZERO)
            progress = next((x for x in state.progress if x.method == method), None)
            if progress is not None and progress.filled_quantity == progress.target_quantity:
                return result("hold", ("method_completed_by_actual_fills",), _ZERO)
            owned = sum((x.quantity for x in remaining_lots), _ZERO)
            target = exit_quantity(
                method,
                owned,
                price.value,
                origin.designated_cash,
                price.value if peak_price is None else peak_price.value,
                fractional=fractional_eligible,
                original_quantity=origin.original_quantity,
                trigger_pct=chosen.principal_trigger_pct,
                trailing_pct=chosen.trailing_pct,
            )
            if progress is not None:
                cumulative_cap = progress.target_quantity
                if method in ("partial_first", "partial_second"):
                    cumulative_cap = min(cumulative_cap, origin.original_quantity / 4)
                target = min(target, max(_ZERO, cumulative_cap - progress.filled_quantity))
            # A progress cap can introduce a sub-increment tail; round it down too.
            target = target.quantize(
                Decimal(".000001") if fractional_eligible else Decimal(1), rounding=ROUND_DOWN
            )
            if target <= 0:
                return result("hold", ("threshold_not_met_or_quantity_below_increment",), _ZERO)
            slices, basis = _fifo(remaining_lots, target, price)
            gross = target * price.value
            net = gross * (1 - costs.adverse_slippage_bps / 10000) - costs.fee
            if net < 0:
                return result("unavailable", ("costs_exceed_estimated_proceeds",))
            gain = net - basis
            if method != "trend" and gain <= 0:
                return result("hold", ("nonpositive_estimated_disposal_gain",), _ZERO)
            remaining = owned - target
            remaining_basis = sum((x.basis for x in remaining_lots), _ZERO) - basis
            return result(
                "proposed",
                ("indicative_tactical_reduction",),
                target,
                slices,
                (
                    gross,
                    net,
                    basis,
                    gain,
                    remaining,
                    remaining_basis,
                    remaining * price.value - remaining_basis,
                ),
            )
    except (DecimalException, ValueError, TypeError, OverflowError):
        raise ValueError("stock_profit_reduction_invalid") from None
