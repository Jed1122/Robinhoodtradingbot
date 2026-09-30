"""Independent research accounting from bound facts; no execution or admission API.

The future episode owner must supply independently risk-admitted, causally verified
facts. Replaying this journal proves internal conservation only, never market truth,
policy compliance, provider calibration, or permission to trade.
"""

from dataclasses import replace
from decimal import Decimal, localcontext
from typing import cast

from trading_bot.config import LoadedConfig, enforce_safety_envelope
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.domain import DataHash
from trading_bot.domain.enums import OrderEvent, OrderState, Side
from trading_bot.domain.options import StructureKind
from trading_bot.domain.order_state_machine import transition
from trading_bot.market_data.options_session_inputs import _ns
from trading_bot.market_data.options_source_models import check
from trading_bot.market_data.options_source_verify import ceil_available_at
from trading_bot.market_data.recording import content_hash
from trading_bot.research.options_account_journal_models import (
    AccountJournalEntry,
    JournalComplete,
    JournalExternalFlow,
    JournalIncident,
    JournalIntent,
    JournalMark,
    JournalOrderUpdate,
    JournalRiskObservation,
    JournalSettlement,
)
from trading_bot.research.options_study_models import StudyScenario
from trading_bot.risk.options_loss_history import (
    OptionsLossObservation,
    evaluate_options_loss_observations,
)
from trading_bot.simulation.options_historical_models import (
    HISTORICAL_TERMINAL as TERMINAL,
)
from trading_bot.simulation.options_historical_models import (
    AccountEpisodeBalance,
    AccountOptionPosition,
    AccountOrderBalance,
    AccountSettlement,
    OptionsAccountPathState,
)

__all__ = [
    "AccountJournalEntry",
    "JournalComplete",
    "JournalExternalFlow",
    "JournalIncident",
    "JournalIntent",
    "JournalMark",
    "JournalOrderUpdate",
    "JournalRiskObservation",
    "JournalSettlement",
    "initial_account_path",
    "reconcile_account_journal",
    "reconstruct_account_journal",
]


def initial_account_path(
    *,
    study_hash: DataHash,
    capital: Decimal,
    start_ns: int,
    loaded: LoadedConfig,
    scenario: StudyScenario,
) -> OptionsAccountPathState:
    check(type(loaded) is LoadedConfig and type(scenario) is StudyScenario)
    enforce_safety_envelope(loaded.config, loaded.safety_envelope)
    check(
        hash_loaded_config(loaded.config, loaded.safety_envelope)
        == (loaded.canonical_json, loaded.config_hash)
    )
    check(loaded.config.options.enabled and not loaded.config.live_trading_enabled)
    digest = content_hash(
        (
            "options-account-genesis-v1",
            study_hash,
            loaded.config_hash,
            scenario.scenario_hash,
            capital,
            start_ns,
        )
    )
    return OptionsAccountPathState(
        path_id="synthetic:" + digest,
        study_hash=study_hash,
        config_hash=loaded.config_hash,
        scenario_hash=scenario.scenario_hash,
        authorized_capital=capital,
        start_ns=start_ns,
        cash=capital,
        fees=Decimal(0),
        cumulative_external_flows=Decimal(0),
        episodes=(),
        orders=(),
        positions=(),
        unsettled=(),
        session_entry_counts=(),
        latched_halts=(),
        incidents=(),
        last_event_ns=start_ns,
        last_event_id=None,
        journal_hash=digest,
    )


def _intent(
    state: OptionsAccountPathState, fact: JournalIntent, at: int, scenario: StudyScenario
) -> OptionsAccountPathState:
    intent = fact.intent
    check(intent.account_scope == state.path_id and intent.config_hash == state.config_hash)
    check(intent.created_at == ceil_available_at(at))
    check(intent.structure.kind in (StructureKind.LONG_CALL, StructureKind.LONG_PUT))
    check(len(intent.structure.legs) == 1 and intent.structure.legs[0].ratio == 1)
    check(not any(o.intent.intent_id == intent.intent_id for o in state.orders))
    leg = intent.structure.legs[0]
    episode = next((e for e in state.episodes if e.episode_id == fact.episode_id), None)
    episodes = state.episodes
    counts = dict(state.session_entry_counts)
    if leg.side is Side.BUY:
        check(episode is None)
        reservation = intent.limit_price * leg.contract.premium_multiplier * intent.quantity
        reservation += scenario.fee_bound_per_unit * intent.quantity
        episodes = (*episodes, AccountEpisodeBalance(fact.episode_id, fact.session_id, reservation))
        counts[fact.session_id] = counts.get(fact.session_id, 0) + 1
    else:
        check(episode is not None and not episode.finalized)
        position = next((p for p in state.positions if p.episode_id == fact.episode_id), None)
        check(
            position is not None
            and position.contract == leg.contract
            and position.units >= intent.quantity
        )
        check(all(o.state in TERMINAL for o in state.orders if o.episode_id == fact.episode_id))
    return replace(
        state,
        episodes=episodes,
        session_entry_counts=tuple(sorted(counts.items())),
        orders=(
            *state.orders,
            AccountOrderBalance(fact.episode_id, intent, OrderState.SUBMISSION_PENDING, at),
        ),
    )


def _order_update(
    state: OptionsAccountPathState,
    entry: AccountJournalEntry,
    fact: JournalOrderUpdate,
    scenario: StudyScenario,
) -> OptionsAccountPathState:
    order = next((o for o in state.orders if o.intent.intent_id == fact.order_id), None)
    check(order is not None)
    order = cast(AccountOrderBalance, order)
    check(entry.available_ns > order.decision_ns)
    # Unknown outcomes stay reserved. A status label cannot invent missing fill facts.
    check(
        fact.event
        in (
            OrderEvent.BROKER_ACCEPTED,
            OrderEvent.BROKER_REJECTED,
            OrderEvent.BROKER_AMBIGUOUS,
            OrderEvent.FILL,
            OrderEvent.PARTIAL_FILL,
            OrderEvent.REQUEST_CANCEL,
            OrderEvent.CANCEL_CONFIRMED,
            OrderEvent.CANCEL_REJECTED,
            OrderEvent.BROKER_EXPIRED,
            OrderEvent.RECONCILIATION_DRIFT,
        )
    )
    if fact.event is OrderEvent.BROKER_EXPIRED:
        check(entry.available_ns >= _ns(order.intent.expires_at))
    next_state = transition(order.state, fact.event)
    changed = replace(
        order,
        state=next_state,
        filled_units=order.filled_units + fact.fill_units,
        accepted_ns=entry.available_ns
        if fact.event is OrderEvent.BROKER_ACCEPTED
        else order.accepted_ns,
    )
    episodes, positions, unsettled = state.episodes, state.positions, state.unsettled
    cash, fees = state.cash, state.fees
    if fact.fill_units:
        check(order.accepted_ns is not None and entry.available_ns > order.accepted_ns)
        check((changed.filled_units == order.intent.quantity) == (fact.event is OrderEvent.FILL))
        check(entry.available_ns < _ns(order.intent.expires_at))
        leg = order.intent.structure.legs[0]
        buying = leg.side is Side.BUY
        price = cast(Decimal, fact.price)
        check(price % leg.contract.tick_size == 0)
        check(price <= order.intent.limit_price if buying else price >= order.intent.limit_price)
        check(fact.fee == (scenario.entry_fee if buying else scenario.exit_fee) * fact.fill_units)
        amount = (
            price * leg.contract.premium_multiplier * fact.fill_units * (-1 if buying else 1)
            - fact.fee
        )
        cash, fees = cash + amount, fees + fact.fee
        episode = next(e for e in state.episodes if e.episode_id == order.episode_id)
        check(not episode.finalized)
        episodes = tuple(
            replace(e, net_cash_flow=e.net_cash_flow + amount) if e == episode else e
            for e in episodes
        )
        position = next((p for p in positions if p.episode_id == order.episode_id), None)
        quantity = (position.units if position else 0) + fact.fill_units * (1 if buying else -1)
        check(quantity >= 0)
        positions = tuple(p for p in positions if p.episode_id != order.episode_id)
        if quantity:
            positions = (
                *positions,
                AccountOptionPosition(
                    order.episode_id,
                    leg.contract,
                    quantity,
                    position.liquidation_price if position else None,
                ),
            )
        unsettled = (
            *unsettled,
            AccountSettlement(
                entry.event_id,
                order.episode_id,
                amount,
                entry.available_ns + scenario.settlement_delay_ns,
            ),
        )
    orders = tuple(changed if o == order else o for o in state.orders)
    return replace(
        state,
        cash=cash,
        fees=fees,
        episodes=episodes,
        orders=orders,
        positions=positions,
        unsettled=unsettled,
    )


def _apply(
    state: OptionsAccountPathState, entry: AccountJournalEntry, scenario: StudyScenario
) -> OptionsAccountPathState:
    fact = entry.fact
    if isinstance(fact, JournalIntent):
        return _intent(state, fact, entry.available_ns, scenario)
    if isinstance(fact, JournalOrderUpdate):
        return _order_update(state, entry, fact, scenario)
    if isinstance(fact, JournalSettlement):
        obligation = next((s for s in state.unsettled if s.event_id == fact.event_id), None)
        check(obligation is not None and entry.available_ns >= obligation.due_ns)
        return replace(state, unsettled=tuple(s for s in state.unsettled if s != obligation))
    if isinstance(fact, JournalComplete):
        episode = next((e for e in state.episodes if e.episode_id == fact.episode_id), None)
        check(episode is not None and not episode.finalized and not state.incidents)
        check(not any(p.episode_id == fact.episode_id for p in state.positions))
        check(not any(s.episode_id == fact.episode_id for s in state.unsettled))
        check(all(o.state in TERMINAL for o in state.orders if o.episode_id == fact.episode_id))
        return replace(
            state,
            episodes=tuple(
                replace(e, finalized=True) if e == episode else e for e in state.episodes
            ),
        )
    if isinstance(fact, JournalExternalFlow):
        return replace(
            state,
            cash=state.cash + fact.amount,
            cumulative_external_flows=state.cumulative_external_flows + fact.amount,
        )
    if isinstance(fact, JournalIncident):
        return replace(
            state,
            incidents=tuple(sorted(set((*state.incidents, fact.reason)))),
            latched_halts=tuple(sorted(set((*state.latched_halts, fact.reason)))),
        )
    check(isinstance(fact, JournalMark))
    mark = cast(JournalMark, fact)
    check(any(p.episode_id == mark.episode_id for p in state.positions))
    return replace(
        state,
        positions=tuple(
            replace(p, liquidation_price=mark.price) if p.episode_id == mark.episode_id else p
            for p in state.positions
        ),
    )


def reconstruct_account_journal(
    initial: OptionsAccountPathState,
    entries: tuple[AccountJournalEntry, ...],
    *,
    loaded: LoadedConfig,
    scenario: StudyScenario,
) -> OptionsAccountPathState:
    check(type(initial) is OptionsAccountPathState)
    check(
        initial
        == initial_account_path(
            study_hash=initial.study_hash,
            capital=initial.authorized_capital,
            start_ns=initial.start_ns,
            loaded=loaded,
            scenario=scenario,
        )
    )
    check(type(entries) is tuple and len(entries) <= loaded.config.options.replay_max_records)
    seen: dict[str, AccountJournalEntry] = {}
    observations: tuple[OptionsLossObservation, ...] = ()
    pending_risk: tuple[int, str, str | None] | None = None
    state = initial
    with localcontext() as context:
        context.prec = 2048
        for entry in entries:
            check(type(entry) is AccountJournalEntry)
            previous = seen.get(entry.event_id)
            if previous is not None:
                check(previous == entry)
                continue
            check(
                entry.previous_hash == state.journal_hash
                and entry.available_ns >= state.last_event_ns
            )
            if type(entry.fact) is JournalRiskObservation:
                observation = entry.fact.observation
                point = observation.point
                check(bool(observations) or state == initial)
                check(pending_risk is None or pending_risk[0] == entry.available_ns)
                check(
                    observation.available_ns == entry.available_ns
                    and observation.ordinal == len(seen)
                    and point.account_id == state.path_id
                    and point.config_hash == state.config_hash
                    and point.source_hash == state.journal_hash
                    and point.liquidation_equity == state.marked_equity
                    and point.cumulative_external_flows == state.cumulative_external_flows
                )
                check(
                    not point.complete
                    or (
                        all(p.liquidation_price is not None for p in state.positions)
                        and not state.incidents
                        and all(
                            o.state is not OrderState.UNKNOWN_REQUIRES_RECONCILIATION
                            for o in state.orders
                        )
                    )
                )
                observations = (*observations, observation)
                loss = evaluate_options_loss_observations(
                    loaded, observations, as_of_ns=entry.available_ns
                )
                hard_halts = set(loss.entry_reasons) & {
                    "weekly_loss_latched",
                    "drawdown_latched",
                    "risk_history_incomplete",
                }
                # Entry halts are not ownership/settlement incidents. They must
                # not prevent an independently admitted protective close completing.
                state = replace(
                    state, latched_halts=tuple(sorted(set(state.latched_halts) | hard_halts))
                )
                pending_risk = None
            else:
                filling = type(entry.fact) is JournalOrderUpdate and bool(entry.fact.fill_units)
                monetary = type(entry.fact) in (JournalMark, JournalExternalFlow) or filling
                if observations and monetary:
                    # A same-event fill may receive its first liquidation mark
                    # before observation. No second mark, flow or fill can erase
                    # that intermediate valuation. A later timestamp cannot repair
                    # a skipped observation by backdating its risk history.
                    check(
                        pending_risk is None
                        or (
                            pending_risk[:2] == (entry.available_ns, "fill")
                            and type(entry.fact) is JournalMark
                            and entry.fact.episode_id == pending_risk[2]
                            and any(
                                p.episode_id == entry.fact.episode_id
                                and p.liquidation_price is None
                                for p in state.positions
                            )
                        )
                    )
                    filled_order = (
                        next(o for o in state.orders if o.intent.intent_id == entry.fact.order_id)
                        if type(entry.fact) is JournalOrderUpdate and filling
                        else None
                    )
                    pending_risk = (
                        entry.available_ns,
                        "fill" if filling else "valuation",
                        filled_order.episode_id if filled_order else None,
                    )
                state = _apply(state, entry, scenario)
            if state.cash < 0:
                state = replace(
                    state,
                    incidents=tuple(sorted(set((*state.incidents, "negative_cash")))),
                    latched_halts=tuple(sorted(set((*state.latched_halts, "negative_cash")))),
                )
            state = replace(
                state,
                last_event_ns=entry.available_ns,
                last_event_id=entry.event_id,
                journal_hash=entry.entry_hash,
            )
            seen[entry.event_id] = entry
    return state


def reconcile_account_journal(
    initial: OptionsAccountPathState,
    entries: tuple[AccountJournalEntry, ...],
    observed: OptionsAccountPathState,
    *,
    loaded: LoadedConfig,
    scenario: StudyScenario,
) -> tuple[str, ...]:
    expected = reconstruct_account_journal(initial, entries, loaded=loaded, scenario=scenario)
    return () if observed == expected else ("account_state_mismatch",)
