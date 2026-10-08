"""Assumption-based daily strategy lifecycle; never broker or market-fill evidence.

Daily bars supply adverse hypothetical prices, not quote events. The common
account owner remains authoritative for admission, obligations and trial losses.
The scheduler cannot resize around a denial or settle outside its frozen calendar.
"""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, localcontext
from typing import cast

from trading_bot.domain import (
    ConfigHash,
    InstrumentId,
    Side,
)
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_daily_protocol import (
    EtfDailyBar,
    EtfDailyError,
    EtfDailyProtocol,
    EtfDailyRequest,
    _check,
    _DailyRecord,
)
from trading_bot.simulation.etf_account import (
    EtfAccountEvent,
    EtfAccountRequest,
    EtfAccountResult,
    _required,
    replay_etf_account,
)
from trading_bot.simulation.etf_exploratory_lifecycle import (
    EtfDailyAttempt,
    EtfDailyExit,
    EtfDailyPoint,
    EtfExploratoryLifecycle,
    _Pending,
)
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


class _Owner(EtfExploratoryLifecycle):
    request: EtfDailyRequest
    protocol: EtfDailyProtocol

    def __init__(self, request: EtfDailyRequest) -> None:
        super().__init__(request)
        self.decisions: list[EtfDailyDecision] = []

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
        self.opening(row, index)
        self.decide(row, prior, index, anchor_index)
        self.closing(row, index)

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
        _check(replay_etf_account(cast(EtfAccountRequest, self.account_request())) == self.state)
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
