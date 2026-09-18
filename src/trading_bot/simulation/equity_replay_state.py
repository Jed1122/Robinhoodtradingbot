"""Single-owner synthetic admissions and scheduling; no provider or persistence boundary."""

from datetime import datetime, timedelta
from decimal import Decimal

from trading_bot.domain import (
    CheckResult,
    InstrumentId,
    OrderIntent,
    OrderPurpose,
    OrderState,
    PortfolioSnapshot,
    Quote,
    Side,
)
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation.configured import ConfiguredOrderSession
from trading_bot.simulation.configured_models import (
    InstrumentConfiguredOrderRequest,
    SyntheticCancelRequest,
    SyntheticMarketEvent,
)
from trading_bot.simulation.equity_replay_models import (
    EquityStrategyReplayRequest,
    ReplayOrderOutcome,
    ReplaySession,
    deny,
)
from trading_bot.simulation.equity_replay_policy import ReplayEntryPolicy
from trading_bot.simulation.equity_replay_portfolio import ReplayOrderRecord, ReplayPortfolio
from trading_bot.simulation.equity_replay_records import ReplayCancellation, ReplayOrderTransition
from trading_bot.simulation.equity_replay_risk import ReplayRiskState, economic_checks
from trading_bot.simulation.events import EventCursor


class ReplayState:
    def __init__(self, request: EquityStrategyReplayRequest) -> None:
        self.request = request
        self.book = ReplayPortfolio(request)
        self.risk = ReplayRiskState(request, self.book)
        self.markets = tuple({e.event_id: e for e in request.markets}.values())
        self.sessions: dict[str, ConfiguredOrderSession] = {}
        self.policies: dict[InstrumentId, ReplayEntryPolicy] = {}
        self.cycle_policies: tuple[ReplayEntryPolicy, ...] = ()
        self.checks: list[tuple[str, tuple[CheckResult, ...]]] = []
        self.transitions: list[ReplayOrderTransition] = []
        self.cancellations: list[ReplayCancellation] = []
        self.last_rebalance_bars: int | None = None

    def visible(self, at: datetime) -> dict[InstrumentId, SyntheticMarketEvent]:
        return {e.quote.instrument_id: e for e in self.markets if e.cursor.occurred_at <= at}

    def quotes(self, at: datetime) -> tuple[Quote, ...]:
        maximum = self.request.loaded.config.freshness.max_executable_quote_age_seconds
        quotes = []
        for _, event in sorted(self.visible(at).items()):
            age = at - event.quote.observed_at
            seconds = Decimal(age.days * 86400 + age.seconds) + Decimal(age.microseconds) / 1000000
            if seconds <= maximum:
                quotes.append(event.quote)
        return tuple(quotes)

    def observe(
        self, at: datetime, *, policies: tuple[ReplayEntryPolicy, ...] = ()
    ) -> PortfolioSnapshot:
        return self.risk.observe(at, self.quotes(at), entry_policies=policies)

    def event(self, symbol: InstrumentId, at: datetime) -> SyntheticMarketEvent:
        event = self.visible(at).get(symbol)
        if (
            event is None
            or event.quote not in self.quotes(at)
            or not event.quote.freshness_verified
        ):
            deny("replay_quote_unavailable")
        return event

    def session(self, symbol: InstrumentId, at: datetime) -> ReplaySession:
        matches = tuple(
            s
            for s in self.request.sessions
            if s.instrument_id == symbol and s.window.starts_at <= at < s.window.ends_at
        )
        if len(matches) != 1:
            deny("replay_session_unavailable")
        return matches[0]

    def active(self, symbol: InstrumentId) -> ReplayOrderRecord | None:
        return next(
            (
                o
                for o in self.book.orders
                if o.intent.instrument_id == symbol and not o.lifecycle.order_terminal
            ),
            None,
        )

    def next_order_key(self) -> tuple[datetime, int, InstrumentId, str] | None:
        candidates = []
        for order_id, session in self.sessions.items():
            key = session.next_event_key
            if key is not None:
                symbol = self.book.initial_order(order_id).order.instrument_id
                candidates.append((*key, symbol, order_id))
        return min(candidates, default=None)

    def step(self) -> None:
        key = self.next_order_key()
        if key is None:
            deny("replay_ordering_invalid")
        at, _, _, order_id = key
        session = self.sessions[order_id]
        offset = len(session.result.decisions)
        result = session.advance_next()
        self.book.apply(order_id, result)
        self.transitions.extend(
            ReplayOrderTransition(order_id, d) for d in result.decisions[offset:]
        )
        self.observe(at)

    def drain(self, at: datetime) -> None:
        while (key := self.next_order_key()) is not None and key[0] == at:
            self.step()

    def cancel(self, record: ReplayOrderRecord, at: datetime, reason: str) -> None:
        if record.lifecycle.snapshot.order.state not in {
            OrderState.SUBMITTED,
            OrderState.PARTIALLY_FILLED,
        }:
            return
        session = self.sessions[record.initial.order.id]
        session.advance_to(at)  # The coordinator has already drained every scheduled action here.
        event = SyntheticCancelRequest(
            "replay-cancel:"
            + content_hash(
                (record.initial.order.id, at, reason, record.lifecycle.snapshot.snapshot_hash)
            ),
            EventCursor(len(session.result.events) + 1, at),
        )
        session.cancel_after_observation(event)
        self.cancellations.append(ReplayCancellation(record.initial.order.id, at, reason))

    def cancel_loss_blocked_entries(self, at: datetime) -> None:
        decision = self.risk.loss_decision(OrderPurpose.ENTRY)
        if decision.cancel_unfilled_entries:
            for record in sorted(
                self.book.orders, key=lambda o: (o.intent.instrument_id, o.initial.order.id)
            ):
                if record.intent.side is Side.BUY and not record.lifecycle.order_terminal:
                    self.cancel(record, at, decision.reason_code)

    async def execute(self, intent: OrderIntent) -> ReplayOrderOutcome:
        at = intent.created_at
        self.observe(at, policies=self.cycle_policies)
        event = self.event(intent.instrument_id, at)
        checks = economic_checks(intent, self.risk, self.request, at)
        self.checks.append((intent.id, checks))
        reasons = tuple(
            c.reason if c.code == "replay_loss_limits" else c.code for c in checks if not c.allowed
        )
        clock = event.clock
        reasons += tuple(
            code
            for code, blocked in (
                ("replay_market_closed", not clock.is_open),
                ("replay_market_halted", clock.halted),
                ("replay_trading_disabled", clock.trading_disabled),
                ("replay_cancel_only", clock.cancel_only),
                (
                    "replay_submission_window_unavailable",
                    not event.window.starts_at <= at < event.window.ends_at,
                ),
                (
                    "replay_session_ending",
                    at
                    + timedelta(
                        milliseconds=self.request.loaded.config.simulation.latency_milliseconds
                    )
                    >= intent.expires_at,
                ),
            )
            if blocked
        )
        instrument = next(i for i in self.request.instruments if i.id == intent.instrument_id)
        if not instrument.tradable:
            reasons += ("replay_instrument_untradable",)
        if reasons:
            return ReplayOrderOutcome(intent.id, False, reasons, None)
        declared = self.session(intent.instrument_id, at)
        count = sum(at < t < intent.expires_at for t in declared.opportunity_times)
        outcome = self.book.reserve(intent, count)
        if outcome.accepted:
            if outcome.order_id is None:
                deny()
            self.sessions[outcome.order_id] = ConfiguredOrderSession(
                InstrumentConfiguredOrderRequest(
                    initial=self.book.initial_order(outcome.order_id),
                    simulation=self.request.loaded.config.simulation,
                    costs=self.request.loaded.config.costs,
                    seed=self.request.seed,
                    submission_window=event.window,
                    events=tuple(
                        e
                        for e in self.markets
                        if e.quote.instrument_id == intent.instrument_id
                        and e.cursor.occurred_at > at
                    ),
                    end_at=self.request.end_at,
                    expires_at=intent.expires_at,
                    instrument=instrument,
                )
            )
            if intent.side is Side.BUY:
                policy = self.risk.policy(intent.exit_policy_version)
                if policy is None:
                    deny("replay_policy_identity_invalid")
                self.policies[intent.instrument_id] = policy
        return outcome
