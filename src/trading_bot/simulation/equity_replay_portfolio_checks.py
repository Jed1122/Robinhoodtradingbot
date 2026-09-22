"""Synthetic portfolio boundary checks; not economic or production pretrade approval."""

from dataclasses import replace
from datetime import datetime

from trading_bot.domain import AssetClass, Instrument, OrderIntent, OrderType, TimeInForce
from trading_bot.domain.decimal_utils import quantize_down, require_bounded_decimal
from trading_bot.simulation.configured_codec import configured_hash
from trading_bot.simulation.configured_fills import costs_for
from trading_bot.simulation.configured_results import ConfiguredOrderResult
from trading_bot.simulation.costs import execution_fee
from trading_bot.simulation.equity_replay_models import (
    EquityStrategyReplayRequest,
    deny,
    label,
    utc,
)
from trading_bot.simulation.lifecycle import replay_order_lifecycle
from trading_bot.simulation.lifecycle_models import LifecycleFillEvent, LifecycleRequest


def intent_slots(
    request: EquityStrategyReplayRequest,
    intent: OrderIntent,
    fee_opportunities: int,
) -> tuple[Instrument, tuple[datetime, ...]]:
    if type(intent) is not OrderIntent:
        deny()
    intent.__post_init__()
    for value in (intent.id, intent.instrument_id, intent.strategy_version):
        label(value)
    if intent.exit_policy_version is not None:
        label(intent.exit_policy_version)
    utc(intent.created_at)
    utc(intent.expires_at)
    if (
        intent.account_id != request.account_id
        or intent.config_hash != request.loaded.config_hash
        or intent.asset_class is not AssetClass.EQUITY
        or intent.order_type is not OrderType.LIMIT
        or intent.time_in_force is not TimeInForce.GOOD_FOR_DAY
        or not request.starts_at <= intent.created_at <= request.end_at
    ):
        deny("replay_intent_identity_invalid")
    instruments = tuple(i for i in request.instruments if i.id == intent.instrument_id)
    sessions = tuple(
        s
        for s in request.sessions
        if s.instrument_id == intent.instrument_id
        and s.window.starts_at <= intent.created_at < s.window.ends_at
        and s.window.ends_at == intent.expires_at
    )
    if len(instruments) != 1 or len(sessions) != 1:
        deny("replay_intent_session_invalid")
    instrument = instruments[0]
    require_bounded_decimal(intent.quantity, "quantity", positive=True)
    if intent.limit_price is None:
        deny()
    require_bounded_decimal(intent.limit_price, "price", positive=True)
    if (
        quantize_down(intent.quantity, instrument.quantity_increment) != intent.quantity
        or quantize_down(intent.limit_price, instrument.price_increment) != intent.limit_price
        or intent.quantity < instrument.minimum_quantity
        or intent.quantity * intent.limit_price < instrument.minimum_notional
        or (
            instrument.maximum_quantity is not None
            and intent.quantity > instrument.maximum_quantity
        )
    ):
        deny("replay_intent_increments_invalid")
    slots = tuple(
        t for t in sessions[0].opportunity_times if intent.created_at < t < intent.expires_at
    )
    if type(fee_opportunities) is not int or fee_opportunities != len(slots):
        deny("replay_fee_capacity_invalid")
    return instrument, slots


def validate_result(
    request: EquityStrategyReplayRequest,
    initial: LifecycleRequest,
    instrument: Instrument,
    slots: tuple[datetime, ...],
    result: ConfiguredOrderResult,
    previous: ConfiguredOrderResult | None,
    through: datetime,
) -> None:
    """Recompute lifecycle accounting; hashes alone are not a balance authority.

    Configured sampling provenance still belongs to the session/coordinator. This boundary
    checks identity, accounting, fees, declared fill capacity, increments and immutable prefixes.
    """
    if type(result) is not ConfiguredOrderResult:
        deny()
    result.__post_init__()
    settings = configured_hash(
        "settings",
        {
            "simulation": request.loaded.config.simulation.model_dump(),
            "costs": request.loaded.config.costs.model_dump(),
            "execution": {"version": "synthetic-equity-increments-v1", "instrument": instrument},
        },
    )
    if (
        result.settings_hash != settings
        or result.assumptions_validated is not False
        or result.evidence_promotable is not False
        or result.source_kind != "synthetic-configured-order-v1"
        or result.lifecycle != replay_order_lifecycle(replace(initial, events=result.events))
        or result.result_hash
        != configured_hash(
            "result",
            {
                "input": result.input_hash,
                "settings": result.settings_hash,
                "events": result.events,
                "decisions": result.decisions,
                "lifecycle": result.lifecycle,
            },
        )
    ):
        deny("replay_result_identity_invalid")
    prior_events = () if previous is None else previous.events
    prior_decisions = () if previous is None else previous.decisions
    if (
        result.events[: len(prior_events)] != prior_events
        or result.decisions[: len(prior_decisions)] != prior_decisions
    ):
        deny("replay_result_prefix_invalid")
    new_times = tuple(e.cursor.occurred_at for e in result.events[len(prior_events) :]) + tuple(
        d.occurred_at for d in result.decisions[len(prior_decisions) :]
    )
    if any(t < through or t > request.end_at for t in new_times):
        deny("replay_ordering_invalid")
    costs = costs_for(AssetClass.EQUITY, request.loaded.config.costs)
    used: set[datetime] = set()
    for event in result.events:
        if type(event) is not LifecycleFillEvent:
            continue
        fill = event.fill
        if (
            fill.occurred_at not in slots
            or fill.occurred_at in used
            or quantize_down(fill.quantity, instrument.quantity_increment) != fill.quantity
            or quantize_down(fill.price, instrument.price_increment) != fill.price
            or fill.fee != execution_fee(fill.quantity, fill.price, costs)
        ):
            deny("replay_fill_contract_invalid")
        used.add(fill.occurred_at)
    _decision_prefixes(initial, result)


def _decision_prefixes(initial: LifecycleRequest, result: ConfiguredOrderResult) -> None:
    """Do not allow an audit record to omit or backdate its generated state change."""
    offset = 0
    at = initial.submitted.occurred_at
    for decision in result.decisions:
        count = len(decision.generated_event_ids)
        generated = result.events[offset : offset + count]
        if (
            decision.occurred_at < at
            or tuple(e.event_id for e in generated) != decision.generated_event_ids
            or any(e.cursor.occurred_at != decision.occurred_at for e in generated)
        ):
            deny("replay_result_identity_invalid")
        offset += count
        prefix = replay_order_lifecycle(replace(initial, events=result.events[:offset]))
        if decision.snapshot_hash != prefix.snapshot.snapshot_hash:
            deny("replay_result_identity_invalid")
        at = decision.occurred_at
    if offset != len(result.events):
        deny("replay_result_identity_invalid")
