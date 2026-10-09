"""Declared offline action inputs, not authenticated brokerage/source evidence."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from trading_bot.domain import require_bounded_decimal
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.simulation.events import EventCursor
from trading_bot.simulation.lifecycle_models import validate_cursor


@dataclass(frozen=True, slots=True)
class CapitalActionIdentity:
    event_id: str
    cursor: EventCursor
    account_id: str
    opening_order_id: str
    symbol: str
    execution_enabled: bool = field(default=False, init=False)
    source_qualified: bool = field(default=False, init=False)
    evidence_promotable: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        validate_cursor(self.cursor)
        for value in (self.event_id, self.account_id, self.opening_order_id):
            _identifier(value)
        if (
            type(self.symbol) is not str
            or self.symbol not in ("SPY", "QQQ", "IWM", "SHY", "IEF")
            or self.execution_enabled is not False
            or self.source_qualified is not False
            or self.evidence_promotable is not False
        ):
            raise ValueError("capital_action_invalid")


def _identifier(value: str) -> None:
    if type(value) is not str or not value.strip() or not 0 < len(value) <= 256:
        raise ValueError("capital_action_invalid")


@dataclass(frozen=True, slots=True)
class CapitalSplitApplied(CapitalActionIdentity):
    action_id: str
    record_hash: str
    ratio: Decimal
    post_action_mark: Decimal

    def __post_init__(self) -> None:
        CapitalActionIdentity.__post_init__(self)
        _identifier(self.action_id)
        _require_sha256_hex(self.record_hash, "action_record")
        require_bounded_decimal(self.ratio, "ratio", positive=True)
        require_bounded_decimal(self.post_action_mark, "post_action_mark", positive=True)


@dataclass(frozen=True, slots=True)
class CapitalDistributionEntitled(CapitalActionIdentity):
    action_id: str
    record_hash: str
    amount_per_share: Decimal
    ex_mark: Decimal
    pay_date: date

    def __post_init__(self) -> None:
        CapitalActionIdentity.__post_init__(self)
        _identifier(self.action_id)
        _require_sha256_hex(self.record_hash, "action_record")
        require_bounded_decimal(self.amount_per_share, "amount_per_share", nonnegative=True)
        require_bounded_decimal(self.ex_mark, "ex_mark", positive=True)
        if type(
            self.pay_date
        ) is not date or not self.cursor.occurred_at.date() <= self.pay_date <= date(2100, 12, 31):
            raise ValueError("capital_action_invalid")


@dataclass(frozen=True, slots=True)
class CapitalDistributionPaid(CapitalActionIdentity):
    entitlement_id: str
    amount: Decimal

    def __post_init__(self) -> None:
        CapitalActionIdentity.__post_init__(self)
        _identifier(self.entitlement_id)
        require_bounded_decimal(self.amount, "distribution_payment", nonnegative=True)


type CapitalActionEvent = (
    CapitalSplitApplied | CapitalDistributionEntitled | CapitalDistributionPaid
)
