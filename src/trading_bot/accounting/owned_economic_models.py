"""Closed local economic facts; hashes never confer authenticated ownership."""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Literal, NoReturn

from trading_bot.clock import require_utc
from trading_bot.domain import (
    AccountId,
    AssetClass,
    BrokerOrder,
    ConfigHash,
    DataHash,
    InstrumentId,
    OrderId,
    OrderIntent,
    OrderState,
    OrderType,
    Position,
)
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.domain.owned_order_lifecycle import OwnedOrderEvent
from trading_bot.risk.options_economics import TrialLossState

VERSION = "owned-equity-economics-v1"
MAX_EVENTS = 10_000
MAX_BYTES = 16_384


class EconomicError(ValueError):
    def __init__(self) -> None:
        super().__init__("owned_economics_invalid")


def deny() -> NoReturn:
    raise EconomicError() from None


def identity(value: str) -> None:
    if type(value) is not str or not value.strip() or len(value) > 255:
        deny()


@dataclass(frozen=True, slots=True)
class Opening:
    instrument_id: InstrumentId
    cash: Decimal


@dataclass(frozen=True, slots=True)
class Reserve:
    intent: OrderIntent
    episode_id: str
    fee_bound: Decimal
    reserved_risk: Decimal


@dataclass(frozen=True, slots=True)
class Bind:
    order: BrokerOrder


@dataclass(frozen=True, slots=True)
class Execution:
    event: OwnedOrderEvent


@dataclass(frozen=True, slots=True)
class FinalFees:
    order_id: OrderId
    total: Decimal


@dataclass(frozen=True, slots=True)
class Settlement:
    obligation_id: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class Release:
    order_id: OrderId


@dataclass(frozen=True, slots=True)
class Complete:
    episode_id: str


@dataclass(frozen=True, slots=True)
class Funding:
    amount: Decimal


type Payload = (
    Opening | Reserve | Bind | Execution | FinalFees | Settlement | Release | Complete | Funding
)


@dataclass(frozen=True, slots=True)
class EconomicEvent:
    id: str
    account_id: AccountId
    occurred_at: datetime
    source_hash: DataHash
    config_hash: ConfigHash
    payload: Payload

    def __post_init__(self) -> None:
        try:
            identity(self.id)
            identity(self.account_id)
            require_utc(self.occurred_at)
            _require_sha256_hex(self.source_hash, "source")
            _require_sha256_hex(self.config_hash, "config")
            p = self.payload
            if type(p) is Opening:
                identity(p.instrument_id)
                require_bounded_decimal(p.cash, "cash", nonnegative=True)
            elif type(p) is Reserve:
                if type(p.intent) is not OrderIntent:
                    deny()
                i = replace(p.intent)
                if i.asset_class is not AssetClass.EQUITY or i.order_type is not OrderType.LIMIT:
                    deny()
                for value in (i.id, i.account_id, i.instrument_id, i.strategy_version):
                    identity(value)
                require_bounded_decimal(i.quantity, "quantity", positive=True)
                if i.limit_price is None:
                    deny()
                require_bounded_decimal(i.limit_price, "limit", positive=True)
                require_bounded_decimal(p.fee_bound, "fees", nonnegative=True)
                require_bounded_decimal(p.reserved_risk, "risk", positive=True)
                identity(p.episode_id)
            elif type(p) is Bind:
                if type(p.order) is not BrokerOrder:
                    deny()
                b = replace(p.order)
                if b.state is not OrderState.SUBMITTED or b.filled_quantity != 0:
                    deny()
            elif type(p) is Execution:
                if type(p.event) is not OwnedOrderEvent:
                    deny()
                p.event.__post_init__()
                if p.event.occurred_at != self.occurred_at:
                    deny()
            elif type(p) is FinalFees:
                identity(p.order_id)
                require_bounded_decimal(p.total, "fee_total", nonnegative=True)
            elif type(p) is Settlement:
                identity(p.obligation_id)
                require_bounded_decimal(p.amount, "settlement")
            elif type(p) is Release:
                identity(p.order_id)
            elif type(p) is Complete:
                identity(p.episode_id)
            elif type(p) is Funding:
                require_bounded_decimal(p.amount, "funding")
            else:
                deny()
        except (ValueError, TypeError, AttributeError):
            deny()


@dataclass(frozen=True, slots=True)
class Allocation:
    reservation: Reserve
    order: BrokerOrder | None
    recorded_fees: Decimal
    fees_final: bool
    released: bool
    cash_hold: Decimal
    share_hold: Decimal


@dataclass(frozen=True, slots=True)
class Obligation:
    id: str
    order_id: OrderId
    amount: Decimal


@dataclass(frozen=True, slots=True)
class EconomicState:
    account_id: AccountId
    config_hash: ConfigHash
    position: Position
    settled_cash: Decimal
    book_cash: Decimal
    available_cash: Decimal
    orders: tuple[Allocation, ...]
    obligations: tuple[Obligation, ...]
    trial: TrialLossState
    event_count: int

    @property
    def source_qualified(self) -> Literal[False]:
        return False

    @property
    def cost_qualified(self) -> Literal[False]:
        return False

    @property
    def execution_enabled(self) -> Literal[False]:
        return False

    @property
    def evidence_promotable(self) -> Literal[False]:
        return False
