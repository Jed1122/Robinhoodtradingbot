"""Immutable offline historical execution state; no provider-write capability."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from trading_bot.domain import DataHash
from trading_bot.domain.enums import OrderEvent, OrderState
from trading_bot.domain.options import OptionsOrderIntent, StructureKind
from trading_bot.market_data.options_session_inputs import _ns
from trading_bot.market_data.options_source_models import check, hashes, instant


@dataclass(frozen=True, slots=True)
class HistoricalTransition:
    available_ns: int
    event: OrderEvent
    previous: OrderState
    current: OrderState


@dataclass(frozen=True, slots=True)
class HistoricalOrder:
    intent: OptionsOrderIntent
    state: OrderState
    decision_ns: int
    filled_units: int = 0
    accepted_ns: int | None = None
    cancel_requested_ns: int | None = None
    last_event_ns: int | None = None
    last_event_id: str | None = None
    scenario_hash: DataHash | None = None
    execution_seed: int | None = None
    seen_at_last_ns: tuple[DataHash, ...] = ()

    def __post_init__(self) -> None:
        check(type(self.intent) is OptionsOrderIntent and type(self.state) is OrderState)
        check(self.intent.structure.kind in (StructureKind.LONG_CALL, StructureKind.LONG_PUT))
        check(len(self.intent.structure.legs) == 1 and self.intent.structure.legs[0].ratio == 1)
        instant(self.decision_ns)
        check(_ns(self.intent.created_at) >= self.decision_ns)
        check(type(self.filled_units) is int and 0 <= self.filled_units <= self.intent.quantity)
        for value in (self.accepted_ns, self.cancel_requested_ns, self.last_event_ns):
            if value is not None:
                instant(value)
                check(value >= self.decision_ns)
        if self.last_event_id is not None:
            hashes((DataHash(self.last_event_id),))
        if self.scenario_hash is not None:
            hashes((self.scenario_hash,))
        if self.execution_seed is not None:
            check(type(self.execution_seed) is int and 0 <= self.execution_seed < 2**63)
        hashes(self.seen_at_last_ns)
        check(len(self.seen_at_last_ns) <= 25000)


@dataclass(frozen=True, slots=True)
class HistoricalOrderStep:
    order: HistoricalOrder
    transitions: tuple[HistoricalTransition, ...] = ()
    fill_units: int = 0
    price: Decimal | None = None
    cash_flow: Decimal = Decimal(0)
    fee: Decimal = Decimal(0)
    settlement_complete: Literal[False] = field(default=False, init=False)
    production_eligible: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
