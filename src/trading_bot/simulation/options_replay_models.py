"""Strict in-memory contracts for a credential-free single-unit engineering replay."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.config import LoadedConfig
from trading_bot.domain.decimal_utils import (
    DomainValidationError,
    _require_nonempty,
    _require_tuple,
    require_bounded_decimal,
)
from trading_bot.domain.enums import OrderEvent, OrderState
from trading_bot.domain.options import OptionContract, OptionQuote
from trading_bot.risk.options_economics import TrialLossState
from trading_bot.strategies.protocol import HistoricalSlice

SOURCE: Literal["synthetic-options-v1"] = "synthetic-options-v1"
ACTIONS = frozenset(
    {
        "market",
        "accept_entry",
        "reject_entry",
        "unknown_entry",
        "cancel_entry",
        "confirm_cancel",
        "request_close",
        "settle",
    }
)


@dataclass(frozen=True, slots=True)
class OptionsReplayEvent:
    event_id: str
    at: datetime
    action: str
    quote: OptionQuote | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.event_id, "event_id")
        require_utc(self.at)
        if type(self.action) is not str or self.action not in ACTIONS:
            raise DomainValidationError("unsupported replay action")
        if self.action == "market":
            if type(self.quote) is not OptionQuote or self.quote.source != SOURCE:
                raise DomainValidationError("synthetic market event requires synthetic quote")
            if self.quote.received_at > self.at:
                raise DomainValidationError("market event cannot observe a future quote")
        elif self.quote is not None:
            raise DomainValidationError("only market events carry quotes")


@dataclass(frozen=True, slots=True)
class OptionsReplayRequest:
    loaded: LoadedConfig
    research_capital: Decimal
    as_of: datetime
    history: HistoricalSlice
    contract: OptionContract
    initial_quote: OptionQuote
    entry_fee: Decimal
    exit_fee: Decimal
    close_limit: Decimal
    events: tuple[OptionsReplayEvent, ...]
    trial: TrialLossState
    source_kind: Literal["synthetic-options-v1"] = SOURCE

    def __post_init__(self) -> None:
        if self.source_kind != SOURCE:
            raise DomainValidationError("only synthetic options engineering replay is supported")
        require_utc(self.as_of)
        require_bounded_decimal(self.research_capital, "research_capital", positive=True)
        require_bounded_decimal(self.close_limit, "close_limit", positive=True)
        for name in ("entry_fee", "exit_fee"):
            require_bounded_decimal(getattr(self, name), name, nonnegative=True)
        if type(self.loaded) is not LoadedConfig or type(self.history) is not HistoricalSlice:
            raise DomainValidationError("exact loaded config and history required")
        if type(self.contract) is not OptionContract or type(self.initial_quote) is not OptionQuote:
            raise DomainValidationError("exact options records required")
        if type(self.trial) is not TrialLossState:
            raise DomainValidationError("exact trial history required")
        if (
            not self.contract.contract_id.startswith("synthetic-")
            or self.initial_quote.source != SOURCE
            or any(bar.source != SOURCE for bar in self.history.bars)
            or self.history.instrument_id != self.contract.underlying
        ):
            raise DomainValidationError("synthetic provenance and underlying identity required")
        _require_tuple(self.events, "events")
        previous = self.as_of
        identities: set[str] = set()
        for event in self.events:
            if type(event) is not OptionsReplayEvent or event.at <= previous:
                raise DomainValidationError("replay events must follow decision time strictly")
            if event.event_id in identities:
                raise DomainValidationError("duplicate event identity")
            identities.add(event.event_id)
            previous = event.at


@dataclass(frozen=True, slots=True)
class OptionsReplayTransition:
    at: datetime
    order: str
    event: OrderEvent
    before: OrderState
    after: OrderState


@dataclass(frozen=True, slots=True)
class OptionsReplayCashFlow:
    event_id: str
    at: datetime
    purpose: str
    amount: Decimal
    fee: Decimal


@dataclass(frozen=True, slots=True)
class OptionsReplayResult:
    status: str
    config_hash: str
    input_hash: str
    entry_intent_hash: str | None
    cash: Decimal
    unsettled_receivable: Decimal
    net_cash_flow: Decimal
    fees: Decimal
    position_units: int
    entry_state: OrderState
    close_state: OrderState | None
    trial: TrialLossState
    cash_flows: tuple[OptionsReplayCashFlow, ...]
    transitions: tuple[OptionsReplayTransition, ...]
    reason_codes: tuple[str, ...]
    source_kind: Literal["synthetic-options-v1"] = field(default=SOURCE, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    production_eligible: Literal[False] = field(default=False, init=False)
    economic_verdict: Literal["ECONOMIC_NO_GO"] = field(default="ECONOMIC_NO_GO", init=False)
