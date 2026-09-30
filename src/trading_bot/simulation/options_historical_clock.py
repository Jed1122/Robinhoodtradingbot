"""Internal modeled lifecycle clock, not a historical-study or risk-admission API.

The episode owner must verify sources and policy before submitting intents. This
component owns only modeled event ordering, accounting and unresolved obligations.
No quote, timer or result is evidence of an actual broker fill or settlement.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from decimal import Decimal, localcontext
from typing import Literal

from trading_bot.config import LoadedConfig
from trading_bot.domain.enums import OrderEvent, OrderState
from trading_bot.domain.options import OptionContract, OptionsOrderIntent
from trading_bot.domain.order_state_machine import transition
from trading_bot.lifecycle.options_expiry import (
    OptionExpiryAssessment,
    OptionExpiryCalendar,
    assess_option_expiry,
)
from trading_bot.market_data.options_quote_stream_models import OptionsMarketEvent
from trading_bot.market_data.options_session_inputs import _ns
from trading_bot.market_data.options_source_models import check, instant
from trading_bot.market_data.options_source_verify import ceil_available_at
from trading_bot.market_data.recording import content_hash
from trading_bot.research.options_account_journal import reconstruct_account_journal
from trading_bot.research.options_account_journal_models import (
    AccountFact,
    AccountJournalEntry,
    JournalComplete,
    JournalIncident,
    JournalIntent,
    JournalOrderUpdate,
    JournalSettlement,
)
from trading_bot.research.options_study_models import StudyScenario
from trading_bot.simulation.options_historical_execution import (
    advance_order,
    propose_order,
    request_cancel,
)
from trading_bot.simulation.options_historical_models import (
    HISTORICAL_TERMINAL,
    HistoricalOrder,
    HistoricalOrderStep,
    HistoricalTransition,
    OptionsAccountPathState,
)


@dataclass(frozen=True, slots=True)
class HistoricalClockResult:
    status: Literal["empty", "completed", "incomplete"]
    state: OptionsAccountPathState
    orders: tuple[HistoricalOrder, ...]
    journal: tuple[AccountJournalEntry, ...]
    transitions: tuple[tuple[str, HistoricalTransition], ...]
    net_cash_flow: Decimal
    fees: Decimal
    reasons: tuple[str, ...]
    reconciliation_reasons: tuple[str, ...]
    expiry: tuple[OptionExpiryAssessment, ...]
    production_eligible: Literal[False] = field(default=False, init=False)
    economic_eligible: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)


class _EpisodeClock:
    """Bounded internal composition. Risk/source decisions are deliberately absent.

    A terminal/unknown journal prefix can be inspected and continued. Resuming an
    active order needs its independently persisted execution cursor, which is not
    implemented here; construction rejects such prefixes instead of guessing it.
    """

    def __init__(
        self,
        initial: OptionsAccountPathState,
        prefix: tuple[AccountJournalEntry, ...],
        *,
        loaded: LoadedConfig,
        scenario: StudyScenario,
        seed: int,
    ) -> None:
        check(type(seed) is int and 0 <= seed < 2**63)
        state = reconstruct_account_journal(initial, prefix, loaded=loaded, scenario=scenario)
        check(
            all(
                o.state in HISTORICAL_TERMINAL
                or o.state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION
                for o in state.orders
            )
        )
        self.initial, self.loaded, self.scenario, self.seed = initial, loaded, scenario, seed
        self._prefix = prefix
        self._actions: list[tuple[str, object]] = []
        self.state, self.journal = state, prefix
        self.now_ns = state.last_event_ns
        self._start_cash, self._start_fees = state.cash, state.fees
        self._cash, self._fees = Decimal(0), Decimal(0)
        self._seen: set[str] = set()
        self._event_count = 0
        self._consumed: dict[tuple[str, str, int, str], int] = {}
        self._orders = {
            o.intent.intent_id: HistoricalOrder(
                o.intent,
                o.state,
                o.decision_ns,
                o.filled_units,
                o.accepted_ns,
            )
            for o in state.orders
        }
        self._transitions: list[tuple[str, HistoricalTransition]] = []
        self._calendars: dict[str, tuple[OptionContract, OptionExpiryCalendar]] = {}

    def watch_expiry(self, contract: OptionContract, calendar: OptionExpiryCalendar) -> None:
        """Bind immutable calendar preimages; the study owner must verify their source."""
        check(type(contract) is OptionContract and type(calendar) is OptionExpiryCalendar)
        check(calendar.contract_id == contract.contract_id)
        binding = (contract, calendar)
        check(
            contract.contract_id not in self._calendars
            or self._calendars[contract.contract_id] == binding
        )
        check(
            all(
                o.intent.structure.legs[0].contract == contract
                for o in self._orders.values()
                if o.intent.structure.legs[0].contract.contract_id == contract.contract_id
            )
        )
        self._calendars[contract.contract_id] = binding
        self._actions.append(("watch", binding))

    def _expiry(self, at: int) -> tuple[OptionExpiryAssessment, ...]:
        contracts = {p.contract.contract_id: p.contract for p in self.state.positions}
        for order in self._orders.values():
            if order.state not in HISTORICAL_TERMINAL:
                c = order.intent.structure.legs[0].contract
                contracts[c.contract_id] = c
        return tuple(
            assess_option_expiry(
                contract=c,
                calendar=self._calendars[c.contract_id][1]
                if c.contract_id in self._calendars
                else None,
                as_of=ceil_available_at(at),
                has_exposure=True,
            )
            for c in sorted(contracts.values(), key=lambda c: c.contract_id)
        )

    def _append(self, facts: tuple[AccountFact, ...], at: int) -> None:
        # Build/replay a complete candidate before mutation. The journal computes
        # cash from prices/quantities independently of the execution cash deltas.
        entries = self.journal
        previous = self.state.journal_hash
        for fact in facts:
            event = AccountJournalEntry(
                content_hash(("historical-clock-fact-v1", previous, at, fact)), at, previous, fact
            )
            entries = (*entries, event)
            previous = event.entry_hash
        following = reconstruct_account_journal(
            self.initial, entries, loaded=self.loaded, scenario=self.scenario
        )
        self.state, self.journal = following, entries

    @contextmanager
    def _atomic_event(self) -> Iterator[None]:
        """No half-consumed observation can be retried with renewed liquidity."""
        before = (
            self.state,
            self.journal,
            self.now_ns,
            self._cash,
            self._fees,
            self._seen.copy(),
            self._event_count,
            self._consumed.copy(),
            self._orders.copy(),
            self._transitions.copy(),
        )
        try:
            yield
        except BaseException:
            (
                self.state,
                self.journal,
                self.now_ns,
                self._cash,
                self._fees,
                self._seen,
                self._event_count,
                self._consumed,
                self._orders,
                self._transitions,
            ) = before
            raise

    def submit(
        self, episode_id: str, session_id: str, intent: OptionsOrderIntent, *, available_ns: int
    ) -> None:
        check(available_ns == self.now_ns)
        c = intent.structure.legs[0].contract
        check(c.contract_id not in self._calendars or self._calendars[c.contract_id][0] == c)
        proposed = propose_order(intent, available_ns=available_ns)
        self._append((JournalIntent(episode_id, session_id, intent),), available_ns)
        self._orders[intent.intent_id] = proposed.order
        self._transitions.extend((intent.intent_id, t) for t in proposed.transitions)
        self._actions.append(("submit", (episode_id, session_id, intent, available_ns)))

    def _apply_step(self, step: HistoricalOrderStep) -> None:
        ident = step.order.intent.intent_id
        facts: list[AccountFact] = []
        for item in step.transitions:
            filling = item.event in (OrderEvent.FILL, OrderEvent.PARTIAL_FILL)
            facts.append(
                JournalOrderUpdate(
                    ident,
                    item.event,
                    step.fill_units if filling else 0,
                    step.price if filling else None,
                    step.fee if filling else Decimal(0),
                )
            )
        if facts:
            self._append(tuple(facts), step.transitions[0].available_ns)
        self._orders[ident] = step.order
        self._transitions.extend((ident, t) for t in step.transitions)
        with localcontext() as context:
            context.prec = 2048
            self._cash += step.cash_flow
            self._fees += step.fee

    def cancel(self, order_id: str, *, available_ns: int) -> None:
        check(available_ns == self.now_ns and order_id in self._orders)
        self._apply_step(request_cancel(self._orders[order_id], available_ns=available_ns))
        self._actions.append(("cancel", (order_id, available_ns)))

    def _move(self, order: HistoricalOrder, event: OrderEvent, at: int) -> None:
        following = transition(order.state, event)
        self._apply_step(
            HistoricalOrderStep(
                replace(order, state=following, last_event_ns=at),
                (HistoricalTransition(at, event, order.state, following),),
            )
        )

    def _complete(self, at: int) -> None:
        for episode in self.state.episodes:
            if (
                not episode.finalized
                and not self.state.incidents
                and not any(p.episode_id == episode.episode_id for p in self.state.positions)
                and not any(s.episode_id == episode.episode_id for s in self.state.unsettled)
                and all(
                    o.state in HISTORICAL_TERMINAL
                    for o in self.state.orders
                    if o.episode_id == episode.episode_id
                )
            ):
                self._append((JournalComplete(episode.episode_id),), at)

    def _timers(self, through: int, *, before_quote: bool = False) -> None:
        """Modeled known expiries/settlement; unknown acceptance never expires flat.

        Cancel acknowledgements exactly tied to a quote are left to the explicit
        scenario race. Earlier timers always precede that quote. DAY expiration
        wins at its exact boundary, which can never supply an executable fill.
        """
        pending: list[tuple[int, str, str]] = []
        for order in self._orders.values():
            if (
                order.state in HISTORICAL_TERMINAL
                or order.state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION
            ):
                continue
            pending.append((_ns(order.intent.expires_at), "expiry", order.intent.intent_id))
            if order.cancel_requested_ns is not None:
                at = order.cancel_requested_ns + self.scenario.cancel_acknowledgement_ns
                if not before_quote or at < through:
                    pending.append((at, "cancel", order.intent.intent_id))
        pending.extend((s.due_ns, "settlement", s.event_id) for s in self.state.unsettled)
        pending.extend(
            (_ns(item.exit_deadline), "protective", item.contract_id)
            for item in self._expiry(self.now_ns)
            if item.exit_deadline is not None
        )
        for due, kind, ident in sorted(pending):
            if due > through:
                continue
            at = max(self.now_ns, due)
            if kind == "protective":
                # Re-evaluate exposure after earlier events: flat is not an incident.
                for item in self._expiry(at):
                    if item.contract_id == ident:
                        for reason in item.reasons:
                            if (
                                reason != "expiry_exit_session"
                                and reason not in self.state.incidents
                            ):
                                self._append((JournalIncident(reason),), at)
            elif kind == "settlement":
                self._append((JournalSettlement(ident),), at)
            else:
                order = self._orders[ident]
                if order.state in HISTORICAL_TERMINAL:
                    continue
                action = (
                    OrderEvent.CANCEL_CONFIRMED
                    if kind == "cancel"
                    else OrderEvent.BROKER_AMBIGUOUS
                    if order.state is OrderState.SUBMISSION_PENDING
                    else OrderEvent.BROKER_EXPIRED
                )
                self._move(order, action, at)
            self.now_ns = at
            self._complete(at)

    def advance_time(self, available_ns: int) -> None:
        with self._atomic_event():
            self._advance_time(available_ns)
        self._actions.append(("time", available_ns))

    def _advance_time(self, available_ns: int) -> None:
        instant(available_ns)
        check(available_ns >= self.now_ns)
        self._timers(available_ns)
        if available_ns > self.now_ns:
            self._seen.clear()
        self.now_ns = available_ns
        self._complete(available_ns)

    def advance(self, event: OptionsMarketEvent) -> None:
        with self._atomic_event():
            self._advance(event)
        self._actions.append(("quote", event))

    def _advance(self, event: OptionsMarketEvent) -> None:
        check(type(event) is OptionsMarketEvent and event.available_ns >= self.now_ns)
        if event.identity in self._seen:
            return
        check(self._event_count < self.loaded.config.options.replay_max_records)
        self._timers(event.available_ns, before_quote=True)
        if event.available_ns > self.now_ns:
            self._seen.clear()
        self.now_ns = event.available_ns
        for order in tuple(self._orders.values()):
            leg = order.intent.structure.legs[0]
            # Source ordinals/projection hashes and receipt times do not establish
            # replenishment. Conservatively share same-native-time side liquidity,
            # including repeated records delivered after a gap or a later receipt.
            key = (event.source, event.symbol, event.event_ns, leg.side.value)
            step = advance_order(
                order,
                event,
                scenario=self.scenario,
                seed=self.seed,
                consumed_units=self._consumed.get(key, 0),
            )
            self._apply_step(step)
            if step.fill_units:
                self._consumed[key] = self._consumed.get(key, 0) + step.fill_units
        self._seen.add(event.identity)
        self._event_count += 1
        self._complete(self.now_ns)

    def result(self) -> HistoricalClockResult:
        reasons = set(self.state.incidents)
        expiry = self._expiry(self.now_ns)
        reasons.update(reason for item in expiry for reason in item.reasons)
        if self.state.positions:
            reasons.add("open_position")
        if self.state.unsettled:
            reasons.add("settlement_pending")
        if any(not episode.finalized for episode in self.state.episodes):
            reasons.add("episode_unfinalized")
        for order in self.state.orders:
            if order.state not in HISTORICAL_TERMINAL:
                reasons.add(
                    "unknown_order"
                    if order.state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION
                    else "pending_order"
                )
        with localcontext() as context:
            context.prec = 2048
            reconciliation = tuple(
                name
                for name, valid in (
                    ("cash_flow_mismatch", self._start_cash + self._cash == self.state.cash),
                    ("fees_mismatch", self._start_fees + self._fees == self.state.fees),
                    (
                        "order_projection_mismatch",
                        all(
                            (o.state, o.filled_units, o.accepted_ns)
                            == (
                                self._orders[o.intent.intent_id].state,
                                self._orders[o.intent.intent_id].filled_units,
                                self._orders[o.intent.intent_id].accepted_ns,
                            )
                            for o in self.state.orders
                        ),
                    ),
                )
                if not valid
            )
        reasons.update(reconciliation)
        return HistoricalClockResult(
            "incomplete" if reasons else "completed" if self.state.episodes else "empty",
            self.state,
            tuple(self._orders.values()),
            self.journal,
            tuple(self._transitions),
            self._cash,
            self._fees,
            tuple(sorted(reasons)),
            reconciliation,
            expiry,
        )
