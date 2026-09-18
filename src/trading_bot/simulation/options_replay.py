"""One synthetic long-option episode through shared features and order transitions.

This is not a broker composition or a full production pretrade evaluation. No network,
credentials, real data or promotion persistence is reachable from this module.
"""

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal, localcontext

from trading_bot.config.hashing import hash_loaded_config
from trading_bot.domain import InstrumentId
from trading_bot.domain.decimal_utils import DomainValidationError
from trading_bot.domain.enums import OrderEvent, OrderState, Side
from trading_bot.domain.options import (
    OptionKind,
    OptionLeg,
    OptionsOrderIntent,
    OptionStructure,
    PositionEffect,
    StructureKind,
    executable_quote_reasons,
)
from trading_bot.domain.options_serialization import options_intent_sha256
from trading_bot.domain.order_state_machine import transition
from trading_bot.market_data.recording import content_hash
from trading_bot.risk.options_economics import (
    OptionsCapitalState,
    TrialEpisode,
    TrialLossState,
    long_option_feasibility,
)
from trading_bot.simulation.options_replay_models import (
    OptionsReplayCashFlow,
    OptionsReplayRequest,
    OptionsReplayResult,
    OptionsReplayTransition,
)
from trading_bot.strategies.features import FeaturePipeline
from trading_bot.strategies.options.momentum import OptionsMomentumStrategy
from trading_bot.strategies.protocol import FeatureSnapshot, StrategyAction, StrategyContext

_TERMINAL = frozenset(
    {
        OrderState.FILLED,
        OrderState.CANCELED,
        OrderState.REJECTED,
        OrderState.EXPIRED,
        OrderState.RISK_REJECTED,
    }
)
_FILLABLE = frozenset({OrderState.SUBMITTED, OrderState.CANCEL_PENDING})


def replay_options(
    request: OptionsReplayRequest, *, event_count: int | None = None
) -> OptionsReplayResult:
    """Replay a recorded fixture, optionally only its first N events.

    The identity binds the entire immutable script, as in the original v1 format.
    Prefix processing never consumes later events; this is not a streaming-data API.
    """
    if type(request) is not OptionsReplayRequest:
        raise DomainValidationError("exact replay request required")
    count = len(request.events) if event_count is None else event_count
    if type(count) is not int or not 0 <= count <= len(request.events):
        raise DomainValidationError("invalid replay event count")
    with localcontext() as ctx:
        ctx.prec = 2048
        return _replay(request, count)


def _replay(r: OptionsReplayRequest, count: int) -> OptionsReplayResult:
    config = r.loaded.config
    canonical, digest = hash_loaded_config(config, r.loaded.safety_envelope)
    if canonical != r.loaded.canonical_json or digest != r.loaded.config_hash:
        raise DomainValidationError("configuration identity mismatch")
    if len(r.history.bars) < config.research.minimum_history_bars:
        raise DomainValidationError("insufficient underlying history")
    input_hash = content_hash(
        {
            "config_hash": digest,
            "capital": r.research_capital,
            "as_of": r.as_of,
            "history": r.history,
            "contract": r.contract,
            "quote": r.initial_quote,
            "fees": (r.entry_fee, r.exit_fee),
            "close_limit": r.close_limit,
            "events": r.events,
            "trial": r.trial,
            "source": r.source_kind,
        }
    )
    short = config.equity_strategies.short_windows[0]
    long = config.equity_strategies.long_windows[0]
    # Feature ratios are numerical analytics, not cash-flow arithmetic. Bound their
    # repeating-decimal precision before the existing feature serializer hashes them.
    with localcontext() as analytics:
        analytics.prec = 64
        features = FeaturePipeline(short_window=short, long_window=long).compute(
            r.history, as_of=r.as_of
        )
    strategy = OptionsMomentumStrategy(
        kind=r.contract.kind,
        short_window=short,
        long_window=long,
    )
    decision = strategy.decide(
        StrategyContext(
            r.as_of,
            FeatureSnapshot(r.as_of, (features,), features.data_hash),
            digest,
            (InstrumentId(r.contract.underlying),),
        )
    )[0]
    reasons = list(
        executable_quote_reasons(
            r.contract,
            r.initial_quote,
            as_of=r.as_of,
            max_age_seconds=config.freshness.max_executable_quote_age_seconds,
            max_underlying_skew_seconds=config.market_data.max_cross_response_timestamp_skew_seconds,
            allow_locked=config.options.allow_locked_quotes,
        )
    )
    if decision.action is not StrategyAction.ENTER_LONG:
        reasons.append("no_momentum_candidate")
    capital = OptionsCapitalState(
        r.research_capital, r.research_capital, r.research_capital, Decimal(0), Decimal(0), 0, 0
    )
    feasible = long_option_feasibility(
        r.loaded,
        capital,
        premium=r.initial_quote.ask,
        multiplier=r.contract.premium_multiplier,
        fee_reserve_per_unit=r.entry_fee + r.exit_fee,
        trial=r.trial,
    )
    reasons.extend(feasible.reason_codes)
    entry = OrderState.PROPOSED
    close: OrderState | None = None
    transitions: list[OptionsReplayTransition] = []

    def advance(order: str, current: OrderState, event: OrderEvent, at: datetime) -> OrderState:
        next_state = transition(current, event)
        transitions.append(OptionsReplayTransition(at, order, event, current, next_state))
        return next_state

    if reasons:
        entry = advance("entry", entry, OrderEvent.RISK_DENY, r.as_of)
        return OptionsReplayResult(
            "capital_denied" if feasible.admissible_units == 0 else "candidate_denied",
            digest,
            input_hash,
            None,
            r.research_capital,
            Decimal(0),
            Decimal(0),
            Decimal(0),
            0,
            entry,
            None,
            r.trial,
            (),
            tuple(transitions),
            tuple(reasons),
        )

    def order_deadline(created_at: datetime) -> datetime:
        session = next(
            (s for s in r.contract.eligible_sessions if s.opens_at <= created_at < s.closes_at),
            None,
        )
        if session is None:
            raise DomainValidationError("order creation requires an eligible option session")
        return min(
            created_at + timedelta(seconds=config.runtime.remainder_order_max_age_seconds),
            session.closes_at,
            r.contract.last_trading_at,
        )

    structure_kind = (
        StructureKind.LONG_CALL if r.contract.kind is OptionKind.CALL else StructureKind.LONG_PUT
    )
    intent = OptionsOrderIntent(
        "synthetic-entry-" + input_hash,
        "synthetic-research",
        OptionStructure(structure_kind, (OptionLeg(r.contract, Side.BUY, PositionEffect.OPEN, 1),)),
        1,
        r.initial_quote.ask,
        "debit",
        r.as_of,
        order_deadline(r.as_of),
        decision.strategy_version,
        digest,
        input_hash,
        "synthetic-explicit-close-v1",
        "limit",
        "day",
    )
    intent_hash = options_intent_sha256(intent)

    def propose(order: str, at: datetime) -> OrderState:
        state = OrderState.PROPOSED
        # These are simulated review stages, not official-interface evidence.
        for event in (
            OrderEvent.RISK_ALLOW,
            OrderEvent.REQUEST_REVIEW,
            OrderEvent.REVIEW_ACCEPTED,
            OrderEvent.PREPARE_SUBMISSION,
        ):
            state = advance(order, state, event, at)
        return state

    entry = propose("entry", r.as_of)
    entry_accepted_at: datetime | None = None
    close_intent: OptionsOrderIntent | None = None
    cash = r.research_capital
    receivable = Decimal(0)
    settlement_pending = False
    units = 0
    flows: list[OptionsReplayCashFlow] = []
    latency = timedelta(milliseconds=config.simulation.latency_milliseconds)
    for event in r.events[:count]:
        if event.action == "accept_entry":
            entry = advance("entry", entry, OrderEvent.BROKER_ACCEPTED, event.at)
            entry_accepted_at = event.at
        elif event.action == "reject_entry":
            entry = advance("entry", entry, OrderEvent.BROKER_REJECTED, event.at)
        elif event.action == "unknown_entry":
            transition_event = (
                OrderEvent.BROKER_AMBIGUOUS
                if entry is OrderState.SUBMISSION_PENDING
                else OrderEvent.RECONCILIATION_DRIFT
            )
            entry = advance("entry", entry, transition_event, event.at)
        elif event.action == "cancel_entry":
            entry = advance("entry", entry, OrderEvent.REQUEST_CANCEL, event.at)
        elif event.action == "confirm_cancel":
            entry = advance("entry", entry, OrderEvent.CANCEL_CONFIRMED, event.at)
        elif event.action == "request_close":
            if units != 1 or entry not in _TERMINAL or close is not None:
                raise DomainValidationError(
                    "close requires one reconciled unit and no conflicting order"
                )
            close_intent = replace(
                intent,
                intent_id="synthetic-close-" + input_hash,
                structure=OptionStructure(
                    structure_kind,
                    (OptionLeg(r.contract, Side.SELL, PositionEffect.CLOSE, 1),),
                ),
                limit_price=r.close_limit,
                net_effect="credit",
                created_at=event.at,
                expires_at=order_deadline(event.at),
            )
            close = propose("close", event.at)
            close = advance("close", close, OrderEvent.BROKER_ACCEPTED, event.at)
        elif event.action == "settle":
            if units or entry not in _TERMINAL or (close is not None and close not in _TERMINAL):
                raise DomainValidationError("cannot settle unresolved strategy episode")
            cash += receivable
            receivable = Decimal(0)
            settlement_pending = False
        elif event.action == "market":
            quote = event.quote
            if quote is None:
                raise DomainValidationError("market quote missing")
            invalid = executable_quote_reasons(
                r.contract,
                quote,
                as_of=event.at,
                max_age_seconds=config.freshness.max_executable_quote_age_seconds,
                max_underlying_skew_seconds=config.market_data.max_cross_response_timestamp_skew_seconds,
                allow_locked=config.options.allow_locked_quotes,
            )
            if invalid:
                continue
            if (
                entry in _FILLABLE
                and entry_accepted_at is not None
                and quote.event_at > entry_accepted_at
                and r.as_of + latency <= quote.event_at <= event.at < intent.expires_at
                and quote.ask <= intent.limit_price
            ):
                amount = -(quote.ask * r.contract.premium_multiplier + r.entry_fee)
                cash += amount
                units = 1
                flows.append(
                    OptionsReplayCashFlow(event.event_id, event.at, "entry", amount, r.entry_fee)
                )
                entry = advance("entry", entry, OrderEvent.FILL, event.at)
            elif (
                close is not None
                and close in _FILLABLE
                and close_intent is not None
                and units == 1
                and quote.event_at > close_intent.created_at
                and close_intent.created_at + latency
                <= quote.event_at
                <= event.at
                < close_intent.expires_at
                and quote.bid >= close_intent.limit_price
            ):
                amount = quote.bid * r.contract.premium_multiplier - r.exit_fee
                receivable += amount
                # Numeric netting is not evidence that gross proceeds and fees settled.
                settlement_pending = True
                units = 0
                flows.append(
                    OptionsReplayCashFlow(event.event_id, event.at, "close", amount, r.exit_fee)
                )
                close = advance("close", close, OrderEvent.FILL, event.at)
    net = sum((flow.amount for flow in flows), Decimal(0))
    fees = sum((flow.fee for flow in flows), Decimal(0))
    terminal = entry in _TERMINAL and (close is None or close in _TERMINAL)
    episode = TrialEpisode(
        "synthetic-episode-" + input_hash,
        feasible.unit_payoff_risk,
        net,
        units == 0,
        terminal,
        not settlement_pending,
    )
    trial = TrialLossState((*r.trial.episodes, episode))
    if cash + receivable != r.research_capital + net:
        raise DomainValidationError("cash-flow conservation failed")
    return OptionsReplayResult(
        "completed_synthetic_replay" if episode.complete else "incomplete_synthetic_replay",
        digest,
        input_hash,
        intent_hash,
        cash,
        receivable,
        net,
        fees,
        units,
        entry,
        close,
        trial,
        tuple(flows),
        tuple(transitions),
        () if episode.complete else ("episode_incomplete",),
    )
