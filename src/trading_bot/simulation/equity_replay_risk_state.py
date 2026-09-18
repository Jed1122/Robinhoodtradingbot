"""Observed synthetic equity history; no reconciliation or production evidence is minted."""

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal, localcontext
from typing import Literal

from trading_bot.domain import InstrumentId, OrderPurpose, PortfolioSnapshot, Quote, Side
from trading_bot.domain.decimal_utils import require_bounded_decimal
from trading_bot.risk.losses import (
    ActivitySnapshot,
    LossDecision,
    LossSnapshot,
    evaluate_loss_limits,
)
from trading_bot.simulation.equity_replay_codec import replay_identity
from trading_bot.simulation.equity_replay_models import (
    EquityStrategyReplayRequest,
    checked,
    deny,
    utc,
)
from trading_bot.simulation.equity_replay_policy import ReplayEntryPolicy, validate_policy
from trading_bot.simulation.equity_replay_portfolio import ReplayOrderRecord, ReplayPortfolio
from trading_bot.simulation.lifecycle_accounting import _context

ZERO = Decimal(0)


def _windows(at: datetime) -> tuple[datetime, datetime]:
    daily = at.replace(hour=0, minute=0, second=0, microsecond=0)
    return daily, daily - timedelta(days=daily.weekday())


def _decline(baseline: Decimal | None, equity: Decimal) -> Decimal:
    if baseline is None or baseline == 0 or equity >= baseline:
        return ZERO
    # Upward rounding cannot move a repeating percentage below an economic threshold.
    # This computes a synthetic observation, not another limit or fill model.
    with localcontext(_context(exact=False)) as context:
        context.rounding = ROUND_CEILING
        value = (baseline - equity) * Decimal(100) / baseline
    return require_bounded_decimal(value, "loss_percentage", nonnegative=True)


def _loss_streak(orders: tuple[ReplayOrderRecord, ...]) -> tuple[int, datetime | None]:
    flows: dict[InstrumentId, Decimal] = {}
    outcomes: list[tuple[datetime, str, Decimal]] = []
    for record in orders:
        symbol = record.intent.instrument_id
        flows[symbol] = (
            flows.get(symbol, ZERO) + record.lifecycle.snapshot.cash - record.initial.cash
        )
        if record.lifecycle.order_terminal and record.lifecycle.snapshot.position.quantity == 0:
            outcomes.append(
                (
                    record.lifecycle.snapshot.cursor.occurred_at,
                    record.initial.order.id,
                    flows.pop(symbol),
                )
            )
    count, last = 0, None
    for at, _, cash_flow in sorted(outcomes):
        if cash_flow < 0:
            count, last = count + 1, at
        elif cash_flow > 0:
            count, last = 0, None
        # No-fill/rejected or break-even orders cannot clear a loss pause.
    return count, last


class ReplayRiskState:
    """Single-owner observations bound to one synthetic book and immutable scenario.

    The coordinator must observe each event/decision's fresh marked portfolio. Only an
    observation at a new UTC boundary establishes that new period's baseline. These
    synthetic baseline flags must never be passed off as broker reconciliation or review.
    """

    def __init__(self, request: EquityStrategyReplayRequest, portfolio: ReplayPortfolio) -> None:
        with checked():
            if (
                type(request) is not EquityStrategyReplayRequest
                or type(portfolio) is not ReplayPortfolio
            ):
                deny()
            self._request = replace(request)
            self._identity = replay_identity(self._request)
            if portfolio.request_identity != self._identity or portfolio.orders:
                deny("replay_risk_identity_invalid")
            self._portfolio = portfolio
            self._snapshot = portfolio.snapshot(request.starts_at, ())
            self._orders = portfolio.orders
            self._quotes: tuple[Quote, ...] = ()
            self._policies: tuple[ReplayEntryPolicy, ...] = ()
            self._daily_at, self._weekly_at = _windows(request.starts_at)
            # A newly created synthetic account starts flat; no pre-creation history is inferred.
            self._daily_base: Decimal | None = request.initial_cash
            self._weekly_base: Decimal | None = request.initial_cash
            self._peak = request.initial_cash
            self._drawdown = ZERO

    @property
    def evidence_promotable(self) -> Literal[False]:
        return False

    @property
    def production_pretrade_eligible(self) -> Literal[False]:
        return False

    def observe(
        self,
        as_of: datetime,
        quotes: tuple[Quote, ...],
        *,
        entry_policies: tuple[ReplayEntryPolicy, ...] = (),
    ) -> PortfolioSnapshot:
        with checked():
            utc(as_of)
            if as_of < self._snapshot.observed_at or type(entry_policies) is not tuple:
                deny("replay_ordering_invalid")
            self._require_observed_prefix(as_of)
            seen: set[InstrumentId] = set()
            for policy in entry_policies:
                validate_policy(policy, self._request)
                if (
                    policy.instrument_id in seen
                    or policy.observed_at != as_of
                    or policy.first_fill_at is not None
                ):
                    deny("replay_policy_identity_invalid")
                seen.add(policy.instrument_id)
            candidate = self._portfolio.snapshot(as_of, quotes)
            supplied = {q.instrument_id: q for q in quotes}
            for position in candidate.positions:
                visible = tuple(
                    e.quote
                    for e in self._request.markets
                    if e.quote.instrument_id == position.instrument_id
                    and e.quote.observed_at <= as_of
                )
                if not visible or supplied.get(position.instrument_id) != max(
                    visible, key=lambda quote: quote.observed_at
                ):
                    deny("replay_risk_mark_not_latest")
            daily, weekly = _windows(as_of)
            daily_base = (
                self._daily_base
                if daily == self._daily_at
                else (candidate.equity if as_of == daily else None)
            )
            weekly_base = (
                self._weekly_base
                if weekly == self._weekly_at
                else (candidate.equity if as_of == weekly else None)
            )
            peak = max(self._peak, candidate.equity)
            drawdown = max(self._drawdown, _decline(peak, candidate.equity))
            self._snapshot, self._quotes, self._orders = candidate, quotes, self._portfolio.orders
            self._policies = entry_policies
            self._daily_at, self._weekly_at = daily, weekly
            self._daily_base, self._weekly_base = daily_base, weekly_base
            self._peak, self._drawdown = peak, drawdown
            return candidate

    def _require_observed_prefix(self, as_of: datetime) -> None:
        previous = {o.initial.order.id: o for o in self._orders}
        for record in self._portfolio.orders:
            old = previous.get(record.initial.order.id)
            offset = len(old.result.events) if old is not None and old.result is not None else 0
            if record.result is not None and any(
                self._snapshot.observed_at < e.cursor.occurred_at < as_of
                for e in record.result.events[offset:]
            ):
                deny("replay_risk_history_gap")
        exposed = {p.instrument_id for p in self._snapshot.positions}
        if any(
            e.quote.instrument_id in exposed
            and self._snapshot.observed_at < e.quote.observed_at < as_of
            for e in self._request.markets
        ):
            deny("replay_risk_history_gap")

    def current(self, request: EquityStrategyReplayRequest, now: datetime) -> PortfolioSnapshot:
        with checked():
            utc(now)
            if replay_identity(request) != self._identity:
                deny("replay_risk_identity_invalid")
            if (
                now != self._snapshot.observed_at
                or self._portfolio.orders != self._orders
                or self._portfolio.snapshot(now, self._quotes) != self._snapshot
            ):
                deny("replay_risk_state_stale")
            return self._snapshot

    def policy(self, version: str | None) -> ReplayEntryPolicy | None:
        return next((p for p in self._policies if p.version == version), None)

    @property
    def orders(self) -> tuple[ReplayOrderRecord, ...]:
        return self._orders

    @property
    def allocatable_cash(self) -> Decimal:
        return self._portfolio.allocatable_cash

    def loss_snapshot(self) -> LossSnapshot:
        with checked():
            snapshot = self.current(self._request, self._snapshot.observed_at)
            count, last = _loss_streak(self._orders)
            return LossSnapshot(
                self._request.account_id,
                _decline(self._daily_base, snapshot.equity),
                _decline(self._weekly_base, snapshot.equity),
                self._drawdown,
                count,
                last,
                self._daily_at,
                self._weekly_at,
                self._daily_base is not None,
                self._weekly_base is not None,
                snapshot.observed_at,
            )

    def loss_decision(self, purpose: OrderPurpose) -> LossDecision:
        with checked():
            return evaluate_loss_limits(
                snapshot=self.loss_snapshot(),
                settings=self._request.loaded.config.loss_limits,
                purpose=purpose,
            )

    def activity_snapshot(self, symbol: InstrumentId) -> ActivitySnapshot:
        with checked():
            snapshot = self.current(self._request, self._snapshot.observed_at)
            entries = tuple(o.intent for o in self._orders if o.intent.side is Side.BUY)
            today = tuple(i for i in entries if i.created_at >= self._daily_at)
            return ActivitySnapshot(
                self._request.account_id,
                symbol,
                len(today),
                sum(i.instrument_id == symbol for i in today),
                max((i.created_at for i in entries), default=None),
                self._daily_at,
                snapshot.observed_at,
            )
