"""Broker-neutral strategy and feature contracts."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from trading_bot.domain import Bar, ConfigHash, DataHash, InstrumentId

FeatureValue = Decimal | int | bool | str | None


@dataclass(frozen=True, slots=True)
class HistoricalSlice:
    instrument_id: InstrumentId
    bars: tuple[Bar, ...]
    spread_percentage: Decimal | None
    data_hash: DataHash


@dataclass(frozen=True, slots=True)
class FeatureVector:
    instrument_id: InstrumentId
    observed_at: datetime
    values: tuple[tuple[str, FeatureValue], ...]
    data_hash: DataHash


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    observed_at: datetime
    vectors: tuple[FeatureVector, ...]
    data_hash: DataHash


class FeatureComputer(Protocol):
    def compute(self, history: HistoricalSlice, *, as_of: datetime) -> FeatureVector: ...


class StrategyAction(StrEnum):
    ENTER_LONG = "enter_long"
    EXIT_LONG = "exit_long"
    HOLD = "hold"


@dataclass(frozen=True, slots=True)
class StrategyDescriptor:
    strategy_id: str
    family: str
    version: str
    rationale: str
    research_only: bool
    parameter_hash: str


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    instrument_id: InstrumentId
    decided_at: datetime
    action: StrategyAction
    score: Decimal
    reason_codes: tuple[str, ...]
    strategy_version: str
    config_hash: ConfigHash
    data_hash: DataHash


@dataclass(frozen=True, slots=True)
class StrategyContext:
    as_of: datetime
    features: FeatureSnapshot
    config_hash: ConfigHash
    eligible_instruments: tuple[InstrumentId, ...]


class Strategy(Protocol):
    @property
    def descriptor(self) -> StrategyDescriptor: ...
    def decide(self, context: StrategyContext) -> tuple[StrategyDecision, ...]: ...


__all__ = [
    "FeatureComputer",
    "FeatureSnapshot",
    "FeatureValue",
    "FeatureVector",
    "HistoricalSlice",
    "Strategy",
    "StrategyAction",
    "StrategyContext",
    "StrategyDecision",
    "StrategyDescriptor",
]
