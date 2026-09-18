"""Value-only composition of the existing decision pipeline for synthetic replay."""

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal, localcontext

from trading_bot.app import (
    DecisionCycleService,
    PerInstrumentDecisionCycleRequest,
    ValidatedMarketSnapshot,
)
from trading_bot.domain import (
    ConfigHash,
    InstrumentId,
    OrderIntent,
    OrderIntentId,
    Side,
    quantize_down,
)
from trading_bot.market_data.recording import content_hash
from trading_bot.market_data.snapshot_loader import BundleSnapshotLoader
from trading_bot.portfolio import (
    IntentPlanner,
    IntentPlanningContext,
    PortfolioConstructor,
    TargetPortfolio,
)
from trading_bot.simulation.equity_replay_codec import encode_order_outcome
from trading_bot.simulation.equity_replay_models import ReplayDecision, deny
from trading_bot.simulation.equity_replay_policy import (
    derive_entry_policy,
    exit_reason,
    observe_entry,
    planning_policy,
    selected_instruments,
)
from trading_bot.simulation.equity_replay_records import ReplayCycleRecord
from trading_bot.simulation.equity_replay_state import ReplayState
from trading_bot.simulation.lifecycle_accounting import _context
from trading_bot.strategies import FeaturePipeline
from trading_bot.strategies.momentum import MomentumStrategy
from trading_bot.strategies.protocol import (
    FeatureSnapshot,
    Strategy,
    StrategyAction,
    StrategyContext,
    StrategyDecision,
    StrategyDescriptor,
)
from trading_bot.strategies.relative_strength import RelativeStrengthStrategy


class _Features:
    def __init__(self, market: ValidatedMarketSnapshot, short: int, long: int) -> None:
        self.market = market
        pipeline = FeaturePipeline(short_window=short, long_window=long)
        # Indicators intentionally use fixed, rounded Decimal arithmetic. Monetary/fill
        # accounting remains exact in its existing inner contexts; it is not rounded here.
        with localcontext(_context(exact=False)):
            vectors = tuple(pipeline.compute(h, as_of=market.as_of) for h in market.histories)
        self.snapshot = FeatureSnapshot(
            market.as_of, vectors, content_hash((market.as_of, vectors))
        )

    def compute(self, market: ValidatedMarketSnapshot, *, as_of: datetime) -> FeatureSnapshot:
        if market != self.market or as_of != market.as_of:
            deny("replay_cycle_identity_invalid")
        return self.snapshot


class _PreparedStrategy:
    def __init__(
        self, original: Strategy, context: StrategyContext, decisions: tuple[StrategyDecision, ...]
    ) -> None:
        self.original, self.context, self.decisions = original, context, decisions

    @property
    def descriptor(self) -> StrategyDescriptor:
        return self.original.descriptor

    def decide(self, context: StrategyContext) -> tuple[StrategyDecision, ...]:
        if context != self.context:
            deny("replay_cycle_identity_invalid")
        return self.decisions


class _Planner(IntentPlanner):
    def __init__(self, state: ReplayState, cycle_key: str) -> None:
        self.state, self.cycle_key, self.ordinal = state, cycle_key, 0
        super().__init__(id_factory=self._identifier)

    def _identifier(self) -> OrderIntentId:
        self.ordinal += 1
        return OrderIntentId("replay-intent:" + content_hash((self.cycle_key, self.ordinal)))

    def plan(
        self, target: TargetPortfolio, context: IntentPlanningContext
    ) -> tuple[OrderIntent, ...]:
        intents: list[OrderIntent] = []
        # Reuse canonical sizing for each desired target; admission rechecks final sizing
        # and reservations afresh for every intent and never silently resizes a denial.
        for desired in sorted(
            target.positions, key=lambda p: (p.target_notional > 0, p.instrument_id)
        ):
            declared = self.state.session(desired.instrument_id, target.as_of)
            current = replace(context, expires_after=declared.window.ends_at - target.as_of)
            intents.extend(super().plan(replace(target, positions=(desired,)), current))
        return tuple(intents)


class _Journal:
    async def finalize(self, payload: object) -> tuple[str, ...]:
        if type(payload) is not dict:
            deny("replay_cycle_identity_invalid")
        return ("replay-cycle:" + content_hash(payload),)


class ReplayCycleComposition:
    def __init__(self, state: ReplayState) -> None:
        self.state = state
        request = state.request
        self.loader = BundleSnapshotLoader(request.bundle, settings=request.snapshot_settings)
        candidate = request.candidate
        self.strategy: Strategy = (
            MomentumStrategy(short_window=candidate.short_window, long_window=candidate.long_window)
            if candidate.strategy_id == "equity_momentum"
            else RelativeStrengthStrategy(
                lookback_window=candidate.long_window, top_n=candidate.top_n or 1
            )
        )

    async def run(self, decision: ReplayDecision) -> ReplayCycleRecord:
        state, request = self.state, self.state.request
        at = decision.cursor.occurred_at
        universe = tuple(sorted(i.id for i in request.instruments))
        market = await self.loader.load(universe, at)
        features = _Features(market, request.candidate.short_window, request.candidate.long_window)
        context = StrategyContext(
            at, features.snapshot, ConfigHash(request.loaded.config_hash), universe
        )
        raw = self.strategy.decide(context)
        bars = {h.instrument_id: h.bars for h in market.histories}
        counts = tuple(len(bars[symbol]) for symbol in universe)
        count = min(counts)
        if request.candidate.strategy_id == "equity_relative_strength":
            if any(
                tuple(b.ends_at for b in bars[s]) != tuple(b.ends_at for b in bars[universe[0]])
                for s in universe
            ):
                deny("replay_rebalance_history_invalid")
            selected = (
                None
                if state.last_rebalance_bars == count
                else selected_instruments(request, context, completed_bars=count)
            )
            if selected is not None:
                state.last_rebalance_bars = count
        else:
            selected = selected_instruments(request, context, completed_bars=count)
        snapshot = state.observe(at)
        positions = {p.instrument_id: p for p in snapshot.positions}
        vectors = {v.instrument_id: v for v in features.snapshot.vectors}
        instruments = {i.id: i for i in request.instruments}
        prices: list[tuple[str, Decimal]] = []
        prepared = []
        new_policies = []
        cancellations: list[tuple[InstrumentId, str]] = []
        for item in sorted(raw, key=lambda d: d.instrument_id):
            symbol = item.instrument_id
            event = state.event(symbol, at)
            active = state.active(symbol)
            price = event.quote.bid if symbol in positions else event.quote.ask
            if price is None:
                deny("replay_quote_unavailable")
            price = quantize_down(price, instruments[symbol].price_increment)
            prices.append((symbol, price))
            action = StrategyAction.HOLD
            reasons: tuple[str, ...] = ("replay_no_new_selection",)
            if symbol in positions:
                policy = state.policies.get(symbol)
                entries = tuple(
                    o
                    for o in state.book.orders
                    if o.intent.instrument_id == symbol and o.intent.side is Side.BUY
                )
                if policy is None or not entries:
                    deny("replay_policy_identity_invalid")
                policy = observe_entry(policy, entries[-1], bars[symbol], at, request)
                state.policies[symbol] = policy
                trigger = exit_reason(
                    policy,
                    event.quote,
                    None if selected is None else symbol in selected,
                    at,
                    request,
                )
                reasons = ("replay_holding_position",)
                if trigger is not None:
                    if active is None:
                        action, reasons = StrategyAction.EXIT_LONG, (trigger,)
                    elif active.intent.side is Side.BUY:
                        cancellations.append((symbol, trigger))
                        reasons = ("replay_exit_waiting_for_entry_cancel", trigger)
                    else:
                        reasons = ("replay_exit_already_active", trigger)
            elif active is not None:
                reasons = ("replay_entry_already_active",)
            elif selected is not None and symbol in selected:
                policy = derive_entry_policy(request, vectors[symbol], price)
                new_policies.append(policy)
                action, reasons = StrategyAction.ENTER_LONG, item.reason_codes
            prepared.append(replace(item, action=action, reason_codes=reasons))
        state.cycle_policies = tuple(new_policies)
        state.observe(at, policies=state.cycle_policies)
        cycle_key = content_hash(
            (
                state.book.request_identity.run_key,
                decision,
                market.data_hash,
                features.snapshot.data_hash,
                snapshot.data_hash,
                tuple(prices),
                tuple(prepared),
            )
        )
        config = request.loaded.config
        planning = IntentPlanningContext(
            request.account_id,
            snapshot,
            request.instruments,
            tuple(prices),
            snapshot.equity,
            request.initial_cash,
            config.position_risk,
            config.activity,
            timedelta(0),
        )
        cycle_request = PerInstrumentDecisionCycleRequest(
            universe,
            at,
            snapshot,
            request.loaded.config_hash,
            request.candidate.exposure_multiplier,
            None,
            planning,
            tuple((p.instrument_id, planning_policy(p, request)) for p in state.cycle_policies),
        )
        state.checks = []
        service = DecisionCycleService(
            snapshot_loader=self.loader,
            features=features,
            strategies=(_PreparedStrategy(self.strategy, context, tuple(prepared)),),
            portfolio=PortfolioConstructor(),
            intent_planner=_Planner(state, str(cycle_key)),
            execution=state,
            journal=_Journal(),
            outcome_encoder=encode_order_outcome,
        )
        with localcontext(_context(exact=False)):
            result = await service.run_cycle(cycle_request)
        for symbol, reason in cancellations:
            active = state.active(symbol)
            if active is not None:
                state.cancel(active, at, reason)
        return ReplayCycleRecord(decision, result, tuple(state.checks), tuple(cancellations))
