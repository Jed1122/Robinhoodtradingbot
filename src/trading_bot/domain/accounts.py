"""Immutable broker-neutral account and portfolio records."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import (
    DomainValidationError,
    _require_decimal,
    _require_nonempty,
    _require_sha256_hex,
    _require_tuple,
)
from trading_bot.domain.enums import AssetClass
from trading_bot.domain.identifiers import AccountId, DataHash, InstrumentId


@dataclass(frozen=True, slots=True)
class AssetBuyingPower:
    asset_class: AssetClass
    amount: Decimal

    def __post_init__(self) -> None:
        _require_decimal(self.amount, "amount", nonnegative=True)


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    account_id: AccountId
    provider_state: str
    equity: Decimal
    cash: Decimal
    buying_power: tuple[AssetBuyingPower, ...]
    restricted: bool
    observed_at: datetime
    data_hash: DataHash

    def __post_init__(self) -> None:
        _require_nonempty(self.account_id, "account_id")
        _require_nonempty(self.provider_state, "provider_state")
        _require_decimal(self.equity, "equity", nonnegative=True)
        _require_decimal(self.cash, "cash", nonnegative=True)
        _require_tuple(self.buying_power, "buying_power")
        if any(not isinstance(item, AssetBuyingPower) for item in self.buying_power):
            raise DomainValidationError("buying_power must contain AssetBuyingPower records")
        require_utc(self.observed_at)
        _require_sha256_hex(self.data_hash, "data_hash")

    def buying_power_for(self, asset_class: AssetClass) -> Decimal:
        matches = tuple(
            item.amount for item in self.buying_power if item.asset_class is asset_class
        )
        if len(matches) != 1:
            raise DomainValidationError(
                "exactly one asset-class buying-power value is required"
            )
        return matches[0]


@dataclass(frozen=True, slots=True)
class Position:
    account_id: AccountId
    instrument_id: InstrumentId
    asset_class: AssetClass
    quantity: Decimal
    average_price: Decimal | None
    market_value: Decimal
    observed_at: datetime
    data_hash: DataHash

    def __post_init__(self) -> None:
        _require_nonempty(self.account_id, "account_id")
        _require_nonempty(self.instrument_id, "instrument_id")
        _require_decimal(self.quantity, "quantity", nonnegative=True)
        if self.average_price is not None:
            _require_decimal(self.average_price, "average_price", positive=True)
        _require_decimal(self.market_value, "market_value", nonnegative=True)
        require_utc(self.observed_at)
        _require_sha256_hex(self.data_hash, "data_hash")


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    account_id: AccountId
    positions: tuple[Position, ...]
    cash: Decimal
    equity: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal
    crypto_exposure: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    observed_at: datetime
    data_hash: DataHash

    def __post_init__(self) -> None:
        _require_nonempty(self.account_id, "account_id")
        _require_tuple(self.positions, "positions")
        if any(not isinstance(position, Position) for position in self.positions):
            raise DomainValidationError("positions must contain Position records")
        if any(position.account_id != self.account_id for position in self.positions):
            raise DomainValidationError("every position must match the portfolio account")
        _require_decimal(self.cash, "cash", nonnegative=True)
        _require_decimal(self.equity, "equity", nonnegative=True)
        _require_decimal(self.gross_exposure, "gross_exposure", nonnegative=True)
        _require_decimal(self.net_exposure, "net_exposure")
        _require_decimal(self.crypto_exposure, "crypto_exposure", nonnegative=True)
        _require_decimal(self.realized_pnl, "realized_pnl")
        _require_decimal(self.unrealized_pnl, "unrealized_pnl")
        if abs(self.net_exposure) > self.gross_exposure:
            raise DomainValidationError("absolute net exposure cannot exceed gross exposure")
        if self.crypto_exposure > self.gross_exposure:
            raise DomainValidationError("crypto exposure cannot exceed gross exposure")
        require_utc(self.observed_at)
        _require_sha256_hex(self.data_hash, "data_hash")
