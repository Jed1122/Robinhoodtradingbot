"""Descriptive, nonpromoting monetary observations from the owned stock replay.

No data provider, strategy, execution, payment or second cash ledger exists here.
Public source admission remains the completed retrospective owner's fresh boundary;
private short algebra workers are not shortened actual-source profiles.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from decimal import (
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
from hashlib import sha256
from itertools import pairwise
from typing import Literal

from pydantic import BaseModel

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.hybrid.accounting import buy_lot, dispose
from trading_bot.hybrid.models import FillFact, Lot, PaperOrder
from trading_bot.research.hybrid_policies import CalendarSession
from trading_bot.research.hybrid_strategies import FAMILIES
from trading_bot.research.metrics import MetricValue
from trading_bot.research.stock_dividend_book import DividendBook, _validate_current_book
from trading_bot.research.stock_economic_policies import (
    STOCK_POLICY_SYMBOLS,
    EconomicPolicyClose,
    KnownPolicyCondition,
    UnavailablePolicyCondition,
    _RetrospectivePolicyClose,
)
from trading_bot.research.stock_economic_replay import (
    _INCOMPLETE,
    EconomicReplayCostMark,
    EconomicReplayRecord,
    EconomicReplaySnapshot,
)
from trading_bot.research.stock_monetary_admission import MonetaryCaseDependency
from trading_bot.research.stock_operating_costs import ModeledOperatingCostPlan
from trading_bot.research.stock_retrospective_replay import (
    RetrospectiveCaseSpec,
    RetrospectiveEconomicReplayResult,
    finish_retrospective_economic_replay,
)
from trading_bot.research.stock_retrospective_replay_inputs import (
    PreparedRetrospectiveReplayInputs,
    RetrospectiveReplayConvention,
)
from trading_bot.research.stock_study_statistics import summarize_price_path

_ZERO, _ONE = Decimal(0), Decimal(1)
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
DEFINITION_HASH = "17a5852d38da25f0c192a8f717a998e020f172350af8f2f83cfbb21880163523"
CLARIFICATION_PARENT_HASH = "fd958a905d6f1b7a14425e48a19c116c832a3c9aea6345dfc8ca8df82472d2af"
CLARIFICATION_HASH = "67e6e721af67cf7091d12eb72f0c14d405e73ca5868b5277e0b8b41e897fdc13"
_PATH_KEYS = (
    "total_return",
    "cagr",
    "annualized_volatility",
    "mean_return",
    "max_drawdown",
    "inherited_max_drawdown",
    "sharpe",
    "sortino",
    "calmar",
)


def _check(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _plain(value: object) -> object:
    if isinstance(value, Decimal):
        parts = value.as_tuple()
        return {"decimal": (parts.sign, parts.digits, parts.exponent)}
    if isinstance(value, datetime):
        return {"utc_datetime": value.isoformat()}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    if isinstance(value, BaseModel):
        return _plain(value.model_dump())
    if is_dataclass(value) and not isinstance(value, type):
        return _plain(asdict(value))
    if isinstance(value, tuple | list):
        return tuple(_plain(item) for item in value)
    if isinstance(value, dict):
        for key in (
            "qualified",
            "source_qualified",
            "strategy_qualified",
            "investment_eligible",
            "trading_enabled",
            "live_authorized",
            "full_task5_complete",
        ):
            if key in value:
                _check(value[key] is False, "nested_metric_scope_cannot_promote")
        return {key: _plain(item) for key, item in value.items()}
    return value


def _digest(tag: str, value: object) -> str:
    payload = json.dumps(
        (tag, _plain(value)), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return sha256(payload.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class _Scope:
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    full_task5_complete: Literal[False] = field(default=False, init=False)

    def _scope(self) -> None:
        _check(
            self.qualified
            is self.source_qualified
            is self.strategy_qualified
            is self.investment_eligible
            is self.trading_enabled
            is self.live_authorized
            is self.full_task5_complete
            is False,
            "unqualified_monetary_metric_scope_required",
        )


@dataclass(frozen=True, slots=True)
class _CurveObservation:
    session_index: int
    at: datetime
    value: Decimal | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class MonetaryCurveMetrics(_Scope):
    series: tuple[_CurveObservation, ...]
    metrics: tuple[tuple[str, MetricValue], ...]
    simple_returns: tuple[Decimal | None, ...]
    log_returns: tuple[Decimal | None, ...]
    expected_mark_count: int
    observed_mark_count: int
    expected_return_count: int
    elapsed_trading_years: Decimal
    missing_indices: tuple[int, ...]
    invalid_indices: tuple[int, ...]
    undefined_reasons: tuple[str, ...]
    inherited_peak: Decimal | None
    input_evidence_hash: str

    @property
    def evidence_hash(self) -> str:
        self._scope()
        return _digest("stock-monetary-curve-metrics-v1", self)


def _expected_calendar(expected: tuple[CalendarSession, ...]) -> None:
    _check(
        type(expected) is tuple and 2 <= len(expected) <= 10000, "expected_metric_calendar_required"
    )
    previous = None
    for session in expected:
        _check(
            type(session) is CalendarSession and type(session.index) is int,
            "typed_metric_session_required",
        )
        require_utc(session.opens_at)
        require_utc(session.closes_at)
        _check(session.opens_at < session.closes_at, "invalid_metric_session")
        if previous is not None:
            _check(
                previous.index + 1 == session.index and previous.closes_at < session.opens_at,
                "metric_calendar_order_changed",
            )
        previous = session


def _inherited_peak(
    prefix: tuple[_CurveObservation, ...] | None,
    baseline: _CurveObservation,
) -> Decimal | None:
    if prefix is None:
        return baseline.value
    if not prefix or prefix[-1] != baseline:
        return None
    previous = None
    for point in prefix:
        if (
            type(point) is not _CurveObservation
            or type(point.value) is not Decimal
            or not point.value.is_finite()
            or point.value <= 0
        ):
            return None
        require_utc(point.at)
        if previous is not None and not (
            previous.session_index + 1 == point.session_index and previous.at < point.at
        ):
            return None
        previous = point
    return max(point.value for point in prefix if point.value is not None)


def _curve(
    observations: tuple[_CurveObservation, ...],
    *,
    expected: tuple[CalendarSession, ...],
    prefix: tuple[_CurveObservation, ...] | None = None,
    unavailable_reason: str | None = None,
) -> MonetaryCurveMetrics:
    """Private algebra worker: missing expected dates never change the denominator."""
    with localcontext(_CONTEXT):
        _expected_calendar(expected)
        _check(type(observations) is tuple, "immutable_metric_observations_required")
        expected_by_index = {session.index: session for session in expected}
        found: dict[int, _CurveObservation] = {}
        invalid: set[int] = set()
        reasons: list[str] = []
        prior_index = None
        for point in observations:
            _check(
                type(point) is _CurveObservation and type(point.session_index) is int,
                "typed_curve_observation_required",
            )
            require_utc(point.at)
            index = point.session_index
            if prior_index is not None and index <= prior_index:
                reasons.append("duplicate_or_reordered_observation")
                invalid.add(index)
            prior_index = index
            if index in found:
                invalid.add(index)
            found[index] = point
            if index not in expected_by_index or point.at != expected_by_index[index].closes_at:
                invalid.add(index)
                reasons.append("unexpected_observation_clock_or_index")
            if point.value is None:
                reasons.append(point.reason or "unknown_wealth")
                invalid.add(index)
            elif type(point.value) is not Decimal or not point.value.is_finite():
                reasons.append("invalid_wealth_value")
                invalid.add(index)
            elif point.value <= 0:
                reasons.append("nonpositive_wealth")
                invalid.add(index)
        missing = tuple(index for index in expected_by_index if index not in found)
        if missing:
            reasons.append("missing_expected_marks")
        if unavailable_reason:
            reasons.append(unavailable_reason)
        series = tuple(
            _CurveObservation(
                session.index,
                session.closes_at,
                None
                if session.index not in found or session.index in invalid
                else found[session.index].value,
                None
                if session.index in found and session.index not in invalid
                else "missing_or_invalid_mark",
            )
            for session in expected
        )
        count = len(expected) - 1
        input_hash = _digest(
            "stock-monetary-curve-input-v1", (observations, expected, prefix, unavailable_reason)
        )
        metrics = tuple(
            (name, MetricValue(None, ";".join(sorted(set(reasons))))) for name in _PATH_KEYS
        )
        simple: tuple[Decimal | None, ...] = (None,) * count
        logs: tuple[Decimal | None, ...] = (None,) * count
        peak = None
        if not reasons:
            values = tuple(point.value for point in series if point.value is not None)
            peak = _inherited_peak(prefix, series[0])
            try:
                summary = summarize_price_path(values, inherited_peak=peak)
                simple = tuple(b / a - _ONE for a, b in pairwise(values))
                logs = tuple((b / a).ln() for a, b in pairwise(values))
                summaries = {
                    "total_return": summary.total_return,
                    "cagr": summary.cagr,
                    "annualized_volatility": summary.annualized_volatility,
                    "mean_return": summary.mean_return,
                    "max_drawdown": summary.max_drawdown,
                    "inherited_max_drawdown": summary.inherited_max_drawdown,
                    "sharpe": summary.sharpe,
                    "sortino": summary.sortino,
                }
                summaries["calmar"] = (
                    None if summary.max_drawdown == 0 else summary.cagr / summary.max_drawdown
                )
                statuses = {name: "defined" for name in _PATH_KEYS}
                for reason in summary.undefined_reasons:
                    name = reason.split(":", 1)[0]
                    statuses[name] = reason
                if summary.max_drawdown == 0:
                    statuses["calmar"] = "zero_segment_drawdown"
                if peak is None:
                    summaries["inherited_max_drawdown"] = None
                    statuses["inherited_max_drawdown"] = "inherited_peak_unavailable"
                metrics = tuple(
                    (name, MetricValue(summaries[name], statuses[name])) for name in _PATH_KEYS
                )
                reasons.extend(status for status in statuses.values() if status != "defined")
            except (ValueError, DecimalException):
                reasons.append("curve_arithmetic_unavailable")
                metrics = tuple(
                    (name, MetricValue(None, "curve_arithmetic_unavailable")) for name in _PATH_KEYS
                )
                simple, logs = (None,) * count, (None,) * count
        return MonetaryCurveMetrics(
            series,
            metrics,
            simple,
            logs,
            len(expected),
            len(observations),
            count,
            Decimal(count) / 252,
            missing,
            tuple(sorted(invalid)),
            tuple(sorted(set(reasons))),
            peak,
            input_hash,
        )


@dataclass(frozen=True, slots=True)
class _ProjectedRow:
    session_index: int
    at: datetime
    gross: Decimal
    net: Decimal | None
    after_provision: Decimal | None
    known_due: Decimal | None
    unknown_ids: tuple[str, ...]
    net_reason: str | None
    after_reason: str | None


def _registered_rate(rate: Decimal | None) -> None:
    _check(
        rate is None
        or (type(rate) is Decimal and rate.is_finite() and rate in (_ZERO, Decimal(".25"))),
        "unregistered_metric_tax_rate",
    )


def _project_row(
    snapshot: EconomicReplaySnapshot,
    mark: EconomicReplayCostMark | None,
    *,
    rate: Decimal | None,
    plan: ModeledOperatingCostPlan,
    activation_at: datetime,
    baseline: bool = False,
) -> _ProjectedRow:
    """Project the owner's exact balances, never another cash ledger or tax scenario."""
    with localcontext(_CONTEXT):
        _registered_rate(rate)
        _check(
            type(snapshot) is EconomicReplaySnapshot and type(baseline) is bool,
            "typed_metric_snapshot_required",
        )
        require_utc(snapshot.at)
        require_utc(activation_at)
        plan.__post_init__()
        for value in (
            snapshot.gross_equity,
            snapshot.cash,
            snapshot.reserved_cash,
            snapshot.tax_reserve,
            snapshot.unsettled,
            snapshot.receivable,
            snapshot.long_term_value,
            snapshot.tactical_value,
        ):
            require_bounded_decimal(value, "monetary_snapshot", nonnegative=True)
        _check(
            snapshot.gross_equity
            == snapshot.cash
            + snapshot.unsettled
            + snapshot.receivable
            + snapshot.long_term_value
            + snapshot.tactical_value,
            "snapshot_gross_conservation_failed",
        )
        reason = None
        unknown: tuple[str, ...] = ()
        due: Decimal | None = None
        net = None
        if baseline:
            _check(
                snapshot.session_index == 199
                and snapshot.at < activation_at
                and mark is None
                and all(charge.due_at >= activation_at for charge in plan.charges),
                "activation_baseline_cost_scope_changed",
            )
            due, net = _ZERO, snapshot.gross_equity
        elif mark is None:
            reason = "missing_close_cost_mark"
        else:
            _check(type(mark) is EconomicReplayCostMark, "typed_close_cost_mark_required")
            mark.__post_init__()
            _check(
                mark.session_index == snapshot.session_index
                and mark.at == snapshot.at
                and mark.phase == "close"
                and mark.plan_hash == plan.evidence_hash
                and mark.gross_equity == snapshot.gross_equity,
                "close_cost_snapshot_mismatch",
            )
            due, unknown = mark.unpaid_known, mark.unpaid_unknown_ids
            net = None if unknown else snapshot.gross_equity - due
            if unknown:
                reason = "unknown_due_operating_cost"
        after = (
            None
            if rate is None or net is None
            else net - snapshot.tax_reserve - rate * snapshot.receivable
        )
        after_reason = "tax_rate_unknown" if rate is None else reason
        return _ProjectedRow(
            snapshot.session_index,
            snapshot.at,
            snapshot.gross_equity,
            net,
            after,
            due,
            unknown,
            reason,
            after_reason,
        )


@dataclass(frozen=True, slots=True)
class _MatchedFill:
    fill: FillFact
    order: PaperOrder
    record: EconomicReplayRecord
    session_index: int
    episode_id: str


@dataclass(frozen=True, slots=True)
class MonetaryEpisode(_Scope):
    episode_id: str
    symbol: str
    sleeve: str
    entry_fill_ids: tuple[str, ...]
    disposal_fill_ids: tuple[str, ...]
    first_entry_at: datetime
    first_entry_index: int
    last_disposal_at: datetime | None
    last_disposal_index: int | None
    proceeds: Decimal
    disposed_basis: Decimal
    pnl: Decimal
    remaining_quantity: Decimal
    completed: bool
    active_order_ids: tuple[str, ...]
    ambiguous_order_ids: tuple[str, ...]
    completion_at: datetime | None
    completion_not_after: datetime | None
    holding_days: Decimal | None
    holding_intervals: int | None


@dataclass(frozen=True, slots=True)
class _ExecutionAudit(_Scope):
    available: bool
    reasons: tuple[str, ...]
    fills: tuple[_MatchedFill, ...]
    episodes: tuple[MonetaryEpisode, ...]
    orders: tuple[PaperOrder, ...]
    final_at: datetime
    input_evidence_hash: str


def _fill_key(
    order_id: str | None, at: datetime, quantity: Decimal, price: Decimal, fee: Decimal
) -> tuple[object, ...]:
    return order_id, at, quantity, price, fee


def _audit_executions(
    book: DividendBook,
    records: tuple[EconomicReplayRecord, ...],
    *,
    calendar: tuple[CalendarSession, ...],
    rate: Decimal | None,
    native_last_index: int,
) -> _ExecutionAudit:
    """Reconcile owned fill identities and lot basis; do not replay cash or executions."""
    with localcontext(_CONTEXT):
        _registered_rate(rate)
        _validate_current_book(book)
        _expected_calendar(calendar)
        _check(
            type(records) is tuple and type(native_last_index) is int,
            "immutable_execution_audit_inputs_required",
        )
        identity = _digest(
            "monetary-execution-audit-input-v1",
            (book.evidence_hash, records, calendar, rate, native_last_index),
        )
        account = book.account

        def fail(reason: str) -> _ExecutionAudit:
            return _ExecutionAudit(
                False, (reason,), (), (), account.orders, book.through_at, identity
            )

        orders = {order.id: order for order in account.orders}
        days = {
            session.opens_at.date(): session
            for session in calendar
            if session.index <= native_last_index
        }
        record_by_key: dict[tuple[object, ...], list[EconomicReplayRecord]] = {}
        fill_by_key: dict[tuple[object, ...], list[FillFact]] = {}
        for row in records:
            if type(row) is not EconomicReplayRecord:
                return fail("typed_execution_record_required")
            if row.outcome != "filled":
                continue
            record_by_key.setdefault(
                _fill_key(row.order_id, row.at, row.quantity, row.price, row.fee), []
            ).append(row)
        for fill in account.fills:
            fill_by_key.setdefault(
                _fill_key(fill.order_id, fill.at, fill.quantity, fill.price, fill.fee), []
            ).append(fill)
        if set(record_by_key) != set(fill_by_key):
            return fail("missing_owned_fill_record")
        if any(len(values) != 1 for values in record_by_key.values()) or any(
            len(values) != 1 for values in fill_by_key.values()
        ):
            return fail("ambiguous_fill_record_join")
        lots: tuple[Lot, ...] = ()
        matches: list[_MatchedFill] = []
        entries: dict[str, list[_MatchedFill]] = {}
        disposals: dict[str, list[_MatchedFill]] = {}
        totals: dict[str, tuple[Decimal, Decimal]] = {}
        gains = fees = _ZERO
        previous_at = None
        sales: dict[str, tuple[Decimal, datetime]] = {}
        for fill in account.fills:
            row = record_by_key[
                _fill_key(fill.order_id, fill.at, fill.quantity, fill.price, fill.fee)
            ][0]
            order = orders.get(fill.order_id)
            if order is None or row.symbol != order.symbol or row.side != order.side:
                return fail("fill_order_record_mismatch")
            session = days.get(fill.at.date())
            if (
                session is None
                or not session.opens_at <= fill.at <= session.closes_at
                or row.session_index != session.index
            ):
                return fail("fill_outside_expected_native_session")
            if previous_at is not None and fill.at < previous_at:
                return fail("owned_fill_clock_rewind")
            previous_at = fill.at
            episode = order.episode_id or (order.id if order.side == "buy" else None)
            if episode is None:
                return fail("owned_episode_identity_unavailable")
            matched = _MatchedFill(fill, order, row, session.index, episode)
            matches.append(matched)
            fees += fill.fee
            try:
                if order.side == "buy":
                    if row.proceeds != 0 or row.disposed_basis != 0 or row.realized_gain != 0:
                        return fail("entry_record_has_disposal_amounts")
                    lot = buy_lot(
                        fill.id,
                        order.symbol,
                        order.sleeve,
                        fill.quantity,
                        fill.price,
                        fill.at,
                        fill.fee,
                    )
                    lots = (*lots, lot.model_copy(update={"episode_id": episode}))
                    entries.setdefault(episode, []).append(matched)
                    cost, quantity = totals.get(episode, (_ZERO, _ZERO))
                    totals[episode] = (
                        cost + fill.quantity * fill.price + fill.fee,
                        quantity + fill.quantity,
                    )
                else:
                    if episode not in entries:
                        return fail("disposal_without_owned_entry")
                    selected = tuple(
                        lot
                        for lot in lots
                        if lot.episode_id == episode
                        and lot.symbol == order.symbol
                        and lot.sleeve == order.sleeve
                    )
                    sale = dispose(
                        selected, fill.quantity, fill.price, fill.at, fee=fill.fee, tax_rate=rate
                    )
                    if (row.proceeds, row.disposed_basis, row.realized_gain) != (
                        sale.proceeds,
                        sale.disposed_basis,
                        sale.gain,
                    ):
                        return fail("disposal_record_mismatch")
                    if row.settlement_at is None or row.settlement_at <= fill.at:
                        return fail("sale_settlement_clock_unavailable")
                    lots = tuple(lot for lot in lots if lot not in selected) + sale.lots
                    disposals.setdefault(episode, []).append(matched)
                    gains += sale.gain
                    sales[fill.id] = sale.proceeds, row.settlement_at
            except (ValueError, TypeError, DecimalException):
                return fail("owned_lot_basis_unavailable")
        if lots != account.lots or fees != account.fees or gains != account.realized_gain:
            return fail("final_lot_fee_or_gain_mismatch")
        for order in account.orders:
            if (
                sum((item.fill.quantity for item in matches if item.order.id == order.id), _ZERO)
                != order.filled
            ):
                return fail("filled_order_quantity_mismatch")
        if set(totals) != {episode.id for episode in account.episodes}:
            return fail("allocation_episode_inventory_mismatch")
        for allocation_fact in account.episodes:
            if totals[allocation_fact.id] != (
                allocation_fact.original_cash,
                allocation_fact.original_quantity,
            ):
                return fail("allocation_episode_basis_mismatch")
        for claim in account.settlements:
            if sales.get(claim.id) != (claim.amount, claim.due_at):
                return fail("surviving_sale_claim_mismatch")
        live_claim_ids = {claim.id for claim in account.settlements}
        if any(
            key not in live_claim_ids and due > book.through_at for key, (_, due) in sales.items()
        ):
            return fail("unsettled_sale_claim_missing")
        audited: list[MonetaryEpisode] = []
        for allocation in account.episodes:
            entry = entries[allocation.id]
            episode_sales = disposals.get(allocation.id, [])
            owned_orders = tuple(
                order
                for order in account.orders
                if (order.episode_id or (order.id if order.side == "buy" else None))
                == allocation.id
            )
            active = tuple(
                order.id for order in owned_orders if order.status in ("open", "partial")
            )
            ambiguous = tuple(
                order.id for order in owned_orders if order.status in ("cancelled", "rejected")
            )
            quantity = sum(
                (lot.quantity for lot in account.lots if lot.episode_id == allocation.id), _ZERO
            )
            completed = quantity == 0 and not active and bool(episode_sales)
            first, last = entry[0], episode_sales[-1] if episode_sales else None
            proceeds = sum((item.record.proceeds for item in episode_sales), _ZERO)
            basis = sum((item.record.disposed_basis for item in episode_sales), _ZERO)
            elapsed = None if last is None else last.fill.at - first.fill.at
            seconds = (
                None
                if elapsed is None
                else Decimal(elapsed.days) * 86400
                + elapsed.seconds
                + Decimal(elapsed.microseconds) / 1000000
            )
            audited.append(
                MonetaryEpisode(
                    allocation.id,
                    allocation.symbol,
                    allocation.sleeve,
                    tuple(item.fill.id for item in entry),
                    tuple(item.fill.id for item in episode_sales),
                    first.fill.at,
                    first.session_index,
                    None if last is None else last.fill.at,
                    None if last is None else last.session_index,
                    proceeds,
                    basis,
                    proceeds - basis,
                    quantity,
                    completed,
                    active,
                    ambiguous,
                    last.fill.at if completed and not ambiguous and last is not None else None,
                    book.through_at if completed else None,
                    None if seconds is None else seconds / 86400,
                    None if last is None else last.session_index - first.session_index,
                )
            )
        return _ExecutionAudit(
            True, (), tuple(matches), tuple(audited), account.orders, book.through_at, identity
        )


_EPISODE_KEYS = (
    "completed_count",
    "positive_count",
    "negative_count",
    "zero_count",
    "open_count",
    "active_order_count",
    "win_rate",
    "average_win",
    "average_loss",
    "profit_factor",
    "mean_holding_days",
    "mean_holding_intervals",
)


@dataclass(frozen=True, slots=True)
class _EpisodeMetrics(_Scope):
    metrics: tuple[tuple[str, MetricValue], ...]
    ambiguous_episode_ids: tuple[str, ...]
    ambiguous_order_ids: tuple[str, ...]
    input_evidence_hash: str
    historical_status_ambiguous_episode_ids: tuple[str, ...] = ()
    historical_status_ambiguous_order_ids: tuple[str, ...] = ()


def _episode_metrics(
    audit: _ExecutionAudit,
    *,
    baseline_at: datetime,
    terminal_at: datetime,
) -> _EpisodeMetrics:
    with localcontext(_CONTEXT):
        require_utc(baseline_at)
        require_utc(terminal_at)
        _check(baseline_at < terminal_at <= audit.final_at, "episode_metric_window_invalid")
        identity = _digest("monetary-episode-cohort-v1", (audit, baseline_at, terminal_at))
        if not audit.available:
            return _EpisodeMetrics(
                tuple(
                    (key, MetricValue(None, "execution_provenance_unavailable"))
                    for key in _EPISODE_KEYS
                ),
                (),
                (),
                identity,
            )
        chosen: list[MonetaryEpisode] = []
        ambiguous: list[MonetaryEpisode] = []
        for episode in audit.episodes:
            if not episode.completed or episode.last_disposal_at is None:
                continue
            lower = episode.last_disposal_at
            upper = episode.completion_at or episode.completion_not_after
            if upper is None:
                ambiguous.append(episode)
            elif lower > terminal_at or upper <= baseline_at:
                continue
            elif baseline_at < lower and upper <= terminal_at:
                chosen.append(episode)
            else:
                ambiguous.append(episode)
        values = {
            key: MetricValue(None, "completion_time_cohort_ambiguous") for key in _EPISODE_KEYS
        }
        if not ambiguous:
            positive = tuple(item.pnl for item in chosen if item.pnl > 0)
            negative = tuple(item.pnl for item in chosen if item.pnl < 0)
            zero = sum(item.pnl == 0 for item in chosen)
            count = len(chosen)
            values.update(
                {
                    "completed_count": MetricValue(count),
                    "positive_count": MetricValue(len(positive)),
                    "negative_count": MetricValue(len(negative)),
                    "zero_count": MetricValue(zero),
                }
            )
            values["win_rate"] = (
                MetricValue(Decimal(len(positive)) / count)
                if count
                else MetricValue(None, "no_completed_episodes")
            )
            values["average_win"] = (
                MetricValue(sum(positive, _ZERO) / len(positive))
                if positive
                else MetricValue(None, "no_positive_episodes" if count else "no_completed_episodes")
            )
            values["average_loss"] = (
                MetricValue(sum(negative, _ZERO) / len(negative))
                if negative
                else MetricValue(None, "no_negative_episodes" if count else "no_completed_episodes")
            )
            values["profit_factor"] = (
                MetricValue(sum(positive, _ZERO) / abs(sum(negative, _ZERO)))
                if negative
                else MetricValue(None, "no_negative_pnl" if count else "no_completed_episodes")
            )
            values["mean_holding_days"] = (
                MetricValue(
                    sum(
                        (item.holding_days for item in chosen if item.holding_days is not None),
                        _ZERO,
                    )
                    / count
                )
                if count
                else MetricValue(None, "no_completed_episodes")
            )
            values["mean_holding_intervals"] = (
                MetricValue(
                    sum(
                        (
                            Decimal(item.holding_intervals)
                            for item in chosen
                            if item.holding_intervals is not None
                        ),
                        _ZERO,
                    )
                    / count
                )
                if count
                else MetricValue(None, "no_completed_episodes")
            )
        historical_episodes: tuple[str, ...] = ()
        historical_orders: tuple[str, ...] = ()
        if terminal_at == audit.final_at:
            values["open_count"] = MetricValue(
                sum(not episode.completed for episode in audit.episodes)
            )
            values["active_order_count"] = MetricValue(
                sum(order.status in ("open", "partial") for order in audit.orders)
            )
        else:
            # A positive owned quantity proves open status without a cancellation
            # clock. Fully filled orders prove terminal status from their fills.
            inactive = {
                order.id
                for order in audit.orders
                if order.status == "filled"
                and all(
                    item.fill.at <= terminal_at for item in audit.fills if item.order.id == order.id
                )
            }
            historical_orders = tuple(
                order.id for order in audit.orders if order.id not in inactive
            )
            unresolved = []
            open_count = 0
            for episode in audit.episodes:
                if episode.first_entry_at > terminal_at:
                    continue
                owned = tuple(
                    item
                    for item in audit.fills
                    if item.episode_id == episode.episode_id and item.fill.at <= terminal_at
                )
                quantity = sum(
                    (
                        item.fill.quantity if item.order.side == "buy" else -item.fill.quantity
                        for item in owned
                    ),
                    _ZERO,
                )
                if quantity > 0:
                    open_count += 1
                elif any(
                    (order.episode_id or (order.id if order.side == "buy" else None))
                    == episode.episode_id
                    and order.id not in inactive
                    for order in audit.orders
                ):
                    unresolved.append(episode.episode_id)
            historical_episodes = tuple(unresolved)
            values["open_count"] = (
                MetricValue(None, "historical_order_lifecycle_unavailable")
                if unresolved
                else MetricValue(open_count)
            )
            values["active_order_count"] = (
                MetricValue(None, "historical_order_lifecycle_unavailable")
                if historical_orders
                else MetricValue(0)
            )
        return _EpisodeMetrics(
            tuple((key, values[key]) for key in _EPISODE_KEYS),
            tuple(item.episode_id for item in ambiguous),
            tuple(sorted({key for item in ambiguous for key in item.ambiguous_order_ids})),
            identity,
            historical_episodes,
            historical_orders,
        )


@dataclass(frozen=True, slots=True)
class MonetarySymbolCoverage:
    symbol: str
    expected_executable_slots: int
    known_active_count: int
    known_inactive_count: int
    unavailable_count: int


@dataclass(frozen=True, slots=True)
class MonetaryPolicyWindow(_Scope):
    baseline_index: int
    terminal_index: int
    expected_executable_slots: int
    known_active_count: int
    known_inactive_count: int
    unavailable_count: int
    unavailable_by_code: tuple[tuple[str, int], ...]
    by_symbol: tuple[MonetarySymbolCoverage, ...]
    inventory_evidence_hash: str


@dataclass(frozen=True, slots=True)
class MonetaryPolicyCoverage(_Scope):
    closes: tuple[EconomicPolicyClose, ...]
    expected_calendar: tuple[CalendarSession, ...]
    family: str
    expected_audit_slots: int
    observed_audit_slots: int
    terminal_audit_slots: int
    missing_slots: tuple[tuple[int, str], ...]
    full: MonetaryPolicyWindow
    input_evidence_hash: str

    @property
    def expected_executable_slots(self) -> int:
        return self.full.expected_executable_slots

    @property
    def known_active_count(self) -> int:
        return self.full.known_active_count

    @property
    def known_inactive_count(self) -> int:
        return self.full.known_inactive_count

    @property
    def unavailable_count(self) -> int:
        return self.full.unavailable_count

    @property
    def unavailable_by_code(self) -> tuple[tuple[str, int], ...]:
        return self.full.unavailable_by_code

    @property
    def by_symbol(self) -> tuple[MonetarySymbolCoverage, ...]:
        return self.full.by_symbol


def _build_policy_window(
    closes: tuple[EconomicPolicyClose, ...],
    expected: tuple[CalendarSession, ...],
    *,
    baseline_index: int,
    terminal_index: int,
    inventory_hash: str,
) -> MonetaryPolicyWindow:
    _check(
        expected[0].index <= baseline_index < terminal_index <= expected[-1].index,
        "policy_coverage_window_outside_native_axis",
    )
    by_index = {close.session_index: close for close in closes}
    counts = {symbol: [0, 0, 0] for symbol in STOCK_POLICY_SYMBOLS}
    codes: dict[str, int] = {}
    for index in range(baseline_index, terminal_index):
        close = by_index.get(index)
        if close is None:
            for symbol in STOCK_POLICY_SYMBOLS:
                counts[symbol][2] += 1
            codes["missing_policy_close"] = codes.get("missing_policy_close", 0) + 8
            continue
        for condition in close.conditions:
            if isinstance(condition, KnownPolicyCondition):
                counts[condition.symbol][0 if condition.active else 1] += 1
            else:
                counts[condition.symbol][2] += 1
                code = condition.outcome.code
                codes[code] = codes.get(code, 0) + 1
    n = terminal_index - baseline_index
    rows = tuple(
        MonetarySymbolCoverage(symbol, n, *counts[symbol]) for symbol in STOCK_POLICY_SYMBOLS
    )
    return MonetaryPolicyWindow(
        baseline_index,
        terminal_index,
        8 * n,
        sum(row.known_active_count for row in rows),
        sum(row.known_inactive_count for row in rows),
        sum(row.unavailable_count for row in rows),
        tuple(sorted(codes.items())),
        rows,
        inventory_hash,
    )


def _policy_coverage(
    closes: tuple[EconomicPolicyClose, ...],
    *,
    expected: tuple[CalendarSession, ...],
    family: str,
) -> MonetaryPolicyCoverage:
    """Read the owned policy inventory once; never rerun signals or infer missing peers."""
    _expected_calendar(expected)
    _check(type(closes) is tuple and family in FAMILIES, "typed_policy_coverage_required")
    sessions = {session.index: session for session in expected}
    seen: set[int] = set()
    previous = None
    for close in closes:
        _check(
            type(close) in (EconomicPolicyClose, _RetrospectivePolicyClose),
            "typed_owned_policy_close_required",
        )
        close.__post_init__()
        index = close.session_index
        _check(
            index in sessions
            and index not in seen
            and (previous is None or index > previous)
            and close.family == family
            and close.information_at == sessions[index].closes_at,
            "policy_coverage_clock_family_or_order_mismatch",
        )
        seen.add(index)
        previous = index
        for condition in close.conditions:
            if isinstance(condition, KnownPolicyCondition):
                following = sessions.get(index + 1)
                _check(
                    following is not None
                    and condition.proposal.execute_not_before == following.opens_at,
                    "policy_proposal_has_no_matching_next_native_open",
                )
            else:
                _check(
                    type(condition) is UnavailablePolicyCondition
                    and type(condition.outcome.code) is str
                    and bool(condition.outcome.code)
                    and type(condition.outcome.reason) is str,
                    "typed_policy_unavailability_required",
                )
    missing = tuple(
        (session.index, symbol)
        for session in expected
        if session.index not in seen
        for symbol in STOCK_POLICY_SYMBOLS
    )
    identity = _digest("monetary-policy-coverage-input-v1", (closes, expected, family))
    full = _build_policy_window(
        closes,
        expected,
        baseline_index=expected[0].index,
        terminal_index=expected[-1].index,
        inventory_hash=identity,
    )
    return MonetaryPolicyCoverage(
        closes,
        expected,
        family,
        len(expected) * 8,
        len(closes) * 8,
        8 if expected[-1].index in seen else 0,
        missing,
        full,
        identity,
    )


def _policy_window(
    coverage: MonetaryPolicyCoverage,
    *,
    baseline_index: int,
    terminal_index: int,
) -> MonetaryPolicyWindow:
    return _build_policy_window(
        coverage.closes,
        coverage.expected_calendar,
        baseline_index=baseline_index,
        terminal_index=terminal_index,
        inventory_hash=coverage.input_evidence_hash,
    )


@dataclass(frozen=True, slots=True)
class _MetricWindow:
    name: str
    baseline_index: int
    terminal_index: int

    def __post_init__(self) -> None:
        _check(
            type(self.name) is str
            and 0 < len(self.name) <= 128
            and type(self.baseline_index) is type(self.terminal_index) is int
            and self.baseline_index < self.terminal_index,
            "invalid_monetary_metric_window",
        )


_PUBLIC_WINDOWS = (
    _MetricWindow("full", 199, 705),
    _MetricWindow("train", 199, 437),
    _MetricWindow("late", 437, 705),
)
_REPLAY_LIMITATIONS = (
    *(
        item
        for item in _INCOMPLETE
        if item != "operating_expense_and_statistical_edge_qualification_not_implemented"
    ),
    "modeled_budget_not_observed_spending_or_statistical_edge_qualification",
    "conditional_observed_cash_reference_not_full_constrained_strategy_evaluation",
    "long_term_reference_restores_75pct_SPY_underweight_at_ordinary_closes",
    "quarterly_5pp_rebalancing_not_implemented_or_evaluated",
    "corporate_action_conversion_volatility_exit_and_quality_allocator_incomplete",
    "estimated_after_provision_not_paid_tax_or_actual_after_tax_performance",
    "latest_retrieval_is_not_native_historical_publication_or_fresh_holdout",
)
_EXPOSURE_KEYS = (
    "mean_gross_equity",
    "long_term_exposure",
    "tactical_exposure",
    "equity_exposure",
    "cash_ratio",
    "unsettled_ratio",
    "receivable_ratio",
    "tax_reserve_ratio",
    "mean_close_known_liability_ratio",
    "sector_exposure",
    "portfolio_correlation",
    "attribution",
)
_EXECUTION_KEYS = (
    "filled_count",
    "buy_notional",
    "sell_notional",
    "two_way_turnover",
    "annualized_two_way_turnover",
    "half_turnover",
    "execution_fees_to_starting_capital",
    "paid_operating_expenses_to_starting_capital",
    "denied_count",
    "rejected_count",
    "cancelled_count",
)


@dataclass(frozen=True, slots=True)
class _CaseMetricFacts:
    spec: RetrospectiveCaseSpec
    book: DividendBook
    snapshots: tuple[EconomicReplaySnapshot, ...]
    cost_marks: tuple[EconomicReplayCostMark, ...]
    records: tuple[EconomicReplayRecord, ...]
    policy_closes: tuple[EconomicPolicyClose, ...]
    calendar: tuple[CalendarSession, ...]
    native_last_index: int
    source_root: str


@dataclass(frozen=True, slots=True)
class MonetarySegmentMetrics(_Scope):
    name: str
    baseline_index: int
    terminal_index: int
    expected_mark_count: int
    expected_return_count: int
    gross: MonetaryCurveMetrics | None
    net: MonetaryCurveMetrics | None
    after_provision: MonetaryCurveMetrics | None
    exposure_metrics: tuple[tuple[str, MetricValue], ...]
    execution_metrics: tuple[tuple[str, MetricValue], ...]
    episode_metrics: _EpisodeMetrics | None
    policy_coverage: MonetaryPolicyWindow | None
    unknown_liability_indices: tuple[int, ...]
    unknown_liability_ids: tuple[str, ...]
    missing_cost_indices: tuple[int, ...]
    unavailable_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MonetaryCaseMetrics(_Scope):
    case_hash: str
    source_root: str
    family: str
    exit_method: str
    long_term_profile: str
    tax_rate: Decimal | None
    operating_plan_hash: str
    status: Literal["summarized", "unavailable"]
    reasons: tuple[str, ...]
    segments: tuple[MonetarySegmentMetrics, ...]
    policy_coverage: MonetaryPolicyCoverage | None
    expected_policy_audit_slots: int
    expected_policy_executable_slots: int
    execution_audit: _ExecutionAudit | None
    case_spec: RetrospectiveCaseSpec
    account_evidence_hash: str | None
    replay_limitations: tuple[str, ...] = field(default=_REPLAY_LIMITATIONS, init=False)
    expected_policy_symbols: tuple[str, ...] = field(default=STOCK_POLICY_SYMBOLS, init=False)

    def _validate_identity(self) -> None:
        self._scope()
        self.case_spec.__post_init__()
        _registered_rate(self.tax_rate)
        _require_sha256_hex(self.source_root, "metric_case_source")
        _check(
            self.case_hash == self.case_spec.evidence_hash
            and self.family == self.case_spec.family
            and self.exit_method == self.case_spec.protocol.exit_method
            and self.long_term_profile == self.case_spec.long_term_profile
            and self.tax_rate == self.case_spec.protocol.tax_rate
            and self.operating_plan_hash == self.case_spec.operating_cost_plan.evidence_hash
            and self.replay_limitations == _REPLAY_LIMITATIONS
            and self.expected_policy_symbols == STOCK_POLICY_SYMBOLS
            and bool(self.segments)
            and self.expected_policy_audit_slots == self.segments[0].expected_mark_count * 8
            and self.expected_policy_executable_slots == self.segments[0].expected_return_count * 8,
            "metric_case_identity_or_denominator_changed",
        )
        if self.status == "unavailable":
            _check(
                bool(self.reasons)
                and self.account_evidence_hash is None
                and self.policy_coverage is None
                and self.execution_audit is None
                and all(
                    segment.gross is segment.net is segment.after_provision is None
                    for segment in self.segments
                ),
                "unavailable_case_cannot_be_a_cash_curve",
            )
        else:
            _check(
                self.status == "summarized"
                and self.account_evidence_hash is not None
                and self.policy_coverage is not None
                and self.execution_audit is not None,
                "summarized_case_identity_missing",
            )
            if self.account_evidence_hash is not None:
                _require_sha256_hex(self.account_evidence_hash, "continuous_model_account")

    @property
    def evidence_hash(self) -> str:
        self._validate_identity()
        return _digest("stock-monetary-case-metrics-v1", self)


def _unavailable_table(keys: tuple[str, ...], reason: str) -> tuple[tuple[str, MetricValue], ...]:
    return tuple((key, MetricValue(None, reason)) for key in keys)


def _unavailable_case(
    spec: RetrospectiveCaseSpec,
    *,
    source_root: str,
    reasons: tuple[str, ...],
    windows: tuple[_MetricWindow, ...] = _PUBLIC_WINDOWS,
) -> MonetaryCaseMetrics:
    _check(bool(reasons), "missing_case_unavailability_reason")
    segments = tuple(
        MonetarySegmentMetrics(
            window.name,
            window.baseline_index,
            window.terminal_index,
            window.terminal_index - window.baseline_index + 1,
            window.terminal_index - window.baseline_index,
            None,
            None,
            None,
            _unavailable_table(_EXPOSURE_KEYS, "case_unavailable"),
            _unavailable_table(_EXECUTION_KEYS, "case_unavailable"),
            None,
            None,
            (),
            (),
            (),
            reasons,
        )
        for window in windows
    )
    full = windows[0]
    return MonetaryCaseMetrics(
        spec.evidence_hash,
        source_root,
        spec.family,
        spec.protocol.exit_method,
        spec.long_term_profile,
        spec.protocol.tax_rate,
        spec.operating_cost_plan.evidence_hash,
        "unavailable",
        reasons,
        segments,
        None,
        (full.terminal_index - full.baseline_index + 1) * 8,
        (full.terminal_index - full.baseline_index) * 8,
        None,
        case_spec=spec,
        account_evidence_hash=None,
    )


def _exposures(
    snapshots: dict[int, EconomicReplaySnapshot],
    projections: dict[int, _ProjectedRow],
    post_indices: tuple[int, ...],
) -> tuple[tuple[str, MetricValue], ...]:
    if not post_indices or any(
        index not in snapshots or snapshots[index].gross_equity <= 0 for index in post_indices
    ):
        return _unavailable_table(_EXPOSURE_KEYS, "missing_or_nonpositive_gross_observation")
    rows = tuple(snapshots[index] for index in post_indices)
    n = Decimal(len(rows))
    values = {
        "mean_gross_equity": MetricValue(sum((row.gross_equity for row in rows), _ZERO) / n),
        "long_term_exposure": MetricValue(
            sum((row.long_term_value / row.gross_equity for row in rows), _ZERO) / n
        ),
        "tactical_exposure": MetricValue(
            sum((row.tactical_value / row.gross_equity for row in rows), _ZERO) / n
        ),
        "equity_exposure": MetricValue(
            sum(
                ((row.long_term_value + row.tactical_value) / row.gross_equity for row in rows),
                _ZERO,
            )
            / n
        ),
        "cash_ratio": MetricValue(sum((row.cash / row.gross_equity for row in rows), _ZERO) / n),
        "unsettled_ratio": MetricValue(
            sum((row.unsettled / row.gross_equity for row in rows), _ZERO) / n
        ),
        "receivable_ratio": MetricValue(
            sum((row.receivable / row.gross_equity for row in rows), _ZERO) / n
        ),
        "tax_reserve_ratio": MetricValue(
            sum((row.tax_reserve / row.gross_equity for row in rows), _ZERO) / n
        ),
        "sector_exposure": MetricValue(None, "sector_inputs_unavailable"),
        "portfolio_correlation": MetricValue(None, "correlation_estimator_not_registered"),
        "attribution": MetricValue(None, "attribution_estimator_not_registered"),
    }
    due = tuple(projections[index].known_due for index in post_indices)
    values["mean_close_known_liability_ratio"] = (
        MetricValue(None, "missing_close_cost_observation")
        if any(value is None for value in due)
        else MetricValue(
            sum(
                (
                    value / row.gross_equity
                    for value, row in zip(due, rows, strict=True)
                    if value is not None
                ),
                _ZERO,
            )
            / n
        )
    )
    return tuple((key, values[key]) for key in _EXPOSURE_KEYS)


def _execution_metrics(
    facts: _CaseMetricFacts,
    audit: _ExecutionAudit,
    *,
    baseline_at: datetime,
    terminal_at: datetime,
    mean_gross: Decimal | int | None,
    return_count: int,
) -> tuple[tuple[str, MetricValue], ...]:
    values = dict(_unavailable_table(_EXECUTION_KEYS, "execution_provenance_unavailable"))
    if audit.available:
        fills = tuple(item for item in audit.fills if baseline_at < item.fill.at <= terminal_at)
        buys = sum(
            (item.fill.quantity * item.fill.price for item in fills if item.order.side == "buy"),
            _ZERO,
        )
        sells = sum(
            (item.fill.quantity * item.fill.price for item in fills if item.order.side == "sell"),
            _ZERO,
        )
        fees = sum((item.fill.fee for item in fills), _ZERO)
        values.update(
            {
                "filled_count": MetricValue(len(fills)),
                "buy_notional": MetricValue(buys),
                "sell_notional": MetricValue(sells),
                "execution_fees_to_starting_capital": MetricValue(
                    fees / facts.book.account.starting_capital
                ),
            }
        )
        if type(mean_gross) is Decimal and mean_gross > 0:
            turnover = (buys + sells) / mean_gross
            values.update(
                {
                    "two_way_turnover": MetricValue(turnover),
                    "annualized_two_way_turnover": MetricValue(turnover * 252 / return_count),
                    "half_turnover": MetricValue(turnover / 2),
                }
            )
        else:
            for key in ("two_way_turnover", "annualized_two_way_turnover", "half_turnover"):
                values[key] = MetricValue(None, "missing_gross_turnover_denominator")
    paid = sum(
        (
            step.gross_amount
            for step in facts.book.trace
            if step.action == "operating_expense" and baseline_at < step.at <= terminal_at
        ),
        _ZERO,
    )
    values["paid_operating_expenses_to_starting_capital"] = MetricValue(
        paid / facts.book.account.starting_capital
    )
    for outcome in ("denied", "rejected", "cancelled"):
        values[outcome + "_count"] = MetricValue(
            sum(
                row.outcome == outcome and baseline_at < row.at <= terminal_at
                for row in facts.records
            )
        )
    return tuple((key, values[key]) for key in _EXECUTION_KEYS)


def _window_curve(
    points: tuple[_CurveObservation, ...],
    *,
    expected: tuple[CalendarSession, ...],
    activation_calendar: tuple[CalendarSession, ...],
) -> MonetaryCurveMetrics:
    baseline, terminal = expected[0].index, expected[-1].index
    part = tuple(point for point in points if baseline <= point.session_index <= terminal)
    by_index = {point.session_index: point for point in points}
    prefix = tuple(
        by_index.get(
            session.index,
            _CurveObservation(session.index, session.closes_at, None, "missing_prior_mark"),
        )
        for session in activation_calendar
        if session.index <= baseline
    )
    return _curve(part, expected=expected, prefix=prefix)


def _summarize_case(
    facts: _CaseMetricFacts,
    *,
    windows: tuple[_MetricWindow, ...] = _PUBLIC_WINDOWS,
) -> MonetaryCaseMetrics:
    """Audit one case once, sharing owned facts and expected axes across every segment."""
    with localcontext(_CONTEXT):
        _check(
            type(facts) is _CaseMetricFacts and type(facts.spec) is RetrospectiveCaseSpec,
            "owned_metric_case_facts_required",
        )
        facts.spec.__post_init__()
        _registered_rate(facts.spec.protocol.tax_rate)
        _check(
            facts.book.tax_rate == facts.spec.protocol.tax_rate,
            "metric_tax_scenario_changed_after_simulation",
        )
        _expected_calendar(facts.calendar)
        native = tuple(
            session for session in facts.calendar if 199 <= session.index <= facts.native_last_index
        )
        _expected_calendar(native)
        _check(
            native[0].index == 199
            and native[-1].index == facts.native_last_index
            and facts.book.through_at == native[-1].closes_at,
            "case_native_terminal_clock_mismatch",
        )
        activation = next(session.opens_at for session in native if session.index == 200)
        _check(type(windows) is tuple and bool(windows), "registered_metric_windows_required")
        for window in windows:
            window.__post_init__()
            _check(
                native[0].index
                <= window.baseline_index
                < window.terminal_index
                <= native[-1].index,
                "metric_window_outside_native_axis",
            )
        close_marks: dict[int, EconomicReplayCostMark] = {}
        for mark in facts.cost_marks:
            mark.__post_init__()
            if mark.phase == "close":
                _check(
                    mark.session_index not in close_marks
                    and 200 <= mark.session_index <= facts.native_last_index,
                    "duplicate_or_padded_close_cost_mark",
                )
                close_marks[mark.session_index] = mark
        snapshots: dict[int, EconomicReplaySnapshot] = {}
        projections: dict[int, _ProjectedRow] = {}
        previous = None
        for snapshot in facts.snapshots:
            _check(
                snapshot.session_index not in snapshots
                and 199 <= snapshot.session_index <= facts.native_last_index
                and (previous is None or snapshot.session_index > previous),
                "duplicate_reordered_or_padded_snapshot",
            )
            previous = snapshot.session_index
            snapshots[snapshot.session_index] = snapshot
            projections[snapshot.session_index] = _project_row(
                snapshot,
                close_marks.get(snapshot.session_index),
                rate=facts.spec.protocol.tax_rate,
                plan=facts.spec.operating_cost_plan,
                activation_at=activation,
                baseline=snapshot.session_index == 199,
            )
        audit = _audit_executions(
            facts.book,
            facts.records,
            calendar=facts.calendar,
            rate=facts.spec.protocol.tax_rate,
            native_last_index=facts.native_last_index,
        )
        coverage = _policy_coverage(facts.policy_closes, expected=native, family=facts.spec.family)
        all_g = tuple(
            _CurveObservation(row.session_index, row.at, row.gross) for row in projections.values()
        )
        all_n = tuple(
            _CurveObservation(row.session_index, row.at, row.net, row.net_reason)
            for row in projections.values()
        )
        all_a = tuple(
            _CurveObservation(row.session_index, row.at, row.after_provision, row.after_reason)
            for row in projections.values()
        )
        segments = []
        for window in windows:
            expected = tuple(
                session
                for session in native
                if window.baseline_index <= session.index <= window.terminal_index
            )

            gross = _window_curve(all_g, expected=expected, activation_calendar=native)
            net = _window_curve(all_n, expected=expected, activation_calendar=native)
            after = _window_curve(all_a, expected=expected, activation_calendar=native)
            post = tuple(session.index for session in expected[1:])
            exposure = _exposures(snapshots, projections, post)
            execution = _execution_metrics(
                facts,
                audit,
                baseline_at=expected[0].closes_at,
                terminal_at=expected[-1].closes_at,
                mean_gross=dict(exposure)["mean_gross_equity"].value,
                return_count=len(post),
            )
            unknown_rows = tuple(
                index for index in post if index in projections and projections[index].unknown_ids
            )
            unknown_ids = tuple(
                sorted(
                    {
                        identity
                        for index in unknown_rows
                        for identity in projections[index].unknown_ids
                    }
                )
            )
            missing_costs = tuple(
                index
                for index in post
                if index in projections and projections[index].known_due is None
            )
            segments.append(
                MonetarySegmentMetrics(
                    window.name,
                    window.baseline_index,
                    window.terminal_index,
                    len(expected),
                    len(expected) - 1,
                    gross,
                    net,
                    after,
                    exposure,
                    execution,
                    _episode_metrics(
                        audit, baseline_at=expected[0].closes_at, terminal_at=expected[-1].closes_at
                    ),
                    _policy_window(
                        coverage,
                        baseline_index=window.baseline_index,
                        terminal_index=window.terminal_index,
                    ),
                    unknown_rows,
                    unknown_ids,
                    missing_costs,
                    (),
                )
            )
        return MonetaryCaseMetrics(
            facts.spec.evidence_hash,
            facts.source_root,
            facts.spec.family,
            facts.spec.protocol.exit_method,
            facts.spec.long_term_profile,
            facts.spec.protocol.tax_rate,
            facts.spec.operating_cost_plan.evidence_hash,
            "summarized",
            (),
            tuple(segments),
            coverage,
            len(native) * 8,
            (len(native) - 1) * 8,
            audit,
            case_spec=facts.spec,
            account_evidence_hash=facts.book.evidence_hash,
        )


@dataclass(frozen=True, slots=True)
class MetricUnavailableSlot:
    slot_id: str
    reason: str

    def __post_init__(self) -> None:
        _check(
            type(self.slot_id) is type(self.reason) is str
            and 0 < len(self.slot_id) <= 256
            and 0 < len(self.reason) <= 2048
            and self.slot_id.isprintable()
            and self.reason.isprintable(),
            "typed_unavailable_comparison_slot_required",
        )


@dataclass(frozen=True, slots=True)
class MonetaryMetricRegistration:
    source_root: str
    expected_case_hashes: tuple[str, ...]
    code_revision: str
    code_tree: str
    source_inventory_hash: str
    expected_native_calendar_hash: str
    unavailable_comparison_slots: tuple[MetricUnavailableSlot, ...] = ()
    definition_hash: str = DEFINITION_HASH
    clarification_hash: str = CLARIFICATION_HASH

    def __post_init__(self) -> None:
        for value in (
            self.source_root,
            self.source_inventory_hash,
            self.expected_native_calendar_hash,
        ):
            _require_sha256_hex(value, "metric_registration")
        _check(
            type(self.expected_case_hashes) is tuple
            and 1 <= len(self.expected_case_hashes) <= 512
            and len(set(self.expected_case_hashes)) == len(self.expected_case_hashes),
            "bounded_unique_registered_metric_cases_required",
        )
        for value in self.expected_case_hashes:
            _require_sha256_hex(value, "registered_metric_case")
        for value in (self.code_revision, self.code_tree):
            _check(
                type(value) is str
                and len(value) == 40
                and all(c in "0123456789abcdef" for c in value),
                "metric_code_identity_binding_required",
            )
        _check(
            self.definition_hash == DEFINITION_HASH
            and self.clarification_hash == CLARIFICATION_HASH,
            "metric_definition_or_lifecycle_version_changed",
        )
        _check(
            type(self.unavailable_comparison_slots) is tuple
            and len(self.unavailable_comparison_slots) <= 10000,
            "immutable_missing_comparison_inventory_required",
        )
        for slot in self.unavailable_comparison_slots:
            _check(type(slot) is MetricUnavailableSlot, "typed_missing_comparison_slot_required")
            slot.__post_init__()
        _check(
            len({slot.slot_id for slot in self.unavailable_comparison_slots})
            == len(self.unavailable_comparison_slots),
            "duplicate_unavailable_comparison_slot",
        )


def monetary_native_calendar_hash(calendar: tuple[CalendarSession, ...]) -> str:
    """Hash the fixed native calendar, never authenticate it or turn padding into prices."""
    _expected_calendar(calendar)
    native = tuple(session for session in calendar if session.index <= 705)
    _check(
        len(native) == 706 and native[0].index == 0 and native[-1].index == 705,
        "full706_native_metric_calendar_required",
    )
    return _digest("stock-monetary-metric-native-calendar-v1", native)


@dataclass(frozen=True, slots=True)
class MonetaryMetricReport(_Scope):
    registration: MonetaryMetricRegistration
    source_result_hash: str
    cases: tuple[MonetaryCaseMetrics, ...]
    full_constrained_cases: tuple[MonetaryCaseDependency, ...]
    long_term_quality_slots: tuple[tuple[str, str], ...]
    conditional_convention: RetrospectiveReplayConvention
    families: tuple[str, ...] = field(default=FAMILIES, init=False)
    reused_late_window: Literal[True] = field(default=True, init=False)
    definition_parent_hashes: tuple[str, ...] = field(
        default=(DEFINITION_HASH, CLARIFICATION_PARENT_HASH), init=False
    )
    code_identity_scope: str = field(
        default="controller_supplied_binding_not_git_authentication", init=False
    )
    schema: str = field(default="stock-monetary-descriptive-metrics-v1", init=False)
    replay_limitations: tuple[str, ...] = field(default=_REPLAY_LIMITATIONS, init=False)

    @property
    def evidence_hash(self) -> str:
        self._scope()
        self.registration.__post_init__()
        _require_sha256_hex(self.source_result_hash, "metric_source_result")
        _check(
            type(self.cases) is tuple
            and tuple(case.case_hash for case in self.cases)
            == self.registration.expected_case_hashes
            and len(self.full_constrained_cases) == 56
            and len(self.long_term_quality_slots) == 8
            and self.families == FAMILIES
            and self.reused_late_window is True
            and self.definition_parent_hashes == (DEFINITION_HASH, CLARIFICATION_PARENT_HASH)
            and self.code_identity_scope == "controller_supplied_binding_not_git_authentication"
            and self.schema == "stock-monetary-descriptive-metrics-v1"
            and self.replay_limitations == _REPLAY_LIMITATIONS,
            "metric_report_inventory_or_scope_changed",
        )
        _check(
            tuple((row.symbol, row.family) for row in self.full_constrained_cases)
            == tuple((symbol, family) for symbol in STOCK_POLICY_SYMBOLS for family in FAMILIES)
            and all(
                type(row) is MonetaryCaseDependency and row.evaluation_status == "unavailable"
                for row in self.full_constrained_cases
            )
            and self.long_term_quality_slots
            == tuple(
                (symbol, "quality_stock_allocator_unavailable") for symbol in STOCK_POLICY_SYMBOLS
            )
            and self.conditional_convention == RetrospectiveReplayConvention(),
            "metric_missing_inventory_or_conditional_scope_changed",
        )
        expected_windows = tuple(
            (window.name, window.baseline_index, window.terminal_index)
            for window in _PUBLIC_WINDOWS
        )
        for case in self.cases:
            case._validate_identity()
            _check(
                tuple(
                    (segment.name, segment.baseline_index, segment.terminal_index)
                    for segment in case.segments
                )
                == expected_windows,
                "public_metric_report_requires_full706_windows",
            )
        return _digest("stock-monetary-metric-report-v1", self)


def summarize_retrospective_monetary_result(
    result: RetrospectiveEconomicReplayResult,
    *,
    fresh_inputs: PreparedRetrospectiveReplayInputs,
    registration: MonetaryMetricRegistration,
) -> MonetaryMetricReport:
    """Fresh source-bound descriptive report; no strategy, cash transition or inference."""
    with localcontext(_CONTEXT):
        _check(
            type(result) is RetrospectiveEconomicReplayResult
            and type(fresh_inputs) is PreparedRetrospectiveReplayInputs
            and type(registration) is MonetaryMetricRegistration,
            "completed_source_bound_metric_inputs_required",
        )
        registration.__post_init__()
        finished = finish_retrospective_economic_replay(result.state, fresh_inputs=fresh_inputs)
        _check(
            result.source_root == finished.source_root == registration.source_root,
            "registered_metric_source_root_changed",
        )
        source_hash = result.evidence_hash
        state = finished.state
        _check(
            monetary_native_calendar_hash(state.panel.calendar)
            == registration.expected_native_calendar_hash
            and tuple(case.spec_hash for case in state.cases) == registration.expected_case_hashes,
            "registered_metric_calendar_or_cases_changed",
        )
        cases = []
        for case in state.cases:
            _registered_rate(case.spec.protocol.tax_rate)
            if case.core is None:
                cases.append(
                    _unavailable_case(
                        case.spec, source_root=result.source_root, reasons=case.unavailable_reasons
                    )
                )
            else:
                core = case.core
                facts = _CaseMetricFacts(
                    case.spec,
                    core.book,
                    core.snapshots,
                    core.cost_marks,
                    core.records,
                    core.policy_closes,
                    state.panel.calendar,
                    705,
                    result.source_root,
                )
                cases.append(_summarize_case(facts))
        report = MonetaryMetricReport(
            registration,
            source_hash,
            tuple(cases),
            state.full_constrained_cases,
            state.long_term_quality_slots,
            fresh_inputs.convention,
        )
        _ = report.evidence_hash
        return report
