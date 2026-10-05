"""Causal offline execution for native or synthetic recorded ETF observations.

The simulator owns acknowledgements/settlement, explicitly as assumptions. It
uses the canonical feature, strategy, portfolio, intent and account owners. No
provider or broker transport is imported. Unknown market semantics deny fills.
"""

from collections.abc import Generator, Iterable
from dataclasses import replace
from decimal import Decimal, localcontext

from trading_bot.domain import (
    AccountId,
    Bar,
    CorporateAction,
    DataHash,
    Fill,
    FillId,
    InstrumentId,
    OrderEvent,
    OrderIntentId,
    OrderPurpose,
    OrderState,
    PortfolioSnapshot,
    Side,
)
from trading_bot.domain.decimal_utils import quantize_down
from trading_bot.market_data.adjustments import adjust_bars
from trading_bot.market_data.etf_source import _ceil_time, _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.portfolio.intents import IntentPlanner, IntentPlanningContext
from trading_bot.portfolio.targets import ExitPolicy, PortfolioConstructor
from trading_bot.research.etf_costs import _fee_context, etf_execution_charges
from trading_bot.simulation.costs import SimulatedCosts, execution_price
from trading_bot.simulation.etf_account import (
    EtfAccountEvent,
    EtfAccountRequest,
    EtfAccountStepper,
    admit_etf_pending_intent,
)
from trading_bot.simulation.etf_history import _policy, _session_date
from trading_bot.simulation.etf_native_models import (
    EtfDailyAccount,
    EtfHistoryRequest,
    EtfHistoryResult,
    EtfReplayEvent,
    EtfReplayOutcome,
    check,
)
from trading_bot.simulation.etf_strategy import EtfEntryPolicy, EtfStrategyDecision
from trading_bot.simulation.lifecycle_accounting import _context
from trading_bot.strategies.features import FeaturePipeline
from trading_bot.strategies.momentum import MomentumStrategy
from trading_bot.strategies.protocol import (
    FeatureSnapshot,
    HistoricalSlice,
    StrategyAction,
    StrategyContext,
    StrategyDecision,
)

ZERO = Decimal("0")
_SECOND = Decimal("1000000000")
_TERMINAL = (OrderState.FILLED, OrderState.CANCELED, OrderState.REJECTED, OrderState.EXPIRED)


def _development(request: EtfHistoryRequest) -> tuple[EtfReplayEvent, ...]:
    # Publication and native event time must both precede the sealed holdout.
    boundary = _ns(request.study.holdout_start)
    return tuple(
        e
        for e in request.dataset.events
        if e.available_at_ns < boundary and e.event_at_ns < boundary
    )


def _outcome(
    request: EtfHistoryRequest, events: tuple[EtfReplayEvent, ...], *, benchmark: bool
) -> EtfReplayOutcome:
    reducer = _outcome_steps(request, events, benchmark=benchmark)
    try:
        next(reducer)
    except StopIteration as finished:
        return finished.value  # type: ignore[no-any-return]
    finally:
        reducer.close()
    raise ValueError("etf_native_history_invalid")


def _outcome_steps(
    request: EtfHistoryRequest,
    events: Iterable[EtfReplayEvent | None],
    *,
    benchmark: bool,
    maximum_decisions: int | None = None,
    decision_counts: dict[str, int] | None = None,
) -> Generator[EtfReplayOutcome, None, EtfReplayOutcome]:
    """Boundary sentinels suspend, never finish a session or reset the owner."""
    policy = _policy(request.study)
    cfg = policy.config
    settings = cfg.equity_strategies
    account = EtfAccountRequest(request.study, request.initial_cash, ())
    account_owner = EtfAccountStepper(account)
    state = account_owner.state
    bars: dict[int, Bar] = {}
    frame: StrategyDecision | None = None
    entry_signals: dict[str, StrategyDecision] = {}
    atr: Decimal | None = None
    frame_day = None
    on_cadence = False
    eligible_count = 0
    clock: EtfReplayEvent | None = None
    quote: EtfReplayEvent | None = None
    control_conflict = quote_conflict = False
    policies: list[EtfEntryPolicy] = []
    decisions: list[EtfStrategyDecision] = []
    daily: list[EtfDailyAccount] = []
    reasons: set[str] = set()
    trigger: str | None = None
    attempted: set[object] = set()
    # Quote capacity is global to this economic owner, not replenished per order.
    capacity: dict[tuple[int, Side], tuple[Decimal, Decimal]] = {}
    schedules: dict[str, str] = {}
    pending: list[tuple[int, str, str]] = []
    fill_sessions: dict[str, int] = {}
    session_count = 0
    current_session: EtfReplayEvent | None = None
    current_eligible = False
    split_seen = False
    unresolved_actions: set[str] = set()
    last_source_event: EtfReplayEvent | None = None
    distributions: list[CorporateAction] = []
    previous_session_open: int | None = None
    fraction = {"conservative": Decimal(".25"), "base": Decimal(".5"), "optimistic": Decimal("1")}[
        request.fill_scenario
    ]
    slippage_factor = {
        "conservative": Decimal("2"),
        "base": Decimal("1"),
        "optimistic": Decimal(".5"),
    }[request.fill_scenario]

    def append(kind: str, at: int, **values: object) -> None:
        nonlocal state
        ordinal = 0 if state.last_ordinal is None else state.last_ordinal + 1
        event = EtfAccountEvent(
            content_hash(("etf-native-account-fact-v1", state.prefix_hash, kind, at, values)),
            ordinal,
            at,
            kind,
            **values,  # type: ignore[arg-type]
        )
        state = account_owner.apply(event)

    def decide(event: EtfReplayEvent, reason: str, order: str | None = None) -> None:
        if decision_counts is not None:
            decision_counts[reason] = decision_counts.get(reason, 0) + 1
        if maximum_decisions is None or len(decisions) < maximum_decisions:
            decisions.append(EtfStrategyDecision(event.ordinal, reason, order))

    def scheduled(until: int) -> None:
        while pending and min(pending)[0] <= until:
            item = min(pending)
            pending.remove(item)
            at, kind, identity = item
            record = next(o for o in state.orders if o.intent.id == identity)
            if record.order.state in _TERMINAL:
                continue
            if kind == "ack" and record.order.state is OrderState.SUBMISSION_PENDING:
                event = {
                    "accept": OrderEvent.BROKER_ACCEPTED,
                    "reject": OrderEvent.BROKER_REJECTED,
                    "unknown": OrderEvent.BROKER_AMBIGUOUS,
                }[request.schedule.acknowledgement]
                if at >= _ns(record.intent.expires_at) and event is OrderEvent.BROKER_ACCEPTED:
                    event = OrderEvent.BROKER_AMBIGUOUS
                append("order_status", at, order_id=identity, order_event=event)
            elif (
                kind == "cancel"
                and record.order.state is OrderState.CANCEL_PENDING
                and request.schedule.cancellation == "confirm"
            ):
                append(
                    "order_status", at, order_id=identity, order_event=OrderEvent.CANCEL_CONFIRMED
                )
            elif kind == "expiry" and record.order.state in (
                OrderState.SUBMITTED,
                OrderState.PARTIALLY_FILLED,
            ):
                append("order_status", at, order_id=identity, order_event=OrderEvent.BROKER_EXPIRED)

    def snapshot(at: int) -> None:
        if current_session is None or not current_eligible:
            return
        mark = ask = None
        if (
            quote is not None
            and quote.bid is not None
            and quote.ask is not None
            and market_reason(quote) is None
            and 0
            <= at - quote.event_at_ns
            <= cfg.freshness.max_executable_quote_age_seconds * _SECOND
        ):
            mark, ask = quote.bid, quote.ask
        nav = state.cash + state.dividend_receivable if state.shares == 0 else None
        if state.shares > 0 and mark is not None:
            nav = state.cash + state.shares * mark + state.dividend_receivable
        if unresolved_actions:
            nav = None
        daily.append(
            EtfDailyAccount(
                _session_date(current_session.event_at_ns),
                at,
                state.cash,
                state.settled_cash,
                state.shares,
                mark,
                nav,
                state.reserved_cash,
                state.fees,
                state.dividend_receivable,
                state.state_hash,
                ask,
                len(account_owner.events),
            )
        )
        if nav is None or mark is None:
            reasons.add("session_liquidation_mark_unavailable")

    def market_reason(event: EtfReplayEvent) -> str | None:
        if unresolved_actions:
            return "input_reconciliation_incomplete"
        if split_seen:
            return "split_accounting_unsupported"
        if event.execution_reasons:
            return event.execution_reasons[0]
        if clock is None or clock.clock is None or clock.execution_reasons:
            return "market_control_unverified"
        control = clock.clock
        if control_conflict or quote_conflict:
            return "conflicting_native_observations"
        if not control.is_open or control.halted or control.cancel_only or control.trading_disabled:
            return "market_control_disabled"
        if (
            control.next_close_at is None
            or event.available_at_ns >= _ns(control.next_close_at)
            or _session_date(clock.event_at_ns) != _session_date(event.available_at_ns)
        ):
            return "market_session_unavailable"
        if event.event_at_ns <= clock.event_at_ns:
            return "quote_before_control_epoch"
        if (
            event.available_at_ns - event.event_at_ns
            > cfg.freshness.max_executable_quote_age_seconds * _SECOND
        ):
            return "quote_stale"
        if event.bid is None or event.ask is None or not ZERO < event.bid < event.ask:
            return "quote_not_two_sided_unlocked"
        if (event.ask - event.bid) * 100 > cfg.equities.max_spread_pct * event.ask:
            return "quote_spread_too_wide"
        if event.bid_size is None or event.ask_size is None:
            return "quote_capacity_unverified"
        return None

    def propose(event: EtfReplayEvent, protective: EtfEntryPolicy | None) -> None:
        nonlocal state
        signal = frame if protective is None else entry_signals.get(protective.order_id)
        if (
            signal is None
            or (atr is None and protective is None)
            or clock is None
            or clock.clock is None
            or clock.clock.next_close_at is None
        ):
            decide(event, "signal_unavailable")
            return
        if protective is not None:
            signal = replace(signal, action=StrategyAction.EXIT_LONG)
        elif benchmark:
            signal = replace(signal, action=StrategyAction.ENTER_LONG)
        now = _ceil_time(event.available_at_ns)
        price = event.ask if protective is None else event.bid
        check(price is not None and event.bid is not None)
        if price is None or event.bid is None:
            return
        distance = (
            protective.stop_distance
            if protective is not None
            else (atr or ZERO) * settings.stop_loss_atr_multiplier
        )
        if protective is None and price <= distance:
            decide(event, "stop_nonpositive")
            return
        exit_policy = ExitPolicy(
            "etf-canonical-exit-v1",
            "atr",
            distance,
            settings.exit_reward_to_initial_risk,
            settings.maximum_holding_bars,
        )
        position = replace(
            state.position,
            market_value=state.shares * event.bid,
            observed_at=now,
            data_hash=DataHash(event.source_hash),
        )
        exposure = position.market_value
        portfolio = PortfolioSnapshot(
            AccountId("etf-offline"),
            (position,) if state.shares else (),
            state.cash,
            state.cash + exposure + state.dividend_receivable,
            exposure,
            exposure,
            ZERO,
            ZERO,
            ZERO,
            now,
            DataHash(state.prefix_hash),
        )
        target = PortfolioConstructor().construct(
            (signal,),
            portfolio,
            as_of=now,
            config_hash=policy.config_hash,
            exposure_multiplier=Decimal("1"),
            exit_policies=((request.instrument.id, exit_policy),) if protective is None else (),
        )
        identity = content_hash(
            (
                "etf-native-order-v1",
                request.study.study_hash,
                event.source_hash,
                state.prefix_hash,
                protective,
                benchmark,
                request.fill_scenario,
            )
        )
        intents = IntentPlanner(id_factory=lambda: OrderIntentId(identity)).plan(
            target,
            IntentPlanningContext(
                portfolio.account_id,
                portfolio,
                (
                    request.instrument
                    if request.instrument.fractional_eligible
                    else replace(
                        request.instrument,
                        quantity_increment=max(Decimal("1"), request.instrument.quantity_increment),
                        minimum_quantity=max(Decimal("1"), request.instrument.minimum_quantity),
                    ),
                ),
                (("SPY", price),),
                portfolio.equity,
                request.study.risk_equity_reference,
                cfg.position_risk,
                cfg.activity,
                clock.clock.next_close_at - now,
            ),
        )
        if not intents:
            decide(event, "common_sizing_denied")
            return
        intent = replace(
            intents[0],
            data_hash=content_hash((target.data_hash, event.source_hash)),
            purpose=OrderPurpose.ENTRY if protective is None else OrderPurpose.PROTECTIVE_EXIT,
        )
        try:
            entry_charges = etf_execution_charges(
                request.costs, at=now, prior_quantity=ZERO, quantity=intent.quantity, price=price
            )
            if protective is None:
                exit_bound = etf_execution_charges(
                    request.costs,
                    at=now,
                    prior_quantity=ZERO,
                    quantity=intent.quantity,
                    price=price + distance * settings.exit_reward_to_initial_risk,
                )
                required_fees = entry_charges.total_fee_usd + exit_bound.total_fee_usd
            else:
                required_fees = entry_charges.total_fee_usd + sum(
                    (
                        order.fees_paid
                        for order in state.orders
                        if order.episode_id == protective.order_id
                    ),
                    ZERO,
                )
        except ValueError:
            decide(event, "cost_window_unavailable")
            return
        if required_fees > request.schedule.episode_fee_bound:
            decide(event, "episode_fee_reserve_insufficient")
            return
        fact = EtfAccountEvent(
            content_hash(("etf-native-pending-v1", intent)),
            0 if state.last_ordinal is None else state.last_ordinal + 1,
            _ns(now),
            "pending_intent",
            intent=intent,
            instrument=request.instrument,
            stop_distance=distance,
            fee_bound=request.schedule.episode_fee_bound,
        )
        admitted = admit_etf_pending_intent(replace(account, events=account_owner.events), fact)
        if not admitted.allowed:
            decide(event, "canonical_account_admission_denied")
            return
        restored = account_owner.apply(fact)
        check(restored == admitted.state)
        state = restored
        pending.extend(
            (
                (_ns(now) + request.schedule.acknowledgement_delay_ns, "ack", intent.id),
                (_ns(intent.expires_at), "expiry", intent.id),
            )
        )
        if protective is None:
            entry_signals[intent.id] = signal
            policies.append(
                EtfEntryPolicy(
                    intent.id,
                    event.ordinal,
                    signal.data_hash,
                    price,
                    distance,
                    price - distance,
                    price + distance * settings.exit_reward_to_initial_risk,
                    settings.maximum_holding_bars,
                    settings.exit_on_regime_change,
                )
            )
        decide(event, "protective_reserved" if protective else "entry_reserved", intent.id)

    def fill(event: EtfReplayEvent, order_id: str, *, in_flight: bool = False) -> None:
        record = next(o for o in state.orders if o.intent.id == order_id)
        if record.order.state not in (OrderState.SUBMITTED, OrderState.PARTIALLY_FILLED) and not (
            in_flight
            and request.schedule.allow_inflight_cancel_fill
            and record.order.state is OrderState.CANCEL_PENDING
        ):
            decide(event, "order_not_fillable", order_id)
            return
        if state.last_at_ns is not None and event.available_at_ns < state.last_at_ns:
            decide(event, "account_time_not_reached", order_id)
            return
        rates = {
            i.role: i.value
            for i in request.costs.intervals
            if i.starts_at <= _ceil_time(event.available_at_ns) < i.ends_at
            and i.known_at <= i.starts_at
        }
        if "latency" not in rates or rates["latency"] <= 0 or "extra_slippage" not in rates:
            decide(event, "cost_window_unavailable", order_id)
            return
        if (
            event.event_at_ns <= max(record.submitted_at_ns, _ns(record.order.updated_at))
            or event.event_at_ns - record.submitted_at_ns < rates["latency"] * _SECOND
        ):
            decide(event, "latency_or_ack_pending", order_id)
            return
        # New-entry halts do not erase fills of this already reserved order.
        # Common account reconciliation still enforces its original quantity,
        # price, fee and trial reservation. Cancel-pending fills require the
        # separately recorded in-flight simulation assumption above.
        if event.available_at_ns >= _ns(record.intent.expires_at):
            decide(event, "order_expired", order_id)
            return
        displayed = event.ask_size if record.intent.side is Side.BUY else event.bid_size
        check(
            displayed is not None
            and event.bid is not None
            and event.ask is not None
            and record.intent.limit_price is not None
        )
        if (
            displayed is None
            or event.bid is None
            or event.ask is None
            or record.intent.limit_price is None
        ):
            return
        key = (event.event_at_ns, record.intent.side)
        prior_cap, used = capacity.get(key, (displayed * fraction, ZERO))
        cap = min(prior_cap, displayed * fraction)
        capacity[key] = cap, used
        increment = (
            request.instrument.quantity_increment
            if request.instrument.fractional_eligible
            else max(Decimal("1"), request.instrument.quantity_increment)
        )
        quantity = quantize_down(min(record.remaining, max(ZERO, cap - used)), increment)
        if not quantity:
            decide(event, "capacity_exhausted", order_id)
            return
        price = execution_price(
            side=record.intent.side,
            bid=event.bid,
            ask=event.ask,
            costs=SimulatedCosts(rates["extra_slippage"] * slippage_factor / 100, ZERO, ZERO),
        )
        rounded = quantize_down(price, request.instrument.price_increment)
        if record.intent.side is Side.BUY and rounded < price:
            rounded += request.instrument.price_increment
        if (record.intent.side is Side.BUY and rounded > record.intent.limit_price) or (
            record.intent.side is Side.SELL and rounded < record.intent.limit_price
        ):
            decide(event, "limit_not_marketable", order_id)
            return
        try:
            submitted = etf_execution_charges(
                request.costs,
                at=_ceil_time(record.submitted_at_ns),
                prior_quantity=ZERO,
                quantity=record.intent.quantity,
                price=record.intent.limit_price,
            )
            charges = etf_execution_charges(
                request.costs,
                at=_ceil_time(event.available_at_ns),
                prior_quantity=record.order.filled_quantity,
                quantity=quantity,
                price=rounded,
                prior_schedule_hash=schedules.get(order_id),
            )
            check(charges.fee_schedule_hash == submitted.fee_schedule_hash)
            digest = content_hash(
                (
                    "etf-native-fill-v1",
                    order_id,
                    event.source_hash,
                    quantity,
                    rounded,
                    charges.fee_schedule_hash,
                )
            )
            execution = Fill(
                FillId(digest),
                record.order.broker_order_id,
                record.order.account_id,
                record.order.instrument_id,
                record.intent.side,
                quantity,
                rounded,
                charges.total_fee_usd,
                _ceil_time(event.available_at_ns),
                DataHash(digest),
            )
            append("fill", event.available_at_ns, fill=execution)
        except ValueError:
            decide(event, "fee_or_account_reconciliation_denied", order_id)
            return
        capacity[key] = cap, used + quantity
        schedules[order_id] = charges.fee_schedule_hash
        fill_sessions[digest] = session_count
        decide(event, "simulated_fill", order_id)

    def project_outcome() -> EtfReplayOutcome:
        return EtfReplayOutcome(
            account_owner.events,
            state,
            tuple(daily),
            tuple(policies),
            tuple(decisions),
            tuple(sorted(reasons)),
        )

    for event in events:
        if event is None:
            yield project_outcome()
            continue
        last_source_event = event
        with localcontext(_fee_context()):
            # Flush a closed session before applying observations of the next one.
            if (
                current_session is not None
                and current_session.clock is not None
                and current_session.clock.next_close_at is not None
            ):
                close_ns = _ns(current_session.clock.next_close_at)
                if event.available_at_ns >= close_ns:
                    scheduled(close_ns)
                    snapshot(close_ns)
                    current_session = None
            scheduled(event.available_at_ns)
            if event.kind == "bar":
                check(event.bar is not None)
                if event.bar is not None:
                    if event.event_at_ns in bars and bars[event.event_at_ns] != event.bar:
                        reasons.add("bar_revision_timeline_unverified")
                    bars[event.event_at_ns] = event.bar
                continue
            if event.kind == "split":
                split_seen = True
                reasons.add("split_accounting_unsupported")
                continue
            if event.kind in ("dividend_ex", "dividend_pay"):
                if event.kind == "dividend_ex" and event.available_at_ns != event.event_at_ns:
                    # The v1 account owner derives entitlement from its current
                    # holdings. Applying a delayed ex-date at receipt would
                    # credit the wrong owner. Preserve the source observation,
                    # but do not invent entitlement or a corresponding payment.
                    check(event.action_id is not None)
                    if event.action_id is not None:
                        unresolved_actions.add(event.action_id)
                    reasons.update(
                        (
                            "input_reconciliation_incomplete",
                            "delayed_distribution_entitlement_unverified",
                        )
                    )
                    decide(event, "delayed_distribution_entitlement_unverified")
                    continue
                if event.action_id in unresolved_actions:
                    decide(event, "input_reconciliation_incomplete")
                    continue
                if event.kind == "dividend_ex":
                    distributions.append(
                        CorporateAction(
                            InstrumentId("SPY"),
                            "dividend",
                            _session_date(event.event_at_ns),
                            _ceil_time(event.available_at_ns),
                            None,
                            event.cash_per_share,
                            DataHash(event.source_hash),
                        )
                    )
                    append(
                        event.kind,
                        event.available_at_ns,
                        action_id=event.action_id,
                        cash_per_share=event.cash_per_share,
                    )
                else:
                    append(event.kind, event.available_at_ns, action_id=event.action_id)
                continue
            if event.kind in ("session", "control"):
                if event.kind == "session" and (
                    (
                        previous_session_open is not None
                        and event.event_at_ns <= previous_session_open
                    )
                    or (clock is not None and event.event_at_ns < clock.event_at_ns)
                    or (quote is not None and event.event_at_ns <= quote.event_at_ns)
                ):
                    decide(event, "native_session_time_regression")
                    reasons.add("native_session_time_regression")
                    continue
                if clock is None or event.event_at_ns > clock.event_at_ns:
                    clock, control_conflict = event, False
                elif event.event_at_ns == clock.event_at_ns and (
                    event.clock != clock.clock or event.execution_reasons != clock.execution_reasons
                ):
                    control_conflict = True
                if event.kind != "session":
                    continue
                session_count += 1
                due = tuple(
                    fid
                    for fid, origin in fill_sessions.items()
                    if session_count - origin >= request.schedule.settlement_sessions
                    and any(fid == row[0] for row in state.unsettled)
                )
                if due:
                    append("settlement", event.available_at_ns, fill_ids=due)
                current_session = event
                selected = tuple(
                    b for stamp, b in sorted(bars.items()) if stamp < event.available_at_ns
                )
                current_eligible = len(selected) >= cfg.research.minimum_history_bars
                frame, atr, frame_day, on_cadence = None, None, None, False
                if not current_eligible:
                    previous_session_open = event.event_at_ns
                    decide(event, "warmup_incomplete")
                    continue
                on_cadence = eligible_count % request.study.rebalance_sessions == 0
                eligible_count += 1
                history = selected[-100:]
                stale_history = (
                    previous_session_open is not None
                    and _ns(history[-1].ends_at) <= previous_session_open
                )
                previous_session_open = event.event_at_ns
                if stale_history:
                    decide(event, "completed_previous_session_bar_missing")
                    continue
                now = _ceil_time(event.available_at_ns)
                with localcontext(_context(exact=False)):
                    history = adjust_bars(
                        history,
                        tuple(distributions),
                        as_of=now,
                        session_dates=tuple(_session_date(_ns(bar.starts_at)) for bar in history),
                    )
                    vector = FeaturePipeline(short_window=20, long_window=100).compute(
                        HistoricalSlice(InstrumentId("SPY"), history, None, content_hash(history)),
                        as_of=now,
                    )
                    frame = MomentumStrategy(short_window=20, long_window=100).decide(
                        StrategyContext(
                            now,
                            FeatureSnapshot(now, (vector,), content_hash(vector)),
                            policy.config_hash,
                            (InstrumentId("SPY"),),
                        )
                    )[0]
                value = dict(vector.values).get("average_true_range")
                atr = value if type(value) is Decimal and value > 0 else None
                frame_day = _session_date(event.event_at_ns)
                decide(event, "signal_" + frame.action.value)
                continue
            if quote is None or event.event_at_ns > quote.event_at_ns:
                # Older quotes never reach capacity use. Only equal-native-time
                # deliveries share a budget, so the prior frontier is dispensable.
                capacity.clear()
                quote, quote_conflict = event, False
            elif event.event_at_ns < quote.event_at_ns:
                decide(event, "native_quote_time_regression")
                continue
            elif (event.bid, event.ask, event.execution_reasons) != (
                quote.bid,
                quote.ask,
                quote.execution_reasons,
            ):
                quote_conflict = True
            reason = market_reason(event)
            if reason is not None:
                decide(event, reason)
                reasons.add(reason)
                continue
            if state.last_at_ns is not None and state.last_at_ns > event.available_at_ns:
                decide(event, "account_time_not_reached")
                continue
            check(event.bid is not None)
            append("mark", event.available_at_ns, mark_price=event.bid)
            active = next((o for o in state.orders if o.order.state not in _TERMINAL), None)
            entry = next(
                (
                    p
                    for p in reversed(policies)
                    if any(o.episode_id == p.order_id for o in state.orders)
                    and (state.shares > 0 or (active and active.intent.side is Side.BUY))
                ),
                None,
            )
            if entry is not None and trigger is None:
                first_fill = min(
                    (
                        e.at_ns
                        for e in account_owner.events
                        if e.fill is not None and e.fill.broker_order_id == entry.order_id
                    ),
                    default=None,
                )
                holding = sum(
                    first_fill is not None and first_fill < stamp < event.available_at_ns
                    for stamp in bars
                )
                if event.bid is not None and event.bid <= entry.stop_price:
                    trigger = "stop_triggered"
                elif not benchmark and event.bid is not None and event.bid >= entry.target_price:
                    trigger = "target_triggered"
                elif (
                    not benchmark
                    and first_fill is not None
                    and holding >= entry.maximum_holding_bars
                ):
                    trigger = "maximum_holding"
                elif (
                    not benchmark
                    and entry.exit_on_regime_change
                    and on_cadence
                    and frame_day == _session_date(event.available_at_ns)
                    and frame is not None
                    and frame.action is StrategyAction.HOLD
                ):
                    trigger = "regime_exit"
                if trigger is not None:
                    decide(event, trigger, entry.order_id)
            if trigger is not None and entry is not None:
                if active is not None and active.intent.side is Side.BUY:
                    if (
                        active.order.state is OrderState.CANCEL_PENDING
                        and request.schedule.allow_inflight_cancel_fill
                    ):
                        fill(event, active.intent.id, in_flight=True)
                    if active.order.state in (OrderState.SUBMITTED, OrderState.PARTIALLY_FILLED):
                        append(
                            "order_status",
                            event.available_at_ns,
                            order_id=active.intent.id,
                            order_event=OrderEvent.REQUEST_CANCEL,
                        )
                        pending.append(
                            (
                                event.available_at_ns + request.schedule.cancellation_delay_ns,
                                "cancel",
                                active.intent.id,
                            )
                        )
                    decide(event, "entry_cancel_reconciliation_required", active.intent.id)
                    continue
                if active is None and state.shares > 0:
                    propose(event, entry)
                    continue
            if active is not None:
                fill(event, active.intent.id)
            elif state.shares == 0:
                trigger = None
                day = _session_date(event.available_at_ns)
                if (
                    frame is not None
                    and atr is not None
                    and frame_day == day
                    and on_cadence
                    and day not in attempted
                    and (frame.action is StrategyAction.ENTER_LONG or benchmark)
                    and (not benchmark or not policies)
                ):
                    attempted.add(day)
                    propose(event, None)
    with localcontext(_fee_context()):
        if current_session is not None and last_source_event is not None:
            snapshot(last_source_event.available_at_ns)
            reasons.add("source_ends_inside_session")
    if not state.complete:
        reasons.add("account_outcome_incomplete")
    return project_outcome()


def run_etf_history(
    request: EtfHistoryRequest, *, through_ordinal: int | None = None
) -> EtfHistoryResult:
    """Run a development-only prefix; no fabricated terminal sale or settlement."""
    check(type(request) is EtfHistoryRequest)
    replace(request)
    events = _development(request)
    if through_ordinal is not None:
        check(type(through_ordinal) is int)
        matches = [i + 1 for i, e in enumerate(events) if e.ordinal == through_ordinal]
        check(len(matches) == 1)
        events = events[: matches[0]]
    return _run_count(request, len(events))


def _run_count(request: EtfHistoryRequest, count: int) -> EtfHistoryResult:
    check(type(count) is int and 0 <= count <= len(_development(request)))
    events = _development(request)[:count]
    candidate = _outcome(request, events, benchmark=False)
    constrained = _outcome(request, events, benchmark=True)
    return EtfHistoryResult(
        request.input_hash,
        request.study.study_hash,
        request.dataset.dataset_hash,
        request.costs.cost_hash,
        content_hash(
            (
                "etf-native-simulation-protocol-v1",
                request.schedule,
                request.instrument,
                "bid-ask-later-event",
                "constrained-buy-hold-with-protective-stop",
                "holdout-sealed",
            )
        ),
        request.initial_cash,
        request.fill_scenario,
        len(events),
        content_hash(events),
        candidate,
        constrained,
        tuple(
            sorted(
                set(request.dataset.limitations)
                | {
                    "simulated_lifecycle_assumptions_unverified",
                    "execution_costs_uncalibrated",
                    "holdout_not_evaluated",
                    "source_not_qualified",
                }
            )
        ),
        tuple(e.bar for e in events if e.bar is not None),
    )


def resume_etf_history(
    request: EtfHistoryRequest, checkpoint: EtfHistoryResult
) -> EtfHistoryResult:
    """Reconstruct consumed facts; changed identity/state never schedules a retry."""
    check(type(checkpoint) is EtfHistoryResult and checkpoint.input_hash == request.input_hash)
    events = _development(request)
    check(type(checkpoint.source_count) is int and 0 < checkpoint.source_count <= len(events))
    rebuilt = run_etf_history(request, through_ordinal=events[checkpoint.source_count - 1].ordinal)
    check(rebuilt == checkpoint)
    return run_etf_history(request)
