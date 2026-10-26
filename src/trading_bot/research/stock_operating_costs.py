"""Explicit modeled cost schedules on a paused account; no observed-spend claim.

Paid charges use the existing dividend/account owner. Due unpaid charges remain
liabilities; an unknown amount makes after-cost equity unavailable. No scheduler,
billing provider, trading permission or cash transfer exists in this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import (
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
from trading_bot.domain.decimal_utils import require_bounded_decimal
from trading_bot.market_data.recording import content_hash
from trading_bot.research.stock_dividend_book import (
    DividendBook,
    DividendBookStep,
    _bind_modeled_operating_phase,
    _BookTransaction,
    _validate_current_book,
    adopt_dividend_account,
    pay_modeled_operating_expense,
)

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
_LIMITATIONS = (
    "explicit_modeled_budget_not_observed_hosting_data_or_model_spending",
    "caller_supplied_due_instants_not_an_independently_verified_billing_calendar",
    "unpaid_known_costs_are_liabilities_unknown_costs_make_net_equity_unavailable",
    "paid_costs_are_not_trading_fees_capital_gains_or_tax_deductions",
    "kernel_expense_phase_and_actual_economic_comparisons_remain_separate",
)


def _check(condition: bool) -> None:
    if not condition:
        raise ValueError("stock_operating_cost_invalid")


@dataclass(frozen=True, slots=True)
class ModeledOperatingCharge:
    id: str
    due_at: datetime
    category: Literal["hosting", "market_data", "model", "other"]
    amount_usd: Decimal | None

    def __post_init__(self) -> None:
        _check(
            type(self.id) is str
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,127}", self.id) is not None
        )
        require_utc(self.due_at)
        _check(
            type(self.category) is str
            and self.category in ("hosting", "market_data", "model", "other")
        )
        if self.amount_usd is not None:
            require_bounded_decimal(self.amount_usd, "modeled_operating_cost", nonnegative=True)


@dataclass(frozen=True, slots=True)
class ModeledOperatingCostPlan:
    label: str
    charges: tuple[ModeledOperatingCharge, ...]
    source_profile: Literal["modeled_operating_budget_v1"] = field(
        default="modeled_operating_budget_v1", init=False
    )
    observed_spending: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _check(
            type(self.label) is str
            and 0 < len(self.label) <= 256
            and self.label.isprintable()
            and type(self.charges) is tuple
            and len(self.charges) <= 10000
            and self.source_profile == "modeled_operating_budget_v1"
            and self.observed_spending is False
        )
        for charge in self.charges:
            _check(type(charge) is ModeledOperatingCharge)
            charge.__post_init__()
        _check(len({charge.id for charge in self.charges}) == len(self.charges))
        _check(self.charges == tuple(sorted(self.charges, key=lambda c: (c.due_at, c.id))))

    @property
    def evidence_hash(self) -> str:
        self.__post_init__()
        return str(content_hash(("stock-modeled-operating-plan-v1", self)))


@dataclass(frozen=True, slots=True)
class OperatingCostUpdate:
    book: DividendBook
    plan: ModeledOperatingCostPlan
    at: datetime
    paid_total: Decimal
    unpaid_known: Decimal
    unpaid_unknown_ids: tuple[str, ...]
    investable_cash: Decimal
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)

    @property
    def evidence_hash(self) -> str:
        _validate_update(self)
        return str(
            content_hash(
                (
                    "stock-operating-cost-update-v1",
                    self.book.evidence_hash,
                    self.plan.evidence_hash,
                    self.at,
                    self.paid_total,
                    self.unpaid_known,
                    self.unpaid_unknown_ids,
                    self.investable_cash,
                    _LIMITATIONS,
                )
            )
        )


def _fingerprint(plan_hash: str, charge: ModeledOperatingCharge) -> str:
    return str(content_hash(("stock-operating-charge-v1", plan_hash, charge)))


def _paid_history(
    book: DividendBook, plan: ModeledOperatingCostPlan, at: datetime
) -> dict[str, Decimal]:
    _validate_current_book(book)
    return _paid_history_validated(book, plan, at)


def _paid_history_validated(
    book: DividendBook, plan: ModeledOperatingCostPlan, at: datetime
) -> dict[str, Decimal]:
    _check(book.through_at <= at)
    plan_hash = plan.evidence_hash
    charges = {charge.id: charge for charge in plan.charges}
    ordered_ids = tuple(charge.id for charge in plan.charges)
    paid: dict[str, Decimal] = {}
    for step in book.trace:
        if step.action != "operating_expense":
            continue
        if step.event_id is None:
            raise ValueError("stock_operating_cost_invalid")
        _check(step.event_id not in paid)
        _check(len(paid) < len(ordered_ids) and step.event_id == ordered_ids[len(paid)])
        charge = charges.get(step.event_id)
        _check(charge is not None)
        if charge is None or charge.amount_usd is None:
            raise ValueError("stock_operating_cost_invalid")
        _check(
            charge.due_at <= step.at <= at
            and step.gross_amount == charge.amount_usd
            and step.event_fingerprint == _fingerprint(plan_hash, charge)
            and step.tax_reserve_added == 0
        )
        paid[step.event_id] = step.gross_amount
    return paid


def _apply_stock_operating_costs(
    book: DividendBook,
    plan: ModeledOperatingCostPlan,
    *,
    at: datetime,
    _transaction: _CostTransaction | None = None,
) -> OperatingCostUpdate:
    """Apply a frozen fictional budget oldest-first; never spend reserved money.

    An unaffordable or unknown due charge pauses later payments. The full due
    liability remains reportable and encumbered; it is not an economic zero.
    """
    with localcontext(_CONTEXT):
        _check(type(plan) is ModeledOperatingCostPlan)
        plan.__post_init__()
        require_utc(at)
        paid = (
            _paid_history(book, plan, at)
            if _transaction is None
            else _transaction._sync(book, plan, at)
        )
        current = book
        if at != book.through_at:
            current = (
                adopt_dividend_account(book, book.account, at=at)
                if _transaction is None
                else _transaction.book.adopt(book, book.account, at=at)
            )
        unpaid_known = _ZERO
        unknown: list[str] = []
        blocked = False
        plan_hash = plan.evidence_hash
        for charge in plan.charges:
            if charge.due_at > at or charge.id in paid:
                continue
            if charge.amount_usd is None:
                unknown.append(charge.id)
                blocked = True
            elif not blocked and charge.amount_usd <= current.account.buying_power:
                pay = (
                    pay_modeled_operating_expense if _transaction is None else _transaction.book.pay
                )
                current = pay(
                    current,
                    charge_id=charge.id,
                    amount_usd=charge.amount_usd,
                    charge_fingerprint=_fingerprint(plan_hash, charge),
                    at=at,
                )
                paid[charge.id] = charge.amount_usd
            else:
                unpaid_known += charge.amount_usd
                blocked = True
        result = OperatingCostUpdate(
            current,
            plan,
            at,
            sum(paid.values(), _ZERO),
            unpaid_known,
            tuple(unknown),
            _ZERO if unknown else max(_ZERO, current.account.buying_power - unpaid_known),
        )

        if _transaction is not None:
            _transaction._accept(result)
        return result


def apply_stock_operating_costs(
    book: DividendBook, plan: ModeledOperatingCostPlan, *, at: datetime
) -> OperatingCostUpdate:
    """Freshly validate the book and apply the explicit oldest-first modeled budget."""
    return _apply_stock_operating_costs(book, plan, at=at)


def _validate_update(value: OperatingCostUpdate) -> None:
    _check(
        type(value) is OperatingCostUpdate
        and value.qualified
        is value.source_qualified
        is value.strategy_qualified
        is value.investment_eligible
        is value.trading_enabled
        is value.live_authorized
        is False
        and value.limitations == _LIMITATIONS
    )
    rebuilt = apply_stock_operating_costs(value.book, value.plan, at=value.at)
    _check(value == rebuilt)


def net_equity_after_operating_costs(
    gross_marked_equity: Decimal, costs: OperatingCostUpdate
) -> Decimal | None:
    """Gross equity already reflects paid cash debits; subtract only unpaid costs."""
    with localcontext(_CONTEXT):
        require_bounded_decimal(gross_marked_equity, "gross_marked_equity", nonnegative=True)
        _validate_update(costs)
        return None if costs.unpaid_unknown_ids else gross_marked_equity - costs.unpaid_known


@dataclass(frozen=True, slots=True)
class OperatingCostPhaseBinding:
    sequence: int
    step_sha256: str
    phase_id: str
    at: datetime
    paid_total: Decimal
    unpaid_known: Decimal
    unpaid_unknown_ids: tuple[str, ...]
    investable_cash: Decimal
    update_hash: str
    mark_payload_hash: str


def _phase_hash(
    plan_hash: str,
    at: datetime,
    account_hash: str,
    previous_step_hash: str,
    paid_total: Decimal,
    unpaid_known: Decimal,
    unknown: tuple[str, ...],
    investable_cash: Decimal,
) -> str:
    return str(
        content_hash(
            (
                "stock-operating-phase-update-v1",
                plan_hash,
                at,
                account_hash,
                previous_step_hash,
                paid_total,
                unpaid_known,
                unknown,
                investable_cash,
            )
        )
    )


def stock_operating_phase_hash(costs: OperatingCostUpdate) -> str:
    """Compact current summary bound to owned account/trace identities, not a Book copy."""
    with localcontext(_CONTEXT):
        _validate_update(costs)
        last = costs.book.trace[-1]
        return _phase_hash(
            costs.plan.evidence_hash,
            costs.at,
            last.account_after_hash,
            last.evidence_hash,
            costs.paid_total,
            costs.unpaid_known,
            costs.unpaid_unknown_ids,
            costs.investable_cash,
        )


def _phase_commitment(plan_hash: str, phase_id: str, update_hash: str, payload_hash: str) -> str:
    return str(
        content_hash(
            (
                "stock-operating-owned-phase-v1",
                plan_hash,
                phase_id,
                update_hash,
                payload_hash,
            )
        )
    )


def bind_stock_operating_phase(
    costs: OperatingCostUpdate, *, phase_id: str, update_hash: str, mark_payload_hash: str
) -> tuple[DividendBook, int, str]:
    """Commit an observed kernel payload only after fresh cost-owner summary validation."""
    with localcontext(_CONTEXT):
        _check(update_hash == stock_operating_phase_hash(costs))
        from trading_bot.domain.decimal_utils import _require_sha256_hex

        _require_sha256_hex(mark_payload_hash, "operating_cost_mark_payload")
        book, step = _bind_modeled_operating_phase(
            costs.book,
            phase_id=phase_id,
            at=costs.at,
            fingerprint=_phase_commitment(
                costs.plan.evidence_hash, phase_id, update_hash, mark_payload_hash
            ),
        )
        return book, step.sequence, step.evidence_hash


def _validate_phase_bindings_validated(
    book: DividendBook,
    plan: ModeledOperatingCostPlan,
    bindings: tuple[OperatingCostPhaseBinding, ...],
) -> dict[str, Decimal]:
    """Check all cost rows against a caller-owned already checked generic book."""
    with localcontext(_CONTEXT):
        _check(book.through_at >= book.account_at)
        _check(
            type(bindings) is tuple
            and all(type(item) is OperatingCostPhaseBinding for item in bindings)
        )
        plan_hash = plan.evidence_hash
        paid: dict[str, Decimal] = {}
        cursor = 0
        for step in book.trace:
            if step.action == "operating_expense":
                if step.event_id is None:
                    raise ValueError("stock_operating_cost_invalid")
                _checked_paid_step(step, plan, plan_hash, paid, book.through_at)
            elif step.action == "operating_cost_phase":
                _check(cursor < len(bindings))
                binding = bindings[cursor]
                _check(binding.sequence == step.sequence)
                cursor += 1
                unknown = tuple(
                    item.id
                    for item in plan.charges
                    if item.due_at <= step.at and item.id not in paid and item.amount_usd is None
                )
                unpaid = sum(
                    (
                        item.amount_usd
                        for item in plan.charges
                        if item.due_at <= step.at
                        and item.id not in paid
                        and item.amount_usd is not None
                    ),
                    _ZERO,
                )
                total = sum(paid.values(), _ZERO)
                _check(
                    binding.step_sha256 == step.evidence_hash
                    and binding.phase_id == step.event_id
                    and binding.at == step.at
                    and step.account_before_hash == step.account_after_hash
                    and step.orders_before_hash == step.orders_after_hash
                    and step.gross_amount == step.tax_reserve_added == 0
                    and binding.paid_total == total
                    and binding.unpaid_known == unpaid
                    and binding.unpaid_unknown_ids == unknown
                )
                _check(step.previous_step_hash is not None)
                if step.previous_step_hash is None:
                    raise ValueError("stock_operating_cost_invalid")
                compact = _phase_hash(
                    plan_hash,
                    step.at,
                    step.account_before_hash,
                    step.previous_step_hash,
                    total,
                    unpaid,
                    unknown,
                    binding.investable_cash,
                )
                _check(
                    binding.update_hash == compact
                    and step.event_fingerprint
                    == _phase_commitment(
                        plan_hash, binding.phase_id, compact, binding.mark_payload_hash
                    )
                )

        _check(cursor == len(bindings))
        return paid


def _checked_paid_step(
    step: DividendBookStep,
    plan: ModeledOperatingCostPlan,
    plan_hash: str,
    paid: dict[str, Decimal],
    at: datetime,
) -> None:
    _check(step.event_id is not None and step.event_id not in paid)
    _check(len(paid) < len(plan.charges))
    charge = plan.charges[len(paid)]
    _check(
        charge.id == step.event_id
        and charge.amount_usd is not None
        and charge.due_at <= step.at <= at
        and step.gross_amount == charge.amount_usd
        and step.event_fingerprint == _fingerprint(plan_hash, charge)
        and step.tax_reserve_added == 0
    )
    paid[charge.id] = step.gross_amount


def validate_stock_operating_phase_bindings(
    book: DividendBook,
    plan: ModeledOperatingCostPlan,
    bindings: tuple[OperatingCostPhaseBinding, ...],
) -> None:
    """Fresh standalone validation of the complete book and every owned cost phase."""
    _validate_current_book(book)
    plan.__post_init__()
    _validate_phase_bindings_validated(book, plan, bindings)


class _CostTransaction:
    """Invocation-local payment history subordinate to one checked book owner."""

    __slots__ = ("_cursor", "_paid", "_summary", "_summary_values", "book", "plan", "plan_hash")

    def __init__(
        self,
        book: _BookTransaction,
        plan: ModeledOperatingCostPlan,
        paid: dict[str, Decimal],
    ) -> None:
        book._require(book.current)
        plan.__post_init__()
        self.book = book
        self.plan = plan
        self.plan_hash = plan.evidence_hash
        self._paid = dict(paid)
        self._cursor = len(book.current.trace)
        self._summary: OperatingCostUpdate | None = None
        self._summary_values: tuple[object, ...] | None = None

    def _sync(
        self, book: DividendBook, plan: ModeledOperatingCostPlan, at: datetime
    ) -> dict[str, Decimal]:
        self.book._require(book)
        _check(plan is self.plan and plan.evidence_hash == self.plan_hash and book.through_at <= at)
        for step in book.trace[self._cursor :]:
            if step.action == "operating_expense":
                _checked_paid_step(step, plan, self.plan_hash, self._paid, at)
        self._cursor = len(book.trace)
        self._summary = None
        self._summary_values = None
        return dict(self._paid)

    @staticmethod
    def _values(value: OperatingCostUpdate) -> tuple[object, ...]:
        return (
            value.at,
            value.paid_total,
            value.unpaid_known,
            value.unpaid_unknown_ids,
            value.investable_cash,
            value.qualified,
            value.source_qualified,
            value.strategy_qualified,
            value.investment_eligible,
            value.trading_enabled,
            value.live_authorized,
            value.limitations,
        )

    def _accept(self, value: OperatingCostUpdate) -> None:
        _check(type(value) is OperatingCostUpdate)
        require_utc(value.at)
        _check(value.at == value.book.through_at)
        self._sync(value.book, value.plan, value.at)
        due = tuple(
            item
            for item in self.plan.charges
            if item.due_at <= value.at and item.id not in self._paid
        )
        if due:
            oldest_amount = due[0].amount_usd
            _check(oldest_amount is None or oldest_amount > value.book.account.buying_power)
        unknown = tuple(item.id for item in due if item.amount_usd is None)
        unpaid = sum((item.amount_usd for item in due if item.amount_usd is not None), _ZERO)
        _check(
            value.paid_total == sum(self._paid.values(), _ZERO)
            and value.unpaid_known == unpaid
            and value.unpaid_unknown_ids == unknown
            and value.investable_cash
            == (_ZERO if unknown else max(_ZERO, value.book.account.buying_power - unpaid))
            and value.qualified
            is value.source_qualified
            is value.strategy_qualified
            is value.investment_eligible
            is value.trading_enabled
            is value.live_authorized
            is False
            and value.limitations == _LIMITATIONS
        )
        self._summary = value
        self._summary_values = self._values(value)

    def _require(self, value: OperatingCostUpdate) -> None:
        self.book._require(value.book)
        require_utc(value.at)
        _check(
            value is self._summary
            and value.plan is self.plan
            and value.at == value.book.through_at
            and self.plan.evidence_hash == self.plan_hash
            and self._values(value) == self._summary_values
        )

    def apply(self, book: DividendBook, *, at: datetime) -> OperatingCostUpdate:
        return _apply_stock_operating_costs(book, self.plan, at=at, _transaction=self)

    def net(self, gross: Decimal, value: OperatingCostUpdate) -> Decimal | None:
        self._require(value)
        require_bounded_decimal(gross, "gross_marked_equity", nonnegative=True)
        return None if value.unpaid_unknown_ids else gross - value.unpaid_known

    def phase_hash(self, value: OperatingCostUpdate) -> str:
        self._require(value)
        last = value.book.trace[-1]
        return _phase_hash(
            self.plan_hash,
            value.at,
            last.account_after_hash,
            last.evidence_hash,
            value.paid_total,
            value.unpaid_known,
            value.unpaid_unknown_ids,
            value.investable_cash,
        )

    def bind(
        self,
        value: OperatingCostUpdate,
        *,
        phase_id: str,
        update_hash: str,
        mark_payload_hash: str,
    ) -> tuple[DividendBook, int, str]:
        _check(update_hash == self.phase_hash(value))
        from trading_bot.domain.decimal_utils import _require_sha256_hex

        _require_sha256_hex(mark_payload_hash, "operating_cost_mark_payload")
        book, step = self.book.bind(
            value.book,
            phase_id=phase_id,
            at=value.at,
            fingerprint=_phase_commitment(self.plan_hash, phase_id, update_hash, mark_payload_hash),
        )
        self._summary = None
        self._summary_values = None
        return book, step.sequence, step.evidence_hash
