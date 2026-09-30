"""Immutable offline historical execution state; no provider-write capability."""

from dataclasses import dataclass, field
from decimal import Decimal, localcontext
from typing import Literal

from trading_bot.domain import DataHash
from trading_bot.domain.decimal_utils import require_bounded_decimal
from trading_bot.domain.enums import OrderEvent, OrderState
from trading_bot.domain.options import OptionContract, OptionsOrderIntent, StructureKind
from trading_bot.market_data.options_source_models import check, hashes, identity, instant
from trading_bot.market_data.options_source_verify import ceil_available_at
from trading_bot.risk.options_economics import TrialEpisode, TrialLossState

HISTORICAL_TERMINAL = frozenset(
    (
        OrderState.FILLED,
        OrderState.CANCELED,
        OrderState.REJECTED,
        OrderState.EXPIRED,
        OrderState.RISK_REJECTED,
    )
)


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
        # Datetime carries microseconds; only its exact upward ns projection is valid.
        check(self.intent.created_at == ceil_available_at(self.decision_ns))
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


@dataclass(frozen=True, slots=True)
class AccountEpisodeBalance:
    episode_id: str
    session_id: str
    reserved_risk: Decimal
    net_cash_flow: Decimal = Decimal(0)
    finalized: bool = False

    def __post_init__(self) -> None:
        identity(self.episode_id)
        identity(self.session_id)
        require_bounded_decimal(self.reserved_risk, "reservation", nonnegative=True)
        require_bounded_decimal(self.net_cash_flow, "cash flow")
        check(type(self.finalized) is bool)


@dataclass(frozen=True, slots=True)
class AccountOrderBalance:
    episode_id: str
    intent: OptionsOrderIntent
    state: OrderState
    decision_ns: int
    filled_units: int = 0
    accepted_ns: int | None = None

    def __post_init__(self) -> None:
        identity(self.episode_id)
        check(type(self.intent) is OptionsOrderIntent and type(self.state) is OrderState)
        check(type(self.filled_units) is int and 0 <= self.filled_units <= self.intent.quantity)
        instant(self.decision_ns)
        check(self.intent.created_at == ceil_available_at(self.decision_ns))
        if self.accepted_ns is not None:
            instant(self.accepted_ns)
            check(self.accepted_ns > self.decision_ns)


@dataclass(frozen=True, slots=True)
class AccountOptionPosition:
    episode_id: str
    contract: OptionContract
    units: int
    liquidation_price: Decimal | None = None

    def __post_init__(self) -> None:
        identity(self.episode_id)
        check(type(self.contract) is OptionContract and type(self.units) is int and self.units > 0)
        if self.liquidation_price is not None:
            require_bounded_decimal(self.liquidation_price, "mark", nonnegative=True)


@dataclass(frozen=True, slots=True)
class AccountSettlement:
    event_id: str
    episode_id: str
    amount: Decimal
    due_ns: int

    def __post_init__(self) -> None:
        identity(self.event_id)
        identity(self.episode_id)
        require_bounded_decimal(self.amount, "settlement")
        instant(self.due_ns)


@dataclass(frozen=True, slots=True)
class OptionsAccountPathState:
    """Diagnostic projection; only full journal reconstruction establishes continuity.

    Cash is book cash including unsettled flows. Positive unsettled proceeds are
    excluded from available_cash. This record cannot certify risk admission.
    """

    path_id: str
    study_hash: DataHash
    config_hash: str
    scenario_hash: DataHash
    authorized_capital: Decimal
    start_ns: int
    cash: Decimal
    fees: Decimal
    cumulative_external_flows: Decimal
    episodes: tuple[AccountEpisodeBalance, ...]
    orders: tuple[AccountOrderBalance, ...]
    positions: tuple[AccountOptionPosition, ...]
    unsettled: tuple[AccountSettlement, ...]
    session_entry_counts: tuple[tuple[str, int], ...]
    latched_halts: tuple[str, ...]
    incidents: tuple[str, ...]
    last_event_ns: int
    last_event_id: str | None
    journal_hash: DataHash
    production_eligible: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        identity(self.path_id)
        for value in (self.study_hash, self.config_hash, self.scenario_hash, self.journal_hash):
            hashes((DataHash(value),))
        require_bounded_decimal(self.authorized_capital, "capital", positive=True)
        require_bounded_decimal(self.cash, "cash")
        require_bounded_decimal(self.fees, "fees", nonnegative=True)
        require_bounded_decimal(self.cumulative_external_flows, "flows")
        instant(self.start_ns)
        instant(self.last_event_ns)
        check(self.last_event_ns >= self.start_ns)
        if self.last_event_id is not None:
            identity(self.last_event_id)
        for records, cls in (
            (self.episodes, AccountEpisodeBalance),
            (self.orders, AccountOrderBalance),
            (self.positions, AccountOptionPosition),
            (self.unsettled, AccountSettlement),
        ):
            check(type(records) is tuple and all(type(r) is cls for r in records))
        for values in (self.latched_halts, self.incidents):
            check(type(values) is tuple and values == tuple(sorted(set(values))))
            for value in values:
                identity(value)
        check(type(self.session_entry_counts) is tuple)
        for session, count in self.session_entry_counts:
            identity(session)
            check(type(count) is int and count > 0)
        check(len(set(s for s, _ in self.session_entry_counts)) == len(self.session_entry_counts))
        check(len(set(e.episode_id for e in self.episodes)) == len(self.episodes))
        check(len(set(o.intent.intent_id for o in self.orders)) == len(self.orders))
        check(len(set(p.episode_id for p in self.positions)) == len(self.positions))
        check(len(set(s.event_id for s in self.unsettled)) == len(self.unsettled))

    @property
    def trial(self) -> TrialLossState:
        return TrialLossState(
            tuple(
                TrialEpisode(
                    e.episode_id,
                    e.reserved_risk,
                    e.net_cash_flow,
                    not any(p.episode_id == e.episode_id for p in self.positions),
                    all(
                        o.state in HISTORICAL_TERMINAL
                        for o in self.orders
                        if o.episode_id == e.episode_id
                    ),
                    e.finalized,
                )
                for e in self.episodes
            )
        )

    @property
    def available_cash(self) -> Decimal:
        with localcontext() as context:
            context.prec = 2048
            return self.cash - sum((max(Decimal(0), s.amount) for s in self.unsettled), Decimal(0))

    @property
    def marked_equity(self) -> Decimal:
        with localcontext() as context:
            context.prec = 2048
            return self.cash + sum(
                (
                    (p.liquidation_price or Decimal(0)) * p.contract.premium_multiplier * p.units
                    for p in self.positions
                ),
                Decimal(0),
            )

    @property
    def risk_capital(self) -> Decimal:
        with localcontext() as context:
            context.prec = 2048
            return max(
                Decimal(0),
                min(
                    self.authorized_capital,
                    self.marked_equity,
                    self.marked_equity - self.cumulative_external_flows,
                ),
            )
