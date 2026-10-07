"""Assumption-based daily strategy lifecycle; never broker or market-fill evidence.

Daily bars supply adverse hypothetical prices, not quote events. The common
account owner remains authoritative for admission, obligations and trial losses.
The scheduler cannot resize around a denial or settle outside its frozen calendar.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from typing import cast

from trading_bot.domain import (
    AccountId,
    AssetClass,
    BrokerOrderId,
    ConfigHash,
    DataHash,
    Fill,
    FillId,
    Instrument,
    InstrumentId,
    OrderEvent,
    OrderIntent,
    OrderIntentId,
    OrderPurpose,
    OrderType,
    Side,
    TimeInForce,
)
from trading_bot.market_data.etf_source import _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.portfolio.sizing import SizingRequest, size_position
from trading_bot.research.etf_benchmark import _money_context
from trading_bot.research.etf_daily_protocol import (
    EtfDailyBar,
    EtfDailyError,
    EtfDailyRequest,
    _check,
    _DailyRecord,
)
from trading_bot.simulation.etf_account import (
    EtfAccountEvent,
    EtfAccountRequest,
    EtfAccountResult,
    EtfAccountStepper,
    _required,
    admit_etf_pending_intent,
    replay_etf_account,
)
from trading_bot.simulation.etf_history import _policy
from trading_bot.simulation.lifecycle_accounting import _context
from trading_bot.strategies.features import FeaturePipeline
from trading_bot.strategies.momentum import MomentumStrategy
from trading_bot.strategies.protocol import (
    FeatureSnapshot,
    HistoricalSlice,
    StrategyAction,
    StrategyContext,
)

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class EtfDailyDecision:
    session_date: date
    rebalance: bool
    signal: str | None
    feature_source_hashes: tuple[str, ...]
    data_hash: str
    scheduled: str | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EtfDailyAttempt:
    session_date: date
    side: Side
    quantity: Decimal
    admitted: bool
    reason: str
    decision_hash: str


@dataclass(frozen=True, slots=True)
class EtfDailyExit:
    session_date: date
    reason: str
    assumed_price: Decimal
    fill_id: str


@dataclass(frozen=True, slots=True)
class EtfDailyPoint:
    session_date: date
    cash: Decimal
    settled_cash: Decimal
    shares: Decimal
    receivable: Decimal
    marked_nav: Decimal
    liquidation_proxy: Decimal
    reserved_trial: Decimal
    consumed_trial: Decimal
    source_hash: str
    account_hash: str


@dataclass(frozen=True, slots=True)
class EtfDailyResult(_DailyRecord):
    request: EtfDailyRequest
    decisions: tuple[EtfDailyDecision, ...]
    attempts: tuple[EtfDailyAttempt, ...]
    exits: tuple[EtfDailyExit, ...]
    points: tuple[EtfDailyPoint, ...]
    events: tuple[EtfAccountEvent, ...]
    account: EtfAccountResult
    incomplete_reasons: tuple[str, ...]

    @property
    def result_hash(self) -> str:
        return content_hash({"schema": "etf-daily-result-v1", "result": self})


@dataclass(frozen=True, slots=True)
class _Pending:
    side: Side
    stop_distance: Decimal
    reason: str
    decision_hash: str


class _Owner:
    def __init__(self, request: EtfDailyRequest) -> None:
        self.request = request
        self.protocol = request.protocol
        self.cfg = _policy(self.protocol.study).config
        self.events: list[EtfAccountEvent] = []
        self.stepper = EtfAccountStepper(self.account_request())
        self.decisions: list[EtfDailyDecision] = []
        self.attempts: list[EtfDailyAttempt] = []
        self.exits: list[EtfDailyExit] = []
        self.points: list[EtfDailyPoint] = []
        self.obligations: dict[str, int] = {}
        self.entitlements: dict[str, date] = {}
        self.pending: _Pending | None = None
        self.entry_index: int | None = None
        self.stop: Decimal | None = None
        self.target: Decimal | None = None
        self.entry_stop = ZERO
        with localcontext(_money_context()):
            self.rate = self.protocol.per_side_cost_bps / Decimal("10000")

    @property
    def state(self) -> EtfAccountResult:
        return self.stepper.state

    def account_request(self) -> EtfAccountRequest:
        return EtfAccountRequest(self.protocol.study, self.request.initial_cash, tuple(self.events))

    def event(self, kind: str, at: datetime, **payload: object) -> EtfAccountEvent:
        # Only already consumed state and this fact enter identity, never future prices.
        return EtfAccountEvent(
            content_hash((self.protocol.protocol_hash, len(self.events), kind, at, payload)),
            len(self.events),
            _ns(at),
            kind,
            **payload,  # type: ignore[arg-type]
        )

    def apply(self, event: EtfAccountEvent) -> None:
        _check(len(self.events) < 10000)
        self.stepper.apply(event)
        self.events.append(event)

    def price(self, raw: Decimal, side: Side) -> Decimal:
        with localcontext(_money_context()):
            adverse = raw * (1 + self.rate if side is Side.BUY else 1 - self.rate)
            rounding = ROUND_CEILING if side is Side.BUY else ROUND_FLOOR
            return (adverse / self.protocol.price_increment).to_integral_value(
                rounding=rounding
            ) * self.protocol.price_increment

    def instrument(self, at: datetime) -> Instrument:
        return Instrument(
            InstrumentId("SPY"),
            "SPY",
            AssetClass.EQUITY,
            "hypothetical-unverified",
            True,
            True,
            self.protocol.price_increment,
            self.protocol.quantity_increment,
            self.protocol.quantity_increment,
            self.protocol.minimum_notional,
            None,
            "US-equity",
            at,
            content_hash(("daily-hypothetical-terms", self.protocol.protocol_hash)),
        )

    def execute(
        self, pending: _Pending, raw: Decimal, row: EtfDailyBar, index: int, at: datetime
    ) -> bool:
        if pending.side is Side.SELL and not self.state.shares:
            return False
        price = self.price(raw, pending.side)
        instrument = self.instrument(at)
        quantity = self.state.shares
        if pending.side is Side.BUY:
            sizing = size_position(
                SizingRequest.from_config(
                    reconciled_equity=self.state.cash,
                    authorized_risk_equity=self.protocol.study.risk_equity_reference,
                    stop_distance_per_unit=pending.stop_distance,
                    entry_price=price,
                    instrument=instrument,
                    position_risk=self.cfg.position_risk,
                    activity=self.cfg.activity,
                )
            )
            if not sizing.allowed or price <= pending.stop_distance:
                self.attempts.append(
                    EtfDailyAttempt(
                        row.session_date,
                        pending.side,
                        ZERO,
                        False,
                        "sizing_denied",
                        pending.decision_hash,
                    )
                )
                return False
            quantity = sizing.quantity
        intent = OrderIntent(
            OrderIntentId(
                content_hash(
                    ("assumed-order", self.protocol.protocol_hash, len(self.events), pending)
                )
            ),
            AccountId("etf-offline"),
            InstrumentId("SPY"),
            AssetClass.EQUITY,
            pending.side,
            OrderPurpose.ENTRY if pending.side is Side.BUY else OrderPurpose.PROTECTIVE_EXIT,
            OrderType.LIMIT,
            TimeInForce.GOOD_FOR_DAY,
            quantity,
            price,
            None,
            at,
            row.raw.ends_at + timedelta(seconds=1),
            self.protocol.protocol_id,
            ConfigHash(self.protocol.study.config_hash),
            DataHash(pending.decision_hash),
            "daily-assumed-exit-v1",
        )
        candidate = self.event(
            "pending_intent",
            at,
            intent=intent,
            instrument=instrument,
            stop_distance=pending.stop_distance,
            fee_bound=self.protocol.episode_fee_bound,
        )
        admission = admit_etf_pending_intent(self.account_request(), candidate)
        self.attempts.append(
            EtfDailyAttempt(
                row.session_date,
                pending.side,
                quantity,
                admission.allowed,
                admission.reason,
                pending.decision_hash,
            )
        )
        if not admission.allowed:
            return False
        self.apply(candidate)
        self.apply(
            self.event(
                "order_status",
                at + timedelta(microseconds=1),
                order_id=intent.id,
                order_event=OrderEvent.BROKER_ACCEPTED,
            )
        )
        fill = Fill(
            FillId(content_hash(("assumed-fill", intent.id))),
            BrokerOrderId(intent.id),
            AccountId("etf-offline"),
            InstrumentId("SPY"),
            pending.side,
            quantity,
            price,
            self.protocol.side_fee,
            at + timedelta(microseconds=2),
            DataHash(pending.decision_hash),
        )
        self.apply(self.event("fill", fill.occurred_at, fill=fill))
        self.obligations[fill.id] = index + self.protocol.settlement_sessions
        if pending.side is Side.BUY:
            self.entry_index, self.entry_stop = index, pending.stop_distance
            self.stop = price - pending.stop_distance
            self.target = (
                price
                + pending.stop_distance * self.cfg.equity_strategies.exit_reward_to_initial_risk
            )
        else:
            self.exits.append(EtfDailyExit(row.session_date, pending.reason, price, fill.id))
            self.entry_index = self.stop = self.target = None
        return True

    def protection(
        self, row: EtfDailyBar, index: int, *, opening: bool, after_entry: bool = False
    ) -> bool:
        if not self.state.shares:
            return False
        stop, target = _required(self.stop), _required(self.target)
        if opening:
            if row.raw.open <= stop:
                price, reason = row.raw.open, "stop_gap_after_entry" if after_entry else "stop_gap"
            elif row.raw.open >= target:
                price, reason = target, "target_gap_conservative"
            else:
                return False
            at = row.raw.starts_at + timedelta(microseconds=40 if after_entry else 10)
        else:
            if row.raw.low <= stop:
                price = stop
                reason = "stop_first_ambiguous" if row.raw.high >= target else "stop"
            elif row.raw.high >= target:
                price, reason = target, "target"
            else:
                return False
            at = row.raw.ends_at - timedelta(microseconds=10)
        pending = _Pending(
            Side.SELL,
            self.entry_stop,
            reason,
            content_hash(("assumed-protection", row.raw.data_hash, stop, target)),
        )
        return self.execute(pending, price, row, index, at)

    def decide(
        self, row: EtfDailyBar, prior: tuple[EtfDailyBar, ...], index: int, anchor_index: int
    ) -> None:
        scheduled = None
        rebalance = (index - anchor_index) % self.protocol.rebalance_sessions == 0
        hashes = tuple(item.feature.data_hash for item in prior)
        signal = None
        reasons: tuple[str, ...] = ()
        digest = content_hash((self.protocol.protocol_hash, row.session_date, hashes))
        if len(prior) == self.protocol.warmup_bars:
            feature = FeaturePipeline().compute(
                HistoricalSlice(
                    InstrumentId("SPY"), tuple(item.feature for item in prior), None, digest
                ),
                as_of=row.raw.starts_at,
            )
            decisions = MomentumStrategy().decide(
                StrategyContext(
                    row.raw.starts_at,
                    FeatureSnapshot(row.raw.starts_at, (feature,), feature.data_hash),
                    ConfigHash(self.protocol.study.config_hash),
                    (InstrumentId("SPY"),),
                )
            )
            decision = decisions[0]
            signal, reasons = decision.action.value, decision.reason_codes
            digest = content_hash((digest, decision))
            atr = dict(feature.values)["average_true_range"]
            _check(isinstance(atr, Decimal))
            stop = cast(Decimal, atr) * self.cfg.equity_strategies.stop_loss_atr_multiplier
            if self.state.shares:
                if (
                    index - _required(self.entry_index) + 1
                    >= self.cfg.equity_strategies.maximum_holding_bars
                ):
                    scheduled = "maximum_hold"
                elif decision.action is StrategyAction.HOLD:
                    scheduled = "regime_exit"
                if scheduled:
                    self.pending = _Pending(Side.SELL, self.entry_stop, scheduled, digest)
            elif rebalance and decision.action is StrategyAction.ENTER_LONG and stop > 0:
                scheduled = "entry"
                self.pending = _Pending(Side.BUY, stop, scheduled, digest)
        else:
            reasons = ("prior_session_history_missing",)
        self.decisions.append(
            EtfDailyDecision(
                row.session_date,
                rebalance,
                signal,
                hashes,
                digest,
                scheduled,
                reasons,
            )
        )

    def advance(
        self, row: EtfDailyBar, prior: tuple[EtfDailyBar, ...], index: int, anchor_index: int
    ) -> None:
        at = row.raw.starts_at
        for fill_id, due in tuple(self.obligations.items()):
            if due <= index:
                self.apply(self.event("settlement", at, fill_ids=(fill_id,)))
                del self.obligations[fill_id]
        for distribution in self.request.distributions:
            if distribution.ex_date == row.session_date:
                key = distribution.source_hash
                self.apply(
                    self.event(
                        "dividend_ex_mark_v2",
                        at,
                        action_id=key,
                        cash_per_share=distribution.cash_per_share,
                        mark_price=row.raw.open,
                    )
                )
                self.entitlements[key] = distribution.pay_date
        for key, due_date in tuple(self.entitlements.items()):
            if due_date <= row.session_date:
                self.apply(self.event("dividend_pay", at, action_id=key))
                del self.entitlements[key]
        self.apply(self.event("mark", at, mark_price=row.raw.open))
        if not self.protection(row, index, opening=True) and self.pending is not None:
            filled = self.execute(
                self.pending, row.raw.open, row, index, at + timedelta(microseconds=20)
            )
            if filled and self.pending.side is Side.BUY:
                self.protection(row, index, opening=True, after_entry=True)
        self.pending = None
        self.decide(row, prior, index, anchor_index)
        self.protection(row, index, opening=False)
        self.apply(self.event("mark", row.raw.ends_at, mark_price=row.raw.close))
        state = self.state
        with localcontext(_money_context()):
            nav = state.cash + state.position.market_value + state.dividend_receivable
            proxy = nav - (
                state.position.market_value * self.rate + self.protocol.side_fee
                if state.shares
                else ZERO
            )
        self.points.append(
            EtfDailyPoint(
                row.session_date,
                state.cash,
                state.settled_cash,
                state.shares,
                state.dividend_receivable,
                nav,
                proxy,
                state.trial.reserved_risk,
                state.trial.consumed_loss,
                row.raw.data_hash,
                state.state_hash,
            )
        )

    def run(self) -> EtfDailyResult:
        incomplete = []
        if self.protocol.price_basis == "unknown":
            incomplete.append("price_action_basis_unknown")
        else:
            rows = {row.session_date: row for row in self.request.bars}
            anchor_index = self.protocol.sessions.index(self.protocol.first_rebalance)
            for index, day in enumerate(self.protocol.sessions[anchor_index:], anchor_index):
                row = rows.get(day)
                if row is None:
                    incomplete.append("missing_session_price")
                    break
                expected = self.protocol.sessions[index - self.protocol.warmup_bars : index]
                prior = tuple(rows[day] for day in expected if day in rows)
                self.advance(row, prior, index, anchor_index)
                if (
                    len(prior) != self.protocol.warmup_bars
                    and "prior_session_history_missing" not in incomplete
                ):
                    incomplete.append("prior_session_history_missing")
        _check(replay_etf_account(self.account_request()) == self.state)
        if not self.state.complete:
            incomplete.append("open_account_obligations")
        return EtfDailyResult(
            self.request,
            tuple(self.decisions),
            tuple(self.attempts),
            tuple(self.exits),
            tuple(self.points),
            tuple(self.events),
            self.state,
            tuple(incomplete),
        )


def run_etf_daily_screen(request: EtfDailyRequest) -> EtfDailyResult:
    """Bounded chronological simulation using declared assumptions only."""
    try:
        _check(type(request) is EtfDailyRequest)
        request.__post_init__()
        checked = replace(request)
        with localcontext(_context(exact=False)) as context:
            context.prec = 64
            return _Owner(checked).run()
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise EtfDailyError() from None


def verify_etf_daily_result(result: EtfDailyResult) -> None:
    try:
        _check(type(result) is EtfDailyResult)
        _check(result == run_etf_daily_screen(result.request))
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise EtfDailyError() from None
