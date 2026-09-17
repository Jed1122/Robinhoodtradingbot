"""Typed replay identities; receipt multiplicity never changes economic input identity."""

from dataclasses import dataclass, replace

from trading_bot.domain import DataHash
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation.equity_replay_models import (
    SOURCE_KIND,
    EquityStrategyReplayRequest,
    ReplayOrderOutcome,
    checked,
    deny,
)


@dataclass(frozen=True, slots=True)
class ReplayIdentity:
    run_key: DataHash
    input_hash: DataHash
    delivery_hash: DataHash


def encode_order_outcome(value: object) -> dict[str, object]:
    """The cycle encoder accepts only the exact fixture outcome contract."""
    with checked():
        if type(value) is not ReplayOrderOutcome:
            deny("replay_outcome_invalid")
        value.__post_init__()
        return {
            "source_kind": SOURCE_KIND,
            "intent_id": value.intent_id,
            "accepted": value.accepted,
            "reasons": value.reasons,
            "order_id": value.order_id,
        }


def replay_identity(request: EquityStrategyReplayRequest) -> ReplayIdentity:
    """Audit hashes are not RNG seeds. Cycles must also bind their visible as-of inputs."""
    with checked():
        if type(request) is not EquityStrategyReplayRequest:
            deny()
        # Reconstruct before serialization so unknown objects never reach canonical_json.
        validated = replace(request)
        run_key = content_hash(
            {
                "source_kind": SOURCE_KIND,
                "kind": "run_key",
                "namespace": validated.namespace,
                "config_hash": validated.loaded.config_hash,
                "seed": validated.seed,
                "candidate": validated.candidate,
                "starts_at": validated.starts_at,
                "initial_cash": validated.initial_cash,
                "instruments": validated.instruments,
                "snapshot_settings": validated.snapshot_settings,
            }
        )
        unique = {event.event_id: event for event in validated.markets}
        input_hash = content_hash(
            {
                "source_kind": SOURCE_KIND,
                "kind": "economic_inputs",
                "run_key": run_key,
                "bundle_hash": validated.bundle.envelope.bundle_hash,
                "sessions": validated.sessions,
                "decisions": validated.decisions,
                "markets": tuple(unique.values()),
                "end_at": validated.end_at,
            }
        )
        delivery_hash = content_hash(
            {
                "source_kind": SOURCE_KIND,
                "kind": "delivery_receipts",
                "input_hash": input_hash,
                "deliveries": tuple(event.event_id for event in validated.markets),
            }
        )
        return ReplayIdentity(run_key, input_hash, delivery_hash)
