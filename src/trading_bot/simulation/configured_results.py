"""Immutable synthetic simulation decisions and explicitly non-promotable results."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from trading_bot.domain import DataHash
from trading_bot.domain.decimal_utils import (
    _require_nonempty,
    _require_sha256_hex,
    _require_tuple,
    require_bounded_decimal,
)
from trading_bot.simulation.configured_fills import SimulatedOutcome
from trading_bot.simulation.configured_models import SOURCE_KIND, checked, deny, utc
from trading_bot.simulation.lifecycle_models import (
    LifecycleControlEvent,
    LifecycleEvent,
    LifecycleFillEvent,
    LifecycleResult,
)


class DecisionReason(StrEnum):
    ACCEPTED = "submission_accepted"
    REJECTED = "submission_rejected"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELED = "cancel_confirmed"
    EXPIRED = "expired"
    ALREADY_TERMINAL = "already_terminal"
    PENDING = "submission_pending"
    TERMINAL = "order_terminal"
    SAME_BAR = "same_bar_forbidden"
    UNVERIFIED = "quote_unverified"
    CLOSED = "market_closed"
    HALTED = "market_halted"
    DISABLED = "trading_disabled"
    CANCEL_ONLY = "cancel_only"
    RACE_SUPPRESSED = "cancel_race_suppressed"
    NO_LIQUIDITY = "no_liquidity"
    LIMIT = "limit_price_not_executable"
    NO_FILL = "no_fill"
    FULL = "full_fill"
    PARTIAL = "partial_fill"
    DUPLICATE = "duplicate_event"


@dataclass(frozen=True, slots=True)
class ConfiguredDecision:
    event_id: str
    event_digest: DataHash
    occurred_at: datetime
    reason: DecisionReason
    selected_outcome: SimulatedOutcome | None
    realized_outcome: SimulatedOutcome | None
    partial_percentage: Decimal | None
    generated_event_ids: tuple[str, ...]
    snapshot_hash: DataHash
    delivery_index: int | None
    original_event_id: str | None = None

    def __post_init__(self) -> None:
        with checked():
            _require_nonempty(self.event_id, "event_id")
            _require_sha256_hex(self.event_digest, "event_digest")
            _require_sha256_hex(self.snapshot_hash, "snapshot_hash")
            utc(self.occurred_at)
            if type(self.reason) is not DecisionReason:
                deny()
            for outcome in (self.selected_outcome, self.realized_outcome):
                if outcome is not None and type(outcome) is not SimulatedOutcome:
                    deny()
            if self.partial_percentage is not None:
                require_bounded_decimal(self.partial_percentage, "percentage", positive=True)
                if self.partial_percentage > 100:
                    deny()
            _require_tuple(self.generated_event_ids, "generated_event_ids")
            for identifier in self.generated_event_ids:
                _require_nonempty(identifier, "generated_event_id")
            if self.delivery_index is not None and (
                type(self.delivery_index) is not int or self.delivery_index < 0
            ):
                deny()
            if self.reason is DecisionReason.DUPLICATE:
                if self.original_event_id != self.event_id or self.generated_event_ids:
                    deny()
            elif self.original_event_id is not None:
                deny()


@dataclass(frozen=True, slots=True)
class ConfiguredOrderResult:
    lifecycle: LifecycleResult
    events: tuple[LifecycleEvent, ...]
    decisions: tuple[ConfiguredDecision, ...]
    settings_hash: DataHash
    input_hash: DataHash
    result_hash: DataHash
    source_kind: Literal["synthetic-configured-order-v1"] = field(default=SOURCE_KIND, init=False)
    assumptions_validated: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        with checked():
            if type(self.lifecycle) is not LifecycleResult:
                deny()
            self.lifecycle.__post_init__()
            _require_tuple(self.events, "events")
            _require_tuple(self.decisions, "decisions")
            for event in self.events:
                if type(event) not in (LifecycleControlEvent, LifecycleFillEvent):
                    deny()
                event.__post_init__()
            for decision in self.decisions:
                if type(decision) is not ConfiguredDecision:
                    deny()
                decision.__post_init__()
            for digest in (self.settings_hash, self.input_hash, self.result_hash):
                _require_sha256_hex(digest, "digest")
