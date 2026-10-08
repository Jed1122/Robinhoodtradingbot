"""Bounded monthly research owner with pure, identity-checked prefix recovery.

All prices, fills and settlement clocks are declared simulation assumptions.
This is not a broker worker, durable runtime or promotion capability.
"""

from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal, localcontext
from typing import cast

from trading_bot.domain import InstrumentId, Side
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_daily_protocol import EtfDailyBar
from trading_bot.research.etf_monthly_protocol import (
    ANCHOR,
    EtfMonthlyError,
    EtfMonthlyProtocol,
    EtfMonthlyRequest,
    EtfMonthlySignal,
    EtfMonthObservation,
    _check,
    _markers,
    _MonthlyRecord,
    monthly_atr_inputs,
)
from trading_bot.simulation.etf_account import EtfAccountEvent, EtfAccountResult, _required
from trading_bot.simulation.etf_exploratory_lifecycle import (
    EtfDailyAttempt,
    EtfDailyExit,
    EtfDailyPoint,
    EtfExploratoryLifecycle,
    _Pending,
)
from trading_bot.simulation.lifecycle_accounting import _context
from trading_bot.strategies.etf_monthly_trend import compute_etf_monthly_signal
from trading_bot.strategies.features import FeaturePipeline
from trading_bot.strategies.protocol import HistoricalSlice


@dataclass(frozen=True, slots=True)
class EtfMonthlyDecision:
    session_date: date
    signal: EtfMonthlySignal | None
    atr_source_hashes: tuple[str, ...]
    data_hash: str
    scheduled: str | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EtfMonthlyAttempt(EtfDailyAttempt):
    pass


@dataclass(frozen=True, slots=True)
class EtfMonthlyExit(EtfDailyExit):
    pass


@dataclass(frozen=True, slots=True)
class EtfMonthlyPoint(EtfDailyPoint):
    pass


@dataclass(frozen=True, slots=True)
class EtfMonthlyCheckpoint(_MonthlyRecord):
    request_hash: str
    protocol_hash: str
    config_hash: str
    code_hash: str
    source_prefix_hash: str
    next_session_index: int
    month_window: tuple[EtfMonthObservation, ...]
    daily_window: tuple[EtfDailyBar, ...]
    decisions: tuple[EtfMonthlyDecision, ...]
    pending: _Pending | None
    entry_index: int | None
    entry_stop: Decimal
    stop: Decimal | None
    target: Decimal | None
    obligations: tuple[tuple[str, int], ...]
    entitlements: tuple[tuple[str, date], ...]
    events: tuple[EtfAccountEvent, ...]
    account: EtfAccountResult
    attempts: tuple[EtfMonthlyAttempt, ...]
    exits: tuple[EtfMonthlyExit, ...]
    points: tuple[EtfMonthlyPoint, ...]
    retained_reasons: tuple[str, ...]

    @property
    def checkpoint_hash(self) -> str:
        return content_hash(("etf-monthly-checkpoint-v1", self))


@dataclass(frozen=True, slots=True)
class EtfMonthlyResult(_MonthlyRecord):
    request: EtfMonthlyRequest
    decisions: tuple[EtfMonthlyDecision, ...]
    attempts: tuple[EtfMonthlyAttempt, ...]
    exits: tuple[EtfMonthlyExit, ...]
    points: tuple[EtfMonthlyPoint, ...]
    events: tuple[EtfAccountEvent, ...]
    account: EtfAccountResult
    incomplete_reasons: tuple[str, ...]
    checkpoint: EtfMonthlyCheckpoint

    @property
    def result_hash(self) -> str:
        return content_hash(("etf-monthly-result-v1", self))


class _Owner(EtfExploratoryLifecycle):
    request: EtfMonthlyRequest
    protocol: EtfMonthlyProtocol

    def __init__(self, request: EtfMonthlyRequest) -> None:
        super().__init__(request)
        self.decisions: list[EtfMonthlyDecision] = []
        self.next_index = self.protocol.sessions.index(ANCHOR)
        self.rows = {r.session_date: r for r in request.bars}
        self.month_days = self.protocol.month_end_sessions
        self.reasons: list[str] = []
        if self.protocol.price_basis == "unknown":
            self.reasons.append("price_action_basis_unknown")

    def reason(self, reason: str) -> None:
        if reason not in self.reasons:
            self.reasons.append(reason)

    def observations(self, index: int) -> tuple[EtfMonthObservation, ...]:
        last = self.protocol.sessions[index]
        months = tuple(d for d in self.month_days if d <= last)[-10:]
        return tuple(
            EtfMonthObservation(
                d.replace(day=1),
                d,
                self.rows[d].raw.ends_at,
                self.rows[d].raw.close,
                self.rows[d].raw.data_hash,
            )
            for d in months
            if d in self.rows
        )

    def decide(self, row: EtfDailyBar, index: int) -> None:
        observations = self.observations(index)
        digest = content_hash(("monthly-decision-input", self.protocol.protocol_hash, observations))
        signal = None
        hashes: tuple[str, ...] = ()
        scheduled = None
        reasons: tuple[str, ...] = ()
        try:
            signal = compute_etf_monthly_signal(
                observations, decision_at=row.raw.ends_at + timedelta(microseconds=1)
            )
            prior = monthly_atr_inputs(self.request, row.session_date)
            hashes = tuple(r.feature.data_hash for r in prior)
            feature = FeaturePipeline().compute(
                HistoricalSlice(InstrumentId("SPY"), tuple(r.feature for r in prior), None, digest),
                as_of=signal.decision_at,
            )
            atr = dict(feature.values)["average_true_range"]
            _check(type(atr) is Decimal)
            stop = cast(Decimal, atr) * self.cfg.equity_strategies.stop_loss_atr_multiplier
            digest = content_hash((digest, signal, feature))
            if self.state.shares and signal.regime == "CASH":
                scheduled = "monthly_cash_exit"
                self.pending = _Pending(Side.SELL, self.entry_stop, scheduled, digest)
            elif not self.state.shares and signal.regime == "LONG_ELIGIBLE" and stop > 0:
                scheduled = "entry"
                self.pending = _Pending(Side.BUY, stop, scheduled, digest)
        except EtfMonthlyError:
            reason = (
                "monthly_history_missing"
                if len(observations) != 10
                else "monthly_atr_history_missing"
            )
            reasons = (reason,)
            self.reason(reason)
        self.decisions.append(
            EtfMonthlyDecision(row.session_date, signal, hashes, digest, scheduled, reasons)
        )

    def advance(self, row: EtfDailyBar, index: int) -> None:
        if row.session_date != ANCHOR:
            self.opening(row, index)
            self.closing(row, index)
            if (
                self.state.shares
                and index - _required(self.entry_index) + 1
                >= self.cfg.equity_strategies.maximum_holding_bars
            ):
                self.pending = _Pending(
                    Side.SELL,
                    self.entry_stop,
                    "maximum_hold",
                    content_hash(("monthly-maximum-hold", row.raw.data_hash, self.entry_index)),
                )
        if row.session_date in self.month_days:
            self.decide(row, index)
        self.next_index = index + 1

    def run_until(self, stop: int) -> None:
        if self.reasons == ["price_action_basis_unknown"]:
            return
        while self.next_index < stop:
            index = self.next_index
            row = self.rows.get(self.protocol.sessions[index])
            if row is None:
                self.reason("missing_session_price")
                break
            self.advance(row, index)

    def result(self) -> EtfMonthlyResult:
        index = self.next_index
        consumed = self.protocol.sessions[:index]
        day = consumed[-1] if consumed else None
        daily = tuple(self.rows[d] for d in consumed[-100:] if d in self.rows)
        months = self.observations(index - 1) if index else ()
        attempts = tuple(
            EtfMonthlyAttempt(
                a.session_date, a.side, a.quantity, a.admitted, a.reason, a.decision_hash
            )
            for a in self.attempts
        )
        exits = tuple(
            EtfMonthlyExit(e.session_date, e.reason, e.assumed_price, e.fill_id) for e in self.exits
        )
        points = tuple(
            EtfMonthlyPoint(
                p.session_date,
                p.cash,
                p.settled_cash,
                p.shares,
                p.receivable,
                p.marked_nav,
                p.liquidation_proxy,
                p.reserved_trial,
                p.consumed_trial,
                p.source_hash,
                p.account_hash,
            )
            for p in self.points
        )
        prefix = content_hash(
            (
                "monthly-consumed-source-v1",
                consumed,
                tuple(r for r in self.request.bars if day is not None and r.session_date <= day),
                tuple(
                    d for d in self.request.distributions if day is not None and d.ex_date <= day
                ),
            )
        )
        checkpoint = EtfMonthlyCheckpoint(
            self.request.request_hash,
            self.protocol.protocol_hash,
            self.protocol.study.config_hash,
            self.protocol.study.code_hash,
            prefix,
            index,
            months,
            daily,
            tuple(self.decisions),
            self.pending,
            self.entry_index,
            self.entry_stop,
            self.stop,
            self.target,
            tuple(self.obligations.items()),
            tuple(self.entitlements.items()),
            tuple(self.events),
            self.state,
            attempts,
            exits,
            points,
            tuple(self.reasons),
        )
        incomplete = list(self.reasons)
        if self.pending is not None:
            incomplete.append("unattempted_scheduled_intent")
        if not self.state.complete:
            incomplete.append("open_account_obligations")
        return EtfMonthlyResult(
            self.request,
            tuple(self.decisions),
            attempts,
            exits,
            points,
            tuple(self.events),
            self.state,
            tuple(incomplete),
            checkpoint,
        )


def _owner(request: EtfMonthlyRequest) -> _Owner:
    _check(type(request) is EtfMonthlyRequest)
    request.__post_init__()
    return _Owner(replace(request))


def run_etf_monthly_screen(
    request: EtfMonthlyRequest, *, through_session: date | None = None
) -> EtfMonthlyResult:
    try:
        with localcontext(_context(exact=False)) as context:
            context.prec = 64
            owner = _owner(request)
            stop = len(request.protocol.sessions)
            if through_session is not None:
                _check(
                    type(through_session) is date and through_session in request.protocol.sessions
                )
                stop = request.protocol.sessions.index(through_session) + 1
                _check(stop >= owner.next_index)
            owner.run_until(stop)
            return owner.result()
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise EtfMonthlyError() from None


def _restored_owner(request: EtfMonthlyRequest, checkpoint: EtfMonthlyCheckpoint) -> _Owner:
    _check(type(checkpoint) is EtfMonthlyCheckpoint)
    _markers(checkpoint)
    _check(type(checkpoint.next_session_index) is int)
    _check(
        request.protocol.sessions.index(ANCHOR)
        <= checkpoint.next_session_index
        <= len(request.protocol.sessions)
    )
    _check(
        len(checkpoint.events) <= 10000
        and len(checkpoint.daily_window) <= 100
        and len(checkpoint.month_window) <= 10
    )
    owner = _owner(request)
    # Rebuild the deterministic prefix through the one reducer, then compare ALL
    # owner state before future advancement. No untrusted saved field is adopted.
    owner.run_until(checkpoint.next_session_index)
    if "missing_session_price" in checkpoint.retained_reasons:
        # The failed next observation did not consume a session. Reproduce that
        # halt before comparing the checkpoint, never advance its cursor.
        _check(checkpoint.next_session_index < len(request.protocol.sessions))
        owner.run_until(checkpoint.next_session_index + 1)
    _check(owner.result().checkpoint == checkpoint)
    return owner


def resume_etf_monthly_screen(
    request: EtfMonthlyRequest, checkpoint: EtfMonthlyCheckpoint
) -> EtfMonthlyResult:
    try:
        with localcontext(_context(exact=False)) as context:
            context.prec = 64
            owner = _restored_owner(request, checkpoint)
            owner.run_until(len(request.protocol.sessions))
            return owner.result()
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise EtfMonthlyError() from None


def checkpoint_etf_monthly_screen(result: EtfMonthlyResult) -> EtfMonthlyCheckpoint:
    verify_etf_monthly_result(result)
    return result.checkpoint


def verify_etf_monthly_result(result: EtfMonthlyResult) -> None:
    try:
        _check(type(result) is EtfMonthlyResult)
        _markers(result)
        with localcontext(_context(exact=False)) as context:
            context.prec = 64
            owner = _restored_owner(result.request, result.checkpoint)
            _check(owner.result() == result)
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise EtfMonthlyError() from None
