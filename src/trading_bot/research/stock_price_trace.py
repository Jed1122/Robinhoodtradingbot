"""Pure, dimensionless next-open target replay with a continuous cash/stock state.

This is an experimental price-only cost ablation, not a monetary ledger or broker
fill model. Prices and targets must be admitted independently by the caller. The
cost basis is the pre-fee target allocation change; actual post-fee turnover is
recorded separately. Neither quantity carries a currency or execution entitlement.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
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

from trading_bot.domain.decimal_utils import require_bounded_decimal
from trading_bot.research.hybrid_strategies import PriceBar

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
_ZERO = Decimal(0)
_ONE = Decimal(1)
_LIMITATIONS = (
    "dimensionless_price_only_path_not_total_return_or_after_tax_wealth",
    "experimental_pre_fee_target_nav_cost_basis_not_broker_notional_fees",
    "fractional_immediate_full_allocation_at_next_open_is_an_assumption",
    "cash_return_is_zero_by_convention",
    "input_calendar_currency_actions_and_point_in_time_eligibility_not_qualified_here",
    "terminal_liquidation_is_a_declared_horizon_convention_not_a_final_signal_fill",
)


@dataclass(frozen=True, slots=True)
class PriceTraceRow:
    """One session; values/turnover/costs use normalized initial NAV units.

    ``opening_nav`` is marked before that open's rebalance. ``executed_target``
    is the previous session's close decision (None for the initial flat row).
    ``target`` is observed at this close and cannot affect this row's execution.
    Stock/cash/quantity reflect the state after any declared terminal liquidation.
    The pre-terminal close is retained separately so the horizon cost is auditable.
    """

    session_index: int
    opens_at: datetime
    closes_at: datetime
    open_price: Decimal
    close_price: Decimal
    opening_nav: Decimal
    post_trade_nav: Decimal
    closing_nav_before_terminal: Decimal
    nav: Decimal
    stock_quantity: Decimal
    stock_value: Decimal
    cash_value: Decimal
    closing_stock_value_before_terminal: Decimal
    closing_cash_value_before_terminal: Decimal
    target: Decimal
    executed_target: Decimal | None
    trade_cost: Decimal
    terminal_cost: Decimal
    cost: Decimal
    cost_basis_turnover: Decimal
    actual_turnover: Decimal


@dataclass(frozen=True, slots=True)
class PriceTrace:
    rows: tuple[PriceTraceRow, ...]
    one_way_cost_bps: Decimal
    terminal_policy: Literal["mark", "liquidate"]
    pending_target: Decimal
    initial_nav: Decimal = field(default=_ONE, init=False)
    arithmetic_precision: Literal[50] = field(default=50, init=False)
    units: Literal["normalized_initial_nav"] = field(default="normalized_initial_nav", init=False)
    quote_currency: None = field(default=None, init=False)
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)


@dataclass(frozen=True, slots=True)
class PriceTraceSlice:
    """Inclusive view of existing rows, with state from the preceding close.

    Slicing performs no execution, rebasing, reset or extra liquidation. Its final
    row contains a horizon cost only if that same row did in the original trace.
    ``inherited_high_watermark`` includes initial NAV and all preceding closes;
    segment-only drawdown can separately start at ``baseline_nav``.
    """

    first_session: int
    last_session: int
    baseline_nav: Decimal
    baseline_stock_quantity: Decimal
    baseline_stock_value: Decimal
    baseline_cash_value: Decimal
    pending_target_at_start: Decimal | None
    inherited_high_watermark: Decimal
    rows: tuple[PriceTraceRow, ...]
    pending_target: Decimal
    arithmetic_precision: Literal[50] = field(default=50, init=False)
    units: Literal["normalized_initial_nav"] = field(default="normalized_initial_nav", init=False)
    quote_currency: None = field(default=None, init=False)
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)


def _utc_timestamp(value: datetime) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("UTC datetime required")


def _validate_inputs(
    bars: tuple[PriceBar, ...],
    opens_at: tuple[datetime, ...],
    targets: tuple[Decimal, ...],
    one_way_cost_bps: Decimal,
    terminal_policy: Literal["mark", "liquidate"],
) -> None:
    if any(type(value) is not tuple for value in (bars, opens_at, targets)):
        raise ValueError("immutable tuples required")
    if not 1 <= len(bars) <= 10000 or len(bars) != len(opens_at) or len(bars) != len(targets):
        raise ValueError("nonempty matching bars, calendar and targets required")
    if type(terminal_policy) is not str or terminal_policy not in ("mark", "liquidate"):
        raise ValueError("declared mark or liquidate terminal policy required")
    require_bounded_decimal(one_way_cost_bps, "one_way_cost_bps", nonnegative=True)
    if one_way_cost_bps >= 10000:
        raise ValueError("cost must be below 10000 basis points")
    previous_close: datetime | None = None
    for bar, opened, target in zip(bars, opens_at, targets, strict=True):
        if type(bar) is not PriceBar:
            raise ValueError("PriceBar required")
        _utc_timestamp(opened)
        _utc_timestamp(bar.completed_at)
        if opened >= bar.completed_at or (previous_close is not None and opened <= previous_close):
            raise ValueError("unique increasing nonoverlapping sessions required")
        for price in (bar.open, bar.close):
            require_bounded_decimal(price, "price", positive=True)
            if not Decimal("1e-30") <= price <= Decimal("1e30"):
                raise ValueError("price outside admitted arithmetic bounds")
        require_bounded_decimal(target, "target", nonnegative=True)
        if target > 1:
            raise ValueError("target must be a Decimal fraction in [0,1]")
        previous_close = bar.completed_at


def trace_price_targets(
    bars: tuple[PriceBar, ...],
    opens_at: tuple[datetime, ...],
    targets: tuple[Decimal, ...],
    *,
    one_way_cost_bps: Decimal,
    terminal_policy: Literal["mark", "liquidate"] = "liquidate",
) -> PriceTrace:
    """Replay prior-close targets at next opens using independent 50-digit math.

    Row zero is flat at NAV one. At each following open the prior close's target
    determines ``cost = rate * abs(target * preopen_nav - old_stock_value)``.
    Remaining NAV is allocated to the target stock/cash fractions. Binary targets
    preserve the legacy full-transition NAV haircuts; fractional rebalancing is
    explicitly an experimental approximation. The last target is never executed.
    """
    _validate_inputs(bars, opens_at, targets, one_way_cost_bps, terminal_policy)
    rows: list[PriceTraceRow] = []
    cash, quantity = _ONE, _ZERO
    try:
        with localcontext(_CONTEXT):
            rate = one_way_cost_bps / Decimal(10000)
            for index, (bar, opened, target) in enumerate(
                zip(bars, opens_at, targets, strict=True)
            ):
                old_stock_value = quantity * bar.open
                opening_nav = cash + old_stock_value
                executed_target = None if index == 0 else targets[index - 1]
                basis, trade_cost, turnover = _ZERO, _ZERO, _ZERO
                post_trade_nav = opening_nav
                if executed_target is not None:
                    basis = abs(executed_target * opening_nav - old_stock_value)
                    trade_cost = rate * basis
                    post_trade_nav = opening_nav - trade_cost
                    stock_allocation = executed_target * post_trade_nav
                    turnover = abs(stock_allocation - old_stock_value)
                    cash = post_trade_nav - stock_allocation
                    if stock_allocation != old_stock_value:
                        quantity = stock_allocation / bar.open
                stock_value = quantity * bar.close
                closing_cash = cash
                closing_stock = stock_value
                closing_nav = cash + stock_value
                terminal_cost = _ZERO
                if index == len(bars) - 1 and terminal_policy == "liquidate":
                    terminal_cost = rate * stock_value
                    basis += stock_value
                    turnover += stock_value
                    cash = closing_nav - terminal_cost
                    stock_value, quantity = _ZERO, _ZERO
                nav = cash + stock_value
                if not nav.is_finite() or nav <= 0:
                    raise ValueError("nonpositive or nonfinite normalized NAV")
                rows.append(
                    PriceTraceRow(
                        index,
                        opened,
                        bar.completed_at,
                        bar.open,
                        bar.close,
                        opening_nav,
                        post_trade_nav,
                        closing_nav,
                        nav,
                        quantity,
                        stock_value,
                        cash,
                        closing_stock,
                        closing_cash,
                        target,
                        executed_target,
                        trade_cost,
                        terminal_cost,
                        trade_cost + terminal_cost,
                        basis,
                        turnover,
                    )
                )
    except DecimalException as exc:
        raise ValueError("normalized price trace arithmetic invalid") from exc
    return PriceTrace(tuple(rows), one_way_cost_bps, terminal_policy, targets[-1])


def slice_price_trace(
    trace: PriceTrace, *, first_session: int, last_session: int
) -> PriceTraceSlice:
    """Select inclusive sessions without reconstructing or altering their state."""
    if (
        type(trace) is not PriceTrace
        or type(first_session) is not int
        or type(last_session) is not int
        or not 0 <= first_session <= last_session < len(trace.rows)
    ):
        raise ValueError("valid inclusive trace session indices required")
    before = None if first_session == 0 else trace.rows[first_session - 1]
    rows = trace.rows[first_session : last_session + 1]
    return PriceTraceSlice(
        first_session=first_session,
        last_session=last_session,
        baseline_nav=_ONE if before is None else before.nav,
        baseline_stock_quantity=_ZERO if before is None else before.stock_quantity,
        baseline_stock_value=_ZERO if before is None else before.stock_value,
        baseline_cash_value=_ONE if before is None else before.cash_value,
        pending_target_at_start=None if before is None else before.target,
        inherited_high_watermark=max((_ONE, *(r.nav for r in trace.rows[:first_session]))),
        rows=rows,
        pending_target=rows[-1].target,
    )
