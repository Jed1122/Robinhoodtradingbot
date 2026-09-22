"""Normalized options observations, not a broker parser or execution capability.

Missing provider sections must remain incomplete. Signed holdings deliberately allow
short options and shares so an unexpected liability can be represented and halted.
Financial inconsistencies are reconciliation incidents, not values to silently repair.
"""

from dataclasses import dataclass, fields
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.domain import AccountId, OrderState, Side
from trading_bot.domain.decimal_utils import (
    DomainValidationError,
    _require_exact_bool,
    _require_exact_enum,
    _require_nonempty,
    _require_nonnegative_int,
    _require_sha256_hex,
    _require_tuple,
    require_bounded_decimal,
)
from trading_bot.domain.options import OptionContract, OptionStructure, PositionEffect


def observation_id(value: str) -> None:
    _require_nonempty(value, "observation identity")
    if len(value) > 255 or any(ord(char) < 32 for char in value):
        raise DomainValidationError("invalid observation identity")


def observation_rows(value: tuple[object, ...], kind: type) -> None:
    _require_tuple(value, "observation rows")
    # Format/resource ceiling, not a strategy threshold. Callers may impose less.
    if len(value) > 10_000 or any(type(row) is not kind for row in value):
        raise DomainValidationError("invalid or oversized observation rows")


def _positive(value: int) -> None:
    _require_nonnegative_int(value, "quantity")
    if value == 0:
        raise DomainValidationError("quantity must be positive")


class OptionsSnapshotSection(StrEnum):
    CASH = "cash"
    CONTRACTS = "contracts"
    POSITIONS = "positions"
    ORDERS = "orders"
    FILLS = "fills"
    SHARES = "shares"
    SETTLEMENTS = "settlements"
    LIFECYCLE = "lifecycle"


class OptionLifecycleKind(StrEnum):
    EXERCISE = "exercise"
    ASSIGNMENT = "assignment"
    EXPIRATION = "expiration"
    BROKER_CLOSEOUT = "broker_closeout"


@dataclass(frozen=True, slots=True)
class OptionsCash:
    equity: Decimal
    settled_cash: Decimal
    buying_power: Decimal
    collateral: Decimal
    reserved_cash: Decimal
    unsettled_receivable: Decimal
    unsettled_payable: Decimal

    def __post_init__(self) -> None:
        for field in fields(self):
            require_bounded_decimal(getattr(self, field.name), field.name)


@dataclass(frozen=True, slots=True)
class ObservedOptionPosition:
    contract_id: str
    quantity: int
    cost_basis: Decimal
    broker_mark: Decimal | None
    pending_exercise: int
    pending_assignment: int
    pending_expiration: int

    def __post_init__(self) -> None:
        observation_id(self.contract_id)
        if type(self.quantity) is not int:
            raise DomainValidationError("signed option quantity must be an integer")
        require_bounded_decimal(self.cost_basis, "cost_basis")
        if self.broker_mark is not None:
            require_bounded_decimal(self.broker_mark, "broker_mark", nonnegative=True)
        for name in ("pending_exercise", "pending_assignment", "pending_expiration"):
            _require_nonnegative_int(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class ObservedOptionLeg:
    contract_id: str
    side: Side
    effect: PositionEffect
    ratio: int

    def __post_init__(self) -> None:
        observation_id(self.contract_id)
        _require_exact_enum(self.side, Side, "side")
        _require_exact_enum(self.effect, PositionEffect, "effect")
        _positive(self.ratio)


@dataclass(frozen=True, slots=True)
class ObservedOptionOrder:
    order_id: str
    legs: tuple[ObservedOptionLeg, ...]
    quantity: int
    filled_quantity: int
    limit_price: Decimal
    net_effect: Literal["debit", "credit"]
    state: OrderState
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        observation_id(self.order_id)
        observation_rows(self.legs, ObservedOptionLeg)
        if not self.legs or len(self.legs) > 4:
            raise DomainValidationError("one to four observed order legs required")
        _positive(self.quantity)
        _require_nonnegative_int(self.filled_quantity, "filled_quantity")
        require_bounded_decimal(self.limit_price, "limit_price", positive=True)
        if type(self.net_effect) is not str or self.net_effect not in ("debit", "credit"):
            raise DomainValidationError("explicit debit/credit required")
        _require_exact_enum(self.state, OrderState, "state")
        require_utc(self.created_at)
        require_utc(self.updated_at)
        if self.updated_at < self.created_at:
            raise DomainValidationError("order timestamps are inconsistent")


@dataclass(frozen=True, slots=True)
class ObservedOptionFill:
    fill_id: str
    order_id: str
    contract_id: str
    side: Side
    effect: PositionEffect
    quantity: int
    price: Decimal
    fee: Decimal
    occurred_at: datetime

    def __post_init__(self) -> None:
        for value in (self.fill_id, self.order_id, self.contract_id):
            observation_id(value)
        _require_exact_enum(self.side, Side, "side")
        _require_exact_enum(self.effect, PositionEffect, "effect")
        _positive(self.quantity)
        require_bounded_decimal(self.price, "price", nonnegative=True)
        require_bounded_decimal(self.fee, "fee", nonnegative=True)
        require_utc(self.occurred_at)


@dataclass(frozen=True, slots=True)
class ObservedSharePosition:
    symbol: str
    quantity: Decimal

    def __post_init__(self) -> None:
        observation_id(self.symbol)
        require_bounded_decimal(self.quantity, "share quantity")


@dataclass(frozen=True, slots=True)
class ObservedOptionSettlement:
    settlement_id: str
    contract_id: str
    amount: Decimal  # Signed receivable (+) or payable (-), not premium per share.
    due_at: datetime
    completed: bool

    def __post_init__(self) -> None:
        observation_id(self.settlement_id)
        observation_id(self.contract_id)
        require_bounded_decimal(self.amount, "settlement amount")
        require_utc(self.due_at)
        _require_exact_bool(self.completed, "completed")


@dataclass(frozen=True, slots=True)
class ObservedOptionLifecycle:
    event_id: str
    contract_id: str
    kind: OptionLifecycleKind
    quantity: int
    cash_delta: Decimal
    occurred_at: datetime

    def __post_init__(self) -> None:
        observation_id(self.event_id)
        observation_id(self.contract_id)
        _require_exact_enum(self.kind, OptionLifecycleKind, "lifecycle kind")
        _positive(self.quantity)
        require_bounded_decimal(self.cash_delta, "cash_delta")
        require_utc(self.occurred_at)


@dataclass(frozen=True, slots=True)
class OwnedOptionPosition:
    position_id: str
    structure: OptionStructure
    units: int

    def __post_init__(self) -> None:
        observation_id(self.position_id)
        if type(self.structure) is not OptionStructure:
            raise DomainValidationError("exact owned structure required")
        _positive(self.units)
        if any(leg.effect is not PositionEffect.OPEN for leg in self.structure.legs):
            raise DomainValidationError("ownership describes opening structure sides")


@dataclass(frozen=True, slots=True)
class OptionsAccountSnapshot:
    account_id: AccountId
    history_start: datetime
    observed_at: datetime
    data_hash: str
    complete_sections: tuple[OptionsSnapshotSection, ...]
    cash: OptionsCash
    contracts: tuple[OptionContract, ...]
    positions: tuple[ObservedOptionPosition, ...]
    orders: tuple[ObservedOptionOrder, ...]
    fills: tuple[ObservedOptionFill, ...]
    shares: tuple[ObservedSharePosition, ...]
    settlements: tuple[ObservedOptionSettlement, ...]
    lifecycle: tuple[ObservedOptionLifecycle, ...]

    def __post_init__(self) -> None:
        observation_id(self.account_id)
        require_utc(self.history_start)
        require_utc(self.observed_at)
        if self.history_start > self.observed_at:
            raise DomainValidationError("snapshot history cannot begin in its future")
        _require_sha256_hex(self.data_hash, "data_hash")
        observation_rows(self.complete_sections, OptionsSnapshotSection)
        if len(set(self.complete_sections)) != len(self.complete_sections):
            raise DomainValidationError("duplicate section claims")
        if type(self.cash) is not OptionsCash:
            raise DomainValidationError("exact cash observation required")
        for name, kind in (
            ("contracts", OptionContract),
            ("positions", ObservedOptionPosition),
            ("orders", ObservedOptionOrder),
            ("fills", ObservedOptionFill),
            ("shares", ObservedSharePosition),
            ("settlements", ObservedOptionSettlement),
            ("lifecycle", ObservedOptionLifecycle),
        ):
            observation_rows(getattr(self, name), kind)
