"""Source-neutral, bounded inputs and outputs for offline ETF execution.

Market provenance and simulated account facts are separate. These records cannot
qualify a provider or confer a paper/live capability. The legacy fixture hash
domains and validators are deliberately unchanged.
"""

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Literal

from trading_bot.domain import AssetClass, Bar, BarInterval, Instrument, MarketClock
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.etf_source import _ceil_time, _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_costs import EtfCostEvidence
from trading_bot.research.etf_study import EtfStudy
from trading_bot.simulation.etf_account import EtfAccountEvent, EtfAccountResult
from trading_bot.simulation.etf_history import _policy, _session_date
from trading_bot.simulation.etf_strategy import EtfEntryPolicy, EtfStrategyDecision

SCENARIOS = ("conservative", "base", "optimistic")


def check(condition: bool) -> None:
    if not condition:
        raise ValueError("etf_native_history_invalid")


@dataclass(frozen=True, slots=True)
class EtfReplayEvent:
    ordinal: int
    event_at_ns: int
    available_at_ns: int
    source_hash: str
    kind: Literal["bar", "quote", "session", "control", "dividend_ex", "dividend_pay", "split"]
    bar: Bar | None = None
    clock: MarketClock | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None
    action_id: str | None = None
    cash_per_share: Decimal | None = None
    execution_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value in (self.ordinal, self.event_at_ns, self.available_at_ns):
            check(type(value) is int and 0 <= value < 2**63)
        check(0 < self.event_at_ns <= self.available_at_ns)
        _require_sha256_hex(self.source_hash, "source")
        check(
            self.kind
            in ("bar", "quote", "session", "control", "dividend_ex", "dividend_pay", "split")
        )
        active = {
            name
            for name in (
                "bar",
                "clock",
                "bid",
                "ask",
                "bid_size",
                "ask_size",
                "action_id",
                "cash_per_share",
            )
            if getattr(self, name) is not None
        }
        expected = {
            "bar": {"bar"},
            "session": {"clock"},
            "control": {"clock"},
            "dividend_ex": {"action_id", "cash_per_share"},
            "dividend_pay": {"action_id"},
            "split": {"action_id"},
        }
        if self.kind == "quote":
            check({"bid", "ask"} <= active <= {"bid", "ask", "bid_size", "ask_size"})
        else:
            check(active == expected[self.kind])
        if self.bar is not None:
            check(type(self.bar) is Bar)
            replace(self.bar)
            check(self.bar.instrument_id == "SPY" and _ns(self.bar.ends_at) == self.event_at_ns)
            check(self.bar.interval is BarInterval.ONE_DAY and self.bar.interpolated is False)
        if self.clock is not None:
            check(type(self.clock) is MarketClock)
            replace(self.clock)
            check(self.clock.venue == "XNYS")
            check(
                self.clock.asset_class is AssetClass.EQUITY
                and self.clock.observed_at == _ceil_time(self.event_at_ns)
            )
        for amount in (self.bid, self.ask, self.bid_size, self.ask_size, self.cash_per_share):
            if amount is not None:
                require_bounded_decimal(amount, "market value", nonnegative=True)
        if self.action_id is not None:
            _require_sha256_hex(self.action_id, "action")
        check(type(self.execution_reasons) is tuple and len(self.execution_reasons) <= 32)
        check(
            all(type(reason) is str and 0 < len(reason) <= 128 for reason in self.execution_reasons)
        )


@dataclass(frozen=True, slots=True)
class EtfReplayDataset:
    events: tuple[EtfReplayEvent, ...]
    provenance_hash: str
    source_kind: Literal["synthetic", "native-latest-vintage"]
    limitations: tuple[str, ...]
    source_qualified: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_sha256_hex(self.provenance_hash, "provenance")
        check(self.source_kind in ("synthetic", "native-latest-vintage"))
        check(type(self.events) is tuple and 0 < len(self.events) <= 150000)
        previous: EtfReplayEvent | None = None
        sessions: set[date] = set()
        for event in self.events:
            check(type(event) is EtfReplayEvent)
            replace(event)
            if previous is not None:
                check(
                    previous.ordinal < event.ordinal
                    and previous.available_at_ns <= event.available_at_ns
                )
            previous = event
            if event.kind == "session":
                session_date = _session_date(event.event_at_ns)
                check(session_date not in sessions)
                sessions.add(session_date)
        check(
            type(self.limitations) is tuple
            and all(type(x) is str and 0 < len(x) <= 128 for x in self.limitations)
        )
        check(self.source_qualified is False)

    @property
    def dataset_hash(self) -> str:
        return content_hash(("etf-replay-dataset-v1", self))


@dataclass(frozen=True, slots=True)
class EtfSimulationSchedule:
    """Explicit research assumptions, never inferred broker observations."""

    acknowledgement_delay_ns: int = 1000000
    cancellation_delay_ns: int = 1000000
    acknowledgement: Literal["accept", "reject", "unknown"] = "accept"
    cancellation: Literal["confirm", "unknown"] = "confirm"
    settlement_sessions: int = 1
    allow_inflight_cancel_fill: bool = False
    episode_fee_bound: Decimal = Decimal("0.10")

    def __post_init__(self) -> None:
        for value in (self.acknowledgement_delay_ns, self.cancellation_delay_ns):
            check(type(value) is int and 0 < value <= 86400000000000)
        check(self.acknowledgement in ("accept", "reject", "unknown"))
        check(self.cancellation in ("confirm", "unknown"))
        check(type(self.settlement_sessions) is int and 1 <= self.settlement_sessions <= 10)
        check(type(self.allow_inflight_cancel_fill) is bool)
        require_bounded_decimal(self.episode_fee_bound, "fee reserve", nonnegative=True)


@dataclass(frozen=True, slots=True)
class EtfHistoryRequest:
    study: EtfStudy
    dataset: EtfReplayDataset
    costs: EtfCostEvidence
    initial_cash: Decimal
    fill_scenario: str
    instrument: Instrument
    schedule: EtfSimulationSchedule = field(default_factory=EtfSimulationSchedule)

    def __post_init__(self) -> None:
        _policy(self.study)
        check(type(self.dataset) is EtfReplayDataset and type(self.costs) is EtfCostEvidence)
        self.dataset.__post_init__()
        check(
            self.costs.calibration_status == "unverified"
            and self.costs.execution_enabled is False
            and self.costs.evidence_promotable is False
            and self.costs.spread_in_fill_price is True
        )
        replace(self.dataset)
        replace(self.costs)
        check(type(self.instrument) is Instrument and self.instrument.id == "SPY")
        replace(self.instrument)
        check(type(self.schedule) is EtfSimulationSchedule)
        replace(self.schedule)
        require_bounded_decimal(self.initial_cash, "capital", positive=True)
        check(self.initial_cash in self.study.capital_tiers and self.fill_scenario in SCENARIOS)
        check(
            all(
                _ns(self.study.requested_start)
                <= (_ns(e.bar.starts_at) if e.bar is not None else e.event_at_ns)
                < _ns(self.study.requested_end)
                for e in self.dataset.events
            )
        )

    @property
    def input_hash(self) -> str:
        return content_hash(("etf-native-history-input-v1", self))


@dataclass(frozen=True, slots=True)
class EtfDailyAccount:
    session_date: date
    at_ns: int
    cash: Decimal
    settled_cash: Decimal
    shares: Decimal
    bid: Decimal | None
    nav: Decimal | None
    reserved_cash: Decimal
    fees: Decimal
    dividend_receivable: Decimal
    state_hash: str
    ask: Decimal | None = None
    account_event_count: int = 0


@dataclass(frozen=True, slots=True)
class EtfReplayOutcome:
    account_events: tuple[EtfAccountEvent, ...]
    account: EtfAccountResult
    daily: tuple[EtfDailyAccount, ...]
    policies: tuple[EtfEntryPolicy, ...]
    decisions: tuple[EtfStrategyDecision, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EtfHistoryResult:
    input_hash: str
    study_hash: str
    dataset_hash: str
    cost_hash: str
    protocol_hash: str
    initial_cash: Decimal
    fill_scenario: str
    source_count: int
    source_prefix_hash: str
    candidate: EtfReplayOutcome
    constrained_benchmark: EtfReplayOutcome
    reasons: tuple[str, ...]
    bars: tuple[Bar, ...] = ()
    paused: Literal[True] = field(default=True, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    @property
    def result_hash(self) -> str:
        return content_hash(("etf-native-history-result-v1", self))
