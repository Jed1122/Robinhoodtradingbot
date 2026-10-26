"""Retrospective dividend reconstruction in an isolated experimental account.

Earned rights bind a prior-session ownership snapshot. Date-only native payment
dates never supply early cash: a caller-bound known calendar determines the later
modeled availability. No broker transport, quote, order creation or trading
authorization exists here. External account adoption is a caller-supplied modeled
transition, not an independently verified execution or reconciliation.
"""

from __future__ import annotations

import re
from dataclasses import MISSING, dataclass, field, fields, replace
from datetime import datetime, timedelta
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
from fractions import Fraction
from typing import Literal
from zoneinfo import ZoneInfo

from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.hybrid.models import Account, AllocationEpisode, FillFact, PaperOrder
from trading_bot.market_data.recording import content_hash
from trading_bot.market_data.stock_economic_evidence import (
    CashDividendAccrual,
    StockCashDividendEvent,
    dividend_entitlement,
)
from trading_bot.research.hybrid_policies import CalendarSession

_NY = ZoneInfo("America/New_York")
_ZERO, _ONE = Decimal(0), Decimal(1)
_MAX_EVENTS = 10000
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
    "retrospective_cash_reconstruction_not_point_in_time_signal_or_actual_broker_booking",
    "caller_bound_calendar_and_source_hashes_do_not_authenticate_origin_or_completeness",
    "recurring_distributions_only_no_due_bill_or_other_corporate_action_semantics",
    "native_date_accrual_cash_field_does_not_determine_modeled_book_availability",
    "flat_paid_cash_tax_scenario_not_qualified_dividend_or_final_tax_reporting",
    "external_account_adoption_is_caller_modeled_not_independently_verified_fills",
    "full_replay_must_rebuild_external_transitions_from_the_prior_experimental_account",
)


class DividendBookError(ValueError):
    """A stable contract failure in the research-only ledger."""


def _check(condition: bool, reason: str) -> None:
    if not condition:
        raise DividendBookError(reason)


def _utc(value: datetime) -> None:
    _check(
        type(value) is datetime and value.tzinfo is not None and value.utcoffset() == timedelta(0),
        "utc_datetime_required",
    )


def _hash(value: object) -> str:
    return str(content_hash(value))


def _account_hash(account: Account) -> str:
    return _hash(("dividend-experimental-account-v1", account.model_dump()))


def _orders_hash(account: Account) -> str:
    return _hash(
        ("dividend-owned-orders-v1", tuple(order.model_dump() for order in account.orders))
    )


def _lots_hash(account: Account) -> str:
    return _hash(("dividend-owned-lots-v1", tuple(lot.model_dump() for lot in account.lots)))


def _event_hash(event: StockCashDividendEvent) -> str:
    return _hash(("dividend-original-event-v1", event))


@dataclass(frozen=True, slots=True)
class DividendEntitlement:
    event: StockCashDividendEvent
    event_fingerprint: str
    snapshot_at: datetime
    ex_opens_at: datetime
    modeled_pay_available_at: datetime | None
    snapshot_account_hash: str
    snapshot_owned_lots_hash: str
    snapshot_lot_ids: tuple[str, ...]
    accrual: CashDividendAccrual


@dataclass(frozen=True, slots=True)
class DividendBookStep:
    sequence: int
    action: Literal[
        "initialize",
        "accrue",
        "credit",
        "advance",
        "adopt_account",
        "operating_expense",
        "operating_cost_phase",
    ]
    at: datetime
    event_id: str | None
    event_fingerprint: str | None
    snapshot_owned_lots_hash: str | None
    account_before_hash: str
    account_after_hash: str
    orders_before_hash: str
    orders_after_hash: str
    gross_amount: Decimal
    tax_reserve_added: Decimal
    previous_step_hash: str | None

    @property
    def evidence_hash(self) -> str:
        return _hash(("dividend-book-step-v1", self))


@dataclass(frozen=True, slots=True, init=False)
class DividendBook:
    account: Account
    entitlements: tuple[DividendEntitlement, ...]
    credited_events: tuple[str, ...]
    tax_rate: Decimal | None
    account_at: datetime
    through_at: datetime
    sessions: tuple[CalendarSession, ...]
    calendar_source_hash: str
    trace: tuple[DividendBookStep, ...]
    arithmetic_precision: Literal[50] = field(default=50, init=False)
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("DividendBook must be created by create_dividend_book")

    @property
    def gross_earned(self) -> Decimal:
        with localcontext(_CONTEXT):
            return sum((item.accrual.accrued_amount for item in self.entitlements), _ZERO)

    @property
    def gross_paid(self) -> Decimal:
        with localcontext(_CONTEXT):
            return sum((step.gross_amount for step in self.trace if step.action == "credit"), _ZERO)

    @property
    def dividend_tax_reserved(self) -> Decimal:
        with localcontext(_CONTEXT):
            return sum((step.tax_reserve_added for step in self.trace), _ZERO)

    @property
    def evidence_hash(self) -> str:
        return _hash(
            (
                "stock-dividend-book-v1",
                self.account.model_dump(),
                self.entitlements,
                self.credited_events,
                self.tax_rate,
                self.account_at,
                self.through_at,
                self.sessions,
                self.calendar_source_hash,
                self.trace,
                self.arithmetic_precision,
                self.qualified,
                self.source_qualified,
                self.investment_eligible,
                self.trading_enabled,
                self.live_authorized,
                self.limitations,
            )
        )


def _account(value: Account, at: datetime) -> Account:
    _check(type(value) is Account, "experimental_account_required")
    try:
        validated = Account.model_validate(value.model_dump())
    except (ValueError, TypeError):
        raise DividendBookError("invalid_experimental_account") from None
    _check(validated.paused is True, "experimental_account_must_remain_paused")
    _check(all(lot.acquired_at <= at for lot in validated.lots), "future_snapshot_acquisition")
    _check(all(fill.at <= at for fill in validated.fills), "future_account_fill")
    return validated


def _calendar(sessions: tuple[CalendarSession, ...], source_hash: str) -> None:
    _require_sha256_hex(source_hash, "calendar_source_hash")
    _check(
        type(sessions) is tuple and 2 <= len(sessions) <= 10000,
        "bounded_immutable_known_calendar_required",
    )
    previous = None
    for session in sessions:
        _check(type(session) is CalendarSession, "known_calendar_session_required")
        _utc(session.opens_at)
        _utc(session.closes_at)
        _check(
            type(session.index) is int
            and session.index >= 0
            and session.opens_at < session.closes_at
            and session.opens_at.astimezone(_NY).date() == session.closes_at.astimezone(_NY).date(),
            "invalid_known_calendar_session",
        )
        if previous is not None:
            _check(
                previous.index + 1 == session.index
                and previous.closes_at < session.opens_at
                and previous.closes_at.astimezone(_NY).date()
                < session.opens_at.astimezone(_NY).date(),
                "calendar_order_or_overlap",
            )
        previous = session


def _validate_book(book: DividendBook) -> Decimal:
    _check(type(book) is DividendBook, "factory_dividend_book_required")
    _check(
        book.qualified
        is book.source_qualified
        is book.investment_eligible
        is book.trading_enabled
        is book.live_authorized
        is False,
        "nonpromotion_scope_required",
    )
    _check(
        book.arithmetic_precision == 50 and book.limitations == _LIMITATIONS,
        "frozen_dividend_scope_required",
    )
    _utc(book.account_at)
    _utc(book.through_at)
    _check(book.account_at <= book.through_at, "account_clock_ahead_of_book")
    _account(book.account, book.account_at)
    _calendar(book.sessions, book.calendar_source_hash)
    if book.tax_rate is not None:
        require_bounded_decimal(book.tax_rate, "tax_rate", nonnegative=True)
        _check(book.tax_rate <= 1, "tax_rate_out_of_range")
    _check(
        type(book.entitlements) is tuple and len(book.entitlements) <= _MAX_EVENTS,
        "dividend_event_limit_or_mutability",
    )
    ids = tuple(item.event.id for item in book.entitlements)
    economics = tuple((item.event.symbol, item.event.ex_date) for item in book.entitlements)
    _check(
        len(set(ids)) == len(ids) and len(set(economics)) == len(economics),
        "conflicting_book_events",
    )
    _check(
        type(book.credited_events) is tuple
        and len(set(book.credited_events)) == len(book.credited_events)
        and set(book.credited_events) <= set(ids),
        "invalid_credited_event_history",
    )
    _check(type(book.trace) is tuple and bool(book.trace), "immutable_dividend_trace_required")
    previous = None
    for index, step in enumerate(book.trace):
        _check(type(step) is DividendBookStep and step.sequence == index, "invalid_trace_sequence")
        _utc(step.at)
        _check(
            step.previous_step_hash == (None if previous is None else previous.evidence_hash),
            "invalid_trace_hash_chain",
        )
        if previous is not None:
            _check(
                step.at >= previous.at and step.account_before_hash == previous.account_after_hash,
                "trace_clock_or_account_rewind",
            )
        previous = step
    _check(
        book.trace[-1].at == book.through_at
        and book.trace[-1].account_after_hash == _account_hash(book.account),
        "account_state_not_bound_to_trace",
    )
    credit_ids = tuple(step.event_id for step in book.trace if step.action == "credit")
    _check(credit_ids == book.credited_events, "forgotten_credited_income_history")
    retained_tax = book.dividend_tax_reserved
    _check(book.account.tax_reserve >= retained_tax, "retained_dividend_tax_reserve_lost")
    return retained_tax


def _make_book(
    account: Account,
    entitlements: tuple[DividendEntitlement, ...],
    credited_events: tuple[str, ...],
    tax_rate: Decimal | None,
    account_at: datetime,
    through_at: datetime,
    sessions: tuple[CalendarSession, ...],
    calendar_source_hash: str,
    trace: tuple[DividendBookStep, ...] | _OwnedBookAppend,
    *,
    _transaction: _BookTransaction | None = None,
) -> DividendBook:
    if _transaction is not None:
        _check(type(trace) is _OwnedBookAppend, "owned_trace_append_required")
        if not isinstance(trace, _OwnedBookAppend):
            raise DividendBookError("owned_trace_append_required")
        _transaction._require(_transaction.current)
        _check(trace.prefix is _transaction.current.trace, "owned_dividend_prefix_changed")
        # Build the unchanged prefix here, rather than accepting a caller-made
        # replacement or rescanning the complete prefix on every retained append.
        trace = (*trace.prefix, trace.step)
    value = object.__new__(DividendBook)
    supplied = {
        "account": account,
        "entitlements": entitlements,
        "credited_events": credited_events,
        "tax_rate": tax_rate,
        "account_at": account_at,
        "through_at": through_at,
        "sessions": sessions,
        "calendar_source_hash": calendar_source_hash,
        "trace": trace,
    }
    for item in fields(DividendBook):
        content = supplied.get(item.name, item.default)
        if content is MISSING:
            raise TypeError("missing internal dividend book field")
        object.__setattr__(value, item.name, content)
    if _transaction is None:
        _validate_book(value)
    else:
        _transaction._accept(value)
    return value


def _step(
    book: DividendBook | None,
    action: Literal[
        "initialize",
        "accrue",
        "credit",
        "advance",
        "adopt_account",
        "operating_expense",
        "operating_cost_phase",
    ],
    at: datetime,
    before: Account,
    after: Account,
    *,
    entitlement: DividendEntitlement | None = None,
    gross_amount: Decimal = _ZERO,
    tax_reserve_added: Decimal = _ZERO,
) -> DividendBookStep:
    return DividendBookStep(
        0 if book is None else len(book.trace),
        action,
        at,
        None if entitlement is None else entitlement.event.id,
        None if entitlement is None else entitlement.event_fingerprint,
        _lots_hash(before) if entitlement is None else entitlement.snapshot_owned_lots_hash,
        _account_hash(before),
        _account_hash(after),
        _orders_hash(before),
        _orders_hash(after),
        gross_amount,
        tax_reserve_added,
        None if book is None else book.trace[-1].evidence_hash,
    )


def create_dividend_book(
    account: Account,
    *,
    account_at: datetime,
    sessions: tuple[CalendarSession, ...],
    calendar_source_hash: str,
    tax_rate: Decimal | None = None,
) -> DividendBook:
    """Bind a caller-supplied experimental account and known calendar; never authenticate either."""
    with localcontext(_CONTEXT):
        _utc(account_at)
        _calendar(sessions, calendar_source_hash)
        validated = _account(account, account_at)
        initial = _step(None, "initialize", account_at, validated, validated)
        return _make_book(
            validated,
            (),
            (),
            tax_rate,
            account_at,
            account_at,
            sessions,
            calendar_source_hash,
            (initial,),
        )


def _boundaries(
    book: DividendBook,
    event: StockCashDividendEvent,
    snapshot_at: datetime,
    ex_opens_at: datetime,
    modeled_pay_available_at: datetime | None,
) -> None:
    _utc(snapshot_at)
    _utc(ex_opens_at)
    index = next(
        (i for i, session in enumerate(book.sessions) if session.opens_at == ex_opens_at), -1
    )
    _check(
        index > 0 and ex_opens_at.astimezone(_NY).date() == event.ex_date,
        "native_ex_date_requires_known_open_and_prior_session",
    )
    _check(
        snapshot_at == book.sessions[index - 1].closes_at
        and snapshot_at < ex_opens_at
        and snapshot_at.astimezone(_NY).date() < event.ex_date,
        "prior_session_close_snapshot_required",
    )
    if modeled_pay_available_at is not None:
        _utc(modeled_pay_available_at)
        _check(event.pay_date is not None, "unknown_pay_date_cannot_have_modeled_availability")
        # Above check establishes a date, while retaining the native optional field unchanged.
        pay_date = event.pay_date
        if pay_date is None:
            raise DividendBookError("unknown_payment_date")
        candidates = tuple(
            session
            for session in book.sessions
            if session.opens_at.astimezone(_NY).date() > pay_date
        )
        _check(
            book.sessions[0].opens_at.astimezone(_NY).date() <= pay_date
            and bool(candidates)
            and modeled_pay_available_at == candidates[0].opens_at,
            "payment_requires_first_known_open_strictly_after_native_date",
        )


def _owned_record_dividend_entitlement(
    book: DividendBook,
    event: StockCashDividendEvent,
    *,
    snapshot_at: datetime,
    ex_opens_at: datetime,
    modeled_pay_available_at: datetime | None,
    _transaction: _BookTransaction | None = None,
) -> DividendBook:
    """Accrue once at the ex open from a locked prior-close ownership snapshot.

    An exact recorded call stays idempotent after later account adoption or credit;
    it never re-derives an earned right from pay-date holdings. Source receipt time
    remains the event's actual retained timestamp, including retrospective receipt.
    """
    with localcontext(_CONTEXT):
        _require_current(book, _transaction)
        _check(type(event) is StockCashDividendEvent, "native_cash_dividend_event_required")
        event.__post_init__()
        _check(event.distribution_type == "recurring", "unsupported_due_bill_distribution")
        _boundaries(book, event, snapshot_at, ex_opens_at, modeled_pay_available_at)
        fingerprint = _event_hash(event)
        existing = next((item for item in book.entitlements if item.event.id == event.id), None)
        if existing is not None:
            _check(
                existing.event_fingerprint == fingerprint
                and existing.snapshot_at == snapshot_at
                and existing.ex_opens_at == ex_opens_at
                and existing.modeled_pay_available_at == modeled_pay_available_at,
                "conflicting_native_event_or_snapshot",
            )
            return book
        _check(len(book.entitlements) < _MAX_EVENTS, "dividend_event_limit")
        _check(
            not any(
                (item.event.symbol, item.event.ex_date) == (event.symbol, event.ex_date)
                for item in book.entitlements
            ),
            "duplicate_or_conflicting_economic_event",
        )
        _check(ex_opens_at >= book.through_at, "dividend_clock_rewind")
        _check(snapshot_at == book.account_at, "snapshot_not_bound_to_current_owned_account")
        _check(
            all(lot.acquired_at <= snapshot_at for lot in book.account.lots),
            "future_snapshot_acquisition",
        )
        shares = sum(
            (lot.quantity for lot in book.account.lots if lot.symbol == event.symbol), _ZERO
        )
        accrual = dividend_entitlement(
            event,
            shares_before_ex=shares,
            held_at=snapshot_at.astimezone(_NY).date(),
            as_of=event.ex_date,
        )
        item = DividendEntitlement(
            event,
            fingerprint,
            snapshot_at,
            ex_opens_at,
            modeled_pay_available_at,
            _account_hash(book.account),
            _lots_hash(book.account),
            tuple(lot.id for lot in book.account.lots),
            accrual,
        )
        step = _step(
            book,
            "accrue",
            ex_opens_at,
            book.account,
            book.account,
            entitlement=item,
            gross_amount=accrual.accrued_amount,
        )
        return _make_book(
            book.account,
            (*book.entitlements, item),
            book.credited_events,
            book.tax_rate,
            book.account_at,
            ex_opens_at,
            book.sessions,
            book.calendar_source_hash,
            _append_trace(book, step, _transaction),
            _transaction=_transaction,
        )


def _owned_credit_due_dividends(
    book: DividendBook,
    *,
    at: datetime,
    _transaction: _BookTransaction | None = None,
) -> DividendBook:
    """Credit each known modeled payment once; unknown tax reserves100% of paid cash."""
    with localcontext(_CONTEXT):
        _require_current(book, _transaction)
        _utc(at)
        _check(at >= book.through_at, "dividend_clock_rewind")
        due = sorted(
            (
                item
                for item in book.entitlements
                if item.event.id not in book.credited_events
                and item.modeled_pay_available_at is not None
                and item.modeled_pay_available_at <= at
            ),
            key=lambda item: (item.modeled_pay_available_at or at, item.event.id),
        )
        if not due:
            if at == book.through_at:
                return book
            step = _step(book, "advance", at, book.account, book.account)
            return _make_book(
                book.account,
                book.entitlements,
                book.credited_events,
                book.tax_rate,
                book.account_at,
                at,
                book.sessions,
                book.calendar_source_hash,
                _append_trace(book, step, _transaction),
                _transaction=_transaction,
            )
        result = book
        for item in due:
            gross = item.accrual.accrued_amount
            tax = gross * (_ONE if result.tax_rate is None else result.tax_rate)
            updated = Account.model_validate(
                result.account.model_dump()
                | {
                    "cash": result.account.cash + gross,
                    "tax_reserve": result.account.tax_reserve + tax,
                }
            )
            step = _step(
                result,
                "credit",
                at,
                result.account,
                updated,
                entitlement=item,
                gross_amount=gross,
                tax_reserve_added=tax,
            )
            result = _make_book(
                updated,
                result.entitlements,
                (*result.credited_events, item.event.id),
                result.tax_rate,
                at,
                at,
                result.sessions,
                result.calendar_source_hash,
                _append_trace(result, step, _transaction),
                _transaction=_transaction,
            )
        return result


def _owned_receivable_value(
    book: DividendBook,
    *,
    at: datetime,
    _transaction: _BookTransaction | None = None,
) -> Decimal:
    """Query the recorded gross receivable at a historical time, never future cash."""
    with localcontext(_CONTEXT):
        _require_current(book, _transaction)
        _utc(at)
        _check(at <= book.through_at, "valuation_ahead_of_book_clock")
        credited = (
            _transaction._credited
            if _transaction is not None and at == book.through_at
            else {step.event_id for step in book.trace if step.action == "credit" and step.at <= at}
        )
        return sum(
            (
                item.accrual.accrued_amount
                for item in book.entitlements
                if item.ex_opens_at <= at and item.event.id not in credited
            ),
            _ZERO,
        )


def _allocation_history(
    old: Account,
    proposed: Account,
    appended: tuple[FillFact, ...],
    orders: dict[str, PaperOrder],
) -> None:
    """Retain original contributions and partial rungs across owned transitions."""
    next_progress = {item.threshold: item for item in proposed.exit_progress}
    for before in old.exit_progress:
        after = next_progress.get(before.threshold)
        if after is None:
            raise DividendBookError("partial_exit_history_lost")
        fills = tuple(
            item for item in appended if orders[item.order_id].threshold == before.threshold
        )
        _check(
            after.symbol == before.symbol
            and after.sleeve == before.sleeve
            and after.target == before.target
            and all(
                orders[item.order_id].side == "sell"
                and orders[item.order_id].symbol == before.symbol
                and orders[item.order_id].sleeve == before.sleeve
                for item in fills
            )
            and after.filled == before.filled + sum((item.quantity for item in fills), _ZERO),
            "partial_exit_history_not_bound_to_owned_fills",
        )

    expected = {item.id: item for item in old.episodes}
    for fill in appended:
        order = orders[fill.order_id]
        if order.side != "buy":
            continue
        episode_id = order.episode_id or order.id
        before_episode = expected.get(episode_id)
        _check(
            before_episode is None
            or (before_episode.symbol == order.symbol and before_episode.sleeve == order.sleeve),
            "original_allocation_identity_rewritten",
        )
        expected[episode_id] = AllocationEpisode(
            id=episode_id,
            symbol=order.symbol,
            sleeve=order.sleeve,
            original_cash=(
                (fill.quantity * fill.price + fill.fee)
                + (_ZERO if before_episode is None else before_episode.original_cash)
            ),
            original_quantity=(
                (_ZERO if before_episode is None else before_episode.original_quantity)
                + fill.quantity
            ),
        )
    _check(
        {item.id: item for item in proposed.episodes} == expected,
        "original_allocation_not_bound_to_owned_buy_fills",
    )


def _adoption_history(book: DividendBook, proposed: Account, at: datetime) -> None:
    _adoption_history_values(book, proposed, at, book.dividend_tax_reserved)


def _adoption_history_values(
    book: DividendBook, proposed: Account, at: datetime, retained_dividend_tax: Decimal
) -> None:
    old = book.account
    _check(proposed.starting_capital == old.starting_capital, "starting_capital_rewind")
    _check(not old.kill_switch or proposed.kill_switch, "sticky_safety_state_cannot_clear")
    _check(
        not old.tactical_suspended or proposed.tactical_suspended,
        "sticky_safety_state_cannot_clear",
    )
    _check(
        not old.weekly_review_required or proposed.weekly_review_required,
        "sticky_safety_state_cannot_clear",
    )
    _check(
        proposed.high_watermark >= old.high_watermark and proposed.fees >= old.fees,
        "monotonic_account_history_lost",
    )
    _check(proposed.tax_reserve >= retained_dividend_tax, "retained_dividend_tax_reserve_lost")
    _check(proposed.tax_reserve >= old.tax_reserve, "prior_tax_reserve_cannot_release")
    old_fills = {item.id: item for item in old.fills}
    new_fills = {item.id: item for item in proposed.fills}
    _check(
        all(new_fills.get(key) == value for key, value in old_fills.items()),
        "prior_fill_history_lost",
    )
    appended = tuple(value for key, value in new_fills.items() if key not in old_fills)
    _check(all(book.through_at <= item.at <= at for item in appended), "external_fill_clock_rewind")
    old_orders = {item.id: item for item in old.orders}
    new_orders = {item.id: item for item in proposed.orders}
    _check(all(key in new_orders for key in old_orders), "prior_owned_order_lost")
    _check(
        all(item.order_id in new_orders for item in appended), "external_fill_without_owned_order"
    )
    quantities: dict[str, Decimal] = {}
    for order_fill in appended:
        quantities[order_fill.order_id] = (
            quantities.get(order_fill.order_id, _ZERO) + order_fill.quantity
        )
    for key, before in old_orders.items():
        after = new_orders[key]
        mutable = {"filled", "reserved_cash", "status"}
        _check(
            before.model_dump(exclude=mutable) == after.model_dump(exclude=mutable)
            and after.filled >= before.filled,
            "prior_order_rewritten_or_fill_rewind",
        )
        _check(
            after.filled == before.filled + quantities.get(key, _ZERO),
            "filled_quantity_not_bound_to_owned_appended_fills",
        )
        if after.status in {"open", "partial"} and after.filled == before.filled:
            _check(
                after.reserved_cash == before.reserved_cash,
                "active_order_reservation_changed_without_fill",
            )
        if before.status in {"filled", "cancelled", "rejected"}:
            _check(after == before, "terminal_order_history_reopened")
    _check(
        set(old.completed_thresholds) <= set(proposed.completed_thresholds),
        "exit_threshold_history_lost",
    )
    _allocation_history(old, proposed, appended, new_orders)
    old_settlements = {item.id: item for item in old.settlements}
    new_settlements = {item.id: item for item in proposed.settlements}
    appended_by_id = {item.id: item for item in appended}
    for key, claim in new_settlements.items():
        if key in old_settlements:
            continue
        fill = appended_by_id.get(key)
        if fill is None:
            raise DividendBookError("new_settlement_without_causal_appended_fill")
        # Match the pure fill_order ledger: each sale receipt is keyed by that
        # exact fill ID, net of its fee, and settles strictly after execution.
        _check(new_orders[fill.order_id].side == "sell", "settlement_requires_owned_sell_order")
        _check(
            claim.amount == fill.quantity * fill.price - fill.fee and claim.due_at > fill.at,
            "settlement_amount_or_due_time_not_bound_to_fill",
        )
    cleared = []
    for key, prior_settlement in old_settlements.items():
        if key in new_settlements:
            _check(new_settlements[key] == prior_settlement, "settlement_history_rewritten")
        else:
            _check(prior_settlement.due_at <= at, "unsettled_receipt_removed_early")
            cleared.append(prior_settlement.amount)
    if not appended:
        _check(
            proposed.lots == old.lots
            and proposed.realized_gain == old.realized_gain
            and proposed.fees == old.fees,
            "external_economic_change_without_modeled_fill",
        )
        _check(
            all(new_orders[key].filled == value.filled for key, value in old_orders.items()),
            "filled_quantity_change_without_modeled_fill",
        )
        _check(
            proposed.cash == old.cash + sum(cleared, _ZERO),
            "unattributed_cash_or_credited_income_lost",
        )


def _owned_adopt_dividend_account(
    book: DividendBook,
    account: Account,
    *,
    at: datetime,
    _transaction: _BookTransaction | None = None,
) -> DividendBook:
    """Adopt a caller-modeled account transition without recomputing earned rights.

    Rewind guards do not independently verify external execution/basis/cash math.
    The full replay must produce the proposed state through owned ledger operations
    from ``book.account``; external text/LLM output is never such an authority.
    """
    with localcontext(_CONTEXT):
        _require_current(book, _transaction)
        _utc(at)
        _check(at >= book.through_at, "dividend_clock_rewind")
        proposed = _account(account, at)
        if _transaction is None:
            _adoption_history(book, proposed, at)
        step = _step(book, "adopt_account", at, book.account, proposed)
        return _make_book(
            proposed,
            book.entitlements,
            book.credited_events,
            book.tax_rate,
            at,
            at,
            book.sessions,
            book.calendar_source_hash,
            _append_trace(book, step, _transaction),
            _transaction=_transaction,
        )


def _owned_pay_modeled_operating_expense(
    book: DividendBook,
    *,
    charge_id: str,
    amount_usd: Decimal,
    charge_fingerprint: str,
    at: datetime,
    _transaction: _BookTransaction | None = None,
) -> DividendBook:
    """Debit a labeled model cost through the paused book, never a brokerage payment.

    The cost-plan owner binds due dates and liabilities separately. This narrow
    transition cannot spend order/tax reserves or reclassify a cost as a fill,
    gain, tax or execution fee. Repeating the same charge is idempotent.
    """
    with localcontext(_CONTEXT):
        _require_current(book, _transaction)
        _utc(at)
        _check(at >= book.through_at, "operating_expense_clock_rewind")
        _check(
            type(charge_id) is str
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,127}", charge_id) is not None,
            "invalid_operating_expense_identity",
        )
        require_bounded_decimal(amount_usd, "operating_expense", nonnegative=True)
        _require_sha256_hex(charge_fingerprint, "operating_expense_fingerprint")
        existing = tuple(
            step
            for step in book.trace
            if step.action == "operating_expense" and step.event_id == charge_id
        )
        if existing:
            _check(
                len(existing) == 1
                and existing[0].gross_amount == amount_usd
                and existing[0].event_fingerprint == charge_fingerprint,
                "conflicting_operating_expense_history",
            )
            return book
        _check(amount_usd <= book.account.buying_power, "unfunded_operating_expense")
        cash_after = book.account.cash - amount_usd
        _check(
            Fraction(book.account.cash) - Fraction(cash_after) == Fraction(amount_usd),
            "operating_expense_debit_not_exactly_representable",
        )
        updated = _account(
            Account.model_validate(book.account.model_dump() | {"cash": cash_after}),
            at,
        )
        step = replace(
            _step(book, "operating_expense", at, book.account, updated, gross_amount=amount_usd),
            event_id=charge_id,
            event_fingerprint=charge_fingerprint,
        )
        return _make_book(
            updated,
            book.entitlements,
            book.credited_events,
            book.tax_rate,
            at,
            at,
            book.sessions,
            book.calendar_source_hash,
            _append_trace(book, step, _transaction),
            _transaction=_transaction,
        )


def _owned_bind_modeled_operating_phase(
    book: DividendBook,
    *,
    phase_id: str,
    fingerprint: str,
    at: datetime,
    _transaction: _BookTransaction | None = None,
) -> tuple[DividendBook, DividendBookStep]:
    """Cost-owner-only append: retain a validated phase commitment without a cash move."""
    with localcontext(_CONTEXT):
        _require_current(book, _transaction)
        _utc(at)
        _check(at >= book.through_at, "operating_cost_phase_clock_rewind")
        _check(
            type(phase_id) is str
            and re.fullmatch(r"[0-9]{1,5}:(open|close)", phase_id) is not None,
            "operating_cost_phase_identity_invalid",
        )
        _require_sha256_hex(fingerprint, "operating_cost_phase_fingerprint")
        _check(
            not any(
                step.action == "operating_cost_phase" and step.event_id == phase_id
                for step in book.trace
            ),
            "operating_cost_phase_repeated",
        )
        step = replace(
            _step(book, "operating_cost_phase", at, book.account, book.account),
            event_id=phase_id,
            event_fingerprint=fingerprint,
        )
        return _make_book(
            book.account,
            book.entitlements,
            book.credited_events,
            book.tax_rate,
            book.account_at,
            at,
            book.sessions,
            book.calendar_source_hash,
            _append_trace(book, step, _transaction),
            _transaction=_transaction,
        ), step


@dataclass(frozen=True, slots=True)
class _OwnedBookAppend:
    prefix: tuple[DividendBookStep, ...]
    step: DividendBookStep


def _append_trace(
    book: DividendBook, step: DividendBookStep, transaction: _BookTransaction | None
) -> tuple[DividendBookStep, ...] | _OwnedBookAppend:
    if transaction is None:
        return (*book.trace, step)
    transaction._require(book)
    return _OwnedBookAppend(book.trace, step)


def _validate_current_book(book: DividendBook) -> Decimal:
    """Fresh generic and adoption-history checks without an abandoned trace append."""
    retained_tax = _validate_book(book)
    with localcontext(_CONTEXT):
        _adoption_history_values(book, book.account, book.through_at, retained_tax)
    return retained_tax


def _require_current(book: DividendBook, transaction: _BookTransaction | None) -> None:
    if transaction is None:
        _validate_book(book)
    else:
        transaction._require(book)


class _BookTransaction:
    """One synchronous owner's checked prefix; never retained on a public result.

    Full entry/exit scans bracket individually checked new Accounts and append
    deltas. No operation accepts an equal-but-foreign predecessor. This provides
    deterministic mutation detection, not protection from concurrent memory writes.
    """

    __slots__ = ("_active", "_credited", "_dividend_tax", "current")

    def __init__(self, book: DividendBook) -> None:
        retained_tax = _validate_current_book(book)
        self.current = book
        self._active = True
        self._dividend_tax = retained_tax
        self._credited = frozenset(book.credited_events)

    def _require(self, book: DividendBook) -> None:
        _check(self._active and book is self.current, "owned_current_dividend_book_required")

    def _accept(self, value: DividendBook) -> None:
        old = self.current
        self._require(old)
        _check(
            value.sessions is old.sessions
            and value.calendar_source_hash == old.calendar_source_hash
            and value.tax_rate == old.tax_rate
            and value.limitations == old.limitations
            and value.arithmetic_precision == 50
            and value.qualified
            is value.source_qualified
            is value.investment_eligible
            is value.trading_enabled
            is value.live_authorized
            is False,
            "owned_dividend_scope_changed",
        )
        _utc(value.account_at)
        _utc(value.through_at)
        _check(
            old.account_at <= value.account_at <= value.through_at
            and value.through_at >= old.through_at
            and len(value.trace) == len(old.trace) + 1,
            "owned_dividend_prefix_changed",
        )
        step = value.trace[-1]
        _check(type(step) is DividendBookStep, "invalid_trace_sequence")
        _utc(step.at)
        _check(
            step.sequence == len(old.trace)
            and step.previous_step_hash == old.trace[-1].evidence_hash
            and step.at == value.through_at
            and step.account_before_hash == _account_hash(old.account)
            and step.account_after_hash == _account_hash(value.account)
            and step.orders_before_hash == _orders_hash(old.account)
            and step.orders_after_hash == _orders_hash(value.account),
            "invalid_owned_dividend_append",
        )
        _account(value.account, value.account_at)
        _check(
            len(value.entitlements) <= _MAX_EVENTS
            and all(a is b for a, b in zip(value.entitlements, old.entitlements, strict=False)),
            "owned_entitlement_prefix_changed",
        )
        if step.action == "accrue":
            _check(
                len(value.entitlements) == len(old.entitlements) + 1
                and value.credited_events == old.credited_events
                and value.account is old.account
                and value.entitlements[-1].event.id == step.event_id
                and value.entitlements[-1].event_fingerprint == step.event_fingerprint
                and value.entitlements[-1].accrual.accrued_amount == step.gross_amount
                and step.tax_reserve_added == 0,
                "invalid_owned_accrual_append",
            )
        else:
            _check(value.entitlements is old.entitlements, "owned_entitlements_changed")
            if step.action == "credit":
                item = next((e for e in old.entitlements if e.event.id == step.event_id), None)
                _check(item is not None, "credit_without_owned_entitlement")
                if item is None:
                    raise DividendBookError("credit_without_owned_entitlement")
                tax = item.accrual.accrued_amount * (_ONE if old.tax_rate is None else old.tax_rate)
                _check(
                    step.event_id not in old.credited_events
                    and value.credited_events == (*old.credited_events, step.event_id)
                    and step.event_fingerprint == item.event_fingerprint
                    and step.gross_amount == item.accrual.accrued_amount
                    and step.tax_reserve_added == tax
                    and value.account.model_dump(exclude={"cash", "tax_reserve"})
                    == old.account.model_dump(exclude={"cash", "tax_reserve"})
                    and value.account.cash == old.account.cash + step.gross_amount
                    and value.account.tax_reserve == old.account.tax_reserve + tax,
                    "invalid_owned_dividend_credit",
                )
            else:
                _check(value.credited_events is old.credited_events, "owned_credit_history_changed")
                _check(step.tax_reserve_added == 0, "unexpected_owned_dividend_tax")
                if step.action == "adopt_account":
                    _adoption_history_values(
                        old, value.account, value.account_at, self._dividend_tax
                    )
                    _check(step.gross_amount == 0, "unexpected_owned_adoption_cash")
                elif step.action == "operating_expense":
                    _check(
                        step.gross_amount >= 0
                        and step.gross_amount <= old.account.buying_power
                        and Fraction(old.account.cash) - Fraction(value.account.cash)
                        == Fraction(step.gross_amount)
                        and value.account.model_dump(exclude={"cash"})
                        == old.account.model_dump(exclude={"cash"}),
                        "invalid_owned_operating_expense",
                    )
                else:
                    _check(
                        step.action in ("advance", "operating_cost_phase")
                        and value.account is old.account
                        and step.gross_amount == 0,
                        "invalid_owned_no_cash_append",
                    )
        self._dividend_tax += step.tax_reserve_added
        _check(
            value.account.tax_reserve >= self._dividend_tax, "retained_dividend_tax_reserve_lost"
        )
        self.current = value
        self._credited = frozenset(value.credited_events)

    def adopt(self, book: DividendBook, account: Account, *, at: datetime) -> DividendBook:
        return _owned_adopt_dividend_account(book, account, at=at, _transaction=self)

    def credit(self, book: DividendBook, *, at: datetime) -> DividendBook:
        return _owned_credit_due_dividends(book, at=at, _transaction=self)

    def accrue(
        self,
        book: DividendBook,
        event: StockCashDividendEvent,
        *,
        snapshot_at: datetime,
        ex_opens_at: datetime,
        modeled_pay_available_at: datetime | None,
    ) -> DividendBook:
        return _owned_record_dividend_entitlement(
            book,
            event,
            snapshot_at=snapshot_at,
            ex_opens_at=ex_opens_at,
            modeled_pay_available_at=modeled_pay_available_at,
            _transaction=self,
        )

    def receivable(self, book: DividendBook, *, at: datetime) -> Decimal:
        return _owned_receivable_value(book, at=at, _transaction=self)

    def pay(
        self,
        book: DividendBook,
        *,
        charge_id: str,
        amount_usd: Decimal,
        charge_fingerprint: str,
        at: datetime,
    ) -> DividendBook:
        return _owned_pay_modeled_operating_expense(
            book,
            charge_id=charge_id,
            amount_usd=amount_usd,
            charge_fingerprint=charge_fingerprint,
            at=at,
            _transaction=self,
        )

    def bind(
        self,
        book: DividendBook,
        *,
        phase_id: str,
        fingerprint: str,
        at: datetime,
    ) -> tuple[DividendBook, DividendBookStep]:
        return _owned_bind_modeled_operating_phase(
            book,
            phase_id=phase_id,
            fingerprint=fingerprint,
            at=at,
            _transaction=self,
        )

    def finish(self) -> DividendBook:
        self._require(self.current)
        try:
            _validate_current_book(self.current)
            return self.current
        finally:
            self._active = False

    def _abort(self) -> None:
        self._active = False


def _begin_book_transaction(book: DividendBook) -> _BookTransaction:
    return _BookTransaction(book)


def record_dividend_entitlement(
    book: DividendBook,
    event: StockCashDividendEvent,
    *,
    snapshot_at: datetime,
    ex_opens_at: datetime,
    modeled_pay_available_at: datetime | None,
) -> DividendBook:
    """Freshly validate the caller book before recording a source-bound earned right."""
    return _owned_record_dividend_entitlement(
        book,
        event,
        snapshot_at=snapshot_at,
        ex_opens_at=ex_opens_at,
        modeled_pay_available_at=modeled_pay_available_at,
    )


def credit_due_dividends(book: DividendBook, *, at: datetime) -> DividendBook:
    """Freshly validate and credit due modeled dividends once."""
    return _owned_credit_due_dividends(book, at=at)


def receivable_value(book: DividendBook, *, at: datetime) -> Decimal:
    """Freshly validate a historical receivable query; it never supplies cash."""
    return _owned_receivable_value(book, at=at)


def adopt_dividend_account(book: DividendBook, account: Account, *, at: datetime) -> DividendBook:
    """Freshly validate a caller-modeled transition; never authenticate an execution."""
    return _owned_adopt_dividend_account(book, account, at=at)


def pay_modeled_operating_expense(
    book: DividendBook,
    *,
    charge_id: str,
    amount_usd: Decimal,
    charge_fingerprint: str,
    at: datetime,
) -> DividendBook:
    """Freshly validate a paused-book debit, retaining reservation and exact-cash checks."""
    return _owned_pay_modeled_operating_expense(
        book,
        charge_id=charge_id,
        amount_usd=amount_usd,
        charge_fingerprint=charge_fingerprint,
        at=at,
    )


def _bind_modeled_operating_phase(
    book: DividendBook,
    *,
    phase_id: str,
    fingerprint: str,
    at: datetime,
) -> tuple[DividendBook, DividendBookStep]:
    return _owned_bind_modeled_operating_phase(
        book,
        phase_id=phase_id,
        fingerprint=fingerprint,
        at=at,
    )
